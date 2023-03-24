from html import escape as html_escape

import jinja2
from jinja2 import Environment
from jinja2.filters import do_mark_safe
# noinspection PyUnresolvedReferences
from satcfdi.transform.catalog import CATALOGS

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


def tag(text, tag):
    return '<' + tag + '>' + text + '</' + tag + '>'
