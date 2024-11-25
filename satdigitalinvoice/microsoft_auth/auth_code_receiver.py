# from https://github.com/AzureAD/microsoft-authentication-library-for-python
# modified to not use threading so as to wait for response
import logging
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from string import Template
from urllib.parse import urlparse, parse_qs

logger = logging.getLogger(__name__)


def _qs2kv(qs):
    """Flatten parse_qs()'s single-item lists into the item itself"""
    return {k: v[0] if isinstance(v, list) and len(v) == 1 else v
            for k, v in qs.items()}


# success_template = Template("Authentication completed. You can close this window now.")
error_template = Template("Authentication failed. $error: $error_description. ($error_uri)")
welcome_template = "Welcome"

success_template = Template('<html><body>Authentication completed. You can close this window now.<script>setTimeout("window.close()",3000)</script></body></html>')


class _AuthCodeHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        # For flexibility, we choose to not check self.path matching redirect_uri
        # assert self.path.startswith('/THE_PATH_REGISTERED_BY_THE_APP')
        qs = parse_qs(urlparse(self.path).query)
        if qs.get('code') or qs.get("error"):  # So, it is an auth response
            self.server.auth_response = _qs2kv(qs)
            logger.debug("Got auth response: %s", self.server.auth_response)
            template = (success_template
                        if "code" in qs else error_template)
            self._send_full_response(
                template.safe_substitute(**self.server.auth_response))
            # NOTE: Don't do self.server.shutdown() here. It'll halt the server.
        else:
            self._send_full_response(welcome_template)

    def _send_full_response(self, body, is_ok=True):
        self.send_response(200 if is_ok else 400)
        content_type = 'text/plain'
        content_type = 'text/html'
        self.send_header('Content-type', content_type)
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    def log_message(self, format, *args):
        logger.debug(format, *args)  # To override the default log-to-stderr behavior


def is_wsl():
    # "Official" way of detecting WSL: https://github.com/Microsoft/WSL/issues/423#issuecomment-221627364
    # Run `uname -a` to get 'release' without python
    #   - WSL 1: '4.4.0-19041-Microsoft'
    #   - WSL 2: '4.19.128-microsoft-standard'
    import platform
    uname = platform.uname()
    platform_name = getattr(uname, 'system', uname[0]).lower()
    release = getattr(uname, 'release', uname[2]).lower()
    return platform_name == 'linux' and 'microsoft' in release


class _AuthCodeHttpServer(HTTPServer, object):
    # address_family = socket.AF_INET6 # if using ipv6
    def __init__(self, server_address, *args, **kwargs):
        _, port = server_address
        if port and (sys.platform == "win32" or is_wsl()):
            # The default allow_reuse_address is True. It works fine on non-Windows.
            # On Windows, it undesirably allows multiple servers listening on same port,
            # yet the second server would not receive any incoming request.
            # So, we need to turn it off.
            self.allow_reuse_address = False
        super(_AuthCodeHttpServer, self).__init__(server_address, *args, **kwargs)

    def handle_timeout(self):
        # It will be triggered when no request comes in self.timeout seconds.
        # See https://docs.python.org/3/library/socketserver.html#socketserver.BaseServer.handle_timeout
        raise RuntimeError("Timeout. No auth response arrived.")  # Terminates this server
        # We choose to not call self.server_close() here,
        # because it would cause a socket.error exception in handle_request(),
        # and likely end up the server being server_close() twice.


class AuthCodeReceiver(object):
    # This class has (rather than is) an _AuthCodeHttpServer, so it does not leak API
    def __init__(self, port=None):
        address = "127.0.0.1"
        self._server = _AuthCodeHttpServer((address, port or 0), _AuthCodeHandler)
        self._closing = False

    def get_port(self):
        """The port this server actually listening to"""
        # https://docs.python.org/2.7/library/socketserver.html#SocketServer.BaseServer.server_address
        return self._server.server_address[1]

    def get_auth_response(self, timeout=None, state=None):
        self._server.timeout = timeout  # Otherwise its handle_timeout() won't work
        self._server.auth_response = {}  # Shared with _AuthCodeHandler
        while not self._closing:  # Otherwise, the handle_request() attempt
            self._server.handle_request()
            if self._server.auth_response:
                if state and state != self._server.auth_response.get("state"):
                    logger.debug("State mismatch. Ignoring this noise.")
                else:
                    break

        response = self._server.auth_response
        self._server.server_close()
        return response or None  # Return via writable result param

    def close(self):
        """Either call this eventually; or use the entire class as context manager"""
        self._closing = True
        self._server.server_close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
