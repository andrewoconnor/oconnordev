import base64
import hashlib
import hmac
import json
import unittest
import urllib.parse
from unittest import mock

import oauth_callback

SESSION = "urn:ietf:params:oauth:request_uri:abc-123"
AUTHORIZE = (
    "https://bedrock-agentcore.us-east-1.amazonaws.com/identities/oauth2/authorize"
    "?request_uri=abc-123"
)
NOW = 1_800_000_000
EXPIRES = NOW + 600
KEY = b"k" * 64


def binding(expires=EXPIRES, session=SESSION, key=KEY, signed=None):
    message = f"schwab-consent:{signed or expires}:{session}".encode()
    mac = hmac.digest(key, message, hashlib.sha256)
    return f"{expires}.{base64.urlsafe_b64encode(mac).decode().rstrip('=')}"


MAC = binding()
CONFIG = {
    "user_pool_id": "us-east-1_pool",
    "client_id": "client",
    "username": "owner",
    "user_id": "owner",
    "region": "us-east-1",
}


class ClientError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class AgentCore:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    def complete_resource_token_auth(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("denied")


class Cognito:
    def __init__(self, result=None, error=None):
        self.calls, self.error = [], error
        self.result = {"AuthenticationResult": {}} if result is None else result

    def admin_initiate_auth(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise ClientError(self.error)
        return self.result


def query(**values):
    return urllib.parse.urlencode(values)


def get(path="/callback", raw="", cookie=MAC):
    return {
        "rawPath": path,
        "rawQueryString": raw,
        "requestContext": {"http": {"method": "GET"}},
        "cookies": ["other=1", f"__Host-consent={cookie}"] if cookie else [],
    }


def post(fields, encode=False, cookie=MAC):
    body = urllib.parse.urlencode(fields)
    if encode:
        body = base64.b64encode(body.encode()).decode()
    return {
        "rawPath": "/callback",
        "requestContext": {"http": {"method": "POST"}},
        "body": body,
        "isBase64Encoded": encode,
        "cookies": [f"__Host-consent={cookie}"] if cookie else [],
    }


def run(event, agentcore=None, cognito=None, now=NOW):
    agentcore, cognito = agentcore or AgentCore(), cognito or Cognito()
    with mock.patch("oauth_callback.time.time", return_value=now + 0.5):
        response = oauth_callback.handle(event, agentcore, cognito, KEY, CONFIG)
    return response, agentcore, cognito


class StartTests(unittest.TestCase):
    def test_signed_link_sets_binding_cookie_and_redirects(self):
        response, _, _ = run(
            get("/start", query(session_id=SESSION, url=AUTHORIZE, binding=MAC), None)
        )
        self.assertEqual(response["statusCode"], 302)
        self.assertEqual(response["headers"]["location"], AUTHORIZE)
        self.assertEqual(
            response["cookies"],
            [
                f"__Host-consent={MAC}; Max-Age=600; Path=/; Secure; HttpOnly; "
                "SameSite=Lax"
            ],
        )

    def test_rejects_unsigned_links_and_other_redirects(self):
        for raw, status in [
            (query(session_id=SESSION, url=AUTHORIZE, binding=f"{EXPIRES}.YmFk"), 403),
            (
                query(session_id=SESSION, url=AUTHORIZE, binding=binding(key=b"x")),
                403,
            ),
            (
                query(
                    session_id=SESSION,
                    url=AUTHORIZE,
                    binding=binding(session=SESSION + "x"),
                ),
                403,
            ),
            (
                query(
                    session_id=SESSION,
                    url=AUTHORIZE,
                    binding=binding(expires=EXPIRES - 1, signed=EXPIRES),
                ),
                403,
            ),
            (query(session_id=SESSION, url=AUTHORIZE), 403),
            (
                query(
                    session_id=SESSION,
                    url="https://evil.example/identities/oauth2/authorize",
                    binding=MAC,
                ),
                400,
            ),
            (
                query(
                    session_id=SESSION,
                    url=AUTHORIZE.replace("us-east-1", "us-west-2"),
                    binding=MAC,
                ),
                400,
            ),
            (
                query(
                    session_id=SESSION,
                    url=AUTHORIZE.replace("https", "http"),
                    binding=MAC,
                ),
                400,
            ),
            (query(session_id="urn:s", url=AUTHORIZE, binding=MAC), 400),
            (query(session_id=SESSION, url=AUTHORIZE, binding=MAC) + "&binding=x", 403),
        ]:
            response, _, _ = run(get("/start", raw, None))
            self.assertEqual(response["statusCode"], status, raw)
            self.assertNotIn("cookies", response)

    def test_expired_or_far_future_links_set_no_cookie(self):
        for value, now in [
            (MAC, EXPIRES),
            (MAC, EXPIRES + 3600),
            (MAC, NOW - 1),
            (binding(expires=NOW + 10**6), NOW),
            (MAC.partition(".")[2], NOW),
        ]:
            response, _, _ = run(
                get(
                    "/start",
                    query(session_id=SESSION, url=AUTHORIZE, binding=value),
                    None,
                ),
                now=now,
            )
            self.assertEqual(response["statusCode"], 403, (value, now))
            self.assertNotIn("cookies", response)

    def test_cookie_lasts_only_until_the_signed_expiry(self):
        response, _, _ = run(
            get("/start", query(session_id=SESSION, url=AUTHORIZE, binding=MAC), None),
            now=NOW + 100,
        )
        self.assertIn("Max-Age=500;", response["cookies"][0])

    def test_handler_reads_the_key_once_and_fails_closed(self):
        boto3 = mock.Mock()
        boto3.client.return_value.get_parameter.return_value = {
            "Parameter": {"Value": "k" * 64}
        }
        env = {
            "LINK_KEY_PARAMETER": "/hermes/key",
            "USER_POOL_ID": "p",
            "CLIENT_ID": "c",
            "USERNAME": "owner",
            "USER_ID": "owner",
            "AWS_REGION": "us-east-1",
        }
        event = get("/start", query(session_id=SESSION, url=AUTHORIZE, binding=MAC))
        with (
            mock.patch.dict("sys.modules", {"boto3": boto3}),
            mock.patch.dict("os.environ", env),
            mock.patch.object(oauth_callback, "KEY", []),
            mock.patch("oauth_callback.time.time", return_value=NOW),
        ):
            self.assertEqual(oauth_callback.handler(event, None)["statusCode"], 302)
            self.assertEqual(oauth_callback.handler(event, None)["statusCode"], 302)
        boto3.client.return_value.get_parameter.assert_called_once_with(
            Name="/hermes/key", WithDecryption=True
        )
        boto3.client.return_value.get_parameter.side_effect = RuntimeError("denied")
        with (
            mock.patch.dict("sys.modules", {"boto3": boto3}),
            mock.patch.dict("os.environ", env),
            mock.patch.object(oauth_callback, "KEY", []),
            mock.patch("builtins.print"),
        ):
            self.assertEqual(oauth_callback.handler(event, None)["statusCode"], 503)


class CallbackTests(unittest.TestCase):
    def test_get_with_binding_cookie_shows_password_form(self):
        response, agentcore, cognito = run(get(raw=query(session_id=SESSION)))
        self.assertEqual(response["statusCode"], 200)
        self.assertIn("type=password", response["body"])
        self.assertIn(f"value='{SESSION}'", response["body"])
        self.assertEqual((agentcore.calls, cognito.calls), ([], []))
        self.assertEqual(response["headers"]["cache-control"], "no-store")
        policy = response["headers"]["content-security-policy"]
        self.assertIn("form-action 'self'", policy)
        self.assertIn("frame-ancestors 'none'", policy)

    def test_browser_without_binding_cookie_is_rejected_before_sign_in(self):
        for event in (
            get(raw=query(session_id=SESSION), cookie=None),
            get(raw=query(session_id=SESSION), cookie=f"{EXPIRES}.YmFk"),
            post({"session_id": SESSION, "password": "pw"}, cookie=None),
            post({"session_id": SESSION, "password": "pw"}, cookie=f"{EXPIRES}.YmFk"),
        ):
            response, agentcore, cognito = run(event)
            self.assertEqual(response["statusCode"], 403)
            self.assertEqual((agentcore.calls, cognito.calls), ([], []))

    def test_expired_cookie_never_reaches_cognito(self):
        for event in (
            get(raw=query(session_id=SESSION)),
            post({"session_id": SESSION, "password": "pw"}),
        ):
            response, agentcore, cognito = run(event, now=EXPIRES)
            self.assertEqual(response["statusCode"], 403)
            self.assertEqual((cognito.calls, agentcore.calls), ([], []))

    def test_owner_password_completes_session_and_clears_cookie(self):
        for encode in (False, True):
            response, agentcore, cognito = run(
                post({"session_id": SESSION, "password": "pw"}, encode)
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
            self.assertIn("__Host-consent=; Max-Age=0", response["cookies"][0])

    def test_sign_in_errors_do_not_complete(self):
        for cognito, status in [
            (Cognito(error="NotAuthorizedException"), 401),
            (Cognito(error="TooManyRequestsException"), 503),
            (Cognito(error="InternalErrorException"), 503),
            (Cognito(result={"ChallengeName": "SOFTWARE_TOKEN_MFA"}), 401),
        ]:
            with mock.patch("builtins.print") as printed:
                response, agentcore, _ = run(
                    post({"session_id": SESSION, "password": "pw"}), cognito=cognito
                )
            self.assertEqual(response["statusCode"], status)
            self.assertEqual(agentcore.calls, [])
            logged = printed.call_args.args[0]
            self.assertNotIn("pw", logged)
        self.assertEqual(json.loads(logged)["event"], "owner_sign_in_challenged")

    def test_wrong_password_shows_the_form_again(self):
        with mock.patch("builtins.print"):
            response, _, _ = run(
                post({"session_id": SESSION, "password": "pw"}),
                cognito=Cognito(error="NotAuthorizedException"),
            )
        self.assertIn("type=password", response["body"])

    def test_rejects_bad_requests_without_calls(self):
        for event, status in [
            (get(path="/", raw=query(session_id=SESSION)), 404),
            (get(raw=""), 400),
            (get(raw=query(session_id="urn:s")), 400),
            (get(raw=query(session_id=SESSION + "a" * 1024)), 400),
            ({**get(), "requestContext": {"http": {"method": "PUT"}}}, 405),
            ({**get("/start"), "requestContext": {"http": {"method": "POST"}}}, 405),
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
            response, agentcore, cognito = run(event)
            self.assertEqual(response["statusCode"], status, event)
            self.assertEqual((agentcore.calls, cognito.calls), ([], []))

    def test_completion_failure_shows_generic_page_and_logs_error(self):
        with mock.patch("builtins.print") as printed:
            response, _, _ = run(
                post({"session_id": SESSION, "password": "pw"}),
                agentcore=AgentCore(fail=True),
            )
        self.assertEqual(response["statusCode"], 502)
        self.assertNotIn("denied", response["body"])
        logged = json.loads(printed.call_args.args[0])
        self.assertEqual(logged["error"], "RuntimeError")
        self.assertEqual(logged["detail"], "denied")
