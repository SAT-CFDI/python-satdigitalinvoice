import logging
import os
from decimal import Decimal
from html import escape as html_escape

import jinja2
import yaml
from jinja2 import Environment
from jinja2.filters import do_mark_safe
from markdown2 import markdown
from satcfdi import Code
from satcfdi.pacs import sat
from satcfdi.transform.helpers import Xint
from weasyprint import HTML, CSS

from . import SOURCE_DIRECTORY

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

    def save(self):
        with open(self.file_source, "w", encoding="utf-8") as fs:
            yaml.dump_all([self], fs, Dumper=yaml.SafeDumper, encoding="utf-8", allow_unicode=True, sort_keys=False)


class PaymentsManager(LocalData):
    file_source = "pagos.yaml"


class NotificationsManager(LocalData):
    file_source = "notifications.yaml"

    def folio(self, serie):
        return self["Series"][serie]

    def set_folio(self, serie, folio):
        self["Series"][serie] = max(self["Series"][serie], folio + 1)
        self.save()


class ClientsManager(LocalData):
    file_source = "clients.yaml"


class FacturasManager(dict):
    def __init__(self, values, file_source="facturas.yaml"):
        with open(file_source, "r", encoding="utf-8") as fs:
            template = environment_default.from_string(fs.read())
            rendered_template = template.render(
                values
            )
            super().__init__(yaml.safe_load(rendered_template))


class CanceladosManager(LocalData):
    file_source = "cancelados.yaml"

    def get_state(self, cfdi, only_cache=True):
        uuid = str(cfdi.uuid)

        res = self.get(uuid)
        if res:
            return res

        if only_cache:
            return {}

        try:
            res = sat_manager.status(cfdi)
            if res["ValidacionEFOS"] != "200":
                logger.error("CFDI No Encontrado '%s' %s", uuid, res)
            else:
                logger.info("CFDI Encontrado '%s' %s", uuid, res)

            self[uuid] = res
            return res
        except Exception:
            logger.exception("Failed to get Status for Invoice: ", uuid)
            return {}


def tag(text, tag):
    return '<' + tag + '>' + text + '</' + tag + '>'


def generate_pdf_template(template_name, fields):
    increment_template = environment_bold_escaped.get_template(template_name)
    md5_document = increment_template.render(
        fields
    )
    html = markdown(md5_document)
    pdf = HTML(string=html).write_pdf(
        target=None,
        stylesheets=[
            os.path.join(SOURCE_DIRECTORY, "markdown_styles", "markdown6.css"),
            CSS(
                string='@page { width: Letter; margin: 1.6cm 1.6cm 1.6cm 1.6cm; }'
            )
        ]
    )

    return pdf


yaml.SafeDumper.add_multi_representer(dict, lambda dumper, data: dumper.represent_dict(data))
yaml.SafeLoader.add_constructor("!decimal", lambda loader, node: Decimal(loader.construct_scalar(node)))


def represent_decimal(dumper, data):
    return dumper.represent_scalar('tag:yaml.org,2002:str', str(data))


def represent_str(dumper, data):
    return dumper.represent_scalar('tag:yaml.org,2002:str', str(data))


yaml.SafeDumper.add_representer(Decimal, represent_decimal)
yaml.SafeDumper.add_representer(Code, represent_str)
yaml.SafeDumper.add_representer(Xint, represent_str)
