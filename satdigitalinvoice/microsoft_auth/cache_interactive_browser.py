import time

from typing import Optional, Any
from azure.core.credentials import TokenCredential, AccessToken
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
        resource = scopes[0]

        token = self.cache.get(tenant_id)

        if not token:
            token = get_token(
                issuer_url="https://login.microsoftonline.com/organizations/",  # is 'https://sts.windows.net/f8cdef31-a31e-4b4a-93e4-5f571e91255a/'
                app_client_id=AZURE_CLI,
                scopes=['offline_access', 'openid', 'profile'],
                login_hint=self.login_hint,
                domain_hint=self.login_hint.split("@")[-1] if "@" in (self.login_hint or "") else None,
                browser_name=self.browser_name,
            )
            self.cache.set(tenant_id, token)  # expire=int(token["expires_in"])

        service_token = self.cache.get((tenant_id, resource))

        if not service_token:
            # Tenant properties
            service_token = token_refresh(
                token=token,
                issuer_url=f"https://sts.windows.net/{tenant_id}/",
                scopes=[resource, 'offline_access', 'openid', 'profile'],
            )

            self.cache.set((tenant_id, 'main'), service_token, expire=int(service_token["expires_in"]))

        # return service_token
        now = int(time.time())
        return AccessToken(service_token["access_token"], now + int(service_token["expires_in"]))
