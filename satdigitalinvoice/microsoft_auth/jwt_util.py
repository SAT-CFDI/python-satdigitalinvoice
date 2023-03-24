import base64
import hashlib
import hmac
import json
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, padding
from hmac import HMAC


def create_signature(data, key, header):
    alg = header["alg"]

    match alg[:2]:
        case "HS":
            algorithm = {
                'HS256': hashlib.sha256,
                'HS384': hashlib.sha384,
                'HS512': hashlib.sha512
            }[alg]

            return HMAC(key, data, algorithm).digest()

        case 'RS' | 'PS':
            algorithm = {
                'RS256': hashes.SHA256,
                'RS384': hashes.SHA384,
                'RS512': hashes.SHA512,
                'PS256': hashes.SHA256,
                'PS384': hashes.SHA384,
                'PS512': hashes.SHA512,
            }[alg]()

            if alg.startswith("RS"):
                pad = padding.PKCS1v15()
            else:
                pad = padding.PSS(
                    mgf=padding.MGF1(algorithm),
                    salt_length=algorithm.digest_size
                )

            return key.sign(
                data=data,
                padding=pad,
                algorithm=algorithm
            )


def make_jwt(key, header, payload):
    header_segment = _base64url_encode(json.dumps(header).encode())
    payload_segment = _base64url_encode(json.dumps(payload).encode())

    signed_data = (header_segment + "." + payload_segment).encode()
    signature = create_signature(signed_data, key, header)
    crypto_segment = _base64url_encode(signature)

    return header_segment + "." + payload_segment + "." + crypto_segment


def load_jwt(jwt):
    try:
        header_segment, payload_segment, crypto_segment = jwt.split('.', 2)

        header = json.loads(_base64url_decode(header_segment))
        payload = json.loads(_base64url_decode(payload_segment))
        signature = _base64url_decode(crypto_segment)

        return header, payload, signature
    except Exception as e:  # (ValueError, TypeError)
        raise Exception("Unable to parse token") from e


def _base64url_decode(input):
    input += '=' * (-len(input) % 4)
    return base64.urlsafe_b64decode(input)


def _base64url_encode(input):
    input = base64.urlsafe_b64encode(input).decode()
    return input.rstrip("=")
