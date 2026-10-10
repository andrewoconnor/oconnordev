"""Render deployment IAM using the locked provider without contacting AWS."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


class StaticSitePolicyRenderingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = tempfile.TemporaryDirectory(prefix="static-site-policy-")
        cls.addClassCleanup(cls.fixture.cleanup)
        cls.directory = Path(cls.fixture.name)
        cls.environment = dict(os.environ, AWS_EC2_METADATA_DISABLED="true")
        # These placeholders are never sent to AWS: provider credential/account
        # discovery is disabled and only local IAM policy documents are evaluated.
        configuration = """
terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 6.66.0" }
  }
}
provider "aws" {
  region                      = "us-east-1"
  access_key                  = "test"
  secret_key                  = "test"
  skip_credentials_validation = true
  skip_requesting_account_id  = true
  skip_metadata_api_check     = true
}
locals {
  accounts = { TOOLS = "421680664125", PRODUCTION = "767397796791" }
  tools_github_actions_broker_role_arn = join("", [
    "arn:aws:iam::421680664125:role/", "oconnordev-github-actions-broker"
  ])
  bucket_arn = "arn:aws:s3:::drumrollworld-web"
  distribution_arn = "arn:aws:cloudfront::767397796791:distribution/TESTDISTRIBUTION"
}
"""
        broker = (ROOT / "infra/aws/tools/github-actions-broker.tf").read_text()
        # Import the actual checked-in locals, not a duplicate permission list.
        locals_match = re.search(r"^locals \{.*?^\}", broker, re.M | re.S)
        if locals_match is None:
            raise AssertionError("Missing TOOLS broker locals")
        configuration += locals_match.group(0)
        site = (
            ROOT / "infra/aws/drumrollworld/github-actions-site-deploy.tf"
        ).read_text()
        for source in (site, broker):
            for match in re.finditer(
                r'^data "aws_iam_policy_document" "[^"]+" \{.*?^\}',
                source,
                re.M | re.S,
            ):
                body = match.group(0)
                if '"github_actions_broker_trust"' in body:
                    continue  # OIDC provider is owned by the unchanged TOOLS root.
                configuration += "\n" + body.replace(
                    "aws_s3_bucket.web.arn", "local.bucket_arn"
                ).replace(
                    "aws_cloudfront_distribution.drumrollworld.arn",
                    "local.distribution_arn",
                )
        (cls.directory / "main.tf").write_text(configuration)
        shutil.copyfile(
            ROOT / "infra/aws/drumrollworld/.terraform.lock.hcl",
            cls.directory / ".terraform.lock.hcl",
        )
        cls.run_tofu(
            "init", "-backend=false", "-input=false", "-lockfile=readonly", "-no-color"
        )
        # Only IAM policy-document data sources exist in this fixture. Applying
        # evaluates their JSON locally; there are no managed resources or AWS APIs.
        cls.run_tofu("apply", "-auto-approve", "-input=false", "-no-color")
        expression = (
            "jsonencode({trust = "
            "data.aws_iam_policy_document.github_actions_site_deploy_trust.json, "
            "site = data.aws_iam_policy_document.github_actions_site_deploy.json, "
            "broker = "
            "data.aws_iam_policy_document.github_actions_broker_assume_production.json})"
        )
        cls.policies = {
            name: json.loads(document)
            for name, document in json.loads(
                json.loads(cls.run_tofu("console", "-no-color", expression=expression))
            ).items()
        }

    @classmethod
    def run_tofu(cls, *args: str, expression: str | None = None) -> str:
        process = subprocess.run(
            ["tofu", *args],
            cwd=cls.directory,
            env=cls.environment,
            input=None if expression is None else expression + "\n",
            text=True,
            capture_output=True,
            timeout=180,
            check=True,
        )
        return process.stdout.strip()

    def test_trust_is_only_the_existing_tools_broker(self):
        self.assertEqual(
            self.policies["trust"]["Statement"],
            [
                {
                    "Sid": "ToolsBrokerOnly",
                    "Effect": "Allow",
                    "Action": "sts:AssumeRole",
                    "Principal": {
                        "AWS": (
                            "arn:aws:iam::421680664125:role/"
                            "oconnordev-github-actions-broker"
                        )
                    },
                }
            ],
        )

    def test_only_the_site_bucket_and_distribution_are_mutable(self):
        statements = {s["Sid"]: s for s in self.policies["site"]["Statement"]}
        self.assertEqual(
            set(statements),
            {
                "ListSiteBucket",
                "SyncSiteObjects",
                "InvalidateSiteDistribution",
                "PreserveExternalImages",
                "ReadGlobeKtxForMetadataRepair",
            },
        )
        self.assertEqual(
            statements["ReadGlobeKtxForMetadataRepair"],
            {
                "Sid": "ReadGlobeKtxForMetadataRepair",
                "Effect": "Allow",
                "Action": "s3:GetObject",
                "Resource": "arn:aws:s3:::drumrollworld-web/images/globe/*.ktx2",
            },
        )
        self.assertEqual(
            statements["ListSiteBucket"]["Resource"], "arn:aws:s3:::drumrollworld-web"
        )
        self.assertEqual(statements["ListSiteBucket"]["Action"], "s3:ListBucket")
        self.assertEqual(
            statements["SyncSiteObjects"]["Resource"],
            "arn:aws:s3:::drumrollworld-web/*",
        )
        self.assertEqual(
            set(statements["SyncSiteObjects"]["Action"]),
            {
                "s3:AbortMultipartUpload",
                "s3:DeleteObject",
                "s3:ListMultipartUploadParts",
                "s3:PutObject",
            },
        )
        self.assertEqual(
            statements["InvalidateSiteDistribution"]["Resource"],
            "arn:aws:cloudfront::767397796791:distribution/TESTDISTRIBUTION",
        )
        self.assertEqual(
            statements["InvalidateSiteDistribution"]["Action"],
            "cloudfront:CreateInvalidation",
        )
        self.assertEqual(statements["PreserveExternalImages"]["Effect"], "Deny")
        self.assertEqual(
            statements["PreserveExternalImages"]["Action"], "s3:DeleteObject"
        )
        self.assertEqual(
            statements["PreserveExternalImages"]["Resource"],
            "arn:aws:s3:::drumrollworld-web/images/*",
        )

    def test_broker_cannot_assume_arbitrary_roles(self):
        (statement,) = self.policies["broker"]["Statement"]
        self.assertEqual(statement["Action"], "sts:AssumeRole")
        self.assertEqual(
            set(statement["Resource"]),
            {
                "arn:aws:iam::767397796791:role/oconnordev-site-deploy",
                "arn:aws:iam::767397796791:role/drumrollworld-site-deploy",
            },
        )


if __name__ == "__main__":
    unittest.main()
