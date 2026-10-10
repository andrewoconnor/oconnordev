"""Deployment boundaries for both static sites; no AWS calls or credentials."""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def block(source: str, kind: str, name: str) -> str:
    match = re.search(
        rf'(?:resource|data) "{kind}" "{name}" \{{(.*?)^\}}',
        source,
        re.MULTILINE | re.DOTALL,
    )
    if match is None:
        raise AssertionError(f"Missing {kind}.{name}")
    return match.group(1)


class StaticSiteDeploymentTests(unittest.TestCase):
    def test_drumroll_workflow_is_master_only_and_prs_have_no_oidc(self):
        workflow = read(".github/workflows/drumrollworld-site.yml")
        self.assertNotIn("pull_request_target:", workflow)
        self.assertIn("workflow_dispatch:", workflow)
        self.assertEqual(workflow.count('"apps/drumrollworld/**"'), 2)
        for path in (
            ".github/workflows/drumrollworld-site.yml",
            "biome.json",
            "mise.toml",
            "mise.lock",
        ):
            self.assertEqual(workflow.count(f'"{path}"'), 2)
        self.assertIn(
            "github.ref == 'refs/heads/master' && "
            "(github.event_name == 'push' || "
            "github.event_name == 'workflow_dispatch')",
            workflow,
        )
        before, deploy = workflow.split("  deploy:", 1)
        self.assertNotIn("id-token: write", before)
        self.assertIn("id-token: write", deploy)
        self.assertIn("needs: check", deploy)
        self.assertIn("concurrency:", workflow)
        self.assertIn("cancel-in-progress: false", workflow)
        self.assertIn("ref: master", deploy)
        self.assertIn("mise run fmt:site", deploy)
        self.assertIn("mise run lint:site", deploy)

    def test_drumroll_build_and_tests_precede_credentials_and_sync(self):
        workflow = read(".github/workflows/drumrollworld-site.yml")
        check, deploy = workflow.split("  deploy:", 1)
        for job in (check, deploy):
            self.assertIn("mise run build:drumrollworld", job)
            self.assertIn("mise run test:drumrollworld", job)
        build = deploy.index("mise run build:drumrollworld")
        tests = deploy.index("mise run test:drumrollworld")
        credentials = deploy.index("Assume TOOLS GitHub Actions broker")
        sync = deploy.index("aws s3 sync")
        self.assertLess(build, credentials)
        self.assertLess(tests, credentials)
        self.assertLess(credentials, sync)
        self.assertNotIn("aws s3 sync apps/drumrollworld/ s3:", deploy)
        assets = deploy.index(
            "aws s3 sync apps/drumrollworld/dist/assets/ s3://drumrollworld-web/assets/"
        )
        html = deploy.index(
            "aws s3 sync apps/drumrollworld/dist/ s3://drumrollworld-web/"
        )
        self.assertLess(assets, html)
        asset_command = deploy[assets:].splitlines()[0]
        self.assertNotIn("--delete", asset_command)
        tasks = read("mise.toml")
        self.assertIn("ci --ignore-scripts --no-audit --no-fund", tasks)
        self.assertIn("node =", tasks)

    def test_drumroll_sync_preserves_out_of_repo_images(self):
        workflow = read(".github/workflows/drumrollworld-site.yml")
        self.assertIn(
            "aws s3 sync apps/drumrollworld/dist/ s3://drumrollworld-web/ "
            '--delete --exclude "images/*" --exclude "assets/*"',
            workflow,
        )
        self.assertIn("vars.DRUMROLLWORLD_SITE_DEPLOY_ROLE_ARN", workflow)
        self.assertIn("vars.DRUMROLLWORLD_CLOUDFRONT_DISTRIBUTION_ID", workflow)
        self.assertIn("vars.OCONNORDEV_TOOLS_GITHUB_ACTIONS_BROKER_ROLE_ARN", workflow)
        self.assertIn('allowed-account-ids: "421680664125"', workflow)
        self.assertIn('allowed-account-ids: "767397796791"', workflow)
        self.assertIn("role-chaining: true", workflow)
        self.assertIn("role-skip-session-tagging: true", workflow)
        self.assertIn('test -n "$DEPLOY_ROLE_ARN"', workflow)
        self.assertIn('test -n "$DISTRIBUTION_ID"', workflow)
        self.assertIn('test -n "$BROKER_ROLE_ARN"', workflow)
        self.assertIn('--distribution-id "$DISTRIBUTION_ID" --paths "/*"', workflow)

    def test_oconnordev_serializes_and_checks_current_master_before_auth(self):
        workflow = read(".github/workflows/oconnordev-site.yml")
        header, jobs = workflow.split("jobs:", 1)
        self.assertIn(
            "concurrency:\n"
            "  group: oconnordev-production-${{ github.ref }}\n"
            "  cancel-in-progress: false\n",
            header,
        )
        self.assertNotIn("drumrollworld-production-", header)
        check, deploy = jobs.split("  deploy:", 1)
        self.assertNotIn("id-token: write", check)
        self.assertNotIn("ref: master", check)
        self.assertNotIn("pull_request_target:", workflow)
        self.assertIn(
            "github.ref == 'refs/heads/master' && "
            "(github.event_name == 'push' || "
            "github.event_name == 'workflow_dispatch')",
            deploy,
        )
        self.assertIn("needs: format", deploy)
        self.assertIn("id-token: write", deploy)
        self.assertRegex(
            deploy,
            r"uses: actions/checkout@[0-9a-f]{40}[^\n]*\n"
            r"        with:\n          ref: master\n",
        )
        checkout = deploy.index("ref: master")
        formatting = deploy.index("run: mise run fmt:site")
        lint = deploy.index("run: mise run lint:site")
        broker = deploy.index("name: Assume TOOLS GitHub Actions broker")
        production = deploy.index("name: Assume PRODUCTION site deploy role")
        self.assertIn(
            "aws s3 sync apps/oconnordev/dist/assets/css/ s3://oconnordev-web/assets/css/",
            deploy,
        )
        css = deploy.index(
            "aws s3 sync apps/oconnordev/dist/assets/css/ s3://oconnordev-web/assets/css/"
        )
        sync = deploy.index(
            "aws s3 sync apps/oconnordev/dist/ s3://oconnordev-web --delete "
            '--exclude "assets/css/*"'
        )
        self.assertNotIn("--delete", deploy[css:].splitlines()[0])
        self.assertLess(production, css)
        self.assertLess(css, sync)
        self.assertIn("vars.OCONNORDEV_TOOLS_GITHUB_ACTIONS_BROKER_ROLE_ARN", deploy)
        self.assertIn("vars.OCONNORDEV_SITE_DEPLOY_ROLE_ARN", deploy)
        self.assertIn('allowed-account-ids: "421680664125"', deploy)
        self.assertIn('allowed-account-ids: "767397796791"', deploy)
        self.assertIn("role-chaining: true", deploy)
        self.assertIn("role-skip-session-tagging: true", deploy)
        self.assertLess(checkout, formatting)
        self.assertLess(formatting, lint)
        self.assertLess(lint, broker)
        self.assertLess(broker, production)
        self.assertLess(production, sync)

    def test_oconnordev_release_is_built_and_verified_before_aws_auth(self):
        workflow = read(".github/workflows/oconnordev-site.yml")
        check, deploy = workflow.split("  deploy:", 1)
        for job in (check, deploy):
            self.assertIn("mise run build:oconnordev", job)
            self.assertIn("mise run test:oconnordev", job)
        credentials = deploy.index("Assume TOOLS GitHub Actions broker")
        self.assertLess(deploy.index("mise run build:oconnordev"), credentials)
        self.assertLess(deploy.index("mise run test:oconnordev"), credentials)
        self.assertNotIn("aws s3 sync apps/oconnordev/ s3:", deploy)
        self.assertEqual(
            workflow.count('"scripts/ci/tests/test_static_site_deployment.py"'), 2
        )
        tasks = read("mise.toml").split('[tasks."build:oconnordev"]', 1)[1]
        self.assertIn(
            "npm --prefix apps/oconnordev ci --ignore-scripts --no-audit --no-fund",
            tasks,
        )
        self.assertIn("playwright install --with-deps chromium", tasks)
        self.assertLess(
            tasks.index("ci --ignore-scripts"), tasks.index("playwright install")
        )
        self.assertLess(
            tasks.index("playwright install"),
            tasks.index("npm --prefix apps/oconnordev run build"),
        )
        ignore_rules = read(".gitignore").splitlines()
        for path in ("/apps/oconnordev/node_modules", "/apps/oconnordev/dist/"):
            self.assertEqual(ignore_rules.count(path), 1)
        self.assertNotIn("/apps/oconnordev/node_modules/", ignore_rules)

    def test_existing_site_uses_biome_and_config_changes_trigger_push(self):
        workflow = read(".github/workflows/oconnordev-site.yml")
        self.assertNotIn("deno", workflow.lower())
        self.assertIn("mise run fmt:site", workflow)
        self.assertIn("mise run lint:site", workflow)
        for path in ("biome.json", "mise.toml", "mise.lock"):
            self.assertEqual(workflow.count(f'"{path}"'), 2)
        self.assertIn("s3://oconnordev-web --delete", workflow)

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

    def test_broker_admits_only_two_specific_deploy_roles(self):
        source = read("infra/aws/tools/github-actions-broker.tf")
        policy = block(
            source, "aws_iam_policy_document", "github_actions_broker_assume_production"
        )
        self.assertIn("local.production_site_deploy_role_arn", policy)
        self.assertIn("local.drumrollworld_site_deploy_role_arn", policy)
        self.assertIn('role/drumrollworld-site-deploy"', source)
        self.assertNotIn('"*"', policy)
        self.assertIn(
            'values   = ["repo:andrewoconnor/oconnordev:ref:refs/heads/master"]', source
        )

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
            ["apps/**/*.html", "apps/**/*.css", "apps/**/*.js", "apps/**/*.mjs"],
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


if __name__ == "__main__":
    unittest.main()
