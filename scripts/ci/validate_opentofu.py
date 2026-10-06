from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from path_selection import ALL_ROOTS, roots_for_paths  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]


def _changed_paths(base_ref: str) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base_ref}...HEAD"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def _selected_roots() -> tuple[str, ...]:
    base_branch = os.environ.get("GITHUB_BASE_REF")
    if not base_branch:
        return ALL_ROOTS
    return roots_for_paths(_changed_paths(f"origin/{base_branch}"))


def _run(command: list[str], env: dict[str, str]) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, cwd=REPO_ROOT, env=env, check=True)


def main() -> int:
    roots = _selected_roots()
    if not roots:
        print("No OpenTofu roots are affected by this change set; validation job reports success.")
        return 0

    plugin_cache = Path(
        os.environ.get("TF_PLUGIN_CACHE_DIR", "~/.opentofu.d/plugin-cache")
    ).expanduser()
    plugin_cache.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["TF_PLUGIN_CACHE_DIR"] = str(plugin_cache)

    for root in roots:
        print(f"Validating {root}", flush=True)
        _run(
            [
                "tofu",
                f"-chdir={root}",
                "init",
                "-backend=false",
                "-input=false",
                "-no-color",
                "-lockfile=readonly",
            ],
            env,
        )
        _run(["tofu", f"-chdir={root}", "validate", "-no-color"], env)

    print(f"Validated {len(roots)} OpenTofu root(s): {', '.join(roots)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
