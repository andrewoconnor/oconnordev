from __future__ import annotations

from collections.abc import Iterable

ALL_ROOTS = (
    "infra/aws/general",
    "infra/aws/security",
    "infra/aws/tools",
    "infra/aws/production",
    "infra/aws/drumrollworld",
    "infra/spacelift",
    "infra/github/oconnordev",
)

ACCOUNT_MAP_CONSUMERS = (
    "infra/aws/general",
    "infra/aws/security",
    "infra/aws/tools",
    "infra/aws/production",
    "infra/aws/drumrollworld",
    "infra/spacelift",
)

_ACCOUNT_MAP = "infra/aws/accounts.json"
_COST_EXPORT_SCHEMA = "infra/aws/cost-export-schema.json"
_TOOLS_ADAPTER_DIR = "agents/hermes/adapter/"
_ALL_ROOTS_INPUTS = ("mise.toml", "mise.lock")


def roots_for_paths(paths: Iterable[str]) -> tuple[str, ...]:
    """Return OpenTofu roots affected by repository-relative changed paths."""
    selected: set[str] = set()

    for raw_path in paths:
        path = raw_path.strip().replace("\\", "/").removeprefix("./")
        if not path:
            continue

        if path in _ALL_ROOTS_INPUTS or path.startswith("scripts/ci/"):
            selected.update(ALL_ROOTS)

        for root in ALL_ROOTS:
            if path == root or path.startswith(f"{root}/"):
                selected.add(root)

        if path == _ACCOUNT_MAP:
            selected.update(ACCOUNT_MAP_CONSUMERS)

        if path == _COST_EXPORT_SCHEMA:
            selected.update(("infra/aws/general", "infra/aws/security"))

        if path.startswith(_TOOLS_ADAPTER_DIR):
            relative = path.removeprefix(_TOOLS_ADAPTER_DIR)
            if "/" not in relative and relative.endswith("-mcp-tools.json"):
                selected.add("infra/aws/tools")

    return tuple(root for root in ALL_ROOTS if root in selected)
