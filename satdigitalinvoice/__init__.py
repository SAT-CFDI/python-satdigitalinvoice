import os

SOURCE_DIRECTORY = os.path.dirname(__file__)

with open("credenciales.py", "r", encoding="utf-8") as f:
    loc = {
        '__file__': "credenciales.py"
    }
    exec(f.read(), {}, loc)

SERIE = loc["SERIE"]
LUGAR_EXPEDICION = loc["LUGAR_EXPEDICION"]
REGIMEN_FISCAL = loc["REGIMEN_FISCAL"]
PAC_SERVICE = loc["PAC_SERVICE"]
FIEL_SIGNER = loc["FIEL_SIGNER"]
EMISOR = loc["EMISOR"]
EMAIL_MANAGER = loc["EMAIL_MANAGER"]
FACTURAS_SOURCE = loc["FACTURAS_SOURCE"]
