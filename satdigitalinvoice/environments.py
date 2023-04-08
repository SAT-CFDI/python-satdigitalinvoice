from html import escape as html_escape

import jinja2
from jinja2 import Environment, Undefined
from jinja2.filters import do_mark_safe
# noinspection PyUnresolvedReferences
from satcfdi.transform.catalog import CATALOGS
from satcfdi.transform.helpers import iterate as h_iterate


class FacturacionEnvironment(Environment):
    @property
    def filter(self):
        def sub(f):
            self.filters[f.__name__] = f
            return f

        return sub

    @property
    def glob(self):
        def sub(f):
            self.globals[f.__name__] = f
            return f

        return sub

    def __init__(self):
        super().__init__(
            loader=jinja2.FileSystemLoader(searchpath=['templates']),
            autoescape=True,
            trim_blocks=True,
            lstrip_blocks=True,
            undefined=jinja2.StrictUndefined,
        )

        @self.glob
        def iterate(v):
            if isinstance(v, Undefined):
                return v
            return h_iterate(v)

        @self.filter
        def bold(k):
            return do_mark_safe(
                tag(html_escape(k), "b")
            )


facturacion_environment = FacturacionEnvironment()


def tag(text, tag):
    return '<' + tag + '>' + text + '</' + tag + '>'
