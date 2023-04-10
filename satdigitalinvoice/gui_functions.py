import logging
import os
from datetime import datetime, date
from decimal import Decimal

import xlsxwriter
from babel.dates import format_date
from markdown2 import markdown
from satcfdi import DatePeriod
from satcfdi.accounting import filter_invoices_iter, filter_payments_iter, invoices_export, payments_export, SatCFDI
from satcfdi.create.cfd import cfdi40
from satcfdi.create.cfd.cfdi40 import Comprobante, PagoComprobante
from satcfdi.pacs import sat
# noinspection PyUnresolvedReferences
from satcfdi.transform.catalog import CATALOGS
from tabulate import tabulate
from weasyprint import HTML, CSS
from xlsxwriter.exceptions import FileCreateError

from . import SOURCE_DIRECTORY, PPD
from .environments import facturacion_environment
from .file_data_managers import ClientsManager, FacturasManager
from .formatting_functions.common import fecha, pesos, porcentaje
from .log_tools import print_yaml
from .utils import clear_directory, find_best_match, months_between, add_month

logger = logging.getLogger(__name__)
logger.level = logging.INFO

sat_manager = sat.SAT()

PERIODOS = {
    "Mensual": 1,
    "Bimestral": 2,
    "Trimestral": 3,
    "Cuatrimestral": 4,
    "Semestral": 6,
    "Anual": 12
}


def create_cfdi(receptor_cif, factura_details, serie, folio, csd_sginer, emisor_cif):
    emisor = cfdi40.Emisor(
        rfc=emisor_cif['Rfc'],
        nombre=emisor_cif['RazonSocial'],
        regimen_fiscal=emisor_cif['RegimenFiscal']
    )
    emisor = emisor | factura_details.get('Emisor', {})
    invoice = cfdi40.Comprobante(
        emisor=emisor,
        lugar_expedicion=emisor_cif['CodigoPostal'],
        receptor=cfdi40.Receptor(
            rfc=factura_details['Receptor'],
            nombre=receptor_cif['RazonSocial'],
            uso_cfdi=factura_details['UsoCFDI'],
            domicilio_fiscal_receptor=receptor_cif['CodigoPostal'],
            regimen_fiscal_receptor=receptor_cif['RegimenFiscal']
        ),
        metodo_pago=factura_details['MetodoPago'],
        forma_pago=factura_details['FormaPago'],
        serie=serie,
        folio=folio,
        conceptos=factura_details["Conceptos"]
    )
    invoice.sign(csd_sginer)
    invoice = invoice.process()

    expected_total = factura_details.get('Total')
    if expected_total is not None:
        if expected_total != invoice['Total']:
            logger.info(f"{factura_details['Receptor']}: Total '{expected_total}' is invalid, expected '{invoice['Total']}'")
            return None

    return invoice


def parse_periodo_mes_ajuste(periodo_mes_ajuste: str):
    parts = periodo_mes_ajuste.split(".")
    if len(parts) != 2:
        raise ValueError("Periodo Invalido")

    periodo, mes_ajuste = parts
    if not mes_ajuste.isnumeric():
        raise ValueError("Periodo Invalido")

    mes_ajuste = int(mes_ajuste)
    if not (12 >= int(mes_ajuste) >= 1):
        raise ValueError("Periodo Invalido")

    if periodo not in PERIODOS:
        raise ValueError("Periodo Invalido")

    return periodo, mes_ajuste


def format_concepto_desc(concepto, periodo):
    concepto = concepto.copy()
    template = facturacion_environment.from_string(concepto["Descripcion"])
    concepto["Descripcion"] = template.render(
        periodo=periodo
    )
    return concepto


def validad_facturas(clients, facturas):
    is_valid = True
    for factura_details in facturas:
        cliente = clients.get(factura_details['Receptor'])
        if not cliente:
            logger.info(f"{factura_details['Receptor']}: client not found")
            is_valid = False

        for c in factura_details["Conceptos"]:
            periodo_mes_ajuste = c.get("_periodo_mes_ajuste", "")
            try:
                parse_periodo_mes_ajuste(periodo_mes_ajuste)
            except ValueError:
                logger.info(f"{factura_details['Receptor']}: _periodo_mes_ajuste '{periodo_mes_ajuste}' is invalid")
                is_valid = False

        if factura_details["MetodoPago"] == "PPD" and factura_details["FormaPago"] != "99":
            logger.info(f"{factura_details['Receptor']}: FormaPago '{factura_details['FormaPago']}' is invalid, expected '99' for PPD")
            is_valid = False

    return is_valid


def year_month_desc(year, month):
    return format_date(date(year=year, month=month, day=1), locale='es_MX', format="'Mes de' MMMM 'del' y").upper()


def periodo_desc(ym_date, periodo_mes_ajuste):
    periodo, mes_ajuste = parse_periodo_mes_ajuste(periodo_mes_ajuste)
    periodo_meses = PERIODOS[periodo]

    if (ym_date.month - mes_ajuste) % periodo_meses == 0:
        periodo = year_month_desc(ym_date.year, ym_date.month)
        if periodo_meses > 1:
            mes_final = (ym_date.month + periodo_meses - 2) % 12 + 1
            periodo += " AL " + year_month_desc(
                year=ym_date.year + int(mes_final < ym_date.month),
                month=mes_final
            )

        return periodo
    return None


def generate_ingresos(folio, serie, clients, facturas, ym_date, csd_signer):
    if not validad_facturas(clients, facturas):
        return

    emisor_cif = clients[csd_signer.rfc]

    def prepare_concepto(concepto):
        periodo = periodo_desc(ym_date, concepto['_periodo_mes_ajuste'])
        if periodo and concepto['ValorUnitario'] is not None:
            return format_concepto_desc(concepto, periodo=periodo)

    def facturas_iter():
        i = 0
        for f in facturas:
            receptor_cif = clients[f['Receptor']]
            conceptos = [x for x in (prepare_concepto(c) for c in f["Conceptos"]) if x]
            if conceptos:
                f["Conceptos"] = conceptos
                yield create_cfdi(receptor_cif, f, serie, str(folio + i), csd_signer, emisor_cif)
                i += 1

    cfdis = [i for i in facturas_iter()]

    if None in cfdis:
        return

    return cfdis


def parse_fecha_pago(fecha_pago):
    if not fecha_pago:
        logger.info("Fecha de Pago esta vacia")
        return

    fecha_pago = datetime.fromisoformat(fecha_pago)
    if fecha_pago > datetime.now():
        logger.info("Fecha de Pago esta en el futuro")
        return

    if fecha_pago.replace(hour=12) > datetime.now():
        fecha_pago = datetime.now()
    else:
        fecha_pago = fecha_pago.replace(hour=12)

    dif = datetime.now() - fecha_pago
    if dif.days > 30:
        logger.info("!!! FECHA DE PAGO ES MAYOR A 30 DIAS !!!")

    return fecha_pago


def pago_factura(serie, folio, factura_pagar, fecha_pago, importe_pago, forma_pago, csd_signer):
    if not (fecha_pago := parse_fecha_pago(fecha_pago)):
        return

    c = factura_pagar

    if importe_pago:
        importe_pago = round(Decimal(importe_pago), 2)
    else:
        importe_pago = c.saldo_pendiente

    invoice = Comprobante.pago_comprobantes(
        comprobantes=[
            PagoComprobante(
                comprobante=c,
                num_parcialidad=c.ultima_num_parcialidad + 1,
                imp_saldo_ant=c.saldo_pendiente,
                imp_pagado=importe_pago
            )
        ],
        fecha_pago=fecha_pago,
        forma_pago=forma_pago,
        serie=serie,
        folio=str(folio),
    )
    invoice.sign(csd_signer)
    return invoice.process()


def find_ajustes(facturas, mes_ajuste):
    for f in facturas:
        rfc = f["Receptor"]
        for concepto in f["Conceptos"]:
            _, mes_aj = parse_periodo_mes_ajuste(concepto['_periodo_mes_ajuste'])
            if mes_aj == mes_ajuste:
                yield rfc, concepto


def facturas_folder(dp: DatePeriod):
    if dp.month:
        return f"facturas/{dp.year}/{dp}"
    return f"facturas/{dp.year}/{dp}"


def facturas_filename(dp: DatePeriod, ext="xlsx"):
    return os.path.join(facturas_folder(dp), f"{dp}.{ext}")


def exportar_facturas(all_invoices, dp: DatePeriod, emisor_cif, rfc_prediales):
    emisor_rfc = emisor_cif['Rfc']
    emisor_regimen = emisor_cif['RegimenFiscal']

    emitidas = filter_invoices_iter(invoices=all_invoices.values(), fecha=dp, rfc_emisor=emisor_rfc)
    emitidas_pagos = filter_payments_iter(invoices=all_invoices, fecha=dp, rfc_emisor=emisor_rfc)

    recibidas = filter_invoices_iter(invoices=all_invoices.values(), fecha=dp, rfc_receptor=emisor_rfc)
    recibidas_pagos = filter_payments_iter(invoices=all_invoices, fecha=dp, rfc_receptor=emisor_rfc)

    recibidas_pagos = list(recibidas_pagos)
    pagos_hechos_iva = [
        p
        for p in recibidas_pagos
        if sum(x.get("Importe", 0) for x in p.impuestos.get("Traslados", {}).values()) > 0
           and p.comprobante["Receptor"].get("RegimenFiscalReceptor") in (emisor_regimen, None)
    ]
    prediales = [p for p in recibidas_pagos if p.comprobante["Emisor"]["Rfc"] in rfc_prediales]

    archivo_excel = facturas_filename(dp)
    os.makedirs(os.path.dirname(archivo_excel), exist_ok=True)

    workbook = xlsxwriter.Workbook(archivo_excel)
    # EMITIDAS
    invoices_export(workbook, "EMITIDAS", emitidas)
    payments_export(workbook, "EMITIDAS PAGOS", emitidas_pagos)

    # RECIBIDAS
    invoices_export(workbook, "RECIBIDAS", recibidas)
    payments_export(workbook, "RECIBIDAS PAGOS", recibidas_pagos)

    # SPECIALES
    payments_export(workbook, f"RECIBIDAS PAGOS IVA {emisor_regimen.code}", pagos_hechos_iva)
    if prediales:
        payments_export(workbook, "PREDIALES", prediales)

    try:
        workbook.close()
        print(f"Archivo {archivo_excel} creado")
    except FileCreateError:
        print(f"No se pudo crear el archivo {archivo_excel}")


def generate_pdf_template(template_name, fields):
    increment_template = facturacion_environment.get_template(template_name)
    md5_document = increment_template.render(
        fields
    )
    html = markdown(md5_document)
    pdf = HTML(string=html).write_pdf(
        target=None,
        stylesheets=[
            os.path.join(SOURCE_DIRECTORY, "markdown_styles", "markdown6.css"),
            CSS(
                string='@page { width: Letter; margin: 1.6cm 1.6cm 1.6cm 1.6cm; }'
            )
        ]
    )
    return pdf


def generate_html_template(template_name, fields):
    increment_template = facturacion_environment.get_template(template_name)
    render = increment_template.render(
        fields
    )
    return render


def mf_pago_fmt(cfdi):
    i = cfdi
    if i['TipoDeComprobante'] == "I":
        return i['TipoDeComprobante'].code + ' ' + i['MetodoPago'].code + ' ' + (i['FormaPago'].code if i['FormaPago'].code != '99' else '')
    return i['TipoDeComprobante'].code


def print_invoices(invoices):
    print(
        tabulate(
            invoices,
            headers=(
                '',
                'Receptor Razon Social',
                'Recep. Rfc',
                'Factura',
                "Fecha",
                "Total",
                "Pagada",
                "Tipo",
                "Folio Fiscal",
                "🛈"
            ),
            disable_numparse=True,
            colalign=("right", "left", "left", "left", "left", "right", "right", "left", "left", "left")
        )
    )


def print_cfdis(cfdis, start):
    print(
        tabulate(
            [
                [
                    i,
                    cfdi['Emisor']['RegimenFiscal'].code,
                    cfdi['Receptor']['Nombre'][0:36],
                    cfdi['Receptor']['Rfc'],
                    cfdi.get('Serie', '') + cfdi.get('Folio', ''),
                    mf_pago_fmt(cfdi),
                    cfdi['SubTotal'],
                    cfdi['Total'],
                ]
                for i, cfdi in enumerate(cfdis, start=start)
            ],
            floatfmt=".2f",
            headers=(
                '',
                'EReg',
                'Receptor Razon Social',
                'Recep. Rfc',
                'Factura',
                "Tipo",
                "Subtotal",
                "Total",
            ),
            disable_numparse=True,
            colalign=("right", "left", "left", "left", "left", "left", "right", "right")
        )
    )


def print_cfdi_details(cfdi):
    i = cfdi
    if i["TipoDeComprobante"] == "P":
        pagos = i["Complemento"]["Pagos"]["Pago"]
        print_yaml({
            "Pago": [{
                "FechaPago": p["FechaPago"],
                "FormaDePagoP": p["FormaDePagoP"],
                "Monto": p["Monto"],
                "DoctoRelacionado": [{
                    "Factura": d.get("Serie", "") + d.get("Folio", ""),
                    "IdDocumento": d.get("IdDocumento"),
                    "NumParcialidad": d.get("NumParcialidad"),
                    "ImpSaldoAnt": d.get("ImpSaldoAnt"),
                    "ImpPagado": d.get("ImpPagado"),
                    "ImpSaldoInsoluto": d.get("ImpSaldoInsoluto"),
                } for d in p["DoctoRelacionado"]]
            } for p in pagos]
        })
    else:
        if isinstance(cfdi, SatCFDI) and cfdi.get("MetodoPago") == PPD:
            print_yaml({
                "Conceptos": [x['Descripcion'] for x in i["Conceptos"]],
                "Pendiente": cfdi.saldo_pendiente,
                "Pagos": [f"{c.comprobante.name} - {c.comprobante.uuid}" for c in cfdi.payments if c.comprobante.estatus != '0']
            })
        else:
            print_yaml({
                "Conceptos": [x['Descripcion'] for x in i["Conceptos"]]
            })


def ajustes_directory(ym_date):
    return os.path.join(facturas_folder(DatePeriod(year=ym_date.year, month=ym_date.month)), 'ajustes')


def ajustes(emisor_rfc, ym_date):
    ym_date_effective = add_month(ym_date)

    # clear directory
    ajustes_dir = ajustes_directory(ym_date)
    clear_directory(ajustes_dir)

    clients = ClientsManager()
    facturas = FacturasManager(None)["Facturas"]

    def ajustes_iter():
        for i, (rfc, concepto) in enumerate(find_ajustes(facturas, ym_date_effective.month)):
            receptor = clients[rfc]
            valor_unitario_raw = concepto["ValorUnitario"]

            if isinstance(valor_unitario_raw, dict):
                vud, vu = find_best_match(valor_unitario_raw, ym_date)
                vund, vun = find_best_match(valor_unitario_raw, ym_date_effective)
                meses = months_between(vund, vud)
                ajuste_porcentaje = (vun / vu - 1)
            else:
                vu = valor_unitario_raw
                vun = None
                meses = None
                ajuste_porcentaje = None

            concepto = format_concepto_desc(concepto, periodo="INMUEBLE")
            file_name = os.path.join(ajustes_dir, f'AjusteRenta_{rfc}_{i}.pdf')

            data = {
                "receptor": receptor,
                "emisor": clients[emisor_rfc],
                "concepto": concepto,
                "valor_unitario": pesos(vu),
                "valor_unitario_nuevo": pesos(vun) if vun else "",
                "ajuste_porcentaje": porcentaje(ajuste_porcentaje, 2) if ajuste_porcentaje is not None else "",
                "ajuste_periodo": f"{meses} MESES",
                "ajuste_efectivo_al": fecha(ym_date_effective),
                "periodo": concepto['_periodo_mes_ajuste'].split('.')[0].upper(),
                "fecha_hoy": fecha(date.today()),
                'file_name': file_name
            }
            if ajuste_porcentaje is not None:
                res = generate_pdf_template(
                    template_name='incremento_template.md',
                    fields=data
                )
                with open(file_name, 'wb') as f:
                    f.write(res)
            yield data

    ajustes_iter = list(ajustes_iter())
    print("Ajuste Efectivo Al:", fecha(ym_date_effective))
    if ajustes_iter:
        print(
            tabulate(
                [
                    [
                        i,
                        ajuste["receptor"]["RazonSocial"][:36],
                        ajuste["receptor"]["Rfc"],
                        ajuste["valor_unitario"].split(' ')[0],
                        ajuste["valor_unitario_nuevo"].split(' ')[0],
                        ajuste["ajuste_porcentaje"].split(' ')[0],
                        ajuste["periodo"],
                        ajuste["ajuste_periodo"],
                    ]
                    for i, ajuste in enumerate(ajustes_iter, start=1)
                ],
                headers=(
                    "",
                    "Receptor Razon Social",
                    "Recep. Rfc",
                    "Actual",
                    "Nuevo",
                    "Ajuste %",
                    "Periodo",
                    "Ajuste Periodo",
                ),
                disable_numparse=True,
                colalign=("right", "left", "left", "right", "right", "right", "left", "left"),
            )
        )
    else:
        print("No hay ajustes para este mes")
