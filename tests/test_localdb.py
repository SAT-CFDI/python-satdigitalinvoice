from datetime import datetime

from satdigitalinvoice.localdb import LocalDB, LocalDBSatCFDI
from satdigitalinvoice.utils import random_string


def test_localdb():
    db = LocalDBSatCFDI(
        base_path=".data",
        enviar_a_partir=datetime(2020, 1, 1),
        pagar_a_partir={
            "PUE": datetime(2020, 1, 1),
            "PPD": datetime(2020, 1, 1),
        }
    )

    db.folio_set(10)
    assert db.folio() == 10

    a = random_string()

    db.save_data('test_save_data', a)
    assert db.load_data('test_save_data') == a


