from __future__ import annotations

import json
import time
from typing import Any

from adapter_config import (
    MAX_LINE_BYTES,
    TARGETS,
    AdapterError,
    Target,
    _json_rpc_error,
    _validate_https_endpoint,
)
from adapter_tools_list import _ToolsListMixin
from adapter_transport import HttpsTransport, TokenCache


class AgentCoreForwarder(_ToolsListMixin):
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
        self.tokens = TokenCache(
            token_url, client_id, client_secret, self.transport, clock=clock
        )
        self.session_id: str | None = None
        self.protocol_version: str | None = None
        self.targets = tuple(targets)
        # One Hermes-visible name, one owner. A name claimed twice would make
        # routing ambiguous. Treat this as a manifest error, not something to
        # guess at at runtime.
        self._owners: dict[str, Target] = {}
        for target in self.targets:
            for tool in target.client_tools:
                if tool in self._owners:
                    raise AdapterError("duplicate_tool_across_targets")
                self._owners[tool] = target

    def _target_for_action(self, action: str) -> Target | None:
        """The target that owns a gateway action name, by its `<name>___` prefix."""
        for target in self.targets:
            if action.startswith(target.prefix):
                return target
        return None

    def _send(
        self, message: dict[str, Any], extra_headers: dict[str, str] | None = None
    ) -> tuple[dict[str, Any] | None, dict[str, str]]:
        body = json.dumps(message, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
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
            if response.status == 202 and message.get("method", "").startswith(
                "notifications/"
            ):
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

    def _remember_protocol(
        self, request: dict[str, Any], response: dict[str, Any]
    ) -> None:
        if request.get("method") == "initialize":
            result = response.get("result")
            version = (
                result.get("protocolVersion") if isinstance(result, dict) else None
            )
            if not isinstance(version, str) or not version:
                raise AdapterError("invalid_gateway_response")
            self.protocol_version = version

    def handle(self, message: Any) -> dict[str, Any] | None:
        if (
            not isinstance(message, dict)
            or message.get("jsonrpc") != "2.0"
            or not isinstance(message.get("method"), str)
        ):
            return _json_rpc_error(
                message.get("id") if isinstance(message, dict) else None,
                -32600,
                "Invalid request",
            )
        method = message["method"]
        if method not in {
            "initialize",
            "notifications/initialized",
            "tools/list",
            "tools/call",
            "ping",
        }:
            return _json_rpc_error(message.get("id"), -32601, "Method not allowed")
        forwarded = dict(message)
        target_headers: dict[str, str] | None = None
        if method == "tools/call":
            params = message.get("params")
            name = params.get("name") if isinstance(params, dict) else None
            if not isinstance(params, dict) or not isinstance(name, str):
                return _json_rpc_error(message.get("id"), -32602, "Tool not allowed")
            target = self._owners.get(name)
            if target is None:
                return _json_rpc_error(message.get("id"), -32602, "Tool not allowed")
            logical_name = (
                name[len(target.client_tool_prefix) :]
                if target.client_tool_prefix
                else name
            )
            forwarded["params"] = {**params, "name": target.prefix + logical_name}
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
