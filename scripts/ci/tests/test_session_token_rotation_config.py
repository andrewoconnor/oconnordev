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

    def test_rotation_poll_defaults_to_fifteen_minutes_with_bounded_overrides(self):
        block = variable_block(
            self.config, "hermes_spacelift_rotation_interval_minutes"
        )
        default = re.search(r"(?m)^\s*default\s*=\s*(\d+)\s*$", block)

        if default is None:
            self.fail("rotation interval default is missing")
        self.assertEqual(default.group(1), "15")
        self.assertIn("var.hermes_spacelift_rotation_interval_minutes >= 1", block)
        self.assertIn("var.hermes_spacelift_rotation_interval_minutes <= 15", block)
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
        for minutes in (None, 1, 5, 15):
            value = 15 if minutes is None else minutes
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
        for index, value in enumerate((-1, 0, 1.5, 15.5, 16)):
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
