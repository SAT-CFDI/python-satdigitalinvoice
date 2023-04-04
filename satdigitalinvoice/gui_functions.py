import logging
import os
from datetime import datetime, date

import xlsxwriter
from babel.dates import format_date
from satcfdi import DatePeriod
from satcfdi.accounting import filter_invoices_iter, filter_payments_iter, invoices_export, payments_export
from satcfdi.accounting.process import IVA16
from satcfdi.create.cfd import cfdi40
from satcfdi.create.cfd.cfdi40 import Comprobante
from satcfdi.pacs import sat
# noinspection PyUnresolvedReferences
from satcfdi.transform.catalog import CATALOGS
from xlsxwriter.exceptions import FileCreateError

from .file_data_managers import  environment_default

logger = logging.getLogger(__name__)
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

    if factura_details['Total'] != invoice['Total']:
        logger.info(f"{factura_details['Receptor']}: Total '{factura_details['Total']}' is invalid, expected '{invoice['Total']}'")
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


def parse_ym_date(periodo):
    return datetime.strptime(periodo, '%Y-%m')


def parse_date_period(periodo):
    if "-" in periodo:
        period = parse_ym_date(periodo)
        return DatePeriod(period.year, period.month)
    else:
        return DatePeriod(int(periodo))


def format_concepto_desc(concepto, periodo):
    concepto = concepto.copy()
    template = environment_default.from_string(concepto["Descripcion"])
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


def generate_ingresos(config, clients, facturas, values, csd_signer):
    if not validad_facturas(clients, facturas):
        return

    inicio = int(values["inicio"])
    if inicio <= 0:
        logger.info("Inicio no Valido")

    final = values["final"] or len(facturas)
    final = int(final)
    if final <= 0 or final < inicio:
        logger.info("Final no Valido")

    ym_date = parse_ym_date(values["periodo"])
    facturas = facturas[inicio - 1:final]
    folio = config.folio()
    serie = config.serie()
    emisor_cif = clients[csd_signer.rfc]

    def prepare_concepto(concepto):
        periodo = periodo_desc(ym_date, concepto['_periodo_mes_ajuste'])
        if periodo:
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


def pago_factura(config, factura_pagar, fecha_pago, forma_pago, csd_signer):
    if not (fecha_pago := parse_fecha_pago(fecha_pago)):
        return

    i = factura_pagar
    if i.saldo_pendiente != i["Total"]:
        logger.info("Comprobante ya tiene pago anterior")
        logger.info(f"Saldo Pendiente: {i.saldo_pendiente}")
        return

    invoice = Comprobante.pago_comprobantes(
        comprobantes=i,
        fecha_pago=fecha_pago,
        forma_pago=forma_pago,
        serie=config.serie(),
        folio=str(config.folio()),
    )
    invoice.sign(csd_signer)
    return invoice.process()

    # Pago Parcial
    # comprobantes = [PagoComprobante(
    #     comprobante=c,
    #     num_parcialidad=c.ultima_num_parcialidad + 1,
    #     imp_saldo_ant=c.saldo_pendiente,
    #     imp_pagado=Decimal(imp_pagado)
    # ) for c, imp_pagado in cfdis],


def find_ajustes(facturas, mes_ajuste):
    for f in facturas:
        rfc = f["Rfc"]
        for concepto in f["Conceptos"]:
            _, mes_aj = parse_periodo_mes_ajuste(concepto['_periodo_mes_ajuste'])
            if mes_aj == mes_ajuste:
                yield rfc, concepto


def exportar_facturas_filename(dp: DatePeriod, ext="xlsx"):
    if dp.month:
        archivo_excel = f"facturas/{dp.year}/{dp}/{dp}.{ext}"
    else:
        archivo_excel = f"facturas/{dp.year}/{dp}.{ext}"

    return archivo_excel


def exportar_facturas(all_invoices, dp: DatePeriod, emisor_cif, rfc_prediales):
    emisor_rfc = emisor_cif['Rfc']
    emisor_regimen = emisor_cif['RegimenFiscal']

    emitidas = filter_invoices_iter(invoices=all_invoices.values(), fecha=dp, rfc_emisor=emisor_rfc)
    emitidas_pendientes = filter_invoices_iter(
        invoices=all_invoices.values(), fecha=lambda x: x <= dp, rfc_emisor=emisor_rfc, estatus='1',
        invoice_type="I", pending_balance=lambda x: x > 0)
    emitidas_pagos = filter_payments_iter(invoices=all_invoices, fecha=dp, rfc_emisor=emisor_rfc)

    recibidas = filter_invoices_iter(invoices=all_invoices.values(), fecha=dp, rfc_receptor=emisor_rfc)
    recibidas_pendientes = filter_invoices_iter(
        invoices=all_invoices.values(), fecha=lambda x: x <= dp, rfc_receptor=emisor_rfc, estatus='1',
        invoice_type="I", pending_balance=lambda x: x > 0)
    recibidas_pagos = filter_payments_iter(invoices=all_invoices, fecha=dp, rfc_receptor=emisor_rfc)

    recibidas_pagos = list(recibidas_pagos)
    pagos_hechos_iva = [
        p
        for p in recibidas_pagos
        if p.impuestos.get("Traslados", {}).get(IVA16, {}).get("Importe", 0) > 0
           and p.comprobante["Receptor"].get("RegimenFiscalReceptor") in (emisor_regimen, None)
    ]
    prediales = [p for p in recibidas_pagos if p.comprobante["Emisor"]["Rfc"] in rfc_prediales]

    archivo_excel = exportar_facturas_filename(dp)
    os.makedirs(os.path.dirname(archivo_excel), exist_ok=True)

    workbook = xlsxwriter.Workbook(archivo_excel)
    # EMITIDAS
    invoices_export(workbook, "EMITIDAS", emitidas)
    invoices_export(workbook, "EMITIDAS PENDIENTES", emitidas_pendientes)
    payments_export(workbook, "EMITIDAS PAGOS", emitidas_pagos)

    # RECIBIDAS
    invoices_export(workbook, "RECIBIDAS", recibidas)
    invoices_export(workbook, "RECIBIDAS PENDIENTES", recibidas_pendientes)
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
