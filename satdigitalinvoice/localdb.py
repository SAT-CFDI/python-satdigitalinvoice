import logging
import os
import pickle
from uuid import UUID

import diskcache
from satcfdi.accounting import SatCFDI
from satcfdi.pacs import sat

from . import DATA_DIRECTORY
from .log_tools import print_yaml

EMAIL_NOTIFICADA = 2
STATUS_SAT = 3
PENDIENTE = 4
FOLIO = 5

sat_manager = sat.SAT()

logger = logging.getLogger(__name__)


class LocalDB(diskcache.Cache):
    def __init__(self):
        super().__init__(directory=os.path.join(DATA_DIRECTORY, 'cache'))

    def folio(self):
        return self.get(FOLIO, 1)

    def folio_set(self, value: int):
        self[FOLIO] = value

    def saldar(self, uuid: UUID):
        return self.get(
            (PENDIENTE, uuid), True
        )

    def saldar_set(self, uuid: UUID, value: bool):
        if value:
            try:
                del self[(PENDIENTE, uuid)]
            except KeyError:
                pass
        else:
            self[(PENDIENTE, uuid)] = value

    def notificar(self, uuid: UUID):
        return self.get(
            (EMAIL_NOTIFICADA, uuid), True
        )

    def notificar_set(self, uuid: UUID, value: bool):
        if value:
            try:
                del self[(EMAIL_NOTIFICADA, uuid)]
            except KeyError:
                pass
        else:
            self[(EMAIL_NOTIFICADA, uuid)] = value

    def status_sat(self, uuid: UUID):
        return self.get(
            (STATUS_SAT, uuid), {}
        )

    def status_sat_set(self, uuid: UUID, value: dict):
        if value:
            self[(STATUS_SAT, uuid)] = value
        else:
            try:
                del self[(STATUS_SAT, uuid)]
            except KeyError:
                pass


class LocalDBSatCFDI(LocalDB):
    def __init__(self, enviar_a_partir, saldar_a_partir):
        super().__init__()
        self.enviar_a_partir = enviar_a_partir
        self.saldar_a_partir = saldar_a_partir

    def notificar(self, cfdi: SatCFDI):
        if cfdi["Fecha"] >= self.enviar_a_partir:
            return super().notificar(cfdi.uuid)
        return False

    def notificar_flip(self, cfdi: SatCFDI):
        v = not self.notificar(cfdi)
        self.notificar_set(cfdi.uuid, v)
        return v

    def saldar(self, cfdi: SatCFDI):
        if cfdi["TipoDeComprobante"] != "I":
            return None
        if cfdi["MetodoPago"] == "PPD" and cfdi.saldo_pendiente == 0:
            return 0
        if cfdi["Fecha"] >= self.saldar_a_partir[cfdi["MetodoPago"]]:
            if super().saldar(cfdi.uuid):
                if cfdi["MetodoPago"] == "PPD":
                    return cfdi.saldo_pendiente
                else:
                    return cfdi["Total"]
        return 0

    def saldar_flip(self, cfdi: SatCFDI):
        v = not self.saldar(cfdi)
        self.saldar_set(cfdi.uuid, v)
        return v

    def status_sat(self, cfdi: SatCFDI, update=False):
        if update:
            res = sat_manager.status(cfdi)
            if res["ValidacionEFOS"] == "200":
                self.status_sat_set(cfdi.uuid, res)
            return res
        else:
            return super().status_sat(cfdi.uuid)

    def describe(self, cfdi: SatCFDI):
        print_yaml({
            'saldar': self.saldar(cfdi),
            'enviar': self.notificar(cfdi),
            'status_sat': self.status_sat(cfdi)
        })


def save_data(file, data):
    with open(os.path.join(DATA_DIRECTORY, file), 'wb') as f:
        pickle.dump(data, f)


def load_data(file, default=None):
    try:
        with open(os.path.join(DATA_DIRECTORY, file), 'rb') as f:
            return pickle.load(f)
    except FileNotFoundError:
        return default
