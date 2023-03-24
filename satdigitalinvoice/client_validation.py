import logging
import re
import warnings

# noinspection PyUnresolvedReferences
from bs4.builder import XMLParsedAsHTMLWarning
from satcfdi import csf, RFC, RFCType
from satcfdi.pacs.sat import SAT

sat_service = SAT()
logger = logging.getLogger(__name__)
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

EMAIL_REGEX = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,7}\b'


def validar_client(client):
    rfc = client['Rfc']
    try:
        rfc = RFC(rfc)
        if not rfc.is_valid():
            raise ValueError("RFC Not Valid Regex")
    except ValueError as ex:
        print(f"{rfc}: {ex}")
        return

    for email in client["Email"]:
        match = re.fullmatch(EMAIL_REGEX, email)
        if not match:
            print(f"{rfc}: Correo '{email}' is invalid")

    if id_cif := client["IdCIF"]:
        try:
            res = csf.retrieve(rfc, id_cif=id_cif)
        except ValueError as ex:
            print(f"{rfc}: idCIF '{id_cif}' is invalid")
            return

        if rfc.type == RFCType.MORAL:
            if client['RazonSocial'] != res['Denominación o Razón Social']:
                print(f"{rfc}: RazonSocial '{client['RazonSocial']}' is invalid, expected '{res['Denominación o Razón Social']}'")
        elif rfc.type == RFCType.FISICA:
            if client['RazonSocial'] != f"{res['Nombre']} {res['Apellido Paterno']} {res['Apellido Materno']}":
                print(f"{rfc}: RazonSocial '{client['RazonSocial']}' is invalid, expected '{res['Nombre']} {res['Apellido Paterno']} {res['Apellido Materno']}'")

        if client['CodigoPostal'] != res['CP']:
            print(f"{rfc}: CodigoPostal '{client['CodigoPostal']}' is invalid, expected '{res['CP']}'")

        if client['RegimenFiscal'] not in (r['RegimenFiscal'] for r in res['Regimenes']):
            print(
                f"{rfc}: RegimenFiscal '{client['RegimenFiscal']}' is invalid, "
                f"expected '{(r['RegimenFiscal'].code for r in res['Regimenes'])}'"
            )

        if res['Situación del contribuyente'] not in ['ACTIVO', 'REACTIVADO']:
            print(f"{rfc}: Is not ACTIVO '{res['Situación del contribuyente']}'")

        taxpayer_status = sat_service.list_69b(rfc)
        if taxpayer_status:
            print(f"{rfc}: has status '{taxpayer_status}'")


def clientes_generar_txt(clients):
    with open("clientes.txt", 'w') as f:
        for i, (cliente_rfc, cliente_data) in enumerate(clients.items(), start=1):
            f.write(f"{i}|{cliente_rfc}|{cliente_data['RazonSocial']}|{cliente_data['CodigoPostal']}")
            f.write("\n")
