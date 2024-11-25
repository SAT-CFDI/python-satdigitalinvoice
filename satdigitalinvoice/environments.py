from datetime import date
from html import escape as html_escape

import jinja2
from jinja2 import Environment, Undefined
from jinja2.filters import do_mark_safe
from satcfdi import render as cfdi_render
from satcfdi.transform.helpers import iterate as h_iterate
import satdigitalinvoice.formatting_functions.common as common

from . import TEMPLATES_DIRECTORY


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
            loader=jinja2.FileSystemLoader(searchpath=[TEMPLATES_DIRECTORY]),
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

        @self.glob
        def today():
            return date.today()

        @self.filter
        def bold(k):
            return do_mark_safe(
                tag(html_escape(str(k)), "b")
            )

        @self.filter
        def moneda_nacional(k):
            return common.pesos(k)

        @self.filter
        def numero(k):
            return common.numero(k)

        @self.filter
        def porcentaje(k):
            return common.porcentaje(k)

        @self.filter
        def fecha(k):
            return common.fecha(k)

        @self.filter
        def delta_tiempo(k):
            return common.delta_tiempo(k)

        @self.glob
        def html_str(cdfi):
            return cfdi_render.html_str(cdfi)


def tag(text, tag):
    return '<' + tag + '>' + text + '</' + tag + '>'


facturacion_environment = FacturacionEnvironment()
