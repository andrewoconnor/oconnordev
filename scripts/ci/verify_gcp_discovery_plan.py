"""Test offline adoption configuration or gate supplied real import-plan JSON."""

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


def verify_import_plan(plan: dict[str, Any], expected_imports: int = 1) -> None:
    """Fail closed on real `tofu show -json` output; mocks cannot prove import."""
    if expected_imports not in (0, 1):
        raise ValueError("Expected imports must be zero (post-adoption) or one")
    module = plan["configuration"]["root_module"]
    expected = {
        "data.google_project.google_auth": "data",
        "google_project.google_auth": "managed",
    }
    resources = module.get("resources", [])
    if (
        module.get("module_calls")
        or len(resources) != 2
        or {r.get("address"): r.get("mode") for r in resources} != expected
    ):
        raise ValueError(
            "Only the exact project resource and discovery data are allowed"
        )
    if plan.get("errored") or plan.get("complete") is False:
        raise ValueError("Plan must be complete and successful")
    for check in plan.get("checks", []):
        if check.get("status") != "pass":
            raise ValueError("Plan has unresolved or failed checks")
    for drift in plan.get("resource_drift", []):
        if drift.get("change", {}).get("actions") != ["no-op"]:
            raise ValueError("Resource drift blocks preservation-only adoption")
    seen = set()
    imports = 0
    for resource in plan.get("resource_changes", []):
        address = resource.get("address")
        if (
            address not in expected
            or address in seen
            or resource.get("mode") != expected[address]
        ):
            raise ValueError("Unexpected or duplicate resource change")
        seen.add(address)
        change = resource["change"]
        importing = change.get("importing")
        if address == "data.google_project.google_auth":
            if importing is not None or change.get("actions") not in (
                ["read"],
                ["no-op"],
            ):
                raise ValueError("Discovery must remain read-only")
            continue
        if change.get("actions") != ["no-op"]:
            raise ValueError(
                "Adoption requires zero adds, updates, replacements and destroys"
            )
        if importing is not None:
            if importing.get("id") != "adept-presence-510022-p7":
                raise ValueError("Unexpected import ID")
            imports += 1
        after = change.get("after") or {}
        if any(
            after.get(key) != value
            for key, value in {
                "project_id": "adept-presence-510022-p7",
                "number": "693193037198",
                "name": "oconnordev-tools",
            }.items()
        ):
            raise ValueError("Imported project identity must be known and exact")
        if any(
            after.get(key) not in (None, "")
            for key in ("org_id", "folder_id", "billing_account")
        ) or after.get("effective_labels") not in (None, {}):
            raise ValueError(
                "Unexpected parent, billing account or labels: stop for owner readback"
            )
        if change.get("after_unknown"):
            raise ValueError("Preservation-only project values must be fully known")
    if "google_project.google_auth" not in seen or imports != expected_imports:
        raise ValueError(
            f"Expected exactly {expected_imports} imports of the approved project"
        )


def run_offline_tests() -> None:
    """Copy actual configuration, omitting only unsupported mock import blocks."""
    import os
    import shutil
    import tempfile

    source = ROOT / "infra/gcp/google-auth"
    with tempfile.TemporaryDirectory(
        prefix="gcp-adoption-mock-", dir=os.environ.get("TMPDIR")
    ) as directory:
        fixture = Path(directory)
        for path in source.iterdir():
            if path.name != "imports.tf" and (
                path.suffix == ".tf"
                or path.name.endswith(".tftest.hcl")
                or path.name == ".terraform.lock.hcl"
            ):
                shutil.copy2(path, fixture / path.name)
        subprocess.run(
            [
                "tofu",
                f"-chdir={fixture}",
                "init",
                "-backend=false",
                "-input=false",
                "-lockfile=readonly",
                "-no-color",
            ],
            check=True,
        )
        result = subprocess.run(
            ["tofu", f"-chdir={fixture}", "test", "-json", "-verbose"],
            capture_output=True,
            text=True,
        )
        if result.returncode:
            print(result.stdout)
            print(result.stderr)
            result.check_returncode()
        events = [
            json.loads(line) for line in result.stdout.splitlines() if line.strip()
        ]
        for event in events:
            if event.get("type") in ("test_run", "test_summary"):
                print(event.get("@message"))
        plans = [
            event["test_plan"]
            for event in events
            if event.get("type") == "test_plan"
            and event.get("@testrun") == "exact_project_succeeds"
        ]
        if len(plans) != 1:
            raise ValueError("Expected one offline exact-identity plan")
        managed = [
            r
            for r in plans[0].get("resource_changes", [])
            if r.get("mode") == "managed"
        ]
        if (
            len(managed) != 1
            or managed[0].get("address") != "google_project.google_auth"
            or managed[0]["change"]["actions"] != ["create"]
            or managed[0]["change"].get("importing") is not None
        ):
            raise ValueError(
                "Offline fixture must create only the mocked project; no import"
            )
        print(
            "Verified offline fixture: mocked creation/identity; imports omitted. "
            "NOT live import evidence."
        )


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--plan-json",
        type=Path,
        help="Real tofu show -json plan; no generated/mocked import evidence",
    )
    parser.add_argument("--expected-imports", type=int, choices=(0, 1), default=1)
    args = parser.parse_args()
    if args.plan_json:
        verify_import_plan(
            json.loads(args.plan_json.read_text()), args.expected_imports
        )
        print(
            f"Verified supplied plan: {args.expected_imports} imports, "
            "0 adds, 0 changes, 0 destroys; no drift"
        )
    else:
        run_offline_tests()


if __name__ == "__main__":
    main()
