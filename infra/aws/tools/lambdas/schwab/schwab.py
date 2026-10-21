from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

UPSTREAM = "https://api.schwabapi.com"
PREFIX = "schwab___"
SCOPES = ["api"]
TOOLS = {
    tool["name"]: tool
    for tool in json.loads(Path(__file__).with_name("tools.json").read_text())["tools"]
}
PATH_VALUE = re.compile(r"[A-Za-z0-9_-]{1,128}")


def failure(text: str) -> dict:
    return {"isError": True, "content": [{"type": "text", "text": text}]}


def request_url(tool: dict, arguments: dict) -> str:
    schema = tool["inputSchema"]
    unknown = set(arguments) - set(schema["properties"])
    missing = set(schema.get("required", [])) - set(arguments)
    if unknown or missing:
        raise ValueError(
            f"Unknown arguments {sorted(unknown)}; missing arguments {sorted(missing)}"
        )
    path, query = tool["path"], {}
    for name, value in arguments.items():
        text = str(value).lower() if isinstance(value, bool) else str(value)
        if "{" + name + "}" in path:
            if not PATH_VALUE.fullmatch(text):
                raise ValueError(f"Invalid {name}")
            path = path.replace("{" + name + "}", text)
        else:
            query[name] = text
    return f"{UPSTREAM}{path}{'?' + urllib.parse.urlencode(query) if query else ''}"


def schwab_token(agentcore, env: dict, force: bool = False) -> tuple[str, str]:
    try:
        workload = agentcore.get_workload_access_token_for_user_id(
            workloadName=env["WORKLOAD_NAME"], userId=env["USER_ID"]
        )["workloadAccessToken"]
        response = agentcore.get_resource_oauth2_token(
            workloadIdentityToken=workload,
            resourceCredentialProviderName=env["PROVIDER_NAME"],
            scopes=SCOPES,
            oauth2Flow="USER_FEDERATION",
            resourceOauth2ReturnUrl=env["RETURN_URL"],
            forceAuthentication=force,
        )
    except Exception as error:
        print(
            json.dumps(
                {
                    "event": "schwab_token_failed",
                    "error": type(error).__name__,
                    "detail": str(error)[:500],
                }
            )
        )
        return "", ""
    return response.get("accessToken", ""), response.get("authorizationUrl", "")


def get(url: str, token: str, opener) -> tuple[int, str]:
    request = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        method="GET",
    )
    try:
        with opener(request, timeout=20) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", "replace")


def result(status: int, body: str) -> object:
    if 200 <= status < 300:
        return json.loads(body) if body else {}
    return failure(f"Schwab returned HTTP {status}: {body[:2000]}")


def handle(event: dict, tool_name: str, agentcore, env: dict, opener) -> object:
    tool = (
        TOOLS.get(tool_name.removeprefix(PREFIX))
        if tool_name.startswith(PREFIX)
        else None
    )
    if tool is None:
        return failure("Unknown Schwab tool")
    try:
        url = request_url(tool, event or {})
    except ValueError as error:
        return failure(str(error))
    token, link = schwab_token(agentcore, env)
    if token:
        status, body = get(url, token, opener)
        if status != 401:
            return result(status, body)
        link = schwab_token(agentcore, env, force=True)[1]
    if not link:
        return failure(
            "AgentCore Identity returned no Schwab token and no consent link."
        )
    return failure(
        "Schwab needs authorization. Send the user this link. It is valid for "
        "10 minutes. The user signs in to Schwab and approves access. Then retry "
        f"the same request: {link}"
    )


def handler(event, context):
    import boto3

    custom = getattr(getattr(context, "client_context", None), "custom", None) or {}
    return handle(
        event,
        custom.get("bedrockAgentCoreToolName", ""),
        boto3.client("bedrock-agentcore"),
        os.environ,
        urllib.request.urlopen,
    )
