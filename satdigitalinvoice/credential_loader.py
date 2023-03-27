

with open("credenciales.py", "r", encoding="utf-8") as f:
    loc = {
        '__file__': "credenciales.py"
    }
    exec(f.read(), {}, loc)

PAC_SERVICE = loc["PAC_SERVICE"]
FIEL_SIGNER = loc["FIEL_SIGNER"]
CSD_SIGNER = loc["CSD_SIGNER"]
EMAIL_MANAGER = loc["EMAIL_MANAGER"]
CORREO_FIRMA = loc["CORREO_FIRMA"]

FACTURAS_SOURCE = loc["FACTURAS_SOURCE"]
AJUSTES_DIR = loc.get("AJUSTES_DIR", "ajustes")

