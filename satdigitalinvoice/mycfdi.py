import glob
import hashlib
import json
import logging
import os
from collections.abc import Mapping
from datetime import datetime
from enum import Enum
from typing import MutableMapping
from uuid import UUID

from satcfdi import render
from satcfdi.accounting import complement_invoices_data, SatCFDI
from satcfdi.accounting.models import EstadoComprobante
from satcfdi.create.cfd.catalogos import TipoDeComprobante, MetodoPago, TipoRelacion
from satcfdi.pacs import sat
from satcfdi.utils import iterate

from .utils import to_uuid, code_str, estado_to_estatus

ALL_INVOICES = 'all_invoices'
ALL_RETENCIONES = 'all_retenciones'
ALL_TRANSFERENCIAS = 'all_trasferencias'
logger = logging.getLogger(__name__)

sat_manager = sat.SAT()


class LiquidatedState(Enum):
    NONE = 1
    PAID = 2
    PENDING = 3
    IGNORED = 4
    CANCELLED = 5

    def __str__(self):
        if self.name == "NONE":
            return ""
        if self.name == "IGNORED":
            return "🚫"
        if self.name == "PAID":
            return "✔"
        if self.name == "PENDING":
            return "⏳"
        if self.name == "CANCELLED":
            return "❌"


def generate_pseudo_random_guid(cadena):
    hash_object = hashlib.md5()
    hash_object.update(cadena.encode('utf-8'))
    return UUID(hash_object.hexdigest())


class MyCFDI(SatCFDI):
    local_db = None
    base_dir = None  # type: str
    enviar_a_partir = None
    pagar_a_partir = None

    def estatus(self) -> EstadoComprobante:
        return EstadoComprobante(self.status_sat().get('Estatus', '1'))

    def consulta_estado(self) -> dict:
        return self.status_sat(update=False)

    def status_sat(self, update=False) -> dict:
        if update:
            res = sat_manager.status(self)
            if res["ValidacionEFOS"] == "200":
                self.local_db.status_merge(
                    uuid=self.uuid,
                    estatus=estado_to_estatus(res["Estado"]),
                    es_cancelable=res["EsCancelable"],
                    estatus_cancelacion=res["EstatusCancelacion"]
                )
            else:
                raise ValueError("Error al actualizar estado de %s: %s", self.uuid, res)
            return res
        else:
            return self.local_db.status(self.uuid)

    @SatCFDI.fecha_cancelacion.getter
    def fecha_cancelacion(self) -> datetime | None:
        return self.status_sat().get('FechaCancelacion')

    @classmethod
    def rename_invoices(cls, search_path="*.xml"):
        # Check that all names are correct
        for file in glob.iglob(os.path.join(cls.base_dir, search_path), recursive=True):
            cls.rename_invoice(file)

    @classmethod
    def get_all_invoices(cls, invoices: MutableMapping, search_path="*.xml") -> bool:
        # Check that all names are correct
        for file in glob.iglob(search_path, recursive=True):
            if not cls.uuid_from_filename(filename=file):
                cls.rename_invoice(file)

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
                path = "{3:%Y}/{3:%Y-%m}/facturas/{4}_{0}_[{1}]_{2}".format(
                    self.name,
                    code_str(self["TipoDeComprobante"]),
                    self.uuid,
                    self["Fecha"],
                    self["Emisor"]["Rfc"],
                )
            case '{http://www.sat.gob.mx/esquemas/retencionpago/1}Retenciones' | '{http://www.sat.gob.mx/esquemas/retencionpago/2}Retenciones':
                path = "{2:%Y}/{2:%Y-%m}/retenciones/{3}_{0}_{1}".format(
                    self.get("FolioInt", ""),
                    self.uuid,
                    self["FechaExp"],
                    self["Emisor"].get('RFCEmisor') or self["Emisor"].get('RfcE')
                )
            case 'SPEI_Tercero':
                path = "{0:%Y}/{0:%Y-%m}/transferencias/{0:%Y%m%d}_{1}_{2}".format(
                    self["FechaOperacion"],
                    self["Ordenante"]["RFC"],
                    generate_pseudo_random_guid(self['CadenaCDA'])
                )
            case _:
                raise Exception("Unknown Tag", self.tag)

        return os.path.join(self.base_dir, path)

    @classmethod
    def uuid_from_filename(cls, filename):
        filename = os.path.basename(filename)
        parts = os.path.splitext(filename)[0].split("_")
        if len(parts) >= 3:
            return to_uuid(parts[-1])
        return None

    @classmethod
    def move_to_folder(cls, xml_data, pdf_data):
        cfdi = cls.from_string(xml_data)

        full_name = cfdi.filename
        os.makedirs(os.path.dirname(full_name), exist_ok=True)

        try:
            with open(full_name + ".xml", 'xb') as fp:
                fp.write(xml_data)
            print(f"Factura ha sido agregada: '{full_name}'")

            if pdf_data:
                with open(full_name + ".pdf", 'wb') as fp:
                    fp.write(pdf_data)
            else:
                try:
                    render.pdf_write(cfdi, full_name + ".pdf")
                except:
                    logger.exception("Fallo crear PDF: '%s'", full_name)
        except FileExistsError:
            print(f"Factura ya se tenia: '{full_name}'", full_name)

        return cfdi

    @classmethod
    def get_all_cfdi(cls) -> Mapping[UUID, 'MyCFDI']:
        all_invoices = cls.local_db.load_data(ALL_INVOICES, {})

        has_updates = cls.get_all_invoices(invoices=all_invoices, search_path=os.path.join(cls.base_dir, "*/*/facturas/*.xml"))
        if has_updates:
            cls.local_db.save_data(ALL_INVOICES, all_invoices)

        complement_invoices_data(all_invoices)
        return all_invoices

    @classmethod
    def get_all_retenciones(cls) -> Mapping[UUID, 'MyCFDI']:
        all_invoices = cls.local_db.load_data(ALL_RETENCIONES, {})

        has_updates = cls.get_all_invoices(invoices=all_invoices, search_path=os.path.join(cls.base_dir, "*/*/retenciones/*.xml"))
        if has_updates:
            cls.local_db.save_data(ALL_RETENCIONES, all_invoices)

        return all_invoices

    @classmethod
    def get_all_transferencias(cls) -> Mapping[UUID, 'MyCFDI']:
        all_invoices = cls.local_db.load_data(ALL_TRANSFERENCIAS, {})

        has_updates = cls.get_all_invoices(invoices=all_invoices, search_path=os.path.join(cls.base_dir, "*/*/transferencias/*.xml"))
        if has_updates:
            cls.local_db.save_data(ALL_TRANSFERENCIAS, all_invoices)

        return all_invoices

    @classmethod
    def rename_invoice(cls, file, create_pdf=True):
        invoice = cls.from_file(file)

        preferred_filename = invoice.filename
        xml_preferred = preferred_filename + ".xml"
        if file != xml_preferred:
            os.makedirs(os.path.dirname(preferred_filename), exist_ok=True)
            try:
                os.rename(file, xml_preferred)
            except FileExistsError:
                os.remove(file)

        if create_pdf:
            pdf_current = file[:-4] + ".pdf"
            pdf_preferred = preferred_filename + ".pdf"
            if pdf_current != pdf_preferred or not os.path.exists(pdf_preferred):
                try:
                    os.rename(pdf_current, pdf_preferred)
                except FileExistsError:
                    os.remove(pdf_current)
                except FileNotFoundError:
                    render.pdf_write(invoice, pdf_preferred)

    def notified(self):
        v = self.local_db.notified2(self.uuid)
        if v is None and self["Fecha"] < self.enviar_a_partir:
            return True
        return v

    def notified_flip(self):
        v = not self.notified()
        self.local_db.notified_set2(self.uuid, v)
        return v

    def liquidated(self):
        v = self.local_db.liquidated2(self.uuid)
        if v is None and self["Fecha"] < self.pagar_a_partir[self["MetodoPago"]]:
            return True
        return v

    def liquidated_flip(self):
        v = not self.liquidated()
        self.local_db.liquidated_set2(self.uuid, v)
        return v

    def liquidated_state(self):
        if self.estatus() == EstadoComprobante.CANCELADO:
            return LiquidatedState.CANCELLED

        if self["TipoDeComprobante"] != TipoDeComprobante.INGRESO:
            return LiquidatedState.NONE

        mpago = self["MetodoPago"]
        if self['Total'] == 0 or (mpago == MetodoPago.PAGO_EN_PARCIALIDADES_O_DIFERIDO and self.saldo_pendiente() == 0):
            return LiquidatedState.PAID

        if self.liquidated():
            if mpago == MetodoPago.PAGO_EN_PARCIALIDADES_O_DIFERIDO:
                return LiquidatedState.IGNORED
            return LiquidatedState.PAID

        return LiquidatedState.PENDING

    @property
    def liquidated_notified_icons(self):
        return str(self.liquidated_state()) + str(" 📧" if self.notified() else "   ")
