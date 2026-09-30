#!/usr/bin/env python3
"""Hermes stdio MCP adapter for one fixed Cognito-protected AgentCore Gateway."""
from __future__ import annotations

import base64
import http.client
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlsplit

TOOL_MANIFEST_PATH = Path(__file__).resolve().parent / "github-mcp-tools.json"
TOOL_MANIFEST = json.loads(TOOL_MANIFEST_PATH.read_text(encoding="utf-8"))
GITHUB_TOOLS = tuple(TOOL_MANIFEST["tools"])
TOOLS = frozenset(GITHUB_TOOLS)
GITHUB_TOOL_FILTER_VALUE = ",".join(sorted(TOOLS))
TARGET_PREFIX = "github___"
REQUIRED_SCOPE = "hermes-mcp/invoke"
MAX_LINE_BYTES = 1024 * 1024
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
CONNECT_TIMEOUT_SECONDS = 5
READ_TIMEOUT_SECONDS = 15
TOKEN_REFRESH_SKEW_SECONDS = 60


class AdapterError(Exception):
    def __init__(self, category: str):
        super().__init__(category)
        self.category = category


def _validate_https_endpoint(value: str, kind: str) -> str:
    try:
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError
        if kind == "gateway":
            valid_host = re.fullmatch(r"[a-z0-9-]+\.gateway\.bedrock-agentcore\.[a-z0-9-]+\.amazonaws\.com", parsed.hostname)
            valid_path = parsed.path == "/mcp"
        else:
            valid_host = re.fullmatch(r"[a-z0-9-]+\.auth\.[a-z0-9-]+\.amazoncognito\.com", parsed.hostname)
            valid_path = parsed.path == "/oauth2/token"
        if not valid_host or not valid_path or parsed.port not in (None, 443):
            raise ValueError
    except (TypeError, ValueError):
        raise AdapterError("invalid_local_endpoint_configuration") from None
    return value


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
            if not isinstance(scope, str) or scope.split() != [REQUIRED_SCOPE]:
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


class AgentCoreForwarder:
    def __init__(
        self,
        gateway_url: str,
        token_url: str,
        client_id: str,
        client_secret: str,
        transport: Any | None = None,
        clock=time.monotonic,
        tools: Any | None = None,
        tool_prefix: str | None = None,
        extra_headers: dict[str, str] | None = None,
    ):
        self.gateway_url = _validate_https_endpoint(gateway_url, "gateway")
        self.transport = transport or HttpsTransport()
        self.tokens = TokenCache(token_url, client_id, client_secret, self.transport, clock=clock)
        self.session_id: str | None = None
        self.protocol_version: str | None = None
        # Defaults preserve the GitHub target's behaviour. Other targets on the
        # same gateway pass their own tool manifest, tool prefix and target
        # headers, so a new target never widens this one's allowlist.
        self.tools = TOOLS if tools is None else frozenset(tools)
        self.tool_prefix = TARGET_PREFIX if tool_prefix is None else tool_prefix
        self.extra_headers = {"X-MCP-Tools": GITHUB_TOOL_FILTER_VALUE} if extra_headers is None else dict(extra_headers)

    @staticmethod
    def _json_rpc_error(message_id: Any, code: int, message: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": message_id, "error": {"code": code, "message": message}}

    def _remember_protocol(self, request: dict[str, Any], response: dict[str, Any]) -> None:
        if request.get("method") == "initialize":
            result = response.get("result")
            version = result.get("protocolVersion") if isinstance(result, dict) else None
            if not isinstance(version, str) or not version:
                raise AdapterError("invalid_gateway_response")
            self.protocol_version = version

    def _send(self, message: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, str]]:
        body = json.dumps(message, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        if len(body) > MAX_LINE_BYTES:
            raise AdapterError("request_too_large")
        for attempt in range(2):
            token = self.tokens.get(force_refresh=attempt == 1)
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            }
            # AgentCore forwards only per-target allowlisted headers. The GitHub
            # toolset filter goes to GitHub; the AWS target gets no extra header.
            headers.update(self.extra_headers)
            if self.protocol_version and message.get("method") != "initialize":
                headers["MCP-Protocol-Version"] = self.protocol_version
            if self.session_id:
                headers["Mcp-Session-Id"] = self.session_id
            response = self.transport.request(self.gateway_url, "POST", headers, body)
            if response.status == 401:
                self.tokens.invalidate(token)
                if attempt == 0:
                    continue
                raise AdapterError("gateway_authentication_failure")
            if response.status == 202 and message.get("method", "").startswith("notifications/"):
                return None, response.headers
            if response.status != 200:
                raise AdapterError("gateway_request_failure")
            session = response.headers.get("mcp-session-id")
            if session:
                self.session_id = session
            content_type = response.headers.get("content-type", "").lower()
            if "text/event-stream" in content_type:
                candidates = []
                for line in response.body.decode("utf-8").splitlines():
                    if line.startswith("data:"):
                        raw = line[5:].strip()
                        if raw:
                            try:
                                candidates.append(json.loads(raw))
                            except json.JSONDecodeError:
                                raise AdapterError("invalid_gateway_response") from None
                for item in reversed(candidates):
                    if isinstance(item, dict) and item.get("id") == message.get("id"):
                        self._remember_protocol(message, item)
                        return item, response.headers
                raise AdapterError("invalid_gateway_response")
            try:
                document = json.loads(response.body.decode("utf-8"))
            except Exception:
                raise AdapterError("invalid_gateway_response") from None
            if not isinstance(document, dict):
                raise AdapterError("invalid_gateway_response")
            self._remember_protocol(message, document)
            return document, response.headers
        raise AdapterError("gateway_authentication_failure")

    def handle(self, message: Any) -> dict[str, Any] | None:
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
            return self._json_rpc_error(message.get("id") if isinstance(message, dict) else None, -32600, "Invalid request")
        method = message["method"]
        if method not in {"initialize", "notifications/initialized", "tools/list", "tools/call", "ping"}:
            return self._json_rpc_error(message.get("id"), -32601, "Method not allowed")
        forwarded = dict(message)
        params = message.get("params", {})
        if method == "tools/call":
            if not isinstance(params, dict) or not isinstance(params.get("name"), str) or params["name"] not in self.tools:
                return self._json_rpc_error(message.get("id"), -32602, "Tool not allowed")
            forwarded_params = dict(params)
            forwarded_params["name"] = self.tool_prefix + params["name"]
            forwarded["params"] = forwarded_params
        try:
            response, _ = self._send(forwarded)
            if response is None or "id" not in message:
                return None
            if response.get("error"):
                return response
            if method == "tools/list":
                result = response.get("result")
                tools = result.get("tools") if isinstance(result, dict) else None
                if not isinstance(result, dict) or not isinstance(tools, list):
                    raise AdapterError("invalid_gateway_response")
                safe_tools = []
                for tool in tools:
                    if not isinstance(tool, dict) or not isinstance(tool.get("name"), str):
                        raise AdapterError("invalid_gateway_response")
                    name = tool["name"]
                    if not name.startswith(self.tool_prefix):
                        raise AdapterError("gateway_tool_set_mismatch")
                    logical_name = name[len(self.tool_prefix):]
                    # Expose only this target's manifest allowlist, even if the
                    # gateway or upstream returns additional tools.
                    if logical_name not in self.tools:
                        continue
                    exposed = dict(tool)
                    exposed["name"] = logical_name
                    safe_tools.append(exposed)
                if {tool["name"] for tool in safe_tools} != self.tools or len(safe_tools) != len(self.tools):
                    raise AdapterError("gateway_tool_set_mismatch")
                output = dict(result)
                output["tools"] = safe_tools
                response = dict(response)
                response["result"] = output
            return response
        except AdapterError as error:
            if "id" not in message:
                return None
            return self._json_rpc_error(message.get("id"), -32000, error.category)


def _load_forwarder() -> AgentCoreForwarder:
    return AgentCoreForwarder(
        gateway_url=os.environ.get("HERMES_GITHUB_GATEWAY_URL", ""),
        token_url=os.environ.get("HERMES_GITHUB_COGNITO_TOKEN_URL", ""),
        client_id=os.environ.get("HERMES_GITHUB_COGNITO_CLIENT_ID", ""),
        client_secret=os.environ.get("HERMES_GITHUB_COGNITO_CLIENT_SECRET", ""),
    )


def serve(stdin=None, stdout=None, forwarder=None) -> None:
    stdin = stdin or sys.stdin.buffer
    stdout = stdout or sys.stdout.buffer
    try:
        client = forwarder or _load_forwarder()
    except AdapterError as error:
        print(error.category, file=sys.stderr)
        return
    while True:
        line = stdin.readline(MAX_LINE_BYTES + 1)
        if not line:
            return
        if len(line) > MAX_LINE_BYTES:
            response = AgentCoreForwarder._json_rpc_error(None, -32000, "request_too_large")
        else:
            try:
                request = json.loads(line)
                response = client.handle(request)
            except json.JSONDecodeError:
                response = AgentCoreForwarder._json_rpc_error(None, -32700, "Parse error")
            except Exception:
                response = AgentCoreForwarder._json_rpc_error(None, -32000, "adapter_failure")
        if response is not None:
            try:
                stdout.write(json.dumps(response, separators=(",", ":"), ensure_ascii=False).encode("utf-8") + b"\n")
                stdout.flush()
            except Exception:
                return


if __name__ == "__main__":
    serve()
