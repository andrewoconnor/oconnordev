from __future__ import annotations

import json
import os

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


def handle(event: dict, agentcore, user_id: str) -> dict:
    if event.get("rawPath") != "/callback":
        return page(404, "Not found", "This page does not exist.")
    session = (event.get("queryStringParameters") or {}).get("session_id", "")
    if not session or len(session) > 2048:
        return page(400, "Missing session", "Open the authorization link again.")
    try:
        agentcore.complete_resource_token_auth(
            sessionUri=session,
            userIdentifier={"userId": user_id},
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
        os.environ["USER_ID"],
    )
