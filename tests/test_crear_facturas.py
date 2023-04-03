import logging
from datetime import date

from satcfdi import Signer
from satcfdi.create.cfd import cfdi40

from satdigitalinvoice.file_data_managers import ClientsManager, FacturasManager, ConfigManager
from satdigitalinvoice.gui_functions import generate_ingresos, periodo_desc

csd_signer = Signer.load(
    certificate=open('csd/cacx7605101p8.cer', 'rb').read(),
    key=open('csd/cacx7605101p8.key', 'rb').read(),
    password=open('csd/cacx7605101p8.txt', 'rb').read(),
)

emisor = {
    "Emisor": cfdi40.Emisor(
        rfc=csd_signer.rfc,
        nombre=csd_signer.legal_name,
        regimen_fiscal="601",
    ),
    "LugarExpedicion": "12345",
}

clients = ClientsManager()


def test_generar_ingresos(caplog):
    caplog.set_level(logging.INFO)

    facturas = FacturasManager()["Facturas"]

    facturas = generate_ingresos(
        config=ConfigManager(),
        clients=clients,
        facturas=facturas,
        values={
            'inicio': '1',
            'final': '',
            'periodo': '2023-04'
        },
        csd_signer=csd_signer,
        base_template=emisor
    )

    assert caplog.records == []
    assert len(facturas) == 3


def test_generar_ingresos_error(caplog):
    caplog.set_level(logging.INFO)
    facturas = FacturasManager()["FacturasIncorrectas"]
    print(len(facturas))

    ingresos = generate_ingresos(
        config=ConfigManager(),
        clients=clients,
        facturas=facturas,
        values={
            'inicio': '1',
            'final': '',
            'periodo': '2023-04'
        },
        csd_signer=csd_signer,
        base_template=emisor
    )

    assert len(caplog.records) == 1
    assert caplog.records[0].message == "ABMG891115PD7: Total '41000.16' is invalid, expected '37019.16'"
    assert ingresos is None


def test_generar_ingresos_error2(caplog):
    caplog.set_level(logging.INFO)
    facturas = FacturasManager()["FacturasIncorrectas2"]
    print(len(facturas))

    ingresos = generate_ingresos(
        config=ConfigManager(),
        clients=ClientsManager(),
        facturas=facturas,
        values={
            'inicio': '1',
            'final': '',
            'periodo': '2023-04'
        },
        csd_signer=csd_signer,
        base_template=emisor
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
