import json
import unittest
from urllib.parse import parse_qs

from hermes_aws_adapter import AWS_TOOLS, TARGET_PREFIX, TOOL_MANIFEST, build_forwarder
from hermes_github_adapter import AgentCoreForwarder, REQUIRED_SCOPE

GATEWAY_URL = "https://gateway-id.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp"
TOKEN_URL = "https://pool.auth.us-east-1.amazoncognito.com/oauth2/token"
EXPECTED_TOOLS = {
    "aws___get_regional_availability",
    "aws___get_tasks",
    "aws___list_regions",
    "aws___read_documentation",
    "aws___retrieve_skill",
    "aws___run_script",
    "aws___search_documentation",
}


def _response(status, document, headers=None):
    return type("Response", (), {"status": status, "headers": headers or {}, "body": json.dumps(document).encode()})()


class FakeTransport:
    def __init__(self, prefix=TARGET_PREFIX):
        self.prefix = prefix
        self.token_calls = 0
        self.gateway_calls = []
        self.extra_tool = False
        self.missing_tool = False

    def request(self, url, method, headers, body):
        if url == TOKEN_URL:
            self.token_calls += 1
            assert parse_qs(body.decode()) == {"grant_type": ["client_credentials"], "scope": [REQUIRED_SCOPE]}
            return _response(200, {"access_token": f"synthetic-access-token-{self.token_calls}", "expires_in": 300, "token_type": "Bearer", "scope": REQUIRED_SCOPE})
        self.gateway_calls.append((url, method, headers.copy(), json.loads(body)))
        message = json.loads(body)
        if message["method"] == "tools/list":
            names = [f"{self.prefix}{tool}" for tool in sorted(AWS_TOOLS)]
            if self.extra_tool:
                names.append(f"{self.prefix}aws___get_presigned_url")
            if self.missing_tool:
                names.pop(0)
            result = {"tools": [{"name": name, "description": "safe"} for name in names]}
        elif message["method"] == "tools/call":
            result = {"content": [{"type": "text", "text": "safe"}]}
        else:
            result = {"protocolVersion": "2025-03-26", "capabilities": {}}
        return _response(200, {"jsonrpc": "2.0", "id": message.get("id"), "result": result}, {"content-type": "application/json", "mcp-session-id": "session-1"})


def make_forwarder(transport=None):
    return AgentCoreForwarder(
        GATEWAY_URL,
        TOKEN_URL,
        "client-id",
        "synthetic-client-secret",
        transport=transport or FakeTransport(),
        tools=AWS_TOOLS,
        tool_prefix=TARGET_PREFIX,
        extra_headers={},
    )


def rpc(method, params=None, message_id=1):
    message = {"jsonrpc": "2.0", "id": message_id, "method": method}
    if params is not None:
        message["params"] = params
    return message


class AwsAdapterTests(unittest.TestCase):
    def test_allowlist_matches_the_published_read_only_tool_set(self):
        self.assertEqual(AWS_TOOLS, EXPECTED_TOOLS)
        self.assertEqual(set(TOOL_MANIFEST["tools"]), EXPECTED_TOOLS)
        self.assertEqual(len(TOOL_MANIFEST["tools"]), len(EXPECTED_TOOLS))

    def test_write_capable_tool_is_excluded(self):
        # get_presigned_url mints S3 upload URLs, so it is outside the boundary.
        self.assertNotIn("aws___get_presigned_url", AWS_TOOLS)
        self.assertIn("aws___get_presigned_url", TOOL_MANIFEST["excluded_tools"])

    def test_gateway_action_names_double_the_prefix(self):
        # AgentCore prefixes each action with the target name, and the AWS MCP
        # Server already namespaces its tools with aws___. The gateway action is
        # therefore aws___aws___<tool>. Recording the manifest names without the
        # server's own prefix produced "unrecognized action" policy failures.
        self.assertEqual(f"{TARGET_PREFIX}aws___run_script", "aws___aws___run_script")
        self.assertEqual(f"{TARGET_PREFIX}aws___search_documentation", "aws___aws___search_documentation")
        for tool in AWS_TOOLS:
            self.assertTrue(tool.startswith("aws___"), tool)

    def test_tool_calls_are_forwarded_with_the_aws_target_prefix(self):
        transport = FakeTransport()
        result = make_forwarder(transport).handle(rpc("tools/call", {"name": "aws___list_regions", "arguments": {}}))
        self.assertEqual(result["result"]["content"][0]["text"], "safe")
        self.assertEqual(transport.gateway_calls[0][3]["params"]["name"], "aws___aws___list_regions")

    def test_no_github_toolset_header_is_sent_to_the_aws_target(self):
        transport = FakeTransport()
        make_forwarder(transport).handle(rpc("tools/call", {"name": "aws___list_regions", "arguments": {}}))
        header_names = {key.lower() for key in transport.gateway_calls[0][2]}
        self.assertNotIn("x-mcp-tools", header_names)

    def test_tools_list_is_narrowed_to_the_manifest_and_prefix_is_stripped(self):
        transport = FakeTransport()
        transport.extra_tool = True
        result = make_forwarder(transport).handle(rpc("tools/list"))
        names = {tool["name"] for tool in result["result"]["tools"]}
        self.assertEqual(names, EXPECTED_TOOLS)
        self.assertEqual(len(names), 7)
        self.assertNotIn("aws___get_presigned_url", names)

    def test_gateway_tool_set_mismatch_fails_closed(self):
        transport = FakeTransport()
        transport.missing_tool = True
        result = make_forwarder(transport).handle(rpc("tools/list"))
        self.assertEqual(result["error"]["message"], "gateway_tool_set_mismatch")

    def test_tools_from_other_targets_on_the_shared_gateway_are_rejected(self):
        # A github___ tool must not satisfy the AWS adapter's exact-set check.
        transport = FakeTransport(prefix="github___")
        result = make_forwarder(transport).handle(rpc("tools/list"))
        self.assertEqual(result["error"]["message"], "gateway_tool_set_mismatch")

    def test_unknown_and_cross_target_tools_are_rejected_without_forwarding(self):
        transport = FakeTransport()
        forwarder = make_forwarder(transport)
        self.assertEqual(forwarder.handle(rpc("tools/call", {"name": "aws___get_presigned_url"}))["error"]["code"], -32602)
        self.assertEqual(forwarder.handle(rpc("tools/call", {"name": "push_files"}))["error"]["code"], -32602)
        self.assertEqual(transport.gateway_calls, [])

    def test_client_secret_and_tokens_are_not_in_json_rpc_responses(self):
        transport = FakeTransport()
        response = make_forwarder(transport).handle(rpc("tools/call", {"name": "aws___list_regions", "arguments": {}}))
        encoded = json.dumps(response)
        self.assertNotIn("synthetic-access-token", encoded)
        self.assertNotIn("synthetic-client-secret", encoded)

    def test_build_forwarder_reads_only_hermes_aws_environment_variables(self):
        import os
        from unittest import mock

        env = {
            "HERMES_AWS_GATEWAY_URL": GATEWAY_URL,
            "HERMES_AWS_COGNITO_TOKEN_URL": TOKEN_URL,
            "HERMES_AWS_COGNITO_CLIENT_ID": "id",
            "HERMES_AWS_COGNITO_CLIENT_SECRET": "secret",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            forwarder = build_forwarder()
        self.assertEqual(forwarder.tools, AWS_TOOLS)
        self.assertEqual(forwarder.tool_prefix, TARGET_PREFIX)
        self.assertEqual(forwarder.extra_headers, {})

    def test_build_forwarder_fails_closed_without_credentials(self):
        import os
        from unittest import mock

        from hermes_github_adapter import AdapterError

        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(AdapterError):
                build_forwarder()


if __name__ == "__main__":
    unittest.main()