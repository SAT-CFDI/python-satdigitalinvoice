import logging
import os
import pickle
from datetime import datetime
from enum import Enum
from uuid import UUID

import diskcache
from satcfdi.models import Code
from satcfdi.accounting import SatCFDI
from satcfdi.accounting.models import EstadoComprobante
from satcfdi.create.cfd.catalogos import MetodoPago, TipoDeComprobante
from satcfdi.pacs import sat

from .utils import estado_to_estatus

LIQUIDATED = 0
NOTIFIED = 2
STATUS_SAT = 3
FOLIO = 5
SERIE = 6
SERIE_PAGO = 7
SOLICITUDES = 'solicitudes'

sat_manager = sat.SAT()

logger = logging.getLogger(__name__)


class LocalDB(diskcache.Cache):
    def __init__(self, base_path: str):
        super().__init__(directory=os.path.join(base_path, 'cache'))
        self.base_path = base_path

    def folio(self) -> int:
        return self.get(FOLIO, 1000)

    def folio_set(self, value: int):
        self[FOLIO] = value

    def serie(self) -> str:
        return self.get(SERIE, 'A')

    def serie_set(self, value: str):
        self[SERIE] = value

    def serie_pago(self) -> str:
        return self.get(SERIE_PAGO, 'P')

    def serie_pago_set(self, value: str):
        self[SERIE_PAGO] = value

    def liquidated(self, uuid: UUID):
        return self.get((LIQUIDATED, uuid))

    def liquidated_set(self, uuid: UUID, value: bool):
        self[(LIQUIDATED, uuid)] = value

    def notified(self, uuid: UUID):
        return self.get((NOTIFIED, uuid))

    def notified_set(self, uuid: UUID, value: bool):
        self[(NOTIFIED, uuid)] = value

    def status(self, uuid: UUID):
        return self.get((STATUS_SAT, uuid), {})

    def status_merge(self, uuid: str | UUID, estatus: str, es_cancelable: str = None,
                     estatus_cancelacion: str = None, fecha_cancelacion: str = None, fecha_ultima_consulta: str = None):
        if isinstance(uuid, str):
            uuid = UUID(uuid)

        current_value = self.status(uuid)

        value = {
            "Estatus": Code(code=estatus, description=EstadoComprobante(estatus).name),
        }
        if es_cancelable:
            value["EsCancelable"] = es_cancelable

        if estatus_cancelacion:
            value["EstatusCancelacion"] = estatus_cancelacion

        if fecha_cancelacion:
            value["FechaCancelacion"] = datetime.fromisoformat(fecha_cancelacion)

        if fecha_ultima_consulta:
            fecha_ultima_consulta = datetime.fromisoformat(fecha_ultima_consulta)
            if current_value and current_value["UltimaConsulta"] > fecha_ultima_consulta:
                return
            value["UltimaConsulta"] = fecha_ultima_consulta
        else:
            value["UltimaConsulta"] = datetime.now().replace(microsecond=0)

        self[(STATUS_SAT, uuid)] = current_value | value

    def status_export(self, uuid: UUID):
        if i := self.status(uuid):
            return [
                uuid,
                i["Estatus"].code,
                i.get("EsCancelable"),
                i.get("EstatusCancelacion"),
                i.get("FechaCancelacion"),
                i.get("UltimaConsulta"),
            ]

    def get_solicitudes(self):
        return self.load_data(SOLICITUDES, {})

    def set_solicitudes(self, solicitudes):
        self.save_data(SOLICITUDES, solicitudes)

    def solicitud_merge(self, solicitud_id, rfc, response, request=None):
        solicitudes = self.get_solicitudes()
        solicitud = solicitudes.setdefault(solicitud_id, {})

        solicitud['rfc'] = rfc
        solicitud['response'] = solicitud.get('response', {}) | response
        if request:
            solicitud['request'] = solicitud.get('request', {}) | request
        solicitud['last_update'] = datetime.now().replace(microsecond=0)

        self.set_solicitudes(solicitudes)
        return solicitud

    def save_data(self, file, data):
        with open(os.path.join(self.base_path, file), 'wb') as f:
            pickle.dump(data, f)

    def load_data(self, file, default=None):
        try:
            with open(os.path.join(self.base_path, file), 'rb') as f:
                return pickle.load(f)
        except FileNotFoundError:
            return default


class StatusState(Enum):
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


class LocalDBSatCFDI(LocalDB):
    def __init__(self, base_path, enviar_a_partir, pagar_a_partir):
        super().__init__(base_path)
        self.enviar_a_partir = enviar_a_partir
        self.pagar_a_partir = pagar_a_partir

    def notified(self, cfdi: SatCFDI):
        v = super().notified(cfdi.uuid)
        if v is None and cfdi["Fecha"] < self.enviar_a_partir:
            return True
        return v

    def notified_flip(self, cfdi: SatCFDI):
        v = not self.notified(cfdi)
        self.notified_set(cfdi.uuid, v)
        return v

    def liquidated(self, cfdi: SatCFDI):
        v = super().liquidated(cfdi.uuid)
        if v is None and cfdi["Fecha"] < self.pagar_a_partir[cfdi["MetodoPago"]]:
            return True
        return v

    def liquidated_flip(self, cfdi: SatCFDI):
        v = not self.liquidated(cfdi)
        self.liquidated_set(cfdi.uuid, v)
        return v

    def status_sat(self, cfdi: SatCFDI, update=False):
        if update:
            res = sat_manager.status(cfdi)
            if res["ValidacionEFOS"] == "200":
                self.status_merge(
                    uuid=cfdi.uuid,
                    estatus=estado_to_estatus(res["Estado"]),
                    es_cancelable=res["EsCancelable"],
                    estatus_cancelacion=res["EstatusCancelacion"]
                )
            else:
                raise ValueError("Error al actualizar estado de %s: %s", cfdi.uuid, res)
            return res
        else:
            return super().status(cfdi.uuid)

    def liquidated_state(self, cfdi: SatCFDI):
        if cfdi.estatus == EstadoComprobante.CANCELADO:
            return StatusState.CANCELLED

        if cfdi["TipoDeComprobante"] != TipoDeComprobante.INGRESO:
            return StatusState.NONE

        mpago = cfdi["MetodoPago"]
        if cfdi['Total'] == 0 or (mpago == MetodoPago.PAGO_EN_PARCIALIDADES_O_DIFERIDO and cfdi.saldo_pendiente == 0):
            return StatusState.PAID

        if self.liquidated(cfdi):
            if mpago == MetodoPago.PAGO_EN_PARCIALIDADES_O_DIFERIDO:
                return StatusState.IGNORED
            return StatusState.PAID

        return StatusState.PENDING
