import logging
from decimal import Decimal
from html import escape as html_escape

import jinja2
import yaml
from jinja2 import Environment
from jinja2.filters import do_mark_safe
from satcfdi import Code
from satcfdi.pacs import sat
from satcfdi.transform.helpers import Xint

# noinspection PyUnresolvedReferences
from satcfdi.transform.catalog import CATALOGS

REGIMEN_FISCAL = CATALOGS['{http://www.sat.gob.mx/sitio_internet/cfd/catalogos}c_RegimenFiscal']

logger = logging.getLogger()
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


class LocalData(dict):
    file_source = None

    def __init__(self):
        with open(self.file_source, "r", encoding="utf-8") as fs:
            super().__init__(yaml.safe_load(fs))


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


class ClientsManager(LocalData):
    file_source = "clients.yaml"

    def __init__(self):
        super().__init__()
        for k in self:
            self[k]["Rfc"] = k
            self[k]["RegimenFiscal"] = Code(self[k]["RegimenFiscal"], REGIMEN_FISCAL.get(self[k]["RegimenFiscal"]))


class FacturasManager(LocalData):
    file_source = "facturas.yaml"


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
