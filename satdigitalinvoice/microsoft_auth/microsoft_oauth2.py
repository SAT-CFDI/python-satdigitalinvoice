import hashlib
import json
import posixpath
import secrets
import webbrowser
from base64 import urlsafe_b64encode
from random import randrange
from urllib.parse import urlparse, parse_qs

import requests

from .auth_code_receiver import AuthCodeReceiver


def get_token(
        issuer_uri,
        client_id,
        redirect_uri=None,
        scopes=None,
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

    if redirect_uri is None:
        server = AuthCodeReceiver(port=0)
        port = server.get_port()
        redirect_uri = f"http://localhost:{port}/"
    else:
        server = AuthCodeReceiver(port=int(redirect_uri.split(":")[-1]))

    res = requests.get(
        url=posixpath.join(issuer_uri, "oauth2/v2.0/authorize"),
        params={
            "client_id": client_id,
            "response_type": "code",
            "scope": " ".join(scopes or []),
            "redirect_uri": redirect_uri,
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

    q = server.get_auth_response(timeout=1000, state=state)
    return _exchange_code(
        client_id=client_id,
        issuer_uri=issuer_uri,
        code_verifier=code_verifier,
        redirect_url=redirect_uri,
        code=q["code"]
    )


def get_token_manual(
        issuer_uri,
        client_id,
        redirect_uri=None,
        scopes=None,
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

    print({
        "code_verifier": code_verifier,
        "code_challenge": code_challenge
    })

    res = requests.get(
        url=posixpath.join(issuer_uri, "oauth2/v2.0/authorize"),
        params={
            "client_id": client_id,
            "response_type": "code",
            "scope": " ".join(scopes),
            "redirect_uri": redirect_uri,
            "state": state,
            "nonce": nonce,  # Optional
            "code_challenge_method": "S256",
            "code_challenge": code_challenge,
            # "client_info": "1",
            # "prompt": "select_account",
            # "login_hint": login_hint or "",
            # "domain_hint": domain_hint or ""
        }
    )
    assert res.status_code == 200

    if browser_name:
        webbrowser.get(browser_name).open(res.request.url)
    else:
        webbrowser.open(res.request.url)

    response = input('TYPE YOUR RETURN URI:')
    o = urlparse(response.rstrip())
    q = parse_qs(o.query)

    return _exchange_code(
        client_id=client_id,
        issuer_uri=issuer_uri,
        code_verifier=code_verifier,
        redirect_url=redirect_uri,
        code=q["code"]
    )


def token_refresh(
        refresh_token,
        issuer_uri,
        client_id,
        scopes=None,
        origin=None
):
    data = {
        "grant_type": "refresh_token",
        "client_id": client_id,
        "refresh_token": refresh_token
    }
    if scopes:
        data["scope"] = " ".join(scopes or [])

    token = requests.post(
        url=posixpath.join(issuer_uri, "oauth2/v2.0/token"),
        data=data,
        headers={
            'origin': origin
        },
    )

    if token.status_code == 200:
        return token.json()

    raise Exception(token.json())


def _exchange_code(issuer_uri, client_id, code_verifier, redirect_url, code):
    token = requests.post(
        url=posixpath.join(issuer_uri, "oauth2/v2.0/token"),
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code_verifier": code_verifier,
            "redirect_uri": redirect_url,
            "code": code
        },
        headers={
            # 'origin': redirect_url  # This might be need for web apps but not for desktop apps
        },
    )
    if token.status_code == 200:
        return token.json()

    assert token.status_code == 200, token.text
