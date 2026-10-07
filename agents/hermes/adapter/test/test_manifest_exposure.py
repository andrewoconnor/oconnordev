import json
import pathlib
import tempfile
import unittest
from unittest import mock

from adapter_config import AdapterError, Target, _load_target

from .test_support import (
    AWS_TARGET,
    AWS_TOOLS,
    EXPECTED_TOOLS,
    GITHUB_TARGET,
    GITHUB_TOOLS,
    SPACELIFT_TARGET,
    SPACELIFT_TOOLS,
    TARGETS,
    FakeTransport,
    exposed_names,
    make_forwarder,
    rpc,
)


class TargetManifestTests(unittest.TestCase):
    def test_every_registered_target_matches_its_verified_allowlist(self):
        # Each upstream is one target. The AWS MCP Server is reached through
        # the security gateway.
        self.assertEqual(
            {target.name for target in TARGETS}, {"github", "aws", "spacelift"}
        )
        self.assertEqual(GITHUB_TARGET.tools, GITHUB_TOOLS)
        self.assertEqual(AWS_TARGET.tools, AWS_TOOLS)
        self.assertEqual(SPACELIFT_TARGET.tools, SPACELIFT_TOOLS)
        self.assertEqual(len(GITHUB_TARGET.tools), 9)
        self.assertEqual(len(AWS_TARGET.tools), 7)
        self.assertEqual(len(SPACELIFT_TARGET.tools), 3)

    def test_manifests_on_disk_are_the_allowlists(self):
        for target in TARGETS:
            document = json.loads(
                (
                    pathlib.Path(__file__).resolve().parent.parent
                    / f"{target.name}-mcp-tools.json"
                ).read_text()
            )
            self.assertEqual(set(document["tools"]), set(target.tools))

    def test_write_capable_aws_tool_is_excluded(self):
        # get_presigned_url mints S3 upload URLs, so it is outside the boundary.
        self.assertNotIn("aws___get_presigned_url", AWS_TARGET.tools)

    def test_write_capable_spacelift_tools_are_excluded(self):
        # mutate runs GraphQL mutations -- run trigger/confirm/discard, stack,
        # context and policy writes, state changes -- and intent imports and
        # deletes infrastructure. The upstream advertises both even to a
        # reader-scoped key, because the listing describes the server rather
        # than the caller, so excluding them here is what keeps them out.
        for tool in ("mutate", "intent"):
            self.assertNotIn(tool, SPACELIFT_TARGET.tools)

    def test_target_prefixes_are_unambiguous(self):
        # The ___ separator means no target prefix can be a prefix of another,
        # which is what makes action-name routing safe.
        for left in TARGETS:
            for right in TARGETS:
                if left is not right:
                    self.assertFalse(right.prefix.startswith(left.prefix))
                    self.assertFalse(left.prefix.startswith(right.prefix))

    def test_gateway_action_names_nest_without_changing_the_client_names(self):
        # AgentCore prefixes each action with the target name; the security
        # gateway adds its own target prefix (aws) to the AWS MCP Server's
        # aws___ namespace, and this gateway adds a third. So the action on the
        # wire is aws___aws___aws___<tool> while the client keeps the canonical
        # aws___<tool>. That gap is declared by gateway_action_prefix rather
        # than baked into every tool name.
        self.assertEqual(AWS_TARGET.prefix, "aws___aws___")
        self.assertEqual(
            AWS_TARGET.prefix + "aws___run_script", "aws___aws___aws___run_script"
        )
        for tool in AWS_TOOLS:
            self.assertTrue(tool.startswith("aws___"), tool)
            self.assertFalse(tool.startswith("aws___aws___"), tool)

    def test_a_malformed_gateway_action_prefix_fails_closed(self):
        # The declared prefix must end in the separator, or action-name routing
        # would mis-split and the tool-set check would compare wrong names.
        with tempfile.TemporaryDirectory() as directory:
            (pathlib.Path(directory) / "bad-mcp-tools.json").write_text(
                json.dumps({"tools": ["x"], "gateway_action_prefix": "aws__"})
            )
            with (
                mock.patch("adapter_config.MANIFEST_DIR", pathlib.Path(directory)),
                self.assertRaises(AdapterError) as caught,
            ):
                _load_target("bad", "bad-mcp-tools.json")
        self.assertEqual(caught.exception.category, "invalid_gateway_action_prefix")

    def test_a_malformed_client_tool_prefix_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            (pathlib.Path(directory) / "bad-mcp-tools.json").write_text(
                json.dumps({"tools": ["x"], "client_tool_prefix": "invalid__"})
            )
            with (
                mock.patch("adapter_config.MANIFEST_DIR", pathlib.Path(directory)),
                self.assertRaises(AdapterError) as caught,
            ):
                _load_target("bad", "bad-mcp-tools.json")
        self.assertEqual(caught.exception.category, "invalid_client_tool_prefix")

    def test_duplicate_tool_across_targets_fails_closed(self):
        overlapping = (
            Target(name="github", tools=frozenset({"shared"}), headers={}),
            Target(name="aws", tools=frozenset({"shared"}), headers={}),
        )
        with self.assertRaises(AdapterError) as caught:
            make_forwarder(targets=overlapping)
        self.assertEqual(caught.exception.category, "duplicate_tool_across_targets")


class ExposureTests(unittest.TestCase):
    def test_tools_list_exposes_every_targets_manifest_tools(self):
        self.assertEqual(exposed_names(make_forwarder()), EXPECTED_TOOLS)
        self.assertEqual(len(EXPECTED_TOOLS), 19)

    def test_extra_tools_are_not_exposed(self):
        transport = FakeTransport()
        transport.extra_tool = True
        self.assertEqual(exposed_names(make_forwarder(transport)), EXPECTED_TOOLS)

    def test_unregistered_targets_are_ignored_not_a_mismatch(self):
        transport = FakeTransport()
        transport.unregistered_target = True
        self.assertEqual(exposed_names(make_forwarder(transport)), EXPECTED_TOOLS)

    def test_a_missing_target_fails_closed(self):
        # One target silently absent must not look like a smaller catalog.
        for hidden in ("github", "aws", "spacelift"):
            transport = FakeTransport()
            transport.hide_target = hidden
            result = make_forwarder(transport).handle(rpc("tools/list"))
            self.assertEqual(
                result["error"]["message"], "gateway_tool_set_mismatch", hidden
            )

    def test_missing_tool_fails_closed(self):
        transport = FakeTransport()
        transport.missing_tool = True
        result = make_forwarder(transport).handle(rpc("tools/list"))
        self.assertEqual(result["error"]["message"], "gateway_tool_set_mismatch")

    def test_tools_list_pages_the_gateway_to_exhaustion(self):
        transport = FakeTransport()
        transport.page_size = 3
        result = make_forwarder(transport).handle(rpc("tools/list"))
        self.assertEqual(
            {tool["name"] for tool in result["result"]["tools"]}, EXPECTED_TOOLS
        )
        # One call per page of three, so derive the page count from the tool
        # count rather than restating it whenever a target is added.
        self.assertEqual(len(transport.gateway_calls), -(-len(EXPECTED_TOOLS) // 3))
        self.assertNotIn("nextCursor", result["result"])

    def test_paging_still_fails_closed_when_a_manifest_is_incomplete(self):
        transport = FakeTransport()
        transport.page_size = 3
        transport.missing_tool = True
        result = make_forwarder(transport).handle(rpc("tools/list"))
        self.assertEqual(result["error"]["message"], "gateway_tool_set_mismatch")

    def test_client_supplied_cursor_cannot_narrow_the_tool_set(self):
        transport = FakeTransport()
        transport.page_size = 3
        self.assertEqual(
            exposed_names(make_forwarder(transport), {"cursor": "3"}), EXPECTED_TOOLS
        )
