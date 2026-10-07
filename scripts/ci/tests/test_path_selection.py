import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CI_DIR = REPO_ROOT / "scripts" / "ci"
sys.path.insert(0, str(CI_DIR))

from path_selection import (  # noqa: E402
    ACCOUNT_MAP_CONSUMERS,
    ALL_ROOTS,
    roots_for_paths,
)


class OpenTofuRootSelectionTests(unittest.TestCase):
    def test_cost_export_schema_change_selects_general_and_security(self):
        self.assertEqual(
            roots_for_paths(["infra/aws/cost-export-schema.json"]),
            ("infra/aws/general", "infra/aws/security"),
        )

    def test_session_token_lambda_and_test_changes_select_only_tools(self):
        for path in (
            "infra/aws/tools/lambdas/spacelift_session_token/spacelift_session_token.py",
            "infra/aws/tools/lambdas/spacelift_session_token/test_spacelift_session_token.py",
        ):
            with self.subTest(path=path):
                self.assertEqual(roots_for_paths([path]), ("infra/aws/tools",))

    def test_legacy_rotation_source_path_no_longer_selects_tools(self):
        self.assertEqual(
            roots_for_paths(["agents/hermes/rotation/spacelift_session_token.py"]),
            (),
        )

    def test_adapter_manifest_change_selects_only_tools(self):
        self.assertEqual(
            roots_for_paths(["agents/hermes/adapter/aws-mcp-tools.json"]),
            ("infra/aws/tools",),
        )

    def test_account_map_change_selects_every_direct_consumer(self):
        self.assertEqual(
            roots_for_paths(["infra/aws/accounts.json"]),
            ACCOUNT_MAP_CONSUMERS,
        )
        self.assertEqual(len(ACCOUNT_MAP_CONSUMERS), 6)

    def test_workflow_only_change_selects_no_opentofu_root(self):
        self.assertEqual(
            roots_for_paths([".github/workflows/opentofu-validate.yml"]),
            (),
        )

    def test_mise_config_change_selects_every_root(self):
        self.assertEqual(roots_for_paths(["mise.toml"]), ALL_ROOTS)

    def test_spacelift_globs_cover_each_external_input_consumer(self):
        main_tf = (REPO_ROOT / "infra/spacelift/main.tf").read_text(encoding="utf-8")
        stacks_tf = (REPO_ROOT / "infra/spacelift/stacks.tf").read_text(
            encoding="utf-8"
        )
        tools_entry = main_tf.split("    tools = {", 1)[1].split("    security = {", 1)[
            0
        ]

        self.assertEqual(
            main_tf.count('"infra/aws/accounts.json"'),
            len(ACCOUNT_MAP_CONSUMERS),
        )
        self.assertIn('project_root = "infra/aws/tools"', tools_entry)
        self.assertEqual(main_tf.count('"agents/hermes/rotation/*.py"'), 0)
        self.assertEqual(main_tf.count('"agents/hermes/adapter/*-mcp-tools.json"'), 1)
        self.assertIn('"agents/hermes/adapter/*-mcp-tools.json"', tools_entry)
        self.assertIn(
            "additional_project_globs = each.value.additional_project_globs",
            stacks_tf,
        )

    def test_lambda_archive_uses_package_and_excludes_tests(self):
        config = (
            REPO_ROOT / "infra/aws/tools/spacelift-token-rotation-config.tf"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "spacelift_rotation_source_dir       = "
            '"${local.repo_root}/infra/aws/tools/lambdas/'
            'spacelift_session_token"',
            config,
        )
        self.assertIn(
            'excludes    = ["test_*.py", "test/**", "**/__pycache__/**", "**/*.pyc"]',
            config,
        )

    def test_mise_rotation_test_task_uses_new_package_directory(self):
        mise = (REPO_ROOT / "mise.toml").read_text(encoding="utf-8")
        self.assertIn(
            "python3 -m unittest discover -s "
            "infra/aws/tools/lambdas/spacelift_session_token "
            "-p 'test_*.py' -v",
            mise,
        )


class RequiredWorkflowTriggerTests(unittest.TestCase):
    def test_required_workflows_run_for_workflow_only_pull_requests(self):
        workflows = (
            ".github/workflows/opentofu-validate.yml",
            ".github/workflows/adapter-tests.yml",
            ".github/workflows/tflint.yml",
            ".github/workflows/checkov.yml",
        )
        for relative_path in workflows:
            with self.subTest(workflow=relative_path):
                content = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
                trigger_header = content.split("\npermissions:", 1)[0]
                self.assertIn("pull_request:", trigger_header)
                self.assertNotIn("paths:", trigger_header)


if __name__ == "__main__":
    unittest.main()
