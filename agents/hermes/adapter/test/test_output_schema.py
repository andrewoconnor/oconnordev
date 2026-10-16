import copy
import unittest
from unittest import mock

from .test_support import EXPECTED_TOOLS, make_forwarder, rpc


class OutputSchemaTests(unittest.TestCase):
    def test_non_object_output_schema_is_omitted_without_mutating_catalog(self):
        schemas = [
            {"type": ["null", "object"]},
            {"type": ["null", "array"], "items": {"type": "string"}},
            {"oneOf": [{"type": "null"}, {"type": "object"}]},
            {"type": "array", "items": {"type": "object"}},
            {"type": "string"},
            {"type": ["object"]},
            {},
            None,
            False,
            [],
            "object",
        ]
        for schema in schemas:
            with self.subTest(schema=schema):
                forwarder = make_forwarder()
                page = forwarder.handle(rpc("tools/list"))
                # Use wire names for the upstream response, not client names.
                tools = page["result"]["tools"]
                for tool in tools:
                    target = forwarder._owners[tool["name"]]
                    tool["name"] = target.prefix + tool["name"]
                    tool["outputSchema"] = schema
                original = copy.deepcopy(page)
                with mock.patch.object(forwarder, "_send", return_value=(page, {})):
                    response = forwarder.handle(rpc("tools/list"))
                exposed = response["result"]["tools"]
                self.assertEqual({tool["name"] for tool in exposed}, EXPECTED_TOOLS)
                for tool in exposed:
                    self.assertNotIn("outputSchema", tool)
                self.assertEqual(page, original)

    def test_object_schema_and_other_metadata_are_preserved_exactly(self):
        forwarder = make_forwarder()
        page = forwarder.handle(rpc("tools/list"))
        original_tools = copy.deepcopy(page["result"]["tools"])
        schema = {
            "type": "object",
            "$defs": {"value": {"type": ["null", "array"]}},
            "properties": {"value": {"$ref": "#/$defs/value"}},
            "oneOf": [{"required": ["value"]}, {"additionalProperties": False}],
        }
        for tool in page["result"]["tools"]:
            client_name = tool["name"]
            tool.update(
                inputSchema={"type": "object", "properties": {"x": {"type": "string"}}},
                annotations={"readOnlyHint": True},
                outputSchema=copy.deepcopy(schema),
                _meta={"example": "preserved"},
            )
            tool["name"] = forwarder._owners[client_name].prefix + client_name
        original = copy.deepcopy(page)
        with mock.patch.object(forwarder, "_send", return_value=(page, {})):
            exposed = forwarder.handle(rpc("tools/list"))["result"]["tools"]
        for base, tool in zip(original_tools, exposed, strict=True):
            upstream = next(
                item
                for item in original["result"]["tools"]
                if item["name"] == forwarder._owners[base["name"]].prefix + base["name"]
            )
            self.assertEqual(tool, {**upstream, "name": base["name"]})
        self.assertEqual(page, original)

    def test_absent_schema_stays_absent(self):
        tools = make_forwarder().handle(rpc("tools/list"))["result"]["tools"]
        self.assertTrue(all("outputSchema" not in tool for tool in tools))

    def test_tool_results_are_not_rewritten(self):
        forwarder = make_forwarder()
        for value in (None, [], {"value": "original"}):
            with self.subTest(value=value):
                response = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {
                        "content": [{"type": "text", "text": "original"}],
                        "structuredContent": value,
                    },
                }
                original = copy.deepcopy(response)
                with mock.patch.object(forwarder, "_send", return_value=(response, {})):
                    result = forwarder.handle(rpc("tools/call", {"name": "get_commit"}))
                self.assertEqual(result, original)
