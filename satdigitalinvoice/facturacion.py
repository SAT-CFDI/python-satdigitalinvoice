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

from . import __version__, PPD, PUE
from .client_validation import validar_client
from .file_data_managers import ClientsManager, FacturasManager
from .gui_functions import generate_ingresos, pago_factura, exportar_facturas, facturas_filename, \
    periodo_desc, generate_html_template, mf_pago_fmt, print_invoices, print_cfdis, print_cfdi_details, ajustes, ajustes_directory
from .layout import make_layout, ActionButtonManager
from .localdb import LocalDBSatCFDI, LiquidatedState
from .log_tools import log_line, log_item, cfdi_header, header_line, print_yaml
from .mycfdi import get_all_cfdi, MyCFDI, move_to_folder
from .utils import random_string, to_uuid, parse_date_period, parse_ym_date, load_certificate, to_int, cert_info

logging.getLogger("weasyprint").setLevel(logging.ERROR)
logging.getLogger("fontTools").setLevel(logging.ERROR)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

ACTION_FACTURAS = "facturas"
ACTION_EMAILS = "emails"
ACTION_CLIENTS = "clients"
ACTION_AJUSTES = "ajustes"


def open_launch_window():
    layout = [[PySimpleGUI.Text("New Window", key="new")]]
    window = PySimpleGUI.Window("Launch Window", layout, modal=True, size=(300, 300))
    window.read(timeout=1000)

    return window


class FacturacionGUI:
    def __init__(self, config):
        self.email_manager = EmailManager(
            **config['email']
        )
        pac = config['pac']
        pac_module, pac_class = pac['type'].split(".")
        mod = __import__(f"satcfdi.pacs.{pac_module}", fromlist=[pac_class])
        self.pac_service = getattr(mod, pac_class)(
            **pac['args']
        )
        self.serie = config['serie']
        self.csd_signer = load_certificate(config.get('csd')) if 'csd' in config else None
        self.fiel_signer = load_certificate(config.get('fiel')) if 'fiel' in config else None

        self.sat_service = SAT(signer=self.fiel_signer)
        self.rfc_prediales = config['rfc_prediales']

        self.window = PySimpleGUI.Window(
            f"Facturación Masiva CFDI 4.0 {self.csd_signer.rfc}",
            make_layout(bool(self.fiel_signer)),
            size=(1280, 800),
            resizable=True,
            font=("Courier New", 10, "bold"),
        )

        self.all_invoices = None
        self.local_db = LocalDBSatCFDI(
            enviar_a_partir=config['enviar_a_partir'],
            pagar_a_partir=config['pagar_a_partir']
        )
        # noinspection PyTypeChecker
        self.selected_satcfdi = None  # type: MyCFDI

        self.action_button_manager = ActionButtonManager(self.window["crear_facturas"])
        self.console = self.window["console"]

        MyCFDI.local_db = self.local_db

    def run(self):
        self.window.finalize()

        self.set_folio()
        self.window['serie'].update(self.serie)

        self.window['factura_pagar'].bind("<Return>", "_enter")
        self.window['periodo'].bind("<Return>", "_enter")
        self.window['importe_pago'].bind("<Return>", "_enter")
        self.window['fecha_pago'].bind("<Return>", "_enter")
        self.window['inicio'].bind("<Return>", "_enter")
        self.window['final'].bind("<Return>", "_enter")
        self.window['forma_pago'].bind("<Return>", "_enter")
        # self.window['console'].bind('<Button-3>', '_double_click')

        # Add logging to the window
        h = logging.StreamHandler(self.window['console'])
        h.setLevel(logging.INFO)
        logging.root.addHandler(h)

        self.main_loop()
        self.window.close()

    def initial_screen(self, emisor_cif):
        self.header("ACERCA DE")
        print_yaml({
            "version": __version__.__version__,
            "facturacion": "CFDI 4.0",
            "emisor": emisor_cif,
            "pac_service": {
                "Type": type(self.pac_service).__name__,
                "Rfc": self.pac_service.RFC,
                "Environment": str(self.pac_service.environment)
            },
            "fiel": cert_info(self.fiel_signer),
            "csd": cert_info(self.csd_signer),
        })

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

    def set_folio(self, folio: int = None):
        if folio:
            self.local_db.folio_set(folio)
            self.window['folio'].update(folio)
        else:
            self.window['folio'].update(self.local_db.folio())

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
                    self.local_db.notified_set(r.uuid, True)
                print_yaml({
                    "correo": subject,
                    "para": receptor["Email"]
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

    def set_selected_satcfdi(self, factura):
        i = factura
        self.selected_satcfdi = i
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
                      and i.estatus == "1"
        if is_enviable:
            self.window["email_notificada"].update(
                " Enviada  " if self.local_db.notified(i) else "Por Enviar",
                visible=True,
                button_color="green" if self.local_db.notified(i) else "red4",
            )
        else:
            self.window["email_notificada"].update("", visible=False)

        # Pendiente de Pago
        is_pendientable = i \
                          and i["Emisor"]["Rfc"] == self.csd_signer.rfc \
                          and i["TipoDeComprobante"] == "I" \
                          and i.estatus == "1" \
                          and (i["MetodoPago"] == PUE or i.saldo_pendiente) \
                          and i["Total"]
        if is_pendientable:
            self.window["pendiente_pago"].update(
                (" Pagada  " if i["MetodoPago"] == PUE else "Ignorada ") if self.local_db.liquidated(i) else "Por Pagar",
                visible=True,
                button_color="green" if self.local_db.liquidated(i) else "red4",
            )
        else:
            self.window["pendiente_pago"].update("", visible=False)

        # PPD
        is_ppd_active = i \
                        and i["Emisor"]["Rfc"] == self.csd_signer.rfc \
                        and i.get("MetodoPago") == PPD \
                        and i.estatus == "1" \
                        and i.saldo_pendiente
        self.window["prepare_pago"].update(disabled=not is_ppd_active)
        self.window["fecha_pago_select"].update(disabled=not is_ppd_active)
        self.window["fecha_pago"].update(disabled=not is_ppd_active)
        self.window["importe_pago"].update(disabled=not is_ppd_active)
        self.window["forma_pago"].update(disabled=not is_ppd_active)

    def print_satcfdis(self, cfdis):
        def info_fmt(i):
            return "" if self.local_db.notified(i) else "📧"

        if cfdis := sorted(cfdis, key=lambda i: (i["Fecha"], i.name), reverse=True):
            if self.window['detallado'].get():
                for i, cfdi in enumerate(cfdis, start=1):
                    log_item(f"FACTURA NUMERO: {i}")
                    print_yaml(cfdi)
                    self.local_db.describe(cfdi)
            else:
                print_invoices(
                    [
                        [
                            i,
                            cfdi['Receptor'].get('Nombre', '')[0:36],
                            cfdi['Receptor']['Rfc'],
                            cfdi.name,
                            cfdi["Fecha"].strftime("%Y-%m-%d"),
                            cfdi["Total"],
                            self.local_db.liquidated_state(cfdi),
                            mf_pago_fmt(cfdi),
                            cfdi.uuid,
                            info_fmt(cfdi)
                        ]
                        for i, cfdi in enumerate(cfdis, start=1)
                    ]
                )
            if len(cfdis) == 1:
                print_cfdi_details(cfdis[0])
                self.set_selected_satcfdi(cfdis[0])
            else:
                self.set_selected_satcfdi(None)
        else:
            print("No hay resultados")
            self.set_selected_satcfdi(None)

    def print_prepared_cfdis(self, cfdis, start=1):
        if cfdis:
            if self.window['detallado'].get():
                for i, cfdi in enumerate(cfdis, start=start):
                    log_item(f"FACTURA NUMERO: {i}")
                    print_yaml(cfdi)
            else:
                print_cfdis(cfdis, start=start)
            self.action_button_manager.set_items(ACTION_FACTURAS, cfdis)
        else:
            print("No hay facturas para este mes")

    def header(self, name, clear=True):
        if clear:
            self.console.update("")
        log_line(name)

    def main_loop(self):
        while True:
            event, values = self.window.read()
            try:
                if event in ("Exit", PySimpleGUI.WIN_CLOSED):
                    return

                action_name, action_items = self.action_button_manager.clear()

                if event in ("prepare_correos", "prepare_clientes", "prepare_facturas", "crear_facturas",
                             "inicio_enter", "final_enter", "preparar_ajuste_anual", "recuperar_emitidas", "recuperar_recibidas"):
                    self.set_selected_satcfdi([])

                match event:
                    case "folio":
                        self.set_folio(to_int(values["folio"]))

                    case "about":
                        clients = ClientsManager()
                        self.initial_screen(clients[self.csd_signer.rfc])

                    case "buscar_factura" | 'factura_pagar_enter':
                        self.header("Buscar Factura")

                        if search_text := values["factura_pagar"].strip().upper():
                            if len(search_text) < 3:
                                self.console.update("El texto de búsqueda debe tener al menos 3 caracteres")
                                continue

                            if search_uuid := to_uuid(search_text):
                                def fac_iter():
                                    if v := self.get_all_invoices().get(search_uuid):
                                        yield v
                            else:
                                def fac_iter():
                                    for i in self.get_all_invoices().values():
                                        if i["Emisor"]["Rfc"] == self.csd_signer.rfc and \
                                                (i.name == search_text or i["Receptor"]["Rfc"] == search_text or search_text in i["Receptor"].get("Nombre", "")):
                                            yield i

                            self.print_satcfdis(fac_iter())
                            self.window["descarga"].update(disabled=not search_uuid)

                    case "preparar_ajuste_anual":
                        self.header(f"AJUSTES")
                        ajustes(
                            emisor_rfc=self.csd_signer.rfc,
                            ym_date=parse_ym_date(values['periodo'])
                        )

                    case "recuperar_emitidas" | "recuperar_recibidas":
                        self.header("RECUPERAR")
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
                            print("FIN")

                    case "prepare_clientes":
                        self.header("CLIENTES")
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
                                            sum(1 for f in facturas if f["Receptor"] == k) or None,
                                            "; ".join(client["Email"])[0:72],
                                        ]
                                        for i, (k, client) in enumerate(clients.items(), start=1)
                                    ],
                                    headers=(
                                        "",
                                        "Razon Social",
                                        "Rfc",
                                        "Reg",
                                        "CP",
                                        "#",
                                        "Email",
                                    ),
                                    colalign=("right", "left", "left", "left", "left", "right"),
                                )
                            )
                            self.action_button_manager.set_items(ACTION_CLIENTS, clients)
                        else:
                            print("No hay clientes")

                    case "prepare_facturas" | "inicio_enter" | "final_enter":
                        ym_date = parse_ym_date(values["periodo"])
                        self.header(f"PREPARAR FACTURAS {values['periodo']}")
                        print('Periodo:', periodo_desc(ym_date, 'Mensual.1'), '[AL ...]')
                        inicio = int(values["inicio"])

                        if cfdis := generate_ingresos(
                            folio=int(values["folio"]),
                            serie=self.serie,
                            clients=ClientsManager(),
                            facturas=FacturasManager(ym_date)["Facturas"],
                            ym_date=ym_date,
                            csd_signer=self.csd_signer
                        ):
                            final = to_int(values["final"]) or len(cfdis)
                            cfdis = cfdis[max(inicio - 1, 0):max(final, 0)]

                        self.print_prepared_cfdis(cfdis, start=inicio)

                    case "prepare_pago" | "importe_pago_enter" | "fecha_pago_enter" | "forma_pago_enter":
                        self.header("COMPROBANTE PAGO")
                        if i := self.selected_satcfdi:
                            if cfdi := pago_factura(
                                    serie=self.serie,
                                    folio=int(values["folio"]),
                                    factura_pagar=i,
                                    fecha_pago=values["fecha_pago"],
                                    forma_pago=values["forma_pago"],
                                    importe_pago=values["importe_pago"],
                                    csd_signer=self.csd_signer
                            ):
                                self.print_prepared_cfdis([cfdi])
                                print_cfdi_details(cfdi)

                    case "ver_factura":
                        if i := self.selected_satcfdi:
                            os.startfile(
                                os.path.abspath(i.filename + ".pdf")
                            )

                    case "status_sat":
                        self.header("STATUS SAT")
                        if i := self.selected_satcfdi:
                            estado = self.local_db.status_sat(i, update=True)
                            self.print_satcfdis([i])
                            print_yaml(estado)

                    case "pendiente_pago":
                        if i := self.selected_satcfdi:
                            st = self.local_db.liquidated_flip(i)
                            self.console.update("")
                            self.header(self.window[event].ButtonText.upper())
                            self.print_satcfdis([i])
                            if i["MetodoPago"] == PUE:
                                print(f"FACTURA MARCADA COMO {'' if st else '-NO- '}PAGADA")
                            else:
                                print(f"FACTURA MARCADA COMO {'' if st else '-NO- '}IGNORADA")

                    case "email_notificada":
                        if i := self.selected_satcfdi:
                            st = self.local_db.notified_flip(i)
                            self.console.update("")
                            self.header(self.window[event].ButtonText.upper())
                            self.print_satcfdis([i])
                            print(f"FACTURA MARCADA COMO {'' if st else '-NO- '}NOTIFICADA")

                    case "prepare_correos":
                        self.header("CORREOS")
                        now = date.today()
                        dp = DatePeriod(now.year, now.month)
                        clients = ClientsManager()
                        a_invoices = self.get_all_invoices()

                        cfdi_correos = []
                        for receptor_rfc, notify_invoices in itertools.groupby(
                                sorted(
                                    (i for i in a_invoices.values() if i.estatus == "1" and not self.local_db.notified(i)),
                                    key=lambda r: r["Receptor"]["Rfc"]
                                ),
                                lambda r: r["Receptor"]["Rfc"]
                        ):
                            notify_invoices = list(notify_invoices)

                            def fac_iter():
                                for i in self.get_all_invoices().values():
                                    if i["Emisor"]["Rfc"] == self.csd_signer.rfc \
                                            and self.local_db.liquidated_state(i) == LiquidatedState.NO \
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
                        self.console.update(autoscroll=True)
                        self.header(f"PROCESAR {action_name.upper()}", clear=False)
                        res = PySimpleGUI.popup(
                            f"Estas seguro que quieres procesar {len(action_items)} {action_name}?",
                            title=self.window[event].ButtonText,
                            button_type=POPUP_BUTTONS_OK_CANCEL,
                        )
                        if res == "OK":
                            self.action_button(action_name, action_items)
                            print("FIN")
                        else:
                            print("OPERACION CANCELADA")
                        self.console.update(autoscroll=False)

                    case "facturas_pendientes":
                        self.header("FACTURAS PENDIENTES")

                        def fac_iter():
                            for i in self.get_all_invoices().values():
                                if i["Emisor"]["Rfc"] == self.csd_signer.rfc \
                                        and self.local_db.liquidated_state(i) == LiquidatedState.NO:
                                    yield i

                        self.print_satcfdis(fac_iter())

                    case "descarga":
                        self.header('DESCARGADA')
                        try:
                            res = self.pac_service.recover(values["factura_pagar"], accept=Accept.XML_PDF)
                            self.all_invoices = None
                            cfdi = move_to_folder(res.xml, pdf_data=res.pdf)
                            cfdi = self.get_all_invoices()[to_uuid(cfdi["Complemento"]["TimbreFiscalDigital"]["UUID"])]
                            self.print_satcfdis([cfdi])
                        except DocumentNotFoundError:
                            logger.info("Factura no encontrada")

                    case "ver_excel":
                        self.header("EXCEL")
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
                        self.header(f"FACTURAS EMITIDAS {values['periodo']}")
                        dp = parse_date_period(values["periodo"])

                        def fact_iter():
                            for i in self.get_all_invoices().values():
                                if i["Emisor"]["Rfc"] == self.csd_signer.rfc \
                                        and i["Fecha"] == dp:
                                    yield i

                        self.print_satcfdis(fact_iter())

                    case "ver_html":
                        self.header("HTML")
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
