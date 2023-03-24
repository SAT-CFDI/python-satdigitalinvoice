import pytest
from yaml.constructor import ConstructorError

from satdigitalinvoice.file_data_managers import LocalData

from satdigitalinvoice.layout import make_layout
from satdigitalinvoice.utils import random_string


def test_layout_unique_keys():
    try:
        import _tkinter
    except ImportError:
        return

    layout = make_layout(has_fiel=True)

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
    class MyConfigManager(LocalData):
        file_source = "duplicated_config.yaml"

    # expect exception thrown
    with pytest.raises(ConstructorError) as e:
        MyConfigManager()
    assert e.value.problem == 'found duplicate key (email_notificada_hasta)'


def test_random_string():
    a = random_string()
    assert len(a) == 43
