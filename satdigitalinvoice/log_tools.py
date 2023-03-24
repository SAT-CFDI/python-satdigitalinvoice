import yaml
from satcfdi import Code


class NoAliasDumper(yaml.SafeDumper):
    def ignore_aliases(self, data):
        return True


def print_yaml(data):
    print(
        yaml.dump(data, Dumper=NoAliasDumper, allow_unicode=True, width=1280, sort_keys=False)
    )


def log_email(receptor, notify_invoices, facturas_pendientes):
    print_yaml({
        "rfc": Code(receptor["Rfc"], receptor["RazonSocial"]),
        "facturas": [f"{i.name} - {i.uuid}" for i in notify_invoices],
        "pendientes_meses_anteriores": [f"{i.name} - {i.uuid}" for i in facturas_pendientes],
        "correos": receptor["Email"]
    })


def header_line(text):
    ln = (151 - len(text)) // 2
    return ("=" * ln) + " " + text + " " + ("=" * ln)


def log_line(text):
    print(
        header_line(text)
    )


def log_item(text):
    ln = (151 - len(text)) // 2
    print(
        ("*" * ln) + " " + text + " " + ("*" * ln),
    )


def cfdi_header(cfdi):
    receptor = Code(cfdi['Receptor']['Rfc'], cfdi['Receptor']['Nombre'])
    return f"{cfdi.name} - {cfdi.uuid} {receptor}"
