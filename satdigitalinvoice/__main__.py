import base64
import io
import itertools
import logging
import os
from datetime import timedelta, date
from zipfile import ZipFile

from PySimpleGUI import POPUP_BUTTONS_OK_CANCEL, PySimpleGUI
from satcfdi import DatePeriod
from satcfdi.accounting import EmailManager
from satcfdi.exceptions import ResponseError, DocumentNotFoundError
from satcfdi.pacs import Accept
from satcfdi.pacs.sat import SAT, TipoDescargaMasivaTerceros, EstadoSolicitud
from satcfdi.printer import Representable
# noinspection PyUnresolvedReferences
from satcfdi.transform.catalog import CATALOGS
from tabulate import tabulate

from . import __version__
from .client_validation import validar_client
from .environments import environment_default
from .file_data_managers import ClientsManager, ConfigManager, FacturasManager
from .gui_functions import generate_ingresos, pago_factura, exportar_facturas, facturas_filename, \
    periodo_desc, generate_html_template, mf_pago_fmt, print_invoices, print_cfdis, print_cfdi_details, ajustes, ajustes_directory
from .layout import make_layout, ActionButtonManager
from .local import LocalDBSatCFDI
from .log_tools import log_line, log_item, cfdi_header, header_line, print_yaml
from .mycfdi import get_all_cfdi, MyCFDI, move_to_folder, PPD, PUE
from .utils import random_string, to_uuid, add_file_handler, parse_date_period, parse_ym_date, load_certificate

logging.getLogger("weasyprint").setLevel(logging.ERROR)
logging.getLogger("fontTools").setLevel(logging.ERROR)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

ACTION_FACTURAS = "facturas"
ACTION_EMAILS = "emails"
ACTION_CLIENTS = "clients"
ACTION_AJUSTES = "ajustes"

template = environment_default.get_template(
    'mail_facturas_template.html'
)


def open_launch_window():
    layout = [[PySimpleGUI.Text("New Window", key="new")]]
    window = PySimpleGUI.Window("Launch Window", layout, modal=True, size=(300, 300))
    window.read(timeout=1000)

    return window


class FacturacionGUI:
    def __init__(self, debug=False):
        # set up logging
        if debug:
            logging.basicConfig(level=logging.ERROR)
        add_file_handler()

        self.email_manager = None
        self.pac_service = None
        self.fiel_signer = None  # SAT(signer=fiel_signer )
        self.csd_signer = None
        self.sat_service = None
        self.rfc_prediales = None

        self.window = PySimpleGUI.Window(
            f"Facturación Masiva CFDI 4.0",  # {self.csd_signer.rfc}
            make_layout(True),
            size=(1280, 800),
            resizable=True,
            font=("Courier New", 10, "bold"),
        )

        self.all_invoices = None
        self.serie = None

        # noinspection PyTypeChecker
        self.local_db = None  # type: LocalDBSatCFDI

        self.action_button_manager = ActionButtonManager(self.window["crear_facturas"])
        self.console = self.window["console"]

    @staticmethod
    def read_config():
        return ConfigManager()

    def prepare(self, config):
        self.local_db = LocalDBSatCFDI(
            enviar_a_partir=config['enviar_a_partir'],
            saldar_a_partir=config['saldar_a_partir']
        )
        self.email_manager = EmailManager(
            **config['email']
        )
        self.csd_signer = load_certificate(
            config['csd'],
        ) if 'csd' in config else None

        self.fiel_signer = load_certificate(
            config['fiel'],
        ) if 'fiel' in config else None

        self.sat_service = SAT(signer=self.fiel_signer)
        pac = config['pac']
        pac_module, pac_class = pac['type'].split(".")
        mod = __import__(f"satcfdi.pacs.{pac_module}", fromlist=[pac_class])
        self.pac_service = getattr(mod, pac_class)(
            **pac['args']
        )
        self.serie = config['serie']
        self.window['serie'].update(self.serie)
        MyCFDI.local_db = self.local_db

    def initial_screen(self, emisor_cif):
        log_line("Acerca De")
        print_yaml({
            "version": __version__.__version__,
            "facturacion": "CFDI 4.0",
            "emisor": emisor_cif,
            "pac_service": {
                "Type": type(self.pac_service).__name__,
                "Rfc": self.pac_service.RFC,
                "Environment": str(self.pac_service.environment)
            }
        })

    def run(self):
        self.window.finalize()

        # Add logging to the window
        h = logging.StreamHandler(self.window['console'])
        h.setLevel(logging.INFO)
        logging.root.addHandler(h)

        try:
            config = self.read_config()
            self.prepare(config)
        except Exception:
            logger.exception(header_line("ERROR"))
            for e in self.window.element_list():
                if isinstance(e, PySimpleGUI.Button):
                    e.update(disabled=True)
                if isinstance(e, PySimpleGUI.Input):
                    e.update("", disabled=True)
            self.window.read()
            self.window.close()
            return

        self.window['factura_pagar'].bind("<Return>", "_enter")
        self.window['periodo'].bind("<Return>", "_enter")
        self.window['importe_pago'].bind("<Return>", "_enter")
        self.window['fecha_pago'].bind("<Return>", "_enter")
        self.window['inicio'].bind("<Return>", "_enter")
        self.window['final'].bind("<Return>", "_enter")
        self.window['forma_pago'].bind("<Return>", "_enter")
        # self.window['console'].bind('<Button-3>', '_double_click')

        self.main_loop()
        self.window.close()

    def get_all_invoices(self):
        if self.all_invoices:
            return self.all_invoices
        self.all_invoices = get_all_cfdi()
        return self.all_invoices

    def generate_invoice(self, invoice):
        ref_id = random_string()
        attempts = 3
        for i in range(attempts):
            if i:
                print(f'Intentando de nuevo... Intento {i + 1} de {attempts}')
                self._read(timeout=2000 * i)

            try:
                res = self.pac_service.stamp(
                    cfdi=invoice,
                    accept=Accept.XML_PDF,
                    ref_id=ref_id
                )
            except Exception as ex:
                logger.error(f"Error Generando: {invoice.get('Serie')}{invoice.get('Folio')} {invoice['Receptor']['Rfc']}")
                if isinstance(ex, ResponseError):
                    logger.error(f"Status Code: {ex.response.status_code}")
                    logger.error(f"Response: {ex.response.text}")
                continue

            self.set_folio(int(res['Folio']) + 1)
            return move_to_folder(res.xml, pdf_data=res.pdf)

    def set_folio(self, folio: int):
        self.local_db.folio_set(folio)
        self.window['folio'].update(folio)

    def enviar_correos(self, emisor_cif, emails):
        with self.email_manager.sender as s:
            for receptor, notify_invoices, pendientes_meses_anteriores in emails:
                attachments = []
                for r in notify_invoices:
                    attachments += [r.filename + ".xml", r.filename + ".pdf"]

                subject = f"Comprobantes Fiscales {receptor['RazonSocial']} - {receptor['Rfc']}"
                s.send_email(
                    subject=subject,
                    to_addrs=receptor["Email"],
                    html=generate_html_template(
                        'mail_facturas_template.html',
                        fields={
                            "facturas": notify_invoices,
                            'pendientes_meses_anteriores': pendientes_meses_anteriores,
                            'emisor': emisor_cif,
                        },
                    ),
                    file_attachments=attachments
                )
                for r in notify_invoices:
                    r.notified = True

                print_yaml({
                    "correo_enviado": subject,
                    'facturas': [f"{i.name} - {i.uuid}" for i in notify_invoices],
                    'pendientes_meses_anteriores': [f"{i.name} - {i.uuid}" for i in pendientes_meses_anteriores],
                    "correos": receptor["Email"]
                })
                self._read()

    def recupera_comprobantes(self, id_solicitud):
        response = self.sat_service.recover_comprobante_status(
            id_solicitud=id_solicitud
        )
        print_yaml(response)
        self._read()
        if response["EstadoSolicitud"] == EstadoSolicitud.Terminada:
            for id_paquete in response['IdsPaquetes']:
                response, paquete = self.sat_service.recover_comprobante_download(
                    id_paquete=id_paquete
                )
                print_yaml(response)
                self._read()
                yield id_paquete, base64.b64decode(paquete) if paquete else None

    def unzip_cfdi(self, file):
        with ZipFile(file, "r") as zf:
            for fileinfo in zf.infolist():
                xml_data = zf.read(fileinfo)
                move_to_folder(xml_data, pdf_data=None)
                self._read()

    def _read(self, timeout=0):
        event, values = self.window.read(timeout=timeout)
        if event in ("Exit", PySimpleGUI.WIN_CLOSED):
            exit(0)

    def factura_uuid(self, text):
        return self.get_all_invoices().get(to_uuid(text))

    def factura_buscar(self, text):
        if text:
            emisor_rfc = self.csd_signer.rfc
            res = None
            for i in self.get_all_invoices().values():
                if i.name == text and i["Emisor"]["Rfc"] == emisor_rfc:
                    if res:
                        logger.info(f"Multiples Facturas Encontradas con el mismo nombre: {text}")
                        return
                    res = i
            if res:
                return res
        logger.info(f"Factura No Encontrada {text}")

    def action_button(self, action_name, action_items):
        if action_name == ACTION_FACTURAS:
            self.all_invoices = None
            for invoice in action_items:
                cfdi = self.generate_invoice(invoice=invoice)
                if cfdi is None:
                    break
                print_yaml({
                    "FacturaGenerada": cfdi_header(cfdi),
                })
                self._read()
        elif action_name == ACTION_EMAILS:
            clients = ClientsManager()
            emisor_cif = clients[self.csd_signer.rfc]
            self.enviar_correos(emisor_cif, action_items)
        elif action_name == ACTION_CLIENTS:
            for rfc, details in action_items.items():
                print(f"Validando: {rfc}")
                self._read()
                validar_client(rfc, details)

    def show(self, factura):
        i = factura
        self.window["ver_factura"].update(disabled=not i)
        if i:
            estado = self.local_db.status_sat(i).get('Estado', 'Vigente')
            self.window["status_sat"].update(
                estado,
                visible=True,
                button_color="red4" if estado != "Vigente" else "green",
            )
        else:
            self.window["status_sat"].update(
                visible=False
            )

        # Email
        is_enviable = i \
                      and i["Emisor"]["Rfc"] == self.csd_signer.rfc \
                      and i["Fecha"] >= self.local_db.enviar_a_partir \
                      and i.estatus == "1"
        if is_enviable:
            self.window["email_notificada"].update(
                "Por Enviar" if self.local_db.notificar(i) else " Enviada  ",
                visible=True,
                button_color="red4" if self.local_db.notificar(i) else "green",
            )
        else:
            self.window["email_notificada"].update("", visible=False)

        # Pendiente de Pago
        is_pendientable = i \
                          and i["Emisor"]["Rfc"] == self.csd_signer.rfc \
                          and i["TipoDeComprobante"] == "I" \
                          and i["Fecha"] >= self.local_db.saldar_a_partir[i['MetodoPago']] \
                          and i.estatus == "1" \
                          and (i["MetodoPago"] == PUE or i.saldo_pendiente) \
                          and i["Total"]
        if is_pendientable:
            self.window["pendiente_pago"].update(
                "Por Saldar" if self.local_db.saldar(i) else " Saldada  ",
                visible=True,
                button_color="red4" if self.local_db.saldar(i) else "green",
            )
        else:
            self.window["pendiente_pago"].update("", visible=False)

        # PPD
        is_ppd_active = i \
                        and i.get("MetodoPago") == PPD \
                        and i.estatus == "1" \
                        and i["Emisor"]["Rfc"] == self.csd_signer.rfc
        self.window["prepare_pago"].update(disabled=not is_ppd_active)
        self.window["fecha_pago_select"].update(disabled=not is_ppd_active)
        self.window["fecha_pago"].update(disabled=not is_ppd_active)
        self.window["importe_pago"].update(disabled=not is_ppd_active)
        self.window["forma_pago"].update(disabled=not is_ppd_active)

        if i:
            self.print_cfdi(i)

    def print_cfdi(self, cfdi):
        i = cfdi
        if self.window['detallado'].get():
            print_yaml(i)
            self.local_db.describe(i)
        else:
            print_invoices([
                [
                    "",
                    i['Receptor']['Nombre'][0:36],
                    i['Receptor']['Rfc'],
                    i.name,
                    i["Fecha"].strftime("%Y-%m-%d"),
                    self.local_db.saldar(i),
                    mf_pago_fmt(i),
                    i.uuid,
                    self.info_fmt(i)
                ]
            ])
            print()
            print_cfdi_details(i)

    def info_fmt(self, cfdi):
        i = cfdi
        return "🗙" if i.estatus == '0' else ("📧" if self.local_db.notificar(i) else "")

    def main_loop(self):
        factura_seleccionada = None  # type: MyCFDI | None
        self.set_folio(self.local_db.folio())

        while True:
            event, values = self.window.read()
            try:
                if event in ("Exit", PySimpleGUI.WIN_CLOSED):
                    return

                if event == "folio":
                    try:
                        self.set_folio(int(values["folio"]))
                    except ValueError:
                        print("El folio debe ser un número entero")
                        self.set_folio(self.local_db.folio())
                    continue

                if event not in ("crear_facturas", "enviar_correos", "confirm_pago_button", "ver_factura", "ver_excel", "pendiente_pago", "ver_carpeta_ajustes"):
                    self.console.update("")
                action_name, action_items = self.action_button_manager.clear()

                if event not in ("factura_pagar", "buscar_factura", 'factura_pagar_enter', "prepare_pago",
                                 "ver_factura", "status_sat", "pendiente_pago", "email_notificada",
                                 "fecha_pago", "forma_pago", "importe_pago", "importe_pago_enter", "fecha_pago_enter", "forma_pago_enter"):
                    factura_seleccionada = None
                    self.show(factura_seleccionada)

                match event:
                    case "about":
                        clients = ClientsManager()
                        self.initial_screen(clients[self.csd_signer.rfc])

                    case "factura_pagar" | "buscar_factura" | 'factura_pagar_enter':
                        if event in ("buscar_factura", 'factura_pagar_enter'):
                            log_line("Buscar Factura")

                        text = values["factura_pagar"].strip()
                        factura_seleccionada = self.factura_uuid(text)
                        if event == "factura_pagar" and factura_seleccionada:
                            log_line("Buscar Factura")

                        if event in ("buscar_factura", 'factura_pagar_enter') and not factura_seleccionada:
                            factura_seleccionada = self.factura_buscar(text)

                        self.window["descarga"].update(disabled=not to_uuid(text))
                        self.show(factura_seleccionada)

                    case "preparar_ajuste_anual":
                        log_line(f"AJUSTES")
                        ajustes(
                            emisor_rfc=self.csd_signer.rfc,
                            ym_date=parse_ym_date(values['periodo'])
                        )

                    case "recuperar_emitidas" | "recuperar_recibidas":
                        log_line("RECUPERAR")
                        fecha_final = date.today()
                        fecha_inicial = fecha_final - timedelta(days=int(values["recuperar_dias"]))
                        id_solicitud = self.local_db.get(event)

                        if not id_solicitud:
                            self._read()
                            response = self.sat_service.recover_comprobante_request(
                                fecha_inicial=fecha_inicial,
                                fecha_final=fecha_final,
                                rfc_receptor=self.sat_service.signer.rfc if "recuperar_recibidas" == event else None,
                                rfc_emisor=self.sat_service.signer.rfc if "recuperar_emitidas" == event else None,
                                tipo_solicitud=TipoDescargaMasivaTerceros.CFDI,
                            )
                            print_yaml(response)
                            self.local_db[event] = response['IdSolicitud']
                            print("Nueva Solicitud Creada")
                        else:
                            print_yaml({
                                'IdSolicitud': id_solicitud
                            })
                            self._read()
                            for paquete_id, data in self.recupera_comprobantes(id_solicitud):
                                if data:
                                    self.all_invoices = None
                                    with io.BytesIO(data) as b:
                                        self.unzip_cfdi(b)
                                del self.local_db[event]
                            log_line("FIN")

                    case "prepare_clientes":
                        log_line("CLIENTES")
                        clients = ClientsManager()
                        ym_date = parse_ym_date(values['periodo'])
                        if clients:
                            facturas = FacturasManager(ym_date)["Facturas"]
                            print(
                                tabulate(
                                    [
                                        [
                                            i,
                                            client["RazonSocial"][:36],
                                            client["Rfc"],
                                            client["RegimenFiscal"].code,
                                            client["CodigoPostal"],
                                            sum(1 for f in facturas if f["Receptor"] == k) or None
                                        ]
                                        for i, (k, client) in enumerate(clients.items(), start=1)
                                    ],
                                    headers=(
                                        "",
                                        "Razon Social",
                                        "Rfc",
                                        "Reg",
                                        "CP",
                                        "Facturas"
                                    ),
                                    colalign=("right", "left", "left", "left", "left", "right"),
                                )
                            )
                            self.action_button_manager.set_items(ACTION_CLIENTS, clients)
                        else:
                            print("No hay clientes")

                    case "prepare_facturas" | "incio_enter" | "final_enter":
                        ym_date = parse_ym_date(values["periodo"])
                        log_line(f"PREPARAR FACTURAS {values['periodo']}")
                        print('Periodo:', periodo_desc(ym_date, 'Mensual.1'), '[AL ...]')

                        inicio = int(values["inicio"])
                        final = int(values["final"]) if values["final"].isdigit() else None

                        facturas = generate_ingresos(
                            folio=int(values["folio"]),
                            serie=self.serie,
                            clients=ClientsManager(),
                            facturas=FacturasManager(ym_date)["Facturas"],
                            inicio=inicio,
                            final=final,
                            ym_date=ym_date,
                            csd_signer=self.csd_signer
                        )
                        if facturas:
                            if self.window['detallado'].get():
                                for i, cfdi in enumerate(facturas, start=inicio):
                                    log_item(f"FACTURA NUMERO: {i}")
                                    print_yaml(cfdi)
                            else:
                                print_cfdis(facturas, start=inicio)
                            self.action_button_manager.set_items(ACTION_FACTURAS, facturas)
                        else:
                            print("No hay facturas para este mes")

                    case "prepare_pago" | "importe_pago_enter" | "fecha_pago_enter" | "forma_pago_enter":
                        log_line("COMPROBANTE PAGO")
                        if i := factura_seleccionada:
                            cfdi = pago_factura(
                                serie=self.serie,
                                folio=int(values["folio"]),
                                factura_pagar=i,
                                fecha_pago=values["fecha_pago"],
                                forma_pago=values["forma_pago"],
                                importe_pago=values["importe_pago"],
                                csd_signer=self.csd_signer
                            )
                            if cfdi:
                                if self.window['detallado'].get():
                                    log_item(f"FACTURA NUMERO: 1")
                                    print_yaml(cfdi)
                                else:
                                    print_cfdis([cfdi], start=1)
                                    print_cfdi_details(cfdi)
                                self.action_button_manager.set_items(ACTION_FACTURAS, [cfdi])

                    case "ver_factura":
                        if i := factura_seleccionada:
                            os.startfile(
                                os.path.abspath(i.filename + ".pdf")
                            )

                    case "status_sat":
                        log_line("STATUS")
                        if i := factura_seleccionada:
                            estado = self.local_db.status_sat(i, update=True)
                            print_yaml(estado)
                            self.local_db.describe(i)

                    case "pendiente_pago":
                        if i := factura_seleccionada:
                            st = self.local_db.saldar_flip(i)
                            self.console.update("")
                            log_line(self.window[event].ButtonText.upper())
                            self.show(i)
                            print(f"FACTURA MARCADA COMO {'-NO- ' if st else ''}SALDADA")

                    case "email_notificada":
                        if i := factura_seleccionada:
                            st = self.local_db.notificar_flip(i)
                            self.console.update("")
                            log_line(self.window[event].ButtonText.upper())
                            self.show(i)
                            print(f"FACTURA MARCADA COMO {'-NO- ' if st else ''}NOTIFICADA")

                    case "prepare_correos":
                        log_line("CORREOS")
                        now = date.today()
                        dp = DatePeriod(now.year, now.month)
                        clients = ClientsManager()
                        a_invoices = self.get_all_invoices()

                        cfdi_correos = []
                        for receptor_rfc, notify_invoices in itertools.groupby(
                                sorted(
                                    (i for i in a_invoices.values() if i.estatus == "1" and self.local_db.notificar(i)),
                                    key=lambda r: r["Receptor"]["Rfc"]
                                ),
                                lambda r: r["Receptor"]["Rfc"]
                        ):
                            notify_invoices = list(notify_invoices)

                            def fac_iter():
                                for i in self.get_all_invoices().values():
                                    if i["Emisor"]["Rfc"] == self.csd_signer.rfc \
                                            and i["TipoDeComprobante"] == "I" \
                                            and i.estatus == '1' \
                                            and self.local_db.saldar(i) \
                                            and i["Fecha"] < dp \
                                            and i["Receptor"]["Rfc"] == receptor_rfc:
                                        yield i

                            fac_pen = sorted(
                                fac_iter(),
                                key=lambda r: r["Fecha"]
                            )
                            receptor = clients[receptor_rfc]
                            cfdi_correos.append((receptor, notify_invoices, fac_pen))

                        if cfdi_correos:
                            print(tabulate(
                                [
                                    [
                                        i,
                                        receptor["RazonSocial"][0:36],
                                        receptor["Rfc"],
                                        ",".join(n.name for n in notify_invoices),
                                        ",".join(n.name for n in facturas_pendientes)
                                    ] for i, (receptor, notify_invoices, facturas_pendientes) in enumerate(cfdi_correos, start=1)
                                ],
                                headers=(
                                    '',
                                    'Receptor Razon Social',
                                    'Recep. Rfc',
                                    'Facturas',
                                    'Pendientes Emitidas Meses Anteriores'
                                ),
                                disable_numparse=True,
                                colalign=("right", "left", "left", "left", "left")
                            ))

                            self.action_button_manager.set_items(ACTION_EMAILS, cfdi_correos)
                        else:
                            print("No hay correos pendientes de enviar")

                    case "crear_facturas":
                        log_line(f"PROCESAR {action_name.upper()}")
                        res = PySimpleGUI.popup(
                            f"Estas seguro que quieres crear {len(action_items)} {action_name}?",
                            title=self.window[event].ButtonText,
                            button_type=POPUP_BUTTONS_OK_CANCEL,
                        )
                        if res == "OK":
                            self.action_button(action_name, action_items)
                            print("FIN")
                        else:
                            print("OPERACION CANCELADA")

                    case "facturas_pendientes":
                        log_line("FACTURAS PENDIENTES")

                        def fac_iter():
                            for i in self.get_all_invoices().values():
                                if i["Emisor"]["Rfc"] == self.csd_signer.rfc \
                                        and i["TipoDeComprobante"] == "I" \
                                        and i.estatus == '1' \
                                        and self.local_db.saldar(i):
                                    yield i

                        rows = []
                        n = 0

                        def inc():
                            nonlocal n
                            n += 1
                            return n

                        for receptor_rfc, fac_pen in itertools.groupby(
                                sorted(
                                    fac_iter(),
                                    key=lambda r: r["Receptor"]["Rfc"]
                                ),
                                lambda r: r["Receptor"]["Rfc"]
                        ):
                            for v, i in enumerate(fac_pen):
                                rows.append([
                                    inc(),
                                    i['Receptor']['Nombre'][0:36] if v == 0 else '*',
                                    receptor_rfc if v == 0 else '*',
                                    i.name,
                                    i["Fecha"].strftime("%Y-%m-%d"),
                                    self.local_db.saldar(i),
                                    mf_pago_fmt(i),
                                    i.uuid,
                                    self.info_fmt(i)
                                ])

                        if rows:
                            print_invoices(rows)
                        else:
                            print("No hay facturas pendientes")

                    case "descarga":
                        log_line('DESCARGADA')
                        try:
                            res = self.pac_service.recover(values["factura_pagar"], accept=Accept.XML_PDF)
                            self.all_invoices = None
                            cfdi = move_to_folder(res.xml, pdf_data=res.pdf)
                            cfdi = self.get_all_invoices()[to_uuid(cfdi["Complemento"]["TimbreFiscalDigital"]["UUID"])]
                            self.show(cfdi)
                        except DocumentNotFoundError:
                            logger.info("Factura no encontrada")

                    case "ver_excel":
                        log_line("EXCEL")
                        clients = ClientsManager()
                        emisor_cif = clients[self.csd_signer.rfc]
                        exportar_facturas(
                            self.get_all_invoices(),
                            parse_date_period(values["periodo"]),
                            emisor_cif,
                            self.rfc_prediales
                        )

                        archivo_excel = facturas_filename(parse_date_period(values["periodo"]))
                        os.startfile(
                            os.path.abspath(archivo_excel)
                        )

                    case "facturas_emitidas" | "periodo_enter":
                        log_line(f"FACTURAS EMITIDAS {values['periodo']}")
                        dp = parse_date_period(values["periodo"])

                        def fact_iter():
                            for i in self.get_all_invoices().values():
                                if i["Emisor"]["Rfc"] == self.csd_signer.rfc \
                                        and i["Fecha"] == dp:
                                    yield i

                        fact_iter = list(fact_iter())
                        if fact_iter:
                            print_invoices([
                                [
                                    e,
                                    i['Receptor']['Nombre'][0:36],
                                    i['Receptor']['Rfc'],
                                    i.name,
                                    i["Fecha"].strftime("%Y-%m-%d"),
                                    self.local_db.saldar(i),
                                    mf_pago_fmt(i),
                                    i.uuid,
                                    self.info_fmt(i)
                                ]
                                for e, i in enumerate(fact_iter, start=1)
                            ])
                        else:
                            print("No hay facturas emitidas para {}".format(dp))

                    case "ver_html":
                        log_line("HTML")
                        dp = parse_date_period(values["periodo"])

                        def fact_iter():
                            for i in self.get_all_invoices().values():
                                if i["Emisor"]["Rfc"] == self.csd_signer.rfc \
                                        and i["Fecha"] == dp:
                                    yield i

                        outfile = facturas_filename(dp, ext="html")
                        Representable.html_write_all(
                            objs=fact_iter(),
                            target=outfile,
                        )
                        os.startfile(
                            os.path.abspath(outfile)
                        )

                    case "ver_carpeta":
                        archivo = facturas_filename(parse_date_period(values["periodo"]))
                        os.startfile(
                            os.path.abspath(os.path.dirname(archivo))
                        )

                    case "ver_carpeta_ajustes":
                        ajustes_dir = ajustes_directory(parse_ym_date(values['periodo']))
                        os.startfile(
                            os.path.abspath(ajustes_dir)
                        )

                    case "periodo" | "inicio" | "final" | "fecha_pago" | "forma_pago" | "importe_pago" | ' ':
                        pass

                    case _:
                        logger.error(f"Unknown event '{event}'")

            except Exception as ex:
                logger.exception(header_line("ERROR"))
