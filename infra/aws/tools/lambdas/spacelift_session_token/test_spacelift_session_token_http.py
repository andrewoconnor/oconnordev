"""Tests for the session-token Lambda's bounded MCP verification."""

import importlib.util
import json
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROTATION_MODULE = Path(__file__).resolve().with_name("spacelift_session_token.py")
TEST_ENV = {
    "API_KEY_SECRET_ID": "api-key-secret",
    "TOKEN_SECRET_ID": "session-token-secret",
    "GRAPHQL_ENDPOINT": "https://example.invalid/graphql",
    "VERIFY_ENDPOINT": "https://example.invalid/mcp",
    "VERIFY_EXPECTED_TOOLS_JSON": '["discover", "provider", "query"]',
}


def load_rotation_module():
    boto3_stub = types.ModuleType("boto3")
    boto3_stub.__dict__["client"] = Mock()
    spec = importlib.util.spec_from_file_location(
        "spacelift_session_token_http_under_test", ROTATION_MODULE
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load rotation module from {ROTATION_MODULE}")
    module = importlib.util.module_from_spec(spec)
    with (
        patch.dict(os.environ, TEST_ENV),
        patch.dict(sys.modules, {"boto3": boto3_stub}),
    ):
        spec.loader.exec_module(module)
    return module


class SessionTokenHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rotation = load_rotation_module()

    def test_verify_requires_exact_expected_tool_allowlist(self):
        listing = json.dumps(
            {"result": {"tools": [{"name": "query"}, {"name": "mutate"}]}}
        )

        with (
            patch.object(self.rotation, "_post", return_value=listing) as post,
            self.assertRaisesRegex(
                self.rotation.RotationError, "verify_tool_allowlist_mismatch"
            ),
        ):
            self.rotation._verify("candidate-token")

        post.assert_called_once()

    def test_allowlist_match_is_followed_by_useful_read(self):
        listing = json.dumps(
            {
                "result": {
                    "tools": [
                        {"name": "discover"},
                        {"name": "provider"},
                        {"name": "query"},
                    ]
                }
            }
        )
        read_result = json.dumps(
            {
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(
                                {
                                    "stack": {
                                        "id": "oconnordev-tools",
                                        "state": "FINISHED",
                                    }
                                }
                            ),
                        }
                    ]
                }
            }
        )

        with patch.object(
            self.rotation, "_post", side_effect=[listing, read_result]
        ) as post:
            self.assertEqual(
                self.rotation._verify("candidate-token"),
                ["discover", "provider", "query"],
            )

        self.assertEqual(post.call_count, 2)
        read_request = post.call_args_list[1].args[1]
        self.assertEqual(read_request["method"], "tools/call")
        self.assertEqual(read_request["params"]["name"], "query")
        self.assertEqual(read_request["params"]["arguments"]["operation"], "stack")

    def test_failed_useful_read_fails_verification(self):
        listing = json.dumps(
            {
                "result": {
                    "tools": [
                        {"name": "discover"},
                        {"name": "provider"},
                        {"name": "query"},
                    ]
                }
            }
        )
        failed_read = json.dumps(
            {"result": {"isError": True, "content": [{"text": "denied"}]}}
        )

        with (
            patch.object(self.rotation, "_post", side_effect=[listing, failed_read]),
            self.assertRaisesRegex(self.rotation.RotationError, "verify_read_failed"),
        ):
            self.rotation._verify("candidate-token")

    def test_http_timeout_is_bounded_by_remaining_lambda_time(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = b"{}"
        context = Mock()
        context.get_remaining_time_in_millis.return_value = 7000

        with patch.object(
            self.rotation.urllib.request, "urlopen", return_value=response
        ) as urlopen:
            self.rotation._post("https://example.invalid", {}, {}, context=context)

        self.assertEqual(urlopen.call_args.kwargs["timeout"], 2)

    def test_http_timeout_stops_before_lambda_safety_margin(self):
        context = Mock()
        context.get_remaining_time_in_millis.return_value = 2000

        with self.assertRaisesRegex(
            self.rotation.RotationError, "http_deadline_exhausted"
        ):
            self.rotation._post("https://example.invalid", {}, {}, context=context)


if __name__ == "__main__":
    unittest.main()
