import re
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
        self.assertEqual(len(ACCOUNT_MAP_CONSUMERS), 7)

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
            '"$CI_PYTHON" -m unittest discover -s '
            "infra/aws/tools/lambdas/spacelift_session_token "
            "-p 'test_*.py' -v",
            mise,
        )


def workflow_check_names(workflow):
    names = []
    jobs = workflow.split("\njobs:\n", 1)[1]
    for job_id, body in re.findall(r"^  ([\w-]+):\n((?:(?:    .*)?\n)*)", jobs, re.M):
        name = re.search(r"^    name: (.+)$", body, re.M)
        label = name.group(1).strip().strip("'\"") if name else job_id
        uses = re.search(r"^    uses: \./(\S+)$", body, re.M)
        if uses:
            called = (REPO_ROOT / uses.group(1)).read_text(encoding="utf-8")
            names += [f"{label} / {inner}" for inner in workflow_check_names(called)]
        else:
            names.append(label)
    return names


class RequiredWorkflowTriggerTests(unittest.TestCase):
    def test_every_required_check_runs_on_every_pull_request(self):
        settings = REPO_ROOT / "infra/github/oconnordev/settings-adoption.tf"
        listed = re.search(
            r"required_status_checks = \[(.*?)\]",
            settings.read_text(encoding="utf-8"),
            re.S,
        )
        required = re.findall(r'"([^"]+)"', listed.group(1))
        self.assertTrue(required)
        producers = {}
        for path in sorted((REPO_ROOT / ".github/workflows").glob("*.yml")):
            content = path.read_text(encoding="utf-8")
            trigger = re.search(r"^  pull_request:\n((?:    .*\n)*)", content, re.M)
            if trigger:
                for context in workflow_check_names(content):
                    producer = (path.name, trigger.group(1))
                    producers.setdefault(context, []).append(producer)
        for context in required:
            with self.subTest(check=context):
                self.assertEqual(len(producers.get(context, [])), 1, context)
                name, trigger = producers[context][0]
                self.assertNotIn("paths", trigger, f"{name} must run on every PR")


if __name__ == "__main__":
    unittest.main()
