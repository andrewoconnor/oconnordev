import json
import unittest
from unittest import mock

import oauth_callback


class AgentCore:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    def complete_resource_token_auth(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("denied")


class OAuthCallbackTests(unittest.TestCase):
    def test_binds_session_to_the_owner_user_id(self):
        agentcore = AgentCore()
        response = oauth_callback.handle(
            {"rawPath": "/callback", "queryStringParameters": {"session_id": "urn:s"}},
            agentcore,
            "owner",
        )
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(
            agentcore.calls,
            [{"sessionUri": "urn:s", "userIdentifier": {"userId": "owner"}}],
        )
        self.assertEqual(response["headers"]["cache-control"], "no-store")

    def test_rejects_other_paths_and_missing_sessions_without_calls(self):
        for event, status in [
            ({"rawPath": "/", "queryStringParameters": {"session_id": "x"}}, 404),
            ({"rawPath": "/callback"}, 400),
            (
                {"rawPath": "/callback", "queryStringParameters": {"session_id": ""}},
                400,
            ),
        ]:
            agentcore = AgentCore()
            response = oauth_callback.handle(event, agentcore, "owner")
            self.assertEqual(response["statusCode"], status)
            self.assertEqual(agentcore.calls, [])

    def test_failure_shows_generic_page_and_logs_error(self):
        with mock.patch("builtins.print") as printed:
            response = oauth_callback.handle(
                {
                    "rawPath": "/callback",
                    "queryStringParameters": {"session_id": "urn:s"},
                },
                AgentCore(fail=True),
                "owner",
            )
        self.assertEqual(response["statusCode"], 502)
        self.assertNotIn("denied", response["body"])
        logged = json.loads(printed.call_args.args[0])
        self.assertEqual(logged["error"], "RuntimeError")
        self.assertEqual(logged["detail"], "denied")
