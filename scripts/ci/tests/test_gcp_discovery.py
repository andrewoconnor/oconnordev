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

    def test_discovery_contains_no_management_or_imports(self):
        root = ROOT / "infra/gcp/google-auth"
        self.assertTrue(root.is_dir(), "Working discovery root is missing")
        source = "\n".join(p.read_text() for p in root.glob("*.tf"))
        self.assertIn('data "google_project" "google_auth"', source)
        for forbidden in (
            'resource "',
            "import {",
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
        self.assertIn("-chdir=infra/gcp/google-auth test", run)

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

    def test_ci_selects_gcp_without_aws_inputs(self):
        root = "infra/gcp/google-auth"
        self.assertIn(root, ALL_ROOTS)
        self.assertNotIn(root, ACCOUNT_MAP_CONSUMERS)
        self.assertEqual(roots_for_paths([root + "/project.tf"]), (root,))


if __name__ == "__main__":
    unittest.main()
