"""Regression checks for Spacelift token-rotation Terraform settings."""

import re
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = REPO_ROOT / "infra/aws/tools/spacelift-token-rotation-config.tf"
LAMBDA_PATH = REPO_ROOT / "infra/aws/tools/spacelift-token-rotation.tf"


def variable_block(source: str, name: str) -> str:
    start = source.index(f'variable "{name}"')
    end = source.index("\n}\n", start) + 3
    return source[start:end]


class RotationConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = CONFIG_PATH.read_text()
        cls.lambda_config = LAMBDA_PATH.read_text()

    def test_rotation_poll_defaults_to_sixty_minutes_with_bounded_overrides(self):
        block = variable_block(
            self.config, "hermes_spacelift_rotation_interval_minutes"
        )
        default = re.search(r"(?m)^\s*default\s*=\s*(\d+)\s*$", block)

        if default is None:
            self.fail("rotation interval default is missing")
        self.assertEqual(default.group(1), "60")
        self.assertIn("var.hermes_spacelift_rotation_interval_minutes >= 1", block)
        self.assertIn("var.hermes_spacelift_rotation_interval_minutes <= 60", block)
        self.assertIn(
            "floor(var.hermes_spacelift_rotation_interval_minutes) "
            "== var.hermes_spacelift_rotation_interval_minutes",
            block,
        )

    def test_opentofu_evaluates_cadence_defaults_overrides_and_rejections(self):
        interval = "hermes_spacelift_rotation_interval_minutes"
        assignments = []
        for name in ("spacelift_rotation_schedule", "spacelift_rotation_alarm_period"):
            match = re.search(rf"(?m)^\s*{name}\s*=.*$", self.config)
            if match is None:
                self.fail(f"missing local {name}")
            assignments.append(match.group(0))
        source = variable_block(self.config, interval)
        source += "\nlocals {\n" + "\n".join(assignments) + "\n}\n"
        tests = []
        for minutes in (None, 1, 15, 60):
            value = 60 if minutes is None else minutes
            schedule = f"rate({value} {'minute' if value == 1 else 'minutes'})"
            variables = (
                "" if minutes is None else f"variables {{ {interval} = {value} }}"
            )
            tests.append(f'''
run "accept_{"default" if minutes is None else minutes}" {{
  command = plan
  {variables}
  assert {{
    condition = local.spacelift_rotation_schedule == "{schedule}"
    error_message = "Unexpected EventBridge cadence."
  }}
  assert {{
    condition = local.spacelift_rotation_alarm_period == {value * 60}
    error_message = "Alarm period must follow the polling interval."
  }}
}}
''')
        for index, value in enumerate((-1, 0, 1.5, 60.5, 61)):
            tests.append(f"""
run "reject_{index}" {{
  command = plan
  variables {{ {interval} = {value} }}
  expect_failures = [var.{interval}]
}}
""")
        with tempfile.TemporaryDirectory(prefix="rotation-cadence-") as directory:
            root = Path(directory)
            (root / "main.tf").write_text(source)
            (root / "cadence.tftest.hcl").write_text("".join(tests))
            for arguments in (
                ["init", "-backend=false", "-input=false", "-no-color"],
                ["test", "-no-color"],
            ):
                result = subprocess.run(
                    ["tofu", f"-chdir={root}", *arguments],
                    text=True,
                    capture_output=True,
                    timeout=60,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_alarms_keep_the_lifetime_floor_and_missing_data_safeguard(self):
        block = variable_block(
            self.config, "hermes_spacelift_token_remaining_floor_seconds"
        )
        self.assertRegex(block, r"(?m)^\s*default\s*=\s*7200\s*$")
        stale = self.lambda_config.split(
            'resource "aws_cloudwatch_metric_alarm" "spacelift_session_token_stale"', 1
        )[1].split('resource "aws_cloudwatch_metric_alarm"', 1)[0]
        self.assertRegex(stale, r"evaluation_periods\s*=\s*2")
        self.assertRegex(stale, r'treat_missing_data\s*=\s*"breaching"')
        self.assertIn("var.hermes_spacelift_token_remaining_floor_seconds", stale)
        self.assertIn("local.spacelift_rotation_alarm_period", stale)
        errors = self.lambda_config.split(
            'resource "aws_cloudwatch_metric_alarm" "spacelift_rotation_errors"', 1
        )[1]
        self.assertRegex(errors, r"evaluation_periods\s*=\s*1")
        self.assertRegex(errors, r'treat_missing_data\s*=\s*"notBreaching"')
        self.assertIn("local.spacelift_rotation_alarm_period", errors)
        # Preserve the current notification boundary: neither alarm has actions.
        self.assertNotRegex(
            stale + errors, r"\b(?:alarm|ok|insufficient_data)_actions\b"
        )

    def test_gateway_m2m_access_token_lasts_one_hour_in_explicit_minutes(self):
        gateway = (CONFIG_PATH.parent / "gateway-auth.tf").read_text()
        client = gateway.split('resource "aws_cognito_user_pool_client" "hermes"', 1)[1]
        self.assertRegex(client, r"access_token_validity\s*=\s*60\b")
        self.assertRegex(
            client, r'token_validity_units\s*\{\s*access_token\s*=\s*"minutes"\s*\}'
        )
        self.assertIn('["client_credentials"]', client)
        self.assertNotRegex(client, r"\b(?:id|refresh)_token_validity\b")

    def test_http_timeout_validation_rejects_fractional_seconds(self):
        block = variable_block(
            self.config, "hermes_spacelift_rotation_http_timeout_seconds"
        )

        self.assertIn(
            "floor(var.hermes_spacelift_rotation_http_timeout_seconds) "
            "== var.hermes_spacelift_rotation_http_timeout_seconds",
            block,
        )

    def test_rotation_lambda_serializes_invocations(self):
        self.assertRegex(
            self.lambda_config,
            r"(?m)^\s*reserved_concurrent_executions\s*=\s*1\s*$",
        )


if __name__ == "__main__":
    unittest.main()
