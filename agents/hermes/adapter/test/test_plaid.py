import json
import unittest
from pathlib import Path

import adapter_config

from .test_support import FakeTransport, make_forwarder, rpc

ROOT = Path(__file__).resolve().parents[4]
RAW = {
    "listItems",
    "getAccounts",
    "getTransactions",
    "getItemStatus",
    "getRecurringTransactions",
    "getLiabilities",
    "getHoldings",
}


class PlaidTests(unittest.TestCase):
    def test_catalog_routing_and_forbidden_calls(self):
        target = next((t for t in adapter_config.TARGETS if t.name == "plaid"), None)
        self.assertIsNotNone(target, "Plaid must be registered")
        self.assertEqual(target.tools, RAW)
        self.assertEqual(target.prefix, "plaid___")
        self.assertEqual(target.client_tool_prefix, "plaid-")
        transport = FakeTransport()
        client = make_forwarder(transport)
        for raw in RAW:
            client.handle(rpc("tools/call", {"name": "plaid-" + raw, "arguments": {}}))
            self.assertEqual(
                transport.gateway_calls[-1][3]["params"]["name"], "plaid___" + raw
            )
        for name in [
            "listItems",
            "plaid-list_items",
            "plaid-link",
            "plaid-removeItem",
            "plaid-getTransactionsSync",
        ]:
            before = len(transport.gateway_calls)
            self.assertIn("error", client.handle(rpc("tools/call", {"name": name})))
            self.assertEqual(len(transport.gateway_calls), before)

    def test_owned_schemas_match_native_catalog_and_restore_restrictions(self):
        path = ROOT / "infra/aws/tools/lambdas/plaid/tools.json"
        self.assertTrue(path.exists(), "Native schema catalog missing")
        runtime = json.loads(path.read_text())["tools"]
        self.assertEqual({t["name"] for t in runtime}, RAW)
        manifest = json.loads(
            (ROOT / "agents/hermes/adapter/plaid-mcp-tools.json").read_text()
        )
        self.assertEqual(manifest["toolSchemas"], runtime)
        exposed = make_forwarder().handle(rpc("tools/list"))["result"]["tools"]
        selected = {t["name"]: t for t in exposed if t["name"].startswith("plaid-")}
        for tool in runtime:
            self.assertEqual(
                selected["plaid-" + tool["name"]]["inputSchema"], tool["inputSchema"]
            )
            self.assertIs(tool["inputSchema"]["additionalProperties"], False)
        transaction = selected["plaid-getTransactions"]["inputSchema"]
        self.assertEqual(transaction["properties"]["count"]["maximum"], 500)
        self.assertEqual(transaction["properties"]["count"]["default"], 100)
        self.assertEqual(
            transaction["properties"]["item"]["enum"],
            ["capital-one", "usaa", "amex", "empower"],
        )
        self.assertEqual(transaction["properties"]["startDate"]["format"], "date")

    def test_missing_plaid_target_fails_closed(self):
        transport = FakeTransport()
        transport.hide_target = "plaid"
        self.assertIn("error", make_forwarder(transport).handle(rpc("tools/list")))
