import logging
from datetime import date, datetime
from decimal import Decimal

from satcfdi import Signer

from satdigitalinvoice.file_data_managers import ClientsManager, FacturasManager, ConfigManager
from satdigitalinvoice.gui_functions import generate_ingresos, periodo_desc
from satdigitalinvoice.utils import find_best_match

csd_signer = Signer.load(
    certificate=open('csd/cacx7605101p8.cer', 'rb').read(),
    key=open('csd/cacx7605101p8.key', 'rb').read(),
    password=open('csd/cacx7605101p8.txt', 'rb').read(),
)
ym_date = datetime(year=2023, month=4, day=1)
clients = ClientsManager()


def test_generar_ingresos(caplog):
    caplog.set_level(logging.INFO)
    config = ConfigManager()
    facturas = FacturasManager(ym_date)["Facturas"]

    facturas = generate_ingresos(
        serie=config["serie"],
        folio=1000,
        clients=clients,
        facturas=facturas,
        ym_date=date(year=2023, month=4, day=1),
        csd_signer=csd_signer,
    )

    assert caplog.records == []
    assert len(facturas) == 3
    assert facturas[0]["Total"] == Decimal('18065.66')


def test_generar_ingresos_error(caplog):
    caplog.set_level(logging.INFO)
    config = ConfigManager()
    facturas = FacturasManager(ym_date)["FacturasIncorrectas"]
    print(len(facturas))

    ingresos = generate_ingresos(
        serie=config["serie"],
        folio=1000,
        clients=clients,
        facturas=facturas,
        ym_date=date(year=2023, month=4, day=1),
        csd_signer=csd_signer,
    )

    assert len(caplog.records) == 1
    assert caplog.records[0].message == "ABMG891115PD7: Total '41000.16' is invalid, expected '37019.16'"
    assert ingresos is None


def test_generar_ingresos_error2(caplog):
    caplog.set_level(logging.INFO)
    config = ConfigManager()
    facturas = FacturasManager(ym_date)["FacturasIncorrectas2"]
    print(len(facturas))

    ingresos = generate_ingresos(
        serie=config["serie"],
        folio=1000,
        clients=ClientsManager(),
        facturas=facturas,
        ym_date=date(year=2023, month=4, day=1),
        csd_signer=csd_signer,
    )

    assert len(caplog.records) == 1
    assert caplog.records[0].message == "XXXNOEXISTO: client not found"
    assert ingresos is None


def test_periodo_desc():
    assert periodo_desc(date(year=2021, month=1, day=1), 'Mensual.1') == 'MES DE ENERO DEL 2021'
    assert periodo_desc(date(year=2021, month=1, day=1), 'Bimestral.2') is None
    assert periodo_desc(date(year=2021, month=1, day=1), 'Trimestral.3') is None
    assert periodo_desc(date(year=2021, month=1, day=1), 'Cuatrimestral.4') is None
    assert periodo_desc(date(year=2021, month=1, day=1), 'Semestral.5') is None
    assert periodo_desc(date(year=2021, month=1, day=1), 'Anual.6') is None

    assert periodo_desc(date(year=2021, month=12, day=1), 'Mensual.7') == 'MES DE DICIEMBRE DEL 2021'
    assert periodo_desc(date(year=2021, month=12, day=1), 'Bimestral.8') == 'MES DE DICIEMBRE DEL 2021 AL MES DE ENERO DEL 2022'
    assert periodo_desc(date(year=2021, month=12, day=1), 'Trimestral.9') == 'MES DE DICIEMBRE DEL 2021 AL MES DE FEBRERO DEL 2022'
    assert periodo_desc(date(year=2021, month=12, day=1), 'Cuatrimestral.8') == 'MES DE DICIEMBRE DEL 2021 AL MES DE MARZO DEL 2022'
    assert periodo_desc(date(year=2021, month=12, day=1), 'Semestral.6') == 'MES DE DICIEMBRE DEL 2021 AL MES DE MAYO DEL 2022'
    assert periodo_desc(date(year=2021, month=12, day=1), 'Anual.12') == 'MES DE DICIEMBRE DEL 2021 AL MES DE NOVIEMBRE DEL 2022'


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
        assert find_best_match(cases, datetime(2022, 4, 5))[1] is None
        assert find_best_match(cases, datetime(2023, 4, 5))[1] == Decimal('20.00')
        assert find_best_match(cases, datetime(2024, 4, 5))[1] == Decimal('30.00')
        assert find_best_match(cases, datetime(2025, 4, 5))[1] == Decimal('40.00')
        assert find_best_match(cases, datetime(2026, 4, 5))[1] is None
