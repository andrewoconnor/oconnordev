import base64
import json
import unittest
from urllib.parse import parse_qs

from hermes_github_adapter import (
    AdapterError,
    AgentCoreForwarder,
    GITHUB_TOOLS,
    GITHUB_TOOL_FILTER_VALUE,
    REQUIRED_SCOPE,
    TOOL_MANIFEST,
    TOOLS,
    TokenCache,
)

GATEWAY_URL = "https://gateway-id.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp"
CLOUDFRONT_GATEWAY_URL = "https://mcp.oconnor.dev/mcp"
TOKEN_URL = "https://pool.auth.us-east-1.amazoncognito.com/oauth2/token"
EXPECTED_TOOLS = {
    "get_file_contents",
    "list_branches",
    "get_commit",
    "create_branch",
    "push_files",
    "create_pull_request",
    "pull_request_read",
}
EXPECTED_TOOL_HEADER = ",".join(sorted(EXPECTED_TOOLS))


class FakeTransport:
    def __init__(self):
        self.token_calls = 0
        self.gateway_calls = []
        self.gateway_401_count = 0
        self.always_401 = False
        self.scope: object = REQUIRED_SCOPE
        self.omit_scope = False
        self.extra_tool = False
        self.missing_tool = False
        # 0 means "return every tool in one page", which is what the gateway
        # does not do. Set a page size to exercise the paging path.
        self.page_size = 0
        self.foreign_tools = False
        self.tokens = []

    def request(self, url, method, headers, body):
        if url == TOKEN_URL:
            self.token_calls += 1
            form = parse_qs(body.decode())
            assert form == {"grant_type": ["client_credentials"], "scope": [REQUIRED_SCOPE]}
            token = f"synthetic-access-token-{self.token_calls}"
            self.tokens.append(token)
            response = {"access_token": token, "expires_in": 300, "token_type": "Bearer"}
            if not self.omit_scope:
                response["scope"] = self.scope
            return _response(200, response)
        self.gateway_calls.append((url, method, headers.copy(), json.loads(body)))
        if self.always_401 or self.gateway_401_count > 0:
            if self.gateway_401_count > 0:
                self.gateway_401_count -= 1
            return _response(401, {})
        message = json.loads(body)
        if message["method"] == "tools/list":
            names = [f"github___{tool}" for tool in sorted(TOOLS)]
            if self.extra_tool:
                names.append("github___dangerous_tool")
            if self.missing_tool:
                names.pop(0)
            if self.foreign_tools:
                names = ["aws___aws___run_script", "aws___aws___list_regions"] + names
            cursor = (message.get("params") or {}).get("cursor")
            if self.page_size:
                start = int(cursor) if cursor else 0
                window = names[start:start + self.page_size]
                following = start + self.page_size
                paged: dict = {"tools": [{"name": name, "description": "safe"} for name in window]}
                if following < len(names):
                    paged["nextCursor"] = str(following)
                result = paged
            else:
                result = {"tools": [{"name": name, "description": "safe"} for name in names]}
        elif message["method"] == "tools/call":
            result = {"content": [{"type": "text", "text": "safe"}]}
        else:
            result = {"protocolVersion": "2025-03-26", "capabilities": {}}
        return _response(200, {"jsonrpc": "2.0", "id": message.get("id"), "result": result}, {"content-type": "application/json", "mcp-session-id": "session-1"})


def _response(status, document, headers=None):
    return type("Response", (), {"status": status, "headers": headers or {}, "body": json.dumps(document).encode()})()


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


class AdapterTests(unittest.TestCase):
    def test_required_scope_matches_generic_cognito_resource_server(self):
        self.assertEqual(REQUIRED_SCOPE, "hermes-mcp/invoke")

    def test_initial_token_acquisition_requests_client_credentials_and_exact_scope(self):
        transport = FakeTransport()
        forwarder = make_forwarder(transport)
        result = forwarder.handle(rpc("tools/call", {"name": "get_file_contents", "arguments": {"owner": "andrewoconnor", "repo": "sample", "path": "src/main.py"}}))
        self.assertEqual(result["result"]["content"][0]["text"], "safe")
        self.assertEqual(transport.token_calls, 1)
        token_body = transport.gateway_calls[0][3]
        self.assertEqual(token_body["params"]["name"], "github___get_file_contents")
        self.assertEqual(transport.gateway_calls[0][2]["X-MCP-Tools"], EXPECTED_TOOL_HEADER)

    def test_token_caching_reuses_token(self):
        transport = FakeTransport()
        now = [0.0]
        cache = TokenCache(TOKEN_URL, "id", "secret", transport, clock=lambda: now[0])
        first = cache.get()
        now[0] = 30.0
        second = cache.get()
        self.assertEqual(first, second)
        self.assertEqual(transport.token_calls, 1)

    def test_proactive_refresh_before_expiration(self):
        transport = FakeTransport()
        now = [0.0]
        cache = TokenCache(TOKEN_URL, "id", "secret", transport, clock=lambda: now[0])
        first = cache.get()
        now[0] = 241.0
        second = cache.get()
        self.assertNotEqual(first, second)
        self.assertEqual(transport.token_calls, 2)

    def test_401_refreshes_once_and_retries_once(self):
        transport = FakeTransport()
        transport.gateway_401_count = 1
        forwarder = make_forwarder(transport)
        result = forwarder.handle(rpc("ping"))
        self.assertIn("result", result)
        self.assertEqual(transport.token_calls, 2)
        self.assertEqual(len(transport.gateway_calls), 2)
        self.assertNotEqual(transport.gateway_calls[0][2]["Authorization"], transport.gateway_calls[1][2]["Authorization"])

    def test_repeated_401_fails_closed(self):
        transport = FakeTransport()
        transport.always_401 = True
        forwarder = make_forwarder(transport)
        result = forwarder.handle(rpc("ping"))
        self.assertEqual(result["error"]["message"], "gateway_authentication_failure")
        self.assertEqual(transport.token_calls, 2)
        self.assertEqual(len(transport.gateway_calls), 2)

    def test_wrong_scope_is_rejected(self):
        for bad in ("other/scope", "hermes-mcp/invoke hermes-mcp/other", "", 7):
            transport = FakeTransport()
            transport.scope = bad
            forwarder = make_forwarder(transport)
            result = forwarder.handle(rpc("ping"))
            self.assertEqual(result["error"]["message"], "oauth_scope_mismatch")
            self.assertEqual(transport.gateway_calls, [])

    def test_absent_scope_is_accepted(self):
        # RFC 6749 section 5.1 makes the response `scope` field OPTIONAL when the
        # granted scope is identical to the requested one. Cognito omits it for
        # this client, so requiring the echo rejected every real token.
        transport = FakeTransport()
        transport.omit_scope = True
        forwarder = make_forwarder(transport)
        result = forwarder.handle(rpc("ping"))
        self.assertIsNotNone(result)
        self.assertNotIn("error", result)
        self.assertEqual(len(transport.gateway_calls), 1)

    def test_cloudfront_gateway_endpoint_is_accepted(self):
        transport = FakeTransport()
        forwarder = AgentCoreForwarder(CLOUDFRONT_GATEWAY_URL, TOKEN_URL, "id", "secret", transport)
        result = forwarder.handle(rpc("ping"))
        self.assertIsNotNone(result)
        self.assertNotIn("error", result)
        self.assertEqual(transport.gateway_calls[0][0], CLOUDFRONT_GATEWAY_URL)

    def test_endpoint_validation_still_rejects_anything_else(self):
        for url in (
            "https://mcp.oconnor.dev.evil.com/mcp",
            "https://evil.com/mcp",
            "https://mcp.oconnor.dev/notmcp",
            "https://mcp.oconnor.dev/mcp/",
            "http://mcp.oconnor.dev/mcp",
            "https://mcp.oconnor.dev:8443/mcp",
            "https://gateway-id.gateway.bedrock-agentcore.us-east-1.amazonaws.com.evil.com/mcp",
            "https://user@mcp.oconnor.dev/mcp",
            "https://mcp.oconnor.dev/mcp?x=1",
        ):
            with self.assertRaises(AdapterError, msg=url):
                AgentCoreForwarder(url, TOKEN_URL, "id", "secret", FakeTransport())

    def test_allowlist_matches_verified_official_tool_names(self):
        self.assertEqual(TOOLS, EXPECTED_TOOLS)
        self.assertEqual(set(GITHUB_TOOLS), EXPECTED_TOOLS)
        self.assertEqual(len(GITHUB_TOOLS), len(EXPECTED_TOOLS))
        self.assertEqual(GITHUB_TOOL_FILTER_VALUE, EXPECTED_TOOL_HEADER)
        self.assertEqual(TOOL_MANIFEST["upstream_commit"], "85598ba6e1256f7ebf4867b95d63b833c4549264")

    def test_only_exact_official_tools_are_exposed_and_prefix_is_removed(self):
        transport = FakeTransport()
        transport.extra_tool = True
        forwarder = make_forwarder(transport)
        result = forwarder.handle(rpc("tools/list"))
        names = {tool["name"] for tool in result["result"]["tools"]}
        self.assertEqual(names, EXPECTED_TOOLS)
        self.assertEqual(len(names), 7)
        self.assertEqual(transport.gateway_calls[0][2]["X-MCP-Tools"], EXPECTED_TOOL_HEADER)

    def test_unknown_methods_and_tools_are_rejected_without_forwarding(self):
        transport = FakeTransport()
        forwarder = make_forwarder(transport)
        self.assertEqual(forwarder.handle(rpc("resources/read"))["error"]["code"], -32601)
        self.assertEqual(forwarder.handle(rpc("tools/call", {"name": "repository_info"}))["error"]["code"], -32602)
        self.assertEqual(transport.gateway_calls, [])

    def test_gateway_tool_set_mismatch_fails_closed(self):
        transport = FakeTransport()
        transport.missing_tool = True
        result = make_forwarder(transport).handle(rpc("tools/list"))
        self.assertEqual(result["error"]["message"], "gateway_tool_set_mismatch")

    def test_tools_list_pages_the_gateway_to_exhaustion(self):
        transport = FakeTransport()
        transport.page_size = 3
        result = make_forwarder(transport).handle(rpc("tools/list"))
        names = {tool["name"] for tool in result["result"]["tools"]}
        self.assertEqual(names, EXPECTED_TOOLS)
        # Seven tools over pages of three, so three gateway calls, and the
        # paging cursor must not be handed on to the client.
        self.assertEqual(len(transport.gateway_calls), 3)
        self.assertNotIn("nextCursor", result["result"])

    def test_paging_still_fails_closed_when_the_manifest_is_incomplete(self):
        transport = FakeTransport()
        transport.page_size = 3
        transport.missing_tool = True
        result = make_forwarder(transport).handle(rpc("tools/list"))
        self.assertEqual(result["error"]["message"], "gateway_tool_set_mismatch")

    def test_other_targets_on_the_shared_gateway_are_ignored_not_a_mismatch(self):
        transport = FakeTransport()
        transport.foreign_tools = True
        result = make_forwarder(transport).handle(rpc("tools/list"))
        self.assertNotIn("error", result)
        self.assertEqual({tool["name"] for tool in result["result"]["tools"]}, EXPECTED_TOOLS)

    def test_client_supplied_cursor_cannot_narrow_the_tool_set(self):
        transport = FakeTransport()
        transport.page_size = 3
        result = make_forwarder(transport).handle(rpc("tools/list", {"cursor": "3"}))
        self.assertEqual({tool["name"] for tool in result["result"]["tools"]}, EXPECTED_TOOLS)

    def test_destination_cannot_be_overridden_by_tool_arguments(self):
        transport = FakeTransport()
        forwarder = make_forwarder(transport)
        forwarder.handle(rpc("tools/call", {"name": "get_file_contents", "arguments": {"owner": "andrewoconnor", "repo": "sample", "path": "src/main.py", "url": "https://evil.invalid"}}))
        self.assertEqual(transport.gateway_calls[0][0], GATEWAY_URL)
        self.assertEqual(len(transport.gateway_calls), 1)

    def test_invalid_gateway_or_token_endpoint_is_rejected(self):
        transport = FakeTransport()
        with self.assertRaises(AdapterError):
            AgentCoreForwarder("https://evil.invalid/mcp", TOKEN_URL, "id", "secret", transport)
        with self.assertRaises(AdapterError):
            AgentCoreForwarder(GATEWAY_URL, "https://evil.invalid/oauth2/token", "id", "secret", transport)

    def test_client_secret_and_tokens_are_not_in_json_rpc_responses(self):
        transport = FakeTransport()
        forwarder = make_forwarder(transport)
        response = forwarder.handle(rpc("tools/call", {"name": "get_file_contents", "arguments": {"owner": "andrewoconnor", "repo": "sample", "path": "src/main.py"}}))
        encoded = json.dumps(response)
        self.assertNotIn("synthetic-access-token", encoded)
        self.assertNotIn("synthetic-client-secret", encoded)


if __name__ == "__main__":
    unittest.main()
