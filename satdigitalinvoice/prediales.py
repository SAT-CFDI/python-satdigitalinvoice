import os
from itertools import batched

import requests
import yaml
from bs4 import BeautifulSoup
from satcfdi.exceptions import ResponseError

from satdigitalinvoice.log_tools import NoAliasDumper


def format_clavecat(clavecat: str):
    if "-" in clavecat:
        return clavecat
    return "-".join([
        "".join(a) for a in batched(clavecat, 3)]
    )


def request_predial(predial: str):
    predial = format_clavecat(predial)

    r = requests.post(
        url="https://predial.torreon.gob.mx/app/php/get_datos_predio.php",
        data={
            "txt_clavecat": predial
        }
    )
    if r.status_code == 200:
        return _parse_response(r.content)

    raise ResponseError(r)


def process_predial(folder, predial: str):
    res = request_predial(predial)

    if pr := res['predial_recibo']:
        r = requests.get(
            url=pr
        )
        pdf_file = os.path.join(folder, f"{predial}.pdf")
        with open(pdf_file, "wb") as f:
            f.write(r.content)

    if pec := res['predial_estado_cuenta']:
        r = requests.get(
            url=pec
        )
        pdf_file = os.path.join(folder, f"{predial}_adeudo.pdf")
        with open(pdf_file, "wb") as f:
            f.write(r.content)

    yaml_file = os.path.join(folder, f"{predial}.yaml")
    with open(yaml_file, "w", encoding="utf-8") as fs:
        yaml.dump(res, fs, Dumper=NoAliasDumper, allow_unicode=True, width=1280, sort_keys=False)


def _parse_response(data):
    if b'No se ha encontrado coincidencia con su clave catastral' in data:
        return None
    if b'La cuenta se encuentra excenta de pago' in data:
        return None

    res = {}
    html = BeautifulSoup(data, 'html.parser')
    i = html.find_all(name="td")
    for k, v in batched(i, 2):  # iterate in pairs
        res[k.text.strip().rstrip(":")] = v.text.strip()

    i = html.find_all(name="div", attrs={"class": "text-xs font-weight-bold text-primary text-uppercase mb-1"})
    j = html.find_all(name="div", attrs={"class": "encabezado-principal mb-0 font-weight-bold text-gray-800"})

    for k, v in zip(i, j):
        res[k.text.strip()] = v.text.split("$", maxsplit=1)[1]

    i = html.find_all(name="div", attrs={"class": "text-xs font-weight-bold text-primary text-uppercase mb-1 text-center"})
    res['TOTAL'] = i[0].text.split("$", maxsplit=1)[1]

    i = html.find_all(name="a")
    for k in i:
        href = k['href']
        for v in ["predial_estado_cuenta", "predial_recibo"]:
            if v in href:
                res[v] = href
            else:
                res[v] = None

    return res
