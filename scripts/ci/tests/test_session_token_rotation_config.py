"""Regression checks for Spacelift token-rotation Terraform settings."""

import re
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

    def test_rotation_poll_is_one_minute_until_expiry_behavior_is_observed(self):
        block = variable_block(
            self.config, "hermes_spacelift_rotation_interval_minutes"
        )
        default = re.search(r"(?m)^\\s*default\\s*=\\s*(\\d+)\\s*$", block)

        if default is None:
            self.fail("rotation interval default is missing")
        self.assertEqual(default.group(1), "1")
        self.assertIn(
            "condition     = var.hermes_spacelift_rotation_interval_minutes == 1",
            block,
        )

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
            r"(?m)^\\s*reserved_concurrent_executions\\s*=\\s*1\\s*$",
        )


if __name__ == "__main__":
    unittest.main()
