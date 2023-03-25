import logging
from datetime import date, datetime

import PySimpleGUI as sg
from PySimpleGUI import POPUP_BUTTONS_OK_CANCEL
from babel.dates import format_date
from satcfdi import Code
from satcfdi.accounting import filter_invoices_by, InvoiceType
from satcfdi.exceptions import ResponseError

from . import EMAIL_MANAGER, EMISOR, FACTURAS_SOURCE, SERIE, LUGAR_EXPEDICION
from .client_validation import validar_client
from .file_data_managers import FacturasManager, environment_default
from .gui_functions import generate_ingresos, pago_factura, find_factura
from .log_tools import LogAdapter, LogHandler, log_cfdi
from .mycfdi import generate_invoice, get_all_cfdi, clients, cancelados_manager, MyCFDI

logging.basicConfig(level=logging.DEBUG)
logger = LogAdapter(logging.getLogger())


def make_layout():
    # First the window layout in 2 columns
    facturas_manager = FacturasManager({
        "periodo": "INVALID"
    }, file_source=FACTURAS_SOURCE)
    numero_facturas = len(facturas_manager["Facturas"])

    # LAYOUT
    button_column = [
        [
            sg.Button("Preparar Facturas", key="validate_invoices"),
            sg.Text("Periodo:"),
            sg.Input(format_date(date.today(), locale='es_MX', format="'Mes de' MMMM 'del' y").upper(), key="periodo", change_submits=True),
            sg.Text("De:"),
            sg.Input("1", key="inicio", size=(4, 1), change_submits=True),
            sg.Text("Hasta:"),
            sg.Input(str(numero_facturas), key="final", size=(4, 1), change_submits=True),
        ]
    ]
    button_column_second = [
        [
            sg.Button("Status SAT", key="status_sat"),
            sg.Button("Preparar Pago", key="prepare_pago"),
            sg.Text("De:"),
            sg.Input("", size=(30, 1), key="factura_pagar", change_submits=True),
            sg.Text("Fecha Pago:"),
            sg.Input(f"{datetime.today():%Y-%m-%d}", size=(12, 1), key="fecha_pago", change_submits=True),
            sg.Text("Forma Pago:"),
            sg.Input("03", size=(4, 1), key="forma_pago", change_submits=True),
        ]
    ]
    button_column_third = [
        [
            sg.Button("Preparar Correos", key="prepare_correos"),
            sg.Button("Facturas Pendientes", key="facturas_pendientes"),
            sg.Checkbox("Ver Detallado", default=False, key="detallado")
        ]
    ]

    button_column_low = [
        [
            sg.Button("Validar Clientes", key="validate_clientes"),
            sg.Button("Crear Facturas", disabled=True, key="crear_facturas"),
            sg.Button("Enviar Correos", disabled=True, key="enviar_correos"),
        ]
    ]

    # ----- Full layout -----
    return [
        [button_column],
        [sg.HSeparator(), ],
        [button_column_second],
        [sg.HSeparator(), ],
        [button_column_third],
        [sg.Output(expand_x=True, expand_y=True, key="console")],
        [button_column_low]
    ]


def log_line(text, exc_info=False):
    ln = (150 - len(text)) // 2
    logger.info(
        ("=" * ln) + " " + text + " " + ("=" * ln),
        exc_info=exc_info
    )


def cfdi_header(cfdi):
    receptor = Code(cfdi['Receptor']['Rfc'], cfdi['Receptor']['Nombre'])
    return f"{cfdi.name} {receptor}"


class InvoiceButtonManager:
    def __init__(self):
        self._cfdis = []

    def set_invoices(self, invoices):
        self._cfdis = invoices
        for i, cfdi in enumerate(self._cfdis, start=1):
            log_line(f"FACTURA NUMERO: {i}")
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
            f"Crear Facturas",
            disabled=len(self._cfdis) == 0
        )


class EmailButtonManager:
    def __init__(self):
        self._emails = []

    def set_invoices(self, invoices):
        self._emails = invoices

        for i, cfdi in enumerate(self._emails, start=1):
            receptor_rfc = cfdi["Receptor"]["Rfc"]
            to_addrs = clients[receptor_rfc]["Email"]

            log_line(f"CORREO NUMERO: {i}")
            logger.info(cfdi_header(cfdi))
            logger.info(to_addrs)
        self.style_button()

    def clear(self):
        emails = self._emails
        self._emails = []
        self.style_button()
        return emails

    def style_button(self):
        button = window['enviar_correos']
        button.update(
            f"Enviar Correos",
            disabled=len(self._emails) == 0
        )


invoice_button_manager = InvoiceButtonManager()
email_button_manager = EmailButtonManager()


def enviar_correos(invoices):
    email_sender = EMAIL_MANAGER.sender
    template = environment_default.get_template(
        'mail_facturas_template_simple.html'
    )

    with email_sender as s:
        for invoice in invoices:
            receptor_rfc = invoice["Receptor"]["Rfc"]

            client = clients[receptor_rfc]
            receptor_nombre = client["RazonSocial"]
            to_addrs = client["Email"]

            message = template.render(
                invoices=[invoice],
            )

            s.send_email(
                subject=f"Comprobantes Fiscales {receptor_nombre} - {receptor_rfc}",
                to_addrs=to_addrs,
                html=message,
                file_attachments=[
                    invoice.filename + ".xml",
                    invoice.filename + ".pdf"
                ]
            )
            logger.info(f"Correo Enviado: {invoice.name} {receptor_rfc} {to_addrs}")
            window.read(timeout=0)
            invoice.notified = ",".join(to_addrs)


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
                case "validate_clientes":
                    res = sg.popup(
                        f"Estas seguro que quieres validar {len(clients)} clientes?",
                        title=window[event].ButtonText,
                        button_type=POPUP_BUTTONS_OK_CANCEL,
                    )
                    if res == "OK":
                        for rfc, details in clients.items():
                            log_line(f"VALIDANDO {rfc}")
                            window.read(timeout=0)
                            validar_client(rfc, details)
                        log_line("FIN")
                    else:
                        log_line("OPERACION CANCELADA")

                case "validate_invoices":
                    facturas = generate_ingresos(values)
                    if facturas:
                        invoice_button_manager.set_invoices(
                            facturas
                        )

                case "prepare_pago":
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
                        log_line("FIN")
                    else:
                        log_line("OPERACION CANCELADA")

                case "prepare_correos":
                    all_invoices = get_all_cfdi()
                    cfdi_correos = [i for i in all_invoices.values() if not i.notified]
                    if cfdi_correos:
                        email_button_manager.set_invoices(
                            cfdi_correos
                        )
                    else:
                        logger.info("No hay correos pendientes de enviar")

                case "enviar_correos":
                    res = sg.popup(
                        f"Estas seguro que quieres enviar {len(emails_to_send)} correos?",
                        title=window[event].ButtonText,
                        button_type=POPUP_BUTTONS_OK_CANCEL
                    )
                    if res == "OK":
                        enviar_correos(emails_to_send)
                        log_line("FIN")
                    else:
                        log_line("OPERACION CANCELADA")

                case "status_sat":
                    i = find_factura(values["factura_pagar"])
                    if i:
                        estado = cancelados_manager.get_state(i, only_cache=False)
                        logger.info_yaml(estado)

                case "facturas_pendientes":
                    all_invoices = get_all_cfdi()

                    fac_pen = filter_invoices_by(
                        invoices=all_invoices,
                        # fecha=lambda x: x < dp,
                        invoice_type=InvoiceType.PAYMENT_PENDING,
                        rfc_emisor=EMISOR.rfc,
                        estatus='1'
                    )
                    for i in fac_pen:
                        f = {
                            'Receptor': Code(i['Receptor']['Rfc'], i['Receptor']['Nombre']),
                            'Factura': f"{i.name} - {i.uuid}",
                            'SaldoPendiente': i.saldo_pendiente
                        }
                        logger.info_yaml(f)

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
    resizable=True
)

ch = LogHandler(window['console'])
ch.setLevel(logging.INFO)
logging.getLogger().addHandler(ch)

main_loop()
window.close()
