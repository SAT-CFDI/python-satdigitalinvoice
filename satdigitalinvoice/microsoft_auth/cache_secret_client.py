import base64
import json

from azure.keyvault.secrets import SecretClient


class CacheSecretClient(SecretClient):
    def __init__(self, cache, encryption_key, vault_url, credential, **kwargs):
        self.cache = cache
        self.encryption_key = encryption_key
        super().__init__(vault_url, credential, **kwargs)

    def cache_get_secret(self, name):
        if res := self.cache.get(name):
            return res

        res = self.get_secret(name)
        self.cache[name] = res
        return res

    def get_secret_value(self, name):
        secret = self.cache_get_secret(name)

        value = secret.value
        content_type = secret.properties.content_type

        match content_type:
            case "application/json":
                return json.loads(value)

            case "base64":
                return base64.b64decode(value)

            case "encrypted":
                return self.encryption_key.decrypt(value.encode())

            case "encrypted/json":
                res = self.encryption_key.decrypt(value.encode())
                return json.loads(res)

        return value
