import yaml
from satcfdi import Code


def print_yaml(data):
    print(
        yaml.safe_dump(data, allow_unicode=True, width=1280, sort_keys=False)
    )


def log_email(receptor, notify_invoices, facturas_pendientes):
    print_yaml({
        "Rfc": Code(receptor["Rfc"], receptor["RazonSocial"]),
        "Facturas": [f"{i.name} - {i.uuid}" for i in notify_invoices],
        "PendientesMesesAnteriores": [f"{i.name} - {i.uuid}" for i in facturas_pendientes],
        "Correos": receptor["Email"]
    })


def log_line(text):
    ln = (150 - len(text)) // 2
    print(
        ("=" * ln) + " " + text + " " + ("=" * ln),
    )


def log_item(text):
    ln = (150 - len(text)) // 2
    print(
        ("*" * ln) + " " + text + " " + ("*" * ln),
    )


def cfdi_header(cfdi):
    receptor = Code(cfdi['Receptor']['Rfc'], cfdi['Receptor']['Nombre'])
    return f"{cfdi.name} - {cfdi.uuid} {receptor}"
