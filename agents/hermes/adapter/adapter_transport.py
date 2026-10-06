from __future__ import annotations

import base64
import http.client
import json
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode, urlsplit

from adapter_config import (
    AdapterError, CONNECT_TIMEOUT_SECONDS, MAX_RESPONSE_BYTES, READ_TIMEOUT_SECONDS,
    REQUIRED_SCOPE, TOKEN_REFRESH_SKEW_SECONDS, _validate_https_endpoint,
)

@dataclass
class HttpResponse:
    status: int
    headers: dict[str, str]
    body: bytes


class HttpsTransport:
    """HTTPS-only transport with fixed connect/read timeouts and no redirects."""

    def __init__(self, connect_timeout: int = CONNECT_TIMEOUT_SECONDS, read_timeout: int = READ_TIMEOUT_SECONDS):
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout

    def request(self, url: str, method: str, headers: dict[str, str], body: bytes) -> HttpResponse:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.port not in (None, 443):
            raise AdapterError("transport_rejected")
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        connection = http.client.HTTPSConnection(parsed.hostname, timeout=self.connect_timeout)
        try:
            connection.connect()
            if connection.sock:
                connection.sock.settimeout(self.read_timeout)
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            response_body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(response_body) > MAX_RESPONSE_BYTES:
                raise AdapterError("remote_response_too_large")
            return HttpResponse(response.status, {key.lower(): value for key, value in response.getheaders()}, response_body)
        except AdapterError:
            raise
        except Exception:
            raise AdapterError("transport_failure") from None
        finally:
            connection.close()


class TokenCache:
    def __init__(self, token_url: str, client_id: str, client_secret: str, transport: Any, clock=time.monotonic):
        self.token_url = _validate_https_endpoint(token_url, "cognito")
        if not client_id or not client_secret:
            raise AdapterError("missing_client_credentials")
        self.client_id = client_id
        self.client_secret = client_secret
        self.transport = transport
        self.clock = clock
        self._token: str | None = None
        self._expires_at = 0.0

    def get(self, force_refresh: bool = False) -> str:
        if not force_refresh and self._token and self.clock() < self._expires_at - TOKEN_REFRESH_SKEW_SECONDS:
            return self._token
        self._token = None
        basic = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode("ascii")
        body = urlencode({"grant_type": "client_credentials", "scope": REQUIRED_SCOPE}).encode("ascii")
        response = self.transport.request(
            self.token_url,
            "POST",
            {"Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
            body,
        )
        if response.status != 200:
            raise AdapterError("token_endpoint_failure")
        try:
            document = json.loads(response.body.decode("utf-8"))
            token = document["access_token"]
            expires_in = document["expires_in"]
            token_type = document["token_type"]
            scope = document.get("scope")
            if not isinstance(token, str) or not token or not isinstance(expires_in, int) or expires_in < 1 or expires_in > 86400:
                raise ValueError
            if not isinstance(token_type, str) or token_type.lower() != "bearer":
                raise ValueError
            # RFC 6749 section 5.1 makes the response `scope` field OPTIONAL
            # when the granted scope is identical to the requested one, and
            # Cognito omits it for this client. Requiring the echo rejected
            # every token. A scope that IS present must still match exactly.
            if "scope" in document and (not isinstance(scope, str) or scope.split() != [REQUIRED_SCOPE]):
                raise AdapterError("oauth_scope_mismatch")
        except AdapterError:
            raise
        except Exception:
            raise AdapterError("invalid_token_response") from None
        self._token = token
        self._expires_at = self.clock() + expires_in
        return token

    def invalidate(self, token: str) -> None:
        if self._token == token:
            self._token = None
            self._expires_at = 0.0
