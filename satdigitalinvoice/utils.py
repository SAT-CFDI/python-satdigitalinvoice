import os
import random
import shutil
import subprocess
import sys
from datetime import datetime, date
from uuid import UUID

from satcfdi.models import Signer, DatePeriod
from satcfdi.accounting.models import EstadoComprobante


def to_date_period(periodo):
    if not periodo:
        return DatePeriod(year=None)

    for f in ('%Y', '%Y-%m', '%Y-%m-%d'):
        try:
            d = datetime.strptime(periodo, f)
            return DatePeriod(
                d.year,
                d.month if '%Y-%m' in f else None,
                d.day if f == '%Y-%m-%d' else None
            )
        except ValueError:
            pass


def to_uuid(s):
    try:
        return UUID(s)
    except ValueError:
        return None


def to_int(s):
    try:
        return int(s)
    except ValueError:
        return None


def random_string():
    chars = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
    return "".join(random.choice(chars) for _ in range(32))


def convert_ans1_date(ans1_date):
    return datetime.strptime(ans1_date.decode('utf-8'), '%Y%m%d%H%M%SZ')


def cert_info(signer: Signer):
    if signer:
        return {
            "NoCertificado": signer.certificate_number,
            # "Tipo": str(signer.type),
            #
            # "organizationName": signer.certificate.get_subject().O,
            # "x500UniqueIdentifier": signer.certificate.get_subject().x500UniqueIdentifier,
            # "serialNumber": signer.certificate.get_subject().serialNumber,
            # "organizationUnitName": signer.certificate.get_subject().OU,
            # "emailAddress": signer.certificate.get_subject().emailAddress,
            #
            "Expira": convert_ans1_date(signer.certificate.get_notAfter()),
            "Creado": convert_ans1_date(signer.certificate.get_notBefore()),
        }


def find_best_match(cases, dp: DatePeriod | date) -> (date, object):
    fk, fv = (None, None)
    for k, v in cases.items():
        k = datetime.strptime(k, '%Y-%m').date()
        if k <= dp:
            if fk is None or k > fk:
                fk, fv = k, v
    return fk, fv


def clear_directory(directory):
    shutil.rmtree(directory, ignore_errors=True)
    os.makedirs(directory, exist_ok=True)


# calculate the number of months between two dates
def months_between(d1, d2):
    return (d1.year - d2.year) * 12 + d1.month - d2.month


def add_month(dp: DatePeriod, months):
    year, month = divmod(dp.year * 12 + dp.month + months - 1, 12)
    month += 1
    return DatePeriod(year, month)


def load_certificate(data):
    if 'data' in data:
        return Signer.load_pkcs12(
            **data,
        )
    else:
        return Signer.load(
            **data,
        )


def first_duplicate(seq):
    seen = set()
    for x in seq:
        if x in seen:
            return x
        seen.add(x)
    return None


def estado_to_estatus(estatus):
    if estatus == 'Vigente':
        return EstadoComprobante.VIGENTE.value
    elif estatus == 'Cancelado':
        return EstadoComprobante.CANCELADO.value
    raise ValueError(f"Unknown status: {estatus}")


def open_file(filename):
    match OS.get_os():
        case OS.WINDOWS:
            os.startfile(filename)
        case OS.LINUX:
            subprocess.call(['xdg-open', filename])
        case OS.MACOS:
            subprocess.call(['open', filename])
        case _:
            raise NotImplementedError(f"Unknown OS: {OS.get_os()}")


# Enum for operative Systems
class OS:
    WINDOWS = 'Windows'
    LINUX = 'Linux'
    MACOS = 'MacOS'
    UNKNOWN = 'Unknown'

    @staticmethod
    def get_os():
        if sys.platform.startswith('win'):
            return OS.WINDOWS
        elif sys.platform.startswith('linux'):
            return OS.LINUX
        elif sys.platform.startswith('darwin'):
            return OS.MACOS
        else:
            return OS.UNKNOWN
