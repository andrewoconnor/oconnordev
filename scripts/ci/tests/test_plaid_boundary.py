import importlib.util
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


class PlaidBoundaryTests(unittest.TestCase):
    def test_no_secret_value_public_endpoint_or_identity_resources(self):
        paths = [
            ROOT / "infra/aws/tools" / name
            for name in ["plaid-runtime.tf", "target-plaid.tf"]
        ]
        self.assertTrue(
            all(path.exists() for path in paths), "Plaid infrastructure missing"
        )
        source = "\n".join(path.read_text() for path in paths)
        for forbidden in [
            "aws_secretsmanager_secret_version",
            "secret_string",
            "secret_binary",
            "aws_lambda_function_url",
            "aws_lambda_permission",
            "aws_bedrockagentcore_workload_identity",
            "aws_bedrockagentcore_oauth2_credential_provider",
            "aws_db_instance",
            "aws_nat_gateway",
            "image_uri",
        ]:
            self.assertNotIn(forbidden, source)
        self.assertIn('resource "aws_secretsmanager_secret" "plaid"', source)
        self.assertIn(
            'source_dir  = "${local.repo_root}/infra/aws/tools/lambdas/plaid"', source
        )

    def test_fixed_read_endpoint_catalog_matches_runtime(self):
        path = ROOT / "infra/aws/tools/target-plaid.tf"
        self.assertTrue(path.exists(), "Plaid target missing")
        spec = importlib.util.spec_from_file_location(
            "native_plaid_boundary", ROOT / "infra/aws/tools/lambdas/plaid/plaid.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        endpoints = dict(re.findall(r'(get\w+)\s*=\s*"(/[^\"]+)"', path.read_text()))
        self.assertEqual(endpoints, {k: v for k, v in module.PATHS.items() if v})
        catalog = json.loads(
            (ROOT / "infra/aws/tools/lambdas/plaid/tools.json").read_text()
        )
        self.assertEqual({t["name"] for t in catalog["tools"]}, set(module.PATHS))

    def test_ci_discovers_all_plaid_tests(self):
        source = (ROOT / "mise.toml").read_text()
        for directory in [
            "infra/aws/tools/lambdas/plaid",
            "scripts/bootstrap",
            "scripts/plaid",
        ]:
            self.assertRegex(source, rf"unittest discover -s {directory} .*test_.*\.py")
