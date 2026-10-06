"""Pure validation logic for the opt-in AgentCore gateway smoke test."""

from __future__ import annotations

import re

EXPECTED_LIVE_ENV = (
    "HERMES_AGENTCORE_GATEWAY_URL",
    "HERMES_AGENTCORE_COGNITO_TOKEN_URL",
    "HERMES_AGENTCORE_COGNITO_CLIENT_ID",
    "HERMES_AGENTCORE_COGNITO_CLIENT_SECRET",
)
READ_ONLY_SMOKE_TOOLS = {
    "github": "get_file_contents",
    "aws": "aws___list_regions",
    "spacelift": "discover",
}
INVALID_OWNER_PROBE = "__hermes_scope_probe__"
INVALID_REPOSITORY_PROBE = "."


class SmokeCheckError(RuntimeError):
    """A live check ran but did not verify its expected result."""


def missing_live_configuration(environ, *, github_owner: str | None, github_repo: str | None) -> list[str]:
    """Names of required settings missing for a live run; values are never returned."""
    missing = [name for name in EXPECTED_LIVE_ENV if not isinstance(environ.get(name), str) or not environ[name].strip()]
    configured_owner = github_owner if github_owner is not None else environ.get("HERMES_SMOKE_GITHUB_OWNER", "")
    configured_repo = github_repo if github_repo is not None else environ.get("HERMES_SMOKE_GITHUB_REPO", "")
    if not str(configured_owner).strip():
        missing.append("HERMES_SMOKE_GITHUB_OWNER")
    if not str(configured_repo).strip():
        missing.append("HERMES_SMOKE_GITHUB_REPO")
    return missing


def build_read_only_calls(per_target: dict[str, set[str]], github_owner: str, github_repo: str) -> dict[str, tuple[str, dict]]:
    """Choose one allowlisted read-only call for every configured target."""
    if "github" not in per_target:
        raise SmokeCheckError("GitHub target is required for the owner/repository authorization probes")
    if not github_owner.strip() or not github_repo.strip():
        raise SmokeCheckError("GitHub smoke owner and repository must be configured")

    calls: dict[str, tuple[str, dict]] = {}
    for target_name, tools in per_target.items():
        tool = READ_ONLY_SMOKE_TOOLS.get(target_name)
        if tool is None or tool not in tools:
            raise SmokeCheckError(f"no safe read-only smoke tool is configured for target {target_name!r}")
        arguments = {"owner": github_owner, "repo": github_repo, "path": "README.md"} if target_name == "github" else {}
        calls[target_name] = (tool, arguments)
    return calls


def _json_rpc(message_id: int, method: str, params: dict | None = None) -> dict:
    request = {"jsonrpc": "2.0", "id": message_id, "method": method}
    if params is not None:
        request["params"] = params
    return request


def _known_sensitive_values(forwarder=None, additional=()):
    values = [value for value in additional if isinstance(value, str) and value]
    token_cache = getattr(forwarder, "tokens", None)
    for name in ("client_id", "client_secret", "_token"):
        value = getattr(token_cache, name, None)
        if isinstance(value, str) and value:
            values.append(value)
    return sorted(set(values), key=len, reverse=True)


def sanitize_diagnostic(value, *, forwarder=None, sensitive_values=()) -> str:
    """Return a bounded diagnostic with known secrets and token-shaped values redacted."""
    if not isinstance(value, str):
        return ""
    text = " ".join(value.split())
    for secret in _known_sensitive_values(forwarder, sensitive_values):
        text = text.replace(secret, "[REDACTED]")
    text = re.sub(r"(?i)\b(Bearer|Basic)\s+[^\s,;\"']+", lambda match: f"{match.group(1)} [REDACTED]", text)
    text = re.sub(
        r"(?i)\b(access[_ -]?token|refresh[_ -]?token|client[_ -]?secret|client[_ -]?id|authorization)\s*[:=]\s*[^\s,;\"']+",
        lambda match: f"{match.group(1)}=[REDACTED]",
        text,
    )
    text = re.sub(r"(?<![A-Za-z0-9_-])(?:eyJ[A-Za-z0-9_-]{8,}\.){2}[A-Za-z0-9_-]{8,}(?![A-Za-z0-9_-])", "[REDACTED]", text)
    text = re.sub(r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{32,}(?![A-Za-z0-9_-])", "[REDACTED]", text)
    text = re.sub(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b", "[REDACTED]", text)
    return text[:240]


def _response_error_detail(response, *, forwarder=None, sensitive_values=()) -> str:
    if not isinstance(response, dict):
        return ""
    error = response.get("error")
    if isinstance(error, dict):
        code = error.get("code")
        label = f"JSON-RPC error {code}" if isinstance(code, int) and not isinstance(code, bool) else "JSON-RPC error"
        detail = sanitize_diagnostic(error.get("message"), forwarder=forwarder, sensitive_values=sensitive_values)
        return f"{label}: {detail}" if detail else label
    result = response.get("result")
    if isinstance(result, dict) and result.get("isError") is True:
        parts = []
        content = result.get("content")
        if isinstance(content, list):
            parts.extend(item["text"] for item in content if isinstance(item, dict) and isinstance(item.get("text"), str))
        structured = result.get("structuredContent")
        if isinstance(structured, dict) and isinstance(structured.get("message"), str):
            parts.append(structured["message"])
        detail = sanitize_diagnostic(" ".join(parts), forwarder=forwarder, sensitive_values=sensitive_values)
        return f"tool returned isError: {detail}" if detail else "tool returned isError"
    return ""


def _call_forwarder(forwarder, message, label, sensitive_values=()):
    try:
        return forwarder.handle(message)
    except Exception as error:
        detail = sanitize_diagnostic(str(error), forwarder=forwarder, sensitive_values=sensitive_values)
        raise SmokeCheckError(f"{label} raised {detail or type(error).__name__}") from None


def _require_result(response, label: str, *, forwarder=None, sensitive_values=()) -> dict:
    if not isinstance(response, dict):
        raise SmokeCheckError(f"{label} returned no JSON-RPC response")
    if "error" in response:
        detail = _response_error_detail(response, forwarder=forwarder, sensitive_values=sensitive_values)
        raise SmokeCheckError(f"{label} failed: {detail or 'JSON-RPC error'}")
    result = response.get("result")
    if not isinstance(result, dict):
        raise SmokeCheckError(f"{label} returned no result")
    return result


def _is_policy_denial(response) -> bool:
    """Recognize AgentCore policy denials, whether top-level or in a tool result."""
    if not isinstance(response, dict):
        return False
    denial_pattern = r"AuthorizeActionException|Tool Execution Denied|policy enforcement"
    error = response.get("error")
    if isinstance(error, dict) and re.search(denial_pattern, str(error), re.IGNORECASE):
        return True
    result = response.get("result")
    if not isinstance(result, dict) or result.get("isError") is not True:
        return False
    return bool(re.search(denial_pattern, str(result), re.IGNORECASE))


def run_gateway_checks(forwarder, per_target: dict[str, set[str]], github_owner: str, github_repo: str, *, sensitive_values=()) -> list[str]:
    """Exercise discovery, safe reads on every target, and non-mutating scope denials."""
    expected = set().union(*per_target.values()) if per_target else set()
    initialize_label = "gateway initialize"
    initialized = _call_forwarder(forwarder, _json_rpc(1, "initialize", {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "adapter-smoke-test", "version": "1"},
    }), initialize_label, sensitive_values)
    init_result = _require_result(initialized, initialize_label, forwarder=forwarder, sensitive_values=sensitive_values)
    if not isinstance(init_result.get("protocolVersion"), str):
        raise SmokeCheckError(f"{initialize_label} returned no MCP protocol version")
    _call_forwarder(forwarder, {"jsonrpc": "2.0", "method": "notifications/initialized"}, "gateway initialized notification", sensitive_values)

    listing_label = "gateway tools/list"
    listing_response = _call_forwarder(forwarder, _json_rpc(2, "tools/list"), listing_label, sensitive_values)
    listing = _require_result(listing_response, listing_label, forwarder=forwarder, sensitive_values=sensitive_values)
    tools = listing.get("tools")
    if not isinstance(tools, list):
        raise SmokeCheckError(f"{listing_label} returned no tools array")
    discovered: set[str] = set()
    tool_specs: dict[str, dict] = {}
    for tool in tools:
        if isinstance(tool, dict) and isinstance(tool.get("name"), str):
            discovered.add(tool["name"])
            tool_specs[tool["name"]] = tool
    if discovered != expected:
        missing = sorted(expected - discovered)
        unexpected = sorted(discovered - expected)
        raise SmokeCheckError(f"gateway discovery mismatch (missing: {missing}; unexpected: {unexpected})")

    messages = [f"PASS: gateway discovery matched {len(expected)} manifest tools"]
    calls = build_read_only_calls(per_target, github_owner, github_repo)
    for target_name, (tool, arguments) in calls.items():
        input_schema = tool_specs[tool].get("inputSchema")
        required = input_schema.get("required", []) if isinstance(input_schema, dict) else None
        if not isinstance(required, list) or any(not isinstance(name, str) for name in required):
            raise SmokeCheckError(f"{target_name} smoke tool {tool} has no usable input schema")
        missing_arguments = sorted(set(required) - set(arguments))
        if missing_arguments:
            raise SmokeCheckError(f"{target_name} smoke tool {tool} requires unconfigured inputs: {missing_arguments}")

    message_id = 3
    for target_name, (tool, arguments) in sorted(calls.items()):
        label = f"{target_name} read-only smoke call {tool}"
        result = _call_forwarder(forwarder, _json_rpc(message_id, "tools/call", {"name": tool, "arguments": arguments}), label, sensitive_values)
        response = _require_result(result, label, forwarder=forwarder, sensitive_values=sensitive_values)
        if response.get("isError") is True:
            detail = _response_error_detail({"result": response}, forwarder=forwarder, sensitive_values=sensitive_values)
            raise SmokeCheckError(f"{label} failed: {detail or 'tool reported an error'}")
        if "content" not in response and "structuredContent" not in response:
            raise SmokeCheckError(f"{label} returned no result payload")
        messages.append(f"PASS: {label}")
        message_id += 1

    github_tool = READ_ONLY_SMOKE_TOOLS["github"]
    probes = (
        ("owner outside the allowed scope", {"owner": INVALID_OWNER_PROBE, "repo": github_repo, "path": "README.md"}),
        ("repository outside the allowed scope", {"owner": github_owner, "repo": INVALID_REPOSITORY_PROBE, "path": "README.md"}),
    )
    for description, arguments in probes:
        label = f"GitHub request for {description}"
        response = _call_forwarder(forwarder, _json_rpc(message_id, "tools/call", {"name": github_tool, "arguments": arguments}), label, sensitive_values)
        if not _is_policy_denial(response):
            detail = _response_error_detail(response, forwarder=forwarder, sensitive_values=sensitive_values)
            suffix = f": {detail}" if detail else ""
            raise SmokeCheckError(f"{label} was not confirmed as an authorization denial{suffix}")
        messages.append(f"PASS: {label} was denied by policy")
        message_id += 1
    return messages
