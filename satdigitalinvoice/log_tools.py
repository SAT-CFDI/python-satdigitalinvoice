import logging

import yaml
from satcfdi import Code


class LogAdapter(logging.LoggerAdapter):
    def info_yaml(self, data):
        self.info(
            yaml.safe_dump(data, allow_unicode=True, width=1280, sort_keys=False)
        )


logger = LogAdapter(logging.getLogger())


class LogHandler(logging.StreamHandler):
    def __init__(self, console):
        super().__init__()
        self.buffer = ""
        self.console = console

    def emit(self, record):
        msg = self.format(record)
        self.buffer += msg + '\n'
        self.console.update(value=self.buffer)

    def clear(self):
        self.buffer = ""
        self.console.update(value="")


def log_email(receptor, notify_invoices, facturas_pendientes):
    logger.info_yaml({
        "Rfc": Code(receptor["Rfc"], receptor["RazonSocial"]),
        "Facturas": [f"{i.name} - {i.uuid}" for i in notify_invoices],
        "Pendientes Meses Anteriores": [f"{i.name} - {i.uuid}" for i in facturas_pendientes],
        "Correos": receptor["Email"]
    })


def log_line(text, exc_info=False):
    ln = (150 - len(text)) // 2
    logger.info(
        ("=" * ln) + " " + text + " " + ("=" * ln),
        exc_info=exc_info
    )


def log_item(text, exc_info=False):
    ln = (150 - len(text)) // 2
    logger.info(
        ("*" * ln) + " " + text + " " + ("*" * ln),
        exc_info=exc_info
    )


def cfdi_header(cfdi):
    receptor = Code(cfdi['Receptor']['Rfc'], cfdi['Receptor']['Nombre'])
    return f"{cfdi.name} - {cfdi.uuid} {receptor}"
