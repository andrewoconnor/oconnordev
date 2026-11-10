from __future__ import annotations

import base64
import html
import json
import os
import re
import urllib.parse

SESSION = re.compile(r"urn:ietf:params:oauth:request_uri:[A-Za-z0-9._~-]+")
MAX_SESSION = 1024
MAX_BODY = 8192
MAX_PASSWORD = 256

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


def page(status: int, title: str, text: str, session: str = "") -> dict:
    form = FORM.format(session=html.escape(session, quote=True)) if session else ""
    return {
        "statusCode": status,
        "headers": {
            "content-type": "text/html; charset=utf-8",
            "cache-control": "no-store",
            "content-security-policy": (
                "default-src 'none'; style-src 'unsafe-inline'; "
                "form-action 'self'; frame-ancestors 'none'"
            ),
            "referrer-policy": "no-referrer",
        },
        "body": PAGE.format(title=title, text=text, form=form),
    }


def valid_session(session: str) -> bool:
    return len(session) <= MAX_SESSION and SESSION.fullmatch(session) is not None


def form_fields(event: dict) -> dict[str, str]:
    body = event.get("body") or ""
    if len(body) > MAX_BODY:
        return {}
    try:
        if event.get("isBase64Encoded"):
            body = base64.b64decode(body, validate=True).decode()
        fields = urllib.parse.parse_qs(body, max_num_fields=4)
    except ValueError:
        return {}
    return {key: values[0] for key, values in fields.items() if len(values) == 1}


def handle(event: dict, agentcore, cognito, config: dict) -> dict:
    if event.get("rawPath") != "/callback":
        return page(404, "Not found", "This page does not exist.")
    method = event.get("requestContext", {}).get("http", {}).get("method")
    if method == "GET":
        session = (event.get("queryStringParameters") or {}).get("session_id", "")
        if not valid_session(session):
            return page(400, "Missing session", "Open the authorization link again.")
        return page(200, "Approve access", "Enter the owner password.", session)
    if method != "POST":
        return page(405, "Not allowed", "Open the authorization link again.")
    fields = form_fields(event)
    session = fields.get("session_id", "")
    password = fields.get("password", "")
    if not valid_session(session) or not 0 < len(password) <= MAX_PASSWORD:
        return page(400, "Missing session", "Open the authorization link again.")
    try:
        result = cognito.admin_initiate_auth(
            UserPoolId=config["user_pool_id"],
            ClientId=config["client_id"],
            AuthFlow="ADMIN_USER_PASSWORD_AUTH",
            AuthParameters={"USERNAME": config["username"], "PASSWORD": password},
        )
        if "AuthenticationResult" not in result:
            raise PermissionError(result.get("ChallengeName", "challenge"))
    except Exception as error:
        print(
            json.dumps({"event": "owner_sign_in_failed", "error": type(error).__name__})
        )
        return page(401, "Sign-in failed", "Check the password and try again.", session)
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
        200, "Access approved", "You can close this page and retry the request."
    )


def handler(event, context):
    import boto3

    return handle(
        event,
        boto3.client("bedrock-agentcore"),
        boto3.client("cognito-idp"),
        {
            "user_pool_id": os.environ["USER_POOL_ID"],
            "client_id": os.environ["CLIENT_ID"],
            "username": os.environ["USERNAME"],
            "user_id": os.environ["USER_ID"],
        },
    )
