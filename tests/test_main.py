from datetime import date, datetime

import pytest
from satcfdi.models import DatePeriod

from satdigitalinvoice.facturacion import FacturacionGUI
from yaml.constructor import ConstructorError

from satdigitalinvoice.file_data_managers import LocalData, ConfigManager, FacturasManager

from satdigitalinvoice.layout import make_layout
from satdigitalinvoice.utils import random_string, add_month


def test_layout_unique_keys():
    try:
        import _tkinter
    except ImportError:
        return

    layout = make_layout(emisores=["CACX7605101P8"], local_db=None)

    def elements(layout):
        for e in layout:
            if isinstance(e, list):
                yield from elements(e)
            else:
                yield e

    unique_keys = set()
    for e in elements(layout):
        if e.Key:
            if e.Key in unique_keys:
                raise Exception(f"Key {e.Key} is not unique")
            else:
                unique_keys.add(e.Key)


def test_duplicated_yaml_file():
    class MyConfigManager(ConfigManager):
        file_source = "config_duplicated.yaml"

    # expect exception thrown
    with pytest.raises(ConstructorError) as e:
        MyConfigManager()
    assert e.value.problem == 'found duplicate key (email_notificada_hasta)'


def test_random_string():
    a = random_string()
    assert len(a) == 32


def test_duplicated_facturas():
    class MyFacturasManager(FacturasManager):
        file_source = "facturas_duplicated.yaml"

    # expect exception thrown
    with pytest.raises(Exception) as e:
        MyFacturasManager(DatePeriod(2021, 1, 1))
    assert str(e.value)[0:20] == 'Factura Duplicada: {'


def test_increase_month():
    d = DatePeriod(2021, 1)
    d = add_month(d, 1)
    assert d.year == 2021 and d.month == 2


# def test_app_setup():
#     config = ConfigManager()
#     a = FacturacionGUI(
#         config
#     )
