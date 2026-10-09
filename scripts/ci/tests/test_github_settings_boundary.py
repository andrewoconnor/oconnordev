"""Evaluate the actual OpenTofu-rendered read permits with the Cedar engine.

No AWS provider, credentials, backend, or network authorization calls are used.
Rulesets also validate a reconstructed minimal schema with observed enum types.
This is not an exported live schema or proof of AgentCore live acceptance.
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
OBSERVED = json.loads(
    (Path(__file__).parent / "fixtures/github-ruleset-observed-schema.json").read_text()
)["deployment_input"]
GATEWAY = OBSERVED["gateway_arn"]
SCHEMA = """namespace AgentCore {
entity OAuthUser;
entity Gateway;
entity LEVEL enum ["repository", "organization", "enterprise"];
entity METHOD enum [
    "list", "get", "get_rules_for_branch", "list_rule_suites", "get_rule_suite"
];
action "github___repository_ruleset_read" appliesTo {
    principal: OAuthUser, resource: Gateway,
    context: {input: {
        owner?: String, repo?: String, level?: LEVEL, method?: METHOD,
        includes_parents?: Bool
    }}
};
}""".replace(
    "LEVEL", OBSERVED["level_entity_type"].removeprefix("AgentCore::")
).replace("METHOD", OBSERVED["method_entity_type"].removeprefix("AgentCore::"))


def enum_entity(field, value):
    return {"__entity": {"type": OBSERVED[f"{field}_entity_type"], "id": value}}


class GitHubSettingsBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = (ROOT / "infra/aws/tools/target-github.tf").read_text()
        policies = (ROOT / "infra/aws/tools/target-github-policies.tf").read_text()
        locals_block = re.search(r"^locals \{.*?^\}", source, re.M | re.S).group(0)
        schema_variable = re.search(
            r'^variable "github_ruleset_cedar_schema" \{.*?^\}', source, re.M | re.S
        ).group(0)
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
        precondition = (
            re.search(r"  lifecycle \{(.*?)\n  \}", read_resource, re.S)
            .group(1)
            .replace(
                "aws_bedrockagentcore_gateway.hermes.gateway_arn", "local.test_gateway"
            )
        )
        configuration = f"""
{schema_variable}
variable "hermes_github_allowed_repositories" {{
  type = set(string)
  default = ["oconnordev"]
}}
variable "hermes_github_default_branches" {{
  type = map(string)
  default = {{ oconnordev = "master" }}
}}
variable "fixture_gateway" {{ default = {json.dumps(GATEWAY)} }}
locals {{
  adapter_root = {json.dumps(str(ROOT / "agents/hermes/adapter"))}
  test_gateway = var.fixture_gateway
}}
{locals_block}
locals {{
  rendered = {{ for tool in local.github_read_tools : tool => <<-CEDAR
{template}
CEDAR
  }}
}}
resource "terraform_data" "read_binding" {{
  for_each = (
    length(var.hermes_github_allowed_repositories) == 0
    ? toset([]) : local.github_read_tools
  )
  lifecycle {{
{precondition}
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
        if tool == "repository_ruleset_read":
            return cedarpy.is_authorized(
                request, self.rendered[tool], [], schema=SCHEMA
            ).allowed
        return cedarpy.is_authorized(request, self.policies, []).allowed

    def arguments(self, tool):
        arguments = {"owner": "andrewoconnor", "repo": "oconnordev"}
        if tool == "repository_ruleset_read":
            arguments.update(
                level=enum_entity("level", "repository"),
                method=enum_entity("method", "list"),
                includes_parents=False,
            )
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
            arguments = self.arguments("repository_ruleset_read") | {
                "method": enum_entity("method", method)
            }
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
                    arguments[field] = (
                        enum_entity(field, value)
                        if field in ("level", "method")
                        else value
                    )
                with self.subTest(field=field, value=value):
                    self.assertFalse(
                        self.decision("repository_ruleset_read", arguments)
                    )

    def plan(self, schema=None, *, disabled=False, gateway=GATEWAY):
        variables_file = Path(self.fixture.name) / "schema-input.tfvars.json"
        variables = {"fixture_gateway": gateway}
        if schema is not None:
            variables["github_ruleset_cedar_schema"] = schema
        if disabled:
            variables.update(
                hermes_github_allowed_repositories=[], hermes_github_default_branches={}
            )
        variables_file.write_text(json.dumps(variables))
        command = [
            "tofu",
            "plan",
            "-input=false",
            "-no-color",
            "-lock=false",
            f"-var-file={variables_file}",
        ]
        return subprocess.run(
            command, cwd=self.fixture.name, capture_output=True, text=True
        )

    def test_schema_binding_default_accepts_observed_gateway_only(self):
        accepted = self.plan()
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        denied = self.plan(gateway=GATEWAY + "-other")
        self.assertNotEqual(denied.returncode, 0)
        self.assertIn("bound to a different gateway", denied.stderr)
        self.assertIn('each.key is "repository_ruleset_read"', denied.stderr)
        self.assertEqual(denied.stderr.count("Error: Resource precondition failed"), 1)
        disabled = self.plan(gateway=GATEWAY + "-other", disabled=True)
        self.assertEqual(disabled.returncode, 0, disabled.stderr)

    def test_schema_input_rejects_injection_invalid_identifier_and_suffix(self):
        for field in ("level", "method"):
            key = f"{field}_entity_type"
            for invalid in (
                'AgentCore::Bad::"injected"',
                f"AgentCore::Bad-Input_{field}",
                f"AgentCore::9Bad_Input_{field}",
                f"OtherNamespace::Bad_Input_{field}",
                f"AgentCore::Nested::Bad_Input_{field}",
                "AgentCore::Bad_Input_other",
                OBSERVED[key] + "\npermit(principal, action, resource);",
            ):
                with self.subTest(field=field, value=invalid):
                    result = self.plan(OBSERVED | {key: invalid})
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("Ruleset enum types must be", result.stderr)
        result = self.plan(OBSERVED | {"gateway_arn": 'bad"arn'})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Ruleset schema gateway_arn must be", result.stderr)

    def test_rendered_ruleset_validates_observed_minimal_schema(self):
        policy = self.rendered["repository_ruleset_read"]
        result = cedarpy.validate_policies(policy, SCHEMA)
        self.assertTrue(result.validation_passed, result.errors)
        for field, ids in {"level": ("repository",), "method": ("list", "get")}.items():
            for entity_id in ids:
                self.assertIn(
                    f'{OBSERVED[f"{field}_entity_type"]}::"{entity_id}"', policy
                )

    def test_prior_string_policy_reproduces_four_schema_errors(self):
        policy = self.rendered["repository_ruleset_read"]
        policy = policy.replace(
            f'{OBSERVED["level_entity_type"]}::"repository"', '"repository"'
        )
        for method in ("list", "get"):
            policy = policy.replace(
                f'{OBSERVED["method_entity_type"]}::"{method}"', f'"{method}"'
            )
        result = cedarpy.validate_policies(policy, SCHEMA)
        self.assertFalse(result.validation_passed)
        self.assertEqual(len(result.errors), 4, result.errors)

    def test_ruleset_wrong_type_and_malformed_inputs_deny(self):
        for field in ("level", "method"):
            value = "repository" if field == "level" else "list"
            for malformed in (
                value,
                False,
                0,
                [],
                {},
                {"__entity": {"type": "AgentCore::Gateway", "id": value}},
                enum_entity("method" if field == "level" else "level", value),
            ):
                with self.subTest(field=field, value=malformed):
                    arguments = self.arguments("repository_ruleset_read") | {
                        field: malformed
                    }
                    self.assertFalse(
                        self.decision("repository_ruleset_read", arguments)
                    )

    def test_existing_five_read_permits_remain_allowed(self):
        for tool in (
            "get_file_contents",
            "list_branches",
            "get_commit",
            "pull_request_read",
            "get_job_logs",
        ):
            with self.subTest(tool=tool):
                self.assertTrue(self.decision(tool, self.arguments(tool)))

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
