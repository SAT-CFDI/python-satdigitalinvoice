import copy
import logging
import os
import shutil
from datetime import datetime, date
from decimal import Decimal
from decimal import InvalidOperation
from itertools import groupby

import xlsxwriter
from markdown2 import markdown
from satcfdi import render
from satcfdi.accounting import filter_invoices_iter, filter_payments_iter, invoices_export, payments_export
from satcfdi.accounting.process import payments_groupby_receptor, payments_retentions_export
from satcfdi.create.cfd import cfdi40
from satcfdi.create.cfd.catalogos import Impuesto
from satcfdi.create.cfd.cfdi40 import Comprobante, PagoComprobante
from satcfdi.diot import DIOT, DatosIdentificacion, Periodo, ProveedorTercero, TipoTercero, TipoOperacion
from satcfdi.models import DatePeriod
from satcfdi.pacs import sat

try:
    from weasyprint import HTML, CSS
except:
    pass

from . import SOURCE_DIRECTORY, ARCHIVOS_DIRECTORY, TEMP_DIRECTORY
from .environments import facturacion_environment
from .exceptions import ConsoleErrors
from .formatting_functions.common import fecha_mes, get_month_name
from .log_tools import to_yaml
from .utils import add_month, find_best_match, months_between, open_file, code_str
from .sat_functions import isr_mensual, sat_retenciones

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


def create_cfdi(emisor_cif, receptor_cif, factura_details):
    invoice = cfdi40.Comprobante(
        emisor=cfdi40.Emisor(
            rfc=emisor_cif['Rfc'],
            nombre=emisor_cif['RazonSocial'],
            regimen_fiscal=factura_details.get("EmisorRegimen") or emisor_cif['RegimenFiscal']
        ),
        lugar_expedicion=emisor_cif['CodigoPostal'],
        receptor=cfdi40.Receptor(
            rfc=receptor_cif['Rfc'],
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
    template = facturacion_environment.from_string(concepto["Descripcion"])
    concepto["Descripcion"] = template.render(
        periodo=periodo
    )
    return concepto


def period_desc(dp: DatePeriod):
    if dp.month:
        return fecha_mes(date(year=dp.year, month=dp.month, day=1))
    return f"AÑO {dp.year}"


def periodicidad_mes_desc(periodo_mes_ajuste):
    _, mes_ajuste = parse_periodo_mes_ajuste(periodo_mes_ajuste)
    return get_month_name(mes_ajuste)


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


def cliente_prediales(facturas):
    res = {}
    for f in facturas:
        receptor = f['Receptor']['Rfc']
        s = res.setdefault(receptor, set())
        for c in f['Conceptos']:
            for p in c['CuentaPredial']:
                s.add(p)
    return res


def generate_ingresos(clients, facturas, dp):
    errors = []

    def facturas_iter():
        for i, f in enumerate(facturas, start=1):
            try:
                emisor_cif = clients.get(f['Emisor'])
                if not emisor_cif:
                    raise ValueError("Emisor not found")

                receptor_cif = clients.get(f['Receptor'])
                if not receptor_cif:
                    raise ValueError("Receptor not found")

                def prepare_concepto(c):
                    periodo = periodicidad_desc(
                        dp,
                        c['_periodo_mes_ajuste'],
                        c.get('_desfase_mes')
                    )
                    if periodo and c['ValorUnitario'] is not None:
                        c = copy.deepcopy(c)
                        sat_retenciones(c, emisor_cif, receptor_cif)
                        return format_concepto_desc(c, periodo=periodo)

                if f["MetodoPago"] == "PPD" and f["FormaPago"] != "99":
                    raise ValueError(f"FormaPago '{f['FormaPago']}' is invalid, expected '99' for PPD")

                if conceptos := [x for x in (prepare_concepto(c) for c in f["Conceptos"]) if x]:
                    f["Conceptos"] = conceptos
                    cfdi = create_cfdi(emisor_cif, receptor_cif, f)

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


def pago_factura(factura_pagar, fecha_pago: datetime, forma_pago: str, importe_pago: Decimal = None, serie_pago=None, receptor_cif=None):
    c = factura_pagar

    receptor = cfdi40.Receptor(
        rfc=receptor_cif['Rfc'],
        nombre=receptor_cif['RazonSocial'],
        domicilio_fiscal_receptor=receptor_cif['CodigoPostal'],
        regimen_fiscal_receptor=receptor_cif['RegimenFiscal'],
        uso_cfdi="CP01"
    )

    invoice = Comprobante.pago_comprobantes(
        receptor=receptor,
        serie=serie_pago or None,
        folio=c.get('Folio') if serie_pago else None,
        comprobantes=[
            PagoComprobante(
                comprobante=c,
                num_parcialidad=c.ultima_num_parcialidad + 1,
                imp_saldo_ant=c.saldo_pendiente(),
                imp_pagado=importe_pago
            )
        ],
        fecha_pago=fecha_pago,
        forma_pago=forma_pago,
    )
    return invoice.process()


def iter_conceptos(facturas):
    for f in facturas:
        rfc_emisor = f["Emisor"]
        rfc_receptor = f["Receptor"]
        for c in f["Conceptos"]:
            yield rfc_emisor, rfc_receptor, c


def find_ajustes(facturas, mes_ajuste):
    for rfc_emisor, rfc_receptor, concepto in iter_conceptos(facturas):
        _, mes_aj = parse_periodo_mes_ajuste(concepto['_periodo_mes_ajuste'])
        if mes_aj == mes_ajuste:
            yield rfc_emisor, rfc_receptor, concepto


def generate_ajustes(clients, facturas, dp_effective):
    errors = []
    ajustes_dir = os.path.join(TEMP_DIRECTORY, 'ajustes')
    os.makedirs(ajustes_dir, exist_ok=True)

    def ajustes_iter():
        for i, (emisor_rfc, receptor_rfc, concepto) in enumerate(find_ajustes(facturas, dp_effective.month), start=1):
            # try:
            valor_unitario_raw = concepto["ValorUnitario"]

            if isinstance(valor_unitario_raw, dict):
                vu_eff, vu = find_best_match(valor_unitario_raw, add_month(dp_effective, -1))
                vun_eff, vun = find_best_match(valor_unitario_raw, dp_effective)
                if vu_eff == vun_eff or vun is None or vu is None:
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
            data = {
                "receptor": clients[receptor_rfc],
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
        # except Exception as e:
        #     errors.append(f"{i} {receptor_rfc}: {str(e)}")

    cfdis = list(ajustes_iter())
    if errors:
        raise ConsoleErrors("Generar Ajustes Errores", errors=errors)
    return cfdis


def create_ajuste_fn(ajuste_porcentaje, data, file_name):
    def fn():
        if ajuste_porcentaje:
            generate_pdf_template(
                template_name='ajuste.md',
                fields=data,
                target=file_name,
            )
            return file_name

    return fn


def find_depositos(facturas):
    for rfc_emisor, rfc_receptor, concepto in iter_conceptos(facturas):
        if "_deposito" in concepto:
            yield rfc_emisor, rfc_receptor, concepto


def generar_depositos(clients, facturas):
    errors = []
    depositos_dir = os.path.join(TEMP_DIRECTORY, 'depositos')
    os.makedirs(depositos_dir, exist_ok=True)

    def depositos_iter():
        for i, (emisor_rfc, receptor_rfc, concepto) in enumerate(find_depositos(facturas), start=1):
            try:
                dep = concepto["_deposito"]

                concepto = format_concepto_desc(concepto, periodo="INMUEBLE")
                file_name = os.path.join(depositos_dir, f'Deposito_{receptor_rfc}_{i}.pdf')

                data = {
                    "receptor": clients[receptor_rfc],
                    "emisor": clients[emisor_rfc],
                    "concepto": concepto,
                    "deposito": dep,
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
        generate_pdf_template(
            template_name='deposito.md',
            fields=data,
            target=file_name,
        )
        return file_name

    return fn


def archivos_folder(dp: DatePeriod):
    if not dp:
        return ARCHIVOS_DIRECTORY

    if dp.month:
        return os.path.join(ARCHIVOS_DIRECTORY, str(dp.year), str(dp.year) + "-{:02d}".format(dp.month))

    return os.path.join(ARCHIVOS_DIRECTORY, str(dp.year))


def archivos_filename(dp: DatePeriod, name=".xlsx"):
    return os.path.join(archivos_folder(dp), f"{dp}{name}")


def exportar_facturas(all_invoices, dp: DatePeriod, emisor_cif, rfc_prediales):
    emisor_rfc = emisor_cif['Rfc']

    emitidas = filter_invoices_iter(invoices=all_invoices.values(), fecha=dp, rfc_emisor=emisor_rfc)
    emitidas_pagos = filter_payments_iter(invoices=all_invoices, fecha=dp, rfc_emisor=emisor_rfc)
    emitidas_pagos = list(emitidas_pagos)

    recibidas = filter_invoices_iter(invoices=all_invoices.values(), fecha=dp, rfc_receptor=emisor_rfc)
    recibidas_pagos = filter_payments_iter(invoices=all_invoices, fecha=dp, rfc_receptor=emisor_rfc)

    recibidas_pagos = list(recibidas_pagos)
    pagos_hechos_iva = [
        p
        for p in recibidas_pagos
        if sum(x.get("Importe", 0) for x in p.impuestos.get("Traslados", {}).values())
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
    payments_export(workbook, f"RECIBIDAS PAGOS IVA", pagos_hechos_iva)
    if prediales:
        payments_export(workbook, "PREDIALES", prediales)

    # RETENCIONES
    if dp.month is None:
        archivo_retenciones = archivos_filename(dp, name="retenciones.txt")
        pagos_agrupados = payments_groupby_receptor(emitidas_pagos)
        payments_retentions_export(archivo_retenciones, pagos_agrupados)

    workbook.close()
    return archivo_excel


def sum_payments(payments):
    amounts = {
        'Subtotal': 0,
        'ISR Ret': 0,
        'IVA Ret': 0,
        'IVA16 Tras': 0,
    }
    for p in payments:
        if p.comprobante['TipoDeComprobante'] == "E":
            if p.comprobante_pagado['MetodoPago'] == 'PPD':
                continue
            else:
                amounts['Subtotal'] -= p.sub_total
                amounts['ISR Ret'] -= p.impuestos.get("Retenciones", {}).get(Impuesto.ISR, {}).get("Importe", 0)
                amounts['IVA Ret'] -= p.impuestos.get("Retenciones", {}).get(Impuesto.IVA, {}).get("Importe", 0)
                amounts['IVA16 Tras'] -= p.impuestos.get("Traslados", {}).get("002|Tasa|0.160000", {}).get("Importe", 0)
        else:
            amounts['Subtotal'] += p.sub_total
            amounts['ISR Ret'] += p.impuestos.get("Retenciones", {}).get(Impuesto.ISR, {}).get("Importe", 0)
            amounts['IVA Ret'] += p.impuestos.get("Retenciones", {}).get(Impuesto.IVA, {}).get("Importe", 0)
            amounts['IVA16 Tras'] += p.impuestos.get("Traslados", {}).get("002|Tasa|0.160000", {}).get("Importe", 0)

    for k in amounts:
        amounts[k] = round(amounts[k])

    return amounts


def generate_pdf_template(template_name, fields, target=None, css_string=None):
    template = facturacion_environment.get_template(template_name)
    md5_document = template.render(
        fields
    )
    html = markdown(md5_document)
    pdf = HTML(string=html).write_pdf(
        target=target,
        stylesheets=[
            os.path.join(SOURCE_DIRECTORY, "markdown_styles", "markdown6.css"),
            CSS(
                string=css_string or '@page { width: Letter; margin: 1.6cm 1.6cm 1.6cm 1.6cm; }'
            )
        ]
    )
    return pdf


def mf_pago_fmt(cfdi):
    i = cfdi
    if i['TipoDeComprobante'] == "I":
        return i['TipoDeComprobante'].code + ' ' + i['MetodoPago'].code + ' ' + i['FormaPago'].code
    return code_str(i['TipoDeComprobante']) + '       '


def preview_cfdis(cfdis):
    outfile = os.path.join(TEMP_DIRECTORY, "factura.html")
    os.makedirs(TEMP_DIRECTORY, exist_ok=True)
    render.html_write(
        xlm=cfdis,
        target=outfile,
    )
    open_file(
        os.path.abspath(outfile)
    )


def center_location(element) -> tuple[int, int]:
    return tuple((c + s // 3) for c, s in zip(element.current_location(), element.size))
