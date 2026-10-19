from __future__ import annotations

import base64
import json
import os
import urllib.parse
import urllib.request

PAGE = (
    "<!doctype html><html lang=en><meta charset=utf-8>"
    "<meta name=viewport content='width=device-width, initial-scale=1'>"
    "<title>{title}</title><body style='font-family:system-ui;margin:3rem'>"
    "<h1>{title}</h1><p>{text}</p></body></html>"
)


def page(status: int, title: str, text: str) -> dict:
    return {
        "statusCode": status,
        "headers": {
            "content-type": "text/html; charset=utf-8",
            "cache-control": "no-store",
            "content-security-policy": "default-src 'none'; style-src 'unsafe-inline'",
            "referrer-policy": "no-referrer",
        },
        "body": PAGE.format(title=title, text=text),
    }


def adapter_token(cognito, identity_env: dict) -> str:
    client = cognito.describe_user_pool_client(
        UserPoolId=identity_env["USER_POOL_ID"], ClientId=identity_env["CLIENT_ID"]
    )["UserPoolClient"]
    basic = base64.b64encode(
        f"{client['ClientId']}:{client['ClientSecret']}".encode()
    ).decode()
    request = urllib.request.Request(
        identity_env["TOKEN_URL"],
        data=urllib.parse.urlencode(
            {"grant_type": "client_credentials", "scope": identity_env["SCOPE"]}
        ).encode(),
        headers={
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read())["access_token"]


def handle(event: dict, cognito, agentcore, identity_env: dict) -> dict:
    if event.get("rawPath") != "/callback":
        return page(404, "Not found", "This page does not exist.")
    session = (event.get("queryStringParameters") or {}).get("session_id", "")
    if not session or len(session) > 2048:
        return page(400, "Missing session", "Open the authorization link again.")
    try:
        agentcore.complete_resource_token_auth(
            sessionUri=session,
            userIdentifier={"userToken": adapter_token(cognito, identity_env)},
        )
    except Exception:
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
        boto3.client("cognito-idp"),
        boto3.client("bedrock-agentcore"),
        os.environ,
    )
