import importlib
import json
import sys
import unittest
from pathlib import Path

from scripts.gateway_validation import (
    INVALID_OWNER_PROBE,
    INVALID_REPOSITORY_PROBE,
    SmokeCheckError,
    run_gateway_checks,
)


class MockGatewayTransport:
    """Serve representative AgentCore JSON-RPC responses without network access."""

    gateway_url = "https://mcp.oconnor.dev/mcp"
    token_url = "https://pool.auth.us-east-1.amazoncognito.com/oauth2/token"
    client_id = "smoke-test-client-id-98765"
    client_secret = "smoke-test-client-secret-54321"
    access_token = "smoke-test-access-token-123456789"

    def __init__(self, *, read_error=None):
        self.read_error = read_error
        self.gateway_messages = []

    def request(self, url, method, headers, body):
        http_response = sys.modules["hermes_agentcore_adapter"].HttpResponse
        if url == self.token_url:
            token = {"access_token": self.access_token, "expires_in": 300, "token_type": "Bearer"}
            return http_response(200, {"content-type": "application/json"}, json.dumps(token).encode())

        message = json.loads(body)
        self.gateway_messages.append(message)
        response = {"jsonrpc": "2.0", "id": message.get("id")}
        if message["method"] == "notifications/initialized":
            return http_response(202, {}, b"")
        if message["method"] == "initialize":
            response["result"] = {"protocolVersion": "2025-03-26", "capabilities": {}}
        elif message["method"] == "tools/list":
            response["result"] = {"tools": [{
                "name": "github___get_file_contents",
                "inputSchema": {"type": "object", "required": ["owner", "repo", "path"]},
            }]}
        elif message["method"] == "tools/call":
            arguments = message["params"]["arguments"]
            if arguments.get("owner") == INVALID_OWNER_PROBE:
                response["error"] = {
                    "code": -32002,
                    "message": "Tool Execution Denied: Tool call not allowed due to policy enforcement",
                    "data": {"type": "AuthorizeActionException"},
                }
            elif arguments.get("repo") == INVALID_REPOSITORY_PROBE:
                response["result"] = {
                    "isError": True,
                    "content": [{"type": "text", "text": "AuthorizeActionException: policy enforcement denied request"}],
                }
            elif self.read_error is not None:
                response.update(self.read_error)
            else:
                response["result"] = {"content": [{"type": "text", "text": "safe read"}]}
        return http_response(
            200,
            {"content-type": "application/json", "mcp-session-id": "smoke-session"},
            json.dumps(response).encode(),
        )


class RealAdapterGatewayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        adapter_root = Path(__file__).resolve().parents[1] / "agents" / "hermes" / "adapter"
        sys.path.insert(0, str(adapter_root))
        cls.adapter = importlib.import_module("hermes_agentcore_adapter")

    def make_forwarder(self, transport):
        target = self.adapter.Target("github", frozenset({"get_file_contents"}), {})
        return self.adapter.AgentCoreForwarder(
            transport.gateway_url,
            transport.token_url,
            transport.client_id,
            transport.client_secret,
            transport=transport,
            targets=(target,),
        )

    def test_gateway_authorization_denials_pass_through_real_adapter(self):
        transport = MockGatewayTransport()
        forwarder = self.make_forwarder(transport)
        messages = run_gateway_checks(forwarder, {"github": {"get_file_contents"}}, "andrewoconnor", "oconnordev")
        self.assertEqual(sum("was denied by policy" in message for message in messages), 2)
        calls = [message for message in transport.gateway_messages if message["method"] == "tools/call"]
        self.assertEqual(len(calls), 3)
        self.assertTrue(all(message["params"]["name"] == "github___get_file_contents" for message in calls))

    def test_read_error_detail_names_target_and_redacts_credentials_and_access_token(self):
        transport = MockGatewayTransport(read_error={
            "error": {
                "code": -32000,
                "message": f"upstream timeout client_id={MockGatewayTransport.client_id} client_secret={MockGatewayTransport.client_secret} Bearer {MockGatewayTransport.access_token}",
            },
        })
        forwarder = self.make_forwarder(transport)
        with self.assertRaises(SmokeCheckError) as caught:
            run_gateway_checks(forwarder, {"github": {"get_file_contents"}}, "andrewoconnor", "oconnordev")
        detail = str(caught.exception)
        self.assertIn("github read-only smoke call get_file_contents", detail)
        self.assertIn("upstream timeout", detail)
        self.assertNotIn(transport.client_id, detail)
        self.assertNotIn(transport.client_secret, detail)
        self.assertNotIn(transport.access_token, detail)


if __name__ == "__main__":
    unittest.main()
