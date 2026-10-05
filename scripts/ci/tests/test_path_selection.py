from pathlib import Path
import sys
import unittest

REPO_ROOT = Path(__file__).resolve().parents[3]
CI_DIR = REPO_ROOT / "scripts" / "ci"
sys.path.insert(0, str(CI_DIR))

from path_selection import ALL_ROOTS, ACCOUNT_MAP_CONSUMERS, roots_for_paths  # noqa: E402


class TerraformRootSelectionTests(unittest.TestCase):
    def test_rotation_source_change_selects_only_tools(self):
        self.assertEqual(
            roots_for_paths(["agents/hermes/rotation/spacelift_session_token.py"]),
            ("infra/aws/tools",),
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

    def test_workflow_only_change_selects_no_terraform_root(self):
        self.assertEqual(
            roots_for_paths([".github/workflows/terraform-validate.yml"]),
            (),
        )

    def test_mise_config_change_selects_every_root(self):
        self.assertEqual(roots_for_paths(["mise.toml"]), ALL_ROOTS)

    def test_spacelift_globs_cover_each_external_input_consumer(self):
        main_tf = (REPO_ROOT / "infra/spacelift/main.tf").read_text(encoding="utf-8")
        stacks_tf = (REPO_ROOT / "infra/spacelift/stacks.tf").read_text(encoding="utf-8")
        tools_entry = main_tf.split("    tools = {", 1)[1].split("    security = {", 1)[0]

        self.assertEqual(
            main_tf.count('"infra/aws/accounts.json"'),
            len(ACCOUNT_MAP_CONSUMERS),
        )
        self.assertEqual(main_tf.count('"agents/hermes/rotation/*.py"'), 1)
        self.assertEqual(main_tf.count('"agents/hermes/adapter/*-mcp-tools.json"'), 1)
        self.assertIn('"agents/hermes/rotation/*.py"', tools_entry)
        self.assertIn('"agents/hermes/adapter/*-mcp-tools.json"', tools_entry)
        self.assertIn(
            "additional_project_globs = each.value.additional_project_globs",
            stacks_tf,
        )


class RequiredWorkflowTriggerTests(unittest.TestCase):
    def test_required_workflows_run_for_workflow_only_pull_requests(self):
        workflows = (
            ".github/workflows/terraform-validate.yml",
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
