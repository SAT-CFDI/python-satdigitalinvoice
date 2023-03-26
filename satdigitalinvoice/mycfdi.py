import atexit
import glob
import logging
import os
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import MutableMapping
from uuid import UUID

import diskcache
from satcfdi.accounting import complement_invoices_data, SatCFDI
from satcfdi.pacs import Accept

from . import EMISOR, PAC_SERVICE
from .file_data_managers import CanceladosManager, PaymentsManager, NotificationsManager, ClientsManager

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
        logger.info("Factura ha sido agregada: '%s'", full_name)

        if pdf_data:
            with open(full_name + ".pdf", 'wb') as fp:
                fp.write(pdf_data)
        else:
            try:
                cfdi.pdf_write(full_name + ".pdf")
            except:
                logger.exception("Fallo crear PDF: '%s'", full_name)
    except FileExistsError:
        logger.info("Factura ya se tenia: %s", full_name)

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


def generate_invoice(invoice, ref_id=None):
    res = PAC_SERVICE.stamp(
        cfdi=invoice,
        accept=Accept.XML_PDF,
        ref_id=ref_id
    )
    serie = invoice.get("Serie")
    folio = int(invoice.get("Folio"))
    if serie and folio:
        notifications.set_folio(serie, folio)
    return move_to_folder(res.xml, pdf_data=res.pdf)
