"""Preservation-only bootstrap contracts; synthetic plans are unit fixtures only."""

import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts/ci"))

PROJECT = "adept-presence-510022-p7"
POOL = "projects/693193037198/locations/global/workloadIdentityPools/spacelift"
SA = f"spacelift-google-auth@{PROJECT}.iam.gserviceaccount.com"
NATIVE = "gcp-01m4xs8mrej8cdgz286edc0ab2@spacelift.iam.gserviceaccount.com"
CONDITION = (
    "assertion.callerType == 'stack' && "
    "assertion.callerId == 'oconnordev-gcp-google-auth'"
)


def fixture(imports=5):
    """Synthetic unit input, NOT a provider plan or inventory dump."""
    values = {
        "google_project.google_auth": {
            "project_id": PROJECT,
            "number": "693193037198",
            "name": "oconnordev-tools",
            "deletion_policy": "ABANDON",
        },
        "google_iam_workload_identity_pool.spacelift": {
            "project": PROJECT,
            "workload_identity_pool_id": "spacelift",
            "name": POOL,
            "display_name": "Spacelift",
            "description": "",
            "disabled": False,
            "state": "ACTIVE",
            "deletion_policy": "ABANDON",
        },
        "google_iam_workload_identity_pool_provider.spacelift": {
            "project": PROJECT,
            "workload_identity_pool_id": "spacelift",
            "workload_identity_pool_provider_id": "spacelift",
            "name": POOL + "/providers/spacelift",
            "display_name": "spacelift",
            "description": "",
            "disabled": False,
            "state": "ACTIVE",
            "deletion_policy": "ABANDON",
            "attribute_condition": CONDITION,
            "attribute_mapping": {
                "attribute.stack": "assertion.callerId",
                "google.subject": "assertion.sub",
            },
            "oidc": [
                {
                    "issuer_uri": "https://andrewoconnor.app.spacelift.io",
                    "allowed_audiences": ["andrewoconnor.app.spacelift.io"],
                    "jwks_json": "",
                }
            ],
        },
        "google_service_account.bootstrap": {
            "project": PROJECT,
            "account_id": "spacelift-google-auth",
            "email": SA,
            "name": f"projects/{PROJECT}/serviceAccounts/{SA}",
            "unique_id": "109396950295423788712",
            "display_name": "",
            "description": "",
            "disabled": False,
            "deletion_policy": "ABANDON",
        },
    }
    ids = {
        "google_iam_workload_identity_pool.spacelift": POOL.replace(
            "693193037198", PROJECT
        ),
        "google_iam_workload_identity_pool_provider.spacelift": (
            POOL + "/providers/spacelift"
        ).replace("693193037198", PROJECT),
        "google_service_account.bootstrap": f"projects/{PROJECT}/serviceAccounts/{SA}",
    }
    for name, email in (("manual", SA), ("native", NATIVE)):
        address = "google_project_iam_member.browser_" + name
        values[address] = {
            "project": PROJECT,
            "role": "roles/browser",
            "member": "serviceAccount:" + email,
            "condition": [],
        }
        ids[address] = f"{PROJECT} roles/browser serviceAccount:{email}"
    resources = [{"address": "data.google_project.google_auth", "mode": "data"}]
    changes = []
    for address, after in values.items():
        resources.append({"address": address, "mode": "managed"})
        change = {"actions": ["no-op"], "after": after}
        if imports and address in ids:
            change["importing"] = {"id": ids[address]}
        changes.append({"address": address, "mode": "managed", "change": change})
    return {
        "configuration": {"root_module": {"resources": resources}},
        "resource_changes": changes,
    }


class BootstrapTests(unittest.TestCase):
    def test_gate_requires_exact_five_new_imports_or_zero_afterward(self):
        import verify_gcp_discovery_plan as gate

        self.assertTrue(
            hasattr(gate, "verify_bootstrap_plan"), "Bootstrap gate is missing"
        )
        gate.verify_bootstrap_plan(fixture(), expected_imports=5)
        gate.verify_bootstrap_plan(fixture(0), expected_imports=0)
        with self.assertRaises(ValueError):
            gate.verify_bootstrap_plan(fixture(), expected_imports=1)
        for address in [r["address"] for r in fixture()["resource_changes"]]:
            for mutation in (
                "update",
                "unknown",
                "missing",
                "wrong_import",
                "identity",
            ):
                changed = fixture()
                resource = next(
                    r for r in changed["resource_changes"] if r["address"] == address
                )
                if mutation == "update":
                    resource["change"]["actions"] = ["update"]
                elif mutation == "unknown":
                    resource["change"]["after_unknown"] = {"name": True}
                elif mutation == "missing":
                    changed["resource_changes"].remove(resource)
                elif mutation == "wrong_import":
                    resource["change"]["importing"] = {"id": PROJECT}
                else:
                    resource["change"]["after"][
                        "name" if address.startswith("google_project.") else "project"
                    ] = "wrong"
                with (
                    self.subTest(address=address, mutation=mutation),
                    self.assertRaises(ValueError),
                ):
                    gate.verify_bootstrap_plan(changed, expected_imports=5)

    def test_gate_rejects_trust_policy_anomalies_and_drift(self):
        import verify_gcp_discovery_plan as gate

        self.assertTrue(
            hasattr(gate, "verify_bootstrap_plan"), "Bootstrap gate is missing"
        )
        for index, key, value in (
            (1, "state", "DELETED"),
            (1, "disabled", True),
            (2, "attribute_condition", "true"),
            (2, "attribute_mapping", {}),
            (2, "oidc", []),
            (2, "display_name", "Spacelift"),
            (3, "display_name", "Spacelift Google Auth"),
            (3, "unique_id", "123"),
            (4, "role", "roles/owner"),
            (5, "condition", [{"expression": "true"}]),
        ):
            plan = fixture()
            plan["resource_changes"][index]["change"]["after"][key] = value
            with self.subTest(key=key, index=index), self.assertRaises(ValueError):
                gate.verify_bootstrap_plan(plan)
        for field, value in (
            ("errored", True),
            ("complete", False),
            ("checks", [{"status": "unknown"}]),
            ("checks", [{"status": "fail"}]),
            ("resource_drift", [{"change": {"actions": ["update"]}}]),
        ):
            plan = copy.deepcopy(fixture())
            plan[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                gate.verify_bootstrap_plan(plan)

    def test_only_existing_additive_resources_are_declared(self):
        root = ROOT / "infra/gcp/google-auth"
        source = (
            (root / "auth-bootstrap.tf").read_text()
            if (root / "auth-bootstrap.tf").exists()
            else ""
        )
        self.assertIn(
            'resource "google_iam_workload_identity_pool" "spacelift"', source
        )
        self.assertIn(
            'resource "google_iam_workload_identity_pool_provider" "spacelift"', source
        )
        self.assertIn('resource "google_service_account" "bootstrap"', source)
        self.assertEqual(source.count('resource "google_project_iam_member"'), 2)
        self.assertEqual(source.count("prevent_destroy = true"), 5)
        self.assertEqual(source.count("deletion_policy"), 3)
        for forbidden in (
            "google_project_service",
            "google_project_iam_binding",
            "google_project_iam_policy",
            "google_service_account_iam",
            "roles/owner",
            "workloadIdentityUser",
            "ignore_changes",
            "google_iam_oauth_client",
        ):
            self.assertNotIn(forbidden, source)
        imports = (root / "imports.tf").read_text()
        self.assertEqual(
            imports.count("import {"),
            6,
            "Existing project history plus five new imports",
        )
        sa = source.split('resource "google_service_account"')[1].split(
            'resource "google_project_iam_member"'
        )[0]
        self.assertNotIn("display_name", sa)
        self.assertIn(CONDITION, source)


if __name__ == "__main__":
    unittest.main()
