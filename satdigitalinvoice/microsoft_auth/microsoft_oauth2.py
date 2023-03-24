import hashlib
import posixpath
import secrets
import webbrowser
from base64 import urlsafe_b64encode
from random import randrange

import requests

from .auth_code_receiver import AuthCodeReceiver
from .jwt_util import load_jwt


def get_token(
        issuer_url,
        app_client_id,
        redirect_url=None,
        scopes=None,
        origin=None,
        login_hint=None,
        domain_hint=None,
        browser_name=None
):
    state = str(randrange(1000000000))  # "InfoOfWhereTheUserWantedToGo"
    nonce = str(randrange(1000000000))

    # Your first step is to generate_key_pair a code verifier and challenge:
    # Code verifier: Random URL-safe string with a minimum length of 43 characters.
    # Code challenge: Base64 URL-encoded SHA-256 hash of the code verifier.
    code_verifier = secrets.token_urlsafe(43)
    m = hashlib.sha256()
    m.update(code_verifier.encode())
    code_challenge = urlsafe_b64encode(m.digest()).decode().rstrip("=")

    if redirect_url is None:
        server = AuthCodeReceiver(port=0)
        port = server.get_port()
        redirect_url = f"http://localhost:{port}/"
    else:
        server = AuthCodeReceiver(port=int(redirect_url.split(":")[-1]))

    res = requests.get(
        url=posixpath.join(issuer_url, "oauth2/v2.0/authorize"),
        params={
            "client_id": app_client_id,
            "response_type": "code",
            "scope": " ".join(scopes or []),
            "redirect_uri": redirect_url,
            "state": state,
            "nonce": nonce,  # Optional
            "code_challenge_method": "S256",
            "code_challenge": code_challenge,
            "client_info": "1",
            "prompt": "select_account",
            "login_hint": login_hint or "",
            "domain_hint": domain_hint or ""
        }
    )

    assert res.status_code == 200

    if browser_name:
        webbrowser.get(browser_name).open(res.request.url)
    else:
        webbrowser.open(res.request.url)

    result = server.get_auth_response(timeout=1000, state=state)
    q = result

    token = requests.post(
        url=posixpath.join(issuer_url, "oauth2/v2.0/token"),
        data={
            "grant_type": "authorization_code",
            "client_id": app_client_id,
            "code_verifier": code_verifier,
            "redirect_uri": redirect_url,
            "code": q["code"],
        },
        headers={
            'content-type': 'application/x-www-form-urlencoded',
            'origin': origin
        },
        # auth=HTTPBasicAuth(CLIENT_ID, CLIENT_SECRET),
    )

    if token.status_code == 200:
        return token.json()

    assert token.status_code == 200


def token_refresh(
        token,
        issuer_url=None,
        scopes=None,
        origin=None
):
    header, payload, _ = load_jwt(token['access_token'])

    issuer_url = issuer_url or payload["iss"]
    app_client_id = payload["appid"]  # Azure portal

    data = {
        "grant_type": "refresh_token",
        "client_id": app_client_id,
        "refresh_token": token['refresh_token']
    }
    if scopes:
        data["scope"] = " ".join(scopes or []),

    token = requests.post(
        url=posixpath.join(issuer_url, "oauth2/v2.0/token"),
        data=data,
        headers={
            'content-type': 'application/x-www-form-urlencoded',
            'origin': origin
        },
        # auth=HTTPBasicAuth(CLIENT_ID, CLIENT_SECRET),
    )

    if token.status_code == 200:
        return token.json()

    raise Exception(token.json())

