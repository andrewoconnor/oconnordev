#!/usr/bin/env python3
"""Hermes stdio MCP adapter for the shared Cognito-protected AgentCore Gateway.

The gateway is not GitHub-specific. It fronts several targets, each with its own
tool namespace, allowlist and request headers, all behind one OAuth client and
one endpoint. This adapter is the single registration Hermes needs: it holds one
token for the gateway and presents every target's capability set through one
stdio server, so the same gateway is never registered twice under different
names.

Adding a target is one manifest plus one entry in TARGETS. A target can only
ever expose the tools its manifest names -- `tools/list` asserts the exposed set
equals the union of the manifests, and `tools/call` refuses any name no target
owns -- so a new target cannot widen an existing target's allowlist.
"""

from __future__ import annotations

import json
import os
import sys

from adapter_config import (
    CLOUDFRONT_GATEWAY_HOSTNAME as CLOUDFRONT_GATEWAY_HOSTNAME,
)
from adapter_config import (
    CONNECT_TIMEOUT_SECONDS as CONNECT_TIMEOUT_SECONDS,
)
from adapter_config import (
    MANIFEST_DIR as MANIFEST_DIR,
)
from adapter_config import (
    MAX_LINE_BYTES as MAX_LINE_BYTES,
)
from adapter_config import (
    MAX_RESPONSE_BYTES as MAX_RESPONSE_BYTES,
)
from adapter_config import (
    MAX_TOOL_LIST_PAGES as MAX_TOOL_LIST_PAGES,
)
from adapter_config import (
    READ_TIMEOUT_SECONDS as READ_TIMEOUT_SECONDS,
)
from adapter_config import (
    REQUIRED_SCOPE as REQUIRED_SCOPE,
)
from adapter_config import (
    TARGETS as TARGETS,
)
from adapter_config import (
    TOKEN_REFRESH_SKEW_SECONDS as TOKEN_REFRESH_SKEW_SECONDS,
)
from adapter_config import (
    AdapterError as AdapterError,
)
from adapter_config import (
    Target as Target,
)
from adapter_config import (
    _json_rpc_error as _json_rpc_error,
)
from adapter_config import (
    _load_target as _load_target,
)
from adapter_config import (
    _validate_https_endpoint as _validate_https_endpoint,
)
from adapter_forwarder import AgentCoreForwarder as AgentCoreForwarder
from adapter_transport import (
    HttpResponse as HttpResponse,
)
from adapter_transport import (
    HttpsTransport as HttpsTransport,
)
from adapter_transport import (
    TokenCache as TokenCache,
)


def _load_forwarder() -> AgentCoreForwarder:
    return AgentCoreForwarder(
        gateway_url=os.environ.get("HERMES_AGENTCORE_GATEWAY_URL", ""),
        token_url=os.environ.get("HERMES_AGENTCORE_COGNITO_TOKEN_URL", ""),
        client_id=os.environ.get("HERMES_AGENTCORE_COGNITO_CLIENT_ID", ""),
        client_secret=os.environ.get("HERMES_AGENTCORE_COGNITO_CLIENT_SECRET", ""),
    )


def serve(stdin=None, stdout=None, forwarder=None) -> None:
    stdin = stdin or sys.stdin.buffer
    stdout = stdout or sys.stdout.buffer
    try:
        client = forwarder or _load_forwarder()
    except AdapterError as error:
        print(error.category, file=sys.stderr)
        return
    while True:
        line = stdin.readline(MAX_LINE_BYTES + 1)
        if not line:
            return
        if len(line) > MAX_LINE_BYTES:
            response = _json_rpc_error(None, -32000, "request_too_large")
        else:
            try:
                request = json.loads(line)
                response = client.handle(request)
            except json.JSONDecodeError:
                response = _json_rpc_error(None, -32700, "Parse error")
            except Exception:
                response = _json_rpc_error(None, -32000, "adapter_failure")
        if response is not None:
            try:
                stdout.write(
                    json.dumps(
                        response, separators=(",", ":"), ensure_ascii=False
                    ).encode("utf-8")
                    + b"\n"
                )
                stdout.flush()
            except Exception:
                return


if __name__ == "__main__":
    serve()
