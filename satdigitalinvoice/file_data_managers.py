import collections.abc
import decimal
import json
import logging
import os
import re
from decimal import Decimal

import jsonschema as jsonschema
import yaml
from satcfdi.models import Code, DatePeriod
from satcfdi.pacs import sat
from satcfdi.transform.helpers import Xint
from yaml import MappingNode, SafeLoader
from yaml.constructor import ConstructorError

from . import SOURCE_DIRECTORY
from .utils import find_best_match, first_duplicate

logger = logging.getLogger(__name__)
sat_manager = sat.SAT()


class DuplicateKeySafeLoader(SafeLoader):
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


decimal_regex = re.compile(r'[-+]?[0-9_]*\.[0-9_]*', re.X)
for ch in '-+0123456789.':
    DuplicateKeySafeLoader.yaml_implicit_resolvers[ch].insert(
        0,
        (
            '!decimal',
            decimal_regex
        )
    )


def load_validator(schema_file):
    with open(os.path.join(SOURCE_DIRECTORY, 'schemas', schema_file), "r", encoding="utf-8") as fs:
        schema = yaml.load(fs, SafeLoader)
        validator = jsonschema.validators.validator_for(schema)
        validator.check_schema(schema)
        return validator(schema)


client_validator = load_validator("cliente.yaml")
factura_validator = load_validator("factura.yaml")


class LocalData(dict):
    file_source = None

    def __new__(cls, *args, **kwargs):
        return super().__new__(cls)

    def __init__(self):
        super().__init__(self._raw())

    def _raw(self):
        with open(self.file_source, "r", encoding="utf-8") as fs:
            return yaml.load(fs, DuplicateKeySafeLoader)


class InitManager(LocalData):
    file_source = "init.yaml"

    def __init__(self):
        try:
            super().__init__()
        except FileNotFoundError:
            pass


class ConfigManager(LocalData):
    file_source = "config.yaml"

    def __init__(self):
        super().__init__()


class ClientsManager(LocalData):
    file_source = "clientes.yaml"

    def __init__(self):
        super().__init__()
        for k, v in self.items():
            if error := jsonschema.exceptions.best_match(client_validator.iter_errors(v)):
                raise error
            self[k]["Rfc"] = k
            self[k]["RegimenFiscal"] = self[k]["RegimenFiscal"]


class FacturasManager(LocalData):
    file_source = "facturas.yaml"

    def __init__(self, dp: DatePeriod | None):
        def loading_function(loader, node):
            cases = loader.construct_mapping(node, deep=True)
            if dp is None:
                return cases
            return find_best_match(
                cases,
                dp
            )[1]

        DuplicateKeySafeLoader.add_constructor("!case", loading_function)
        super().__init__()
        if dup := first_duplicate(json.dumps(x, sort_keys=True, default=str) for x in self["Facturas"]):
            raise Exception("Factura Duplicada: {}".format(dup))

        if dp:
            for v in self["Facturas"]:
                if error := jsonschema.exceptions.best_match(factura_validator.iter_errors(v)):
                    raise error


def decimal_constructor(loader, node):
    value = loader.construct_scalar(node)
    try:
        return Decimal(value)
    except decimal.InvalidOperation:
        raise ConstructorError(None, None,
                               "expected a decimal value, but found %s" % value,
                               node.start_mark)


DuplicateKeySafeLoader.add_constructor("!decimal", decimal_constructor)
DuplicateKeySafeLoader.add_constructor("!read", lambda loader, node: open(loader.construct_scalar(node), 'rb').read())


def represent_decimal(dumper, data):
    return dumper.represent_scalar('tag:yaml.org,2002:str', str(data))


def represent_str(dumper, data):
    return dumper.represent_scalar('tag:yaml.org,2002:str', str(data))


yaml.SafeDumper.add_multi_representer(dict, lambda dumper, data: dumper.represent_dict(data))
yaml.SafeDumper.add_representer(Decimal, represent_decimal)
yaml.SafeDumper.add_representer(Code, represent_str)
yaml.SafeDumper.add_representer(Xint, represent_str)
