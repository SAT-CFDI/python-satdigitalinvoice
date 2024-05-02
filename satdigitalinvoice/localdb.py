import logging
import os
import pickle
from datetime import datetime
from uuid import UUID

import diskcache
from satcfdi.accounting import SatCFDI
from satcfdi.accounting.models import EstadoComprobante
from satcfdi.models import Code
from satcfdi.pacs import sat

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
        return self.get(FOLIO, 1)

    def folio_set(self, value: int):
        self[FOLIO] = value

    def serie(self) -> str:
        return self.get(SERIE, '')

    def serie_set(self, value: str):
        self[SERIE] = value

    def serie_pago(self) -> str:
        return self.get(SERIE_PAGO, '')

    def serie_pago_set(self, value: str):
        self[SERIE_PAGO] = value

    def liquidated2(self, uuid: UUID):
        return self.get((LIQUIDATED, uuid))

    def liquidated_set2(self, uuid: UUID, value: bool):
        self[(LIQUIDATED, uuid)] = value

    def notified2(self, uuid: UUID):
        return self.get((NOTIFIED, uuid))

    def notified_set2(self, uuid: UUID, value: bool):
        self[(NOTIFIED, uuid)] = value

    def status(self, uuid: UUID):
        return self.get((STATUS_SAT, uuid), {})

    def status_merge(self, uuid: str | UUID, estatus: str, es_cancelable: str = None,
                     estatus_cancelacion: str = None, fecha_cancelacion: str = None, fecha_ultima_consulta: str = None):
        if isinstance(uuid, str):
            uuid = UUID(uuid)

        current_value = self.status(uuid)

        value = {
            "Estatus": estatus,
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
                i["Estatus"],
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




