"""Static boundary checks for the owner-managed API key parameter."""

import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[2]


class ParameterBoundaryTests(unittest.TestCase):
    def test_rollout_preserves_legacy_configuration_and_both_permissions(self):
        function = (TOOLS / "spacelift-token-rotation.tf").read_text()
        target = (TOOLS / "target-spacelift.tf").read_text()
        iam = (TOOLS / "spacelift-token-rotation-iam.tf").read_text()
        self.assertIn("API_KEY_SECRET_ID", function)
        self.assertIn("API_KEY_PARAMETER_NAME     = local.spacelift_api_key_parameter_name", function)
        self.assertNotIn('variable "hermes_spacelift_use_ssm_api_key"', target)
        self.assertIn("secretsmanager:GetSecretValue", iam)
        self.assertIn("local.spacelift_legacy_api_key_secret_arn", iam)
        self.assertIn("ssm:GetParameter", iam)
        self.assertIn("${var.hermes_spacelift_api_key_secret_name}-??????", target)

    def test_api_key_parameter_is_reference_only_and_scoped(self):
        target = (TOOLS / "target-spacelift.tf").read_text()
        iam = (TOOLS / "spacelift-token-rotation-iam.tf").read_text()
        function = (TOOLS / "spacelift-token-rotation.tf").read_text()
        self.assertIn(
            'spacelift_api_key_parameter_name = "/hermes/spacelift/api-key"', target
        )
        self.assertIn("parameter${local.spacelift_api_key_parameter_name}", target)
        all_tf = "\n".join(path.read_text() for path in TOOLS.glob("*.tf"))
        self.assertNotIn('data "aws_ssm_parameter"', target)
        self.assertNotIn('resource "aws_ssm_parameter"', target)
        self.assertEqual(all_tf.count("/hermes/spacelift/api-key"), 2)
        self.assertNotIn("aws_ssm_parameter.spacelift", all_tf)
        guardrail = (TOOLS / "target-aws.tf").read_text()
        for action in (
            "ssm:GetParameter",
            "ssm:GetParameters",
            "ssm:GetParametersByPath",
            "ssm:GetParameterHistory",
        ):
            self.assertIn(f'"{action}"', guardrail)
        self.assertIn("local.spacelift_api_key_parameter_arn", guardrail)
        self.assertIn("parameter/hermes/spacelift", guardrail)
        self.assertNotIn('data "aws_secretsmanager_secret" "spacelift_api_key"', target)
        self.assertIn('actions   = ["ssm:GetParameter"]', iam)
        self.assertIn("resources = [local.spacelift_api_key_parameter_arn]", iam)
        self.assertIn("API_KEY_PARAMETER_NAME", function)
        self.assertIn("local.spacelift_api_key_parameter_name", function)
