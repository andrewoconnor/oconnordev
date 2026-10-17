"""Offline source contract: no shared Gateway payload delivery or replacement."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOOLS = ROOT / "infra/aws/tools"


def resource_types(text):
    """Match declarations, not resource names mentioned in explanatory comments."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"(?m)^\s*(?:#|//).*$", "", text)
    return re.findall(r'(?m)^\s*resource\s+"([^"]+)"\s+"[^"]+"\s*\{', text)


class GatewayLogPrivacyTests(unittest.TestCase):
    def test_no_application_log_delivery_or_payload_subscription_replacement(self):
        types = resource_types("\n".join(p.read_text() for p in TOOLS.glob("*.tf")))
        self.assertNotIn("aws_cloudwatch_log_delivery", types)
        self.assertNotIn("aws_cloudwatch_log_subscription_filter", types)
        self.assertNotIn("aws_cloudwatch_log_destination", types)

    def test_comments_are_not_active_resource_declarations(self):
        self.assertEqual(
            resource_types(
                '# resource "aws_cloudwatch_log_delivery" "old" {\n'
                '/* resource "aws_cloudwatch_log_delivery" "old" {} */\n'
                '// resource "aws_cloudwatch_log_delivery" "old" {\n'
            ),
            [],
        )

    def test_retention_metadata_and_native_alarm_remain(self):
        text = (TOOLS / "gateway-observability.tf").read_text()
        types = resource_types(text)
        for kind in (
            "aws_cloudwatch_log_group",
            "aws_cloudwatch_log_delivery_source",
            "aws_cloudwatch_log_delivery_destination",
            "aws_cloudwatch_metric_alarm",
        ):
            self.assertIn(kind, types)
        self.assertRegex(text, r"default\s*=\s*7\b")
        self.assertRegex(
            text, r"retention_in_days\s*=\s*var.hermes_gateway_log_retention_days"
        )
        self.assertRegex(text, r'namespace\s*=\s*"AWS/Bedrock-AgentCore"')
        self.assertRegex(text, r'metric_name\s*=\s*"UserErrors"')
        self.assertNotIn("aws_cloudwatch_log_metric_filter", types)
