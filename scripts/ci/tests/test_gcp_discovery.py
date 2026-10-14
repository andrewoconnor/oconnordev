"""Stage-one native GCP safety contracts; no live credentials required."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts/ci"))
from path_selection import (  # noqa: E402
    ACCOUNT_MAP_CONSUMERS,
    ALL_ROOTS,
    roots_for_paths,
)


class GCPDiscoveryTests(unittest.TestCase):
    def test_native_stack_is_separate_and_least_privilege(self):
        path = ROOT / "infra/spacelift/gcp-google-auth.tf"
        self.assertTrue(path.exists(), "Native GCP administrative wiring is missing")
        source = path.read_text()
        self.assertIn('resource "spacelift_stack" "gcp_google_auth"', source)
        self.assertIn('name        = "oconnordev-gcp-google-auth"', source)
        self.assertIn('project_root = "infra/gcp/google-auth"', source)
        self.assertIn("autodeploy            = false", source)
        self.assertIn("protect_from_deletion = true", source)
        self.assertIn('resource "spacelift_gcp_service_account" "google_auth"', source)
        self.assertIn(
            'token_scopes = ["https://www.googleapis.com/auth/cloud-platform"]', source
        )
        self.assertIn(
            "spacelift_gcp_service_account.google_auth.service_account_email", source
        )
        for forbidden in (
            "for_each",
            "aws_integration",
            "infra/aws",
            "GOOGLE_APPLICATION_CREDENTIALS",
            "oidc",
        ):
            self.assertNotIn(forbidden, source)
        self.assertNotIn(
            "gcp_google_auth", (ROOT / "infra/spacelift/main.tf").read_text()
        )

    def test_preservation_only_project_import(self):
        root = ROOT / "infra/gcp/google-auth"
        source = (root / "project.tf").read_text()
        self.assertIn('resource "google_project" "google_auth"', source)
        imports = (root / "imports.tf").read_text()
        self.assertIn("to = google_project.google_auth", imports)
        self.assertIn('id = "adept-presence-510022-p7"', imports)
        self.assertIn("prevent_destroy = true", source)
        self.assertIn('deletion_policy = "ABANDON"', source)
        self.assertIn("ignore_changes = [auto_create_network]", source)
        provider = " ".join((root / "providers.tf").read_text().split())
        self.assertIn('deletion_policy = "ABANDON"', provider)
        self.assertIn("add_terraform_attribution_label = false", provider)
        for forbidden in (
            "billing_account =",
            "org_id =",
            "folder_id =",
            "google_project_iam",
            "google_compute",
            "google_project_service",
            "ignore_changes = all",
        ):
            self.assertNotIn(forbidden, source)
        self.assertIn('self.number == "693193037198"', source)

    def test_discovery_identity_is_retained(self):
        root = ROOT / "infra/gcp/google-auth"
        self.assertTrue(root.is_dir(), "Working discovery root is missing")
        source = "\n".join(p.read_text() for p in root.glob("*.tf"))
        self.assertIn('data "google_project" "google_auth"', source)
        for forbidden in (
            "credentials",
            "access_token",
            "billing_account =",
            "google_iam_oauth_client",
        ):
            self.assertNotIn(forbidden, source)
        self.assertIn('project_id = "adept-presence-510022-p7"', source)
        self.assertIn('self.number == "693193037198"', source)
        self.assertIn('self.name == "oconnordev-tools"', source)
        self.assertIn('self.project_id == "adept-presence-510022-p7"', source)
        self.assertIn('version = "8.7.0"', source)

    def test_mise_runs_discovery_mock_tests(self):
        import tomllib

        tasks = tomllib.loads((ROOT / "mise.toml").read_text())["tasks"]
        self.assertIn("test:opentofu-gcp", tasks["test"]["depends"])
        run = tasks["test:opentofu-gcp"]["run"]
        self.assertIn("-lockfile=readonly", run)
        self.assertIn("python3 scripts/ci/verify_gcp_discovery_plan.py", run)

    def test_mock_plan_gate_rejects_cloud_mutation(self):
        gate = ROOT / "scripts/ci/verify_gcp_discovery_plan.py"
        self.assertTrue(gate.exists(), "Mock-plan no-change gate is missing")
        from verify_gcp_discovery_plan import verify_plan

        # Unit fixture, not live output. The task feeds this gate real mock-plan JSON.
        valid = {
            "configuration": {
                "root_module": {
                    "resources": [
                        {"address": "data.google_project.google_auth", "mode": "data"}
                    ]
                }
            }
        }
        verify_plan(valid)
        import copy

        for action in ("create", "update", "delete"):
            mutated = copy.deepcopy(valid)
            mutated["resource_changes"] = [
                {"mode": "managed", "change": {"actions": [action]}}
            ]
            with self.subTest(action=action), self.assertRaises(ValueError):
                verify_plan(mutated)
        imported = copy.deepcopy(valid)
        imported["resource_changes"] = [
            {"change": {"actions": ["no-op"], "importing": {"id": "project"}}}
        ]
        with self.assertRaises(ValueError):
            verify_plan(imported)
        tasks = (ROOT / "mise.toml").read_text()
        self.assertIn("python3 scripts/ci/verify_gcp_discovery_plan.py", tasks)

    def test_import_plan_gate_accepts_only_exact_import(self):
        import copy

        from verify_gcp_discovery_plan import verify_import_plan

        # Synthetic unit fixture ONLY, never provider/live plan evidence.
        valid = {
            "configuration": {
                "root_module": {
                    "resources": [
                        {"address": "data.google_project.google_auth", "mode": "data"},
                        {"address": "google_project.google_auth", "mode": "managed"},
                    ]
                }
            },
            "resource_changes": [
                {
                    "address": "google_project.google_auth",
                    "mode": "managed",
                    "change": {
                        "actions": ["no-op"],
                        "importing": {"id": "adept-presence-510022-p7"},
                        "after": {
                            "project_id": "adept-presence-510022-p7",
                            "name": "oconnordev-tools",
                            "number": "693193037198",
                        },
                    },
                }
            ],
        }
        verify_import_plan(valid, expected_imports=1)
        for mutation in (
            "create",
            "update",
            "delete",
            "wrong_id",
            "wrong_address",
            "missing_import",
            "drift",
            "wrong_number",
            "wrong_name",
            "duplicate",
            "extra",
            "unknown_checks",
            "parent",
            "billing",
            "labels",
        ):
            changed = copy.deepcopy(valid)
            resource = changed["resource_changes"][0]
            if mutation in ("create", "update", "delete"):
                resource["change"]["actions"] = [mutation]
            elif mutation == "wrong_id":
                resource["change"]["importing"]["id"] = "another-project"
            elif mutation == "wrong_address":
                resource["address"] = "google_project.other"
            elif mutation == "missing_import":
                del resource["change"]["importing"]
            elif mutation == "wrong_number":
                resource["change"]["after"]["number"] = "693193037199"
            elif mutation == "wrong_name":
                resource["change"]["after"]["name"] = "another-project"
            elif mutation == "duplicate":
                changed["resource_changes"].append(copy.deepcopy(resource))
            elif mutation == "extra":
                extra = copy.deepcopy(resource)
                extra["address"] = "google_project.other"
                changed["resource_changes"].append(extra)
            elif mutation == "unknown_checks":
                changed["checks"] = [{"status": "unknown"}]
            elif mutation == "parent":
                resource["change"]["after"]["folder_id"] = "123"
            elif mutation == "billing":
                resource["change"]["after"]["billing_account"] = "123456-123456-123456"
            elif mutation == "labels":
                resource["change"]["after"]["effective_labels"] = {"new": "label"}
            else:
                changed["resource_drift"] = [{"change": {"actions": ["update"]}}]
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                verify_import_plan(changed, expected_imports=1)

    def test_ci_selects_gcp_without_aws_inputs(self):
        root = "infra/gcp/google-auth"
        self.assertIn(root, ALL_ROOTS)
        self.assertNotIn(root, ACCOUNT_MAP_CONSUMERS)
        self.assertEqual(roots_for_paths([root + "/project.tf"]), (root,))


if __name__ == "__main__":
    unittest.main()
