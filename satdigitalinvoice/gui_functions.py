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
from .utils import add_month, find_best_match, months_between, open_file
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
                imp_saldo_ant=c.saldo_pendiente,
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
    ajustes_dir = os.path.join(archivos_folder(dp_effective), 'ajustes')
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
    depositos_dir = os.path.join(ARCHIVOS_DIRECTORY, 'depositos')
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
        if sum(x.get("Importe", 0) for x in p.impuestos.get("Traslados", {}).values()) > 0 and p.comprobante["Receptor"].get("RegimenFiscalReceptor") not in ('616',)
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


def calculate_declaracion_provisional(all_invoices, dp: DatePeriod, emisor_cif, rfc_prediales):
    emisor_rfc = emisor_cif['Rfc']

    emitidas_pagos = list(filter_payments_iter(invoices=all_invoices, fecha=dp, rfc_emisor=emisor_rfc))
    recibidas_pagos = list(filter_payments_iter(invoices=all_invoices, fecha=dp, rfc_receptor=emisor_rfc))
    prediales = [p for p in recibidas_pagos if p.comprobante["Emisor"]["Rfc"] in rfc_prediales]

    emitidas_pagos = sum_payments(emitidas_pagos)
    recibidas_pagos = sum_payments(recibidas_pagos)
    prediales = sum_payments(prediales)['Subtotal']

    # ISR
    total_ingresos = emitidas_pagos['Subtotal']
    deduccion_opcional = round(total_ingresos * Decimal("0.35"))
    total_deducciones = deduccion_opcional + prediales
    base_gravable = total_ingresos - deduccion_opcional - prediales
    isr_causado = isr_mensual(dp, base_gravable)
    isr_a_cargo = isr_causado - emitidas_pagos['ISR Ret']

    # IVA
    iva_a_cargo = round(total_ingresos * Decimal("0.16")) - emitidas_pagos['IVA Ret'] - recibidas_pagos['IVA16 Tras']
    res = {
        "ISR PERSONAS FÍSICAS. ARRENDAMIENTO DE INMUEBLES (USO O GOCE)": {
            "¿Tus ingresos fueron obtenidos en copropiedad o sociedad conyugal?": "No",
            "Tipo de deducción": "Deducción opcional",
            "Total de ingresos": total_ingresos,
            "Deducción opcional": deduccion_opcional,
            "Impuesto predial": prediales,
            "Total de deducciones autorizadas": total_deducciones,
            "Base gravable del pago provisional": base_gravable,
            "ISR causado": isr_causado,
            "Estímulos acreditables": 0,
            "Impuesto retenido": emitidas_pagos['ISR Ret'],
            "ISR a cargo": isr_a_cargo,
        },
        "IMPUESTO AL VALOR AGREGADO": {
            "Actividades gravadas a la tasa del 16%": total_ingresos,
            "Actividades gravadas a la tasa del 0%": 0,
            "Actividades exentas": 0,
            "Actividades no objeto del impuesto": 0,
            "IVA cobrado del periodo a la tasa del 16%": round(total_ingresos * Decimal("0.16")),
            "IVA acreditable del periodo": recibidas_pagos['IVA16 Tras'],
            "IVA retenido": emitidas_pagos['IVA Ret'],
            "¿Tienes otras cantidades a cargo?": 'No',
            "Cantidad a cargo": iva_a_cargo,
            "¿Tienes otras cantidades a favor?": 'No',
            "Impuesto a cargo": iva_a_cargo,
        },
        "TOTAL": isr_a_cargo + iva_a_cargo

    }
    p_desc = period_desc(dp)
    return p_desc + "\n" + emisor_rfc + "\n" + to_yaml(res)


def calculate_diot(all_invoices, dp: DatePeriod, emisor_cif):
    emisor_rfc = emisor_cif['Rfc']
    recibidas_pagos = filter_payments_iter(invoices=all_invoices, fecha=dp, rfc_receptor=emisor_rfc)
    recibidas_pagos = list(r for r in recibidas_pagos if r.comprobante["Receptor"].get("RegimenFiscalReceptor") not in ('616',))
    recibidas_pagos.sort(key=lambda x: x.comprobante["Emisor"]["Rfc"])

    provedores = {}
    for rfc, group in groupby(recibidas_pagos, lambda x: x.comprobante["Emisor"]["Rfc"]):
        payments = list(group)
        provedores[rfc] = {
            'Subtotal': sum(i.sub_total for i in payments),
            "Base16": round(sum(
                i.impuestos.get("Traslados", {}).get("002|Tasa|0.160000", {}).get("Base", 0) for i in payments
                if i.impuestos.get("Traslados", {}).get("002|Tasa|0.160000", {}).get("Importe")
            )),
        }

    diot = DIOT(
        datos_identificacion=DatosIdentificacion(
            rfc=emisor_rfc,
            curp=emisor_cif['CURP'],
            nombre=emisor_cif['Nombre'],
            apellido_paterno=emisor_cif['ApellidoPaterno'],
            apellido_materno=emisor_cif['ApellidoMaterno'],
            ejercicio=dp.year,
        ),
        periodo=f'{dp.month:02d}',
        proveedores=[
            ProveedorTercero(
                tipo_tercero=TipoTercero.PROVEEDOR_NACIONAL,
                tipo_operacion=TipoOperacion.OTROS,
                rfc=rfc,
                iva16=values["Base16"],
            )
            for rfc, values in provedores.items() if values["Base16"]
        ]
    )

    diot_folder = os.path.join(archivos_folder(dp), 'diot')
    shutil.rmtree(diot_folder, ignore_errors=True)
    os.makedirs(diot_folder, exist_ok=True)

    diot_file = diot.generate_package(
        dirname=diot_folder
    )
    diot_file = os.path.basename(diot_file)

    diot_pdf = os.path.join(diot_folder, f"{diot_file}.pdf")
    render.pdf_write(diot, target=diot_pdf)

    with open(os.path.join(diot_folder, f"{diot_file}.export.txt"), "wb") as f:
        diot.export(f)
    with open(os.path.join(diot_folder, f"{diot_file}.plain.txt"), "wb") as f:
        diot.plain_write(f)

    return diot_pdf


def sum_payments(payments):
    return {
        'Subtotal': round(sum(i.sub_total for i in payments)),
        'ISR Ret': round(sum(i.impuestos.get("Retenciones", {}).get(Impuesto.ISR, {}).get("Importe", 0) for i in payments)),
        'IVA Ret': round(sum(i.impuestos.get("Retenciones", {}).get(Impuesto.IVA, {}).get("Importe", 0) for i in payments)),

        'IVA16 Tras': round(sum(i.impuestos.get("Traslados", {}).get("002|Tasa|0.160000", {}).get("Importe", 0) for i in payments)),
    }


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
    return i['TipoDeComprobante'].code + '       '


def preview_cfdis(cfdis):
    outfile = os.path.join(TEMP_DIRECTORY, "factura.html")
    render.html_write(
        xlm=cfdis,
        target=outfile,
    )
    open_file(
        os.path.abspath(outfile)
    )


def center_location(element) -> tuple[int, int]:
    return tuple((c + s // 3) for c, s in zip(element.current_location(), element.size))
