import base64

from azure.identity import AzureCliCredential
from azure.keyvault.secrets import SecretClient
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives._serialization import Encoding, PrivateFormat, NoEncryption
from cryptography.hazmat.primitives.serialization import pkcs12


def get_certificate(vault_url, certificate_name):
    credential = AzureCliCredential(
        tenant_id="72f988bf-86f1-41af-91ab-2d7cd011db47"
    )
    secret_client = SecretClient(vault_url=vault_url, credential=credential)
    return secret_client.get_secret(certificate_name)


def get_client_credential(vault_url, certificate_name):
    cert_key = get_certificate(vault_url, certificate_name)

    # https://github.com/Azure/azure-sdk-for-python/blob/07d10639d7e47f4852eaeb74aef5d569db499d6e/sdk/identity/azure-identity/azure/identity/_credentials/certificate.py#L101-L123
    private_key, cert, _ = pkcs12.load_key_and_certificates(
        base64.b64decode(cert_key.value), None, backend=default_backend()
    )

    return {
        "private_key": private_key.private_bytes(
            encoding=Encoding.PEM,
            format=PrivateFormat.PKCS8,
            encryption_algorithm=NoEncryption()).decode(),
        "thumbprint": cert.fingerprint(hashes.SHA1()).hex(),
        "public_certificate": cert.public_bytes(Encoding.PEM).decode(),
    }
