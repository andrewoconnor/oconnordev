from .test_support import *

class EndpointTests(unittest.TestCase):
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
            "https://evil.oconnor.dev/mcp",
            "https://evil.com/mcp",
            "https://mcp.oconnor.dev/notmcp",
            "https://mcp.oconnor.dev/",
            "https://mcp.oconnor.dev/mcp/",
            "http://mcp.oconnor.dev/mcp",
            "https://mcp.oconnor.dev:8443/mcp",
            "https://gateway-id.gateway.bedrock-agentcore.us-east-1.amazonaws.com.evil.com/mcp",
            "https://user@mcp.oconnor.dev/mcp",
            "https://mcp.oconnor.dev/mcp?x=1",
        ):
            with self.assertRaises(AdapterError, msg=url):
                AgentCoreForwarder(url, TOKEN_URL, "id", "secret", FakeTransport())

    def test_invalid_token_endpoint_is_rejected(self):
        with self.assertRaises(AdapterError):
            AgentCoreForwarder(GATEWAY_URL, "https://evil.invalid/oauth2/token", "id", "secret", FakeTransport())

class EnvironmentTests(unittest.TestCase):
    def test_forwarder_reads_the_agentcore_namespaced_variables(self):
        env = {
            "HERMES_AGENTCORE_GATEWAY_URL": GATEWAY_URL,
            "HERMES_AGENTCORE_COGNITO_TOKEN_URL": TOKEN_URL,
            "HERMES_AGENTCORE_COGNITO_CLIENT_ID": "id",
            "HERMES_AGENTCORE_COGNITO_CLIENT_SECRET": "secret",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            forwarder = _load_forwarder()
        self.assertEqual(forwarder.targets, TARGETS)

    def test_forwarder_fails_closed_without_credentials(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(AdapterError):
                _load_forwarder()

    def test_client_secret_and_tokens_are_not_in_json_rpc_responses(self):
        transport = FakeTransport()
        forwarder = make_forwarder(transport)
        for name in ("get_file_contents", "aws___list_regions"):
            encoded = json.dumps(forwarder.handle(rpc("tools/call", {"name": name, "arguments": {}})))
            self.assertNotIn("synthetic-access-token", encoded)
            self.assertNotIn("synthetic-client-secret", encoded)


if __name__ == "__main__":
    unittest.main()
