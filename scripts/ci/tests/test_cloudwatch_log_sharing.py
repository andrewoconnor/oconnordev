from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SINK = "arn:aws:oam:us-east-1:482921124454:sink/12345678-1234-1234-1234-123456789012"


class CloudWatchLogSharingTests(unittest.TestCase):
    def test_athena_resource_is_moved_without_configuration_changes(self):
        generic = (ROOT / "infra/aws/security/athena.tf").read_text()
        billing = (ROOT / "infra/aws/security/cost-analytics.tf").read_text()
        self.assertNotIn('resource "aws_athena_workgroup"', billing)
        self.assertEqual(generic.count('resource "aws_athena_workgroup"'), 1)
        for expected in (
            'resource "aws_athena_workgroup" "hermes_analytics"',
            'name          = "hermes-analytics"',
            "enforce_workgroup_configuration    = true",
            "bytes_scanned_cutoff_per_query     = "
            "var.athena_bytes_scanned_cutoff_per_query",
            'encryption_option = "SSE_S3"',
        ):
            self.assertIn(expected, generic)

    def test_dependency_wiring_and_existing_read_boundary(self):
        dependencies = (ROOT / "infra/spacelift/dependencies.tf").read_text()
        for name in ("tools_security_logs_sink", "production_security_logs_sink"):
            self.assertIn(
                f'resource "spacelift_stack_dependency_reference" "{name}"',
                dependencies,
            )
        self.assertEqual(
            dependencies.count('output_name         = "cloudwatch_logs_sink_arn"'), 2
        )
        self.assertEqual(
            dependencies.count('input_name          = "TF_VAR_security_logs_sink_arn"'),
            2,
        )
        gateway = (ROOT / "infra/aws/security/gateway.tf").read_text()
        for deny in ("sts:AssumeRole", "kms:Decrypt", "secretsmanager:GetSecretValue"):
            self.assertIn(deny, gateway)
        for account in ("tools", "production"):
            source = (
                ROOT / f"infra/aws/{account}/cloudwatch-log-sharing.tf"
            ).read_text()
            self.assertNotIn("link_configuration", source)
            self.assertNotIn("AWS::CloudWatch::Metric", source)

    def _mock_test(self, account: str, tests: str):
        # Copy only the real log-sharing resources into an isolated module.
        # The AWS provider is mocked: even command=apply makes no AWS calls.
        with tempfile.TemporaryDirectory(prefix="log-sharing-") as temporary:
            folder = Path(temporary)
            shutil.copyfile(
                ROOT / f"infra/aws/{account}/cloudwatch-log-sharing.tf",
                folder / "sharing.tf",
            )
            shutil.copyfile(ROOT / "infra/aws/accounts.json", folder / "accounts.json")
            shutil.copyfile(
                ROOT / "infra/aws/security/.terraform.lock.hcl",
                folder / ".terraform.lock.hcl",
            )
            (folder / "main.tf").write_text(
                """terraform {
  required_providers {
    aws = {
      source = "hashicorp/aws"
      version = "6.66.0"
    }
  }
}
locals { accounts = jsondecode(file("${path.module}/accounts.json")) }
"""
            )
            (folder / "sharing.tftest.hcl").write_text(tests)
            env = os.environ.copy()
            env.setdefault(
                "TF_PLUGIN_CACHE_DIR", str(Path.home() / ".opentofu.d/plugin-cache")
            )
            for arguments in (
                [
                    "init",
                    "-backend=false",
                    "-input=false",
                    "-lockfile=readonly",
                    "-no-color",
                ],
                ["test", "-no-color"],
            ):
                result = subprocess.run(
                    ["tofu", f"-chdir={folder}", *arguments],
                    env=env,
                    text=True,
                    capture_output=True,
                    timeout=120,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_sink_policy_is_logs_only_and_names_exactly_two_accounts(self):
        self._mock_test(
            "security",
            f'''
mock_provider "aws" {{
  mock_resource "aws_oam_sink" {{
    defaults = {{ arn = "{SINK}" }}
  }}
}}
run "sink_policy" {{
  command = apply
  assert {{
    condition = (
      toset(jsondecode(aws_oam_sink_policy.cloudwatch_logs.policy)
        .Statement[0].Principal.AWS) == toset([
      "arn:aws:iam::421680664125:root", "arn:aws:iam::767397796791:root"
    ]))
    error_message = "Only TOOLS and PRODUCTION may link to the sink."
  }}
  assert {{
    condition = (jsondecode(aws_oam_sink_policy.cloudwatch_logs.policy)
      .Statement[0].Condition["ForAllValues:StringEquals"]
      ["oam:ResourceTypes"] == ["AWS::Logs::LogGroup"])
    error_message = "Only CloudWatch logs may be shared."
  }}
  assert {{
    condition = (jsondecode(aws_oam_sink_policy.cloudwatch_logs.policy)
      .Statement[0].Condition.Null["oam:ResourceTypes"] == "false")
    error_message = "An absent resource-types context must not pass the policy."
  }}
  assert {{
    condition = (toset(jsondecode(aws_oam_sink_policy.cloudwatch_logs.policy)
      .Statement[0].Action) == toset(["oam:CreateLink", "oam:UpdateLink"]))
    error_message = "Link management must not grant wildcard OAM permissions."
  }}
}}
''',
        )

    def _source_test(self, account: str):
        self._mock_test(
            account,
            f'''
mock_provider "aws" {{}}
run "unresolved" {{
  command = plan
  assert {{
    condition = length(aws_oam_link.security_logs) == 0
    error_message = "No link may exist before the sink dependency resolves."
  }}
}}
run "resolved" {{
  command = plan
  variables {{ security_logs_sink_arn = "{SINK}" }}
  assert {{
    condition = (length(aws_oam_link.security_logs) == 1 &&
      aws_oam_link.security_logs[0].resource_types ==
      toset(["AWS::Logs::LogGroup"]))
    error_message = "The resolved link must share only logs."
  }}
  assert {{
    condition = (aws_oam_link.security_logs[0].sink_identifier == "{SINK}" &&
      aws_oam_link.security_logs[0].label_template == "oconnordev-{account}")
    error_message = "The source must target the SECURITY sink with its own label."
  }}
}}
run "reject_wrong_account" {{
  command = plan
  variables {{
    security_logs_sink_arn = "{SINK.replace("482921124454", "905418422177")}"
  }}
  expect_failures = [var.security_logs_sink_arn]
}}
run "reject_wrong_region" {{
  command = plan
  variables {{ security_logs_sink_arn = "{SINK.replace("us-east-1", "us-west-2")}" }}
  expect_failures = [var.security_logs_sink_arn]
}}
''',
        )

    def test_tools_link(self):
        self._source_test("tools")

    def test_production_link(self):
        self._source_test("production")


if __name__ == "__main__":
    unittest.main()
