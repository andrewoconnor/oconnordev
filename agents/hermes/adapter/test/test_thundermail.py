"""Secretless native Thundermail catalog/routing acceptance tests."""

import json
import unittest
from pathlib import Path
from unittest import mock

import adapter_config
from adapter_config import AdapterError

from .test_support import EXPECTED_TOOLS, FakeTransport, make_forwarder, rpc

ROOT = Path(__file__).resolve().parents[4]
RAW = {"imap_list_mailboxes", "imap_search_messages", "imap_get_message"}
CLIENT = {"thundermail-" + name for name in RAW}


class ThundermailTests(unittest.TestCase):
    def targets(self):
        with mock.patch.dict(
            "os.environ", {"HERMES_AGENTCORE_THUNDERMAIL_ENABLED": "true"}, clear=True
        ):
            return adapter_config.load_targets()

    def test_opt_in_raw_names_namespaced_and_no_unknown_calls(self):
        targets = self.targets()
        mail = next((t for t in targets if t.name == "thundermail"), None)
        self.assertIsNotNone(mail, "explicit opt-in must register native target")
        self.assertEqual(mail.tools, RAW)
        self.assertEqual(mail.client_tools, CLIENT)
        self.assertEqual(mail.prefix, "thundermail___")
        self.assertEqual(mail.headers, {})
        transport = FakeTransport()
        original = transport._catalog
        transport._catalog = lambda: original() + [mail.prefix + t for t in RAW]
        client = make_forwarder(transport, targets=targets)
        self.assertEqual(
            {t["name"] for t in client.handle(rpc("tools/list"))["result"]["tools"]},
            EXPECTED_TOOLS | CLIENT,
        )
        for raw in RAW:
            client.handle(
                rpc("tools/call", {"name": "thundermail-" + raw, "arguments": {}})
            )
            self.assertEqual(
                transport.gateway_calls[-1][3]["params"]["name"], mail.prefix + raw
            )
        for forbidden in [
            *RAW,
            "thundermail-imap_delete_message",
            "thundermail-send",
            "thundermail-imap-list-mailboxes",
            "thundermail-login",
        ]:
            before = len(transport.gateway_calls)
            self.assertIn(
                "error", client.handle(rpc("tools/call", {"name": forbidden}))
            )
            self.assertEqual(len(transport.gateway_calls), before)

    def test_default_and_invalid_flag(self):
        for env in [{}, {"HERMES_AGENTCORE_THUNDERMAIL_ENABLED": "false"}]:
            with mock.patch.dict("os.environ", env, clear=True):
                self.assertEqual(adapter_config.load_targets(), adapter_config.TARGETS)
        with (
            mock.patch.dict(
                "os.environ",
                {"HERMES_AGENTCORE_THUNDERMAIL_ENABLED": "yes"},
                clear=True,
            ),
            self.assertRaises(AdapterError),
        ):
            adapter_config.load_targets()

    def test_owned_strict_schema_and_sdk(self):
        try:
            from mcp.types import ListToolsResult
        except ImportError:
            self.skipTest(
                "Run mise run test:thundermail-sdk with isolated pinned MCP SDK"
            )

        manifest = json.loads(
            (ROOT / "agents/hermes/adapter/thundermail-mcp-tools.json").read_text()
        )
        owned = manifest["toolSchemas"]
        runtime = json.loads(
            (
                ROOT / "infra/aws/tools/lambdas/thundermail_mcp/tool-schemas.json"
            ).read_text()
        )["tools"]
        self.assertEqual(owned, runtime)
        self.assertEqual({t["name"] for t in owned}, RAW)
        mail = next(t for t in self.targets() if t.name == "thundermail")
        tools = [
            {"name": t.prefix + name, "inputSchema": {"type": "object"}}
            for t in adapter_config.TARGETS
            for name in t.tools
        ]
        # Restore restrictions omitted by native SchemaDefinition.
        tools += [
            {"name": mail.prefix + tool["name"], "inputSchema": {"type": "object"}}
            for tool in owned
        ]
        client = make_forwarder(targets=self.targets())
        client._send = lambda message: (
            {"jsonrpc": "2.0", "id": message["id"], "result": {"tools": tools}},
            {},
        )
        exposed = client.handle(rpc("tools/list"))["result"]
        parsed = ListToolsResult.model_validate(exposed)
        selected = {tool.name: tool for tool in parsed.tools if tool.name in CLIENT}
        self.assertEqual(set(selected), CLIENT)
        for tool in owned:
            self.assertEqual(
                selected["thundermail-" + tool["name"]].model_dump(by_alias=True)[
                    "inputSchema"
                ],
                tool["inputSchema"],
            )
            self.assertIs(tool["inputSchema"]["additionalProperties"], False)
