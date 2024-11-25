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

    def get_secret_value(self, name, clear_cache=False):
        if clear_cache:
            try:
                del self.cache[name]
            except KeyError:
                pass
        secret = self.cache_get_secret(name)

        value = secret.value
        content_type = secret.properties.content_type

        match content_type:
            case "base64":
                return base64.b64decode(value)

            case "encrypted/json":
                res = self.encryption_key.decrypt(value.encode())
                return json.loads(res)

        return value

    def set_secret_value(self, name, value, content_type="encrypted/json"):

        match content_type:
            case "base64":
                value = base64.b64encode(value).decode()

            case "encrypted/json":
                value = self.encryption_key.encrypt(json.dumps(value).encode()).decode()

            case _:
                raise ValueError(f"Invalid content_type: {content_type}")

        self.set_secret(name, value, content_type=content_type)
        try:
            del self.cache[name]
        except KeyError:
            pass

