import collections.abc
import json
import logging
import os
from datetime import date
from decimal import Decimal

import jsonschema as jsonschema
import yaml
from satcfdi import Code
from satcfdi.pacs import sat
# noinspection PyUnresolvedReferences
from satcfdi.transform.catalog import CATALOGS
from satcfdi.transform.helpers import Xint
from yaml import MappingNode, SafeLoader
from yaml.constructor import ConstructorError

from . import SOURCE_DIRECTORY
from .utils import find_best_match, first_duplicate

REGIMEN_FISCAL = CATALOGS['{http://www.sat.gob.mx/sitio_internet/cfd/catalogos}c_RegimenFiscal']

logger = logging.getLogger(__name__)
sat_manager = sat.SAT()


class DuplicateKeySafeLoader(yaml.CSafeLoader):
    def construct_mapping(self, node, deep=False):
        if isinstance(node, MappingNode):
            self.flatten_mapping(node)

        if not isinstance(node, MappingNode):
            raise ConstructorError(None, None,
                                   "expected a mapping node, but found %s" % node.id,
                                   node.start_mark)
        mapping = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, collections.abc.Hashable):
                raise ConstructorError("while constructing a mapping", node.start_mark,
                                       "found unhashable key", key_node.start_mark)
            value = self.construct_object(value_node, deep=deep)
            if key in mapping:
                raise ConstructorError("while constructing a mapping", node.start_mark,
                                       "found duplicate key (%s)" % key, key_node.start_mark)
            mapping[key] = value
        return mapping


def load_validator(schema_file):
    with open(os.path.join(SOURCE_DIRECTORY, 'schemas', schema_file), "r", encoding="utf-8") as fs:
        schema = yaml.load(fs, SafeLoader)
        validator = jsonschema.validators.validator_for(schema)
        validator.check_schema(schema)
        return validator(schema)


client_validator = load_validator("cliente.yaml")
factura_validator = load_validator("factura.yaml")
config_validator = load_validator("config.yaml")


class LocalData(dict):
    file_source = None

    def __new__(cls, *args, **kwargs):
        return super().__new__(cls)

    def __init__(self):
        super().__init__(self._raw())

    def _raw(self):
        with open(self.file_source, "r", encoding="utf-8") as fs:
            return yaml.load(fs, DuplicateKeySafeLoader)


class ConfigManager(LocalData):
    file_source = "config.yaml"

    def __init__(self):
        super().__init__()
        if error := jsonschema.exceptions.best_match(config_validator.iter_errors(self)):
            raise error


class ClientsManager(LocalData):
    file_source = "clientes.yaml"

    def __init__(self):
        super().__init__()
        for k, v in self.items():
            if error := jsonschema.exceptions.best_match(client_validator.iter_errors(v)):
                raise error
            self[k]["Rfc"] = k
            self[k]["RegimenFiscal"] = Code(self[k]["RegimenFiscal"], REGIMEN_FISCAL.get(self[k]["RegimenFiscal"]))


class FacturasManager(LocalData):
    file_source = "facturas.yaml"

    def __init__(self, emission_date: date | None):
        def loading_function(loader, node):
            cases = loader.construct_mapping(node, deep=True)
            if emission_date is None:
                return cases
            return find_best_match(
                cases,
                emission_date
            )[1]

        DuplicateKeySafeLoader.add_constructor("!case", loading_function)
        super().__init__()
        if dup := first_duplicate(json.dumps(x, sort_keys=True, default=str) for x in self["Facturas"]):
            raise ValueError("Factura Duplicada: {}".format(dup))

        if emission_date:
            for v in self["Facturas"]:
                if error := jsonschema.exceptions.best_match(factura_validator.iter_errors(v)):
                    raise error


DuplicateKeySafeLoader.add_constructor("!decimal", lambda loader, node: Decimal(loader.construct_scalar(node)))
DuplicateKeySafeLoader.add_constructor("!read", lambda loader, node: open(loader.construct_scalar(node), 'rb').read())


def represent_decimal(dumper, data):
    return dumper.represent_scalar('tag:yaml.org,2002:str', str(data))


def represent_str(dumper, data):
    return dumper.represent_scalar('tag:yaml.org,2002:str', str(data))


yaml.SafeDumper.add_multi_representer(dict, lambda dumper, data: dumper.represent_dict(data))
yaml.SafeDumper.add_representer(Decimal, represent_decimal)
yaml.SafeDumper.add_representer(Code, represent_str)
yaml.SafeDumper.add_representer(Xint, represent_str)
