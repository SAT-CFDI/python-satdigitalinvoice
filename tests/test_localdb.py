from datetime import datetime

from satdigitalinvoice.localdb import LocalDB, LocalDBSatCFDI, save_data, load_data
from satdigitalinvoice.utils import random_string


def test_localdb():
    db = LocalDBSatCFDI(
        enviar_a_partir=datetime(2020, 1, 1),
        pagar_a_partir={
            "PUE": datetime(2020, 1, 1),
            "PPD": datetime(2020, 1, 1),
        }
    )

    db.folio_set(10)
    assert db.folio() == 10


def test_save_data():
    a = random_string()

    save_data('test_save_data', a)
    assert load_data('test_save_data') == a


