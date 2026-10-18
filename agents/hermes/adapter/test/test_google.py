import unittest

import adapter_config

from .test_support import EXPECTED_TOOLS, FakeTransport, make_forwarder, rpc

RAW = {"getMessage", "listCalendars", "listEvents", "listLabels", "listMessages"}


class GoogleTests(unittest.TestCase):
    def test_tools_route_to_gateway_actions_and_unknown_calls_are_refused(self):
        google = next(t for t in adapter_config.TARGETS if t.name == "google")
        self.assertEqual(google.tools, RAW)
        self.assertEqual(google.prefix, "google___")
        self.assertEqual(google.client_tools, {"google-" + name for name in RAW})
        transport = FakeTransport()
        client = make_forwarder(transport)
        listed = {
            t["name"] for t in client.handle(rpc("tools/list"))["result"]["tools"]
        }
        self.assertEqual(listed, EXPECTED_TOOLS)
        for raw in RAW:
            client.handle(rpc("tools/call", {"name": "google-" + raw, "arguments": {}}))
            self.assertEqual(
                transport.gateway_calls[-1][3]["params"]["name"], "google___" + raw
            )
        for forbidden in [
            "sendMessage",
            "google-sendMessage",
            "google-insertEvent",
            "gmail-listLabels",
            *RAW,
        ]:
            before = len(transport.gateway_calls)
            self.assertIn(
                "error", client.handle(rpc("tools/call", {"name": forbidden}))
            )
            self.assertEqual(len(transport.gateway_calls), before)
