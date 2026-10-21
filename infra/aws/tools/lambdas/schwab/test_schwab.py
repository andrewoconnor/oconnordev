import io
import json
import unittest
import urllib.error
from email.message import Message
from unittest import mock

import schwab

ENV = {
    "WORKLOAD_NAME": "hermes-schwab",
    "USER_ID": "owner",
    "PROVIDER_NAME": "hermes-schwab",
    "RETURN_URL": "https://callback.example/callback",
}
LINK = "https://bedrock-agentcore.us-east-1.amazonaws.com/identities/oauth2/authorize?request_uri=x"


class AgentCore:
    def __init__(self, *responses, fail=False):
        self.responses, self.fail, self.calls = list(responses), fail, []

    def get_workload_access_token_for_user_id(self, **kwargs):
        self.calls.append(("workload", kwargs))
        if self.fail:
            raise RuntimeError("denied")
        return {"workloadAccessToken": "wat"}

    def get_resource_oauth2_token(self, **kwargs):
        self.calls.append(("token", kwargs))
        return self.responses.pop(0)


class Response(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class Opener:
    def __init__(self, status=200, body=b'{"ok": true}'):
        self.status, self.body, self.requests = status, body, []

    def __call__(self, request, timeout):
        self.requests.append(request)
        if self.status != 200:
            raise urllib.error.HTTPError(
                request.full_url, self.status, "x", Message(), io.BytesIO(self.body)
            )
        return Response(self.body)


def call(tool, arguments, agentcore, opener):
    return schwab.handle(arguments, "schwab___" + tool, agentcore, ENV, opener)


class SchwabTests(unittest.TestCase):
    def test_reads_token_for_the_owner_and_sends_only_a_read_get(self):
        agentcore, opener = AgentCore({"accessToken": "t"}), Opener()
        result = call(
            "getQuotes", {"symbols": "SPCX,$SPX", "indicative": True}, agentcore, opener
        )
        self.assertEqual(result, {"ok": True})
        self.assertEqual(
            agentcore.calls,
            [
                ("workload", {"workloadName": "hermes-schwab", "userId": "owner"}),
                (
                    "token",
                    {
                        "workloadIdentityToken": "wat",
                        "resourceCredentialProviderName": "hermes-schwab",
                        "scopes": ["api"],
                        "oauth2Flow": "USER_FEDERATION",
                        "resourceOauth2ReturnUrl": ENV["RETURN_URL"],
                        "forceAuthentication": False,
                    },
                ),
            ],
        )
        request = opener.requests[0]
        self.assertEqual(
            request.full_url,
            "https://api.schwabapi.com/marketdata/v1/quotes?symbols=SPCX%2C%24SPX&indicative=true",
        )
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(request.get_header("Authorization"), "Bearer t")
        self.assertEqual(request.get_header("Accept"), "application/json")
        self.assertIsNone(request.get_header("Content-type"))

    def test_path_arguments_are_substituted_and_validated(self):
        opener = Opener()
        call(
            "getAccount",
            {"accountHash": "AB12", "fields": "positions"},
            AgentCore({"accessToken": "t"}),
            opener,
        )
        self.assertEqual(
            opener.requests[0].full_url,
            "https://api.schwabapi.com/trader/v1/accounts/AB12?fields=positions",
        )
        for bad in ["../orders", "a/b", "a?b", ""]:
            agentcore = AgentCore()
            result = call("getAccount", {"accountHash": bad}, agentcore, opener)
            self.assertTrue(result["isError"])
            self.assertEqual(agentcore.calls, [])

    def test_unknown_tools_and_arguments_are_refused_without_calls(self):
        for arguments, name in [
            ({}, "schwab___placeOrder"),
            ({"symbols": "X"}, "getQuotes"),
            ({}, "schwab___getQuotes"),
            ({"symbols": "X", "accountHash": "Y"}, "schwab___getQuotes"),
        ]:
            agentcore, opener = AgentCore(), Opener()
            result = schwab.handle(arguments, name, agentcore, ENV, opener)
            self.assertTrue(result["isError"])
            self.assertEqual((agentcore.calls, opener.requests), ([], []))

    def test_missing_token_returns_the_consent_link(self):
        opener = Opener()
        result = call(
            "getAccountNumbers", {}, AgentCore({"authorizationUrl": LINK}), opener
        )
        self.assertTrue(result["isError"])
        self.assertIn(LINK, result["content"][0]["text"])
        self.assertEqual(opener.requests, [])

    def test_rejected_token_forces_a_new_consent_link(self):
        agentcore = AgentCore({"accessToken": "t"}, {"authorizationUrl": LINK})
        result = call(
            "listAccounts", {}, agentcore, Opener(status=401, body=b"expired")
        )
        self.assertIn(LINK, result["content"][0]["text"])
        self.assertTrue(agentcore.calls[-1][1]["forceAuthentication"])

    def test_schwab_errors_are_tool_errors(self):
        result = call(
            "listAccounts",
            {},
            AgentCore({"accessToken": "t"}),
            Opener(status=400, body=b"bad"),
        )
        self.assertTrue(result["isError"])
        self.assertIn("HTTP 400: bad", result["content"][0]["text"])

    def test_identity_failure_is_logged_without_a_link(self):
        with mock.patch("builtins.print") as printed:
            result = call("listAccounts", {}, AgentCore(fail=True), Opener())
        self.assertTrue(result["isError"])
        self.assertEqual(json.loads(printed.call_args.args[0])["error"], "RuntimeError")

    def test_handler_reads_the_tool_name_from_the_client_context(self):
        context = mock.Mock()
        context.client_context.custom = {"bedrockAgentCoreToolName": "schwab___nope"}
        with mock.patch.dict("sys.modules", {"boto3": mock.Mock()}):
            result = schwab.handler({}, context)
        self.assertEqual(result["content"][0]["text"], "Unknown Schwab tool")

    def test_every_tool_is_a_read_only_path(self):
        self.assertEqual(len(schwab.TOOLS), 7)
        for tool in schwab.TOOLS.values():
            self.assertTrue(
                tool["path"].startswith(("/trader/v1/accounts", "/marketdata/v1/"))
            )
            self.assertNotIn("order", tool["path"].lower())
