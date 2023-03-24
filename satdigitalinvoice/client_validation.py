import logging
import os
import re
import warnings

# noinspection PyUnresolvedReferences
from bs4.builder import XMLParsedAsHTMLWarning
from satcfdi import csf, RFC, RFCType
from satcfdi.pacs.sat import SAT

sat_service = SAT()
logger = logging.getLogger()
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

EMAIL_REGEX = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,7}\b'


def validar_client(rfc, details):
    try:
        rfc = RFC(rfc)
        if not rfc.is_valid():
            raise ValueError("RFC Not Valid Regex")
    except ValueError as ex:
        logger.error(f"{rfc}: {ex}")
        return

    for email in details["Email"]:
        match = re.fullmatch(EMAIL_REGEX, email)
        if not match:
            logger.error(f"{rfc}: Correo '{email}' is invalid")

    if id_cif := details["IdCIF"]:
        try:
            res = csf.retrieve(rfc, id_cif=id_cif)
        except ValueError as ex:
            logger.error(f"{rfc}: idCIF '{id_cif}' is invalid")
            return

        if rfc.type == RFCType.MORAL:
            if details['RazonSocial'] != res['Denominación o Razón Social']:
                logger.error(f"{rfc}: RazonSocial '{details['RazonSocial']}' is invalid, expected '{res['Denominación o Razón Social']}'")
        elif rfc.type == RFCType.FISICA:
            if details['RazonSocial'] != f"{res['Nombre']} {res['Apellido Paterno']} {res['Apellido Materno']}":
                logger.error(f"{rfc}: RazonSocial '{details['RazonSocial']}' is invalid, expected '{res['Nombre']} {res['Apellido Paterno']} {res['Apellido Materno']}'")

        if details['CodigoPostal'] != res['CP']:
            logger.error(f"{rfc}: CodigoPostal '{details['CodigoPostal']}' is invalid, expected '{res['CP']}'")

        if details['RegimenFiscal'] not in (r['RegimenFiscal'] for r in res['Regimenes']):
            logger.error(
                f"{rfc}: RegimenFiscal '{details['RegimenFiscal']}' is invalid, "
                f"expected '{(r['RegimenFiscal'].code for r in res['Regimenes'])}'"
            )

        if res['Situación del contribuyente'] not in ['ACTIVO', 'REACTIVADO']:
            logger.error(f"{rfc}: Is not ACTIVO '{res['Situación del contribuyente']}'")

        taxpayer_status = sat_service.list_69b(rfc)
        if taxpayer_status:
            logger.error(f"{rfc}: has status '{taxpayer_status}'")


def clientes_generar_txt(clients):
    with open("clientes.txt", 'w') as f:
        for i, (cliente_rfc, cliente_data) in enumerate(clients.items(), start=1):
            f.write(f"{i}|{cliente_rfc}|{cliente_data['RazonSocial']}|{cliente_data['CodigoPostal']}")
            f.write("\n")
