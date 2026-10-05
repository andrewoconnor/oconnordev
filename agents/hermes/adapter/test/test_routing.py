from .test_support import *

class RoutingTests(unittest.TestCase):
    def test_github_call_is_forwarded_with_its_prefix_and_toolset_header(self):
        transport = FakeTransport()
        result = make_forwarder(transport).handle(rpc("tools/call", {"name": "get_file_contents", "arguments": {"owner": "andrewoconnor", "repo": "sample", "path": "src/main.py"}}))
        self.assertEqual(result["result"]["content"][0]["text"], "safe")
        self.assertEqual(transport.gateway_calls[0][3]["params"]["name"], "github___get_file_contents")
        self.assertEqual(transport.gateway_calls[0][2]["X-MCP-Tools"], EXPECTED_TOOL_HEADER)

    def test_aws_call_is_forwarded_with_the_nested_prefix_and_no_toolset_header(self):
        # The client names the tool aws___list_regions; on the wire it becomes
        # aws___aws___aws___list_regions, because the security gateway and this
        # one each add a prefix on top of the server's own namespace.
        transport = FakeTransport()
        result = make_forwarder(transport).handle(rpc("tools/call", {"name": "aws___list_regions", "arguments": {}}))
        self.assertEqual(result["result"]["content"][0]["text"], "safe")
        self.assertEqual(transport.gateway_calls[0][3]["params"]["name"], "aws___aws___aws___list_regions")
        self.assertNotIn("x-mcp-tools", {key.lower() for key in transport.gateway_calls[0][2]})

    def test_spacelift_call_is_forwarded_with_its_prefix_and_no_toolset_header(self):
        # Spacelift's upstream does not namespace its own tools, so the gateway
        # action is the single-prefixed spacelift___<tool>. The read-only
        # narrowing lives in the target's URL, not in a request header.
        transport = FakeTransport()
        result = make_forwarder(transport).handle(rpc("tools/call", {"name": "query", "arguments": {"operation": "stacks"}}))
        self.assertEqual(result["result"]["content"][0]["text"], "safe")
        self.assertEqual(transport.gateway_calls[0][3]["params"]["name"], "spacelift___query")
        self.assertNotIn("x-mcp-tools", {key.lower() for key in transport.gateway_calls[0][2]})

    def test_one_token_serves_every_target(self):
        transport = FakeTransport()
        forwarder = make_forwarder(transport)
        forwarder.handle(rpc("tools/call", {"name": "get_file_contents", "arguments": {}}))
        forwarder.handle(rpc("tools/call", {"name": "aws___list_regions", "arguments": {}}))
        forwarder.handle(rpc("tools/call", {"name": "query", "arguments": {}}))
        self.assertEqual(transport.token_calls, 1)
        self.assertEqual(len(transport.gateway_calls), 3)

    def test_unknown_and_cross_target_names_are_rejected_without_forwarding(self):
        transport = FakeTransport()
        forwarder = make_forwarder(transport)
        for name in (
            "aws___get_presigned_url",
            "repository_info",
            "github___get_file_contents",
            # The raw wire action, which the client never sees and must not
            # reach by naming directly; the client name is one level shorter.
            "aws___aws___aws___list_regions",
            "spacelift___query",
            "mutate",
            "intent",
        ):
            self.assertEqual(forwarder.handle(rpc("tools/call", {"name": name}))["error"]["code"], -32602, name)
        self.assertEqual(transport.gateway_calls, [])

    def test_unknown_methods_are_rejected_without_forwarding(self):
        transport = FakeTransport()
        self.assertEqual(make_forwarder(transport).handle(rpc("resources/read"))["error"]["code"], -32601)
        self.assertEqual(transport.gateway_calls, [])

    def test_destination_cannot_be_overridden_by_tool_arguments(self):
        transport = FakeTransport()
        make_forwarder(transport).handle(rpc("tools/call", {"name": "get_file_contents", "arguments": {"owner": "andrewoconnor", "repo": "sample", "path": "src/main.py", "url": "https://evil.invalid"}}))
        self.assertEqual(transport.gateway_calls[0][0], GATEWAY_URL)
        self.assertEqual(len(transport.gateway_calls), 1)
