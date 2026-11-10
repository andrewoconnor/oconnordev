import base64
import json
import unittest
import urllib.parse
from unittest import mock

import oauth_callback

SESSION = "urn:ietf:params:oauth:request_uri:abc-123"
CONFIG = {
    "user_pool_id": "us-east-1_pool",
    "client_id": "client",
    "username": "owner",
    "user_id": "owner",
}


class AgentCore:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    def complete_resource_token_auth(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("denied")


class Cognito:
    def __init__(self, result=None, fail=False):
        self.calls, self.fail = [], fail
        self.result = {"AuthenticationResult": {}} if result is None else result

    def admin_initiate_auth(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("Incorrect username or password.")
        return self.result


def get(session=SESSION, path="/callback"):
    return {
        "rawPath": path,
        "requestContext": {"http": {"method": "GET"}},
        "queryStringParameters": {"session_id": session},
    }


def post(fields, encode=False):
    body = urllib.parse.urlencode(fields)
    if encode:
        body = base64.b64encode(body.encode()).decode()
    return {
        "rawPath": "/callback",
        "requestContext": {"http": {"method": "POST"}},
        "body": body,
        "isBase64Encoded": encode,
    }


class OAuthCallbackTests(unittest.TestCase):
    def test_get_shows_password_form_without_completing(self):
        agentcore, cognito = AgentCore(), Cognito()
        response = oauth_callback.handle(get(), agentcore, cognito, CONFIG)
        self.assertEqual(response["statusCode"], 200)
        self.assertIn("type=password", response["body"])
        self.assertIn(f"value='{SESSION}'", response["body"])
        self.assertEqual(agentcore.calls, [])
        self.assertEqual(cognito.calls, [])
        self.assertEqual(response["headers"]["cache-control"], "no-store")
        self.assertIn(
            "form-action 'self'", response["headers"]["content-security-policy"]
        )
        self.assertIn(
            "frame-ancestors 'none'", response["headers"]["content-security-policy"]
        )

    def test_owner_password_completes_session_for_owner(self):
        for encode in (False, True):
            agentcore, cognito = AgentCore(), Cognito()
            response = oauth_callback.handle(
                post({"session_id": SESSION, "password": "pw"}, encode),
                agentcore,
                cognito,
                CONFIG,
            )
            self.assertEqual(response["statusCode"], 200)
            self.assertEqual(
                cognito.calls,
                [
                    {
                        "UserPoolId": "us-east-1_pool",
                        "ClientId": "client",
                        "AuthFlow": "ADMIN_USER_PASSWORD_AUTH",
                        "AuthParameters": {"USERNAME": "owner", "PASSWORD": "pw"},
                    }
                ],
            )
            self.assertEqual(
                agentcore.calls,
                [{"sessionUri": SESSION, "userIdentifier": {"userId": "owner"}}],
            )

    def test_failed_or_challenged_sign_in_does_not_complete(self):
        for cognito in (Cognito(fail=True), Cognito(result={"ChallengeName": "MFA"})):
            agentcore = AgentCore()
            with mock.patch("builtins.print") as printed:
                response = oauth_callback.handle(
                    post({"session_id": SESSION, "password": "pw"}),
                    agentcore,
                    cognito,
                    CONFIG,
                )
            self.assertEqual(response["statusCode"], 401)
            self.assertIn("type=password", response["body"])
            self.assertEqual(agentcore.calls, [])
            logged = printed.call_args.args[0]
            self.assertNotIn("pw", logged)
            self.assertEqual(json.loads(logged)["event"], "owner_sign_in_failed")

    def test_rejects_bad_requests_without_calls(self):
        for event, status in [
            (get(path="/"), 404),
            (get(session=""), 400),
            (get(session="urn:s"), 400),
            (get(session=SESSION + "a" * 1024), 400),
            (
                {"rawPath": "/callback", "requestContext": {"http": {"method": "PUT"}}},
                405,
            ),
            (post({"session_id": SESSION}), 400),
            (post({"session_id": "urn:s", "password": "pw"}), 400),
            (post({"session_id": SESSION, "password": "p" * 257}), 400),
            (
                {
                    **post({"session_id": SESSION, "password": "pw"}),
                    "isBase64Encoded": True,
                },
                400,
            ),
            ({**post({}), "body": "a=1&" * 5}, 400),
        ]:
            agentcore, cognito = AgentCore(), Cognito()
            response = oauth_callback.handle(event, agentcore, cognito, CONFIG)
            self.assertEqual(response["statusCode"], status, event)
            self.assertEqual(agentcore.calls, [])
            self.assertEqual(cognito.calls, [])

    def test_completion_failure_shows_generic_page_and_logs_error(self):
        with mock.patch("builtins.print") as printed:
            response = oauth_callback.handle(
                post({"session_id": SESSION, "password": "pw"}),
                AgentCore(fail=True),
                Cognito(),
                CONFIG,
            )
        self.assertEqual(response["statusCode"], 502)
        self.assertNotIn("denied", response["body"])
        logged = json.loads(printed.call_args.args[0])
        self.assertEqual(logged["error"], "RuntimeError")
        self.assertEqual(logged["detail"], "denied")
