import logging
import os
from datetime import datetime, date
from decimal import Decimal
from decimal import InvalidOperation

import xlsxwriter
from babel.dates import format_date
from markdown2 import markdown
from satcfdi import DatePeriod
from satcfdi.accounting import filter_invoices_iter, filter_payments_iter, invoices_export, payments_export
from satcfdi.accounting.process import payments_groupby_receptor, payments_retentions_export
from satcfdi.create.cfd import cfdi40
from satcfdi.create.cfd.cfdi40 import Comprobante, PagoComprobante
from satcfdi.pacs import sat
from satcfdi.printer import Representable
# noinspection PyUnresolvedReferences
from satcfdi.transform.catalog import CATALOGS
from weasyprint import HTML, CSS
from xlsxwriter.exceptions import FileCreateError

from . import SOURCE_DIRECTORY, ARCHIVOS_DIRECTORY, TEMP_DIRECTORY
from .environments import facturacion_environment
from .utils import add_month

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
        # serie=serie,
        # folio=folio,
        conceptos=factura_details["Conceptos"]
    )
    invoice = invoice.process()

    expected_total = factura_details.get('Total')
    if expected_total is not None:
        if expected_total != invoice['Total']:
            print(f"{factura_details['Receptor']}: Total '{expected_total}' is invalid, expected '{invoice['Total']}'")
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


def validad_facturas(clients, facturas):
    is_valid = True
    for factura_details in facturas:
        cliente = clients.get(factura_details['Receptor'])
        if not cliente:
            print(f"{factura_details['Receptor']}: client not found")
            is_valid = False

        for c in factura_details["Conceptos"]:
            periodo_mes_ajuste = c.get("_periodo_mes_ajuste", "")
            try:
                parse_periodo_mes_ajuste(periodo_mes_ajuste)
            except ValueError:
                print(f"{factura_details['Receptor']}: _periodo_mes_ajuste '{periodo_mes_ajuste}' is invalid")
                is_valid = False

        if factura_details["MetodoPago"] == "PPD" and factura_details["FormaPago"] != "99":
            print(f"{factura_details['Receptor']}: FormaPago '{factura_details['FormaPago']}' is invalid, expected '99' for PPD")
            is_valid = False

    return is_valid


def period_desc(dp: DatePeriod):
    return format_date(date(year=dp.year, month=dp.month, day=1), locale='es_MX', format="'Mes de' MMMM 'del' y").upper()


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
    if not validad_facturas(clients, facturas):
        return

    emisor_cif = clients[emisor_rfc]

    def prepare_concepto(concepto):
        periodo = periodicidad_desc(
            dp,
            concepto['_periodo_mes_ajuste'],
            concepto.get('_desfase_mes')
        )
        if periodo and concepto['ValorUnitario'] is not None:
            return format_concepto_desc(concepto, periodo=periodo)

    def facturas_iter():
        i = 0
        for f in facturas:
            receptor_cif = clients[f['Receptor']]
            conceptos = [x for x in (prepare_concepto(c) for c in f["Conceptos"]) if x]
            if conceptos:
                f["Conceptos"] = conceptos
                yield create_cfdi(receptor_cif, f, emisor_cif)
                i += 1

    cfdis = [i for i in facturas_iter()]

    if None in cfdis:
        return

    return cfdis


def parse_fecha_pago(fecha_pago):
    if not fecha_pago:
        raise ValueError("Fecha de Pago es requerida")

    fecha_pago = datetime.fromisoformat(fecha_pago)
    if fecha_pago > datetime.now():
        raise ValueError("Fecha de Pago es mayor a la fecha actual")

    if fecha_pago.replace(hour=12) > datetime.now():
        fecha_pago = datetime.now()
    else:
        fecha_pago = fecha_pago.replace(hour=12)

    dif = datetime.now() - fecha_pago
    if dif.days > 30:
        raise ValueError("Fecha de Pago es de hace mas de 30 dias")

    return fecha_pago


def parse_importe_pago(importe_pago: str):
    if not importe_pago:
        return None

    try:
        return round(Decimal(importe_pago), 2)
    except InvalidOperation:
        raise ValueError("Importe de Pago es invalido")


def pago_factura(factura_pagar, fecha_pago: datetime, forma_pago: str, importe_pago: Decimal = None):
    c = factura_pagar
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
    )
    return invoice.process()


def find_ajustes(facturas, mes_ajuste):
    for f in facturas:
        rfc = f["Receptor"]
        for concepto in f["Conceptos"]:
            _, mes_aj = parse_periodo_mes_ajuste(concepto['_periodo_mes_ajuste'])
            if mes_aj == mes_ajuste:
                yield rfc, concepto


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
    payments_export(workbook, f"RECIBIDAS PAGOS IVA {emisor_regimen.code}", pagos_hechos_iva)
    if prediales:
        payments_export(workbook, "PREDIALES", prediales)

    # RETENCIONES
    if dp.month is None:
        archivo_retenciones = archivos_filename(dp, ext="retenciones.txt")
        pagos_agrupados = payments_groupby_receptor(emitidas_pagos)
        payments_retentions_export(archivo_retenciones, pagos_agrupados)

    try:
        workbook.close()
        return archivo_excel
    except FileCreateError:
        return None


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
        return i['TipoDeComprobante'].code + ' ' + i['MetodoPago'].code + ' ' + (i['FormaPago'].code if i['FormaPago'].code != '99' else '')
    return i['TipoDeComprobante'].code


def ajustes_directory(dp: DatePeriod):
    return os.path.join(archivos_folder(dp), 'ajustes')


def preview_cfdis(cfdis):
    outfile = os.path.join(TEMP_DIRECTORY, "factura.html")
    Representable.html_write_all(
        objs=cfdis,
        target=outfile,
    )
    os.startfile(
        os.path.abspath(outfile)
    )
