"""Offline source contract for temporary Gateway delivery via the existing log group."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOOLS = ROOT / "infra/aws/tools"


def resource_types(text):
    """Match declarations, not resource names mentioned in explanatory comments."""
    text = re.sub(r"(?ms)^[ \t]*/\*.*?\*/", "", text)
    text = re.sub(r"(?m)^\s*(?:#|//).*$", "", text)
    return re.findall(r'(?m)^\s*resource\s+"([^"]+)"\s+"[^"]+"\s*\{', text)


class GatewayLogPrivacyTests(unittest.TestCase):
    def test_only_the_restored_delivery_exists_without_replacement_sinks(self):
        types = resource_types("\n".join(p.read_text() for p in TOOLS.glob("*.tf")))
        self.assertEqual(types.count("aws_cloudwatch_log_delivery"), 1)
        self.assertNotIn("aws_cloudwatch_log_subscription_filter", types)
        self.assertNotIn("aws_cloudwatch_log_destination", types)

    def test_delivery_uses_existing_source_and_destination(self):
        text = (TOOLS / "gateway-observability.tf").read_text()
        self.assertIn(
            "delivery_source_name     = "
            "aws_cloudwatch_log_delivery_source.gateway_application_logs.name",
            text,
        )
        self.assertIn(
            "delivery_destination_arn = "
            "aws_cloudwatch_log_delivery_destination.gateway_application_logs.arn",
            text,
        )

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
