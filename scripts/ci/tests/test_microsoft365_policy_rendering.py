"""Render real IAM expressions with locked AWS 6.66.0, no AWS calls/apply."""

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FUNCTION = "arn:aws:lambda:us-east-1:421680664125:function:hermes-microsoft365-mcp"
SECRET = (
    "arn:aws:secretsmanager:us-east-1:421680664125:secret:"
    "/hermes/microsoft365/msal-cache-test12"
)
REPO = "arn:aws:ecr:us-east-1:421680664125:repository/oconnordev-tools"


class Microsoft365PolicyRenderingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture = tempfile.TemporaryDirectory(
            prefix="m365-iam-", dir=os.environ.get("TMPDIR")
        )
        cls.addClassCleanup(fixture.cleanup)
        directory = Path(fixture.name)
        config = """terraform {
 required_providers {
  aws = { source = "hashicorp/aws", version = "~> 6.66.0" }
  archive = { source = "hashicorp/archive", version = "~> 2.8.0" }
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
        source = (ROOT / "infra/aws/tools/microsoft365-runtime.tf").read_text()
        names = []
        for match in re.finditer(
            r'^data "aws_iam_policy_document" "([^"]+)" \{.*?^\}', source, re.M | re.S
        ):
            body = match.group(0)
            for ref, value in {
                "aws_lambda_function.microsoft365.arn": FUNCTION,
                "aws_secretsmanager_secret.microsoft365_cache.arn": SECRET,
                "${aws_cloudwatch_log_group.microsoft365.arn}": (
                    "arn:aws:logs:us-east-1:421680664125:log-group:"
                    "/aws/lambda/hermes-microsoft365-mcp"
                ),
            }.items():
                body = body.replace(
                    ref, value if ref.startswith("${") else json.dumps(value)
                )
            config += body + "\n"
            names.append(match.group(1))
        ecr = (ROOT / "infra/aws/tools/ecr.tf").read_text()
        publisher = ecr[ecr.index('resource "aws_iam_role" "tools_image_publisher"') :]
        for output_name, field in [
            ("publisher", "policy"),
            ("publisher_trust", "assume_role_policy"),
        ]:
            expr = re.search(
                r"\b" + field + r"\s*=\s*(jsonencode\(\{.*?^  \}\))",
                publisher,
                re.M | re.S,
            ).group(1)
            expr = expr.replace(
                "aws_ecr_repository.tools_images.arn", json.dumps(REPO)
            ).replace(
                "aws_iam_openid_connect_provider.github_actions.arn",
                json.dumps(
                    "arn:aws:iam::421680664125:oidc-provider/token.actions.githubusercontent.com"
                ),
            )
            config += f'output "{output_name}" {{ value = {expr} }}\n'
        config += (
            '\noutput "documents" { value = {'
            + ", ".join(
                f"{name} = data.aws_iam_policy_document.{name}.json" for name in names
            )
            + "} }\n"
        )
        (directory / "main.tf").write_text(config)
        shutil.copyfile(
            ROOT / "infra/aws/tools/.terraform.lock.hcl",
            directory / ".terraform.lock.hcl",
        )

        def run(*args):
            result = subprocess.run(
                ["tofu", *args],
                cwd=directory,
                env=dict(os.environ, AWS_EC2_METADATA_DISABLED="true"),
                capture_output=True,
                text=True,
                timeout=180,
            )
            if result.returncode:
                raise AssertionError(result.stdout + result.stderr)
            return result.stdout

        run("init", "-backend=false", "-input=false", "-lockfile=readonly")
        run("plan", "-input=false", "-out=fixture.plan")
        outputs = json.loads(run("show", "-json", "fixture.plan"))["planned_values"][
            "outputs"
        ]
        cls.documents = {
            name: json.loads(doc) for name, doc in outputs["documents"]["value"].items()
        }
        cls.publisher = json.loads(outputs["publisher"]["value"])
        cls.trust = json.loads(outputs["publisher_trust"]["value"])

    def test_gateway_only_url_and_secret_is_runtime_only(self):
        statements = self.documents["microsoft365_gateway_invoke"]["Statement"]
        self.assertEqual(len(statements), 2)
        expected = {
            "lambda:InvokeFunctionUrl": {
                "StringEquals": {"lambda:FunctionUrlAuthType": "AWS_IAM"}
            },
            "lambda:InvokeFunction": {"Bool": {"lambda:InvokedViaFunctionUrl": "true"}},
        }
        for statement in statements:
            self.assertEqual(statement["Resource"], FUNCTION)
            self.assertEqual(statement["Condition"], expected[statement["Action"]])
        runtime = self.documents["microsoft365_runtime"]["Statement"]
        cache = next(s for s in runtime if s["Sid"] == "OnlyTheConsumerCache")
        self.assertEqual(
            set(cache["Action"]),
            {"secretsmanager:GetSecretValue", "secretsmanager:PutSecretValue"},
        )
        self.assertEqual(cache["Resource"], SECRET)
        self.assertNotIn("Principal", cache)

    def test_publisher_cannot_read_cache_deploy_or_apply(self):
        (trust,) = self.trust["Statement"]
        self.assertEqual(
            trust["Condition"]["StringEquals"],
            {
                "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
                "token.actions.githubusercontent.com:sub": (
                    "repo:andrewoconnor/oconnordev:ref:refs/heads/master"
                ),
            },
        )
        for statement in self.publisher["Statement"]:
            self.assertTrue(all(a.startswith("ecr:") for a in statement["Action"]))
            self.assertEqual(
                statement["Resource"],
                "*" if statement["Action"] == ["ecr:GetAuthorizationToken"] else REPO,
            )
