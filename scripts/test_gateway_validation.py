import unittest

from scripts.gateway_validation import (
    EXPECTED_LIVE_ENV,
    INVALID_OWNER_PROBE,
    INVALID_REPOSITORY_PROBE,
    SmokeCheckError,
    build_read_only_calls,
    missing_live_configuration,
    run_gateway_checks,
)

TARGET_TOOLS = {
    "github": {
        "get_file_contents",
        "list_branches",
        "get_commit",
        "create_branch",
        "push_files",
        "delete_file",
        "create_pull_request",
        "pull_request_read",
        "get_job_logs",
    },
    "aws": {
        "aws___get_regional_availability",
        "aws___get_tasks",
        "aws___list_regions",
        "aws___read_documentation",
        "aws___retrieve_skill",
        "aws___run_script",
        "aws___search_documentation",
    },
    "spacelift": {"discover", "provider", "query"},
}


class FakeForwarder:
    def __init__(
        self,
        *,
        discovery=None,
        deny_probes=True,
        denial_format="result",
        fail_positive=None,
        empty_positive=None,
        required_tool=None,
    ):
        self.discovery = discovery or set().union(*TARGET_TOOLS.values())
        self.deny_probes = deny_probes
        self.denial_format = denial_format
        self.fail_positive = fail_positive
        self.empty_positive = empty_positive
        self.required_tool = required_tool
        self.calls = []

    def handle(self, message):
        method = message["method"]
        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": message["id"],
                "result": {"protocolVersion": "2025-03-26"},
            }
        if method == "notifications/initialized":
            return None
        if method == "tools/list":
            tools = []
            for name in sorted(self.discovery):
                required = (
                    ["unconfigured"]
                    if name == self.required_tool
                    else ["owner", "repo", "path"]
                    if name == "get_file_contents"
                    else []
                )
                tools.append(
                    {
                        "name": name,
                        "inputSchema": {
                            "type": "object",
                            "properties": {},
                            "required": required,
                        },
                    }
                )
            return {"jsonrpc": "2.0", "id": message["id"], "result": {"tools": tools}}
        if method == "tools/call":
            name = message["params"]["name"]
            args = message["params"].get("arguments", {})
            self.calls.append((name, args))
            probe = (
                args.get("owner") == INVALID_OWNER_PROBE
                or args.get("repo") == INVALID_REPOSITORY_PROBE
            )
            if probe and self.deny_probes:
                denial_message = (
                    "Tool Execution Denied: Tool call not allowed due to "
                    "policy enforcement"
                )
                if self.denial_format == "jsonrpc":
                    return {
                        "jsonrpc": "2.0",
                        "id": message["id"],
                        "error": {"code": -32002, "message": denial_message},
                    }
                return {
                    "jsonrpc": "2.0",
                    "id": message["id"],
                    "result": {
                        "isError": True,
                        "content": [
                            {
                                "type": "text",
                                "text": "AuthorizeActionException - " + denial_message,
                            }
                        ],
                    },
                }
            if probe:
                return {
                    "jsonrpc": "2.0",
                    "id": message["id"],
                    "result": {
                        "isError": False,
                        "content": [{"type": "text", "text": "unexpectedly allowed"}],
                    },
                }
            if name == self.fail_positive:
                return {
                    "jsonrpc": "2.0",
                    "id": message["id"],
                    "result": {
                        "isError": True,
                        "content": [{"type": "text", "text": "failed"}],
                    },
                }
            if name == self.empty_positive:
                return {
                    "jsonrpc": "2.0",
                    "id": message["id"],
                    "result": {"isError": False},
                }
            return {
                "jsonrpc": "2.0",
                "id": message["id"],
                "result": {
                    "isError": False,
                    "content": [{"type": "text", "text": "safe read"}],
                },
            }
        raise AssertionError(f"unexpected method {method}")


class GatewaySmokeTests(unittest.TestCase):
    def test_live_configuration_names_are_explicit_and_missing_values_reported(self):
        self.assertEqual(
            set(EXPECTED_LIVE_ENV),
            {
                "HERMES_AGENTCORE_GATEWAY_URL",
                "HERMES_AGENTCORE_COGNITO_TOKEN_URL",
                "HERMES_AGENTCORE_COGNITO_CLIENT_ID",
                "HERMES_AGENTCORE_COGNITO_CLIENT_SECRET",
            },
        )
        missing = missing_live_configuration({}, github_owner="", github_repo="")
        self.assertTrue(all(name in missing for name in EXPECTED_LIVE_ENV))
        self.assertIn("HERMES_SMOKE_GITHUB_OWNER", missing)
        self.assertIn("HERMES_SMOKE_GITHUB_REPO", missing)
        configured = {name: "set" for name in EXPECTED_LIVE_ENV}
        self.assertEqual(
            missing_live_configuration(
                configured, github_owner="andrewoconnor", github_repo="oconnordev"
            ),
            [],
        )
        configured["HERMES_SMOKE_GITHUB_OWNER"] = "andrewoconnor"
        configured["HERMES_SMOKE_GITHUB_REPO"] = "oconnordev"
        self.assertEqual(
            missing_live_configuration(configured, github_owner=None, github_repo=None),
            [],
        )

    def test_safe_read_only_call_is_configured_for_each_target(self):
        calls = build_read_only_calls(TARGET_TOOLS, "andrewoconnor", "oconnordev")
        self.assertEqual(set(calls), {"github", "aws", "spacelift"})
        self.assertEqual(
            calls["github"],
            (
                "get_file_contents",
                {"owner": "andrewoconnor", "repo": "oconnordev", "path": "README.md"},
            ),
        )
        self.assertEqual(calls["aws"], ("aws___list_regions", {}))
        self.assertEqual(calls["spacelift"], ("discover", {}))

    def test_missing_read_tool_or_unconfigured_target_fails_closed(self):
        without_read = {
            **TARGET_TOOLS,
            "github": TARGET_TOOLS["github"] - {"get_file_contents"},
        }
        with self.assertRaisesRegex(SmokeCheckError, "no safe read-only smoke tool"):
            build_read_only_calls(without_read, "andrewoconnor", "oconnordev")
        with self.assertRaisesRegex(SmokeCheckError, "no safe read-only smoke tool"):
            build_read_only_calls(
                {**TARGET_TOOLS, "extra": {"tool"}}, "andrewoconnor", "oconnordev"
            )

    def test_calls_one_read_only_tool_per_target_and_denies_out_of_scope_owner_and_repo(
        self,
    ):
        forwarder = FakeForwarder()
        messages = run_gateway_checks(
            forwarder, TARGET_TOOLS, "andrewoconnor", "oconnordev"
        )
        self.assertEqual(len(messages), 6)
        self.assertEqual(
            {name for name, _ in forwarder.calls},
            {
                "get_file_contents",
                "aws___list_regions",
                "discover",
            },
        )
        self.assertEqual(
            sum(
                args.get("owner") == INVALID_OWNER_PROBE for _, args in forwarder.calls
            ),
            1,
        )
        self.assertEqual(
            sum(
                args.get("repo") == INVALID_REPOSITORY_PROBE
                for _, args in forwarder.calls
            ),
            1,
        )
        self.assertTrue(all("PASS" in message for message in messages))

    def test_top_level_jsonrpc_policy_denial_is_recognized(self):
        forwarder = FakeForwarder(denial_format="jsonrpc")
        messages = run_gateway_checks(
            forwarder, TARGET_TOOLS, "andrewoconnor", "oconnordev"
        )
        self.assertEqual(
            sum("was denied by policy" in message for message in messages), 2
        )

    def test_unexpectedly_allowed_scope_probe_fails(self):
        with self.assertRaisesRegex(SmokeCheckError, "not confirmed"):
            run_gateway_checks(
                FakeForwarder(deny_probes=False),
                TARGET_TOOLS,
                "andrewoconnor",
                "oconnordev",
            )

    def test_discovery_mismatch_fails_before_any_tool_calls(self):
        forwarder = FakeForwarder(
            discovery=set().union(*TARGET_TOOLS.values()) - {"discover"}
        )
        with self.assertRaisesRegex(SmokeCheckError, "discovery mismatch"):
            run_gateway_checks(forwarder, TARGET_TOOLS, "andrewoconnor", "oconnordev")
        self.assertEqual(forwarder.calls, [])

    def test_unsupported_required_schema_input_fails_before_tool_calls(self):
        forwarder = FakeForwarder(required_tool="discover")
        with self.assertRaisesRegex(SmokeCheckError, "requires unconfigured inputs"):
            run_gateway_checks(forwarder, TARGET_TOOLS, "andrewoconnor", "oconnordev")
        self.assertEqual(forwarder.calls, [])

    def test_failed_positive_read_call_fails(self):
        with self.assertRaisesRegex(SmokeCheckError, "read-only smoke call.*failed"):
            run_gateway_checks(
                FakeForwarder(fail_positive="aws___list_regions"),
                TARGET_TOOLS,
                "andrewoconnor",
                "oconnordev",
            )

    def test_missing_positive_result_payload_fails(self):
        with self.assertRaisesRegex(SmokeCheckError, "no result payload"):
            run_gateway_checks(
                FakeForwarder(empty_positive="aws___list_regions"),
                TARGET_TOOLS,
                "andrewoconnor",
                "oconnordev",
            )

    def test_non_authorization_error_does_not_count_as_a_policy_denial(self):
        forwarder = FakeForwarder()
        original_handle = forwarder.handle

        def handle(message):
            response = original_handle(message)
            args = (message.get("params") or {}).get("arguments", {})
            if args.get("owner") == INVALID_OWNER_PROBE:
                return {
                    "jsonrpc": "2.0",
                    "id": message["id"],
                    "result": {
                        "isError": True,
                        "content": [
                            {"type": "text", "text": "GitHub API 404 Not Found"}
                        ],
                    },
                }
            return response

        forwarder.handle = handle
        with self.assertRaisesRegex(SmokeCheckError, "authorization denial"):
            run_gateway_checks(forwarder, TARGET_TOOLS, "andrewoconnor", "oconnordev")


if __name__ == "__main__":
    unittest.main()
