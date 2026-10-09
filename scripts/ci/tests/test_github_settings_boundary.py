"""Evaluate the actual OpenTofu-rendered read permits with the Cedar engine.

No AWS provider, credentials, backend, or network authorization calls are used.
This checks standard Cedar decisions, not AgentCore catalog/schema acceptance.
"""

import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

import cedarpy

ROOT = Path(__file__).resolve().parents[3]
TOOLS = {
    "repository_ruleset_read",
    "list_repository_collaborators",
    "list_label",
    "get_label",
}
GATEWAY = "arn:aws:bedrock-agentcore:us-east-1:000000000000:gateway/offline"


class GitHubSettingsBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = (ROOT / "infra/aws/tools/target-github.tf").read_text()
        policies = (ROOT / "infra/aws/tools/target-github-policies.tf").read_text()
        locals_block = re.search(r"^locals \{.*?^\}", source, re.M | re.S).group(0)
        read_resource = policies.split(
            'resource "aws_bedrockagentcore_policy" "github_branch_write"'
        )[0]
        template = re.search(
            r"statement = <<-CEDAR\n(.*?)\n\s*CEDAR", read_resource, re.S
        ).group(1)
        template = template.replace("each.key", "tool").replace(
            "aws_bedrockagentcore_gateway.hermes.gateway_arn", "local.test_gateway"
        )
        cls.fixture = tempfile.TemporaryDirectory(
            prefix="github-cedar-", dir=os.environ.get("TMPDIR")
        )
        cls.addClassCleanup(cls.fixture.cleanup)
        directory = Path(cls.fixture.name)
        configuration = f"""
variable "hermes_github_allowed_repositories" {{ default = ["oconnordev"] }}
variable "hermes_github_default_branches" {{ default = {{ oconnordev = "master" }} }}
locals {{
  adapter_root = {json.dumps(str(ROOT / "agents/hermes/adapter"))}
  test_gateway = {json.dumps(GATEWAY)}
}}
{locals_block}
locals {{
  rendered = {{ for tool in local.github_read_tools : tool => <<-CEDAR
{template}
CEDAR
  }}
}}
"""
        (directory / "main.tf").write_text(configuration)
        subprocess.run(
            ["tofu", "init", "-backend=false", "-input=false", "-no-color"],
            cwd=directory,
            capture_output=True,
            check=True,
        )
        result = subprocess.run(
            ["tofu", "console", "-no-color"],
            cwd=directory,
            input="jsonencode(local.rendered)\n",
            text=True,
            capture_output=True,
            check=True,
        )
        cls.rendered = json.loads(json.loads(result.stdout))
        cls.policies = "\n".join(cls.rendered.values())
        cls.source = source

    def decision(self, tool, arguments, *, gateway=GATEWAY, wire=True):
        request = {
            "principal": 'AgentCore::OAuthUser::"offline"',
            "action": f'AgentCore::Action::"{("github___" if wire else "") + tool}"',
            "resource": f'AgentCore::Gateway::"{gateway}"',
            "context": {"input": arguments},
        }
        return cedarpy.is_authorized(request, self.policies, []).allowed

    def arguments(self, tool):
        arguments = {"owner": "andrewoconnor", "repo": "oconnordev"}
        if tool == "repository_ruleset_read":
            arguments.update(level="repository", method="list", includes_parents=False)
        return arguments

    def test_four_native_read_actions_are_allowed(self):
        self.assertTrue(self.rendered.keys() >= TOOLS)
        for tool in TOOLS:
            with self.subTest(tool=tool):
                self.assertTrue(self.decision(tool, self.arguments(tool)))
                self.assertFalse(self.decision(tool, self.arguments(tool), wire=False))
                self.assertFalse(
                    self.decision(tool, self.arguments(tool), gateway="other")
                )

    def test_owner_and_repository_are_required_and_isolated(self):
        for tool in TOOLS:
            for field in ("owner", "repo"):
                for replacement in (None, "outside", "", ["oconnordev"]):
                    arguments = self.arguments(tool)
                    if replacement is None:
                        del arguments[field]
                    else:
                        arguments[field] = replacement
                    with self.subTest(tool=tool, field=field, value=replacement):
                        self.assertFalse(self.decision(tool, arguments))

    def test_rulesets_only_list_get_repository_without_parents(self):
        for method in ("list", "get"):
            arguments = self.arguments("repository_ruleset_read") | {"method": method}
            self.assertTrue(self.decision("repository_ruleset_read", arguments))
        for field, replacements in {
            "method": (
                None,
                "get_rules_for_branch",
                "list_rule_suites",
                "get_rule_suite",
                "create",
                "delete",
                "LIST",
            ),
            "level": (None, "organization", "enterprise", "Repository"),
            "includes_parents": (None, True, "false", 0),
        }.items():
            for value in replacements:
                arguments = self.arguments("repository_ruleset_read")
                if value is None:
                    del arguments[field]
                else:
                    arguments[field] = value
                with self.subTest(field=field, value=value):
                    self.assertFalse(
                        self.decision("repository_ruleset_read", arguments)
                    )

    def test_read_permits_do_not_allow_write_or_secret_actions(self):
        for action in (
            "create_branch",
            "push_files",
            "delete_file",
            "create_pull_request",
            "repository_ruleset_write",
            "update_repository",
            "get_secret_value",
            "lambda_invoke",
        ):
            self.assertFalse(
                self.decision(action, self.arguments("repository_ruleset_read"))
            )
        self.assertEqual(
            re.findall(r'^resource "([^"]+)" "([^"]+)"', self.source, re.M),
            [
                ("aws_secretsmanager_secret", "github_machine_user_pat"),
                ("aws_bedrockagentcore_api_key_credential_provider", "github"),
                ("aws_iam_role_policy", "github_target_credentials"),
                ("terraform_data", "github_target_catalog_rebuild"),
                ("aws_bedrockagentcore_gateway_target", "github"),
            ],
        )
        self.assertEqual(
            re.findall(r'^data "([^"]+)" "([^"]+)"', self.source, re.M),
            [
                ("aws_secretsmanager_secret", "github_machine_user_pat_existing"),
                ("aws_iam_policy_document", "github_target_credentials"),
            ],
        )
        self.assertEqual(
            re.findall(r"actions\s*=\s*\[([^\]]+)\]", self.source),
            [
                '"bedrock-agentcore:GetResourceApiKey"',
                '"secretsmanager:GetSecretValue"',
            ],
        )
        self.assertIn('api_key_secret_source = "EXTERNAL"', self.source)
        self.assertNotIn("aws_secretsmanager_secret_version", self.source)
        self.assertNotIn("aws_lambda_function", self.source)
        self.assertIn('actions   = ["secretsmanager:GetSecretValue"]', self.source)
        self.assertIn(
            "resources = [aws_secretsmanager_secret.github_machine_user_pat.arn]",
            self.source,
        )


if __name__ == "__main__":
    unittest.main()
