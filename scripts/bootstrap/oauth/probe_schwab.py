#!/usr/bin/env python3
"""Call Schwab directly with several header variants.

Creates a temporary workload identity, gets a Schwab token through the
hermes-schwab AgentCore provider with one browser consent, prints only HTTP
status codes and Schwab's error text, and deletes the identity. Needs
tools-account AWS credentials and the AWS CLI.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

WORKLOAD = "schwab-probe"
USER = "owner"
RETURN_URL = "http://localhost:9090/oauth2/callback"
URL = "https://api.schwabapi.com/marketdata/v1/quotes?fields=quote%2Creference%2Cregular&symbols=SPCX"
AGENT = "Apache-HttpAsyncClient/5.6.1 (Java/25.0.4.1)"
VARIANTS = {
    "as the gateway sends it": {
        "Content-Type": "application/json",
        "User-Agent": AGENT,
    },
    "without content-type": {"User-Agent": AGENT},
    "with accept": {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": AGENT,
    },
    "accept without content-type": {"Accept": "application/json", "User-Agent": AGENT},
}


def aws(service: str, operation: str, payload: dict, check: bool = True) -> dict:
    result = subprocess.run(
        [
            "aws",
            service,
            operation,
            "--region",
            "us-east-1",
            "--output",
            "json",
            "--cli-input-json",
            json.dumps(payload),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode and check:
        raise SystemExit(f"aws {service} {operation} failed: {result.stderr.strip()}")
    return json.loads(result.stdout) if result.stdout.strip() else {}


def resource_token(workload_token: str) -> dict:
    return aws(
        "bedrock-agentcore",
        "get-resource-oauth2-token",
        {
            "workloadIdentityToken": workload_token,
            "resourceCredentialProviderName": "hermes-schwab",
            "scopes": ["api"],
            "oauth2Flow": "USER_FEDERATION",
            "resourceOauth2ReturnUrl": RETURN_URL,
        },
    )


def main() -> int:
    spec = importlib.util.spec_from_file_location(
        "consent", Path(__file__).with_name("consent.py")
    )
    consent = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(consent)
    aws(
        "bedrock-agentcore-control",
        "create-workload-identity",
        {"name": WORKLOAD, "allowedResourceOauth2ReturnUrls": [RETURN_URL]},
        check=False,
    )
    try:
        workload_token = aws(
            "bedrock-agentcore",
            "get-workload-access-token-for-user-id",
            {"workloadName": WORKLOAD, "userId": USER},
        )["workloadAccessToken"]
        found = resource_token(workload_token)
        if not found.get("accessToken"):
            print(
                f"Open this URL and approve Schwab access:\n{found['authorizationUrl']}"
            )
            webbrowser.open(found["authorizationUrl"])
            session = consent.wait_for_session_id()
            aws(
                "bedrock-agentcore",
                "complete-resource-token-auth",
                {"sessionUri": session, "userIdentifier": {"userId": USER}},
            )
            found = resource_token(workload_token)
        token = found.get("accessToken")
        if not token:
            print("AgentCore returned no Schwab token.", file=sys.stderr)
            return 1
        for name, headers in VARIANTS.items():
            request = urllib.request.Request(
                URL, headers={**headers, "Authorization": f"Bearer {token}"}
            )
            try:
                with urllib.request.urlopen(request, timeout=15) as response:
                    print(f"{name}: {response.status}")
            except urllib.error.HTTPError as error:
                body = error.read()[:200].decode("utf-8", "replace")
                print(f"{name}: {error.code} {body}")
    finally:
        aws(
            "bedrock-agentcore-control",
            "delete-workload-identity",
            {"name": WORKLOAD},
            check=False,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
