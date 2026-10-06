import json
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
class CostExportBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.general = (ROOT/'infra/aws/general/cost-export.tf').read_text()
        cls.security = (ROOT/'infra/aws/security/cost-analytics.tf').read_text()
        cls.queries = (ROOT/'infra/aws/security/cost-analytics-queries.tf').read_text()
        cls.iam = (ROOT/'infra/aws/security/cost-analytics-iam.tf').read_text()
        cls.schema = json.loads((ROOT/'infra/aws/cost-export-schema.json').read_text())
        cls.runbook = (ROOT/'docs/aws-cost-analytics.md').read_text()
    def test_general_export_configuration(self):
        for s in ('aws_bcmdataexports_export','COST_AND_USAGE_REPORT','TIME_GRANULARITY = "DAILY"','INCLUDE_RESOURCES = "TRUE"','INCLUDE_SPLIT_COST_ALLOCATION_DATA = "FALSE"','SYNCHRONOUS','OVERWRITE_REPORT','force_destroy = false','prevent_destroy = true'):
            self.assertIn(s,self.general)
        self.assertIn('local.accounts["GENERAL"]',self.general)
        self.assertIn('local.accounts["SECURITY"]',self.general)
    def test_security_resources_and_queries(self):
        for s in ('hermes-analytics','org_billing','cost_usage','aws_athena_workgroup','aws_glue_catalog_database','aws_glue_catalog_table','projection.billing_period.type','BILLING_PERIOD=$${billing_period}'):
            self.assertIn(s,self.security)
        self.assertEqual(self.queries.count('resource "aws_athena_named_query"'),3)
    def test_access_boundaries_and_denies(self):
        self.assertIn('s3:GetObject',self.iam)
        self.assertIn('billing/${local.cost_export_name}/data/*',self.iam)
        self.assertIn('${local.analytics_results_prefix}*',self.iam)
        self.assertNotIn('s3:*',self.iam)
        self.assertNotIn('athena:*',self.iam)
        self.assertIn('local.security_gateway_role_arn',self.general)
        self.assertNotIn('s3:PutObject',self.iam.split('ReadCurExportObjects')[1].split('ListCurExportPrefix')[0])
        gw=(ROOT/'infra/aws/security/gateway.tf').read_text()
        for s in ('kms:Decrypt','sts:AssumeRole','iam:GetRoleCredentials'): self.assertIn(s,gw)
        for s in ('oconnordev-cloudtrail','oconnordev-config'): self.assertNotIn(s,self.iam)
    def test_shared_schema_projection_and_docs(self):
        self.assertEqual(len(self.schema['columns']),17)
        self.assertIn('cost_export_schema',self.general)
        self.assertIn('cost_export_columns',self.security)
        self.assertNotIn('SELECT *',self.general)
        self.assertIn('physical Parquet',self.runbook)
    def test_dependency_is_one_way(self):
        deps=(ROOT/'infra/spacelift/dependencies.tf').read_text()
        self.assertIn('security_general',deps)
        self.assertIn('cost_export_bucket_name',deps)
        self.assertIn('cost_export_data_location',deps)
if __name__=='__main__': unittest.main()
