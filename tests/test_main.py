from satcfdi import Signer
from satcfdi.accounting.email import EmailManager
from satcfdi.pacs import Environment
from satcfdi.pacs.diverza import Diverza

from satdigitalinvoice.__main__ import FacturacionGUI
from satdigitalinvoice.layout import make_layout


def test_main():
    pac_service = Diverza(
        rfc="asdfas",
        id='123',
        token='asdf',
        environment=Environment.TEST
    )

    fiel_signer = None

    csd_signer = Signer.load(
        certificate=open('csd/cacx7605101p8.cer', 'rb').read(),
        key=open('csd/cacx7605101p8.key', 'rb').read(),
        password=open('csd/cacx7605101p8.txt', 'rb').read(),
    )

    email_manager = EmailManager(
        stmp_host="hola.com",
        stmp_port=123,
        imap_host="hola.com",
        imap_port=789,
        user="someuser@email.com",
        password="1234"
    )

    app = FacturacionGUI(
        pac_service=pac_service,
        csd_signer=csd_signer,
        fiel_signer=fiel_signer,
        email_manager=email_manager,
    )


# function to check the uniqueness of keys in pysimplegui layout
def check_unique_keys(layout):
    keys = []
    for element in layout:
        if isinstance(element, list):
            check_unique_keys(element)
        else:
            if element[0] in keys:
                raise Exception(f"Key {element[0]} is not unique")
            else:
                keys.append(element[0])


def test_layout_unique_keys():
    layout = make_layout(has_fiel=True)

    def elements(layout):
        for e in layout:
            if isinstance(e, list):
                yield from elements(e)
            else:
                yield e

    unique_keys = set()
    for e in elements(layout):
        if e.Key:
            if e.Key in unique_keys:
                raise Exception(f"Key {e.Key} is not unique")
            else:
                unique_keys.add(e.Key)
