import unittest

from adapter_forwarder import TokenCache

from .test_support import REQUIRED_SCOPE, TOKEN_URL, FakeTransport, make_forwarder, rpc


class TokenTests(unittest.TestCase):
    def test_required_scope_matches_generic_cognito_resource_server(self):
        self.assertEqual(REQUIRED_SCOPE, "hermes-mcp/invoke")

    def test_initial_token_acquisition_requests_client_credentials_and_exact_scope(
        self,
    ):
        transport = FakeTransport()
        make_forwarder(transport).handle(rpc("ping"))
        self.assertEqual(transport.token_calls, 1)

    def test_token_caching_reuses_token(self):
        transport = FakeTransport()
        now = [0.0]
        cache = TokenCache(TOKEN_URL, "id", "secret", transport, clock=lambda: now[0])
        first = cache.get()
        now[0] = 30.0
        self.assertEqual(first, cache.get())
        self.assertEqual(transport.token_calls, 1)

    def test_proactive_refresh_before_expiration(self):
        transport = FakeTransport()
        now = [0.0]
        cache = TokenCache(TOKEN_URL, "id", "secret", transport, clock=lambda: now[0])
        first = cache.get()
        now[0] = 241.0
        self.assertNotEqual(first, cache.get())
        self.assertEqual(transport.token_calls, 2)

    def test_401_refreshes_once_and_retries_once(self):
        transport = FakeTransport()
        transport.gateway_401_count = 1
        result = make_forwarder(transport).handle(rpc("ping"))
        self.assertIn("result", result)
        self.assertEqual(transport.token_calls, 2)
        self.assertEqual(len(transport.gateway_calls), 2)
        self.assertNotEqual(
            transport.gateway_calls[0][2]["Authorization"],
            transport.gateway_calls[1][2]["Authorization"],
        )

    def test_repeated_401_fails_closed(self):
        transport = FakeTransport()
        transport.always_401 = True
        result = make_forwarder(transport).handle(rpc("ping"))
        self.assertEqual(result["error"]["message"], "gateway_authentication_failure")
        self.assertEqual(transport.token_calls, 2)
        self.assertEqual(len(transport.gateway_calls), 2)

    def test_wrong_scope_is_rejected(self):
        for bad in ("other/scope", "hermes-mcp/invoke hermes-mcp/other", "", 7):
            transport = FakeTransport()
            transport.scope = bad
            result = make_forwarder(transport).handle(rpc("ping"))
            self.assertEqual(result["error"]["message"], "oauth_scope_mismatch", bad)
            self.assertEqual(transport.gateway_calls, [])

    def test_absent_scope_is_accepted(self):
        # RFC 6749 section 5.1 makes the response `scope` field OPTIONAL when the
        # granted scope is identical to the requested one. Cognito omits it for
        # this client, so requiring the echo rejected every real token.
        transport = FakeTransport()
        transport.omit_scope = True
        result = make_forwarder(transport).handle(rpc("ping"))
        self.assertIsNotNone(result)
        self.assertNotIn("error", result)
        self.assertEqual(len(transport.gateway_calls), 1)

    def test_token_response_without_access_token_is_rejected(self):
        transport = FakeTransport()
        transport.token_drop = ("access_token",)
        result = make_forwarder(transport).handle(rpc("ping"))
        self.assertEqual(result["error"]["message"], "invalid_token_response")
        self.assertEqual(transport.gateway_calls, [])

    def test_non_json_token_response_is_rejected(self):
        transport = FakeTransport()
        transport.token_raw = b"not-json"
        result = make_forwarder(transport).handle(rpc("ping"))
        self.assertEqual(result["error"]["message"], "invalid_token_response")
        self.assertEqual(transport.gateway_calls, [])
