import os
import random
import shutil
from datetime import datetime
from uuid import UUID

from satcfdi import Signer, DatePeriod


def parse_date_period(periodo):
    fmt, period = try_parsing_date(periodo)
    if fmt == '%Y':
        return DatePeriod(period.year)
    if fmt == '%Y-%m':
        return DatePeriod(period.year, period.month)
    if fmt == '%Y-%m-%d':
        return DatePeriod(period.year, period.month, period.day)


def try_parsing_date(text):
    for fmt in ('%Y', '%Y-%m', '%Y-%m-%d'):
        try:
            return fmt, datetime.strptime(text, fmt)
        except ValueError:
            pass
    raise ValueError('no valid date format found')


def parse_ym_date(periodo):
    return try_parsing_date(periodo)[1]


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
    chars = "0123456789abcdefghijklmnopqrstuvwxzyABCDEFGHIJKLMNOPQRSTUVWXZY"
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


def find_best_match(cases, emission_date):
    fk, fv = (None, None)
    for k, v in cases.items():
        k = parse_ym_date(k)
        if k <= emission_date:
            if fk is None or k > fk:
                fk, fv = k, v
    return fk, fv


def clear_directory(directory):
    shutil.rmtree(directory, ignore_errors=True)
    os.makedirs(directory, exist_ok=True)


# calculate the number of months between two dates
def months_between(d1, d2):
    return (d1.year - d2.year) * 12 + d1.month - d2.month


def add_month(d):
    m = d.month % 12 + 1
    y = d.year + d.month // 12
    return d.replace(year=y, month=m)


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
