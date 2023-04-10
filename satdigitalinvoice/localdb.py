import logging
import os
import pickle
from enum import Enum
from uuid import UUID

import diskcache
from satcfdi.accounting import SatCFDI
from satcfdi.pacs import sat

from . import DATA_DIRECTORY
from .log_tools import print_yaml
from . import PPD

LIQUIDATED = 0
NOTIFIED = 2
STATUS_SAT = 3
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

    def liquidated(self, uuid: UUID):
        return self.get(
            (LIQUIDATED, uuid), False
        )

    def liquidated_set(self, uuid: UUID, value: bool):
        if value:
            self[(LIQUIDATED, uuid)] = value
        else:
            try:
                del self[(LIQUIDATED, uuid)]
            except KeyError:
                pass

    def notified(self, uuid: UUID):
        return self.get(
            (NOTIFIED, uuid), False
        )

    def notified_set(self, uuid: UUID, value: bool):
        if value:
            self[(NOTIFIED, uuid)] = value
        else:
            try:
                del self[(NOTIFIED, uuid)]
            except KeyError:
                pass

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


class LiquidatedState(Enum):
    NONE = 1
    YES = 2
    NO = 3
    IGNORED = 4
    CANCELLED = 5

    def __str__(self):
        if self.name == "NONE":
            return ""
        if self.name == "IGNORED":
            return "Ignorada"
        if self.name == "YES":
            return "Si"
        if self.name == "NO":
            return "No"
        if self.name == "CANCELLED":
            return "Cancelada"


class LocalDBSatCFDI(LocalDB):
    def __init__(self, enviar_a_partir, pagar_a_partir):
        super().__init__()
        self.enviar_a_partir = enviar_a_partir
        self.pagar_a_partir = pagar_a_partir

    def notified(self, cfdi: SatCFDI):
        if cfdi["Fecha"] >= self.enviar_a_partir:
            return super().notified(cfdi.uuid)
        return True

    def notified_flip(self, cfdi: SatCFDI):
        v = not self.notified(cfdi)
        self.notified_set(cfdi.uuid, v)
        return v

    def liquidated(self, cfdi: SatCFDI):
        if cfdi["Fecha"] >= self.pagar_a_partir[cfdi["MetodoPago"]]:
            return super().liquidated(cfdi.uuid)
        return True

    def liquidated_flip(self, cfdi: SatCFDI):
        v = not self.liquidated(cfdi)
        self.liquidated_set(cfdi.uuid, v)
        return v

    def status_sat(self, cfdi: SatCFDI, update=False):
        if update:
            res = sat_manager.status(cfdi)
            if res["ValidacionEFOS"] == "200":
                self.status_sat_set(cfdi.uuid, res)
            return res
        else:
            return super().status_sat(cfdi.uuid)

    def liquidated_state(self, cfdi: SatCFDI):
        if cfdi.estatus == '0':
            return LiquidatedState.CANCELLED

        if cfdi["TipoDeComprobante"] != "I":
            return LiquidatedState.NONE

        mpago = cfdi["MetodoPago"]
        if mpago == PPD and cfdi.saldo_pendiente == 0:
            return LiquidatedState.YES

        if self.liquidated(cfdi):
            if mpago == PPD:
                return LiquidatedState.IGNORED
            return LiquidatedState.YES

        return LiquidatedState.NO

    def describe(self, cfdi: SatCFDI):
        print_yaml({
            'saldada': self.liquidated(cfdi),
            'enviada': self.notified(cfdi),
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
