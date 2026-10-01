"""Mint a Spacelift session JWT from the read-only API key and publish it.

The function reads the long-lived Spacelift API key, exchanges it for a session
JWT through the ``apiKeyUser`` GraphQL mutation, and writes that JWT to a
separate secret. An AgentCore EXTERNAL API-key credential provider reads the
second secret on every outbound request, so rotation is a secret write and
nothing else: this function holds no AgentCore control-plane permission.

Nothing here logs, returns or persists the API key or the JWT. Only token
metadata is recorded -- ``iat``, ``exp``, the remaining lifetime, and whether
the upstream issued a new expiry window.

That last field exists because the upstream does not mint a fresh ten-hour
session on every call. It reuses one fixed expiry window per API key, anchored
to the first mint, and re-minting returns the same ``exp`` without extending
it. A rotation is therefore only healthy while the window still has life left,
which is why the emitted metric carries the remaining seconds rather than a
plain success flag.
"""

import base64
import json
import os
import time
import urllib.error
import urllib.request

import boto3

REGION = os.environ.get("AWS_REGION")
API_KEY_SECRET_ID = os.environ["API_KEY_SECRET_ID"]
API_KEY_ID_FIELD = os.environ.get("API_KEY_ID_FIELD", "api_key_id")
API_KEY_SECRET_FIELD = os.environ.get("API_KEY_SECRET_FIELD", "api_key_secret")
TOKEN_SECRET_ID = os.environ["TOKEN_SECRET_ID"]
TOKEN_JSON_KEY = os.environ.get("TOKEN_JSON_KEY", "token")
GRAPHQL_ENDPOINT = os.environ["GRAPHQL_ENDPOINT"]
METRIC_NAMESPACE = os.environ.get("METRIC_NAMESPACE", "Hermes/SpaceliftAuth")
METRIC_REMAINING = os.environ.get("METRIC_REMAINING", "SessionTokenRemainingSeconds")
HTTP_TIMEOUT_SECONDS = int(os.environ.get("HTTP_TIMEOUT_SECONDS", "15"))
VERIFY_ENDPOINT = os.environ.get("VERIFY_ENDPOINT", "")

MUTATION = (
    "mutation GetSpaceliftToken($id: ID!, $secret: String!) "
    "{ apiKeyUser(id: $id, secret: $secret) { jwt } }"
)


class RotationError(Exception):
    """A rotation failure whose message is safe to log."""


def _log(event, **fields):
    print(json.dumps({"event": event, **fields}, sort_keys=True), flush=True)


def _claim(token, name):
    try:
        segment = token.split(".")[1]
        payload = json.loads(base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4)))
        return payload.get(name)
    except Exception:
        return None


def _post(url, payload, headers):
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), method="POST", headers=headers
    )
    with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
        return response.read().decode("utf-8", "replace")


def _mint(key_id, key_secret):
    """Exchange the API key for a session JWT.

    The mutation answers HTTP 200 even when the credential is rejected, so a
    null ``apiKeyUser`` is an authentication failure and not a success.
    """
    try:
        body = _post(
            GRAPHQL_ENDPOINT,
            {"query": MUTATION, "variables": {"id": key_id, "secret": key_secret}},
            {"Content-Type": "application/json"},
        )
    except urllib.error.HTTPError as error:
        raise RotationError(f"graphql_http_{error.code}") from None
    except Exception as error:
        raise RotationError(f"graphql_transport_{type(error).__name__}") from None

    try:
        document = json.loads(body)
    except ValueError:
        raise RotationError("graphql_response_not_json") from None

    if document.get("errors"):
        raise RotationError("graphql_returned_errors")

    user = (document.get("data") or {}).get("apiKeyUser")
    if not user or not user.get("jwt"):
        raise RotationError("apikeyuser_null")

    return user["jwt"]


def _tool_names(body):
    """Read tool names out of an MCP response, tolerating SSE framing."""
    documents = []
    try:
        documents.append(json.loads(body))
    except ValueError:
        for line in body.splitlines():
            if line.startswith("data:"):
                try:
                    documents.append(json.loads(line[5:].strip()))
                except ValueError:
                    continue

    for document in documents:
        result = (document or {}).get("result") or {}
        tools = result.get("tools")
        if isinstance(tools, list):
            return [tool.get("name") for tool in tools if isinstance(tool, dict)]
    return None


def _verify(token):
    """Confirm the minted JWT reaches the narrowed MCP endpoint.

    Only the tool count is recorded; the response body is never logged.
    """
    if not VERIFY_ENDPOINT:
        return None

    try:
        body = _post(
            VERIFY_ENDPOINT,
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            {
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "Authorization": f"Bearer {token}",
            },
        )
    except urllib.error.HTTPError as error:
        raise RotationError(f"verify_http_{error.code}") from None
    except Exception as error:
        raise RotationError(f"verify_transport_{type(error).__name__}") from None

    names = _tool_names(body)
    if names is None:
        raise RotationError("verify_response_unparseable")
    return names


def _previous_exp(secrets):
    """Read the expiry currently published, so a rolled window is detectable."""
    try:
        current = json.loads(secrets.get_secret_value(SecretId=TOKEN_SECRET_ID)["SecretString"])
    except Exception:
        return None
    token = current.get(TOKEN_JSON_KEY) if isinstance(current, dict) else None
    return _claim(token, "exp") if token else None


def handler(event, context):
    secrets = boto3.client("secretsmanager", region_name=REGION)

    try:
        document = json.loads(
            secrets.get_secret_value(SecretId=API_KEY_SECRET_ID)["SecretString"]
        )
        key_id = document[API_KEY_ID_FIELD]
        key_secret = document[API_KEY_SECRET_FIELD]
    except Exception as error:
        _log("failed", stage="api_key_secret_read", error=type(error).__name__)
        raise

    _log("api_key_loaded", key_id_length=len(key_id))

    try:
        token = _mint(key_id, key_secret)
    except RotationError as error:
        _log("failed", stage="mint", error=str(error))
        raise

    issued_at = _claim(token, "iat")
    expires_at = _claim(token, "exp")
    if expires_at is None:
        _log("failed", stage="mint", error="minted_token_missing_exp")
        raise RotationError("minted_token_missing_exp")

    remaining = expires_at - time.time()
    previous_exp = _previous_exp(secrets)
    window_rolled = previous_exp is not None and previous_exp != expires_at

    try:
        tools = _verify(token)
    except RotationError as error:
        _log("failed", stage="verify", error=str(error))
        raise

    secrets.put_secret_value(
        SecretId=TOKEN_SECRET_ID, SecretString=json.dumps({TOKEN_JSON_KEY: token})
    )

    cloudwatch = boto3.client("cloudwatch", region_name=REGION)
    cloudwatch.put_metric_data(
        Namespace=METRIC_NAMESPACE,
        MetricData=[
            {
                "MetricName": METRIC_REMAINING,
                "Value": remaining,
                "Unit": "Seconds",
                "Dimensions": [{"Name": "SecretId", "Value": TOKEN_SECRET_ID}],
            }
        ],
    )

    _log(
        "rotated",
        iat=issued_at,
        exp=expires_at,
        lifetime_seconds=(expires_at - issued_at) if issued_at else None,
        remaining_seconds=round(remaining, 3),
        previous_exp=previous_exp,
        window_rolled=window_rolled,
        tool_count=len(tools) if tools is not None else None,
    )

    return {
        "exp": expires_at,
        "remaining_seconds": round(remaining, 3),
        "window_rolled": window_rolled,
    }