from satcfdi import Signer
from satcfdi.accounting.email import EmailManager
from satcfdi.pacs import Environment
from satcfdi.pacs.diverza import Diverza

from satdigitalinvoice.__main__ import FacturacionGUI


def create_app():
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

    return app


