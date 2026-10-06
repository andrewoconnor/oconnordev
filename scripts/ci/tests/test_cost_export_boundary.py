from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[3]


class CostExportBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.general = (ROOT / "infra/aws/general/cost-export.tf").read_text()
        cls.security = (ROOT / "infra/aws/security/cost-analytics.tf").read_text()
        cls.schema = (ROOT / "infra/aws/cost-export-schema.json").read_text()
        cls.spacelift = (ROOT / "infra/spacelift/dependencies.tf").read_text()
        cls.runbook = (ROOT / "docs/aws-cost-analytics.md").read_text()

    def test_general_owns_org_cur_export_and_prefix(self):
        for expected in ("aws_bcmdataexports_export", "COST_AND_USAGE_REPORT", "DAILY", "PARQUET", "billing/", "local.accounts[\"GENERAL\"]"):
            self.assertIn(expected, self.general)
        self.assertIn("INCLUDE_RESOURCES", self.general)
        self.assertIn("INCLUDE_SPLIT_COST_ALLOCATION_DATA", self.general)
        self.assertNotIn("INCLUDE_MANUAL_DISCOUNT_COMPATIBILITY", self.general)
        self.assertIn("force_destroy = false", self.general)

    def test_security_workgroup_glue_saved_queries_and_projected_partition(self):
        for expected in ("hermes-analytics", "org_billing", "cost_usage", "aws_athena_workgroup", "aws_glue_catalog_database", "aws_glue_catalog_table", "aws_athena_named_query", "projection.billing_period.type", "BILLING_PERIOD=$${billing_period}"):
            self.assertIn(expected, self.security)
        self.assertIn('local.accounts["SECURITY"]', self.security)

    def test_cross_account_source_and_results_are_prefix_scoped(self):
        self.assertIn('"arn:aws:iam::${local.accounts["SECURITY"]}:role/oconnordev-security-gateway"', self.general)
        self.assertIn('billing/${local.cost_export_name}/data/*', self.general)
        self.assertIn('"${aws_s3_bucket.athena_results.arn}/${local.analytics_results_prefix}*"', self.security)
        self.assertNotIn("oconnordev-cloudtrail", self.security)
        self.assertNotIn("oconnordev-config", self.security)

    def test_selected_column_schema_is_shared(self):
        for field in ("bill_payer_account_id", "line_item_usage_account_id", "line_item_usage_start_date", "product_region_code", "line_item_unblended_cost"):
            self.assertIn(field, self.schema)
        self.assertIn("cost_usage", self.runbook)

    def test_spacelift_dependency_is_general_to_security(self):
        self.assertIn('stack_dependency.security_general', self.spacelift)
        self.assertIn('output_name         = "cost_export_bucket_name"', self.spacelift)
        self.assertNotIn('stack_id            = spacelift_stack.accounts["general"].id\n  depends_on_stack_id = spacelift_stack.accounts["security"].id', self.spacelift)

    def test_existing_denies_remain_and_no_security_source_extensions(self):
        gateway = (ROOT / "infra/aws/security/gateway.tf").read_text()
        for deny in ("kms:Decrypt", "sts:AssumeRole", "DenySecretAndCredentialReturningApis"):
            self.assertIn(deny, gateway)
        for forbidden in ("oconnordev-cloudtrail", "oconnordev-config", "cloudtrail.amazonaws.com", "config.amazonaws.com"):
            self.assertNotIn(forbidden, self.security)


if __name__ == "__main__":
    unittest.main()
