from __future__ import annotations

import urllib.error
import urllib.request

UPSTREAM = "https://api.schwabapi.com"
PATHS = ("/trader/v1/accounts", "/marketdata/v1/")


def reply(status: int, body: str, content_type: str = "application/json") -> dict:
    return {
        "statusCode": status,
        "headers": {"content-type": content_type},
        "body": body,
    }


def allowed(path: str) -> bool:
    return (
        path.startswith(PATHS)
        and ".." not in path
        and "//" not in path
        and "\\" not in path
    )


def handle(event: dict, opener=urllib.request.urlopen) -> dict:
    method = event.get("requestContext", {}).get("http", {}).get("method")
    path = event.get("rawPath", "")
    if method != "GET" or not allowed(path):
        return reply(403, '{"error": "Only read-only Schwab GET paths are allowed"}')
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    authorization = headers.get("authorization", "")
    if not authorization.startswith("Bearer "):
        return reply(401, '{"error": "Missing bearer token"}')
    query = event.get("rawQueryString", "")
    request = urllib.request.Request(
        f"{UPSTREAM}{path}{'?' + query if query else ''}",
        headers={"Authorization": authorization, "Accept": "application/json"},
        method="GET",
    )
    try:
        with opener(request, timeout=20) as response:
            return reply(
                response.status,
                response.read().decode("utf-8", "replace"),
                response.headers.get("content-type", "application/json"),
            )
    except urllib.error.HTTPError as error:
        return reply(
            error.code,
            error.read().decode("utf-8", "replace"),
            error.headers.get("content-type", "application/json"),
        )


def handler(event, context):
    return handle(event)
