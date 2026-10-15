"""Stage-three synthetic unit plans; never live IAM or import evidence."""

import copy
import importlib
import sys
import unittest
from pathlib import Path

from test_gcp_auth_bootstrap import NATIVE, PROJECT, SA, fixture

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts/ci"))
gate = importlib.import_module("verify_gcp_discovery_plan")

MEMBER = f"serviceAccount:{NATIVE}"
SA_ID = f"projects/{PROJECT}/serviceAccounts/{SA}"
VALUES = {
    "google_project_iam_member.wif_viewer_native": {
        "project": PROJECT,
        "role": "roles/iam.workloadIdentityPoolViewer",
        "member": MEMBER,
        "condition": [],
    },
    "google_service_account_iam_member.viewer_native": {
        "service_account_id": SA_ID,
        "role": "roles/iam.serviceAccountViewer",
        "member": MEMBER,
        "condition": [],
    },
}
IDS = {
    address: f"{value.get('project', SA_ID)} {value['role']} {MEMBER}"
    for address, value in VALUES.items()
}


def read_fixture(imports=2):
    plan = fixture(0)
    for address, value in VALUES.items():
        plan["configuration"]["root_module"]["resources"].append(
            {"address": address, "mode": "managed"}
        )
        change = {"actions": ["no-op"], "after": copy.deepcopy(value)}
        if imports:
            change["importing"] = {"id": IDS[address]}
        plan["resource_changes"].append(
            {"address": address, "mode": "managed", "change": change}
        )
    return plan


class ReadAccessTests(unittest.TestCase):
    def test_exact_two_imports_and_post_adoption_noop(self):
        self.assertTrue(hasattr(gate, "verify_read_access_plan"), "Missing read gate")
        gate.verify_read_access_plan(read_fixture(), expected_imports=2)
        gate.verify_read_access_plan(read_fixture(0), expected_imports=0)
        with self.assertRaises(ValueError):
            gate.verify_read_access_plan(read_fixture(), expected_imports=5)

    def test_rejects_broader_or_conditional_members_and_every_cloud_action(self):
        self.assertTrue(hasattr(gate, "verify_read_access_plan"), "Missing read gate")
        for index in (-1, -2):
            for key, value in (
                ("role", "roles/owner"),
                ("role", "roles/iam.serviceAccountAdmin"),
                ("role", "roles/viewer"),
                ("member", "allAuthenticatedUsers"),
                ("member", f"serviceAccount:{SA}"),
                ("condition", [{"title": "invented", "expression": "true"}]),
                ("project", "another-project"),
                ("service_account_id", f"projects/{PROJECT}/serviceAccounts/other"),
            ):
                plan = read_fixture()
                after = plan["resource_changes"][index]["change"]["after"]
                # Wrong resource-scope fields are not silently accepted either.
                after[key] = value
                with self.subTest(index=index, key=key), self.assertRaises(ValueError):
                    gate.verify_read_access_plan(plan)
        for actions in (
            ["create"],
            ["update"],
            ["delete"],
            ["delete", "create"],
            ["read"],
        ):
            plan = read_fixture()
            plan["resource_changes"][-1]["change"]["actions"] = actions
            with self.subTest(actions=actions), self.assertRaises(ValueError):
                gate.verify_read_access_plan(plan)

    def test_all_existing_preservation_guards_remain_active(self):
        self.assertTrue(hasattr(gate, "verify_read_access_plan"), "Missing read gate")
        for index in range(len(read_fixture()["resource_changes"])):
            for mutation in ("unknown", "missing", "import", "update", "duplicate"):
                plan = read_fixture()
                resource = plan["resource_changes"][index]
                if mutation == "unknown":
                    resource["change"]["after_unknown"] = {"member": True}
                elif mutation == "missing":
                    plan["resource_changes"].remove(resource)
                elif mutation == "import":
                    resource["change"]["importing"] = {"id": PROJECT}
                elif mutation == "update":
                    resource["change"]["actions"] = ["update"]
                else:
                    plan["resource_changes"].append(copy.deepcopy(resource))
                with (
                    self.subTest(index=index, mutation=mutation),
                    self.assertRaises(ValueError),
                ):
                    gate.verify_read_access_plan(plan)
        for key, value in (
            ("errored", True),
            ("complete", False),
            ("deferred_changes", [{"reason": "unknown"}]),
            ("checks", [{"status": "unknown"}]),
            ("checks", [{"status": "pass", "instances": [{"status": "fail"}]}]),
            ("resource_drift", [{"change": {"actions": ["update"]}}]),
        ):
            plan = read_fixture()
            plan[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                gate.verify_read_access_plan(plan)
        plan = read_fixture()
        plan["resource_changes"][2]["change"]["after"]["attribute_condition"] = "true"
        with self.assertRaises(ValueError):
            gate.verify_read_access_plan(plan)

    def test_cli_defaults_to_read_access_and_keeps_explicit_bootstrap_mode(self):
        import contextlib
        import io
        import json
        import tempfile
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic-unit-only.json"
            for argv, plan in (
                (["--plan-json", str(path)], read_fixture()),
                (["--mode", "bootstrap", "--plan-json", str(path)], fixture()),
            ):
                path.write_text(json.dumps(plan))
                with (
                    patch.object(sys, "argv", ["gate", *argv]),
                    contextlib.redirect_stdout(io.StringIO()),
                ):
                    gate.main()

    def test_only_two_new_additive_members_and_exact_import_triples(self):
        root = ROOT / "infra/gcp/google-auth"
        source = (
            (root / "read-access.tf").read_text()
            if (root / "read-access.tf").exists()
            else ""
        )
        self.assertEqual(source.count('resource "google_project_iam_member"'), 1)
        self.assertEqual(
            source.count('resource "google_service_account_iam_member"'), 1
        )
        self.assertEqual(source.count("prevent_destroy = true"), 2)
        for forbidden in (
            "iam_binding",
            "iam_policy",
            "roles/owner",
            "roles/editor",
            "condition {",
            "google_project_service",
        ):
            self.assertNotIn(forbidden, source)
        imports = (root / "imports.tf").read_text()
        self.assertEqual(imports.count("import {"), 8)
        for address, identity in IDS.items():
            self.assertIn(f"to = {address}", imports)
            self.assertIn(f'id = "{identity}"', imports)


if __name__ == "__main__":
    unittest.main()
