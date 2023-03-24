import base64
import io
import itertools
import os
import shutil
import logging
from datetime import datetime, timedelta, date
from decimal import Decimal
from uuid import UUID
from zipfile import ZipFile

from PySimpleGUI import POPUP_BUTTONS_OK_CANCEL, PySimpleGUI
from markdown2 import markdown
from satcfdi import DatePeriod, CFDI, Code, Signer
from satcfdi.accounting import filter_invoices_by, InvoiceType
from satcfdi.create import Issuer
from satcfdi.exceptions import ResponseError, DocumentNotFoundError
from satcfdi.pacs import Accept
from satcfdi.pacs.sat import SAT, TipoDescargaMasivaTerceros, EstadoSolicitud
# noinspection PyUnresolvedReferences
from satcfdi.transform.catalog import CATALOGS

from weasyprint import HTML, CSS

from . import SOURCE_DIRECTORY, __version__, local
from .client_validation import validar_client
from .file_data_managers import environment_default, environment_bold_escaped, ClientsManager, ConfigManager
from .formatting_functions.common import fecha, pesos, porcentaje
from .gui_functions import generate_ingresos, pago_factura, find_ajustes, format_concepto_desc, exportar_facturas, exportar_facturas_filename, parse_ym_date
from .layout import make_layout, InvoiceButtonManager, EmailButtonManager
from .log_tools import LogHandler, LogAdapter, log_line, log_item, cfdi_header
from .mycfdi import get_all_cfdi, MyCFDI, move_to_folder, local_db, PPD, PUE

logging.basicConfig(level=logging.INFO)
logging.getLogger("weasyprint").setLevel(logging.ERROR)
logging.getLogger("fontTools").setLevel(logging.ERROR)

logger = LogAdapter(logging.getLogger())

AJUSTES_DIR = "ajustes"
template = environment_default.get_template(
    'mail_facturas_template.html'
)


class FacturacionGUI:
    def __init__(self, pac_service, csd_signer: Signer, email_manager, fiel_signer=None, concepto_adapter=None):
        self.email_manager = email_manager
        self.pac_service = pac_service
        self.sat_service = SAT(
            signer=fiel_signer
        )
        self.concepto_adapter = concepto_adapter
        clients = ClientsManager()

        self.issuer_cif = clients[csd_signer.rfc]
        self.lugar_expedicion = self.issuer_cif['CodigoPostal']
        self.issuer = Issuer(
            signer=csd_signer,
            tax_system=self.issuer_cif['RegimenFiscal'],
            legal_name=self.issuer_cif['RazonSocial']
        )

        MyCFDI.issuer_rfc = self.issuer.rfc
        window = PySimpleGUI.Window(
            f"Facturacion 4.0  RazonSocial: {self.issuer.legal_name}  RFC: {self.issuer.rfc}  "
            f"Serie: {local.config.serie()}  Regimen: {self.issuer.tax_system}  LugarExpedicion: {self.lugar_expedicion}",
            make_layout(fiel_signer is not None),
            size=(1280, 800),
            resizable=True,
        )
        self.window = window

        self.ch = LogHandler(self.window['console'])
        self.ch.setLevel(logging.INFO)
        logging.getLogger().addHandler(self.ch)

        self.invoice_button_manager = InvoiceButtonManager(window["crear_facturas"], window["detallado"])
        self.email_button_manager = EmailButtonManager(window["enviar_correos"])
        self.all_invoices = None

    def initial_screen(self):
        signer = self.issuer.signer

        def convert_ans1_date(ans1_date):
            return datetime.strptime(ans1_date.decode('utf-8'), '%Y%m%d%H%M%SZ')

        try:
            logger.info_yaml({
                "Version": __version__.__version__,
                "Facturacion": "CFDI 4.0",
                "Emisor": self.issuer_cif,
                "Certificado": {
                    "No Certificado": signer.certificate_number,
                    "Curp": str(signer.curp),
                    "Sucursal": signer.branch_name,
                    "Expiracion": convert_ans1_date(signer.certificate.get_notAfter()),
                    "Creacion": convert_ans1_date(signer.certificate.get_notBefore()),
                    "Typo": str(signer.type)
                },
                "Config": local.config,
            })
        except:
            logger.exception("Error al obtener datos")

    def start(self):
        self.window.finalize()
        self.initial_screen()
        self.main_loop()
        self.window.close()

    def get_all_invoices(self):
        if self.all_invoices:
            return self.all_invoices
        self.all_invoices = get_all_cfdi()
        return self.all_invoices

    def generate_invoice(self, invoice, ref_id=None):
        res = self.pac_service.stamp(
            cfdi=invoice,
            accept=Accept.XML_PDF,
            ref_id=ref_id
        )
        local.config.inc_folio()
        return move_to_folder(res.xml, pdf_data=res.pdf)

    def enviar_correos(self, emails):
        with self.email_manager.sender as s:
            for receptor, notify_invoices, facturas_pendientes in emails:
                receptor_nombre = receptor["RazonSocial"]
                to_addrs = receptor["Email"]

                attachments = []
                for r in notify_invoices:
                    attachments += [r.filename + ".xml", r.filename + ".pdf"]

                message = self.generate_html_template(
                    'mail_facturas_template.html',
                    fields={
                        'invoices': notify_invoices,
                        'pending_invoices': facturas_pendientes,
                    }
                )

                s.send_email(
                    subject=f"Comprobantes Fiscales {receptor_nombre} - {receptor['Rfc']}",
                    to_addrs=to_addrs,
                    html=message,
                    file_attachments=attachments
                )

                self.window.read(timeout=0)

                for r in notify_invoices:
                    r.notified = ",".join(to_addrs)

    def recupera_comprobantes(self, id_solicitud):
        response = self.sat_service.recover_comprobante_status(
            id_solicitud=id_solicitud
        )
        logger.info_yaml(response)
        self.window.read(timeout=0)
        if response["EstadoSolicitud"] == EstadoSolicitud.Terminada:
            for id_paquete in response['IdsPaquetes']:
                response, paquete = self.sat_service.recover_comprobante_download(
                    id_paquete=id_paquete
                )
                logger.info_yaml(response)
                self.window.read(timeout=0)
                yield id_paquete, base64.b64decode(paquete) if paquete else None

    def unzip_cfdi(self, file):
        with ZipFile(file, "r") as zf:
            for fileinfo in zf.infolist():
                xml_data = zf.read(fileinfo)
                move_to_folder(xml_data, pdf_data=None)
                self.window.read(timeout=0)

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
        try:
            factura_uuid = UUID(text)
            factura = self.get_all_invoices().get(factura_uuid)
            if factura:
                return factura
        except:
            pass

    def factura_buscar(self, text):
        if text:
            emisor_rfc = self.issuer.rfc
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

    def log_cfdi(self, cfdi: CFDI):
        cfdi_copy = cfdi.copy()
        del cfdi_copy["Certificado"]
        del cfdi_copy["Sello"]

        if not self.window['detallado'].get():
            del cfdi_copy["Serie"]
            del cfdi_copy["NoCertificado"]
            cfdi_copy.pop("Emisor")
            cfdi_copy["Receptor"] = f"{cfdi_copy['Receptor']['Rfc']}, {cfdi_copy['Receptor']['Nombre']}, {cfdi_copy['Receptor']['RegimenFiscalReceptor']}"
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

        logger.info_yaml(cfdi_copy)

    def main_loop(self):
        factura_seleccionada = None  # type: MyCFDI | None

        while True:
            event, values = self.window.read()
            local.config = ConfigManager()
            try:
                if event in ("Exit", PySimpleGUI.WIN_CLOSED):
                    return

                if event not in ("crear_facturas", "enviar_correos", "confirm_pago_button", "ver_factura", "ver_excel"):
                    self.ch.clear()
                invoices_to_create = self.invoice_button_manager.clear()
                emails_to_send = self.email_button_manager.clear()

                match event:
                    case "about":
                        self.initial_screen()

                    case "factura_pagar" | "buscar_factura":
                        text = self.window["factura_pagar"].get().strip()
                        if event == "buscar_factura":
                            factura_seleccionada = self.factura_uuid(text)
                            if not factura_seleccionada:
                                factura_seleccionada = self.factura_buscar(text)
                        else:
                            factura_seleccionada = self.factura_uuid(text)

                        if factura_seleccionada:
                            self.log_cfdi(factura_seleccionada)
                            local_db.describe(factura_seleccionada)

                        not_ppd = not factura_seleccionada or factura_seleccionada.get("MetodoPago") != PPD or factura_seleccionada.estatus != "1" or \
                                  factura_seleccionada["Emisor"]["Rfc"] != self.issuer.rfc
                        self.window["status_sat"].update(disabled=not factura_seleccionada)
                        self.window["pago_pue"].update(
                            disabled=not factura_seleccionada
                                     or factura_seleccionada.get("MetodoPago") != PUE
                                     or factura_seleccionada.estatus != "1"
                                     or factura_seleccionada["Emisor"]["Rfc"] != self.issuer.rfc
                        )

                        self.window["email_notificada"].update(
                            disabled=not factura_seleccionada
                                     or factura_seleccionada["Emisor"]["Rfc"] != self.issuer.rfc
                        )
                        self.window["ver_factura"].update(disabled=not factura_seleccionada)

                        self.window["ignorar_ppd"].update(disabled=not_ppd)
                        self.window["prepare_pago"].update(disabled=not_ppd)
                        self.window["fecha_pago_select"].update(disabled=not_ppd)
                        self.window["fecha_pago"].update(disabled=not_ppd)
                        self.window["forma_pago"].update(disabled=not_ppd)

                        def is_uuid(s):
                            try:
                                UUID(s)
                                return True
                            except ValueError:
                                return False

                        self.window["descarga"].update(disabled=not is_uuid(text))

                    case "preparar_ajuste_anual":
                        log_item(f"AJUSTE ANUAL")
                        ym_date = parse_ym_date(values['anio_mes_ajuste'])
                        ajuste_porcentaje = values['ajuste_porcentaje']
                        if not ajuste_porcentaje:
                            logger.error("Especificar Ajuste Porcetaje")
                            continue

                        ajuste_porcentaje = Decimal(ajuste_porcentaje) / 100

                        shutil.rmtree(AJUSTES_DIR, ignore_errors=True)
                        os.makedirs(AJUSTES_DIR, exist_ok=True)
                        clients = ClientsManager()

                        has_ajustes = False
                        for i, (rfc, concepto) in enumerate(find_ajustes(ym_date.month), start=1):
                            has_ajustes = True
                            receptor = clients[rfc]
                            valor_unitario_nuevo = concepto["ValorUnitario"] * (1 + ajuste_porcentaje)
                            format_concepto_desc(concepto, periodo="INMUEBLE")

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
                            logger.info_yaml(data)
                            res = self.generate_pdf_template(template_name='incremento_template.md', fields=data)
                            file_name = f'{AJUSTES_DIR}/AjusteRenta_{rfc}_{concepto["CuentaPredial"]}.pdf'
                            with open(file_name, 'wb') as f:
                                f.write(res)
                            self.window.read(timeout=0)

                        if has_ajustes:
                            os.startfile(
                                os.path.abspath(AJUSTES_DIR)
                            )

                    case "recuperar_emitidas" | "recuperar_recibidas":
                        log_line("RECUPERAR")
                        fecha_final = date.today()
                        fecha_inicial = fecha_final - timedelta(days=int(values["recuperar_dias"]))
                        id_solicitud = local.config.get(event)

                        if not id_solicitud:
                            logger.info("Creando Nueva Solicitud")
                            self.window.read(timeout=0)
                            response = self.sat_service.recover_comprobante_request(
                                fecha_inicial=fecha_inicial,
                                fecha_final=fecha_final,
                                rfc_receptor=self.sat_service.signer.rfc if "recuperar_recibidas" == event else None,
                                rfc_emisor=self.sat_service.signer.rfc if "recuperar_emitidas" == event else None,
                                tipo_solicitud=TipoDescargaMasivaTerceros.CFDI,
                            )
                            logger.info_yaml(response)
                            local.config[event] = response['IdSolicitud']
                            local.config.save()
                        else:
                            logger.info_yaml({
                                'IdSolicitud': id_solicitud
                            })
                            self.window.read(timeout=0)
                            for paquete_id, data in self.recupera_comprobantes(id_solicitud):
                                if data:
                                    self.all_invoices = None
                                    with io.BytesIO(data) as b:
                                        self.unzip_cfdi(b)
                                del local.config[event]
                                local.config.save()

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
                                self.window.read(timeout=0)
                                validar_client(rfc, details)
                            log_item("FIN")
                        else:
                            log_item("OPERACION CANCELADA")

                    case "prepare_facturas":
                        log_line("PREPARAR FACTURAS")
                        facturas = generate_ingresos(values, self.issuer, self.lugar_expedicion, self.concepto_adapter)
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
                                factura_pagar=i,
                                fecha_pago=values["fecha_pago"],
                                forma_pago=values["forma_pago"],
                                issuer=self.issuer,
                                lugar_expedicion=self.lugar_expedicion
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
                            estado = local_db.status_sat(i, update=True)
                            logger.info_yaml(estado)
                            local_db.describe(i)

                    case "pago_pue":
                        if i := factura_seleccionada:
                            self.log_cfdi(i)
                            local_db.describe(i)
                            st = local_db.pue_pagada(i)
                            res = PySimpleGUI.popup(
                                f"Estas seguro que quieres marcarla como {'-NO- ' if st else ''}pagada?",
                                title=self.window[event].ButtonText,
                                button_type=POPUP_BUTTONS_OK_CANCEL,
                            )
                            if res == "OK":
                                self.ch.clear()
                                local_db.pue_pagada_set(i.uuid, not st)
                                self.log_cfdi(i)
                                local_db.describe(i)
                                logger.info(f"FACTURA MARCADA COMO {'-NO- ' if st else ''}PAGADA")

                    case "ignorar_ppd":
                        if i := factura_seleccionada:
                            self.log_cfdi(i)
                            local_db.describe(i)
                            st = local_db.ppd_ignorar(i)
                            res = PySimpleGUI.popup(
                                f"Estas seguro que quieres marcarla como {'-NO- ' if st else ''}ignorada?",
                                title=self.window[event].ButtonText,
                                button_type=POPUP_BUTTONS_OK_CANCEL,
                            )
                            if res == "OK":
                                self.ch.clear()
                                local_db.ppd_ignorar_set(i.uuid, not st)
                                self.log_cfdi(i)
                                local_db.describe(i)
                                logger.info(f"FACTURA MARCADA COMO {'-NO- ' if st else ''}IGNORADA")

                    case "email_notificada":
                        if i := factura_seleccionada:
                            self.log_cfdi(i)
                            local_db.describe(i)
                            st = local_db.email_notificada(i)
                            res = PySimpleGUI.popup(
                                f"Estas seguro que quieres marcarla como {'-NO- ' if st else ''}notificada?",
                                title=self.window[event].ButtonText,
                                button_type=POPUP_BUTTONS_OK_CANCEL,
                            )
                            if res == "OK":
                                self.ch.clear()
                                local_db.email_notificada_set(i.uuid, not st)
                                self.log_cfdi(i)
                                local_db.describe(i)
                                logger.info(f"FACTURA MARCADA COMO {'-NO- ' if st else ''}NOTIFICADA")

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
                                try:
                                    cfdi = self.generate_invoice(invoice=invoice)
                                    logger.info(f'Factura Generada: {cfdi_header(cfdi)}')
                                    self.window.read(timeout=0)
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
                        now = datetime.now()
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
                            fac_pen = filter_invoices_by(
                                invoices=a_invoices,
                                fecha=lambda x: x < dp,
                                invoice_type=InvoiceType.PAYMENT_PENDING,
                                rfc_emisor=self.issuer.rfc,
                                rfc_receptor=receptor_rfc,
                                estatus='1'
                            )
                            receptor = clients[receptor_rfc]
                            cfdi_correos.append((receptor, notify_invoices, fac_pen))

                        if cfdi_correos:
                            self.email_button_manager.set_emails(
                                cfdi_correos
                            )
                        else:
                            logger.info("No hay correos pendientes de enviar")

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

                        fac_pen = filter_invoices_by(
                            invoices=self.get_all_invoices(),
                            invoice_type=InvoiceType.PAYMENT_PENDING,
                            rfc_emisor=self.issuer.rfc,
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
                            res = self.pac_service.recover(values["factura_pagar"], accept=Accept.XML_PDF)
                            self.all_invoices = None
                            cfdi = move_to_folder(res.xml, pdf_data=res.pdf)
                            self.log_cfdi(cfdi)
                        except DocumentNotFoundError:
                            logger.info("Factura no encontrada")

                    case "exportar_facturas":
                        log_line("EXPORTAR FACTURAS")
                        exportar_facturas(self.get_all_invoices(), values["periodo"], self.issuer)

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
                log_line("ERROR")
                logger.exception(ex)
