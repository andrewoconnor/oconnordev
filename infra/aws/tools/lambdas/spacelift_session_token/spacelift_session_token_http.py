"""Bounded HTTP and MCP checks for session-token rotation."""

import json
import math
import os
import urllib.error
import urllib.request

HTTP_TIMEOUT_SECONDS = int(os.environ.get("HTTP_TIMEOUT_SECONDS", "5"))
HTTP_SAFETY_MARGIN_SECONDS = 5
VERIFY_ENDPOINT = os.environ.get("VERIFY_ENDPOINT", "")
VERIFY_EXPECTED_TOOLS_JSON = os.environ.get(
    "VERIFY_EXPECTED_TOOLS_JSON", '["discover", "provider", "query"]'
)
LAMBDA_TIMEOUT_FALLBACK_SECONDS = 30


class RotationError(Exception):
    """A rotation failure whose message is safe to log."""


def _http_timeout(context):
    remaining_time = getattr(context, "get_remaining_time_in_millis", None)
    if callable(remaining_time):
        try:
            remaining_millis = remaining_time()
        except Exception:
            raise RotationError("lambda_remaining_time_unavailable") from None
        if (
            not isinstance(remaining_millis, (int, float))
            or isinstance(remaining_millis, bool)
            or not math.isfinite(remaining_millis)
        ):
            raise RotationError("lambda_remaining_time_unavailable")
        remaining_seconds = remaining_millis / 1000
    else:
        remaining_seconds = LAMBDA_TIMEOUT_FALLBACK_SECONDS

    timeout = min(
        HTTP_TIMEOUT_SECONDS,
        remaining_seconds - HTTP_SAFETY_MARGIN_SECONDS,
    )
    if timeout <= 0:
        raise RotationError("http_deadline_exhausted")
    return timeout


def _post(url, payload, headers, *, context=None):
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), method="POST", headers=headers
    )
    with urllib.request.urlopen(request, timeout=_http_timeout(context)) as response:
        return response.read().decode("utf-8", "replace")


def _documents(body):
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
    return documents


def _tool_names(body):
    """Read tool names out of an MCP response, tolerating SSE framing."""
    for document in _documents(body):
        if not isinstance(document, dict):
            continue
        result = document.get("result")
        if not isinstance(result, dict):
            continue
        tools = result.get("tools")
        if isinstance(tools, list):
            names = [
                tool.get("name")
                for tool in tools
                if isinstance(tool, dict) and isinstance(tool.get("name"), str)
            ]
            return names if len(names) == len(tools) else None
    return None


def _stack_from_result(value):
    if not isinstance(value, dict):
        return None
    if value.get("id") == "oconnordev-tools" and isinstance(value.get("state"), str):
        return value
    for key in ("stack", "data", "structuredContent"):
        stack = _stack_from_result(value.get(key))
        if stack is not None:
            return stack
    return None


def _verify_useful_read(body):
    for document in _documents(body):
        if not isinstance(document, dict) or document.get("error"):
            continue
        result = document.get("result")
        if not isinstance(result, dict) or result.get("isError") is True:
            continue
        stack = _stack_from_result(result)
        if stack is None:
            content = result.get("content")
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and isinstance(item.get("text"), str):
                        try:
                            stack = _stack_from_result(json.loads(item["text"]))
                        except ValueError:
                            continue
                        if stack is not None:
                            break
        if stack is not None:
            return True
    return False


def _verify(token, *, context=None, post_request=None):
    """Check the exact read-only tools and exercise an authenticated stack read."""
    if not VERIFY_ENDPOINT:
        raise RotationError("verify_endpoint_missing")

    try:
        expected = json.loads(VERIFY_EXPECTED_TOOLS_JSON)
    except ValueError:
        raise RotationError("verify_expected_tools_invalid") from None
    if (
        not isinstance(expected, list)
        or not expected
        or any(not isinstance(name, str) or not name for name in expected)
        or len(expected) != len(set(expected))
    ):
        raise RotationError("verify_expected_tools_invalid")

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "Authorization": f"Bearer {token}",
    }
    send = post_request or _post
    try:
        body = send(
            VERIFY_ENDPOINT,
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            headers,
            context=context,
        )
    except urllib.error.HTTPError as error:
        raise RotationError(f"verify_http_{error.code}") from None
    except Exception as error:
        raise RotationError(f"verify_transport_{type(error).__name__}") from None

    names = _tool_names(body)
    if names is None or len(names) != len(set(names)) or set(names) != set(expected):
        raise RotationError("verify_tool_allowlist_mismatch")

    try:
        read_body = send(
            VERIFY_ENDPOINT,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "query",
                    "arguments": {
                        "operation": "stack",
                        "select": "id name state",
                        "variables": {"id": "oconnordev-tools"},
                    },
                },
            },
            headers,
            context=context,
        )
    except urllib.error.HTTPError as error:
        raise RotationError(f"verify_read_http_{error.code}") from None
    except Exception as error:
        raise RotationError(f"verify_read_transport_{type(error).__name__}") from None

    if not _verify_useful_read(read_body):
        raise RotationError("verify_read_failed")
    return names