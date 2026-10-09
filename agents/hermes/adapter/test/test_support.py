import json
from urllib.parse import parse_qs

from hermes_agentcore_adapter import (
    REQUIRED_SCOPE,
    TARGETS,
    AgentCoreForwarder,
)

GATEWAY_URL = "https://gateway-id.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp"
CLOUDFRONT_GATEWAY_URL = "https://mcp.oconnor.dev/mcp"
TOKEN_URL = "https://pool.auth.us-east-1.amazoncognito.com/oauth2/token"

GITHUB_TOOLS = {
    "get_file_contents",
    "list_branches",
    "get_commit",
    "create_branch",
    "push_files",
    "delete_file",
    "create_pull_request",
    "pull_request_read",
    "get_job_logs",
    "repository_ruleset_read",
    "list_repository_collaborators",
    "list_label",
    "get_label",
}
# The client keeps the canonical AWS names even though these tools now arrive
# through two gateways. The extra hop lives in the manifest's declared wire
# prefix, not in the names Hermes sees.
AWS_TOOLS = {
    "aws___get_regional_availability",
    "aws___get_tasks",
    "aws___list_regions",
    "aws___read_documentation",
    "aws___retrieve_skill",
    "aws___run_script",
    "aws___search_documentation",
}
SPACELIFT_TOOLS = {
    "discover",
    "provider",
    "query",
}
EXPECTED_TOOLS = GITHUB_TOOLS | AWS_TOOLS | SPACELIFT_TOOLS
GITHUB_TARGET = next(target for target in TARGETS if target.name == "github")
AWS_TARGET = next(target for target in TARGETS if target.name == "aws")
SPACELIFT_TARGET = next(target for target in TARGETS if target.name == "spacelift")
EXPECTED_TOOL_HEADER = ",".join(sorted(GITHUB_TOOLS))


def _response(status, document, headers=None):
    return type(
        "Response",
        (),
        {
            "status": status,
            "headers": headers or {},
            "body": json.dumps(document).encode(),
        },
    )()


class FakeTransport:
    """Stands in for the gateway, serving every registered target's tools."""

    def __init__(self):
        self.token_calls = 0
        self.gateway_calls = []
        self.gateway_401_count = 0
        self.always_401 = False
        self.scope: object = REQUIRED_SCOPE
        self.omit_scope = False
        # Drop keys from the token response, or replace its body entirely with
        # raw bytes, to exercise the token-response validation path.
        self.token_drop: tuple[str, ...] = ()
        self.token_raw: bytes | None = None
        self.extra_tool = False
        self.missing_tool = False
        # 0 means "return every tool in one page", which is what the gateway
        # does not do. Set a page size to exercise the paging path.
        self.page_size = 0
        self.unregistered_target = False
        self.hide_target: str | None = None
        self.tokens = []

    def _catalog(self):
        names = []
        for target in TARGETS:
            if target.name == self.hide_target:
                continue
            names += [f"{target.prefix}{tool}" for tool in sorted(target.tools)]
        if self.extra_tool:
            names.append("github___dangerous_tool")
        if self.missing_tool:
            names.pop(0)
        if self.unregistered_target:
            names.append("slack___post_message")
        return sorted(names)

    def request(self, url, method, headers, body):
        if url == TOKEN_URL:
            self.token_calls += 1
            form = parse_qs(body.decode())
            assert form == {
                "grant_type": ["client_credentials"],
                "scope": [REQUIRED_SCOPE],
            }
            token = f"synthetic-access-token-{self.token_calls}"
            self.tokens.append(token)
            if self.token_raw is not None:
                return type(
                    "Response",
                    (),
                    {"status": 200, "headers": {}, "body": self.token_raw},
                )()
            response = {
                "access_token": token,
                "expires_in": 300,
                "token_type": "Bearer",
            }
            if not self.omit_scope:
                response["scope"] = self.scope
            for key in self.token_drop:
                response.pop(key, None)
            return _response(200, response)
        self.gateway_calls.append((url, method, headers.copy(), json.loads(body)))
        if self.always_401 or self.gateway_401_count > 0:
            if self.gateway_401_count > 0:
                self.gateway_401_count -= 1
            return _response(401, {})
        message = json.loads(body)
        if message["method"] == "tools/list":
            names = self._catalog()
            cursor = (message.get("params") or {}).get("cursor")
            if self.page_size:
                start = int(cursor) if cursor else 0
                window = names[start : start + self.page_size]
                following = start + self.page_size
                paged: dict = {
                    "tools": [{"name": name, "description": "safe"} for name in window]
                }
                if following < len(names):
                    paged["nextCursor"] = str(following)
                result = paged
            else:
                result = {
                    "tools": [{"name": name, "description": "safe"} for name in names]
                }
        elif message["method"] == "tools/call":
            result = {"content": [{"type": "text", "text": "safe"}]}
        else:
            result = {"protocolVersion": "2025-03-26", "capabilities": {}}
        return _response(
            200,
            {"jsonrpc": "2.0", "id": message.get("id"), "result": result},
            {"content-type": "application/json", "mcp-session-id": "session-1"},
        )


def make_forwarder(transport=None, **kwargs):
    return AgentCoreForwarder(
        GATEWAY_URL,
        TOKEN_URL,
        "client-id",
        "synthetic-client-secret",
        transport=transport or FakeTransport(),
        **kwargs,
    )


def rpc(method, params=None, message_id=1):
    message = {"jsonrpc": "2.0", "id": message_id, "method": method}
    if params is not None:
        message["params"] = params
    return message


def exposed_names(forwarder, params=None):
    result = forwarder.handle(rpc("tools/list", params))
    return {tool["name"] for tool in result["result"]["tools"]}


__all__ = [name for name in globals() if not name.startswith("__")]
