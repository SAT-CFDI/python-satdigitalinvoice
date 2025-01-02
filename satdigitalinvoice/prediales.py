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
        url="https://pagoenlinea-api.torreon.gob.mx/api/predial/consultar",
        data={
            "cveCatastral": predial
        }
    )
    if r.status_code == 200:
        return r.json()

    raise ResponseError(r)


def process_predial(folder, predial: str):
    res = request_predial(predial)

    yaml_file = os.path.join(folder, f"{predial}.yaml")
    with open(yaml_file, "w", encoding="utf-8") as fs:
        yaml.dump(res, fs, Dumper=NoAliasDumper, allow_unicode=True, width=1280, sort_keys=False)

    edo_cta = res['datosEdoCta']
    url_adeudo = f"https://app.torreon.gob.mx/httpmethods/predial_estado_cuenta?adeudo_id={edo_cta['K_ADEUDO']}"
    r = requests.get(
        url=url_adeudo
    )
    pdf_file = os.path.join(folder, f"{predial}.pdf")
    with open(pdf_file, "wb") as f:
        f.write(r.content)
