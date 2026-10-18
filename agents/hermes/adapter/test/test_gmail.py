import unittest

import adapter_config

from .test_support import EXPECTED_TOOLS, FakeTransport, make_forwarder, rpc

RAW = {"getMessage", "listLabels", "listMessages"}


class GmailTests(unittest.TestCase):
    def test_tools_route_to_gateway_actions_and_unknown_calls_are_refused(self):
        gmail = next(t for t in adapter_config.TARGETS if t.name == "gmail")
        self.assertEqual(gmail.tools, RAW)
        self.assertEqual(gmail.prefix, "gmail___")
        self.assertEqual(gmail.client_tools, {"gmail-" + name for name in RAW})
        transport = FakeTransport()
        client = make_forwarder(transport)
        listed = {
            t["name"] for t in client.handle(rpc("tools/list"))["result"]["tools"]
        }
        self.assertEqual(listed, EXPECTED_TOOLS)
        for raw in RAW:
            client.handle(rpc("tools/call", {"name": "gmail-" + raw, "arguments": {}}))
            self.assertEqual(
                transport.gateway_calls[-1][3]["params"]["name"], "gmail___" + raw
            )
        for forbidden in [
            "sendMessage",
            "gmail-sendMessage",
            "gmail-trashMessage",
            *RAW,
        ]:
            before = len(transport.gateway_calls)
            self.assertIn(
                "error", client.handle(rpc("tools/call", {"name": forbidden}))
            )
            self.assertEqual(len(transport.gateway_calls), before)
