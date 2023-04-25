import base64
import csv
import io
import itertools
import logging
import os
from datetime import date, datetime
from uuid import UUID
from zipfile import ZipFile

from PySimpleGUI import POPUP_BUTTONS_OK_CANCEL, PySimpleGUI as sg, POPUP_BUTTONS_NO_BUTTONS
from satcfdi import DatePeriod, csf
from satcfdi.accounting import EmailManager
from satcfdi.accounting.models import EstadoComprobante
from satcfdi.accounting.process import complement_invoices
from satcfdi.create.cfd import cfdi40
from satcfdi.exceptions import ResponseError
from satcfdi.pacs import Accept
from satcfdi.pacs.sat import SAT, EstadoSolicitud
# noinspection PyUnresolvedReferences
from satcfdi.transform.catalog import CATALOGS
from xlsxwriter.exceptions import XlsxFileError

from . import __version__, PPD, PUE, TEMP_DIRECTORY, ARCHIVOS_DIRECTORY, DATA_DIRECTORY, METADATA_FILE
from .client_validation import validar_client, clientes_generar_txt
from .environments import facturacion_environment
from .file_data_managers import ClientsManager, FacturasManager
from .gui_functions import generate_ingresos, pago_factura, exportar_facturas, archivos_folder, period_desc, parse_fecha_pago, parse_importe_pago, preview_cfdis, center_location, \
    CALENDAR_FECHA_FMT, ConsoleErrors, \
    generate_ajustes
from .layout import make_layout, ActionButtonManager, TipoRecuperar, SearchOptions
from .localdb import LocalDBSatCFDI, StatusState
from .log_tools import cfdi_header, header_line, print_yaml
from .mycfdi import MyCFDI
from .utils import random_string, to_date_period, load_certificate, to_int, cert_info, add_month, to_uuid, open_file, OS

logging.getLogger("weasyprint").setLevel(logging.ERROR)
logging.getLogger("fontTools").setLevel(logging.ERROR)

logger = logging.getLogger(__name__)


def open_launch_window():
    layout = [[sg.Text("New Window", key="new")]]
    window = sg.Window("Launch Window", layout, modal=True, size=(300, 300))
    window.read(timeout=1000)

    return window


class FacturacionGUI:
    def __init__(self, config):
        os.makedirs(TEMP_DIRECTORY, exist_ok=True)
        self.email_manager = EmailManager(
            **config['email']
        )
        pac = config['pac']
        pac_module, pac_class = pac['type'].split(".")
        mod = __import__(f"satcfdi.pacs.{pac_module}", fromlist=[pac_class])
        self.pac_service = getattr(mod, pac_class)(
            **pac['args']
        )
        self.csd_signer = load_certificate(config.get('csd')) if 'csd' in config else None
        self.fiel_signer = load_certificate(config.get('fiel')) if 'fiel' in config else None

        self.sat_service = SAT(signer=self.fiel_signer)
        self.rfc_prediales = config['rfc_prediales']

        self.all_invoices = None
        self.local_db = LocalDBSatCFDI(
            base_path=DATA_DIRECTORY,
            enviar_a_partir=config['enviar_a_partir'],
            pagar_a_partir=config['pagar_a_partir']
        )
        self.facturas_con_serie_folio = config.get('facturas_con_serie_folio', ('I', 'P'))

        MyCFDI.local_db = self.local_db
        MyCFDI.base_dir = ARCHIVOS_DIRECTORY

        self.window = sg.Window(
            f"Facturación Mensual CFDI 4.0 {self.csd_signer.rfc}",
            make_layout(bool(self.fiel_signer), self.local_db),
            size=(1280, 720),
            resizable=True,
            font=("Courier New", 10, "bold"),
            ttk_theme="default",
            margins=(0, 0),
            # use_custom_titlebar=True,
            titlebar_font=("Courier New", 11, "bold"),
            finalize=True,
        )

        self.action_button_manager = ActionButtonManager(
            button=self.window["crear_facturas"],
            preview=self.window["ver_preview"],
        )
        self.console = self.window["console"]

        self.set_serie()
        self.set_folio()

        self.window.bind("<FocusIn>", "_focus_in")
        self.window.bind("<FocusOut>", "_focus_out")

        for t in ('facturas_periodo', 'emitidas_search', 'ajustes_periodo', 'serie', 'folio'):
            self.window[t].bind("<Return>", "_enter")
            self.window[t].bind("<FocusOut>", "_enter", propagate=False)

        modifier_key = "Command" if OS.get_os() == OS.MACOS else "Control"

        for t in ('facturas_table', 'clientes_table', 'emitidas_table', 'correos_table', 'ajustes_table', 'solicitudes_table'):
            self.window[t].bind(f'<{modifier_key}-a>', '+select_all')
            self.window[t].bind('<BackSpace>', '+delete')  # BackSpace
            # self.window[t].bind('<Double-Button-1>', '_enter')
            self.window[t].bind('<Return>', '_enter')

    def run(self):
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
        if not self.all_invoices:
            self.all_invoices = MyCFDI.get_all_cfdi()
        return self.all_invoices

    def add_created_invoice(self, invoice: MyCFDI):
        self.all_invoices[invoice.uuid] = invoice
        complement_invoices(self.all_invoices, invoice)

    def generate_invoice(self, invoice):
        ref_id = random_string()

        # Add Serie and Folio and signature
        folio = None
        if invoice['TipoDeComprobante'] in self.facturas_con_serie_folio:
            invoice['Serie'] = self.local_db.serie()
            folio = self.local_db.folio()
            invoice['Folio'] = str(folio)

        cfdi40.Comprobante.sign(invoice, self.csd_signer)

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
                message = f"Error al generar factura: {invoice.get('Serie')}{invoice.get('Folio')} {invoice['Receptor']['Rfc']}"
                logger.exception(message)
                print(message)
                if isinstance(ex, ResponseError):
                    logger.error(f"Status Code: {ex.response.status_code}")
                    print(f"Status Code: {ex.response.status_code}")
                    logger.error(f"Response: {ex.response.text}")
                    print(f"Response: {ex.response.text}")
                continue

            if folio is not None:
                self.set_folio(folio + 1)
            cfdi = MyCFDI.move_to_folder(res.xml, pdf_data=res.pdf)
            self.add_created_invoice(cfdi)
            return cfdi

    def set_serie(self, serie: str = None):
        if serie:
            self.local_db.serie_set(serie)

        serie = serie or self.local_db.serie()
        self.window['serie'].update(serie)
        self.window['serie_folio'].update(f"{serie}{self.local_db.folio()}")

    def set_folio(self, folio: int = None):
        if folio:
            self.local_db.folio_set(folio)

        folio = folio or self.local_db.folio()
        self.window['folio'].update(folio)
        self.window['serie_folio'].update(f"{self.local_db.serie()}{folio}")

    def nueva_solicitud(self, values):
        tipo_recuperar = values["tipo_recuperar"]

        args = {
            'fecha_inicial': datetime.strptime(values["fecha_inicial"], CALENDAR_FECHA_FMT),
            'fecha_final': datetime.strptime(values["fecha_final"], CALENDAR_FECHA_FMT),
            'rfc_receptor': self.sat_service.signer.rfc if tipo_recuperar == TipoRecuperar.Recibidas else None,
            'rfc_emisor': self.sat_service.signer.rfc if tipo_recuperar == TipoRecuperar.Emitidas else None,
            'tipo_solicitud': values["tipo_solicitud"],
        }

        response = self.sat_service.recover_comprobante_request(
            **args
        )

        self.local_db.solicitud_merge(response["IdSolicitud"], request=args, response=response)

    def recupera_comprobantes(self, response):
        if response["EstadoSolicitud"] == EstadoSolicitud.Terminada:
            for id_paquete in response['IdsPaquetes']:
                r, paquete = self.sat_service.recover_comprobante_download(
                    id_paquete=id_paquete
                )
                print(f"paquete: {id_paquete}")
                print_yaml(r)
                if paquete:
                    data = base64.b64decode(paquete)
                    with io.BytesIO(data) as b:
                        self.unzip_cfdi(b)

    def unzip_cfdi(self, file):
        with ZipFile(file, "r") as zf:
            for fileinfo in zf.infolist():
                data = zf.read(fileinfo)
                match os.path.splitext(fileinfo.filename)[1]:
                    case ".xml":
                        self.all_invoices = None
                        MyCFDI.move_to_folder(data, pdf_data=None)
                    case ".pdf":
                        pass
                    case ".txt":
                        cfdi_metadata_reader = csv.reader(
                            (c.decode('utf-8') for c in data.splitlines() if c),
                            delimiter='~',
                            quotechar='|'
                        )
                        header = next(cfdi_metadata_reader)
                        for row in cfdi_metadata_reader:
                            row = dict(zip(header, row))
                            print_yaml(row)
                            self.local_db.status_merge(
                                uuid=row['Uuid'],
                                estatus=row['Estatus'],
                                fecha_cancelacion=row['FechaCancelacion']
                            )
                self._read()

    def _read(self, timeout=0):
        event, values = self.window.read(timeout=timeout)
        if event in ("Exit", sg.WIN_CLOSED):
            exit(0)

    def action_button(self, action_name, action_items):
        match action_name:
            case 'solicitudes':
                for solicitud in action_items:
                    id_solicitud = solicitud["response"]["IdSolicitud"]
                    response = self.sat_service.recover_comprobante_status(
                        id_solicitud=id_solicitud
                    )
                    print_yaml(response)
                    self.local_db.solicitud_merge(id_solicitud, response=response)
                    self.recupera_comprobantes(response)
                    self._read()

            case 'facturas' | 'pago':
                for invoice in action_items:
                    cfdi = self.generate_invoice(invoice=invoice)
                    if cfdi is None:
                        break
                    print_yaml({
                        "FacturaGenerada": cfdi_header(cfdi),
                    })
                    self._read()

            case 'correos':
                clients = ClientsManager()
                emisor = clients[self.csd_signer.rfc]
                with self.email_manager.sender as s:
                    for receptor, facturas, facturas_facturas_pendientes_meses_anteriores in action_items:

                        def attachments():
                            for ni in facturas:
                                yield ni.filename + ".xml"
                                yield ni.filename + ".pdf"

                        subject = f"Comprobantes Fiscales {receptor['RazonSocial']} - {receptor['Rfc']}"

                        s.send_email(
                            subject=subject,
                            to_addrs=receptor["Email"],
                            html=facturacion_environment.get_template('mail_facturas_template.html').render(
                                facturas=facturas,
                                facturas_pendientes_meses_anteriores=facturas_facturas_pendientes_meses_anteriores,
                                emisor=emisor,
                                receptor=receptor,
                            ),
                            file_attachments=attachments()
                        )
                        for r in facturas:
                            self.local_db.notified_set(r.uuid, True)
                        print_yaml({
                            "correo": subject,
                            "para": receptor["Email"]
                        })
                        self._read()

            case 'ajustes':
                clients = ClientsManager()
                emisor = clients[self.csd_signer.rfc]
                with self.email_manager.sender as s:
                    for data in action_items:
                        receptor = data['receptor']
                        file_name = data['file_name']
                        subject = f"Ajuste Renta {receptor['RazonSocial']} - {receptor['Rfc']}"

                        if not data['ajuste_porcentaje']:
                            print(f"NO HAY {subject}")
                            continue

                        s.send_email(
                            subject=subject,
                            to_addrs=receptor["Email"],
                            html=facturacion_environment.get_template('mail_ajustes_template.html').render(
                                emisor=emisor,
                                receptor=receptor,
                            ),
                            file_attachments=[file_name]
                        )
                        print_yaml({
                            "correo": subject,
                            "para": receptor["Email"]
                        })
                        self._read()

            case 'clientes':
                for client in action_items:
                    print(f"Validando: {client['Rfc']}")
                    validar_client(client)
                    self._read()

            case _:
                raise ValueError(f"Invalid action: {action_name}")

        print("FIN")

    def set_selected_satcfdis(self, cfdis: list):
        i = cfdis[0] if len(cfdis) == 1 else None

        if i:
            estatus = EstadoComprobante(i.estatus)
            self.window["status_sat"].update(
                estatus.name.center(10),
                disabled=False,
                button_color="red4" if estatus != EstadoComprobante.Vigente else "dark green",
            )
        else:
            self.window["status_sat"].update(
                "".ljust(10), disabled=True, button_color=sg.theme_background_color()
            )

        # Email
        is_active = \
            bool(i) \
            and i["Emisor"]["Rfc"] == self.csd_signer.rfc \
            and i.estatus == EstadoComprobante.Vigente
        if is_active:
            self.window["email_notificada"].update(
                "Enviada".center(10) if self.local_db.notified(i) else "Por Enviar",
                disabled=False,
                button_color="dark green" if self.local_db.notified(i) else "red4",
            )
        else:
            self.window["email_notificada"].update(
                "".ljust(10), disabled=True, button_color=sg.theme_background_color()
            )

        # Pendiente de Pago
        is_pendientable = \
            is_active \
            and i["TipoDeComprobante"] == "I" \
            and (i["MetodoPago"] == PUE or i.saldo_pendiente) \
            and i["Total"]
        if is_pendientable:
            self.window["pendiente_pago"].update(
                (("Pagada" if i["MetodoPago"] == PUE else "Ignorada")
                 if self.local_db.liquidated(i) else "Por Pagar").center(10),
                disabled=False,
                button_color=("dark green" if i["MetodoPago"] == PUE else "yellow4")
                if self.local_db.liquidated(i) else "red4",
            )
        else:
            is_ppd_pagada = is_active \
                            and i["TipoDeComprobante"] == "I" \
                            and i["MetodoPago"] == PPD \
                            and i.saldo_pendiente == 0
            if is_ppd_pagada:
                self.window["pendiente_pago"].update(
                    "Pagada".center(10),
                    disabled=True,
                    button_color="dark green",
                )
            else:
                self.window["pendiente_pago"].update(
                    "".ljust(10),
                    disabled=True,
                    button_color=sg.theme_background_color()
                )

        # PPD
        is_ppd_active = \
            is_active \
            and i["TipoDeComprobante"] == "I" \
            and i["MetodoPago"] == PPD \
            and i.saldo_pendiente > 0

        self.window["ppd_action_items"].update(visible=is_ppd_active)
        self.window["importe_pago"].update(i.saldo_pendiente if is_ppd_active else '')
        if is_ppd_active:
            self.action_button_manager.set_items("pago", [None])
        else:
            self.action_button_manager.clear()

    def header(self, name):
        self.window['console_tab'].select()
        self.console.update(header_line(name))
        self._read()

    def download_invoice(self, uuid: UUID):
        res = self.pac_service.recover(uuid, accept=Accept.XML_PDF)
        self.all_invoices = None
        return MyCFDI.move_to_folder(res.xml, pdf_data=res.pdf)

    def facturas_search(self):
        search_text = self.window["emitidas_search"].get()
        search_text = search_text.strip()

        if len(search_text) < 3:
            raise ValueError("Búsqueda debe de tener al menos 3 caracteres")

        def fact_iter():
            if search_text == SearchOptions.PorPagar:
                for i in self.get_all_invoices().values():
                    if i["Emisor"]["Rfc"] == self.csd_signer.rfc \
                            and self.local_db.liquidated_state(i) == StatusState.PENDING:
                        yield i
            elif search_text == SearchOptions.PorEnviar:
                for i in self.get_all_invoices().values():
                    if i["Emisor"]["Rfc"] == self.csd_signer.rfc \
                            and not self.local_db.notified(i) \
                            and i.estatus == EstadoComprobante.Vigente:
                        yield i
            elif date_search_text := to_date_period(search_text):
                for i in self.get_all_invoices().values():
                    if i["Emisor"]["Rfc"] == self.csd_signer.rfc \
                            and i["Fecha"] == date_search_text:
                        yield i
            elif uuid_search_text := to_uuid(search_text):
                if uuid_search_text not in self.get_all_invoices():
                    try:
                        self.download_invoice(uuid_search_text)
                    except ResponseError as e:
                        if e.response.status_code == 404:
                            self.error_message(f"Factura no encontrada en el PAC")
                        else:
                            raise e
                if c := self.get_all_invoices().get(uuid_search_text):
                    yield c
            else:
                up_search_text = search_text.upper()
                for i in self.get_all_invoices().values():
                    if i["Emisor"]["Rfc"] == self.csd_signer.rfc \
                            and (
                            i.name == up_search_text
                            or i["Receptor"]["Rfc"] == up_search_text
                            or up_search_text in i["Receptor"].get("Nombre", "")
                    ):
                        yield i

        self.window['emitidas_table'].update(
            values=list(fact_iter()),
        )

    def crear_pago(self, values):
        fecha_pago = parse_fecha_pago(values["fecha_pago"])
        importe_pago = parse_importe_pago(values["importe_pago"])
        self.window["importe_pago"].update(importe_pago)

        # noinspection PyUnresolvedReferences
        cfdi = pago_factura(
            factura_pagar=self.window["emitidas_table"].selected_items()[0],
            fecha_pago=fecha_pago,
            forma_pago=values["forma_pago"],
            importe_pago=importe_pago,
        )
        return [cfdi]

    def error_message(self, ex):
        sg.Popup(
            ex,
            no_titlebar=True,
            background_color="red4",
            location=center_location(self.window),
            button_type=POPUP_BUTTONS_NO_BUTTONS,
            auto_close=True,
            non_blocking=True,
        )

    def nuevas_facturas(self, values, force=False):
        facturas_table = self.window['facturas_table']
        has_value = bool(facturas_table.metadata)
        facturas_table.update(values=[])
        self.window['preparar_facturas_text'].update("")

        if has_value or force:
            dp = to_date_period(values["facturas_periodo"])
            if dp is None or dp.month is None:
                raise ValueError("Periodo no válido")

            self.window['preparar_facturas_text'].update(f"{period_desc(dp)}")

            cfdis = generate_ingresos(
                clients=ClientsManager(),
                facturas=FacturasManager(dp)["Facturas"],
                dp=dp,
                emisor_rfc=self.csd_signer.rfc
            )
            facturas_table.update(
                values=cfdis,
            )

    def nuevos_ajustes(self, values, force=False):
        ajustes_table = self.window['ajustes_table']
        has_value = bool(ajustes_table.metadata)
        ajustes_table.update(values=[])
        self.window['preparar_ajustes_text'].update("")

        if has_value or force:
            dp = to_date_period(values["ajustes_periodo"])
            if dp is None or dp.month is None:
                raise ValueError("Periodo no válido")

            dp_effective = add_month(dp, 1)
            self.window['preparar_ajustes_text'].update(f"{period_desc(dp)}, Ajustes Efectivos Al: {period_desc(dp_effective)}")

            ajustes = generate_ajustes(
                clients=ClientsManager(),
                facturas=FacturasManager(None)["Facturas"],
                dp=dp,
                dp_effective=dp_effective,
                emisor_rfc=self.csd_signer.rfc
            )
            ajustes_table.update(
                values=ajustes,
            )

    def main_tab_group(self, values):
        self.action_button_manager.clear()

        match values['main_tab_group']:
            case 'facturas_tab':
                self.nuevas_facturas(values)

            case 'clientes_tab':
                self.window['clientes_table'].update(
                    values=list(ClientsManager().values()),
                )

            case 'emitidas_tab':
                self.facturas_search()

            case 'correos_tab':
                now = date.today()
                dp_now = DatePeriod(now.year, now.month)
                clients = ClientsManager()

                def correos():
                    for receptor_rfc, notify_invoices in itertools.groupby(
                            sorted(
                                (i for i in self.get_all_invoices().values()
                                 if i["Emisor"]["Rfc"] == self.csd_signer.rfc
                                    and i.estatus == EstadoComprobante.Vigente
                                    and not self.local_db.notified(i)
                                 ),
                                key=lambda r: r["Receptor"]["Rfc"]
                            ),
                            lambda r: r["Receptor"]["Rfc"]
                    ):
                        notify_invoices = list(notify_invoices)

                        def fac_pen_iter():
                            for i in self.get_all_invoices().values():
                                if i["Emisor"]["Rfc"] == self.csd_signer.rfc \
                                        and self.local_db.liquidated_state(i) == StatusState.PENDING \
                                        and i["Fecha"] < dp_now \
                                        and i["Receptor"]["Rfc"] == receptor_rfc \
                                        and i not in notify_invoices:
                                    yield i

                        fac_pen = sorted(
                            fac_pen_iter(),
                            key=lambda r: r["Fecha"]
                        )
                        yield clients[receptor_rfc], notify_invoices, fac_pen

                self.window['correos_table'].update(
                    values=list(correos()),
                )

            case 'ajustes_tab':
                self.nuevos_ajustes(values)

            case 'solicitudes_tab':
                solitudes = self.local_db.get_solicitudes()
                self.window['solicitudes_table'].update(
                    values=list(solitudes.values()),
                )

    def main_loop(self):
        has_focus = True
        _, values = self.window.read(timeout=0)
        event = "main_tab_group"

        while True:
            try:
                if event in ("Exit", sg.WIN_CLOSED):
                    return

                match event:
                    case '_focus_in':
                        if not has_focus:
                            has_focus = True
                            if values["main_tab_group"] in ("clientes_tab", "facturas_tab", "ajustes_tab", "correos_tab"):
                                self.main_tab_group(values)

                    case '_focus_out':
                        try:
                            has_focus = bool(self.window.TKroot.focus_get())
                        except KeyError:
                            has_focus = True

                    case "folio_enter":
                        self.set_folio(to_int(values["folio"]))

                    case "serie_enter":
                        self.set_serie(values["serie"])

                    case "about":
                        clients = ClientsManager()
                        self.initial_screen(clients[self.csd_signer.rfc])

                    case "nueva_solicitud":
                        self.nueva_solicitud(values)
                        self.main_tab_group(values)

                    case "buscar_facturas":
                        self.window["emitidas_search"].update(values["buscar_facturas"])
                        self.facturas_search()

                    case "emitidas_search_enter":
                        self.facturas_search()

                    case "facturas_periodo_enter":
                        self.nuevas_facturas(values, force=True)

                    case "ajustes_periodo_enter":
                        self.nuevos_ajustes(values, force=True)

                    case 'main_tab_group':
                        self.main_tab_group(values)

                    case 'facturas_table_enter':
                        # noinspection PyUnresolvedReferences
                        if s_items := self.window["facturas_table"].selected_items():
                            preview_cfdis(s_items)

                    case 'clientes_table_enter':
                        # noinspection PyUnresolvedReferences
                        for client in self.window["clientes_table"].selected_items():
                            url = csf.url(rfc=client["Rfc"], id_cif=client["IdCIF"])
                            open_file(url)

                    case 'emitidas_table_enter':
                        # noinspection PyUnresolvedReferences
                        if s_items := self.window["emitidas_table"].selected_items():
                            preview_cfdis(s_items)

                    case 'ajustes_table_enter':
                        # noinspection PyUnresolvedReferences
                        for ajuste in self.window["ajustes_table"].selected_items():
                            open_file(
                                os.path.abspath(ajuste['file_name'])
                            )

                    case 'correos_table_enter' | 'solicitudes_table_enter':
                        pass

                    case "facturas_table" | "clientes_table" | "correos_table" | "ajustes_table" | "emitidas_table" | "solicitudes_table":
                        # noinspection PyUnresolvedReferences
                        s_items = self.window[event].selected_items()
                        if event == "emitidas_table":
                            self.set_selected_satcfdis(s_items)
                        else:
                            self.action_button_manager.set_items(event.split("_")[0], s_items)

                    case "facturas_table+select_all" | "clientes_table+select_all" | "correos_table+select_all" | \
                         "ajustes_table+select_all" | "emitidas_table+select_all" | 'solicitudes_table+select_all':
                        # noinspection PyUnresolvedReferences
                        self.window[event.split("+")[0]].select_all()

                    case "facturas_table+delete" | "clientes_table+delete" | "correos_table+delete" | \
                         "ajustes_table+delete" | "emitidas_table+delete":
                        # noinspection PyUnresolvedReferences
                        # self.window[event.split("+")[0]].delete_selected()
                        pass

                    case "solicitudes_table+delete":
                        solitudes = self.local_db.get_solicitudes()
                        # noinspection PyUnresolvedReferences
                        sel = self.window["solicitudes_table"].selected_items()
                        for s in sel:
                            if s["response"].get("EstadoSolicitud").code < EstadoSolicitud.Terminada:
                                self.error_message("No se puede eliminar una solicitud en proceso")
                                continue
                            del solitudes[s["response"]["IdSolicitud"]]
                        self.local_db.set_solicitudes(solitudes)
                        self.main_tab_group(values)

                    case "status_sat":
                        # noinspection PyUnresolvedReferences
                        if i := self.window["emitidas_table"].selected_items()[0]:
                            self.local_db.status_sat(i, update=True)
                            self.set_selected_satcfdis([i])
                            # noinspection PyUnresolvedReferences
                            self.window['emitidas_table'].refresh()

                    case "pendiente_pago":
                        # noinspection PyUnresolvedReferences
                        if i := self.window["emitidas_table"].selected_items()[0]:
                            self.local_db.liquidated_flip(i)
                            self.set_selected_satcfdis([i])
                            # noinspection PyUnresolvedReferences
                            self.window['emitidas_table'].refresh()

                    case "email_notificada":
                        # noinspection PyUnresolvedReferences
                        if i := self.window["emitidas_table"].selected_items()[0]:
                            self.local_db.notified_flip(i)
                            self.set_selected_satcfdis([i])
                            # noinspection PyUnresolvedReferences
                            self.window['emitidas_table'].refresh()

                    case "crear_facturas" | "ver_preview":
                        action_text = self.action_button_manager.text()
                        action_name = self.action_button_manager.name
                        action_items = self.action_button_manager.items

                        if action_name == "pago":
                            action_items = self.crear_pago(values)

                        if event == "ver_preview":
                            if action_name in ("facturas", "pago"):
                                preview_cfdis(action_items)

                        elif event == "crear_facturas":
                            res = sg.popup(
                                f"Estas seguro que quieres '{action_text}'?",
                                title="Confirmar",
                                button_type=POPUP_BUTTONS_OK_CANCEL,
                                location=center_location(self.window),
                                keep_on_top=True,
                            )
                            if res == "OK":
                                self.header(action_text.upper())
                                self.action_button_manager.clear()
                                self.action_button(
                                    action_name=action_name,
                                    action_items=action_items
                                )

                    case "editar_clientes":
                        open_file(
                            os.path.abspath("clientes.yaml")
                        )

                    case "exportar_clientes":
                        filename = 'clientes.txt'
                        clients = ClientsManager()
                        clientes_generar_txt(filename, clients)
                        open_file(
                            os.path.dirname(
                                os.path.abspath(filename)
                            )
                        )

                    case "editar_facturas" | "editar_ajustes":
                        open_file(
                            os.path.abspath("facturas.yaml")
                        )

                    case "editar_configurar":
                        open_file(
                            os.path.abspath("config.yaml")
                        )

                    case "ver_config":
                        open_file(
                            os.path.abspath(".")
                        )

                    case "ver_excel":
                        dp = to_date_period(values["periodo"])
                        clients = ClientsManager()
                        emisor_cif = clients[self.csd_signer.rfc]
                        archivo_excel = exportar_facturas(
                            self.get_all_invoices(),
                            dp,
                            emisor_cif,
                            self.rfc_prediales
                        )
                        open_file(
                            os.path.abspath(archivo_excel)
                        )

                    case "ver_carpeta":
                        dp = to_date_period(values["periodo"])
                        directory = archivos_folder(dp)
                        open_file(
                            os.path.abspath(directory)
                        )

                    case "organizar_facturas":
                        MyCFDI.rename_invoices(search_path="**/*.xml")

                    case "cargar_zip":
                        zip_file = sg.popup_get_file('', multiple_files=False, no_window=True, file_types=(("ZIP Files", "*.zip"),))
                        if zip_file:
                            self.header("Cargar ZIP")
                            self.unzip_cfdi(zip_file)

                    case 'importar_emitidas':
                        csv_file = sg.popup_get_file('', multiple_files=False, no_window=True, file_types=(("CSV Files", "*.csv"),))
                        if csv_file:
                            self.header("Importar emitidas")
                            all_invoices = self.get_all_invoices()
                            with open(csv_file, newline='', encoding='utf-8') as f:
                                reader = csv.reader(f)
                                header = next(reader)
                                for row in reader:
                                    row = dict(zip(header, row))
                                    uuid = UUID(row["Folio Fiscal (UUID)"])
                                    if uuid not in all_invoices:
                                        cfdi = self.download_invoice(uuid)

                                        if row.get("Estatus", "Entregado SAT") != "Entregado SAT":
                                            estado = self.local_db.status_sat(cfdi, update=True)
                                            print_yaml(estado)
                                    self._read()
                                print("FIN")

                    case "exportar_metadata":
                        with open(METADATA_FILE, 'w', newline='', encoding='utf-8') as f:
                            writer = csv.writer(f)
                            for i in self.get_all_invoices():
                                if status := self.local_db.status_export(i):
                                    writer.writerow(status)

                    case "importar_metadata":
                        with open(METADATA_FILE, newline='', encoding='utf-8') as f:
                            reader = csv.reader(f)
                            for row in reader:
                                self.local_db.status_merge(*row)

                    case _:
                        logger.error(f"Unknown event '{event}'")

            except (ValueError, XlsxFileError) as ex:
                self.error_message(ex)
            except ConsoleErrors as ex:
                self.header(str(ex))
                for error in ex.errors:
                    self.console.update(f"{error}\n", append=True)
            except Exception as ex:
                self.header("Exception")
                self.console.update(append=True, value=str(ex))
                logger.exception("Main Loop Exception")

            event, values = self.window.read()
