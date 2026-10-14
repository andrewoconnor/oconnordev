"""Exercise the real offline mock plan and reject management/import changes."""

import json
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


def verify_plan(plan: dict[str, Any]) -> None:
    module = plan["configuration"]["root_module"]
    resources = module.get("resources", [])
    if module.get("module_calls") or len(resources) != 1:
        raise ValueError("Discovery must contain exactly one data source, no modules")
    if (
        resources[0].get("address") != "data.google_project.google_auth"
        or resources[0].get("mode") != "data"
    ):
        raise ValueError("Discovery must not manage resources")
    for resource in plan.get("resource_changes", []):
        change = resource["change"]
        if (
            resource.get("mode") != "data"
            or change.get("importing") is not None
            or change["actions"] not in (["read"], ["no-op"])
        ):
            raise ValueError(
                "Discovery must have zero managed changes and zero imports"
            )


def main() -> None:
    result = subprocess.run(
        ["tofu", "-chdir=infra/gcp/google-auth", "test", "-json", "-verbose"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    events = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    plans = [
        event["test_plan"]
        for event in events
        if event.get("type") == "test_plan"
        and event.get("@testrun") == "exact_project_succeeds"
    ]
    if len(plans) != 1:
        raise ValueError("Expected exactly one successful identity mock plan")
    verify_plan(plans[0])
    print("Verified offline mock plan: 0 managed adds/changes/destroys, 0 imports")


if __name__ == "__main__":
    main()
