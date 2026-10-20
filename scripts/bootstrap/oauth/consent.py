#!/usr/bin/env python3
"""Grant AgentCore one-time OAuth consent for a 3LO gateway target.

Uses the adapter's environment: HERMES_AGENTCORE_GATEWAY_URL,
HERMES_AGENTCORE_COGNITO_TOKEN_URL, HERMES_AGENTCORE_COGNITO_CLIENT_ID and
HERMES_AGENTCORE_COGNITO_CLIENT_SECRET. Needs AWS credentials for the tools
account to call CompleteResourceTokenAuth. Pass --tool to choose the target
(default google___listLabels; for Outlook use outlook___listMailFolders) and
--force to replace a stored token, and --local to return to this script instead
of the target's hosted callback. Pass --arguments with a JSON object to call
a tool that needs parameters.
"""

from __future__ import annotations

import base64
import http.server
import json
import os
import re
import subprocess
import sys
import threading
import urllib.parse
import urllib.request
import webbrowser

SCOPE = "hermes-mcp/invoke"
PORT = 9090
CALLBACK_PATH = "/oauth2/callback"
TOOL = "google___listLabels"
ELICITATION_REQUIRED = -32042
AUTHORIZE_URL = re.compile(
    r"https://bedrock-agentcore\.[a-z0-9-]+\.amazonaws\.com/identities/oauth2/authorize[^\s\"'<>]*"
)


def post(url: str, body: bytes, headers: dict[str, str]) -> tuple[bytes, dict]:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read(), {k.lower(): v for k, v in response.headers.items()}


def access_token(token_url: str, client_id: str, client_secret: str) -> str:
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    body = urllib.parse.urlencode(
        {"grant_type": "client_credentials", "scope": SCOPE}
    ).encode()
    raw, _ = post(
        token_url,
        body,
        {
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    return json.loads(raw)["access_token"]


def messages(raw: bytes, content_type: str) -> list[dict]:
    text = raw.decode("utf-8")
    if "text/event-stream" not in content_type:
        return [json.loads(text)]
    return [
        json.loads(line[5:].strip())
        for line in text.splitlines()
        if line.startswith("data:") and line[5:].strip()
    ]


def elicitation_url(found: list[dict]) -> str | None:
    for message in found:
        error = message.get("error") or {}
        if error.get("code") != ELICITATION_REQUIRED:
            continue
        for item in (error.get("data") or {}).get("elicitations") or []:
            url = item.get("url", "")
            if item.get("mode") == "url" and url.startswith("https://"):
                return url
    match = AUTHORIZE_URL.search(json.dumps(found))
    return match.group(0) if match else None


def succeeded(found: list[dict]) -> bool:
    return any(
        "result" in message and not (message.get("result") or {}).get("isError")
        for message in found
    ) and not any("error" in message for message in found)


class Gateway:
    def __init__(self, url: str, token: str):
        self.url, self.token, self.session, self.version = url, token, None, None

    def rpc(self, method: str, params: dict, message_id: int) -> list[dict]:
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        if self.version:
            headers["MCP-Protocol-Version"] = self.version
        body = json.dumps(
            {"jsonrpc": "2.0", "id": message_id, "method": method, "params": params}
        ).encode()
        raw, response_headers = post(self.url, body, headers)
        self.session = response_headers.get("mcp-session-id", self.session)
        return messages(raw, response_headers.get("content-type", ""))

    def initialize(self) -> None:
        found = self.rpc(
            "initialize",
            {
                "protocolVersion": "2025-11-25",
                "capabilities": {"elicitation": {"url": {}}},
                "clientInfo": {"name": "agentcore-consent", "version": "1"},
            },
            1,
        )
        self.version = found[-1]["result"]["protocolVersion"]

    def list_labels(
        self,
        force: bool = False,
        tool: str = TOOL,
        local: bool = False,
        arguments: dict | None = None,
    ) -> list[dict]:
        params: dict = {"name": tool, "arguments": arguments or {}}
        provider: dict = {}
        if force:
            provider["forceAuthentication"] = True
        if local:
            provider["returnUrl"] = f"http://localhost:{PORT}{CALLBACK_PATH}"
        if provider:
            params["_meta"] = {
                "aws.bedrock-agentcore.gateway/credentialProviderConfiguration": {
                    "oauthCredentialProvider": provider
                }
            }
        return self.rpc("tools/call", params, 2)


def wait_for_session_id() -> str:
    received: dict[str, str] = {}

    class Callback(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            session = urllib.parse.parse_qs(parsed.query).get("session_id", [""])[0]
            ok = parsed.path == CALLBACK_PATH and bool(session)
            if ok:
                received["session_id"] = session
            self.send_response(200 if ok else 400)
            self.end_headers()
            self.wfile.write(
                b"Consent received. Return to the terminal."
                if ok
                else b"Missing session_id."
            )
            if ok:
                threading.Thread(target=server.shutdown).start()

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", PORT), Callback)
    server.serve_forever()
    return received["session_id"]


def complete(session_uri: str, token: str) -> None:
    subprocess.run(
        [
            "aws",
            "bedrock-agentcore",
            "complete-resource-token-auth",
            "--region",
            "us-east-1",
            "--cli-input-json",
            json.dumps(
                {"sessionUri": session_uri, "userIdentifier": {"userToken": token}}
            ),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
    )


def main() -> int:
    env = {
        key: os.environ.get(f"HERMES_AGENTCORE_{key}", "")
        for key in (
            "GATEWAY_URL",
            "COGNITO_TOKEN_URL",
            "COGNITO_CLIENT_ID",
            "COGNITO_CLIENT_SECRET",
        )
    }
    missing = [f"HERMES_AGENTCORE_{key}" for key, value in env.items() if not value]
    if missing:
        print("Set " + ", ".join(missing), file=sys.stderr)
        return 2
    token = access_token(
        env["COGNITO_TOKEN_URL"],
        env["COGNITO_CLIENT_ID"],
        env["COGNITO_CLIENT_SECRET"],
    )
    gateway = Gateway(env["GATEWAY_URL"], token)
    gateway.initialize()
    arguments = sys.argv[1:]
    tool = arguments[arguments.index("--tool") + 1] if "--tool" in arguments else TOOL
    local = "--local" in arguments
    call = (
        json.loads(arguments[arguments.index("--arguments") + 1])
        if "--arguments" in arguments
        else {}
    )
    found = gateway.list_labels(
        force="--force" in arguments, tool=tool, local=local, arguments=call
    )
    url = elicitation_url(found)
    if url is None:
        if succeeded(found):
            print(f"Consent already exists; {tool} succeeded.")
            print(json.dumps(found, indent=2)[:4000])
            return 0
        print(f"{tool} failed without a consent URL:", file=sys.stderr)
        print(json.dumps(found, indent=2)[:4000], file=sys.stderr)
        return 1
    print(f"Open this URL and approve read-only access:\n{url}")
    webbrowser.open(url)
    complete(wait_for_session_id(), token)
    found = gateway.list_labels(tool=tool, arguments=call)
    if not succeeded(found):
        print(f"Consent did not complete; {tool} still fails:", file=sys.stderr)
        print(json.dumps(found, indent=2)[:4000], file=sys.stderr)
        return 1
    print(f"Consent complete; {tool} succeeded.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
