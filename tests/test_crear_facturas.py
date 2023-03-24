from datetime import date, datetime
from decimal import Decimal
from unittest import mock

import pytest
from satcfdi.models import Signer, DatePeriod

from satdigitalinvoice.__version__ import __package__
from satdigitalinvoice.exceptions import ConsoleErrors
from satdigitalinvoice.file_data_managers import ClientsManager, FacturasManager
from satdigitalinvoice.gui_functions import generate_ingresos, periodicidad_desc
from satdigitalinvoice.utils import find_best_match
from tests.utils import verify_result, XElementPrettyPrinter

csd_signer = Signer.load(
    certificate=open('csd/cacx7605101p8.cer', 'rb').read(),
    key=open('csd/cacx7605101p8.key', 'rb').read(),
    password=open('csd/cacx7605101p8.txt', 'rb').read(),
)
ym_date = DatePeriod(year=2023, month=4)
clients = ClientsManager()
module = __package__


def test_generar_ingresos():
    facturas = FacturasManager(ym_date)["Facturas"]

    with mock.patch(f'satcfdi.create.cfd.cfdi40.datetime') as m:
        m.now = mock.Mock(return_value=datetime(2022, 1, 1))

        facturas = generate_ingresos(
            clients=clients,
            facturas=facturas,
            dp=date(year=2023, month=4, day=1),
        )

        assert len(facturas) == 3

        pp = XElementPrettyPrinter()
        verify = verify_result(data=pp.pformat(facturas), filename=f"facturas.pretty.py")
        assert verify


def test_generar_ingresos_error():
    facturas = FacturasManager(ym_date)["FacturasIncorrectas"]
    assert len(facturas) == 1

    with pytest.raises(ConsoleErrors) as e:
        generate_ingresos(
            clients=clients,
            facturas=facturas,
            dp=date(year=2023, month=4, day=1),
        )

    assert e.value.errors == ["1 ABMG891115PD7: Total '41000.16' is invalid, expected '37019.16'"]


def test_generar_ingresos_error2():
    facturas = FacturasManager(ym_date)["FacturasIncorrectas2"]
    assert len(facturas) == 1

    with pytest.raises(ConsoleErrors) as e:
        generate_ingresos(
            clients=ClientsManager(),
            facturas=facturas,
            dp=date(year=2023, month=4, day=1),
        )

    assert e.value.errors == ['1 XXXNOEXISTO: Receptor not found']


def test_periodo_desc():
    assert periodicidad_desc(DatePeriod(year=2021, month=1), 'Mensual.1', offset=0) == 'MES DE ENERO DEL 2021'
    assert periodicidad_desc(DatePeriod(year=2021, month=1), 'Bimestral.2', offset=0) is None
    assert periodicidad_desc(DatePeriod(year=2021, month=1), 'Trimestral.3', offset=0) is None
    assert periodicidad_desc(DatePeriod(year=2021, month=1), 'Cuatrimestral.4', offset=0) is None
    assert periodicidad_desc(DatePeriod(year=2021, month=1), 'Semestral.5', offset=0) is None
    assert periodicidad_desc(DatePeriod(year=2021, month=1), 'Anual.6', offset=0) is None

    assert periodicidad_desc(DatePeriod(year=2021, month=12), 'Mensual.7', offset=0) == 'MES DE DICIEMBRE DEL 2021'
    assert periodicidad_desc(DatePeriod(year=2021, month=12), 'Bimestral.8', offset=0) == 'MES DE DICIEMBRE DEL 2021 AL MES DE ENERO DEL 2022'
    assert periodicidad_desc(DatePeriod(year=2021, month=12), 'Trimestral.9', offset=0) == 'MES DE DICIEMBRE DEL 2021 AL MES DE FEBRERO DEL 2022'
    assert periodicidad_desc(DatePeriod(year=2021, month=12), 'Cuatrimestral.8', offset=0) == 'MES DE DICIEMBRE DEL 2021 AL MES DE MARZO DEL 2022'
    assert periodicidad_desc(DatePeriod(year=2021, month=12), 'Semestral.6', offset=0) == 'MES DE DICIEMBRE DEL 2021 AL MES DE MAYO DEL 2022'
    assert periodicidad_desc(DatePeriod(year=2021, month=12), 'Anual.12', offset=0) == 'MES DE DICIEMBRE DEL 2021 AL MES DE NOVIEMBRE DEL 2022'

    assert periodicidad_desc(DatePeriod(year=2021, month=1), 'Mensual.1', offset=1) == 'MES DE FEBRERO DEL 2021'
    assert periodicidad_desc(DatePeriod(year=2021, month=1), 'Bimestral.2', offset=1) is None
    assert periodicidad_desc(DatePeriod(year=2021, month=1), 'Trimestral.3', offset=1) is None
    assert periodicidad_desc(DatePeriod(year=2021, month=1), 'Cuatrimestral.4', offset=1) is None
    assert periodicidad_desc(DatePeriod(year=2021, month=1), 'Semestral.5', offset=1) is None
    assert periodicidad_desc(DatePeriod(year=2021, month=1), 'Anual.6', offset=1) is None

    assert periodicidad_desc(DatePeriod(year=2021, month=12), 'Mensual.7', offset=1) == 'MES DE ENERO DEL 2022'
    assert periodicidad_desc(DatePeriod(year=2021, month=12), 'Bimestral.8', offset=1) == 'MES DE ENERO DEL 2022 AL MES DE FEBRERO DEL 2022'
    assert periodicidad_desc(DatePeriod(year=2021, month=12), 'Trimestral.9', offset=1) == 'MES DE ENERO DEL 2022 AL MES DE MARZO DEL 2022'
    assert periodicidad_desc(DatePeriod(year=2021, month=12), 'Cuatrimestral.8', offset=1) == 'MES DE ENERO DEL 2022 AL MES DE ABRIL DEL 2022'
    assert periodicidad_desc(DatePeriod(year=2021, month=12), 'Semestral.6', offset=1) == 'MES DE ENERO DEL 2022 AL MES DE JUNIO DEL 2022'
    assert periodicidad_desc(DatePeriod(year=2021, month=12), 'Anual.12', offset=1) == 'MES DE ENERO DEL 2022 AL MES DE DICIEMBRE DEL 2022'


def test_find_best_match():
    casesA = {
        '2022-12': Decimal('20.00'),
        '2023-12': Decimal('30.00'),
        '2024-12': Decimal('40.00'),
        '2025-12': None,
    }
    casesB = {
        '2025-12': None,
        '2024-12': Decimal('40.00'),
        '2023-12': Decimal('30.00'),
        '2022-12': Decimal('20.00'),
    }

    for cases in (casesA, casesB):
        assert find_best_match(cases, DatePeriod(2022, 4, 5))[1] is None
        assert find_best_match(cases, DatePeriod(2023, 4, 5))[1] == Decimal('20.00')
        assert find_best_match(cases, DatePeriod(2024, 4, 5))[1] == Decimal('30.00')
        assert find_best_match(cases, DatePeriod(2025, 4, 5))[1] == Decimal('40.00')
        assert find_best_match(cases, DatePeriod(2026, 4, 5))[1] is None
