import json
import unittest
from pathlib import Path

import adapter_config

from .test_support import EXPECTED_TOOLS, FakeTransport, make_forwarder, rpc

MAIL_TOOLS = {
    "list-mail-messages",
    "get-mail-message",
    "list-mail-folders",
    "list-mail-child-folders",
    "list-mail-folder-messages",
}


class Microsoft365Tests(unittest.TestCase):
    def test_mail_tools_route_and_unknown_calls_are_refused(self):
        mail = next(t for t in adapter_config.TARGETS if t.name == "microsoft365")
        self.assertEqual(mail.tools, MAIL_TOOLS)
        self.assertEqual(mail.prefix, "microsoft365___")
        self.assertEqual(mail.headers, {})
        transport = FakeTransport()
        client = make_forwarder(transport)
        result = client.handle(rpc("tools/list"))
        self.assertEqual({t["name"] for t in result["result"]["tools"]}, EXPECTED_TOOLS)
        for tool in MAIL_TOOLS:
            client.handle(rpc("tools/call", {"name": tool, "arguments": {}}))
            self.assertEqual(
                transport.gateway_calls[-1][3]["params"]["name"], mail.prefix + tool
            )
        for forbidden in [
            "graph-batch",
            "login",
            "get-current-user",
            "send-mail",
            "list-users",
            "list-calendars",
        ]:
            before = len(transport.gateway_calls)
            self.assertIn(
                "error", client.handle(rpc("tools/call", {"name": forbidden}))
            )
            self.assertEqual(len(transport.gateway_calls), before)

    def test_actual_strict_runtime_catalog_survives_adapter_discovery(self):
        root = Path(__file__).resolve().parents[4]
        catalog = json.loads(
            (
                root / "infra/aws/tools/lambdas/microsoft365_mcp/tools-manifest.json"
            ).read_text()
        )
        mail = next(t for t in adapter_config.TARGETS if t.name == "microsoft365")
        tools = [
            {"name": t.prefix + name}
            for t in adapter_config.TARGETS
            if t is not mail
            for name in t.tools
        ]
        tools += [{**tool, "name": mail.prefix + tool["name"]} for tool in catalog]
        client = make_forwarder()
        client._send = lambda message: (
            {"jsonrpc": "2.0", "id": message["id"], "result": {"tools": tools}},
            {},
        )
        result = client.handle(rpc("tools/list"))["result"]["tools"]
        exposed = {tool["name"]: tool for tool in result if tool["name"] in MAIL_TOOLS}
        self.assertEqual(set(exposed), MAIL_TOOLS)
        for tool in catalog:
            self.assertEqual(exposed[tool["name"]]["inputSchema"], tool["inputSchema"])
            self.assertFalse(tool["inputSchema"]["additionalProperties"])
        self.assertEqual(
            exposed["get-mail-message"]["inputSchema"]["required"], ["messageId"]
        )
        self.assertEqual(
            exposed["list-mail-child-folders"]["inputSchema"]["required"],
            ["mailFolderId"],
        )
