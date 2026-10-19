import unittest

import adapter_config

from .test_support import FakeTransport, make_forwarder, rpc

RAW = {
    "getAccount",
    "getAccountNumbers",
    "getMarketHours",
    "getPriceHistory",
    "getQuotes",
    "listAccounts",
    "searchInstruments",
}
URL = "https://bedrock-agentcore.us-east-1.amazonaws.com/identities/oauth2/authorize?request_uri=x"


class SchwabTests(unittest.TestCase):
    def test_tools_route_and_order_tools_are_refused(self):
        schwab = next(t for t in adapter_config.TARGETS if t.name == "schwab")
        self.assertEqual(schwab.tools, RAW)
        transport = FakeTransport()
        client = make_forwarder(transport)
        for raw in RAW:
            client.handle(rpc("tools/call", {"name": "schwab-" + raw, "arguments": {}}))
            self.assertEqual(
                transport.gateway_calls[-1][3]["params"]["name"], "schwab___" + raw
            )
        for forbidden in ["schwab-placeOrder", "schwab-cancelOrder", "getQuotes"]:
            before = len(transport.gateway_calls)
            self.assertIn(
                "error", client.handle(rpc("tools/call", {"name": forbidden}))
            )
            self.assertEqual(len(transport.gateway_calls), before)

    def test_consent_elicitation_becomes_a_tool_result_with_the_link(self):
        client = make_forwarder()
        elicitation = {
            "jsonrpc": "2.0",
            "id": 1,
            "error": {
                "code": -32042,
                "message": "Authorization required",
                "data": {"elicitations": [{"mode": "url", "url": URL}]},
            },
        }
        client._send = lambda message, headers=None: (elicitation, {})
        response = client.handle(rpc("tools/call", {"name": "schwab-listAccounts"}))
        self.assertNotIn("error", response)
        self.assertTrue(response["result"]["isError"])
        self.assertIn(URL, response["result"]["content"][0]["text"])

    def test_other_errors_and_non_https_links_pass_through(self):
        client = make_forwarder()
        for error in [
            {"code": -32603, "message": "Internal error"},
            {
                "code": -32042,
                "data": {"elicitations": [{"mode": "url", "url": "http://x"}]},
            },
        ]:
            original = {"jsonrpc": "2.0", "id": 1, "error": error}
            client._send = lambda message, headers=None, r=original: (r, {})
            self.assertEqual(
                client.handle(rpc("tools/call", {"name": "schwab-getQuotes"})), original
            )
