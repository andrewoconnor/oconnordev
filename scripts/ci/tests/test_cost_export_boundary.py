import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


class CostExportBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.general = (ROOT / "infra/aws/general/cost-export.tf").read_text()
        cls.security = (ROOT / "infra/aws/security/cost-analytics.tf").read_text()
        cls.queries = (ROOT / "infra/aws/security/cost-analytics-queries.tf").read_text()
        cls.iam = (ROOT / "infra/aws/security/cost-analytics-iam.tf").read_text()
        cls.schema = json.loads((ROOT / "infra/aws/cost-export-schema.json").read_text())
        cls.runbook = (ROOT / "docs/aws-cost-analytics.md").read_text()

    def test_general_export_configuration(self):
        for expected in (
            "aws_bcmdataexports_export",
            "COST_AND_USAGE_REPORT",
            "TIME_GRANULARITY",
            'INCLUDE_RESOURCES',
            'INCLUDE_SPLIT_COST_ALLOCATION_DATA',
            'frequency = "SYNCHRONOUS"',
            'output_type = "CUSTOM"',
            'overwrite   = "OVERWRITE_REPORT"',
            'export_bucket_name        = "oconnordev-org-cost-usage"',
            's3_prefix = "billing"',
            "force_destroy = false",
            "prevent_destroy = true",
        ):
            self.assertIn(expected, self.general)
        self.assertIn('local.accounts["GENERAL"]', self.general)
        self.assertIn('local.accounts["SECURITY"]', self.general)

    def test_glue_reads_the_export_delivery_path(self):
        self.assertIn('s3_prefix = "billing"', self.general)
        self.assertIn('export_name               = "oconnordev-org-cost-usage"', self.general)
        self.assertIn('s3://${local.export_bucket_name}/billing/${local.export_name}/data/', self.general)
        self.assertIn('location      = local.cost_export_data_root', self.security)
        self.assertIn('cost_export_data_root    = var.cost_export_data_location', self.security)
        self.assertIn('BILLING_PERIOD=$${billing_period}', self.security)
        self.assertIn('The Glue table root is the exact Data Exports data location above', self.runbook)

    def test_security_resources_and_queries(self):
        for expected in (
            'analytics_results_name   = "oconnordev-security-athena"',
            "hermes-analytics",
            "org_billing",
            "cost_usage",
            "aws_athena_workgroup",
            "aws_glue_catalog_database",
            "aws_glue_catalog_table",
            '"projection.billing_period.type"',
        ):
            self.assertIn(expected, self.security)
        self.assertEqual(self.queries.count('resource "aws_athena_named_query"'), 3)

    def test_access_boundaries_and_preserved_denies(self):
        self.assertIn('s3:GetObject', self.iam)
        self.assertIn('billing/${local.cost_export_name}/data/*', self.iam)
        self.assertIn('${local.analytics_results_prefix}*', self.iam)
        self.assertNotIn('s3:*', self.iam)
        self.assertNotIn('athena:*', self.iam)
        self.assertIn('local.security_gateway_role_arn', self.general)
        self.assertNotIn('s3:PutObject', self.iam.split('ReadCurExportObjects')[1].split('ListCurExportPrefix')[0])
        gateway = (ROOT / "infra/aws/security/gateway.tf").read_text()
        for expected in ('kms:Decrypt', 'sts:AssumeRole', 'iam:GetCredentialReport', 'iam:GetLoginProfile'):
            self.assertIn(expected, gateway)
        for forbidden in ('oconnordev-cloudtrail', 'oconnordev-config'):
            self.assertNotIn(forbidden, self.iam)

    def test_shared_schema_and_runbook(self):
        self.assertEqual(len(self.schema["columns"]), 17)
        self.assertIn("cur_schema", self.general)
        self.assertIn("cur_columns", self.general)
        self.assertIn("cost_export_columns", self.security)
        self.assertNotIn("SELECT *", self.general)
        self.assertIn("physical types", self.runbook)

    def test_dependency_is_one_way(self):
        dependencies = (ROOT / "infra/spacelift/dependencies.tf").read_text()
        self.assertIn("security_general", dependencies)
        self.assertIn("cost_export_bucket_name", dependencies)
        self.assertIn("cost_export_data_location", dependencies)


if __name__ == "__main__":
    unittest.main()
