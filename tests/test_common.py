from satdigitalinvoice.formatting_functions.common import pesos
from decimal import Decimal


def test_pesos():
    assert pesos(1000.0) == '$1,000.00 (SON: MIL PESOS 00/100M.N.)'
    assert pesos(Decimal("123.123")) == '$123.12 (SON: CIENTO VEINTITRÉS PESOS 12/100M.N.)'
