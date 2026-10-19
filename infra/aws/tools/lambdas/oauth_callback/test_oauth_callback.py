import json
import unittest
from unittest import mock

import oauth_callback

ENV = {
    "USER_POOL_ID": "us-east-1_pool",
    "CLIENT_ID": "client",
    "TOKEN_URL": "https://auth.example/oauth2/token",
    "SCOPE": "hermes-mcp/invoke",
}


class Cognito:
    def describe_user_pool_client(self, **kwargs):
        assert kwargs == {"UserPoolId": "us-east-1_pool", "ClientId": "client"}
        return {"UserPoolClient": {"ClientId": "client", "ClientSecret": "s3cret"}}


class AgentCore:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    def complete_resource_token_auth(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("denied")


class TokenResponse:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps({"access_token": "jwt"}).encode()


class OAuthCallbackTests(unittest.TestCase):
    def call(self, event, agentcore):
        with mock.patch.object(
            oauth_callback.urllib.request, "urlopen", return_value=TokenResponse()
        ) as urlopen:
            response = oauth_callback.handle(event, Cognito(), agentcore, ENV)
        return response, urlopen

    def test_binds_session_with_adapter_client_token(self):
        agentcore = AgentCore()
        response, urlopen = self.call(
            {"rawPath": "/callback", "queryStringParameters": {"session_id": "urn:s"}},
            agentcore,
        )
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(
            agentcore.calls,
            [{"sessionUri": "urn:s", "userIdentifier": {"userToken": "jwt"}}],
        )
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, ENV["TOKEN_URL"])
        self.assertIn(b"grant_type=client_credentials", request.data)
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
            response, urlopen = self.call(event, agentcore)
            self.assertEqual(response["statusCode"], status)
            self.assertEqual(agentcore.calls, [])
            urlopen.assert_not_called()

    def test_failure_shows_generic_page(self):
        response, _ = self.call(
            {"rawPath": "/callback", "queryStringParameters": {"session_id": "urn:s"}},
            AgentCore(fail=True),
        )
        self.assertEqual(response["statusCode"], 502)
        self.assertNotIn("denied", response["body"])
