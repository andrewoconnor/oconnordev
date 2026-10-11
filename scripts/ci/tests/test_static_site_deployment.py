"""Tested same-run artifacts and credential/deployment boundaries."""

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def read(path):
    return (ROOT / path).read_text()


def block(source, kind, name):
    match = re.search(
        rf'(?:resource|data) "{kind}" "{name}" \{{(.*?)^\}}',
        source,
        re.MULTILINE | re.DOTALL,
    )
    if match is None:
        raise AssertionError(f"Missing {kind}.{name}")
    return match.group(1)


class StaticSiteDeploymentTests(unittest.TestCase):
    def test_checks_once_and_deploys_exact_same_run_before_credentials(self):
        for site in ("oconnordev", "drumrollworld"):
            workflow = (ROOT / f".github/workflows/{site}-site.yml").read_text()
            check, deploy = workflow.split("  deploy:", 1)
            self.assertIn("  check:", check)
            self.assertEqual(workflow.count(f"mise run build:{site}"), 1)
            self.assertEqual(workflow.count(f"mise run test:{site}"), 1)
            self.assertNotIn("id-token: write", check)
            self.assertIn("needs: check", deploy)
            self.assertEqual(workflow.count("timeout-minutes:"), 2)
            self.assertIn(f"environment: {site}-production", deploy)
            self.assertNotIn("ref: master", workflow)
            self.assertEqual(workflow.count("ref: ${{ github.sha }}"), 2)
            self.assertRegex(check, r"actions/upload-artifact@[a-f0-9]{40}")
            self.assertRegex(deploy, r"actions/download-artifact@[a-f0-9]{40}")
            self.assertEqual(workflow.count(f"name: {site}-${{{{ github.sha }}}}"), 2)
            self.assertNotIn("run-id:", deploy)
            self.assertNotIn("github-token:", deploy)
            self.assertIn("needs.check.outputs.sha256", deploy)
            self.assertLess(
                deploy.index("site_artifact.py verify"),
                deploy.index("configure-aws-credentials@"),
            )
            self.assertLess(
                deploy.index('test "$MASTER_SHA" = "$EXPECTED_SHA"'),
                deploy.index("configure-aws-credentials@"),
            )
            self.assertIn("git ls-remote origin refs/heads/master", deploy)
            self.assertIn("cancel-in-progress: false", workflow)
            self.assertIn("github.ref == 'refs/heads/master'", deploy)
            self.assertNotIn("pull_request_target:", workflow)
            self.assertNotIn("mise run build:", deploy)
            self.assertNotIn("mise run lint:", deploy)
            self.assertNotIn("mise run fmt:", deploy)
            for action in re.findall(r"uses:\s+(\S+)", workflow):
                self.assertRegex(action, r"^[^@]+@[0-9a-f]{40}$")

    def test_account_guards_match_authoritative_accounts(self):
        accounts = json.loads((ROOT / "infra/aws/accounts.json").read_text())
        for site in ("oconnordev", "drumrollworld"):
            workflow = (ROOT / f".github/workflows/{site}-site.yml").read_text()
            self.assertEqual(
                re.findall(r'allowed-account-ids: "([0-9]+)"', workflow),
                [accounts["TOOLS"], accounts["PRODUCTION"]],
            )
            self.assertIn(
                f"vars.{site.upper()}_TOOLS_GITHUB_ACTIONS_BROKER_ROLE_ARN", workflow
            )

    def test_publication_has_no_duplicate_sync_uploads(self):
        source = (ROOT / "scripts/ci/publish_site.sh").read_text()
        self.assertIn("--delete --size-only", source)
        self.assertIn('--exclude "assets/*" --exclude "images/*"', source)
        self.assertIn("public,max-age=31536000,immutable", source)
        self.assertIn("public,max-age=0,must-revalidate", source)
        self.assertIn("[A-Z0-9]{8}", source)
        self.assertNotIn("build-meta.json", source)

    def test_every_action_is_pinned(self):
        for name in ("oconnordev", "drumrollworld"):
            actions = re.findall(
                r"uses:\s+(\S+)", read(f".github/workflows/{name}-site.yml")
            )
            self.assertTrue(actions)
            for action in actions:
                self.assertRegex(action, r"^[^@]+@[0-9a-f]{40}$")

    def test_drumroll_role_trust_and_policy_are_site_scoped(self):
        source = read("infra/aws/drumrollworld/github-actions-site-deploy.tf")
        trust = block(
            source, "aws_iam_policy_document", "github_actions_site_deploy_trust"
        )
        self.assertIn("local.tools_github_actions_broker_role_arn", trust)
        self.assertIn('actions = ["sts:AssumeRole"]', trust)
        self.assertNotIn("Federated", trust)
        role = block(source, "aws_iam_role", "github_actions_site_deploy")
        self.assertIn('"drumrollworld-site-deploy"', role)
        policy = block(source, "aws_iam_policy_document", "github_actions_site_deploy")
        self.assertIn("aws_s3_bucket.web.arn", policy)
        self.assertIn("aws_cloudfront_distribution.drumrollworld.arn", policy)
        self.assertIn('"cloudfront:CreateInvalidation"', policy)
        self.assertNotIn('"s3:*"', policy)
        self.assertNotIn('"cloudfront:*"', policy)
        self.assertIn('sid       = "PreserveExternalImages"', policy)
        self.assertIn('effect    = "Deny"', policy)
        self.assertIn('resources = ["${aws_s3_bucket.web.arn}/images/*"]', policy)

    def test_outputs_flow_from_workload_stack_to_repository_variables(self):
        outputs = read("infra/aws/drumrollworld/outputs.tf")
        dependencies = read("infra/spacelift/dependencies.tf")
        variables = read("infra/github/oconnordev/drumrollworld.tf")
        edge = block(
            dependencies,
            "spacelift_stack_dependency",
            "github_repository_config_drumrollworld",
        )
        self.assertIn('spacelift_stack.accounts["drumrollworld"].id', edge)
        self.assertIn("count = var.enable_github_repository_config ? 1 : 0", edge)
        for suffix in ("site_deploy_role_arn", "cloudfront_distribution_id"):
            name = f"drumrollworld_{suffix}"
            self.assertIn(f'output "{name}"', outputs)
            self.assertIn(f'output_name         = "{name}"', dependencies)
            self.assertIn(f'input_name          = "TF_VAR_{name}"', dependencies)
            self.assertIn(f'variable_name = "{name.upper()}"', variables)
        self.assertEqual(
            variables.count(
                "count = local.drumrollworld_deployment_configured ? 1 : 0"
            ),
            2,
        )
        self.assertIn("drumrollworld_site_deploy_role_arn", variables)
        self.assertIn("drumrollworld_cloudfront_distribution_id", variables)

    def test_biome_covers_html_css_and_javascript(self):
        config = json.loads(read("biome.json"))
        for language in ("html", "css", "javascript"):
            self.assertNotEqual(
                config.get(language, {}).get("formatter", {}).get("enabled"), False
            )
        self.assertTrue(config["linter"]["enabled"])
        self.assertTrue(config["html"]["experimentalFullSupportEnabled"])
        self.assertTrue(config["html"]["formatter"]["enabled"])
        self.assertEqual(config["html"]["formatter"]["whitespaceSensitivity"], "strict")
        self.assertTrue(config["html"]["linter"]["enabled"])
        self.assertTrue(config["css"]["formatter"]["enabled"])
        self.assertTrue(config["css"]["linter"]["enabled"])
        self.assertEqual(
            config["files"]["includes"],
            [
                "apps/**/*.html",
                "apps/**/*.css",
                "apps/**/*.js",
                "apps/**/*.mjs",
                "!apps/drumrollworld/third-party/basis-1.50.0-no-eval/basis_transcoder.js",
            ],
        )
        self.assertTrue(config["vcs"]["enabled"])
        self.assertTrue(config["vcs"]["useIgnoreFile"])
        for path in (
            "/apps/drumrollworld/node_modules/",
            "/apps/drumrollworld/dist/",
        ):
            self.assertIn(path, read(".gitignore"))
        self.assertFalse(config["assist"]["enabled"])
        self.assertNotIn("deno =", read("mise.toml"))
        self.assertIn('[tasks."lint:site"]', read("mise.toml"))
