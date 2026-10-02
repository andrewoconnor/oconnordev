import json
import os
import pathlib
import tempfile
import unittest
from unittest import mock
from urllib.parse import parse_qs

from hermes_agentcore_adapter import (
    AdapterError,
    AgentCoreForwarder,
    REQUIRED_SCOPE,
    TARGETS,
    Target,
    TokenCache,
    _load_forwarder,
    _load_target,
)

GATEWAY_URL = "https://gateway-id.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp"
CLOUDFRONT_GATEWAY_URL = "https://mcp.oconnor.dev/mcp"
TOKEN_URL = "https://pool.auth.us-east-1.amazoncognito.com/oauth2/token"

GITHUB_TOOLS = {
    "get_file_contents",
    "list_branches",
    "get_commit",
    "create_branch",
    "push_files",
    "delete_file",
    "create_pull_request",
    "pull_request_read",
}
# The client keeps the canonical AWS names even though these tools now arrive
# through two gateways. The extra hop lives in the manifest's declared wire
# prefix, not in the names Hermes sees.
AWS_TOOLS = {
    "aws___get_regional_availability",
    "aws___get_tasks",
    "aws___list_regions",
    "aws___read_documentation",
    "aws___retrieve_skill",
    "aws___run_script",
    "aws___search_documentation",
}
SPACELIFT_TOOLS = {
    "discover",
    "provider",
    "query",
}
EXPECTED_TOOLS = GITHUB_TOOLS | AWS_TOOLS | SPACELIFT_TOOLS
GITHUB_TARGET = next(target for target in TARGETS if target.name == "github")
AWS_TARGET = next(target for target in TARGETS if target.name == "aws")
SPACELIFT_TARGET = next(target for target in TARGETS if target.name == "spacelift")
EXPECTED_TOOL_HEADER = ",".join(sorted(GITHUB_TOOLS))


def _response(status, document, headers=None):
    return type("Response", (), {"status": status, "headers": headers or {}, "body": json.dumps(document).encode()})()


class FakeTransport:
    """Stands in for the gateway, serving every registered target's tools."""

    def __init__(self):
        self.token_calls = 0
        self.gateway_calls = []
        self.gateway_401_count = 0
        self.always_401 = False
        self.scope: object = REQUIRED_SCOPE
        self.omit_scope = False
        # Drop keys from the token response, or replace its body entirely with
        # raw bytes, to exercise the token-response validation path.
        self.token_drop: tuple[str, ...] = ()
        self.token_raw: bytes | None = None
        self.extra_tool = False
        self.missing_tool = False
        # 0 means "return every tool in one page", which is what the gateway
        # does not do. Set a page size to exercise the paging path.
        self.page_size = 0
        self.unregistered_target = False
        self.hide_target: str | None = None
        self.tokens = []

    def _catalog(self):
        names = []
        for target in TARGETS:
            if target.name == self.hide_target:
                continue
            names += [f"{target.prefix}{tool}" for tool in sorted(target.tools)]
        if self.extra_tool:
            names.append("github___dangerous_tool")
        if self.missing_tool:
            names.pop(0)
        if self.unregistered_target:
            names.append("slack___post_message")
        return sorted(names)

    def request(self, url, method, headers, body):
        if url == TOKEN_URL:
            self.token_calls += 1
            form = parse_qs(body.decode())
            assert form == {"grant_type": ["client_credentials"], "scope": [REQUIRED_SCOPE]}
            token = f"synthetic-access-token-{self.token_calls}"
            self.tokens.append(token)
            if self.token_raw is not None:
                return type("Response", (), {"status": 200, "headers": {}, "body": self.token_raw})()
            response = {"access_token": token, "expires_in": 300, "token_type": "Bearer"}
            if not self.omit_scope:
                response["scope"] = self.scope
            for key in self.token_drop:
                response.pop(key, None)
            return _response(200, response)
        self.gateway_calls.append((url, method, headers.copy(), json.loads(body)))
        if self.always_401 or self.gateway_401_count > 0:
            if self.gateway_401_count > 0:
                self.gateway_401_count -= 1
            return _response(401, {})
        message = json.loads(body)
        if message["method"] == "tools/list":
            names = self._catalog()
            cursor = (message.get("params") or {}).get("cursor")
            if self.page_size:
                start = int(cursor) if cursor else 0
                window = names[start:start + self.page_size]
                following = start + self.page_size
                paged: dict = {"tools": [{"name": name, "description": "safe"} for name in window]}
                if following < len(names):
                    paged["nextCursor"] = str(following)
                result = paged
            else:
                result = {"tools": [{"name": name, "description": "safe"} for name in names]}
        elif message["method"] == "tools/call":
            result = {"content": [{"type": "text", "text": "safe"}]}
        else:
            result = {"protocolVersion": "2025-03-26", "capabilities": {}}
        return _response(200, {"jsonrpc": "2.0", "id": message.get("id"), "result": result}, {"content-type": "application/json", "mcp-session-id": "session-1"})


def make_forwarder(transport=None, **kwargs):
    return AgentCoreForwarder(
        GATEWAY_URL,
        TOKEN_URL,
        "client-id",
        "synthetic-client-secret",
        transport=transport or FakeTransport(),
        **kwargs,
    )


def rpc(method, params=None, message_id=1):
    message = {"jsonrpc": "2.0", "id": message_id, "method": method}
    if params is not None:
        message["params"] = params
    return message


def exposed_names(forwarder, params=None):
    result = forwarder.handle(rpc("tools/list", params))
    return {tool["name"] for tool in result["result"]["tools"]}


class TargetManifestTests(unittest.TestCase):
    def test_every_registered_target_matches_its_verified_allowlist(self):
        # One target per upstream, and exactly one target for AWS: the AWS
        # tools come through the security gateway rather than alongside it.
        self.assertEqual({target.name for target in TARGETS}, {"github", "aws", "spacelift"})
        self.assertEqual(GITHUB_TARGET.tools, GITHUB_TOOLS)
        self.assertEqual(AWS_TARGET.tools, AWS_TOOLS)
        self.assertEqual(SPACELIFT_TARGET.tools, SPACELIFT_TOOLS)
        self.assertEqual(len(GITHUB_TARGET.tools), 8)
        self.assertEqual(len(AWS_TARGET.tools), 7)
        self.assertEqual(len(SPACELIFT_TARGET.tools), 3)

    def test_manifests_on_disk_are_the_allowlists(self):
        for target in TARGETS:
            document = json.loads((pathlib.Path(__file__).resolve().parent.parent / f"{target.name}-mcp-tools.json").read_text())
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
        self.assertEqual(AWS_TARGET.prefix + "aws___run_script", "aws___aws___aws___run_script")
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
            with mock.patch("hermes_agentcore_adapter.MANIFEST_DIR", pathlib.Path(directory)):
                with self.assertRaises(AdapterError) as caught:
                    _load_target("bad", "bad-mcp-tools.json")
        self.assertEqual(caught.exception.category, "invalid_gateway_action_prefix")

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
        self.assertEqual(len(EXPECTED_TOOLS), 18)

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
            self.assertEqual(result["error"]["message"], "gateway_tool_set_mismatch", hidden)

    def test_missing_tool_fails_closed(self):
        transport = FakeTransport()
        transport.missing_tool = True
        result = make_forwarder(transport).handle(rpc("tools/list"))
        self.assertEqual(result["error"]["message"], "gateway_tool_set_mismatch")

    def test_tools_list_pages_the_gateway_to_exhaustion(self):
        transport = FakeTransport()
        transport.page_size = 3
        result = make_forwarder(transport).handle(rpc("tools/list"))
        self.assertEqual({tool["name"] for tool in result["result"]["tools"]}, EXPECTED_TOOLS)
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
        self.assertEqual(exposed_names(make_forwarder(transport), {"cursor": "3"}), EXPECTED_TOOLS)


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


class TokenTests(unittest.TestCase):
    def test_required_scope_matches_generic_cognito_resource_server(self):
        self.assertEqual(REQUIRED_SCOPE, "hermes-mcp/invoke")

    def test_initial_token_acquisition_requests_client_credentials_and_exact_scope(self):
        transport = FakeTransport()
        make_forwarder(transport).handle(rpc("ping"))
        self.assertEqual(transport.token_calls, 1)

    def test_token_caching_reuses_token(self):
        transport = FakeTransport()
        now = [0.0]
        cache = TokenCache(TOKEN_URL, "id", "secret", transport, clock=lambda: now[0])
        first = cache.get()
        now[0] = 30.0
        self.assertEqual(first, cache.get())
        self.assertEqual(transport.token_calls, 1)

    def test_proactive_refresh_before_expiration(self):
        transport = FakeTransport()
        now = [0.0]
        cache = TokenCache(TOKEN_URL, "id", "secret", transport, clock=lambda: now[0])
        first = cache.get()
        now[0] = 241.0
        self.assertNotEqual(first, cache.get())
        self.assertEqual(transport.token_calls, 2)

    def test_401_refreshes_once_and_retries_once(self):
        transport = FakeTransport()
        transport.gateway_401_count = 1
        result = make_forwarder(transport).handle(rpc("ping"))
        self.assertIn("result", result)
        self.assertEqual(transport.token_calls, 2)
        self.assertEqual(len(transport.gateway_calls), 2)
        self.assertNotEqual(transport.gateway_calls[0][2]["Authorization"], transport.gateway_calls[1][2]["Authorization"])

    def test_repeated_401_fails_closed(self):
        transport = FakeTransport()
        transport.always_401 = True
        result = make_forwarder(transport).handle(rpc("ping"))
        self.assertEqual(result["error"]["message"], "gateway_authentication_failure")
        self.assertEqual(transport.token_calls, 2)
        self.assertEqual(len(transport.gateway_calls), 2)

    def test_wrong_scope_is_rejected(self):
        for bad in ("other/scope", "hermes-mcp/invoke hermes-mcp/other", "", 7):
            transport = FakeTransport()
            transport.scope = bad
            result = make_forwarder(transport).handle(rpc("ping"))
            self.assertEqual(result["error"]["message"], "oauth_scope_mismatch", bad)
            self.assertEqual(transport.gateway_calls, [])

    def test_absent_scope_is_accepted(self):
        # RFC 6749 section 5.1 makes the response `scope` field OPTIONAL when the
        # granted scope is identical to the requested one. Cognito omits it for
        # this client, so requiring the echo rejected every real token.
        transport = FakeTransport()
        transport.omit_scope = True
        result = make_forwarder(transport).handle(rpc("ping"))
        self.assertIsNotNone(result)
        self.assertNotIn("error", result)
        self.assertEqual(len(transport.gateway_calls), 1)

    def test_token_response_without_access_token_is_rejected(self):
        transport = FakeTransport()
        transport.token_drop = ("access_token",)
        result = make_forwarder(transport).handle(rpc("ping"))
        self.assertEqual(result["error"]["message"], "invalid_token_response")
        self.assertEqual(transport.gateway_calls, [])

    def test_non_json_token_response_is_rejected(self):
        transport = FakeTransport()
        transport.token_raw = b"not-json"
        result = make_forwarder(transport).handle(rpc("ping"))
        self.assertEqual(result["error"]["message"], "invalid_token_response")
        self.assertEqual(transport.gateway_calls, [])


class EndpointTests(unittest.TestCase):
    def test_cloudfront_gateway_endpoint_is_accepted(self):
        transport = FakeTransport()
        forwarder = AgentCoreForwarder(CLOUDFRONT_GATEWAY_URL, TOKEN_URL, "id", "secret", transport)
        result = forwarder.handle(rpc("ping"))
        self.assertIsNotNone(result)
        self.assertNotIn("error", result)
        self.assertEqual(transport.gateway_calls[0][0], CLOUDFRONT_GATEWAY_URL)

    def test_endpoint_validation_still_rejects_anything_else(self):
        for url in (
            "https://mcp.oconnor.dev.evil.com/mcp",
            "https://evil.oconnor.dev/mcp",
            "https://evil.com/mcp",
            "https://mcp.oconnor.dev/notmcp",
            "https://mcp.oconnor.dev/",
            "https://mcp.oconnor.dev/mcp/",
            "http://mcp.oconnor.dev/mcp",
            "https://mcp.oconnor.dev:8443/mcp",
            "https://gateway-id.gateway.bedrock-agentcore.us-east-1.amazonaws.com.evil.com/mcp",
            "https://user@mcp.oconnor.dev/mcp",
            "https://mcp.oconnor.dev/mcp?x=1",
        ):
            with self.assertRaises(AdapterError, msg=url):
                AgentCoreForwarder(url, TOKEN_URL, "id", "secret", FakeTransport())

    def test_invalid_token_endpoint_is_rejected(self):
        with self.assertRaises(AdapterError):
            AgentCoreForwarder(GATEWAY_URL, "https://evil.invalid/oauth2/token", "id", "secret", FakeTransport())


class EnvironmentTests(unittest.TestCase):
    def test_forwarder_reads_the_agentcore_namespaced_variables(self):
        env = {
            "HERMES_AGENTCORE_GATEWAY_URL": GATEWAY_URL,
            "HERMES_AGENTCORE_COGNITO_TOKEN_URL": TOKEN_URL,
            "HERMES_AGENTCORE_COGNITO_CLIENT_ID": "id",
            "HERMES_AGENTCORE_COGNITO_CLIENT_SECRET": "secret",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            forwarder = _load_forwarder()
        self.assertEqual(forwarder.targets, TARGETS)

    def test_forwarder_fails_closed_without_credentials(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(AdapterError):
                _load_forwarder()

    def test_client_secret_and_tokens_are_not_in_json_rpc_responses(self):
        transport = FakeTransport()
        forwarder = make_forwarder(transport)
        for name in ("get_file_contents", "aws___list_regions"):
            encoded = json.dumps(forwarder.handle(rpc("tools/call", {"name": name, "arguments": {}})))
            self.assertNotIn("synthetic-access-token", encoded)
            self.assertNotIn("synthetic-client-secret", encoded)


if __name__ == "__main__":
    unittest.main()
