import yaml


class NoAliasDumper(yaml.SafeDumper):
    def ignore_aliases(self, data):
        return True


def print_yaml(data):
    print(
        to_yaml(data)
    )


def to_yaml(data):
    return yaml.dump(data, Dumper=NoAliasDumper, allow_unicode=True, width=1280, sort_keys=False)


def header_line(text):
    ln = (150 - len(text)) // 2
    return ("=" * ln) + " " + text + " " + ("=" * ln) + "\n"
