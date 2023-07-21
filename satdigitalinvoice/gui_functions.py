import logging
import os
from datetime import datetime, date
from decimal import Decimal
from decimal import InvalidOperation

import xlsxwriter
from markdown2 import markdown
from satcfdi.accounting import filter_invoices_iter, filter_payments_iter, invoices_export, payments_export
from satcfdi.accounting.process import payments_groupby_receptor, payments_retentions_export
from satcfdi.create.cfd import cfdi40
from satcfdi.create.cfd.cfdi40 import Comprobante, PagoComprobante
from satcfdi.models import DatePeriod
from satcfdi.pacs import sat
from satcfdi.printer import Representable
from weasyprint import HTML, CSS

from . import SOURCE_DIRECTORY, ARCHIVOS_DIRECTORY, TEMP_DIRECTORY
from .environments import facturacion_environment
from .exceptions import ConsoleErrors
from .formatting_functions.common import fecha_mes
from .utils import add_month, find_best_match, months_between, open_file

logger = logging.getLogger(__name__)
logger.level = logging.INFO

sat_manager = sat.SAT()

PERIODICIDAD = {
    "Mensual": 1,
    "Bimestral": 2,
    "Trimestral": 3,
    "Cuatrimestral": 4,
    "Semestral": 6,
    "Anual": 12
}
CALENDAR_FECHA_FMT = '%Y-%m-%d'


def create_cfdi(receptor_cif, factura_details, emisor_cif):
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
        # cfdi_relacionados=[
        #     cfdi40.CfdiRelacionados(
        #         tipo_relacion=TipoRelacion.SUSTITUCION_DE_LOS_CFDI_PREVIOSaaaaaaa,
        #         cfdi_relacionado=''xyc',
        #     )
        # ],
        # serie=serie,
        # folio=folio,
        conceptos=factura_details["Conceptos"]
    )
    invoice = invoice.process()
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

    if periodo not in PERIODICIDAD:
        raise ValueError("Periodo Invalido")

    return PERIODICIDAD[periodo], mes_ajuste


def format_concepto_desc(concepto, periodo):
    concepto = concepto.copy()
    template = facturacion_environment.from_string(concepto["Descripcion"])
    concepto["Descripcion"] = template.render(
        periodo=periodo
    )
    return concepto


def period_desc(dp: DatePeriod):
    return fecha_mes(date(year=dp.year, month=dp.month, day=1))


def periodicidad_desc(dp: DatePeriod, periodo_mes_ajuste, offset):
    periodo_meses, mes_ajuste = parse_periodo_mes_ajuste(periodo_mes_ajuste)

    if (dp.month - mes_ajuste) % periodo_meses == 0:
        if offset:
            dp = add_month(dp, offset)

        periodo = period_desc(dp)
        if periodo_meses > 1:
            periodo += " AL " + period_desc(
                dp=add_month(dp, periodo_meses - 1)
            )

        return periodo
    return None


def generate_ingresos(clients, facturas, dp, emisor_rfc):
    emisor_cif = clients[emisor_rfc]
    errors = []

    def facturas_iter():
        for i, f in enumerate(facturas, start=1):
            try:
                def prepare_concepto(c):
                    periodo = periodicidad_desc(
                        dp,
                        c['_periodo_mes_ajuste'],
                        c.get('_desfase_mes')
                    )
                    if periodo and c['ValorUnitario'] is not None:
                        return format_concepto_desc(c, periodo=periodo)

                receptor_cif = clients.get(f['Receptor'])
                if not receptor_cif:
                    raise ValueError("client not found")

                if f["MetodoPago"] == "PPD" and f["FormaPago"] != "99":
                    raise ValueError(f"FormaPago '{f['FormaPago']}' is invalid, expected '99' for PPD")

                if conceptos := [x for x in (prepare_concepto(c) for c in f["Conceptos"]) if x]:
                    f["Conceptos"] = conceptos
                    cfdi = create_cfdi(receptor_cif, f, emisor_cif)

                    expected_total = f.get('Total')
                    if expected_total is not None and expected_total != cfdi['Total']:
                        raise ValueError(f"Total '{expected_total}' is invalid, expected '{cfdi['Total']}'")

                    yield cfdi
            except Exception as e:
                errors.append(f"{i} {f['Receptor']}: {str(e)}")

    cfdis = list(facturas_iter())
    if errors:
        raise ConsoleErrors("Generar Facturas Errores", errors=errors)
    return cfdis


def parse_fecha_pago(fecha_pago):
    if not fecha_pago:
        raise ValueError("Fecha de Pago es requerida")

    fecha_pago = datetime.strptime(fecha_pago, CALENDAR_FECHA_FMT)
    if fecha_pago > datetime.now():
        raise ValueError("Fecha de Pago es mayor a la fecha actual")

    if fecha_pago.replace(hour=12) > datetime.now():
        fecha_pago = datetime.now()
    else:
        fecha_pago = fecha_pago.replace(hour=12)

    return fecha_pago


def parse_importe_pago(importe_pago: str):
    try:
        return round(Decimal(importe_pago), 2)
    except InvalidOperation:
        raise ValueError("Importe de Pago es invalido")


def pago_factura(factura_pagar, fecha_pago: datetime, forma_pago: str, importe_pago: Decimal = None, serie_pago=None):
    c = factura_pagar
    invoice = Comprobante.pago_comprobantes(
        serie=serie_pago or None,
        folio=c.get('Folio') if serie_pago else None,
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
    )
    return invoice.process()


def find_ajustes(facturas, mes_ajuste):
    for f in facturas:
        rfc = f["Receptor"]
        for concepto in f["Conceptos"]:
            _, mes_aj = parse_periodo_mes_ajuste(concepto['_periodo_mes_ajuste'])
            if mes_aj == mes_ajuste:
                yield rfc, concepto


def generate_ajustes(clients, facturas, dp, dp_effective, emisor_rfc):
    errors = []
    ajustes_dir = os.path.join(archivos_folder(dp), 'ajustes')
    os.makedirs(ajustes_dir, exist_ok=True)

    def ajustes_iter():
        for i, (receptor_rfc, concepto) in enumerate(find_ajustes(facturas, dp_effective.month), start=1):
            try:
                valor_unitario_raw = concepto["ValorUnitario"]

                if isinstance(valor_unitario_raw, dict):
                    vu_eff, vu = find_best_match(valor_unitario_raw, dp)
                    vun_eff, vun = find_best_match(valor_unitario_raw, dp_effective)
                    if vu_eff == vun_eff:
                        vun = None
                        num_meses = None
                    else:
                        num_meses = months_between(vun_eff, vu_eff)

                    if vun and vu:
                        ajuste_porcentaje = round((vun / vu - 1) * 100, 2)
                    else:
                        ajuste_porcentaje = None
                else:
                    vu = valor_unitario_raw
                    vun = None
                    num_meses = None
                    ajuste_porcentaje = None

                concepto = format_concepto_desc(concepto, periodo="INMUEBLE")
                file_name = os.path.join(ajustes_dir, f'AjusteRenta_{receptor_rfc}_{i}.pdf')
                client_receptor = clients[receptor_rfc]  # type: dict
                data = {
                    "receptor": client_receptor,
                    "emisor": clients[emisor_rfc],
                    "concepto": concepto,
                    "valor_unitario": vu,
                    "valor_unitario_nuevo": vun or '',
                    "ajuste_porcentaje": ajuste_porcentaje or "",
                    "meses": num_meses or '',
                    "efectivo_periodo_desc": periodicidad_desc(dp_effective, concepto['_periodo_mes_ajuste'], concepto.get('_desfase_mes')),
                    "periodo": concepto['_periodo_mes_ajuste'].split('.')[0].upper(),
                }
                data['create_fn'] = create_ajuste_fn(ajuste_porcentaje, data, file_name)

                yield data
            except Exception as e:
                errors.append(f"{i} {receptor_rfc}: {str(e)}")

    cfdis = list(ajustes_iter())
    if errors:
        raise ConsoleErrors("Generar Ajustes Errores", errors=errors)
    return cfdis


def create_ajuste_fn(ajuste_porcentaje, data, file_name):
    def fn():
        if ajuste_porcentaje:
            res = generate_pdf_template(
                template_name='ajuste_template.md',
                fields=data
            )
            with open(file_name, 'wb') as f:
                f.write(res)
            return file_name
    return fn


def generar_depositos(clients, facturas, dp, emisor_rfc):
    errors = []
    depositos_dir = os.path.join(archivos_folder(dp), 'depositos')
    os.makedirs(depositos_dir, exist_ok=True)

    def depositos_iter():
        for i, (receptor_rfc, concepto) in enumerate(find_ajustes(facturas, dp.month), start=1):
            try:
                vu = concepto["ValorUnitario"]

                concepto = format_concepto_desc(concepto, periodo="INMUEBLE")
                file_name = os.path.join(depositos_dir, f'Deposito_{receptor_rfc}_{i}.pdf')

                client_receptor = clients[receptor_rfc]  # type: dict
                data = {
                    "receptor": client_receptor,
                    "emisor": clients[emisor_rfc],
                    "concepto": concepto,
                    "valor_unitario": vu,
                    "periodo": concepto['_periodo_mes_ajuste'].split('.')[0].upper(),
                }
                data['create_fn'] = create_deposito_fn(data, file_name)
                yield data
            except Exception as e:
                errors.append(f"{i} {receptor_rfc}: {str(e)}")

    cfdis = list(depositos_iter())
    if errors:
        raise ConsoleErrors("Generar Depositos Errores", errors=errors)
    return cfdis


def create_deposito_fn(data, file_name):
    def fn():
        res = generate_pdf_template(
            template_name='deposito_template.md',
            fields=data
        )
        with open(file_name, 'wb') as f:
            f.write(res)
        return file_name

    return fn


def archivos_folder(dp: DatePeriod):
    if dp.month:
        return os.path.join(ARCHIVOS_DIRECTORY, str(dp.year), str(dp.year) + "-{:02d}".format(dp.month))
    return os.path.join(ARCHIVOS_DIRECTORY, str(dp.year))


def archivos_filename(dp: DatePeriod, ext="xlsx"):
    return os.path.join(archivos_folder(dp), f"{dp}.{ext}")


def exportar_facturas(all_invoices, dp: DatePeriod, emisor_cif, rfc_prediales):
    emisor_rfc = emisor_cif['Rfc']
    emisor_regimen = emisor_cif['RegimenFiscal']

    emitidas = filter_invoices_iter(invoices=all_invoices.values(), fecha=dp, rfc_emisor=emisor_rfc)
    emitidas_pagos = filter_payments_iter(invoices=all_invoices, fecha=dp, rfc_emisor=emisor_rfc)
    emitidas_pagos = list(emitidas_pagos)

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

    archivo_excel = archivos_filename(dp)
    os.makedirs(os.path.dirname(archivo_excel), exist_ok=True)

    workbook = xlsxwriter.Workbook(archivo_excel)
    # EMITIDAS
    invoices_export(workbook, "EMITIDAS", emitidas)
    payments_export(workbook, "EMITIDAS PAGOS", emitidas_pagos)

    # RECIBIDAS
    invoices_export(workbook, "RECIBIDAS", recibidas)
    payments_export(workbook, "RECIBIDAS PAGOS", recibidas_pagos)

    # SPECIALES
    payments_export(workbook, f"RECIBIDAS PAGOS IVA {emisor_regimen}", pagos_hechos_iva)
    if prediales:
        payments_export(workbook, "PREDIALES", prediales)

    # RETENCIONES
    if dp.month is None:
        archivo_retenciones = archivos_filename(dp, ext="retenciones.txt")
        pagos_agrupados = payments_groupby_receptor(emitidas_pagos)
        payments_retentions_export(archivo_retenciones, pagos_agrupados)

    workbook.close()
    return archivo_excel


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


def mf_pago_fmt(cfdi):
    i = cfdi
    if i['TipoDeComprobante'] == "I":
        return i['TipoDeComprobante'].code + ' ' + i['MetodoPago'].code + ' ' + (i['FormaPago'].code if i['FormaPago'].code != '99' else '  ')
    return i['TipoDeComprobante'].code + '       '


def preview_cfdis(cfdis):
    outfile = os.path.join(TEMP_DIRECTORY, "factura.html")
    Representable.html_write_all(
        objs=cfdis,
        target=outfile,
    )
    open_file(
        os.path.abspath(outfile)
    )


def center_location(element) -> tuple[int, int]:
    return tuple((c + s // 3) for c, s in zip(element.current_location(), element.size))
