"""Secretless freshness and architecture guard, executed before AWS credentials."""

from __future__ import annotations

import json
import re
import subprocess
import sys

EXACT_INPUTS = {
    ".github/workflows/thundermail-image.yml",
    "scripts/ci/thundermail_image.py",
    "agents/hermes/adapter/thundermail-mcp-tools.json",
}


def is_image_input(path: str) -> bool:
    return (
        path.startswith("infra/aws/tools/lambdas/thundermail_mcp/")
        or path.startswith("agents/hermes/adapter/")
        or path.startswith("infra/aws/tools/")
        or path in {"mise.toml", "mise.lock", ".github/workflows/adapter-tests.yml"}
        or path in EXACT_INPUTS
    )


def check_image_metadata(metadata: dict) -> str:
    if metadata.get("Architecture") != "arm64" or metadata.get("Os") != "linux":
        raise ValueError("publication requires a single linux/arm64 image")
    identity = metadata.get("Id")
    if not isinstance(identity, str) or not re.fullmatch(
        r"sha256:[0-9a-f]{64}", identity
    ):
        raise ValueError("missing local image identity")
    return identity


def main() -> None:
    expected, image = sys.argv[1:]
    subprocess.run(["git", "fetch", "--no-tags", "origin", "master"], check=True)
    # Compare trees, not commits: unrelated commits do not make tested bytes stale.
    changed = subprocess.check_output(
        ["git", "diff", "--name-only", expected, "FETCH_HEAD"], text=True
    ).splitlines()
    if any(is_image_input(path) for path in changed):
        raise SystemExit(
            "image inputs differ from current master; rerun current workflow"
        )
    metadata = json.loads(
        subprocess.check_output(["docker", "image", "inspect", image], text=True)
    )
    print(check_image_metadata(metadata[0]))


if __name__ == "__main__":
    main()
