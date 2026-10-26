"""Render actual IAM data documents with the locked provider, offline only."""

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
        cls.fixture = tempfile.TemporaryDirectory(
            prefix="site-iam-", dir=os.environ.get("TMPDIR")
        )
        cls.addClassCleanup(cls.fixture.cleanup)
        cls.directory = Path(cls.fixture.name)
        accounts = json.loads((ROOT / "infra/aws/accounts.json").read_text())
        config = (
            """terraform {
 required_providers {
  aws = { source = "hashicorp/aws", version = "~> 6.70.0" }
 }
}
provider "aws" {
 region = "us-east-1"
 access_key = "test"
 secret_key = "test"
 skip_credentials_validation = true
 skip_requesting_account_id = true
 skip_metadata_api_check = true
}
"""
            + "locals { accounts = "
            + json.dumps(accounts)
            + " }\n"
        )
        broker = (ROOT / "infra/aws/tools/github-actions-broker.tf").read_text()
        config += re.search(r"^locals \{.*?^\}", broker, re.M | re.S).group(0)
        documents = []
        for prefix, source in [("broker", broker)] + [
            (
                site,
                (ROOT / "infra/modules/static-site/deploy.tf").read_text(),
            )
            for site, account in (
                ("oconnordev", "oconnordev"),
                ("drumrollworld", "drumrollworld"),
            )
        ]:
            if prefix != "broker":
                account = prefix
                locals_source = (ROOT / f"infra/aws/{account}/locals.tf").read_text()
                arn = re.search(
                    r"  tools_github_actions_broker_role_arn = (.*)", locals_source
                ).group(1)
                config += f"\nlocals {{ {prefix}_broker_arn = {arn} }}\n"
                site_source = (ROOT / f"infra/aws/{account}/site.tf").read_text()
                extra = re.search(
                    r"extra_deploy_statements\s*=\s*(\[.*?^  \}\])",
                    site_source,
                    re.M | re.S,
                )
                extra_value = extra.group(1) if extra else "[]"
                config += f"\nlocals {{ {prefix}_extra = {extra_value} }}\n"
            for match in re.finditer(
                r'^data "aws_iam_policy_document" "([^\"]+)" \{.*?^\}',
                source,
                re.M | re.S,
            ):
                name = prefix + "_" + match.group(1)
                body = match.group(0).replace(
                    '"' + match.group(1) + '"', '"' + name + '"', 1
                )
                body = body.replace(
                    "aws_iam_openid_connect_provider.github_actions.arn",
                    json.dumps(
                        "arn:aws:iam::"
                        + accounts["TOOLS"]
                        + ":oidc-provider/token.actions.githubusercontent.com"
                    ),
                )
                body = body.replace(
                    "var.broker_role_arn",
                    f"local.{prefix}_broker_arn",
                )
                body = body.replace(
                    "aws_s3_bucket.web.arn", json.dumps(f"arn:aws:s3:::{prefix}-web")
                )
                body = re.sub(
                    r"aws_cloudfront_distribution\.[a-z_]+\.arn",
                    json.dumps(
                        "arn:aws:cloudfront::"
                        + accounts["PRODUCTION"]
                        + ":distribution/TEST"
                    ),
                    body,
                )
                if prefix != "broker":
                    body = body.replace(
                        "var.extra_deploy_statements", f"local.{prefix}_extra"
                    )
                config += "\n" + body
                documents.append(name)
        config += (
            '\noutput "documents" { value = {'
            + ", ".join(
                f"{name} = data.aws_iam_policy_document.{name}.json"
                for name in documents
            )
            + "} }\n"
        )
        (cls.directory / "main.tf").write_text(config)
        shutil.copyfile(
            ROOT / "infra/aws/drumrollworld/.terraform.lock.hcl",
            cls.directory / ".terraform.lock.hcl",
        )
        for args in (
            ("init", "-backend=false", "-input=false", "-lockfile=readonly"),
            ("apply", "-auto-approve", "-input=false"),
        ):
            cls.run_tofu(*args)
        cls.policies = {
            name: json.loads(doc)
            for name, doc in json.loads(
                cls.run_tofu("output", "-json", "documents")
            ).items()
        }

    @classmethod
    def run_tofu(cls, *args):
        result = subprocess.run(
            ["tofu", *args],
            cwd=cls.directory,
            env=dict(os.environ, AWS_EC2_METADATA_DISABLED="true"),
            capture_output=True,
            text=True,
            timeout=180,
        )
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        return result.stdout

    def test_each_environment_can_chain_only_to_its_site(self):
        for site, trust_name, policy_name in (
            (
                "oconnordev",
                "github_actions_broker_trust",
                "github_actions_broker_assume_production",
            ),
            (
                "drumrollworld",
                "drumrollworld_broker_trust",
                "drumrollworld_broker_assume_production",
            ),
        ):
            trust_key = "broker_" + trust_name
            policy_key = "broker_" + policy_name
            self.assertIn(trust_key, self.policies)
            self.assertIn(policy_key, self.policies)
            (trust,) = self.policies[trust_key]["Statement"]
            conditions = trust["Condition"]["StringEquals"]
            self.assertEqual(
                conditions["token.actions.githubusercontent.com:sub"],
                f"repo:andrewoconnor/oconnordev:environment:{site}-production",
            )
            self.assertEqual(
                conditions["token.actions.githubusercontent.com:aud"],
                "sts.amazonaws.com",
            )
            self.assertEqual(trust["Action"], "sts:AssumeRoleWithWebIdentity")
            (permission,) = self.policies[policy_key]["Statement"]
            self.assertEqual(permission["Action"], "sts:AssumeRole")
            self.assertEqual(
                permission["Resource"],
                f"arn:aws:iam::767397796791:role/{site}-site-deploy",
            )
            (site_trust,) = self.policies[f"{site}_github_actions_site_deploy_trust"][
                "Statement"
            ]
            expected_broker = (
                "oconnordev-github-actions-broker"
                if site == "oconnordev"
                else "drumrollworld-github-actions-broker"
            )
            self.assertEqual(
                site_trust["Principal"]["AWS"],
                f"arn:aws:iam::421680664125:role/{expected_broker}",
            )
            # Exact equality denies branch subjects and the other site's environment.
            for denied in (
                "repo:andrewoconnor/oconnordev:ref:refs/heads/master",
                "repo:andrewoconnor/oconnordev:ref:refs/heads/feature",
                "repo:other/repo:environment:" + site + "-production",
                "repo:andrewoconnor/oconnordev:environment:"
                + ("drumrollworld" if site == "oconnordev" else "oconnordev")
                + "-production",
            ):
                self.assertNotEqual(
                    conditions["token.actions.githubusercontent.com:sub"], denied
                )

    def test_site_permissions_have_no_repair_reads_or_wildcard_actions(self):
        for site in ("oconnordev", "drumrollworld"):
            statements = self.policies[f"{site}_github_actions_site_deploy"][
                "Statement"
            ]
            by_sid = {statement["Sid"]: statement for statement in statements}
            expected_sids = {
                "ListSiteBucket",
                "SyncSiteObjects",
                "InvalidateSiteDistribution",
            }
            if site == "drumrollworld":
                expected_sids.add("PreserveExternalImages")
            self.assertEqual(set(by_sid), expected_sids)
            self.assertEqual(
                by_sid["ListSiteBucket"]["Resource"], f"arn:aws:s3:::{site}-web"
            )
            self.assertEqual(by_sid["ListSiteBucket"]["Action"], "s3:ListBucket")
            self.assertEqual(
                by_sid["SyncSiteObjects"]["Resource"], f"arn:aws:s3:::{site}-web/*"
            )
            self.assertEqual(
                set(by_sid["SyncSiteObjects"]["Action"]),
                {
                    "s3:PutObject",
                    "s3:DeleteObject",
                    "s3:AbortMultipartUpload",
                    "s3:ListMultipartUploadParts",
                },
            )
            self.assertEqual(
                by_sid["InvalidateSiteDistribution"]["Resource"],
                "arn:aws:cloudfront::767397796791:distribution/TEST",
            )
            self.assertEqual(
                by_sid["InvalidateSiteDistribution"]["Action"],
                "cloudfront:CreateInvalidation",
            )
            for statement in statements:
                actions = statement["Action"]
                if isinstance(actions, str):
                    actions = [actions]
                self.assertNotIn("s3:GetObject", actions)
                self.assertFalse(any("*" in action for action in actions))
            if site == "drumrollworld":
                deny = next(
                    s for s in statements if s["Sid"] == "PreserveExternalImages"
                )
                self.assertEqual(deny["Effect"], "Deny")
                self.assertEqual(
                    deny["Resource"], "arn:aws:s3:::drumrollworld-web/images/*"
                )
