#!/usr/bin/env python3
"""Hermes stdio MCP adapter for the shared Cognito-protected AgentCore Gateway.

The gateway is not GitHub-specific. It fronts several targets, each with its own
tool namespace, allowlist and request headers, all behind one OAuth client and
one endpoint. This adapter is the single registration Hermes needs: it holds one
token for the gateway and presents every target's capability set through one
stdio server, so the same gateway is never registered twice under different
names.

Adding a target is one manifest plus one entry in TARGETS. A target can only
ever expose the tools its manifest names -- `tools/list` asserts the exposed set
equals the union of the manifests, and `tools/call` refuses any name no target
owns -- so a new target cannot widen an existing target's allowlist.
"""
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

MANIFEST_DIR = Path(__file__).resolve().parent
REQUIRED_SCOPE = "hermes-mcp/invoke"
# The gateway is fronted by CloudFront at this hostname. The AWS-issued
# *.gateway.bedrock-agentcore.<region>.amazonaws.com origin is still accepted;
# this is an additional host, not a replacement.
CLOUDFRONT_GATEWAY_HOSTNAME = "mcp.oconnor.dev"
MAX_LINE_BYTES = 1024 * 1024
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
# AgentCore pages `tools/list`. The page size is size-based rather than
# count-based, so the number of pages depends on how verbose the upstream tool
# descriptions are. This is a runaway guard, not an expected page count.
MAX_TOOL_LIST_PAGES = 20
CONNECT_TIMEOUT_SECONDS = 5
READ_TIMEOUT_SECONDS = 15
TOKEN_REFRESH_SKEW_SECONDS = 60


class AdapterError(Exception):
    def __init__(self, category: str):
        super().__init__(category)
        self.category = category


def _json_rpc_error(message_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "error": {"code": code, "message": message}}


def _validate_https_endpoint(value: str, kind: str) -> str:
    try:
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError
        if kind == "gateway":
            valid_host = parsed.hostname == CLOUDFRONT_GATEWAY_HOSTNAME or re.fullmatch(
                r"[a-z0-9-]+\.gateway\.bedrock-agentcore\.[a-z0-9-]+\.amazonaws\.com",
                parsed.hostname,
            )
            valid_path = parsed.path == "/mcp"
        else:
            valid_host = re.fullmatch(r"[a-z0-9-]+\.auth\.[a-z0-9-]+\.amazoncognito\.com", parsed.hostname)
            valid_path = parsed.path == "/oauth2/token"
        if not valid_host or not valid_path or parsed.port not in (None, 443):
            raise ValueError
    except (TypeError, ValueError):
        raise AdapterError("invalid_local_endpoint_configuration") from None
    return value


@dataclass(frozen=True)
class Target:
    """One AgentCore target: its tool namespace, allowlist and request headers.

    `tools` holds the logical names the client sees, which are the manifest's
    names. The gateway action name is this target's `prefix` plus a logical
    name, and the adapter strips exactly that one prefix.
    """

    name: str
    tools: frozenset[str]
    headers: dict[str, str]
    # The prefix AgentCore puts in front of a logical name on the wire. None
    # means the target's own name, which is the usual case.
    action_prefix: str | None = None

    @property
    def prefix(self) -> str:
        """The prefix AgentCore puts in front of a logical tool name.

        Normally the target's own name (`<name>___`). The AWS target overrides
        it. Its tools already carry the AWS MCP Server's own `aws___` namespace,
        and the security account's gateway prefixes its own target name on the
        way through, so the action on the wire is two levels deeper than the
        name the client sees. Declaring that in the manifest, rather than
        writing the nesting into the tool names, is what keeps the client's
        names canonical (`aws___run_script`) instead of leaking the number of
        gateways in the path into every name. Recording names without the full
        nesting is what previously produced unrecognized-action failures.

        The `___` separator means one target's prefix can never be a prefix of
        another's, so resolving an action name to a target is unambiguous.
        """
        return self.action_prefix or f"{self.name}___"


def _load_target(name: str, manifest_name: str, *, toolset_header: bool = False) -> Target:
    document = json.loads((MANIFEST_DIR / manifest_name).read_text(encoding="utf-8"))
    tools = frozenset(document["tools"])
    # The GitHub upstream accepts an X-MCP-Tools toolset filter; the AWS and
    # Spacelift targets want no extra request header. AgentCore forwards only
    # the headers a target allowlists, so a header sent for one target is not
    # sent for another. Spacelift narrows its own toolset in the target's URL
    # (`?tools=query,provider`), so it needs no header here.
    headers = {"X-MCP-Tools": ",".join(sorted(tools))} if toolset_header else {}
    # A manifest may declare the wire prefix explicitly, for a target whose
    # tools arrive through more than one gateway. It must end in the separator,
    # or action-name routing would silently mis-split.
    action_prefix = document.get("gateway_action_prefix")
    if action_prefix is not None and (not isinstance(action_prefix, str) or not action_prefix.endswith("___")):
        raise AdapterError("invalid_gateway_action_prefix")
    return Target(name=name, tools=tools, headers=headers, action_prefix=action_prefix)


TARGETS = (
    _load_target("github", "github-mcp-tools.json", toolset_header=True),
    _load_target("aws", "aws-mcp-tools.json"),
    _load_target("spacelift", "spacelift-mcp-tools.json"),
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


class AgentCoreForwarder:
    def __init__(
        self,
        gateway_url: str,
        token_url: str,
        client_id: str,
        client_secret: str,
        transport: Any | None = None,
        clock=time.monotonic,
        targets: Any = TARGETS,
    ):
        self.gateway_url = _validate_https_endpoint(gateway_url, "gateway")
        self.transport = transport or HttpsTransport()
        self.tokens = TokenCache(token_url, client_id, client_secret, self.transport, clock=clock)
        self.session_id: str | None = None
        self.protocol_version: str | None = None
        self.targets = tuple(targets)
        # One logical name, one owner. A name claimed twice would make routing
        # ambiguous and is a manifest error, not a runtime condition to guess at.
        self._owners: dict[str, Target] = {}
        for target in self.targets:
            for tool in target.tools:
                if tool in self._owners:
                    raise AdapterError("duplicate_tool_across_targets")
                self._owners[tool] = target

    def _target_for_action(self, action: str) -> Target | None:
        """The target that owns a gateway action name, by its `<name>___` prefix."""
        for target in self.targets:
            if action.startswith(target.prefix):
                return target
        return None

    def _send(self, message: dict[str, Any], extra_headers: dict[str, str] | None = None) -> tuple[dict[str, Any] | None, dict[str, str]]:
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
            # AgentCore forwards only per-target allowlisted headers, so a
            # request carries the headers of the target it addresses and no
            # others.
            headers.update(extra_headers or {})
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

    def _remember_protocol(self, request: dict[str, Any], response: dict[str, Any]) -> None:
        if request.get("method") == "initialize":
            result = response.get("result")
            version = result.get("protocolVersion") if isinstance(result, dict) else None
            if not isinstance(version, str) or not version:
                raise AdapterError("invalid_gateway_response")
            self.protocol_version = version

    def handle(self, message: Any) -> dict[str, Any] | None:
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
            return _json_rpc_error(message.get("id") if isinstance(message, dict) else None, -32600, "Invalid request")
        method = message["method"]
        if method not in {"initialize", "notifications/initialized", "tools/list", "tools/call", "ping"}:
            return _json_rpc_error(message.get("id"), -32601, "Method not allowed")
        forwarded = dict(message)
        target_headers: dict[str, str] | None = None
        if method == "tools/call":
            params = message.get("params")
            name = params.get("name") if isinstance(params, dict) else None
            target = self._owners.get(name) if isinstance(name, str) else None
            if target is None:
                return _json_rpc_error(message.get("id"), -32602, "Tool not allowed")
            forwarded["params"] = {**params, "name": target.prefix + name}
            target_headers = target.headers
        try:
            if method == "tools/list":
                return self._tools_list(message)
            response, _ = self._send(forwarded, target_headers)
            if response is None or "id" not in message:
                return None
            return response
        except AdapterError as error:
            if "id" not in message:
                return None
            return _json_rpc_error(message.get("id"), -32000, error.category)

    def _tools_list(self, message: dict[str, Any]) -> dict[str, Any] | None:
        """Return every target's manifest tools, paging the gateway to exhaustion.

        AgentCore pages `tools/list`: the result carries `nextCursor` alongside
        `tools`, and the page size is size-based, so the first page is not the
        tool set. Reading only the first page makes a complete catalog look
        partial -- the tools on the later pages are still callable, which is
        what makes that misread so convincing.

        The exposed set is still asserted equal to the union of the manifests,
        so paging cannot widen the allowlist and a target that fails to appear
        is a mismatch rather than a silently smaller catalog. Any cursor the
        client sends is ignored: this adapter never emits one, because it
        returns the whole set at once.
        """
        if "id" not in message:
            return None
        safe_tools: list[dict[str, Any]] = []
        seen: set[str] = set()
        first_response: dict[str, Any] | None = None
        result: dict[str, Any] = {}
        cursor: str | None = None
        for _ in range(MAX_TOOL_LIST_PAGES):
            page_request = dict(message)
            page_request["params"] = {"cursor": cursor} if cursor else {}
            page, _headers = self._send(page_request)
            if page is None:
                raise AdapterError("invalid_gateway_response")
            if page.get("error"):
                return page
            if first_response is None:
                first_response = page
            page_result = page.get("result")
            tools = page_result.get("tools") if isinstance(page_result, dict) else None
            if not isinstance(page_result, dict) or not isinstance(tools, list):
                raise AdapterError("invalid_gateway_response")
            result = page_result
            for tool in tools:
                if not isinstance(tool, dict) or not isinstance(tool.get("name"), str):
                    raise AdapterError("invalid_gateway_response")
                name = tool["name"]
                target = self._target_for_action(name)
                if target is None:
                    # A target this adapter does not register. Not an error and
                    # never exposed; the equality check below is what enforces
                    # the allowlist.
                    continue
                logical_name = name[len(target.prefix):]
                # Expose only the owning target's manifest allowlist, even if
                # the gateway or an upstream returns additional tools.
                if logical_name not in target.tools or logical_name in seen:
                    continue
                exposed = dict(tool)
                exposed["name"] = logical_name
                safe_tools.append(exposed)
                seen.add(logical_name)
            cursor = page_result.get("nextCursor")
            if not isinstance(cursor, str) or not cursor:
                break
        else:
            raise AdapterError("gateway_tool_pagination_limit")
        if seen != set(self._owners) or len(safe_tools) != len(self._owners):
            raise AdapterError("gateway_tool_set_mismatch")
        # Drop nextCursor: the client is being handed the complete set, so
        # there is nothing further to fetch.
        output = {key: value for key, value in result.items() if key != "nextCursor"}
        output["tools"] = safe_tools
        response = dict(first_response)
        response["result"] = output
        return response


def _load_forwarder() -> AgentCoreForwarder:
    return AgentCoreForwarder(
        gateway_url=os.environ.get("HERMES_AGENTCORE_GATEWAY_URL", ""),
        token_url=os.environ.get("HERMES_AGENTCORE_COGNITO_TOKEN_URL", ""),
        client_id=os.environ.get("HERMES_AGENTCORE_COGNITO_CLIENT_ID", ""),
        client_secret=os.environ.get("HERMES_AGENTCORE_COGNITO_CLIENT_SECRET", ""),
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
            response = _json_rpc_error(None, -32000, "request_too_large")
        else:
            try:
                request = json.loads(line)
                response = client.handle(request)
            except json.JSONDecodeError:
                response = _json_rpc_error(None, -32700, "Parse error")
            except Exception:
                response = _json_rpc_error(None, -32000, "adapter_failure")
        if response is not None:
            try:
                stdout.write(json.dumps(response, separators=(",", ":"), ensure_ascii=False).encode("utf-8") + b"\n")
                stdout.flush()
            except Exception:
                return


if __name__ == "__main__":
    serve()
