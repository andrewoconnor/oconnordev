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


def _require_result(response, label: str) -> dict:
    if not isinstance(response, dict):
        raise SmokeCheckError(f"{label} returned no JSON-RPC response")
    if "error" in response:
        error = response.get("error")
        raise SmokeCheckError(f"{label} returned JSON-RPC error: {error}")
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


def run_gateway_checks(forwarder, per_target: dict[str, set[str]], github_owner: str, github_repo: str) -> list[str]:
    """Exercise discovery, safe reads on every target, and non-mutating scope denials."""
    expected = set().union(*per_target.values()) if per_target else set()
    initialized = forwarder.handle(_json_rpc(1, "initialize", {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "adapter-smoke-test", "version": "1"},
    }))
    init_result = _require_result(initialized, "gateway initialize")
    if not isinstance(init_result.get("protocolVersion"), str):
        raise SmokeCheckError("gateway initialize returned no MCP protocol version")
    forwarder.handle({"jsonrpc": "2.0", "method": "notifications/initialized"})

    listing = _require_result(forwarder.handle(_json_rpc(2, "tools/list")), "gateway tools/list")
    tools = listing.get("tools")
    if not isinstance(tools, list):
        raise SmokeCheckError("gateway tools/list returned no tools array")
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
        result = forwarder.handle(_json_rpc(message_id, "tools/call", {"name": tool, "arguments": arguments}))
        response = _require_result(result, f"{target_name} read-only smoke call {tool}")
        if response.get("isError") is True:
            raise SmokeCheckError(f"{target_name} read-only smoke call failed: {tool}")
        if "content" not in response and "structuredContent" not in response:
            raise SmokeCheckError(f"{target_name} read-only smoke call returned no result payload: {tool}")
        messages.append(f"PASS: {target_name} read-only tool call {tool}")
        message_id += 1

    github_tool = READ_ONLY_SMOKE_TOOLS["github"]
    probes = (
        ("owner outside the allowed scope", {"owner": INVALID_OWNER_PROBE, "repo": github_repo, "path": "README.md"}),
        ("repository outside the allowed scope", {"owner": github_owner, "repo": INVALID_REPOSITORY_PROBE, "path": "README.md"}),
    )
    for description, arguments in probes:
        response = forwarder.handle(_json_rpc(message_id, "tools/call", {"name": github_tool, "arguments": arguments}))
        if not _is_policy_denial(response):
            raise SmokeCheckError(f"GitHub request for {description} was not confirmed as an authorization denial")
        messages.append(f"PASS: GitHub request for {description} was denied by policy")
        message_id += 1
    return messages
