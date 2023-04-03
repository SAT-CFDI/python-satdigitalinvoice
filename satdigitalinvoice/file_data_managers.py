import logging
import os
from decimal import Decimal
from html import escape as html_escape
import collections.abc
import jinja2
import yaml
from jinja2 import Environment
from jinja2.filters import do_mark_safe
import jsonschema as jsonschema
from jsonschema.validators import Draft202012Validator
from satcfdi import Code
from satcfdi.pacs import sat
# noinspection PyUnresolvedReferences
from satcfdi.transform.catalog import CATALOGS
from satcfdi.transform.helpers import Xint
from satdigitalinvoice import SOURCE_DIRECTORY
from yaml import MappingNode, SafeLoader
from yaml.constructor import ConstructorError

REGIMEN_FISCAL = CATALOGS['{http://www.sat.gob.mx/sitio_internet/cfd/catalogos}c_RegimenFiscal']

logger = logging.getLogger(__name__)
sat_manager = sat.SAT()

environment_default = Environment(
    loader=jinja2.FileSystemLoader(searchpath=['templates']),
    autoescape=False,
    trim_blocks=True,
    lstrip_blocks=True,
    undefined=jinja2.StrictUndefined,
)


def finalize_html(val):
    return do_mark_safe(
        tag(html_escape(val), "b")
    )


environment_bold_escaped = Environment(
    loader=jinja2.FileSystemLoader(searchpath=['templates']),
    autoescape=True,
    trim_blocks=True,
    lstrip_blocks=True,
    undefined=jinja2.StrictUndefined,
    finalize=finalize_html
)


class DuplicateKeySafeLoader(yaml.SafeLoader):
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


class LocalData(dict):
    file_source = None

    def __new__(cls, *args, **kwargs):
        return super().__new__(cls)

    def __init__(self):
        super().__init__(self._raw())

    def reload(self):
        super().update(self._raw())

    def _raw(self):
        with open(self.file_source, "r", encoding="utf-8") as fs:
            return yaml.load(fs, DuplicateKeySafeLoader)


class ConfigManager(LocalData):
    file_source = "config.yaml"

    def folio(self):
        return self["folio"]

    def serie(self):
        return self["serie"]

    def inc_folio(self):
        self["folio"] += 1
        self.save()

    def save(self):
        with open(self.file_source, "w", encoding="utf-8") as fs:
            yaml.dump_all([self], fs, Dumper=yaml.SafeDumper, encoding="utf-8", allow_unicode=True, sort_keys=False)


def load_validator(schema_file):
    with open(os.path.join(SOURCE_DIRECTORY, 'schemas', schema_file), "r", encoding="utf-8") as fs:
        schema = yaml.load(fs, SafeLoader)
        validator = jsonschema.validators.validator_for(schema)
        validator.check_schema(schema)
        return validator(schema)


client_validator = load_validator("client.yaml")
factura_validator = load_validator("factura.yaml")


class ClientsManager(LocalData):
    file_source = "clients.yaml"

    def __init__(self):
        super().__init__()

        for k, v in self.items():
            if error := jsonschema.exceptions.best_match(client_validator.iter_errors(v)):
                raise error
            self[k]["Rfc"] = k
            self[k]["RegimenFiscal"] = Code(self[k]["RegimenFiscal"], REGIMEN_FISCAL.get(self[k]["RegimenFiscal"]))


class FacturasManager(LocalData):
    file_source = "facturas.yaml"

    def __init__(self):
        super().__init__()

        for v in self["Facturas"]:
            if error := jsonschema.exceptions.best_match(factura_validator.iter_errors(v)):
                raise error


def tag(text, tag):
    return '<' + tag + '>' + text + '</' + tag + '>'


yaml.SafeDumper.add_multi_representer(dict, lambda dumper, data: dumper.represent_dict(data))
yaml.SafeLoader.add_constructor("!decimal", lambda loader, node: Decimal(loader.construct_scalar(node)))


def represent_decimal(dumper, data):
    return dumper.represent_scalar('tag:yaml.org,2002:str', str(data))


def represent_str(dumper, data):
    return dumper.represent_scalar('tag:yaml.org,2002:str', str(data))


yaml.SafeDumper.add_representer(Decimal, represent_decimal)
yaml.SafeDumper.add_representer(Code, represent_str)
yaml.SafeDumper.add_representer(Xint, represent_str)
