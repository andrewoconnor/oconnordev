#!/usr/bin/env python3
"""Opt-in live smoke checks for the deployed AgentCore adapter and gateway.

The live check first confirms the registered Hermes server discovers exactly
what the adapter manifests declare. It then uses the adapter against the live
gateway to repeat discovery, call one known read-only tool per configured
target, and verify that two harmless GitHub reads outside the configured owner
and repository scope are denied by Cedar. No write-capable tool is called.

Credentials are resolved from the selected Hermes MCP server's configured
``env`` (including its normal variable interpolation) and are never printed.
The GitHub scope probe requires ``HERMES_SMOKE_GITHUB_OWNER`` and
``HERMES_SMOKE_GITHUB_REPO`` or equivalent command-line options. Without
``--live`` this script performs no network requests and exits 2 so a skipped
check cannot be mistaken for a pass.
"""

from __future__ import annotations

import argparse
import importlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import NoReturn

if __package__:
    from .gateway_validation import (
        EXPECTED_LIVE_ENV,
        SmokeCheckError,
        missing_live_configuration,
        run_gateway_checks,
    )
else:
    from gateway_validation import (
        EXPECTED_LIVE_ENV,
        SmokeCheckError,
        missing_live_configuration,
        run_gateway_checks,
    )

DEFAULT_SERVER = "agentcore"
DEFAULT_CHECKOUT = os.environ.get("HERMES_ADAPTER_CHECKOUT", "/opt/data/hermes-agentcore-adapter")
DISCOVERED_RE = re.compile(r"Tools discovered:\s*(\d+)")
TOOL_LINE_RE = re.compile(r"^\s{4}([A-Za-z0-9_]+)\s{2,}", re.MULTILINE)


def _fail(message: str) -> NoReturn:
    print(f"FAIL: {message}", file=sys.stderr)
    raise SystemExit(1)


def load_hermes_server_environment(hermes_bin: str, server: str) -> dict[str, str]:
    """Resolve a configured stdio server's filtered environment without printing it."""
    executable = Path(hermes_bin).resolve()
    candidates = [(executable.parent.parent, executable.parent.parent.parent)]
    candidates.append((Path("/opt/hermes/.venv"), Path("/opt/hermes")))
    runtime = next(((venv, root) for venv, root in candidates if (root / "tools" / "mcp_tool_config.py").is_file()), None)
    if runtime is None:
        raise SmokeCheckError("Hermes MCP config loader is unavailable beside the selected Hermes executable")
    venv_root, hermes_root = runtime
    python_version = f"python{sys.version_info.major}.{sys.version_info.minor}"
    site_packages = venv_root / "lib" / python_version / "site-packages"
    sys.path.insert(0, str(hermes_root))
    if site_packages.is_dir():
        sys.path.insert(0, str(site_packages))
    try:
        config_loader = importlib.import_module("tools.mcp_tool_config")
        servers = config_loader._load_mcp_config()
        server_config = servers.get(server) if isinstance(servers, dict) else None
        if not isinstance(server_config, dict) or not isinstance(server_config.get("command"), str):
            raise SmokeCheckError(f"Hermes MCP server {server!r} is missing or is not configured for stdio")
        return config_loader._build_safe_env(server_config.get("env"))
    except SmokeCheckError:
        raise
    except Exception:
        raise SmokeCheckError(f"could not resolve the configured environment for Hermes MCP server {server!r}") from None


def load_expected_tools(adapter_dir: Path) -> tuple[set[str], dict[str, set[str]]]:
    """The tools the manifests declare, read through the adapter's own loader."""
    sys.path.insert(0, str(adapter_dir))
    try:
        adapter = importlib.import_module("hermes_agentcore_adapter")
    except Exception as exc:
        _fail(f"could not import the adapter from {adapter_dir}: {exc}")

    expected: set[str] = set()
    per_target: dict[str, set[str]] = {}
    for target in adapter.TARGETS:
        tools = set(target.client_tools)
        per_target[target.name] = tools
        expected |= tools
    return expected, per_target


def discover(hermes_bin: str, server: str) -> tuple[set[str], str]:
    try:
        result = subprocess.run(
            [hermes_bin, "mcp", "test", server],
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        _fail(f"could not run `hermes mcp test {server}`: {exc}")
    output = f"{result.stdout}\n{result.stderr}"
    if result.returncode != 0:
        _fail(f"`hermes mcp test {server}` exited {result.returncode}; the adapter did not connect or did not agree with the gateway.\n{output.strip()}")

    match = DISCOVERED_RE.search(output)
    if not match:
        print(output, file=sys.stderr)
        raise SystemExit(2)
    discovered = set(TOOL_LINE_RE.findall(output))
    if not discovered:
        print(output, file=sys.stderr)
        raise SystemExit(2)
    declared = int(match.group(1))
    if declared != len(discovered):
        _fail(f"the server reported {declared} tools but {len(discovered)} names were listed; refusing to trust a partial read")
    return discovered, output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="opt in to live gateway discovery, read-only calls, and GitHub policy-denial probes")
    parser.add_argument("--server", default=DEFAULT_SERVER, help="MCP server name as registered with Hermes")
    parser.add_argument("--checkout", default=DEFAULT_CHECKOUT, help="checkout the adapter runs from")
    parser.add_argument("--hermes", default=None, help="path to the hermes executable")
    parser.add_argument("--github-owner", default=os.environ.get("HERMES_SMOKE_GITHUB_OWNER"), help="allowed GitHub owner (or HERMES_SMOKE_GITHUB_OWNER)")
    parser.add_argument("--github-repo", default=os.environ.get("HERMES_SMOKE_GITHUB_REPO"), help="allowed GitHub repository (or HERMES_SMOKE_GITHUB_REPO)")
    args = parser.parse_args()

    if not args.live:
        print("SKIP: live gateway checks are opt-in; pass --live to run them.", file=sys.stderr)
        return 2

    hermes_bin = args.hermes or shutil.which("hermes") or "/opt/hermes/bin/hermes"
    if not Path(hermes_bin).exists():
        print(f"could not find the hermes executable; pass --hermes (tried {hermes_bin})", file=sys.stderr)
        return 2

    try:
        gateway_env = load_hermes_server_environment(hermes_bin, args.server)
    except SmokeCheckError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2
    github_owner = args.github_owner or gateway_env.get("HERMES_SMOKE_GITHUB_OWNER")
    github_repo = args.github_repo or gateway_env.get("HERMES_SMOKE_GITHUB_REPO")
    missing = missing_live_configuration(gateway_env, github_owner=github_owner, github_repo=github_repo)
    if missing:
        print("FAIL: --live requires configuration missing from the selected Hermes server or smoke-test options: " + ", ".join(missing), file=sys.stderr)
        return 2
    github_owner = str(github_owner)
    github_repo = str(github_repo)

    adapter_dir = Path(args.checkout) / "agents" / "hermes" / "adapter"
    if not (adapter_dir / "hermes_agentcore_adapter.py").exists():
        print(f"no adapter at {adapter_dir}; pass --checkout", file=sys.stderr)
        return 2

    expected, per_target = load_expected_tools(adapter_dir)
    discovered, _ = discover(hermes_bin, args.server)
    missing_tools = sorted(expected - discovered)
    unexpected_tools = sorted(discovered - expected)
    if missing_tools or unexpected_tools:
        _fail(f"the registered adapter tool set does not match the manifests (missing: {missing_tools}; unexpected: {unexpected_tools})")

    adapter = importlib.import_module("hermes_agentcore_adapter")
    try:
        forwarder = adapter.AgentCoreForwarder(
            gateway_url=gateway_env["HERMES_AGENTCORE_GATEWAY_URL"],
            token_url=gateway_env["HERMES_AGENTCORE_COGNITO_TOKEN_URL"],
            client_id=gateway_env["HERMES_AGENTCORE_COGNITO_CLIENT_ID"],
            client_secret=gateway_env["HERMES_AGENTCORE_COGNITO_CLIENT_SECRET"],
        )
        results = run_gateway_checks(forwarder, per_target, github_owner, github_repo)
    except Exception as exc:
        _fail(f"live gateway validation failed: {getattr(exc, 'category', type(exc).__name__)}")

    print("OK: Hermes registration and direct gateway checks passed.")
    for result in results:
        print(f"  {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())