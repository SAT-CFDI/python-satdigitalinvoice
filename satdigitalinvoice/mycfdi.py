import atexit
import glob
import logging
import os
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from itertools import groupby
from typing import MutableMapping
from uuid import UUID

import diskcache
from satcfdi import DatePeriod
from satcfdi.accounting import filter_invoices_by, InvoiceType, complement_invoices_data, SatCFDI
from satcfdi.accounting.email import EmailSender
from satcfdi.exceptions import ResponseError
from satcfdi.pacs import Accept

from . import EMISOR, PAC_SERVICE
from .file_data_managers import CanceladosManager, PaymentsManager, NotificationsManager, ClientsManager, environment_default

ALL_INVOICES = b'all_invoices'
ALL_RETENCIONES = b'all_retenciones'

logging.basicConfig(level=logging.INFO)
logging.getLogger("weasyprint").setLevel(logging.ERROR)
logging.getLogger("fontTools").setLevel(logging.ERROR)
logging.getLogger("azure").setLevel(logging.ERROR)

logger = logging.getLogger()

cancelados_manager = CanceladosManager()
payments_manager = PaymentsManager()
notifications = NotificationsManager()
clients = ClientsManager()

pagados = payments_manager["Pagados"]
ignorar = payments_manager["IgnorarPendienteDePago"]

PPD = "PPD"
PUE = "PUE"

cache = diskcache.Cache("tmp")


class MyCFDI(SatCFDI):
    _only_cache = True

    @classmethod
    def cache_setting(cls, only_cache):
        cls._only_cache = only_cache

        def save_cancelados():
            cancelados_manager.save()

        if not only_cache:
            atexit.register(save_cancelados)

    def consulta_estado(self):
        return cancelados_manager.get_state(self, only_cache=self._only_cache)

    @SatCFDI.estatus.getter
    def estatus(self) -> str:
        Estatus = {
            "Cancelado": "0",
            "Vigente": "1"
        }
        estado = cancelados_manager.get_state(self, only_cache=self._only_cache).get('Estado')
        return Estatus.get(estado, "1")

    @SatCFDI.fecha_cancelacion.getter
    def fecha_cancelacion(self) -> datetime:
        return None

    @SatCFDI.saldo_pendiente.getter
    def saldo_pendiente(self) -> Decimal:
        if self['TipoDeComprobante'] == "I" and self["Emisor"]["Rfc"] == EMISOR.rfc:
            if self["MetodoPago"] == PPD:
                if self.name in ignorar:
                    return Decimal()

            if self["MetodoPago"] == PUE and not self.payments:
                if self.name in pagados:
                    return Decimal()
                else:
                    return self['Total']

        return super().saldo_pendiente

    @classmethod
    def get_all_invoices(cls, invoices: MutableMapping, search_path="*.xml") -> bool:
        # Check that all names are correct
        for file in glob.iglob(search_path, recursive=True):
            if not cls.uuid_from_filename(filename=file):
                invoice = cls.from_file(file)
                rename_invoice(file, invoice)

        # Load Invoices
        dup_check = set()
        was_updated = False

        for file in glob.iglob(search_path, recursive=True):
            fid = cls.uuid_from_filename(filename=file)
            if fid:
                if fid not in invoices:
                    was_updated = True
                    invoices[fid] = cls.from_file(file)
            else:
                raise Exception("CFDI with invalid File Name")

            # Check we don't have a duplicate
            if fid not in dup_check:
                dup_check.add(fid)
            else:
                raise Exception("Duplicated Invoice Found", fid, file)

        # Remove extra
        if len(dup_check) < len(invoices):
            was_updated = True
            for i in list(invoices.keys()):
                if i not in dup_check:
                    del invoices[i]

        # if the length does not match, then we need to try again :-/
        return was_updated

    @property
    def filename(self):
        match self.tag:
            case '{http://www.sat.gob.mx/cfd/3}Comprobante' | '{http://www.sat.gob.mx/cfd/4}Comprobante':
                return "facturas/{3:%Y}/{3:%Y-%m}/{4}/{3:%Y-%m-%d}_{0}_[{1}]_{2}".format(
                        self.name,
                        self["TipoDeComprobante"].code,
                        self.uuid,
                        self["Fecha"],
                        "Emitidas" if self["Emisor"]["Rfc"] == EMISOR.rfc else "Recibidas"
                    )
            case '{http://www.sat.gob.mx/esquemas/retencionpago/1}Retenciones' | '{http://www.sat.gob.mx/esquemas/retencionpago/2}Retenciones':
                return "retenciones/{2:%Y}/{2:%Y-%m}/{3}/{2:%Y-%m-%d}_{0}_{1}".format(
                        self.get("FolioInt", ""),
                        self.uuid,
                        self["FechaExp"],
                        "Emitidas" if self["Emisor"]["RFCEmisor"] == EMISOR.rfc else "Recibidas"
                    )

    @classmethod
    def uuid_from_filename(cls, filename):
        filename = os.path.basename(filename)
        parts = os.path.splitext(filename)[0].split("_")
        if len(parts) >= 3:
            try:
                return UUID(parts[-1])
            except ValueError:
                pass
        return None

    @property
    def notified(self) -> bool:
        return self["Emisor"]["Rfc"] != EMISOR.rfc \
            or self["Fecha"] <= notifications['NotifiedAfter'] \
            or str(self.uuid) in notifications['Notified']

    @notified.setter
    def notified(self, value):
        notifications['Notified'][str(self.uuid)] = value
        notifications.save()


def rename_invoice(file, invoice: MyCFDI, include_pdf=True):
    preferred_filename = invoice.filename
    if preferred_filename + ".xml" != file:
        os.makedirs(os.path.dirname(preferred_filename), exist_ok=True)

        try:
            os.rename(file, preferred_filename + ".xml")
        except FileExistsError:
            os.remove(file)

        if include_pdf:
            try:
                os.rename(file[:-4] + ".pdf", preferred_filename + ".pdf")
            except FileExistsError:
                os.remove(file[:-4] + ".pdf")
            except FileNotFoundError:
                logger.warning("PDF Not found for %s, will create one instead", preferred_filename + ".pdf")
                invoice.pdf_write(preferred_filename + ".pdf")


def move_to_folder(xml_data, pdf_data):
    cfdi = MyCFDI.from_string(xml_data)

    full_name = cfdi.filename
    os.makedirs(os.path.dirname(full_name), exist_ok=True)

    try:
        with open(full_name + ".xml", 'xb') as fp:
            fp.write(xml_data)
        logger.info("Invoice has been added '%s'", full_name)

        if pdf_data:
            with open(full_name + ".pdf", 'wb') as fp:
                fp.write(pdf_data)
        else:
            try:
                cfdi.pdf_write(full_name + ".pdf")
            except:
                logger.exception("Failed to create PDF")
    except FileExistsError:
        logger.info("Invoice already found %s", full_name)

    return cfdi


def get_all_cfdi() -> Mapping[UUID, MyCFDI]:
    all_invoices = cache.get(ALL_INVOICES, {})

    has_updates = MyCFDI.get_all_invoices(invoices=all_invoices, search_path="facturas/**/*.xml")
    if has_updates:
        cache[ALL_INVOICES] = all_invoices

    complement_invoices_data(all_invoices)
    return all_invoices


def get_all_retenciones() -> Mapping[UUID, MyCFDI]:
    all_invoices = cache.get(ALL_RETENCIONES, {})

    has_updates = MyCFDI.get_all_invoices(invoices=all_invoices, search_path="retenciones/**/*.xml")
    if has_updates:
        cache[ALL_RETENCIONES] = all_invoices

    return all_invoices


def email_invoices(all_invoices: Mapping[UUID, MyCFDI], email_sender: EmailSender):
    now = datetime.now()
    dp = DatePeriod(now.year, now.month)

    with email_sender as s:
        for receptor_rfc, notify_invoices in groupby(
                sorted(
                    (i for i in all_invoices.values() if not i.notified),
                    key=lambda r: r["Receptor"]["Rfc"]
                ),
                lambda r: r["Receptor"]["Rfc"]
        ):
            notify_invoices = list(notify_invoices)  # type: list[MyCFDI]
            client = clients[receptor_rfc]
            receptor_nombre = client["RazonSocial"]
            to_addrs = client["Email"]
            template = environment_default.get_template(
                client.get('EmailTemplate', 'mail_facturas_template.html')
            )
            email_review = client.get("EmailReview", False)

            attachments = []
            for r in notify_invoices:
                attachments.append(r.filename + ".xml")
                attachments.append(r.filename + ".pdf")

            fac_pen = filter_invoices_by(
                invoices=all_invoices,
                fecha=lambda x: x < dp,
                invoice_type=InvoiceType.PAYMENT_PENDING,
                rfc_emisor=EMISOR.rfc,
                rfc_receptor=receptor_rfc,
                estatus='1'
            )
            facturas_pendientes = ", ".join(r.name for r in fac_pen)

            message = template.render(
                invoices=notify_invoices,
                pending_invoices=facturas_pendientes
            )

            print("Confirm Email To:", receptor_nombre, to_addrs)
            print("Facturas:", [r.name for r in notify_invoices])
            print("Facturas Pendientes:", facturas_pendientes)
            user_input = input("Confirm send (y/n/r) [n]:").upper()

            if user_input in ("Y", "R"):
                if email_review or user_input == "R":
                    message = f"Enviar a: {','.join(to_addrs)}<br><br>" + message
                    to_addrs = [email_sender.user]

                s.send_email(
                    subject=f"Comprobantes Fiscales {receptor_nombre} - {receptor_rfc}",
                    to_addrs=to_addrs,
                    html=message,
                    file_attachments=attachments
                )

            for r in notify_invoices:
                r.notified = ",".join(to_addrs)


def generate_invoice(invoice, ref_id):
    try:
        res = PAC_SERVICE.stamp(
            cfdi=invoice,
            accept=Accept.XML_PDF,
            ref_id=ref_id
        )
        serie = invoice.get("Serie")
        folio = invoice.get("Folio")
        if serie and folio:
            notifications.set_folio(serie, folio)
        cfdi = move_to_folder(res.xml, pdf_data=res.pdf)
        logger.info(f'Factura Generada {serie}{folio} {cfdi["Receptor"]["Rfc"]}')
    except ResponseError as ex:
        logger.error(f"Status Code {ex.response.status_code}")
        logger.error(f"Text {ex.response.text}")
        raise

