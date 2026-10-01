#!/usr/bin/env python3
"""Hermes stdio MCP adapter for the read-only AWS tools on the shared gateway.

The shared gateway is the same Cognito-protected AgentCore gateway the GitHub
target lives behind; this adapter exposes only the AWS target's tools, with the
target prefix stripped, and asserts that the gateway advertises exactly the
manifest tool set before exposing anything.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from hermes_github_adapter import AdapterError, AgentCoreForwarder, serve

TOOL_MANIFEST_PATH = Path(__file__).resolve().parent / "aws-mcp-tools.json"
TOOL_MANIFEST = json.loads(TOOL_MANIFEST_PATH.read_text(encoding="utf-8"))
AWS_TOOLS = frozenset(TOOL_MANIFEST["tools"])
TARGET_PREFIX = "aws___"


def build_forwarder() -> AgentCoreForwarder:
    return AgentCoreForwarder(
        gateway_url=os.environ.get("HERMES_AWS_GATEWAY_URL", ""),
        token_url=os.environ.get("HERMES_AWS_COGNITO_TOKEN_URL", ""),
        client_id=os.environ.get("HERMES_AWS_COGNITO_CLIENT_ID", ""),
        client_secret=os.environ.get("HERMES_AWS_COGNITO_CLIENT_SECRET", ""),
        tools=AWS_TOOLS,
        tool_prefix=TARGET_PREFIX,
        # The GitHub target's X-MCP-Tools toolset filter is GitHub-specific; the
        # AWS target wants no extra request header.
        extra_headers={},
    )


def main() -> None:
    try:
        forwarder = build_forwarder()
    except AdapterError as error:
        print(error.category, file=sys.stderr)
        return
    serve(forwarder=forwarder)


if __name__ == "__main__":
    main()