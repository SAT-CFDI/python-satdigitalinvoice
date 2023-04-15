import yaml
from satcfdi import Code


class NoAliasDumper(yaml.SafeDumper):
    def ignore_aliases(self, data):
        return True


def print_yaml(data):
    print(
        yaml.dump(data, Dumper=NoAliasDumper, allow_unicode=True, width=1280, sort_keys=False)
    )


def header_line(text):
    ln = (150 - len(text)) // 2
    return ("=" * ln) + " " + text + " " + ("=" * ln)


def cfdi_header(cfdi):
    receptor = Code(cfdi['Receptor']['Rfc'], cfdi['Receptor']['Nombre'])
    return f"{cfdi.name} - {cfdi.uuid} {receptor}"
