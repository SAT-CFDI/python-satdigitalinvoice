import logging
import re
import warnings

from bs4.builder import XMLParsedAsHTMLWarning
from satcfdi.models import RFC, RFCType
from satcfdi import csf
from satcfdi.pacs.sat import SAT

sat_service = SAT()
logger = logging.getLogger(__name__)
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

EMAIL_REGEX = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,7}\b'


def validar_client(client):
    errors = []

    rfc = client['Rfc']

    def error(msg):
        errors.append(f"{rfc}: {msg}")

    try:
        rfc = RFC(rfc)

        for email in client["Email"]:
            if not re.fullmatch(EMAIL_REGEX, email):
                error(f"Correo '{email}' is invalid")

        res = csf.retrieve(rfc, id_cif=client["IdCIF"])

        if rfc.type == RFCType.FISICA:
            razon_social = f"{res['Nombre']} {res['Apellido Paterno']} {res['Apellido Materno']}"
        elif 'Denominación o Razón Social' in res:
            razon_social = res['Denominación o Razón Social']
        else:
            error(f"Does not have 'Denominación o Razón Social'")

        if client['RazonSocial'] != razon_social:
            error(f"RazonSocial '{client['RazonSocial']}' is invalid, expected '{razon_social}'")

        if client['CodigoPostal'] != res['CP']:
            error(f"CodigoPostal '{client['CodigoPostal']}' is invalid, expected '{res['CP']}'")

        for r in res['Regimenes']:
            if r['RegimenFiscal'].code == None:
                error(f"RegimenFiscal '{r['RegimenFiscal']}' is invalid")

        if client['RegimenFiscal'] not in (r['RegimenFiscal'] for r in res['Regimenes']):
            regimen = ', '.join(r['RegimenFiscal'].code or "" for r in res['Regimenes'])
            error(
                f"RegimenFiscal '{client['RegimenFiscal']}' is invalid, "
                f"expected one of '{regimen}'"
            )

        if res['Situación del contribuyente'] not in ('ACTIVO', 'REACTIVADO'):
            error(f"Is not ACTIVO '{res['Situación del contribuyente']}'")

        taxpayer_status = sat_service.list_69b(rfc)
        if taxpayer_status:
            error(f"has status '{taxpayer_status}'")
    except Exception as ex:
        error(ex)

    return errors


def clientes_generar_txt(filename, clients):
    with open(filename, 'w', encoding='utf-8') as f:
        for i, (cliente_rfc, cliente_data) in enumerate(clients.items(), start=1):
            f.write(f"{i}|{cliente_rfc}|{cliente_data['RazonSocial']}|{cliente_data['CodigoPostal']}\n")
