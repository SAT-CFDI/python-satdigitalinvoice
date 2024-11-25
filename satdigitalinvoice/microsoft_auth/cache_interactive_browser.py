import time

from typing import Optional, Any
from azure.core.credentials import TokenCredential, AccessToken

from .jwt_util import load_jwt
from .microsoft_oauth2 import get_token, token_refresh

AZURE_CLI = "04b07795-8ddb-461a-bbee-02f9e1bf7b46"


class CacheInteractiveBrowserCredential(TokenCredential):
    def __init__(self, cache, login_hint=None, browser_name=None):
        self.cache = cache
        self.login_hint = login_hint
        self.browser_name = browser_name

    """Authenticates by requesting a token from the Azure CLI.

    This requires previously logging in to Azure via "az login", and will use the CLI's currently logged in identity.
    """

    def get_token(self, *scopes: str, claims: Optional[str] = None, tenant_id: Optional[str] = None, **kwargs: Any) -> AccessToken:
        if tenant_id is None:
            raise ValueError("Tenant is required")
        if len(scopes) != 1:
            raise ValueError("This credential requires exactly one scope per token request.")

        service_token = self.cache.get((tenant_id, scopes[0]))
        if not service_token:
            refresh_token = self.cache.get(tenant_id)
            if not refresh_token:
                refresh_token = get_token(
                    issuer_uri="https://login.microsoftonline.com/f20a8dfd-ca10-4d0f-926d-e0a08b44bb15/",
                    client_id=AZURE_CLI,
                    scopes=['offline_access', 'openid', 'profile'],
                    login_hint=self.login_hint,
                    domain_hint=self.login_hint.split("@")[-1] if "@" in (self.login_hint or "") else None,
                    browser_name=self.browser_name,
                )['refresh_token']
                self.cache.set(tenant_id, refresh_token, expire=90*24*60*60)  # expire=int(token["expires_in"])

            # Tenant properties
            service_token = token_refresh(
                refresh_token=refresh_token,
                issuer_uri=f"https://sts.windows.net/{tenant_id}/",
                client_id=AZURE_CLI,
                scopes=scopes,
            )

            self.cache.set((tenant_id, scopes[0]), service_token, expire=service_token["expires_in"])
            refresh_token = service_token["refresh_token"]
            self.cache.set(tenant_id, refresh_token, expire=90*24*60*60)

        # return service_token
        _, payload, _ = load_jwt(service_token["access_token"])
        return AccessToken(service_token["access_token"], payload["exp"])
