#!/usr/bin/env python3
"""Smoke-test the *deployed* AgentCore adapter against the live gateway.

The adapter maps the gateway's wire action names onto the canonical names the
client sees, so if the deployed code and the manifest disagree with the gateway
about how many namespace levels an action carries, every tool for that target is
dropped. The adapter does catch that and raises `gateway_tool_set_mismatch`, but
only at connection time, and the message does not say which side is stale.

This runs the real registration through `hermes mcp test`, which spawns the
adapter exactly as the agent does, and then asserts the discovered tool set is
*exactly* what the manifests declare -- no missing tools, no extra ones, and no
leaked wire prefix on any name -- so a mismatch fails the deploy with the
offending names called out. Run it after every deploy, before using the tools.

Exit codes: 0 match, 1 mismatch or connection failure, 2 the check could not run.

Usage:
    adapter_smoke_test.py [--server agentcore] [--checkout DIR] [--hermes PATH]
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

DEFAULT_SERVER = "agentcore"
DEFAULT_CHECKOUT = os.environ.get("HERMES_ADAPTER_CHECKOUT", "/opt/data/hermes-agentcore-adapter")
DISCOVERED_RE = re.compile(r"Tools discovered:\s*(\d+)")
# `hermes mcp test` lists each tool as four spaces, the name, then a description.
# Continuation lines of a wrapped description start in column zero, so anchoring
# on the indentation keeps them out.
TOOL_LINE_RE = re.compile(r"^\s{4}([A-Za-z0-9_]+)\s{2,}", re.MULTILINE)


def _fail(message: str):
    print(f"FAIL: {message}", file=sys.stderr)
    raise SystemExit(1)


def load_expected_tools(adapter_dir: Path) -> tuple[set[str], dict[str, set[str]]]:
    """The tools the manifests declare, read through the adapter's own loader.

    Importing the adapter rather than re-reading the JSON keeps this honest: it
    asserts what the deployed code will actually do, including how it resolves
    each target's wire prefix, rather than what a second parser thinks.
    """
    sys.path.insert(0, str(adapter_dir))
    try:
        adapter = importlib.import_module("hermes_agentcore_adapter")
    except Exception as exc:  # surfaced as a hard failure
        _fail(f"could not import the adapter from {adapter_dir}: {exc}")

    expected: set[str] = set()
    per_target: dict[str, set[str]] = {}
    for target in adapter.TARGETS:
        tools = set(target.tools)
        per_target[target.name] = tools
        expected |= tools

    # A logical name is what the client sees, so it must never still carry a
    # `___` separator: that would mean a wire prefix leaked into the client
    # namespace, which is exactly the stale-manifest failure.
    leaked = sorted(name for name in expected if "___" in name and name.count("___") > 1)
    if leaked:
        _fail(f"manifest declares a name with a leaked wire prefix: {leaked}")
    return expected, per_target


def discover(hermes_bin: str, server: str) -> tuple[set[str], str]:
    result = subprocess.run(
        [hermes_bin, "mcp", "test", server],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    output = f"{result.stdout}\n{result.stderr}"
    if result.returncode != 0:
        _fail(
            f"`hermes mcp test {server}` exited {result.returncode}; the adapter did not "
            f"connect or did not agree with the gateway.\n{output.strip()}"
        )

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
    parser.add_argument("--server", default=DEFAULT_SERVER, help="MCP server name as registered with Hermes")
    parser.add_argument("--checkout", default=DEFAULT_CHECKOUT, help="checkout the adapter runs from")
    parser.add_argument("--hermes", default=None, help="path to the hermes executable")
    args = parser.parse_args()

    hermes_bin = args.hermes or shutil.which("hermes") or "/opt/hermes/bin/hermes"
    if not Path(hermes_bin).exists():
        print(f"could not find the hermes executable; pass --hermes (tried {hermes_bin})", file=sys.stderr)
        return 2

    adapter_dir = Path(args.checkout) / "agents" / "hermes" / "adapter"
    if not (adapter_dir / "hermes_agentcore_adapter.py").exists():
        print(f"no adapter at {adapter_dir}; pass --checkout", file=sys.stderr)
        return 2

    expected, per_target = load_expected_tools(adapter_dir)
    discovered, _ = discover(hermes_bin, args.server)

    missing = sorted(expected - discovered)
    unexpected = sorted(discovered - expected)
    if missing or unexpected:
        detail = []
        if missing:
            detail.append(f"missing: {missing}")
        if unexpected:
            detail.append(f"unexpected: {unexpected}")
        hint = ""
        if any(name.count("___") > 1 for name in unexpected):
            hint = (
                "\nThe gateway is advertising names with an extra namespace level. Most likely the "
                "deployed adapter or manifest is stale, or the manifest's gateway_action_prefix no "
                "longer matches the number of gateways in the path."
            )
        _fail(f"the deployed tool set does not match the manifests ({'; '.join(detail)}){hint}")

    print("OK: the deployed adapter agrees with the gateway.")
    for name in sorted(per_target):
        print(f"  {name}: {len(per_target[name])} tools")
    print(f"  total: {len(discovered)} tools, all under canonical names")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
