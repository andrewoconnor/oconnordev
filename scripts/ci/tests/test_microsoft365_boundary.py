"""Secretless source/contract regression; mock plans cover rendered resources."""

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


class Microsoft365BoundaryTests(unittest.TestCase):
    def test_reviewed_owner_activation_defaults(self):
        import re

        source = (ROOT / "infra/aws/tools/microsoft365-runtime.tf").read_text()
        defaults = dict(
            re.findall(
                r'variable "(microsoft365_[^"]+)" \{.*?default\s*=\s*([^\n]+)',
                source,
                re.S,
            )
        )
        self.assertEqual(
            defaults,
            {
                "microsoft365_runtime_enabled": "true",
                "microsoft365_image_digest": (
                    '"sha256:c70a21d96fb7395455a638f76166c9418'
                    '0b28a79dd4819dc9c55f3a3d89998f1"'
                ),
                "microsoft365_client_id": '"084a3e9f-a9f4-43f7-89f9-d229cf97853e"',
                "microsoft365_owner_home_account_id": (
                    '"00000000-0000-0000-592d-43aab53672fd.'
                    '9188040d-6c67-4c5b-b112-36a304b66dad"'
                ),
            },
        )
        tools = ROOT / "infra/aws/tools"
        for path in tools.glob("*.tf"):
            self.assertNotIn(
                'resource "aws_secretsmanager_secret_version"', path.read_text()
            )
            self.assertNotIn('resource "aws_cloudwatch_log_delivery"', path.read_text())
        gateway = (tools / "gateway.tf").read_text()
        self.assertRegex(gateway, r'\bmode\s*=\s*"ENFORCE"')

    def test_runtime_and_gateway_boundary(self):
        path = ROOT / "infra/aws/tools/microsoft365-runtime.tf"
        self.assertTrue(path.exists(), "missing Microsoft365 runtime infrastructure")
        import re

        text = re.sub(r"[ \t]+", " ", path.read_text())
        for fragment in [
            "reserved_concurrent_executions = 1",
            'architectures = ["arm64"]',
            'authorization_type = "AWS_IAM"',
            '"lambda:FunctionUrlAuthType"',
            '"lambda:InvokedViaFunctionUrl"',
            '"secretsmanager:GetSecretValue", "secretsmanager:PutSecretValue"',
            "SECRET_ARN",
            "EXPECTED_HOME_ACCOUNT_ID",
            "retention_in_days = 14",
            'image_tag_mutability = "IMMUTABLE"',
        ]:
            self.assertIn(fragment, text)
        self.assertNotIn("aws_secretsmanager_secret_version", text)
        self.assertNotIn("secret_string", text)
        target = re.sub(
            r"[ \t]+",
            " ",
            (ROOT / "infra/aws/tools/target-microsoft365.tf").read_text(),
        )
        for fragment in [
            'service = "lambda"',
            'region = "us-east-1"',
            'listing_mode = "DEFAULT"',
            "microsoft365___",
            "AgentCore::OAuthUser",
            'principal.hasTag("scope")',
        ]:
            self.assertIn(fragment, target)
        self.assertNotIn("lambda {", target)

    def test_shared_repository_name_and_references(self):
        runtime = (ROOT / "infra/aws/tools/microsoft365-runtime.tf").read_text()
        self.assertIn('resource "aws_ecr_repository" "tools_images"', runtime)
        self.assertIn('name                 = "oconnordev-tools"', runtime)
        self.assertIn("aws_ecr_repository.tools_images.repository_url", runtime)
        publisher = (ROOT / "infra/aws/tools/microsoft365-publisher.tf").read_text()
        self.assertIn("aws_ecr_repository.tools_images.arn", publisher)
        workflow = (ROOT / ".github/workflows/microsoft365-image.yml").read_text()
        self.assertIn(
            "421680664125.dkr.ecr.us-east-1.amazonaws.com/oconnordev-tools", workflow
        )
        self.assertIn("--repository-name oconnordev-tools", workflow)

    def test_shared_image_tag_namespaces_target_commit_run_and_attempt(self):
        workflow = (ROOT / ".github/workflows/microsoft365-image.yml").read_text()
        self.assertIn(
            "IMAGE_TAG: microsoft365-${{ github.sha }}-"
            "${{ github.run_id }}-${{ github.run_attempt }}",
            workflow,
        )

    def test_lwa_readiness_uses_pinned_release_supported_threshold(self):
        runtime = ROOT / "infra/tools/lambdas/microsoft365_mcp"
        dockerfile = (runtime / "Dockerfile").read_text()
        self.assertIn("AWS_LWA_READINESS_CHECK_MIN_UNHEALTHY_STATUS=201", dockerfile)
        self.assertNotIn("AWS_LWA_READINESS_CHECK_HEALTHY_STATUS", dockerfile)
        self.assertIn(
            'AWS_LWA_READINESS_CHECK_MIN_UNHEALTHY_STATUS = "201"',
            (ROOT / "infra/aws/tools/microsoft365-runtime.tf").read_text(),
        )

    def test_image_workflow_selects_tools(self):
        from scripts.ci.path_selection import roots_for_paths

        self.assertIn(
            "infra/aws/tools",
            roots_for_paths([".github/workflows/microsoft365-image.yml"]),
        )

    def test_runtime_path_selects_tools_and_contract_is_strict(self):
        from scripts.ci.path_selection import roots_for_paths

        path = "infra/tools/lambdas/microsoft365_mcp/tools-manifest.json"
        self.assertEqual(roots_for_paths([path]), ("infra/aws/tools",))
        catalog = json.loads((ROOT / path).read_text())
        self.assertEqual(len(catalog), 5)
        manifest = json.loads(
            (ROOT / "agents/hermes/adapter/microsoft365-mcp-tools.json").read_text()
        )
        self.assertEqual({tool["name"] for tool in catalog}, set(manifest["tools"]))
        for tool in catalog:
            self.assertFalse(tool["inputSchema"]["additionalProperties"])
        workflow = (ROOT / ".github/workflows/microsoft365-image.yml").read_text()
        self.assertIn(
            "--platform linux/arm64 --provenance=false --sbom=false", workflow
        )
        self.assertIn("--network none", workflow)
        self.assertLess(
            workflow.index("Compare application inputs to fresh master"),
            workflow.index("uses: aws-actions/configure-aws-credentials"),
        )
        self.assertNotIn("pull_request_target", workflow)
        self.assertNotIn("update-function-code", workflow)

    def test_manifest_is_exact_investigated_five(self):
        manifest = json.loads(
            (ROOT / "agents/hermes/adapter/microsoft365-mcp-tools.json").read_text()
        )
        expected = {
            "get-mail-message",
            "list-mail-messages",
            "list-mail-folders",
            "list-mail-child-folders",
            "list-mail-folder-messages",
        }
        self.assertEqual(set(manifest["tools"]), expected)
        self.assertEqual(len(manifest["tools"]), 5)
        self.assertEqual(manifest["gateway_action_prefix"], "microsoft365___")
