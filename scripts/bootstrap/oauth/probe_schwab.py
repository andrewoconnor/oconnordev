#!/usr/bin/env python3
"""Call Schwab with the gateway's stored token and several header variants.

Uses the adapter's HERMES_AGENTCORE_* variables and tools-account AWS
credentials. Prints only HTTP status codes and Schwab's error text.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

WORKLOAD = "hermes-rfltsq6ysk"
URL = "https://api.schwabapi.com/marketdata/v1/quotes?fields=quote%2Creference%2Cregular&symbols=SPCX"
VARIANTS = {
    "as the gateway sends it": {
        "Content-Type": "application/json",
        "User-Agent": "Apache-HttpAsyncClient/5.6.1 (Java/25.0.4.1)",
    },
    "without content-type": {
        "User-Agent": "Apache-HttpAsyncClient/5.6.1 (Java/25.0.4.1)"
    },
    "with accept": {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "Apache-HttpAsyncClient/5.6.1 (Java/25.0.4.1)",
    },
    "accept without content-type": {
        "Accept": "application/json",
        "User-Agent": "Apache-HttpAsyncClient/5.6.1 (Java/25.0.4.1)",
    },
}


def aws(*args: str) -> str:
    command = ["aws", "bedrock-agentcore", *args, "--region", "us-east-1"]
    result = subprocess.run(
        [*command, "--output", "json"], capture_output=True, text=True
    )
    if result.returncode:
        raise SystemExit(
            f"aws bedrock-agentcore {args[0]} failed: {result.stderr.strip()}"
        )
    return result.stdout


def main() -> int:
    spec = importlib.util.spec_from_file_location(
        "consent", Path(__file__).with_name("consent.py")
    )
    consent = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(consent)
    jwt = consent.access_token(
        os.environ["HERMES_AGENTCORE_COGNITO_TOKEN_URL"],
        os.environ["HERMES_AGENTCORE_COGNITO_CLIENT_ID"],
        os.environ["HERMES_AGENTCORE_COGNITO_CLIENT_SECRET"],
    )
    workload = json.loads(
        aws(
            "get-workload-access-token-for-jwt",
            "--workload-name",
            WORKLOAD,
            "--user-token",
            jwt,
        )
    )["workloadAccessToken"]
    resource = json.loads(
        aws(
            "get-resource-oauth2-token",
            "--workload-identity-token",
            workload,
            "--resource-credential-provider-name",
            "hermes-schwab",
            "--scopes",
            "api",
            "--oauth2-flow",
            "USER_FEDERATION",
        )
    )
    token = resource.get("accessToken")
    if not token:
        print("No stored Schwab token; run consent.py first.", file=sys.stderr)
        return 1
    for name, headers in VARIANTS.items():
        request = urllib.request.Request(
            URL, headers={**headers, "Authorization": f"Bearer {token}"}
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                print(f"{name}: {response.status}")
        except urllib.error.HTTPError as error:
            print(
                f"{name}: {error.code} {error.read()[:200].decode('utf-8', 'replace')}"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
