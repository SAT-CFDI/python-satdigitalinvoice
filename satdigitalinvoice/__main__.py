import base64
import io
import itertools
import logging
import os
import shutil
from datetime import date, datetime, timedelta
from decimal import Decimal
from zipfile import ZipFile

import PySimpleGUI as sg
from PySimpleGUI import POPUP_BUTTONS_OK_CANCEL
from babel.dates import format_date
from satcfdi import Code, DatePeriod
from satcfdi.accounting import filter_invoices_by, InvoiceType
from satcfdi.exceptions import ResponseError, DocumentNotFoundError
from satcfdi.pacs import Accept
from satcfdi.pacs.sat import SAT, TipoDescargaMasivaTerceros, EstadoSolicitud
# noinspection PyUnresolvedReferences
from satcfdi.transform.catalog import CATALOGS

from . import EMAIL_MANAGER, EMISOR, FACTURAS_SOURCE, SERIE, LUGAR_EXPEDICION, PAC_SERVICE, FIEL_SIGNER, PROPIETARIO_CORREO, AJUSTES_DIR, CORREO_FIRMA
from .client_validation import validar_client
from .file_data_managers import FacturasManager, environment_default, generate_pdf_template
from .formatting_functions.common import fecha, pesos, porcentaje
from .gui_functions import generate_ingresos, pago_factura, find_factura
from .log_tools import LogAdapter, LogHandler, log_cfdi, log_email
from .mycfdi import generate_invoice, get_all_cfdi, clients, cancelados_manager, MyCFDI, move_to_folder, notifications

logging.basicConfig(level=logging.DEBUG)
logger = LogAdapter(logging.getLogger())

FORMA_PAGO = CATALOGS['{http://www.sat.gob.mx/sitio_internet/cfd/catalogos}c_FormaPago']
SAT_SERVICE = SAT(
    signer=FIEL_SIGNER
)
TEXT_PADDING = ((5, 0), 3)
RTEXT_PADDING = ((0, 0), 3)


def make_layout():
    # First the window layout in 2 columns
    facturas_manager = FacturasManager({
        "periodo": "INVALID"
    }, file_source=FACTURAS_SOURCE)
    numero_facturas = len(facturas_manager["Facturas"])

    # LAYOUT
    button_column = [
        sg.Button("Preparar Facturas", key="prepare_facturas"),
        sg.Text("Periodo:", pad=TEXT_PADDING),
        sg.Input(format_date(date.today(), locale='es_MX', format="'Mes de' MMMM 'del' y").upper(), key="periodo", change_submits=True),
        sg.Text("De:", pad=TEXT_PADDING),
        sg.Input("1", key="inicio", size=(4, 1), change_submits=True),
        sg.Text("Hasta:", pad=TEXT_PADDING),
        sg.Input(str(numero_facturas), key="final", size=(4, 1), change_submits=True),
    ]

    c_second = [
        sg.Column(
            [
                [
                    sg.Text("Factura:", pad=TEXT_PADDING),
                    sg.Input("", size=(30, 1), key="factura_pagar", change_submits=True),
                ],
                [
                    sg.Button("Status", key="status_sat"),
                    sg.Button("Descarga", key="descarga"),
                ]
            ],
            pad=0
        ),
        sg.VSeparator(),
        sg.Column(
            [
                [
                    sg.CalendarButton("FechaPago:", format='%Y-%m-%d', title="FechaPago", no_titlebar=False, target="fecha_pago", pad=TEXT_PADDING),
                    sg.Input("", size=(12, 1), key="fecha_pago", change_submits=True),
                    sg.Text("FormaPago:", pad=TEXT_PADDING),
                    sg.Combo([Code(k, v) for k, v in FORMA_PAGO.items()], default_value=Code("03", FORMA_PAGO["03"]), key="forma_pago", change_submits=True)
                ],
                [
                    sg.Button("Preparar Pago", key="prepare_pago"),
                ]
            ],
            pad=0
        )
    ]

    button_column_third = [
        sg.Button("Preparar Correos", key="prepare_correos"),
        sg.Button("Facturas Pendientes", key="facturas_pendientes"),
        sg.Checkbox("Ver Detallado", default=False, key="detallado"),
        sg.VSeparator(),
        sg.Button("Preparar Ajuste Anual", key="preparar_ajuste_anual"),
        sg.Text("Año-Mes:", pad=TEXT_PADDING),
        sg.Input((date.today() + timedelta(days=31)).strftime('%Y-%m'), size=(8, 1), key="anio_mes_ajuste"),
        sg.Text("Ajuste:", pad=TEXT_PADDING),
        sg.Input("", size=(6, 1), key="ajuste_porcentaje"),
        sg.Text("%", pad=RTEXT_PADDING),
        sg.VSeparator(),
        sg.Text("Recuperar:", pad=TEXT_PADDING),
        sg.Button("Emitidas", key="recuperar_emitidas"),
        sg.Button("Recibidas", key="recuperar_recibidas"),
        sg.Text("Dias:", pad=TEXT_PADDING),
        sg.Input("40", size=(4, 1), key="recuperar_dias"),
    ]

    button_column_low = [
        sg.Button("Validar Clientes", key="validate_clientes"),
        sg.Button("Crear Facturas", disabled=True, key="crear_facturas"),
        sg.Button("Enviar Correos", disabled=True, key="enviar_correos"),

    ]

    # ----- Full layout -----
    return [
        button_column,
        [sg.HSeparator()],
        c_second,
        [sg.HSeparator()],
        button_column_third,
        [sg.Output(expand_x=True, expand_y=True, key="console")],
        button_column_low
    ]


def log_line(text, exc_info=False):
    ln = (150 - len(text)) // 2
    logger.info(
        ("=" * ln) + " " + text + " " + ("=" * ln),
        exc_info=exc_info
    )


def log_item(text, exc_info=False):
    ln = (150 - len(text)) // 2
    logger.info(
        ("*" * ln) + " " + text + " " + ("*" * ln),
        exc_info=exc_info
    )


def cfdi_header(cfdi):
    receptor = Code(cfdi['Receptor']['Rfc'], cfdi['Receptor']['Nombre'])
    return f"{cfdi.name} - {cfdi.uuid} {receptor}"


class InvoiceButtonManager:
    def __init__(self):
        self._cfdis = []

    def set_invoices(self, invoices):
        self._cfdis = invoices
        for i, cfdi in enumerate(self._cfdis, start=1):
            log_item(f"FACTURA NUMERO: {i}")
            log_cfdi(cfdi, detailed=window['detallado'].get())

        self.style_button()

    def clear(self):
        cfdis = self._cfdis
        self._cfdis = []
        self.style_button()
        return cfdis

    def style_button(self):
        button = window['crear_facturas']
        button.update(
            disabled=len(self._cfdis) == 0
        )


class EmailButtonManager:
    def __init__(self):
        self._emails = {}

    def set_invoices(self, invoices):
        self._emails = invoices

        for i, (receptor_rfc, (notify_invoices, facturas_pendientes)) in enumerate(invoices.items(), start=1):
            log_item(f"CORREO NUMERO: {i}")
            log_email(receptor_rfc, notify_invoices, facturas_pendientes)

        self.style_button()

    def clear(self):
        emails = self._emails
        self._emails = {}
        self.style_button()
        return emails

    def style_button(self):
        button = window['enviar_correos']
        button.update(
            disabled=len(self._emails) == 0
        )


invoice_button_manager = InvoiceButtonManager()
email_button_manager = EmailButtonManager()


def enviar_correos(invoices):
    template = environment_default.get_template(
        'mail_facturas_template.html'
    )

    with EMAIL_MANAGER.sender as s:
        for receptor_rfc, (notify_invoices, facturas_pendientes) in invoices.items():
            client = clients[receptor_rfc]
            receptor_nombre = client["RazonSocial"]
            to_addrs = client["Email"]

            attachments = []
            for r in notify_invoices:
                attachments += [r.filename + ".xml", r.filename + ".pdf"]

            message = template.render(
                invoices=notify_invoices,
                pending_invoices=facturas_pendientes,
                CORREO_FIRMA=CORREO_FIRMA
            )

            s.send_email(
                subject=f"Comprobantes Fiscales {receptor_nombre} - {receptor_rfc}",
                to_addrs=to_addrs,
                html=message,
                file_attachments=attachments
            )

            window.read(timeout=0)

            for r in notify_invoices:
                r.notified = ",".join(to_addrs)


def recupera_comprobantes(id_solicitud):
    response = SAT_SERVICE.recover_comprobante_status(
        id_solicitud=id_solicitud
    )
    logger.info_yaml(response)
    window.read(timeout=0)
    if response["EstadoSolicitud"] == EstadoSolicitud.Terminada:
        for id_paquete in response['IdsPaquetes']:
            response, paquete = SAT_SERVICE.recover_comprobante_download(
                id_paquete=id_paquete
            )
            logger.info_yaml(response)
            window.read(timeout=0)
            yield id_paquete, base64.b64decode(paquete) if paquete else None


def unzip_cfdi(file):
    with ZipFile(file, "r") as zf:
        for fileinfo in zf.infolist():
            xml_data = zf.read(fileinfo)
            move_to_folder(xml_data, pdf_data=None)
            window.read(timeout=0)


def find_ajustes(mes_ajuste):
    facturas_manager = FacturasManager({"periodo": "INMUEBLE"})

    for f in facturas_manager['Facturas']:
        rfc = f["Rfc"]
        for concepto in f["Conceptos"]:
            if concepto['_MesAjusteAnual'] == mes_ajuste:
                yield rfc, concepto


def main_loop():
    while True:
        event, values = window.read()
        try:
            if event in ("Exit", sg.WIN_CLOSED):
                return

            if event not in ("crear_facturas", "enviar_correos"):
                ch.clear()
            invoices_to_create = invoice_button_manager.clear()
            emails_to_send = email_button_manager.clear()

            match event:
                case "preparar_ajuste_anual":
                    anio_ajuste, mes_ajuste = (int(x) for x in values['anio_mes_ajuste'].split("-"))
                    ajuste_porcentaje = values['ajuste_porcentaje']
                    if not ajuste_porcentaje:
                        logger.error("Especificar Ajuste Porcetaje")
                        continue

                    ajuste_porcentaje = Decimal(ajuste_porcentaje) / 100
                    ajuste_efectivo_al = date(anio_ajuste, mes_ajuste, 1)

                    shutil.rmtree(AJUSTES_DIR, ignore_errors=True)
                    os.makedirs(AJUSTES_DIR, exist_ok=True)

                    for rfc, concepto in find_ajustes(mes_ajuste):
                        client = clients[rfc]
                        valor_unitario_nuevo = concepto["ValorUnitario"] * (1 + ajuste_porcentaje)

                        data = {
                            "Client": client,
                            "Rfc": rfc,
                            "Concepto": concepto,
                            "FechaHoy": fecha(date.today()),
                            "ValorUnitarioNuevo": pesos(valor_unitario_nuevo),
                            "Ajuste": porcentaje(ajuste_porcentaje, 2),
                            "AjustePeriodo": "UN AÑO",
                            "AjusteEfectivoAl": fecha(ajuste_efectivo_al),
                            "Propietario": EMISOR.legal_name,
                            "PropietarioCorreo": PROPIETARIO_CORREO,
                        }

                        logger.info_yaml(data)
                        res = generate_pdf_template(template_name='incremento_template.md', fields=data)
                        file_name = f'{AJUSTES_DIR}/AjusteAnual_{rfc}_{concepto["CuentaPredial"]}.pdf'
                        with open(file_name, 'wb') as f:
                            f.write(res)
                        window.read(timeout=0)

                case "recuperar_emitidas" | "recuperar_recibidas":
                    log_line("RECUPERAR")
                    fecha_final = date.today()
                    fecha_inicial = fecha_final - timedelta(days=int(values["recuperar_dias"]))
                    id_solicitud = notifications.get(event)

                    if not id_solicitud:
                        logger.info("Creando Nueva Solicitud")
                        window.read(timeout=0)
                        response = SAT_SERVICE.recover_comprobante_request(
                            fecha_inicial=fecha_inicial,
                            fecha_final=fecha_final,
                            rfc_receptor=SAT_SERVICE.signer.rfc if "recuperar_recibidas" == event else None,
                            rfc_emisor=SAT_SERVICE.signer.rfc if "recuperar_emitidas" == event else None,
                            tipo_solicitud=TipoDescargaMasivaTerceros.CFDI,
                        )
                        logger.info_yaml(response)
                        notifications[event] = response['IdSolicitud']
                        notifications.save()
                    else:
                        logger.info_yaml({
                            'IdSolicitud': id_solicitud
                        })
                        window.read(timeout=0)
                        for paquete_id, data in recupera_comprobantes(id_solicitud):
                            if data:
                                with io.BytesIO(data) as b:
                                    unzip_cfdi(b)
                            del notifications[event]
                            notifications.save()

                case "validate_clientes":
                    log_line("VALIDAR CLIENTES")
                    res = sg.popup(
                        f"Estas seguro que quieres validar {len(clients)} clientes?",
                        title=window[event].ButtonText,
                        button_type=POPUP_BUTTONS_OK_CANCEL,
                    )
                    if res == "OK":
                        for rfc, details in clients.items():
                            log_item(f"VALIDANDO {rfc}")
                            window.read(timeout=0)
                            validar_client(rfc, details)
                        log_item("FIN")
                    else:
                        log_item("OPERACION CANCELADA")

                case "prepare_facturas":
                    log_line("PREPARAR FACTURAS")
                    facturas = generate_ingresos(values)
                    if facturas:
                        invoice_button_manager.set_invoices(
                            facturas
                        )

                case "prepare_pago":
                    log_line("PREPARAR PAGO")
                    cfdi_pago = pago_factura(
                        factura_pagar=values["factura_pagar"],
                        fecha_pago=values["fecha_pago"],
                        forma_pago=values["forma_pago"]
                    )
                    if cfdi_pago:
                        invoice_button_manager.set_invoices(
                            [cfdi_pago]
                        )

                case "crear_facturas":
                    log_line("CREAR FACTURAS")
                    res = sg.popup(
                        f"Estas seguro que quieres crear {len(invoices_to_create)} facturas?",
                        title=window[event].ButtonText,
                        button_type=POPUP_BUTTONS_OK_CANCEL,

                    )
                    if res == "OK":
                        for invoice in invoices_to_create:
                            try:
                                cfdi = generate_invoice(invoice=invoice)
                                logger.info(f'Factura Generada: {cfdi_header(cfdi)}')
                                window.read(timeout=0)
                            except ResponseError as ex:
                                logger.error(f'Error Generando: {cfdi_header(MyCFDI(invoice))}')
                                logger.error(f"Status Code: {ex.response.status_code}")
                                logger.info_yaml(ex.response.json())
                                break
                        log_item("FIN")
                    else:
                        log_item("OPERACION CANCELADA")

                case "prepare_correos":
                    log_line("PREPARAR CORREOS")
                    all_invoices = get_all_cfdi()
                    now = datetime.now()
                    dp = DatePeriod(now.year, now.month)

                    cfdi_correos = {}
                    for receptor_rfc, notify_invoices in itertools.groupby(
                            sorted(
                                (i for i in all_invoices.values() if not i.notified),
                                key=lambda r: r["Receptor"]["Rfc"]
                            ),
                            lambda r: r["Receptor"]["Rfc"]
                    ):
                        notify_invoices = list(notify_invoices)
                        fac_pen = filter_invoices_by(
                            invoices=all_invoices,
                            fecha=lambda x: x < dp,
                            invoice_type=InvoiceType.PAYMENT_PENDING,
                            rfc_emisor=EMISOR.rfc,
                            rfc_receptor=receptor_rfc,
                            estatus='1'
                        )
                        cfdi_correos[receptor_rfc] = (notify_invoices, fac_pen)

                    if cfdi_correos:
                        email_button_manager.set_invoices(
                            cfdi_correos
                        )
                    else:
                        logger.info("No hay correos pendientes de enviar")

                case "enviar_correos":
                    log_line("ENVIAR CORREOS")
                    res = sg.popup(
                        f"Estas seguro que quieres enviar {len(emails_to_send)} correos?",
                        title=window[event].ButtonText,
                        button_type=POPUP_BUTTONS_OK_CANCEL
                    )
                    if res == "OK":
                        enviar_correos(emails_to_send)
                        log_item("FIN")
                    else:
                        log_item("OPERACION CANCELADA")

                case "status_sat":
                    log_line("STATUS")
                    i = find_factura(values["factura_pagar"])
                    if i:
                        estado = cancelados_manager.get_state(i, only_cache=False)
                        logger.info_yaml(estado)

                case "facturas_pendientes":
                    log_line("FACTURAS PENDIENTES")
                    all_invoices = get_all_cfdi()

                    fac_pen = filter_invoices_by(
                        invoices=all_invoices,
                        invoice_type=InvoiceType.PAYMENT_PENDING,
                        rfc_emisor=EMISOR.rfc,
                        estatus='1'
                    )
                    for receptor_rfc, fac_pen in itertools.groupby(
                            sorted(
                                fac_pen,
                                key=lambda r: r["Receptor"]["Rfc"]
                            ),
                            lambda r: r["Receptor"]["Rfc"]
                    ):
                        f = {
                            'Receptor': Code(receptor_rfc, clients[receptor_rfc]['RazonSocial']),
                            'Facturas Pendientes': [
                                {
                                    "Factura": f"{i.name} - {i.uuid}",
                                    'SaldoPendiente': i.saldo_pendiente,
                                    'Fecha': i["Fecha"]
                                }
                                for i in fac_pen
                            ]
                        }
                        logger.info_yaml(f)

                case "descarga":
                    log_line('DESCARGADA')
                    try:
                        res = PAC_SERVICE.recover(values["factura_pagar"], accept=Accept.XML_PDF)
                        cfdi = move_to_folder(res.xml, pdf_data=res.pdf)
                        log_cfdi(cfdi, detailed=values['detallado'])
                    except DocumentNotFoundError:
                        logger.info("Factura no encontrada")

                case "periodo" | "inicio" | "final" | "factura_pagar" | "fecha_pago" | "forma_pago":
                    pass

                case _:
                    logger.error(f"Unknown event {event}")

        except Exception:
            log_line("ERROR NO CONTROLADO", exc_info=True)


window = sg.Window(
    f"Facturacion 4.0  RazonSocial: {EMISOR.legal_name}  RFC: {EMISOR.rfc}  Facturas: {FACTURAS_SOURCE}  "
    f"Serie: {SERIE}  Regimen: {EMISOR.tax_system}  LugarExpedicion: {LUGAR_EXPEDICION}",
    make_layout(),
    size=(1280, 800),
    resizable=True,
)

ch = LogHandler(window['console'])
ch.setLevel(logging.INFO)
logging.getLogger().addHandler(ch)

main_loop()
window.close()
