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


PROJECT = "adept-presence-510022-p7"
POOL = "projects/693193037198/locations/global/workloadIdentityPools/spacelift"
MANUAL_SA = f"spacelift-google-auth@{PROJECT}.iam.gserviceaccount.com"
NATIVE_SA = "gcp-01m4xs8mrej8cdgz286edc0ab2@spacelift.iam.gserviceaccount.com"
BOOTSTRAP_IMPORTS = {
    "google_iam_workload_identity_pool.spacelift": POOL.replace(
        "693193037198", PROJECT
    ),
    "google_iam_workload_identity_pool_provider.spacelift": (
        POOL + "/providers/spacelift"
    ).replace("693193037198", PROJECT),
    "google_service_account.bootstrap": (
        f"projects/{PROJECT}/serviceAccounts/{MANUAL_SA}"
    ),
    "google_project_iam_member.browser_manual": (
        f"{PROJECT} roles/browser serviceAccount:{MANUAL_SA}"
    ),
    "google_project_iam_member.browser_native": (
        f"{PROJECT} roles/browser serviceAccount:{NATIVE_SA}"
    ),
}


def verify_bootstrap_plan(plan: dict[str, Any], expected_imports: int = 5) -> None:
    """Gate actual show-json, never infer live totals from offline mocks."""
    if expected_imports not in (0, 5):
        raise ValueError("Require five new imports initially or zero after adoption")
    expected = {address: "managed" for address in BOOTSTRAP_IMPORTS}
    expected.update(
        {
            "google_project.google_auth": "managed",
            "data.google_project.google_auth": "data",
        }
    )
    module = plan["configuration"]["root_module"]
    configured = module.get("resources", [])
    if (
        module.get("module_calls")
        or len(configured) != len(expected)
        or {r.get("address"): r.get("mode") for r in configured} != expected
    ):
        raise ValueError(
            "Only the existing project/discovery and five adopted objects are allowed"
        )
    if (
        plan.get("errored")
        or plan.get("complete") is False
        or plan.get("deferred_changes")
    ):
        raise ValueError("Plan must be complete and successful")
    for check in plan.get("checks", []):
        if check.get("status") != "pass" or any(
            i.get("status") != "pass" for i in check.get("instances", [])
        ):
            raise ValueError("Unresolved or failed checks")
    for drift in plan.get("resource_drift", []):
        if drift.get("change", {}).get("actions") != ["no-op"]:
            raise ValueError("Resource drift blocks preservation-only adoption")
    seen = set()
    imported = set()
    for resource in plan.get("resource_changes", []):
        address = resource.get("address")
        if (
            address not in expected
            or address in seen
            or resource.get("mode") != expected[address]
        ):
            raise ValueError("Unexpected or duplicate address")
        seen.add(address)
        change = resource["change"]
        if change.get("actions") != ["no-op"]:
            raise ValueError("Require zero cloud changes and resolved discovery")
        # Reuse the project-only identity, parent/billing/labels and unknown gates.
        if address == "google_project.google_auth":
            project_plan = {
                **plan,
                "configuration": {
                    "root_module": {
                        "resources": [
                            {
                                "address": "data.google_project.google_auth",
                                "mode": "data",
                            },
                            {"address": address, "mode": "managed"},
                        ]
                    }
                },
                "resource_changes": [resource],
            }
            verify_import_plan(project_plan, expected_imports=0)
            if change.get("after", {}).get("deletion_policy") != "ABANDON":
                raise ValueError("Project deletion policy must remain ABANDON")
            continue
        if change.get("after_unknown"):
            raise ValueError("Preserved values must be fully known")
        importing = change.get("importing")
        if importing is not None:
            if (
                address not in BOOTSTRAP_IMPORTS
                or importing.get("id") != BOOTSTRAP_IMPORTS[address]
            ):
                raise ValueError("Wrong import identity")
            imported.add(address)
        if address.startswith("data."):
            if importing is not None:
                raise ValueError("Discovery cannot import")
            after = change.get("after") or {}
            if any(
                after.get(k) != v
                for k, v in {
                    "project_id": PROJECT,
                    "name": "oconnordev-tools",
                    "number": "693193037198",
                }.items()
            ):
                raise ValueError("Discovery identity changed")
            continue
        after = change.get("after") or {}
        fields: dict[str, Any] = {"project": PROJECT}
        if address.startswith("google_iam_workload_identity_pool"):
            provider = address.startswith("google_iam_workload_identity_pool_provider.")
            fields.update(
                {
                    "workload_identity_pool_id": "spacelift",
                    "name": POOL + ("/providers/spacelift" if provider else ""),
                    "state": "ACTIVE",
                    "disabled": False,
                    "display_name": "spacelift" if provider else "Spacelift",
                    "deletion_policy": "ABANDON",
                }
            )
            if after.get("description") not in (None, ""):
                raise ValueError("Uninventoried description")
            if provider:
                fields.update(
                    {
                        "workload_identity_pool_provider_id": "spacelift",
                        "attribute_condition": (
                            "assertion.callerType == 'stack' && "
                            "assertion.callerId == 'oconnordev-gcp-google-auth'"
                        ),
                        "attribute_mapping": {
                            "attribute.stack": "assertion.callerId",
                            "google.subject": "assertion.sub",
                        },
                    }
                )
                oidc = after.get("oidc") or []
                if (
                    len(oidc) != 1
                    or oidc[0].get("issuer_uri")
                    != "https://andrewoconnor.app.spacelift.io"
                    or oidc[0].get("allowed_audiences")
                    != ["andrewoconnor.app.spacelift.io"]
                    or oidc[0].get("jwks_json") not in (None, "")
                    or any(after.get(k) for k in ("aws", "saml", "x509"))
                ):
                    raise ValueError("OIDC trust mismatch")
        elif address == "google_service_account.bootstrap":
            fields.update(
                {
                    "account_id": "spacelift-google-auth",
                    "email": MANUAL_SA,
                    "name": f"projects/{PROJECT}/serviceAccounts/{MANUAL_SA}",
                    "unique_id": "109396950295423788712",
                    "disabled": False,
                    "deletion_policy": "ABANDON",
                }
            )
            if any(
                after.get(k) not in (None, "") for k in ("display_name", "description")
            ):
                raise ValueError("Do not add service-account metadata")
        else:
            fields.update(
                {
                    "role": "roles/browser",
                    "member": "serviceAccount:"
                    + (MANUAL_SA if address.endswith("_manual") else NATIVE_SA),
                }
            )
            if after.get("condition") not in (None, []):
                raise ValueError("Unexpected IAM condition")
        if any(after.get(key) != value for key, value in fields.items()):
            raise ValueError(f"Preserved identity/configuration mismatch: {address}")
    if seen - {"data.google_project.google_auth"} != set(expected) - {
        "data.google_project.google_auth"
    }:
        raise ValueError(
            "Every managed object, including the existing project no-op, is required"
        )
    if imported != (set(BOOTSTRAP_IMPORTS) if expected_imports else set()):
        raise ValueError(
            "Wrong exact new import set; existing project must never re-import"
        )


READ_ACCESS_FIELDS = {
    "google_project_iam_member.wif_viewer_native": {
        "project": PROJECT,
        "role": "roles/iam.workloadIdentityPoolViewer",
        "member": f"serviceAccount:{NATIVE_SA}",
    },
    "google_service_account_iam_member.viewer_native": {
        "service_account_id": f"projects/{PROJECT}/serviceAccounts/{MANUAL_SA}",
        "role": "roles/iam.serviceAccountViewer",
        "member": f"serviceAccount:{NATIVE_SA}",
    },
}
READ_ACCESS_IMPORTS = {
    address: f"{fields.get('project', fields.get('service_account_id'))} "
    f"{fields['role']} {fields['member']}"
    for address, fields in READ_ACCESS_FIELDS.items()
}


def verify_read_access_plan(plan: dict[str, Any], expected_imports: int = 2) -> None:
    """Stage three: only two exact existing read memberships may be imported."""
    if expected_imports not in (0, 2):
        raise ValueError("Require two read-access imports or zero after adoption")
    module = plan["configuration"]["root_module"]
    configured = module.get("resources", [])
    expected = {
        **{address: "managed" for address in BOOTSTRAP_IMPORTS},
        **{address: "managed" for address in READ_ACCESS_IMPORTS},
        "google_project.google_auth": "managed",
        "data.google_project.google_auth": "data",
    }
    if (
        module.get("module_calls")
        or len(configured) != len(expected)
        or {r.get("address"): r.get("mode") for r in configured} != expected
    ):
        raise ValueError("Only existing bootstrap and two exact read members allowed")
    old_changes = []
    seen = set()
    imported = set()
    for resource in plan.get("resource_changes", []):
        address = resource.get("address")
        if address not in READ_ACCESS_IMPORTS:
            old_changes.append(resource)
            continue
        if address in seen or resource.get("mode") != "managed":
            raise ValueError("Duplicate or invalid read membership")
        seen.add(address)
        change = resource["change"]
        after = change.get("after") or {}
        fields = READ_ACCESS_FIELDS[address]
        if (
            change.get("actions") != ["no-op"]
            or change.get("after_unknown")
            or any(after.get(key) != value for key, value in fields.items())
            or after.get("condition") not in (None, [])
            or any(
                key in after and key not in fields
                for key in ("project", "service_account_id")
            )
        ):
            raise ValueError(
                "Read member must be exact, known, unconditional and no-op"
            )
        importing = change.get("importing")
        if importing is not None:
            if importing.get("id") != READ_ACCESS_IMPORTS[address]:
                raise ValueError("Wrong read membership import identity")
            imported.add(address)
    if seen != set(READ_ACCESS_IMPORTS) or imported != (
        set(READ_ACCESS_IMPORTS) if expected_imports else set()
    ):
        raise ValueError("Wrong exact read membership/import set")
    # Reuse all historical identity, trust, drift, checks and no-op guards.
    # Historical import blocks stay idempotent: no bootstrap/project re-imports.
    verify_bootstrap_plan(
        {
            **plan,
            "configuration": {
                "root_module": {
                    **module,
                    "resources": [
                        r
                        for r in configured
                        if r.get("address") not in READ_ACCESS_IMPORTS
                    ],
                }
            },
            "resource_changes": old_changes,
        },
        expected_imports=0,
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
            {r.get("address") for r in managed}
            != set(BOOTSTRAP_IMPORTS)
            | set(READ_ACCESS_IMPORTS)
            | {"google_project.google_auth"}
            or len(managed) != 8
            or any(
                r["change"]["actions"] != ["create"]
                or r["change"].get("importing") is not None
                for r in managed
            )
        ):
            raise ValueError(
                "Offline fixture must create only eight mocked objects; no import"
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
    parser.add_argument(
        "--mode",
        choices=("read-access", "bootstrap"),
        default="read-access",
        help="Current read-access stage (default) or historical bootstrap gate",
    )
    parser.add_argument("--expected-imports", type=int, choices=(0, 2, 5))
    args = parser.parse_args()
    expected_imports = args.expected_imports
    if expected_imports is None:
        expected_imports = 2 if args.mode == "read-access" else 5
    if expected_imports not in ((0, 2) if args.mode == "read-access" else (0, 5)):
        parser.error("Import count does not match the selected adoption stage")
    if args.plan_json:
        verifier = (
            verify_read_access_plan
            if args.mode == "read-access"
            else verify_bootstrap_plan
        )
        verifier(json.loads(args.plan_json.read_text()), expected_imports)
        print(
            f"Verified supplied plan: {expected_imports} imports, "
            "0 adds, 0 changes, 0 destroys; no drift"
        )
    else:
        run_offline_tests()


if __name__ == "__main__":
    main()
