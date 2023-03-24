import base64
import logging
import random
from datetime import datetime
from uuid import UUID

from satcfdi import Signer


def to_uuid(s):
    try:
        return UUID(s)
    except ValueError:
        return None


def random_string():
    hash = random.randbytes(32)
    res = base64.urlsafe_b64encode(hash).decode()
    return res.rstrip("=")


def add_file_handler():
    fh = logging.FileHandler(
        f'.data/errors.log',
        mode='a'
    )
    fh.setLevel(logging.ERROR)
    formatter = logging.Formatter('%(asctime)s - %(message)s')
    fh.setFormatter(formatter)
    logging.root.addHandler(fh)


def convert_ans1_date(ans1_date):
    return datetime.strptime(ans1_date.decode('utf-8'), '%Y%m%d%H%M%SZ')


def cert_info(signer: Signer):
    if signer:
        return {
            "NoCertificado": signer.certificate_number,
            "Tipo": str(signer.type),

            "organizationName": signer.certificate.get_subject().O,
            "x500UniqueIdentifier": signer.certificate.get_subject().x500UniqueIdentifier,
            "serialNumber": signer.certificate.get_subject().serialNumber,
            "organizationUnitName": signer.certificate.get_subject().OU,
            "emailAddress": signer.certificate.get_subject().emailAddress,

            "notAfter": convert_ans1_date(signer.certificate.get_notAfter()),
            "notBefore": convert_ans1_date(signer.certificate.get_notBefore()),
        }