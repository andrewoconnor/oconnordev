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
        cls.schema = (ROOT / "infra/aws/cost-export-schema.json").read_text()
        cls.runbook = (ROOT / "docs/aws-cost-analytics.md").read_text()
        cls.general_json = json.loads(cls.general[cls.general.index('query_statement'):cls.general.index('table_configurations')]) if False else json.loads((ROOT / 'infra/aws/cost-export-schema.json').read_text())

    def test_general_owns_org_cur_export_and_prefix(self):
        for value in ('aws_bcmdataexports_export', 'COST_AND_USAGE_REPORT', 'TIME_GRANULARITY = "DAILY"', 'INCLUDE_RESOURCES = "TRUE"', 'INCLUDE_SPLIT_COST_ALLOCATION_DATA = "FALSE"', 'SYNCHRONOUS', 'OVERWRITE_REPORT', 'force_destroy = false', 'prevent_destroy = true'):
            self.assertIn(value, self.general)
        self.assertIn('"SECURITY"', self.general)
        self.assertIn('"GENERAL"', self.general)

    def test_security_workgroup_glue_saved_queries_and_projected_partition(self):
        for value in ('hermes-analytics', 'org_billing', 'cost_usage', 'aws_athena_workgroup', 'aws_glue_catalog_database', 'aws_glue_catalog_table', 'projection.billing_period.type', 'BILLING_PERIOD=$${billing_period}'):
            self.assertIn(value, self.security)
        self.assertIn('aws_athena_named_query', self.queries)
        self.assertEqual(self.queries.count('resource "aws_athena_named_query"'), 3)

    def test_cross_account_source_and_results_are_prefix_scoped(self):
        self.assertIn('s3:GetObject', self.security)
        self.assertIn('billing/${local.cost_export_name}/data/*', self.security)
        self.assertIn('${local.analytics_results_prefix}*', self.security)
        self.assertNotIn('s3:*', self.security)
        self.assertNotIn('athena:*', self.security)
        self.assertIn('role/oconnordev-security-gateway', self.general)
        self.assertIn('local.security_gateway_role_arn', self.general)
        self.assertNotIn('s3:PutObject', self.general)
        self.assertNotIn('s3:DeleteObject', self.general)

    def test_existing_denies_remain_and_no_security_source_extensions(self):
        gateway = (ROOT / 'infra/aws/security/gateway.tf').read_text()
        for value in ('kms:Decrypt', 'sts:AssumeRole', 'iam:GetRoleCredentials'):
            self.assertIn(value, gateway)
        self.assertNotIn('oconnordev-cloudtrail', self.security)
        self.assertNotIn('oconnordev-config', self.security)

    def test_selected_column_schema_is_shared(self):
        schema = json.loads(self.schema)
        self.assertEqual(len(schema['columns']), 17)
        for col in schema['columns']:
            self.assertIn('name', col)
            self.assertIn('type', col)
        self.assertIn('cost_export_schema', self.general)
        self.assertIn('cost_export_columns', self.security)
        self.assertNotIn('SELECT *', self.general)
        self.assertIn('cost_usage', self.runbook)

    def test_spacelift_dependency_is_general_to_security(self):
        deps = (ROOT / 'infra/spacelift/dependencies.tf').read_text()
        self.assertIn('security_general', deps)
        self.assertIn('cost_export_bucket_name', deps)
        self.assertIn('cost_export_data_location', deps)

if __name__ == '__main__':
    unittest.main()
