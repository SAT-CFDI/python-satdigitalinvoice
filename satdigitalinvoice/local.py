import logging
import os
import pickle
from uuid import UUID

import diskcache
from satcfdi.accounting import SatCFDI
from satcfdi.pacs import sat
from .log_tools import print_yaml

PUE_PAGADA = 0
PPD_IGNORAR = 1
EMAIL_NOTIFICADA = 2
STATUS_SAT = 3

sat_manager = sat.SAT()

logger = logging.getLogger(__name__)
DATA_DIR = '.data'


class LocalDB:
    def __init__(self):
        self.local_storage = diskcache.Cache(os.path.join(DATA_DIR, 'cache'))

    def pue_pagada(self, uuid: UUID):
        return self.local_storage.get(
            (PUE_PAGADA, uuid), False
        )

    def pue_pagada_set(self, uuid: UUID, value: bool):
        if value:
            self.local_storage[(PUE_PAGADA, uuid)] = value
        else:
            try:
                del self.local_storage[(PUE_PAGADA, uuid)]
            except KeyError:
                pass

    def ppd_ignorar(self, uuid: UUID):
        return self.local_storage.get(
            (PPD_IGNORAR, uuid), False
        )

    def ppd_ignorar_set(self, uuid: UUID, value: bool):
        if value:
            self.local_storage[(PPD_IGNORAR, uuid)] = value
        else:
            try:
                del self.local_storage[(PPD_IGNORAR, uuid)]
            except KeyError:
                pass

    def email_notificada(self, uuid: UUID):
        return self.local_storage.get(
            (EMAIL_NOTIFICADA, uuid), False
        )

    def email_notificada_set(self, uuid: UUID, value: bool):
        if value:
            self.local_storage[(EMAIL_NOTIFICADA, uuid)] = value
        else:
            try:
                del self.local_storage[(EMAIL_NOTIFICADA, uuid)]
            except KeyError:
                pass

    def status_sat(self, uuid: UUID):
        return self.local_storage.get(
            (STATUS_SAT, uuid), {}
        )

    def status_sat_set(self, uuid: UUID, value: dict):
        if value:
            self.local_storage[(STATUS_SAT, uuid)] = value
        else:
            try:
                del self.local_storage[(STATUS_SAT, uuid)]
            except KeyError:
                pass


class LocalDBSatCFDI(LocalDB):
    def __init__(self, config):
        super().__init__()
        self.config = config

    def email_notificada(self, cfdi: SatCFDI):
        if cfdi["Fecha"] <= self.config['email_notificada_hasta']:
            return True
        return super().email_notificada(cfdi.uuid)

    def pue_pagada(self, cfdi: SatCFDI):
        if cfdi["Fecha"] <= self.config['pue_pagada_hasta']:
            return True
        return super().pue_pagada(cfdi.uuid)

    def ppd_ignorar(self, cfdi: SatCFDI):
        if cfdi["Fecha"] <= self.config['ppd_ignorar_hasta']:
            return True
        return super().ppd_ignorar(cfdi.uuid)

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
            'pue_pagada': self.pue_pagada(cfdi),
            'ppd_ignorar': self.ppd_ignorar(cfdi),
            'email_notificada': self.email_notificada(cfdi),
            'status_sat': self.status_sat(cfdi)
        })


def save_data(file, data):
    with open(os.path.join(DATA_DIR, file), 'wb') as f:
        pickle.dump(data, f)


def load_data(file, default=None):
    try:
        with open(os.path.join(DATA_DIR, file), 'rb') as f:
            return pickle.load(f)
    except FileNotFoundError:
        return default
