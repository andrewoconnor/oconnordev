import base64
import json
import unittest
from urllib.parse import parse_qs

from hermes_github_adapter import (
    AdapterError,
    AgentCoreForwarder,
    REQUIRED_SCOPE,
    TOOLS,
    TokenCache,
)

GATEWAY_URL = "https://gateway-id.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp"
TOKEN_URL = "https://pool.auth.us-east-1.amazoncognito.com/oauth2/token"


class FakeTransport:
    def __init__(self):
        self.token_calls = 0
        self.gateway_calls = []
        self.gateway_401_count = 0
        self.always_401 = False
        self.scope = REQUIRED_SCOPE
        self.omit_scope = False
        self.extra_tool = False
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
    def test_initial_token_acquisition_requests_client_credentials_and_exact_scope(self):
        transport = FakeTransport()
        forwarder = make_forwarder(transport)
        result = forwarder.handle(rpc("tools/call", {"name": "get_file_contents", "arguments": {"owner": "andrewoconnor", "repo": "sample", "path": "README.md"}}))
        self.assertEqual(result["result"]["content"][0]["text"], "safe")
        self.assertEqual(transport.token_calls, 1)
        token_body = transport.gateway_calls[0][3]
        self.assertEqual(token_body["params"]["name"], "github___get_file_contents")

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

    def test_wrong_or_missing_scope_is_rejected(self):
        for mode in ("wrong", "missing"):
            transport = FakeTransport()
            if mode == "wrong":
                transport.scope = "other/scope"
            else:
                transport.omit_scope = True
            forwarder = make_forwarder(transport)
            result = forwarder.handle(rpc("ping"))
            self.assertEqual(result["error"]["message"], "oauth_scope_mismatch")
            self.assertEqual(transport.gateway_calls, [])

    def test_only_official_tools_are_exposed_and_prefix_is_removed(self):
        expected = {"create_branch", "create_pull_request", "get_file_contents", "list_branches", "pull_request_read", "push_files"}
        self.assertEqual(TOOLS, expected)
        transport = FakeTransport()
        forwarder = make_forwarder(transport)
        result = forwarder.handle(rpc("tools/list"))
        names = {tool["name"] for tool in result["result"]["tools"]}
        self.assertEqual(names, TOOLS)
        self.assertEqual(len(names), 6)

    def test_unknown_methods_and_tools_are_rejected_without_forwarding(self):
        transport = FakeTransport()
        forwarder = make_forwarder(transport)
        self.assertEqual(forwarder.handle(rpc("resources/read"))["error"]["code"], -32601)
        self.assertEqual(forwarder.handle(rpc("tools/call", {"name": "graphql"}))["error"]["code"], -32602)
        self.assertEqual(transport.gateway_calls, [])

    def test_gateway_tool_set_mismatch_fails_closed(self):
        transport = FakeTransport()
        transport.extra_tool = True
        result = make_forwarder(transport).handle(rpc("tools/list"))
        self.assertEqual(result["error"]["message"], "gateway_tool_set_mismatch")

    def test_destination_cannot_be_overridden_by_tool_arguments(self):
        transport = FakeTransport()
        forwarder = make_forwarder(transport)
        forwarder.handle(rpc("tools/call", {"name": "get_file_contents", "arguments": {"owner": "andrewoconnor", "repo": "sample", "path": "README.md", "url": "https://evil.invalid"}}))
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
        response = forwarder.handle(rpc("tools/call", {"name": "get_file_contents", "arguments": {"owner": "andrewoconnor", "repo": "sample", "path": "README.md"}}))
        encoded = json.dumps(response)
        self.assertNotIn("synthetic-access-token", encoded)
        self.assertNotIn("synthetic-client-secret", encoded)


if __name__ == "__main__":
    unittest.main()
