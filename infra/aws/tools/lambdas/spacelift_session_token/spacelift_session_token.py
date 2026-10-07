"""Mint a Spacelift session JWT from the read-only API key and publish it.

The function reads the long-lived Spacelift API key, exchanges it for a session
JWT through the ``apiKeyUser`` GraphQL mutation, and writes that JWT to a
separate secret. An AgentCore EXTERNAL API-key credential provider reads the
second secret on every outbound request, so rotation is a secret write and
nothing else: this function holds no AgentCore control-plane permission.

Nothing here logs, returns or persists the API key or the JWT. Only token
metadata is recorded -- ``iat``, ``exp``, the remaining lifetime, and whether
the expiry changed since the currently published token.
"""

import base64
import json
import math
import os
import time
import urllib.error
import urllib.request
from typing import TypeGuard

import boto3
from spacelift_session_token_http import (
    RotationError,
)
from spacelift_session_token_http import (
    _post as _http_post,
)
from spacelift_session_token_http import (
    _verify as _verify_mcp,
)

REGION = os.environ.get("AWS_REGION")
API_KEY_SECRET_ID = os.environ["API_KEY_SECRET_ID"]
API_KEY_ID_FIELD = os.environ.get("API_KEY_ID_FIELD", "api_key_id")
API_KEY_SECRET_FIELD = os.environ.get("API_KEY_SECRET_FIELD", "api_key_secret")
TOKEN_SECRET_ID = os.environ["TOKEN_SECRET_ID"]
TOKEN_JSON_KEY = os.environ.get("TOKEN_JSON_KEY", "token")
GRAPHQL_ENDPOINT = os.environ["GRAPHQL_ENDPOINT"]
METRIC_NAMESPACE = os.environ.get("METRIC_NAMESPACE", "Hermes/SpaceliftAuth")
METRIC_REMAINING = os.environ.get("METRIC_REMAINING", "SessionTokenRemainingSeconds")

MUTATION = (
    "mutation GetSpaceliftToken($id: ID!, $secret: String!) "
    "{ apiKeyUser(id: $id, secret: $secret) { jwt } }"
)


def _log(event, **fields):
    print(json.dumps({"event": event, **fields}, sort_keys=True), flush=True)


def _claim(token, name):
    try:
        segment = token.split(".")[1]
        payload = json.loads(
            base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))
        )
        return payload.get(name)
    except Exception:
        return None


def _post(url, payload, headers, *, context=None):
    return _http_post(url, payload, headers, context=context)


def _mint(key_id, key_secret, *, context=None):
    """Exchange the API key for a session JWT.

    The mutation answers HTTP 200 even when the credential is rejected, so a
    null ``apiKeyUser`` is an authentication failure and not a success.
    """
    try:
        body = _post(
            GRAPHQL_ENDPOINT,
            {"query": MUTATION, "variables": {"id": key_id, "secret": key_secret}},
            {"Content-Type": "application/json"},
            context=context,
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


def _verify(token, *, context=None):
    return _verify_mcp(token, context=context, post_request=_post)


def _valid_expiry(value: object) -> TypeGuard[int | float]:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _authentication_failed(error):
    return str(error) in {"verify_http_401", "verify_read_http_401"}


def _previous_token(secrets):
    """Read the currently published token when it is available."""
    try:
        secret_value = secrets.get_secret_value(SecretId=TOKEN_SECRET_ID)
    except Exception as error:
        response = getattr(error, "response", None)
        code = (
            response.get("Error", {}).get("Code")
            if isinstance(response, dict) and isinstance(response.get("Error"), dict)
            else None
        )
        if code == "ResourceNotFoundException":
            return None
        raise RotationError("token_secret_read_failed") from None

    try:
        current = json.loads(secret_value["SecretString"])
    except (KeyError, TypeError, ValueError):
        return None
    token = current.get(TOKEN_JSON_KEY) if isinstance(current, dict) else None
    return token if isinstance(token, str) else None


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
        token = _mint(key_id, key_secret, context=context)
    except RotationError as error:
        _log("failed", stage="mint", error=str(error))
        raise

    issued_at = _claim(token, "iat")
    expires_at = _claim(token, "exp")
    if expires_at is None:
        _log("failed", stage="mint", error="minted_token_missing_exp")
        raise RotationError("minted_token_missing_exp")
    if not _valid_expiry(expires_at):
        _log("failed", stage="mint", error="invalid_exp")
        raise RotationError("invalid_exp")
    if expires_at <= time.time():
        _log("failed", stage="mint", error="minted_token_expired")
        raise RotationError("minted_token_expired")

    try:
        previous_token = _previous_token(secrets)
    except RotationError as error:
        _log("failed", stage="token_secret_read", error=str(error))
        raise
    previous_exp = _claim(previous_token, "exp") if previous_token else None
    if _valid_expiry(previous_exp) and expires_at < previous_exp:
        _log("failed", stage="mint", error="minted_token_expiry_regressed")
        raise RotationError("minted_token_expiry_regressed")
    expiry_changed = _valid_expiry(previous_exp) and previous_exp != expires_at

    try:
        tools = _verify(token, context=context)
    except RotationError as error:
        _log("failed", stage="verify", error=str(error))
        raise

    same_expiry = _valid_expiry(previous_exp) and expires_at == previous_exp
    stored_token_rejected = False
    if token != previous_token and same_expiry:
        try:
            _verify(previous_token, context=context)
        except RotationError as error:
            if not _authentication_failed(error):
                _log("failed", stage="verify_stored_token", error=str(error))
                raise
            _log("stored_token_unauthenticated", error=str(error))
            stored_token_rejected = True

    now = time.time()
    if expires_at <= now:
        _log("failed", stage="publish", error="minted_token_expired")
        raise RotationError("minted_token_expired")
    remaining = expires_at - now
    token_unchanged = token == previous_token
    token_published = not token_unchanged and (
        not _valid_expiry(previous_exp)
        or expires_at > previous_exp
        or stored_token_rejected
    )
    if token_published:
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
        lifetime_seconds=(expires_at - issued_at) if _valid_expiry(issued_at) else None,
        remaining_seconds=round(remaining, 3),
        previous_exp=previous_exp,
        expiry_changed=expiry_changed,
        token_unchanged=token_unchanged,
        token_published=token_published,
        tool_count=len(tools),
    )

    return {
        "exp": expires_at,
        "remaining_seconds": round(remaining, 3),
        "expiry_changed": expiry_changed,
        "token_unchanged": token_unchanged,
        "token_published": token_published,
    }
