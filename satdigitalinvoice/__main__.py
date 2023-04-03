import base64
import io
import itertools
import logging
import os
import shutil
from datetime import timedelta, date
from decimal import Decimal
from zipfile import ZipFile

from PySimpleGUI import POPUP_BUTTONS_OK_CANCEL, PySimpleGUI
from markdown2 import markdown
from satcfdi import DatePeriod, CFDI, Code, Signer
from satcfdi.accounting import filter_invoices_iter, SatCFDI
from satcfdi.create.cfd import cfdi40
from satcfdi.exceptions import ResponseError, DocumentNotFoundError
from satcfdi.pacs import Accept
from satcfdi.pacs.sat import SAT, TipoDescargaMasivaTerceros, EstadoSolicitud
# noinspection PyUnresolvedReferences
from satcfdi.transform.catalog import CATALOGS
from weasyprint import HTML, CSS

from . import SOURCE_DIRECTORY, __version__
from .client_validation import validar_client
from .file_data_managers import environment_default, environment_bold_escaped, ClientsManager, ConfigManager, FacturasManager
from .formatting_functions.common import fecha, pesos, porcentaje
from .gui_functions import generate_ingresos, pago_factura, find_ajustes, format_concepto_desc, exportar_facturas, exportar_facturas_filename, parse_ym_date
from .layout import make_layout, InvoiceButtonManager, EmailButtonManager
from .local import LocalDBSatCFDI
from .log_tools import log_line, log_item, cfdi_header, print_yaml, header_line
from .mycfdi import get_all_cfdi, MyCFDI, move_to_folder, PPD, PUE
from .utils import random_string, to_uuid, add_file_handler, convert_ans1_date

logging.getLogger("weasyprint").setLevel(logging.ERROR)
logging.getLogger("fontTools").setLevel(logging.ERROR)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

AJUSTES_DIR = "ajustes"
template = environment_default.get_template(
    'mail_facturas_template.html'
)


class FacturacionGUI:
    def __init__(self, pac_service, csd_signer: Signer, email_manager, fiel_signer=None, debug=False):
        # set up logging
        if debug:
            logging.basicConfig(level=logging.ERROR)
        add_file_handler()

        self.email_manager = email_manager
        self.pac_service = pac_service
        self.sat_service = SAT(
            signer=fiel_signer
        )
        self.csd_signer = csd_signer

        self.window = PySimpleGUI.Window(
            f"Facturacion 4.0",
            make_layout(fiel_signer is not None),
            size=(1280, 800),
            resizable=True,
        )

        self.all_invoices = None
        self.config = None
        self.local_db = None
        self.base_template = None
        self.issuer_cif = None

        self.invoice_button_manager = InvoiceButtonManager(self.window["crear_facturas"], self.window["detallado"])
        self.email_button_manager = EmailButtonManager(self.window["enviar_correos"])
        self.console = self.window["console"]

    def prepare(self):
        clients = ClientsManager()
        self.config = ConfigManager()
        self.local_db = LocalDBSatCFDI(self.config)

        issuer_cif = clients[self.csd_signer.rfc]
        self.issuer_cif = issuer_cif

        self.base_template = {
            "Emisor": cfdi40.Emisor(
                rfc=issuer_cif['Rfc'],
                nombre=issuer_cif['RazonSocial'],
                regimen_fiscal=issuer_cif['RegimenFiscal']
            ),
            "LugarExpedicion": issuer_cif['CodigoPostal']
        }

        MyCFDI.issuer_rfc = self.csd_signer.rfc
        MyCFDI.local_db = self.local_db

        # update window title
        self.window.set_title(
            f"Facturacion 4.0  RFC: {self.csd_signer.rfc}  RazonSocial: {issuer_cif['RazonSocial']}  RegimenFiscal: {issuer_cif['RegimenFiscal']}  "
            f"LugarExpedicion: {issuer_cif['CodigoPostal']}"
        )

    def initial_screen(self):
        print_yaml({
            "version": __version__.__version__,
            "facturacion": "CFDI 4.0",
            "emisor": self.base_template,
            "pac_service": {
                "Type": type(self.pac_service).__name__,
                "Rfc": self.pac_service.RFC,
                "Environment": str(self.pac_service.environment)
            }
        })

    def start(self):
        self.window.finalize()

        # Add logging to the window
        h = logging.StreamHandler(self.window['console'])
        h.setLevel(logging.INFO)
        logger.addHandler(h)

        try:
            self.prepare()
            self.initial_screen()
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
                self._read(timeout=1000 * i)

            try:
                res = self.pac_service.stamp(
                    cfdi=invoice,
                    accept=Accept.XML_PDF,
                    ref_id=ref_id
                )
            except Exception as ex:
                logger.error(f'Error Generando: {cfdi_header(MyCFDI(invoice))}')
                if isinstance(ex, ResponseError):
                    logger.error(f"Status Code: {ex.response.status_code}")
                    logger.error(f"Response: {ex.response.text}")
                continue

            self.config.inc_folio()
            return move_to_folder(res.xml, pdf_data=res.pdf)

    def enviar_correos(self, emails):
        with self.email_manager.sender as s:
            for receptor, notify_invoices, pendientes_meses_anteriores in emails:
                attachments = []
                for r in notify_invoices:
                    attachments += [r.filename + ".xml", r.filename + ".pdf"]

                subject = f"Comprobantes Fiscales {receptor['RazonSocial']} - {receptor['Rfc']}"
                s.send_email(
                    subject=subject,
                    to_addrs=receptor["Email"],
                    html=self.generate_html_template(
                        'mail_facturas_template.html',
                        fields={
                            "facturas": notify_invoices,
                            'pendientes_meses_anteriores': pendientes_meses_anteriores,
                        }
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

    def generate_pdf_template(self, template_name, fields):
        increment_template = environment_bold_escaped.get_template(template_name)
        md5_document = increment_template.render(
            emisor=self.issuer_cif,
            fecha_hoy=fecha(date.today()),
            **fields
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

    def generate_html_template(self, template_name, fields):
        increment_template = environment_default.get_template(template_name)
        render = increment_template.render(
            emisor=self.issuer_cif, **fields
        )
        return render

    def factura_uuid(self, text):
        return self.get_all_invoices().get(to_uuid(text))

    def factura_buscar(self, text):
        if text:
            emisor_rfc = self.csd_signer.rfc
            res = None
            for i in self.get_all_invoices().values():
                if i.name == text and i["Emisor"]["Rfc"] == emisor_rfc:
                    logger.info(f"Factura Encontrada: {i['Receptor']['Rfc']}  {i.name}  {i.uuid}  {i['Fecha']}")
                    if res:
                        logger.info(f"Multiples Facturas Encontradas con el mismo nombre: {text}")
                        return
                    res = i
            if res:
                return res
        logger.info(f"Factura No Encontrada {text}")

    def log_cfdi(self, cfdi: CFDI, ver_saldo=True):
        cfdi_copy = cfdi.copy()
        del cfdi_copy["Certificado"]
        del cfdi_copy["Sello"]

        if not self.window['detallado'].get():
            del cfdi_copy["Serie"]
            del cfdi_copy["NoCertificado"]
            cfdi_copy.pop("Emisor")
            cfdi_copy["Receptor"] = f"{cfdi_copy['Receptor']['Rfc']}, {cfdi_copy['Receptor']['Nombre']}, {cfdi_copy['Receptor'].get('RegimenFiscalReceptor')}"
            cfdi_copy["Conceptos"] = [x['Descripcion'] for x in cfdi_copy["Conceptos"]]  # f"<< {len(cfdi_copy['Conceptos'])} >>"
            cfdi_copy.pop("Impuestos", None)
            cfdi_copy.pop("Fecha")
            cfdi_copy.pop("LugarExpedicion")
            cfdi_copy.pop("Version")
            cfdi_copy.pop("TipoDeComprobante")
            if cfdi_copy.get("Exportacion") == "01":
                del cfdi_copy["Exportacion"]
            if cfdi_copy.get("FormaPago") == "99":
                del cfdi_copy["FormaPago"]
            if cfdi_copy.get("Moneda") in ("MXN", "XXX"):
                del cfdi_copy["Moneda"]

            if complemento := cfdi_copy.get("Complemento"):
                cfdi_copy["Complemento"] = {}
                if pagos := complemento.get("Pagos"):
                    def clean_doc(d):
                        d = d.copy()
                        d.pop("ImpuestosDR")
                        if d.get("MonedaDR") in ("MXN", "XXX"):
                            del d["MonedaDR"]
                            d.pop("EquivalenciaDR")
                        return d

                    def clean_pago(p):
                        p = p.copy()
                        p.pop("ImpuestosP")
                        p["DoctoRelacionado"] = [clean_doc(x) for x in p["DoctoRelacionado"]]
                        if p.get("MonedaP") in ("MXN", "XXX"):
                            del p["MonedaP"]
                            p.pop("TipoCambioP")
                        return p

                    pagos_copy = pagos.copy()
                    pagos_copy["Pago"] = [clean_pago(x) for x in pagos_copy["Pago"]]
                    cfdi_copy["Complemento"]["Pagos"] = pagos_copy

                if timbre_fiscal_digital := complemento.get("TimbreFiscalDigital"):
                    cfdi_copy["Complemento"]["TimbreFiscalDigital"] = timbre_fiscal_digital['UUID']

        if isinstance(cfdi, SatCFDI) and ver_saldo:
            cfdi_copy["_saldo_pendiente"] = cfdi.saldo_pendiente

        print_yaml(cfdi_copy)

    def main_loop(self):
        factura_seleccionada = None  # type: MyCFDI | None

        while True:
            event, values = self.window.read()
            self.config.reload()
            try:
                if event in ("Exit", PySimpleGUI.WIN_CLOSED):
                    return

                if event not in ("crear_facturas", "enviar_correos", "confirm_pago_button", "ver_factura", "ver_excel"):
                    self.console.update("")
                invoices_to_create = self.invoice_button_manager.clear()
                emails_to_send = self.email_button_manager.clear()

                match event:
                    case "about":
                        self.initial_screen()

                    case "factura_pagar" | "buscar_factura":
                        text = self.window["factura_pagar"].get().strip()
                        factura_seleccionada = self.factura_uuid(text)
                        if event == "buscar_factura" and not factura_seleccionada:
                            factura_seleccionada = self.factura_buscar(text)

                        if factura_seleccionada:
                            self.log_cfdi(factura_seleccionada)
                            self.local_db.describe(factura_seleccionada)

                        not_ppd_all = not factura_seleccionada \
                                      or factura_seleccionada.get("MetodoPago") != PPD \
                                      or factura_seleccionada.estatus != "1"
                        not_ppd = not_ppd_all \
                                  or factura_seleccionada["Emisor"]["Rfc"] != self.csd_signer.rfc

                        not_pue = not factura_seleccionada \
                                  or factura_seleccionada.get("MetodoPago") != PUE \
                                  or factura_seleccionada.estatus != "1" or \
                                  factura_seleccionada["Emisor"]["Rfc"] != self.csd_signer.rfc

                        self.window["status_sat"].update(disabled=not factura_seleccionada)

                        self.window["pago_pue"].update(
                            disabled=not_pue
                                     or factura_seleccionada["Fecha"] <= self.config['pue_pagada_hasta']
                        )
                        self.window["email_notificada"].update(
                            disabled=not factura_seleccionada
                                     or factura_seleccionada["Emisor"]["Rfc"] != self.csd_signer.rfc
                                     or factura_seleccionada["Fecha"] <= self.config['email_notificada_hasta']
                        )
                        self.window["ignorar_ppd"].update(
                            disabled=not_ppd_all
                                     or factura_seleccionada["Fecha"] <= self.config['ppd_ignorar_hasta']
                        )

                        self.window["ver_factura"].update(disabled=not factura_seleccionada)

                        self.window["prepare_pago"].update(disabled=not_ppd)
                        self.window["fecha_pago_select"].update(disabled=not_ppd)
                        self.window["fecha_pago"].update(disabled=not_ppd)
                        self.window["forma_pago"].update(disabled=not_ppd)
                        self.window["descarga"].update(disabled=not to_uuid(text))

                    case "preparar_ajuste_anual":
                        log_item(f"AJUSTE ANUAL")
                        ym_date = parse_ym_date(values['anio_mes_ajuste'])
                        ajuste_porcentaje = values['ajuste_porcentaje']
                        if not ajuste_porcentaje:
                            logger.info("Especificar Ajuste Porcetaje")
                            continue

                        ajuste_porcentaje = Decimal(ajuste_porcentaje) / 100

                        shutil.rmtree(AJUSTES_DIR, ignore_errors=True)
                        os.makedirs(AJUSTES_DIR, exist_ok=True)
                        clients = ClientsManager()
                        facturas = FacturasManager()["Facturas"]

                        has_ajustes = False
                        for i, (rfc, concepto) in enumerate(find_ajustes(facturas, ym_date.month), start=1):
                            has_ajustes = True
                            receptor = clients[rfc]
                            valor_unitario_nuevo = concepto["ValorUnitario"] * (1 + ajuste_porcentaje)
                            concepto = format_concepto_desc(concepto, periodo="INMUEBLE")

                            data = {
                                "receptor": receptor,
                                "concepto": concepto,
                                "valor_unitario_nuevo": pesos(valor_unitario_nuevo),
                                "ajuste_porcentaje": porcentaje(ajuste_porcentaje, 2),
                                "ajuste_periodo": "UN AÑO",
                                "ajuste_efectivo_al": fecha(ym_date),
                                "periodo": concepto['_periodo_mes_ajuste'].split(".")[0].upper()
                            }

                            log_item(f"CARTA INCREMENTO NUMERO: {i}")
                            print_yaml(data)
                            res = self.generate_pdf_template(template_name='incremento_template.md', fields=data)
                            file_name = f'{AJUSTES_DIR}/AjusteRenta_{rfc}_{concepto["CuentaPredial"]}.pdf'
                            with open(file_name, 'wb') as f:
                                f.write(res)
                            self._read()

                        if has_ajustes:
                            os.startfile(
                                os.path.abspath(AJUSTES_DIR)
                            )

                    case "recuperar_emitidas" | "recuperar_recibidas":
                        log_line("RECUPERAR")
                        fecha_final = date.today()
                        fecha_inicial = fecha_final - timedelta(days=int(values["recuperar_dias"]))
                        id_solicitud = self.config.get(event)

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
                            self.config[event] = response['IdSolicitud']
                            self.config.save()
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
                                del self.config[event]
                                self.config.save()

                    case "validate_clientes":
                        log_line("VALIDAR CLIENTES")
                        clients = ClientsManager()
                        res = PySimpleGUI.popup(
                            f"Estas seguro que quieres validar {len(clients)} clientes?",
                            title=self.window[event].ButtonText,
                            button_type=POPUP_BUTTONS_OK_CANCEL,
                        )
                        if res == "OK":
                            for rfc, details in clients.items():
                                log_item(f"VALIDANDO {rfc}")
                                self._read()
                                validar_client(rfc, details)
                            log_item("FIN")
                        else:
                            log_item("OPERACION CANCELADA")

                    case "prepare_facturas":
                        log_line("PREPARAR FACTURAS")
                        facturas = generate_ingresos(
                            config=self.config,
                            clients=ClientsManager(),
                            facturas=FacturasManager()["Facturas"],
                            values=values,
                            csd_signer=self.csd_signer,
                            base_template=self.base_template
                        )
                        if facturas:
                            for i, cfdi in enumerate(facturas, start=1):
                                log_item(f"FACTURA NUMERO: {i}")
                                self.log_cfdi(cfdi)

                            self.invoice_button_manager.set_invoices(
                                facturas
                            )

                    case "prepare_pago":
                        log_line("COMPROBANTE PAGO")
                        if i := factura_seleccionada:
                            cfdi_pago = pago_factura(
                                config=self.config,
                                factura_pagar=i,
                                fecha_pago=values["fecha_pago"],
                                forma_pago=values["forma_pago"],
                                csd_signer=self.csd_signer,
                                lugar_expedicion=self.base_template["LugarExpedicion"]
                            )
                            if cfdi_pago:
                                self.log_cfdi(cfdi_pago)
                                self.invoice_button_manager.set_invoices(
                                    [cfdi_pago]
                                )

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

                    case "pago_pue":
                        if i := factura_seleccionada:
                            self.log_cfdi(i)
                            self.local_db.describe(i)
                            st = self.local_db.pue_pagada(i)
                            res = PySimpleGUI.popup(
                                f"Estas seguro que quieres marcarla como {'-NO- ' if st else ''}pagada?",
                                title=self.window[event].ButtonText,
                                button_type=POPUP_BUTTONS_OK_CANCEL,
                            )
                            if res == "OK":
                                self.console.update("")
                                self.local_db.pue_pagada_set(i.uuid, not st)
                                self.log_cfdi(i)
                                self.local_db.describe(i)
                                print(f"FACTURA MARCADA COMO {'-NO- ' if st else ''}PAGADA")

                    case "ignorar_ppd":
                        if i := factura_seleccionada:
                            self.log_cfdi(i)
                            self.local_db.describe(i)
                            st = self.local_db.ppd_ignorar(i)
                            res = PySimpleGUI.popup(
                                f"Estas seguro que quieres marcarla como {'-NO- ' if st else ''}ignorada?",
                                title=self.window[event].ButtonText,
                                button_type=POPUP_BUTTONS_OK_CANCEL,
                            )
                            if res == "OK":
                                self.console.update("")
                                self.local_db.ppd_ignorar_set(i.uuid, not st)
                                self.log_cfdi(i)
                                self.local_db.describe(i)
                                print(f"FACTURA MARCADA COMO {'-NO- ' if st else ''}IGNORADA")

                    case "email_notificada":
                        if i := factura_seleccionada:
                            self.log_cfdi(i)
                            self.local_db.describe(i)
                            st = self.local_db.email_notificada(i)
                            res = PySimpleGUI.popup(
                                f"Estas seguro que quieres marcarla como {'-NO- ' if st else ''}notificada?",
                                title=self.window[event].ButtonText,
                                button_type=POPUP_BUTTONS_OK_CANCEL,
                            )
                            if res == "OK":
                                self.console.update("")
                                self.local_db.email_notificada_set(i.uuid, not st)
                                self.log_cfdi(i)
                                self.local_db.describe(i)
                                print(f"FACTURA MARCADA COMO {'-NO- ' if st else ''}NOTIFICADA")

                    case "crear_facturas":
                        log_line("CREAR FACTURAS")
                        res = PySimpleGUI.popup(
                            f"Estas seguro que quieres crear {len(invoices_to_create)} facturas?",
                            title=self.window[event].ButtonText,
                            button_type=POPUP_BUTTONS_OK_CANCEL,
                        )
                        if res == "OK":
                            self.all_invoices = None
                            for invoice in invoices_to_create:
                                cfdi = self.generate_invoice(invoice=invoice)
                                if cfdi is None:
                                    break
                                print_yaml({
                                    "FacturaGenerada": cfdi_header(cfdi),
                                })
                                self._read()
                            log_item("FIN")
                        else:
                            log_item("OPERACION CANCELADA")

                    case "prepare_correos":
                        log_line("PREPARAR CORREOS")
                        now = date.today()
                        dp = DatePeriod(now.year, now.month)
                        clients = ClientsManager()
                        a_invoices = self.get_all_invoices()

                        cfdi_correos = []
                        for receptor_rfc, notify_invoices in itertools.groupby(
                                sorted(
                                    (i for i in a_invoices.values() if not i.notified),
                                    key=lambda r: r["Receptor"]["Rfc"]
                                ),
                                lambda r: r["Receptor"]["Rfc"]
                        ):
                            notify_invoices = list(notify_invoices)
                            fac_pen = filter_invoices_iter(
                                invoices=a_invoices.values(),
                                fecha=lambda x: x < dp,
                                invoice_type="I",
                                pending_balance=lambda x: x > 0,
                                rfc_emisor=self.csd_signer.rfc,
                                rfc_receptor=receptor_rfc,
                                estatus='1'
                            )
                            receptor = clients[receptor_rfc]
                            cfdi_correos.append((receptor, notify_invoices, sorted(fac_pen, key=lambda r: r["Fecha"])))

                        if cfdi_correos:
                            self.email_button_manager.set_emails(
                                cfdi_correos
                            )
                        else:
                            print("No hay correos pendientes de enviar")

                    case "enviar_correos":
                        log_line("ENVIAR CORREOS")
                        res = PySimpleGUI.popup(
                            f"Estas seguro que quieres enviar {len(emails_to_send)} correos?",
                            title=self.window[event].ButtonText,
                            button_type=POPUP_BUTTONS_OK_CANCEL
                        )
                        if res == "OK":
                            self.enviar_correos(emails_to_send)
                            log_item("FIN")
                        else:
                            log_item("OPERACION CANCELADA")

                    case "facturas_pendientes":
                        clients = ClientsManager()
                        log_line("FACTURAS PENDIENTES")

                        fac_pen = filter_invoices_iter(
                            invoices=self.get_all_invoices().values(),
                            invoice_type="I",
                            pending_balance=lambda x: x > 0,
                            rfc_emisor=self.csd_signer.rfc,
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
                                'FacturasPendientes': [
                                    {
                                        "Factura": f"{i.name} - {i.uuid}",
                                        'SaldoPendiente': i.saldo_pendiente,
                                        'Fecha': i["Fecha"]
                                    }
                                    for i in sorted(fac_pen, key=lambda r: r["Fecha"])
                                ]
                            }
                            print_yaml(f)

                    case "descarga":
                        log_line('DESCARGADA')
                        try:
                            res = self.pac_service.recover(values["factura_pagar"], accept=Accept.XML_PDF)
                            self.all_invoices = None
                            cfdi = move_to_folder(res.xml, pdf_data=res.pdf)
                            self.log_cfdi(cfdi, ver_saldo=False)
                        except DocumentNotFoundError:
                            logger.info("Factura no encontrada")

                    case "exportar_facturas":
                        log_line("EXPORTAR FACTURAS")
                        exportar_facturas(self.get_all_invoices(), values["periodo"], self.csd_signer.rfc, self.issuer_cif['RegimenFiscal'])

                    case "ver_excel":
                        archivo_excel = exportar_facturas_filename(values["periodo"])
                        os.startfile(
                            os.path.abspath(archivo_excel)
                        )

                    case "periodo" | "inicio" | "final" | "fecha_pago" | "forma_pago":
                        pass

                    case _:
                        logger.error(f"Unknown event '{event}'")

            except Exception as ex:
                logger.exception(header_line("ERROR"))
