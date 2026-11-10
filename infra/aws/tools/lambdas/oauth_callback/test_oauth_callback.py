import base64
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
MAC = "Z29vZA"
CONFIG = {
    "user_pool_id": "us-east-1_pool",
    "client_id": "client",
    "username": "owner",
    "user_id": "owner",
    "mac_key_id": "key",
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


class Kms:
    def __init__(self, error=None):
        self.calls, self.error = [], error

    def verify_mac(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise ClientError(self.error)
        if kwargs["Mac"] != b"good":
            raise ClientError("KMSInvalidMacException")
        return {"MacValid": True}


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


def run(event, agentcore=None, cognito=None, kms=None):
    agentcore, cognito, kms = (
        agentcore or AgentCore(),
        cognito or Cognito(),
        kms or Kms(),
    )
    return (
        oauth_callback.handle(event, agentcore, cognito, kms, CONFIG),
        agentcore,
        cognito,
    )


class StartTests(unittest.TestCase):
    def test_signed_link_sets_binding_cookie_and_redirects(self):
        kms = Kms()
        response, _, _ = run(
            get("/start", query(session_id=SESSION, url=AUTHORIZE, mac=MAC), None),
            kms=kms,
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
        self.assertEqual(
            kms.calls,
            [
                {
                    "KeyId": "key",
                    "MacAlgorithm": "HMAC_SHA_256",
                    "Message": b"schwab-consent:" + SESSION.encode(),
                    "Mac": b"good",
                }
            ],
        )

    def test_rejects_unsigned_links_and_other_redirects(self):
        for raw, status in [
            (query(session_id=SESSION, url=AUTHORIZE, mac="YmFk"), 403),
            (query(session_id=SESSION, url=AUTHORIZE), 403),
            (
                query(
                    session_id=SESSION,
                    url="https://evil.example/identities/oauth2/authorize",
                    mac=MAC,
                ),
                400,
            ),
            (
                query(
                    session_id=SESSION,
                    url=AUTHORIZE.replace("us-east-1", "us-west-2"),
                    mac=MAC,
                ),
                400,
            ),
            (
                query(
                    session_id=SESSION, url=AUTHORIZE.replace("https", "http"), mac=MAC
                ),
                400,
            ),
            (query(session_id="urn:s", url=AUTHORIZE, mac=MAC), 400),
            (query(session_id=SESSION, url=AUTHORIZE, mac=MAC) + "&mac=x", 403),
        ]:
            response, _, _ = run(get("/start", raw, None))
            self.assertEqual(response["statusCode"], status, raw)
            self.assertNotIn("cookies", response)

    def test_kms_failure_is_unavailable(self):
        for event in (
            get("/start", query(session_id=SESSION, url=AUTHORIZE, mac=MAC), None),
            get(raw=query(session_id=SESSION)),
        ):
            with mock.patch("builtins.print"):
                response, _, cognito = run(event, kms=Kms(error="ThrottlingException"))
            self.assertEqual(response["statusCode"], 503)
            self.assertEqual(cognito.calls, [])


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
            get(raw=query(session_id=SESSION), cookie="YmFk"),
            post({"session_id": SESSION, "password": "pw"}, cookie=None),
            post({"session_id": SESSION, "password": "pw"}, cookie="YmFk"),
        ):
            response, agentcore, cognito = run(event)
            self.assertEqual(response["statusCode"], 403)
            self.assertEqual((agentcore.calls, cognito.calls), ([], []))

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
