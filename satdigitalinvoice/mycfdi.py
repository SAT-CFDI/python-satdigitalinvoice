import glob
import logging
import os
from collections.abc import Mapping
from datetime import datetime
from typing import MutableMapping
from uuid import UUID

from satcfdi import render
from satcfdi.accounting import complement_invoices_data, SatCFDI
from satcfdi.accounting.models import EstadoComprobante

from .utils import to_uuid

ALL_INVOICES = 'all_invoices'
ALL_RETENCIONES = 'all_retenciones'
logger = logging.getLogger(__name__)


class MyCFDI(SatCFDI):
    local_db = None
    base_dir = None  # type: str

    @SatCFDI.estatus.getter
    def estatus(self) -> EstadoComprobante:
        return self.consulta_estado().get('Estatus', EstadoComprobante.VIGENTE)

    def consulta_estado(self):
        return self.local_db.status_sat(self)

    @SatCFDI.fecha_cancelacion.getter
    def fecha_cancelacion(self) -> datetime | None:
        return self.consulta_estado().get('FechaCancelacion')

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
                    self["TipoDeComprobante"].code,
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
