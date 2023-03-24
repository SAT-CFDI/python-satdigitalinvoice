import base64
import io
import itertools
import logging
import os
from datetime import timedelta, date
from zipfile import ZipFile

from PySimpleGUI import POPUP_BUTTONS_OK_CANCEL, PySimpleGUI
from satcfdi import DatePeriod, csf
from satcfdi.accounting import EmailManager
from satcfdi.create.cfd import cfdi40
from satcfdi.exceptions import ResponseError
from satcfdi.pacs import Accept
from satcfdi.pacs.sat import SAT, TipoDescargaMasivaTerceros, EstadoSolicitud
from satcfdi.printer import Representable
# noinspection PyUnresolvedReferences
from satcfdi.transform.catalog import CATALOGS

from . import __version__, PPD, PUE, TEMP_DIRECTORY
from .client_validation import validar_client
from .environments import facturacion_environment
from .file_data_managers import ClientsManager, FacturasManager
from .formatting_functions.common import fecha
from .gui_functions import generate_ingresos, pago_factura, exportar_facturas, archivos_filename, mf_pago_fmt, archivos_folder, period_desc, ajustes_directory, find_ajustes, \
    format_concepto_desc, generate_pdf_template, periodicidad_desc, parse_fecha_pago, parse_importe_pago, preview_cfdis
from .layout import make_layout, ActionButtonManager
from .localdb import LocalDBSatCFDI, LiquidatedState
from .log_tools import cfdi_header, header_line, print_yaml
from .mycfdi import get_all_cfdi, MyCFDI, move_to_folder
from .utils import random_string, parse_date_period, load_certificate, to_int, cert_info, add_month, clear_directory, find_best_match, months_between

logging.getLogger("weasyprint").setLevel(logging.ERROR)
logging.getLogger("fontTools").setLevel(logging.ERROR)

logger = logging.getLogger(__name__)


def open_launch_window():
    layout = [[PySimpleGUI.Text("New Window", key="new")]]
    window = PySimpleGUI.Window("Launch Window", layout, modal=True, size=(300, 300))
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
        self.serie = config['serie']
        self.csd_signer = load_certificate(config.get('csd')) if 'csd' in config else None
        self.fiel_signer = load_certificate(config.get('fiel')) if 'fiel' in config else None

        self.sat_service = SAT(signer=self.fiel_signer)
        self.rfc_prediales = config['rfc_prediales']

        self.all_invoices = None
        self.local_db = LocalDBSatCFDI(
            enviar_a_partir=config['enviar_a_partir'],
            pagar_a_partir=config['pagar_a_partir']
        )
        # noinspection PyTypeChecker
        self.selected_satcfdi = None  # type: MyCFDI

        self.window = PySimpleGUI.Window(
            f"Facturación Mensual CFDI 4.0 {self.csd_signer.rfc}",
            make_layout(bool(self.fiel_signer), self.local_db),
            size=(1280, 800),
            resizable=True,
            font=("Courier New", 10, "bold"),
        )

        self.action_button_manager = ActionButtonManager(self.window["crear_facturas"])
        self.console = self.window["console"]

        MyCFDI.local_db = self.local_db

    def run(self):
        self.window.finalize()

        self.set_folio()
        self.window['serie'].update(self.serie)

        self.window['periodo'].bind("<Return>", "_enter")
        self.window['importe_pago'].bind("<Return>", "_enter")
        self.window['fecha_pago'].bind("<Return>", "_enter")
        self.window['forma_pago'].bind("<Return>", "_enter")
        self.window['emitidas_search'].bind("<Return>", "_enter")

        self.window['facturas_table'].bind('<Double-Button-1>', '_double_click')
        self.window['clientes_table'].bind('<Double-Button-1>', '_double_click')
        self.window['emitidas_table'].bind('<Double-Button-1>', '_double_click')
        self.window['ajustes_table'].bind('<Double-Button-1>', '_double_click')

        self.window['facturas_table'].bind('<Control-KeyPress-a>', '+select_all')
        self.window['clientes_table'].bind('<Control-KeyPress-a>', '+select_all')
        self.window['emitidas_table'].bind('<Control-KeyPress-a>', '+select_all')
        self.window['correos_table'].bind('<Control-KeyPress-a>', '+select_all')
        self.window['ajustes_table'].bind('<Control-KeyPress-a>', '+select_all')

        # Add logging to the window
        h = logging.StreamHandler(self.window['console'])
        h.setLevel(logging.ERROR)
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

        # Add Serie and Folio and signature
        invoice['Serie'] = self.serie
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
                logger.error(f"Error Generando: {invoice.get('Serie')}{invoice.get('Folio')} {invoice['Receptor']['Rfc']}")
                if isinstance(ex, ResponseError):
                    logger.error(f"Status Code: {ex.response.status_code}")
                    logger.error(f"Response: {ex.response.text}")
                continue

            self.set_folio(folio + 1)
            return move_to_folder(res.xml, pdf_data=res.pdf)

    def set_folio(self, folio: int = None):
        if folio:
            self.local_db.folio_set(folio)
        self.window['folio'].update(folio or self.local_db.folio())

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
        match action_name:
            case 'facturas':
                self.all_invoices = None
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
                emisor_cif = clients[self.csd_signer.rfc]
                with self.email_manager.sender as s:
                    for receptor, notify_invoices, pendientes_meses_anteriores in action_items:
                        def attachments():
                            for ni in notify_invoices:
                                yield ni.filename + ".xml"
                                yield ni.filename + ".pdf"

                        subject = f"Comprobantes Fiscales {receptor['RazonSocial']} - {receptor['Rfc']}"

                        s.send_email(
                            subject=subject,
                            to_addrs=receptor["Email"],
                            html=facturacion_environment.get_template('mail_facturas_template.html').render(
                                facturas=notify_invoices,
                                pendientes_meses_anteriores=pendientes_meses_anteriores,
                                emisor=emisor_cif,
                            ),
                            file_attachments=attachments()
                        )
                        for r in notify_invoices:
                            self.local_db.notified_set(r.uuid, True)
                        print_yaml({
                            "correo": subject,
                            "para": receptor["Email"]
                        })
                        self._read()

            case 'ajustes':
                clients = ClientsManager()
                emisor_cif = clients[self.csd_signer.rfc]
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
                                emisor=emisor_cif,
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

        self.selected_satcfdi = i
        if i:
            estado = self.local_db.status_sat(i).get('Estado', 'Vigente')
            self.window["status_sat"].update(
                estado.center(10),
                disabled=False,
                button_color="red4" if estado != "Vigente" else "green",
            )
        else:
            self.window["status_sat"].update(
                "".ljust(10), disabled=True, button_color=PySimpleGUI.theme_background_color()
            )

        # Email
        is_enviable = i \
                      and i["Emisor"]["Rfc"] == self.csd_signer.rfc \
                      and i.estatus == "1"
        if is_enviable:
            self.window["email_notificada"].update(
                "Enviada".center(10) if self.local_db.notified(i) else "Por Enviar",
                disabled=False,
                button_color="green" if self.local_db.notified(i) else "red4",
            )
        else:
            self.window["email_notificada"].update(
                "".ljust(10), disabled=True, button_color=PySimpleGUI.theme_background_color()
            )

        # Pendiente de Pago
        is_pendientable = i \
                          and i["Emisor"]["Rfc"] == self.csd_signer.rfc \
                          and i["TipoDeComprobante"] == "I" \
                          and i.estatus == "1" \
                          and (i["MetodoPago"] == PUE or i.saldo_pendiente) \
                          and i["Total"]
        if is_pendientable:
            self.window["pendiente_pago"].update(
                ("Pagada".center(10) if i["MetodoPago"] == PUE else "Ignorada".center(10)) if self.local_db.liquidated(i) else "Por Pagar".center(10),
                disabled=False,
                button_color="green" if self.local_db.liquidated(i) else "red4",
            )
        else:
            self.window["pendiente_pago"].update(
                "".ljust(10), disabled=True, button_color=PySimpleGUI.theme_background_color()
            )

        # PPD
        is_ppd_active = i \
                        and i["Emisor"]["Rfc"] == self.csd_signer.rfc \
                        and i.get("MetodoPago") == PPD \
                        and i.estatus == "1" \
                        and i.saldo_pendiente
        is_ppd_active = bool(is_ppd_active)
        self.window["ppd_action_items"].update(visible=is_ppd_active)
        self.window["importe_pago"].update("")

    def header(self, name):
        self.console.update("")
        print(header_line(name))

    def facturas_search(self, search_text):
        search_text = search_text.strip().upper()
        if len(search_text) < 3:
            self.window["emitidas_text"].update("El texto de búsqueda debe tener al menos 3 caracteres")
            return

        self.window["emitidas_text"].update(search_text)

        def fact_iter():
            for i in self.get_all_invoices().values():
                if i["Emisor"]["Rfc"] == self.csd_signer.rfc \
                        and (
                        i.name == search_text
                        or i["Receptor"]["Rfc"] == search_text
                        or search_text in i["Receptor"].get("Nombre", "")
                ):
                    yield i

        self.window['emitidas_table'].update(
            values=list(fact_iter()),
        )

    def facturas_pendientes(self):
        self.window["emitidas_text"].update("Facturas Pendientes de Pago")

        def fact_iter():
            for i in self.get_all_invoices().values():
                if i["Emisor"]["Rfc"] == self.csd_signer.rfc \
                        and self.local_db.liquidated_state(i) == LiquidatedState.NO:
                    yield i

        self.window['emitidas_table'].update(
            values=list(fact_iter()),
        )

    def facturas_emitidas(self, dp):
        self.window["emitidas_text"].update("Facturas Emitidas en " + str(dp))

        def fact_iter():
            for i in self.get_all_invoices().values():
                if i["Emisor"]["Rfc"] == self.csd_signer.rfc \
                        and i["Fecha"] == dp:
                    yield i

        self.window['emitidas_table'].update(
            values=list(fact_iter()),
        )

    def main_loop(self):
        while True:
            event, values = self.window.read()
            try:
                if event in ("Exit", PySimpleGUI.WIN_CLOSED):
                    return

                try:
                    dp = parse_date_period(values["periodo"])
                except ValueError:
                    dp = None

                if event in ("periodo_enter", "refresh_facturas", "refresh_ajustes", "refresh_clientes", "refresh_correos"):
                    event = 'main_tab_group'

                match event:
                    case "folio":
                        self.set_folio(to_int(values["folio"]))

                    case "about":
                        clients = ClientsManager()
                        self.initial_screen(clients[self.csd_signer.rfc])

                    case "recuperar_emitidas" | "recuperar_recibidas":
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

                    case "emitidas_search_enter":
                        self.action_button_manager.clear()
                        self.facturas_search(values["emitidas_search"])

                    case 'main_tab_group':
                        if values['main_tab_group'] == 'console_tab':
                            self.action_button_manager.clear()

                        if values['main_tab_group'] == 'recuperar_tab':
                            self.action_button_manager.clear()

                        if values['main_tab_group'] == 'facturas_tab':
                            self.window['facturas_table'].update(values=[])

                            if dp is None or dp.month is None:
                                self.window['preparar_facturas_text'].update("Periodo no válido")
                                continue

                            self.window['preparar_facturas_text'].update(f"{period_desc(dp)}")
                            self.console.update("")
                            cfdis = generate_ingresos(
                                clients=ClientsManager(),
                                facturas=FacturasManager(dp)["Facturas"],
                                dp=dp,
                                emisor_rfc=self.csd_signer.rfc
                            )
                            if cfdis:
                                self.window['facturas_table'].update(
                                    values=cfdis,
                                )
                            else:
                                self.window['console_tab'].select()
                                continue

                        if values['main_tab_group'] == 'clients_tab':
                            self.window['clientes_table'].update(
                                values=list(ClientsManager().values()),
                            )

                        if values['main_tab_group'] == 'emitidas_tab':
                            self.action_button_manager.clear()
                            self.facturas_pendientes()

                        if values['main_tab_group'] == 'correos_tab':
                            now = date.today()
                            dp_now = DatePeriod(now.year, now.month)
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

                                def fac_pen_iter():
                                    for i in self.get_all_invoices().values():
                                        if i["Emisor"]["Rfc"] == self.csd_signer.rfc \
                                                and self.local_db.liquidated_state(i) == LiquidatedState.NO \
                                                and i["Fecha"] < dp_now \
                                                and i["Receptor"]["Rfc"] == receptor_rfc \
                                                and i not in notify_invoices:
                                            yield i

                                fac_pen = sorted(
                                    fac_pen_iter(),
                                    key=lambda r: r["Fecha"]
                                )
                                receptor = clients[receptor_rfc]
                                cfdi_correos.append((receptor, notify_invoices, fac_pen))

                            self.window['correos_table'].update(
                                values=cfdi_correos,
                            )

                        if values['main_tab_group'] == 'ajustes_tab':
                            self.window['ajustes_table'].update(values=[])
                            if dp is None or dp.month is None:
                                self.window['preparar_ajustes_text'].update("Periodo no válido")
                                continue

                            dp_effective = add_month(dp, 1)
                            self.window['preparar_ajustes_text'].update(f"Ajustes Efectivos Al: {period_desc(dp_effective)}")

                            # clear directory
                            ajustes_dir = ajustes_directory(DatePeriod(dp.year, dp.month))
                            clear_directory(ajustes_dir)
                            emisor_rfc = self.csd_signer.rfc

                            clients = ClientsManager()
                            facturas = FacturasManager(None)["Facturas"]

                            def ajustes_iter():
                                for i, (receptor_rfc, concepto) in enumerate(find_ajustes(facturas, dp_effective.month)):
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
                                        "fecha_hoy": fecha(date.today()),
                                        'file_name': file_name
                                    }

                                    if ajuste_porcentaje:
                                        res = generate_pdf_template(
                                            template_name='incremento_template.md',
                                            fields=data
                                        )
                                        with open(file_name, 'wb') as f:
                                            f.write(res)
                                    yield data

                            self.window['ajustes_table'].update(
                                values=list(ajustes_iter()),
                            )

                    case "facturas_pendientes":
                        self.facturas_pendientes()

                    case "facturas_emitidas":
                        self.facturas_emitidas(dp)

                    case 'facturas_table_double_click':
                        # noinspection PyUnresolvedReferences
                        s_items = self.window["facturas_table"].selected_items()
                        preview_cfdis(s_items)

                    case 'clientes_table_double_click':
                        # noinspection PyUnresolvedReferences
                        for client in self.window["clientes_table"].selected_items():
                            url = csf.url(rfc=client["Rfc"], id_cif=client["IdCIF"])
                            os.startfile(url)

                    case 'emitidas_table_double_click':
                        # noinspection PyUnresolvedReferences
                        s_items = self.window["emitidas_table"].selected_items()
                        preview_cfdis(s_items)

                    case 'ajustes_table_double_click':
                        # noinspection PyUnresolvedReferences
                        for ajuste in self.window["ajustes_table"].selected_items():
                            os.startfile(
                                os.path.abspath(ajuste['file_name'])
                            )

                    case "facturas_table" | "clientes_table" | "correos_table" | "ajustes_table" | "emitidas_table":
                        # noinspection PyUnresolvedReferences
                        s_items = self.window[event].selected_items()
                        if event == "emitidas_table":
                            self.set_selected_satcfdis(s_items)
                        else:
                            self.action_button_manager.set_items(event.split("_")[0], s_items)

                    case "facturas_table+select_all" | "clientes_table+select_all" | "correos_table+select_all" | "ajustes_table+select_all" | "emitidas_table+select_all":
                        # noinspection PyUnresolvedReferences
                        self.window[event.split("+")[0]].select_all()

                    case "prepare_pago" | "importe_pago_enter" | "fecha_pago_enter" | "forma_pago_enter" | "ver_html_pago":
                        if i := self.selected_satcfdi:
                            fecha_pago = parse_fecha_pago(values["fecha_pago"])
                            importe_pago = parse_importe_pago(values["importe_pago"]) or i.saldo_pendiente
                            self.window["importe_pago"].update(importe_pago)

                            cfdi = pago_factura(
                                factura_pagar=i,
                                fecha_pago=fecha_pago,
                                forma_pago=values["forma_pago"],
                                importe_pago=importe_pago,
                            )
                            self.action_button_manager.set_items('facturas', [cfdi])
                            if event == "ver_html_pago":
                                preview_cfdis([cfdi])

                    case "status_sat":
                        if i := self.selected_satcfdi:
                            self.local_db.status_sat(i, update=True)
                            self.set_selected_satcfdis([i])

                    case "pendiente_pago":
                        if i := self.selected_satcfdi:
                            self.local_db.liquidated_flip(i)
                            self.set_selected_satcfdis([i])

                    case "email_notificada":
                        if i := self.selected_satcfdi:
                            self.local_db.notified_flip(i)
                            self.set_selected_satcfdis([i])

                    case "crear_facturas":
                        action_text = self.action_button_manager.text()
                        res = PySimpleGUI.popup(
                            f"Estas seguro que quieres '{action_text}'?",
                            title="Confirmar",
                            button_type=POPUP_BUTTONS_OK_CANCEL,
                        )
                        if res == "OK":
                            self.header(action_text.upper())
                            self.window['console_tab'].select()
                            self._read()
                            self.action_button(
                                action_name=self.action_button_manager.name,
                                action_items=self.action_button_manager.items
                            )
                            self.action_button_manager.clear()

                    case "ver_excel":
                        clients = ClientsManager()
                        emisor_cif = clients[self.csd_signer.rfc]
                        if archivo_excel := exportar_facturas(
                                self.get_all_invoices(),
                                dp,
                                emisor_cif,
                                self.rfc_prediales
                        ):
                            os.startfile(
                                os.path.abspath(archivo_excel)
                            )
                        else:
                            raise Exception("No se pudo crear el archivo, cierra el archivo si se tiene abierto")

                    case "ver_html":
                        def fact_iter():
                            for i in self.get_all_invoices().values():
                                if i["Fecha"] == dp:
                                    yield i

                        if cfdis := list(fact_iter()):
                            outfile = archivos_filename(dp, ext="html")
                            Representable.html_write_all(
                                objs=cfdis,
                                target=outfile,
                            )
                            os.startfile(
                                os.path.abspath(outfile)
                            )
                        else:
                            raise Exception("No hay facturas para el periodo seleccionado")

                    case "ver_carpeta":
                        directory = archivos_folder(dp)
                        os.startfile(
                            os.path.abspath(directory)
                        )

                    case "ver_config":
                        os.startfile(
                            os.path.abspath(".")
                        )

                    case "editar_clientes":
                        os.startfile(
                            os.path.abspath("clientes.yaml")
                        )

                    case "editar_facturas":
                        os.startfile(
                            os.path.abspath("facturas.yaml")
                        )

                    case "sat_status_todas":
                        def fact_iter():
                            for i in self.get_all_invoices().values():
                                if i["Fecha"] == dp:
                                    yield i

                        for cfdi in fact_iter():
                            print(f"Estado SAT: {cfdi_header(cfdi)}")
                            self._read()
                            estado = self.local_db.status_sat(cfdi, update=True)
                            print_yaml(estado)
                        print("FIN")

                    case "periodo" | "inicio" | "final" | "fecha_pago" | "forma_pago" | "importe_pago" | ' ':
                        pass

                    case _:
                        logger.error(f"Unknown event '{event}'")

            except Exception as ex:
                logger.exception(header_line("ERROR"))
                if values['main_tab_group'] != 'console_tab':
                    PySimpleGUI.Popup(
                        ex,
                        no_titlebar=True,
                        grab_anywhere=True,
                        any_key_closes=True,
                        background_color="red4",
                    )
