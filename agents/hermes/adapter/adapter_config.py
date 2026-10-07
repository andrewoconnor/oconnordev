from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

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
    return {
        "jsonrpc": "2.0",
        "id": message_id,
        "error": {"code": code, "message": message},
    }


def _validate_https_endpoint(value: str, kind: str) -> str:
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError
        if kind == "gateway":
            valid_host = parsed.hostname == CLOUDFRONT_GATEWAY_HOSTNAME or re.fullmatch(
                r"[a-z0-9-]+\.gateway\.bedrock-agentcore\.[a-z0-9-]+\.amazonaws\.com",
                parsed.hostname,
            )
            valid_path = parsed.path == "/mcp"
        else:
            valid_host = re.fullmatch(
                r"[a-z0-9-]+\.auth\.[a-z0-9-]+\.amazoncognito\.com", parsed.hostname
            )
            valid_path = parsed.path == "/oauth2/token"
        if not valid_host or not valid_path or parsed.port not in (None, 443):
            raise ValueError
    except (TypeError, ValueError):
        raise AdapterError("invalid_local_endpoint_configuration") from None
    return value


@dataclass(frozen=True)
class Target:
    """One AgentCore target: its tool namespace, allowlist and request headers.

    `tools` holds the upstream names after removing this target's gateway action
    prefix. `client_tool_prefix` is added to those names in Hermes' `tools/list`
    so overlapping tool names from different backends remain distinct. On a call,
    the adapter removes that client prefix and adds the gateway action prefix.
    """

    name: str
    tools: frozenset[str]
    headers: dict[str, str]
    # The prefix AgentCore puts in front of a logical name on the wire. None
    # means the target's own name, which is the usual case.
    action_prefix: str | None = None
    # Optional Hermes-facing namespace, separate from the upstream tool names.
    client_tool_prefix: str = ""

    @property
    def client_tools(self) -> frozenset[str]:
        return frozenset(f"{self.client_tool_prefix}{tool}" for tool in self.tools)

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


def _load_target(
    name: str, manifest_name: str, *, toolset_header: bool = False
) -> Target:
    document = json.loads((MANIFEST_DIR / manifest_name).read_text(encoding="utf-8"))
    tools = frozenset(document["tools"])
    # The GitHub upstream accepts an X-MCP-Tools toolset filter; the AWS and
    # Spacelift targets want no extra request header. AgentCore forwards only
    # the headers a target allowlists, so a header sent for one target is not
    # sent to another. Spacelift narrows its own toolset in the target's URL
    # (`?tools=query,provider`), so it needs no header here.
    headers = {"X-MCP-Tools": ",".join(sorted(tools))} if toolset_header else {}
    # A manifest may declare the wire prefix explicitly, for a target whose
    # tools arrive through more than one gateway. It must end in the separator,
    # or action-name routing would silently mis-split.
    action_prefix = document.get("gateway_action_prefix")
    if action_prefix is not None and (
        not isinstance(action_prefix, str) or not action_prefix.endswith("___")
    ):
        raise AdapterError("invalid_gateway_action_prefix")
    client_tool_prefix = document.get("client_tool_prefix", "")
    if not isinstance(client_tool_prefix, str) or (
        client_tool_prefix and not client_tool_prefix.endswith("___")
    ):
        raise AdapterError("invalid_client_tool_prefix")
    return Target(
        name=name,
        tools=tools,
        headers=headers,
        action_prefix=action_prefix,
        client_tool_prefix=client_tool_prefix,
    )


TARGETS = (
    _load_target("github", "github-mcp-tools.json", toolset_header=True),
    _load_target("aws", "aws-mcp-tools.json"),
    _load_target("spacelift", "spacelift-mcp-tools.json"),
)
