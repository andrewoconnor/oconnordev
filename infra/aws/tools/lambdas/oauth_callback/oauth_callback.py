from __future__ import annotations

import base64
import binascii
import html
import json
import os
import re
import urllib.parse

SESSION = re.compile(r"urn:ietf:params:oauth:request_uri:[A-Za-z0-9._~-]+")
MAX_SESSION = 1024
MAX_BODY = 8192
MAX_PASSWORD = 256
MAX_MAC = 128
MAC_PREFIX = b"schwab-consent:"
COOKIE = "__Host-consent"
COOKIE_SECONDS = 600
AUTHORIZE_PATH = "/identities/oauth2/authorize"

PAGE = (
    "<!doctype html><html lang=en><meta charset=utf-8>"
    "<meta name=viewport content='width=device-width, initial-scale=1'>"
    "<title>{title}</title><body style='font-family:system-ui;margin:3rem'>"
    "<h1>{title}</h1><p>{text}</p>{form}</body></html>"
)
FORM = (
    "<form method=post action=/callback>"
    "<input type=hidden name=session_id value='{session}'>"
    "<label>Password <input type=password name=password required "
    "autocomplete=current-password autofocus></label> "
    "<button>Approve</button></form>"
)
HEADERS = {
    "cache-control": "no-store",
    "referrer-policy": "no-referrer",
}


def page(status: int, title: str, text: str, session: str = "", cookies=None) -> dict:
    form = FORM.format(session=html.escape(session, quote=True)) if session else ""
    response = {
        "statusCode": status,
        "headers": {
            **HEADERS,
            "content-type": "text/html; charset=utf-8",
            "content-security-policy": (
                "default-src 'none'; style-src 'unsafe-inline'; "
                "form-action 'self'; frame-ancestors 'none'"
            ),
        },
        "body": PAGE.format(title=title, text=text, form=form),
    }
    if cookies:
        response["cookies"] = cookies
    return response


def unavailable() -> dict:
    return page(503, "Try again later", "The service is busy. Try again soon.")


def binding_cookie(value: str, seconds: int) -> str:
    return (
        f"{COOKIE}={value}; Max-Age={seconds}; Path=/; Secure; HttpOnly; SameSite=Lax"
    )


def valid_session(session: str) -> bool:
    return len(session) <= MAX_SESSION and SESSION.fullmatch(session) is not None


def fields(text: str) -> dict[str, str]:
    if len(text) > MAX_BODY:
        return {}
    try:
        parsed = urllib.parse.parse_qs(text, max_num_fields=4)
    except ValueError:
        return {}
    return {key: values[0] for key, values in parsed.items() if len(values) == 1}


def form_fields(event: dict) -> dict[str, str]:
    body = event.get("body") or ""
    if len(body) > MAX_BODY * 2:
        return {}
    if event.get("isBase64Encoded"):
        try:
            body = base64.b64decode(body, validate=True).decode()
        except ValueError:
            return {}
    return fields(body)


def request_cookie(event: dict) -> str:
    for item in event.get("cookies") or []:
        name, _, value = item.partition("=")
        if name.strip() == COOKIE:
            return value.strip()
    return ""


def error_code(error: Exception) -> str:
    response = getattr(error, "response", None)
    return (
        response.get("Error", {}).get("Code", "") if isinstance(response, dict) else ""
    )


def log(event: str, error: Exception) -> None:
    print(
        json.dumps({"event": event, "error": error_code(error) or type(error).__name__})
    )


def bound(kms, config: dict, session: str, mac_text: str) -> bool:
    if not mac_text or len(mac_text) > MAX_MAC:
        return False
    try:
        mac = base64.urlsafe_b64decode(mac_text + "=" * (-len(mac_text) % 4))
    except (binascii.Error, ValueError):
        return False
    try:
        return kms.verify_mac(
            KeyId=config["mac_key_id"],
            MacAlgorithm="HMAC_SHA_256",
            Message=MAC_PREFIX + session.encode(),
            Mac=mac,
        )["MacValid"]
    except Exception as error:
        if error_code(error) == "KMSInvalidMacException":
            return False
        raise


def authorization_url(url: str, region: str) -> bool:
    parts = urllib.parse.urlsplit(url)
    return (
        parts.scheme == "https"
        and parts.netloc == f"bedrock-agentcore.{region}.amazonaws.com"
        and parts.path == AUTHORIZE_PATH
        and not parts.fragment
    )


def start(event: dict, kms, config: dict) -> dict:
    query = fields(event.get("rawQueryString") or "")
    session, url, mac = (query.get(key, "") for key in ("session_id", "url", "mac"))
    if not valid_session(session) or not authorization_url(url, config["region"]):
        return page(400, "Invalid link", "Ask Hermes again for a new link.")
    try:
        if not bound(kms, config, session, mac):
            return page(403, "Invalid link", "Ask Hermes again for a new link.")
    except Exception as error:
        log("binding_check_failed", error)
        return unavailable()
    return {
        "statusCode": 302,
        "headers": {**HEADERS, "location": url},
        "cookies": [binding_cookie(mac, COOKIE_SECONDS)],
    }


def sign_in(cognito, config: dict, password: str, session: str) -> dict | None:
    try:
        result = cognito.admin_initiate_auth(
            UserPoolId=config["user_pool_id"],
            ClientId=config["client_id"],
            AuthFlow="ADMIN_USER_PASSWORD_AUTH",
            AuthParameters={"USERNAME": config["username"], "PASSWORD": password},
        )
    except Exception as error:
        log("owner_sign_in_failed", error)
        if error_code(error) == "NotAuthorizedException":
            return page(
                401, "Sign-in failed", "Check the password and try again.", session
            )
        return unavailable()
    if "AuthenticationResult" not in result:
        print(json.dumps({"event": "owner_sign_in_challenged"}))
        return page(401, "Sign-in failed", "The owner sign-in needs another step.")
    return None


def callback(event: dict, agentcore, cognito, kms, config: dict, method: str):
    if method == "GET":
        session = fields(event.get("rawQueryString") or "").get("session_id", "")
    else:
        posted = form_fields(event)
        session = posted.get("session_id", "")
        password = posted.get("password", "")
        if not 0 < len(password) <= MAX_PASSWORD:
            session = ""
    if not valid_session(session):
        return page(400, "Missing session", "Open the authorization link again.")
    try:
        if not bound(kms, config, session, request_cookie(event)):
            return page(
                403,
                "Wrong browser",
                "Open the link from Hermes in this browser and approve again.",
            )
    except Exception as error:
        log("binding_check_failed", error)
        return unavailable()
    if method == "GET":
        return page(200, "Approve access", "Enter the owner password.", session)
    failed = sign_in(cognito, config, password, session)
    if failed:
        return failed
    try:
        agentcore.complete_resource_token_auth(
            sessionUri=session,
            userIdentifier={"userId": config["user_id"]},
        )
    except Exception as error:
        print(
            json.dumps(
                {
                    "event": "consent_completion_failed",
                    "error": type(error).__name__,
                    "detail": str(error)[:500],
                }
            )
        )
        return page(
            502,
            "Authorization failed",
            "The consent could not be completed. Ask Hermes again for a new link.",
        )
    return page(
        200,
        "Access approved",
        "You can close this page and retry the request.",
        cookies=[binding_cookie("", 0)],
    )


def handle(event: dict, agentcore, cognito, kms, config: dict) -> dict:
    path = event.get("rawPath")
    method = event.get("requestContext", {}).get("http", {}).get("method")
    if path == "/start" and method == "GET":
        return start(event, kms, config)
    if path == "/callback" and method in ("GET", "POST"):
        return callback(event, agentcore, cognito, kms, config, method)
    if path in ("/start", "/callback"):
        return page(405, "Not allowed", "Open the authorization link again.")
    return page(404, "Not found", "This page does not exist.")


def handler(event, context):
    import boto3

    return handle(
        event,
        boto3.client("bedrock-agentcore"),
        boto3.client("cognito-idp"),
        boto3.client("kms"),
        {
            "user_pool_id": os.environ["USER_POOL_ID"],
            "client_id": os.environ["CLIENT_ID"],
            "username": os.environ["USERNAME"],
            "user_id": os.environ["USER_ID"],
            "mac_key_id": os.environ["MAC_KEY_ID"],
            "region": os.environ["AWS_REGION"],
        },
    )
