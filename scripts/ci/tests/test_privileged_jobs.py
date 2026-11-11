"""Jobs holding OIDC or App credentials run no dependency-managed code."""

import ast
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = ROOT / ".github/workflows"
DEPENDENCY_TOOLS = re.compile(r"\b(mise|npm|npx|node|pip|pip3|cargo|uv|poetry)\b")


def jobs(path):
    section = path.read_text(encoding="utf-8").split("\njobs:\n", 1)[1]
    return re.findall(r"^  ([\w-]+):\n((?:(?:    .*)?\n)*)", section, re.M)


def privileged_jobs():
    found = {}
    for path in sorted(WORKFLOWS.glob("*.yml")):
        for name, body in jobs(path):
            calls_workflow = re.search(r"^    uses: \./\.github/workflows/", body, re.M)
            if not calls_workflow and ("id-token: write" in body or "secrets." in body):
                found[f"{path.name}:{name}"] = body
    return found


def repository_scripts(body):
    return re.findall(r"\b(?:python3|bash|source) (scripts/\S+)", body)


class PrivilegedJobTests(unittest.TestCase):
    def test_privileged_jobs_are_the_known_set(self):
        self.assertEqual(
            set(privileged_jobs()),
            {
                "site.yml:deploy",
                "tool-image.yml:publish",
                "dependabot-auto-merge.yml:enable",
            },
        )

    def test_privileged_jobs_run_no_actions_checkout_or_package_tools(self):
        for job, body in privileged_jobs().items():
            with self.subTest(job=job):
                self.assertNotRegex(body, r"\buses:")
                self.assertNotIn("actions/checkout", body)
                self.assertNotRegex(body, DEPENDENCY_TOOLS)
                self.assertRegex(body, re.compile(r"^    permissions:\n", re.M))
                self.assertNotIn("write-all", body)

    def test_repository_scripts_in_privileged_jobs_use_no_dependencies(self):
        stdlib = set(sys.stdlib_module_names)
        for job, body in privileged_jobs().items():
            for script in repository_scripts(body):
                with self.subTest(job=job, script=script):
                    source = (ROOT / script).read_text(encoding="utf-8")
                    if script.endswith(".py"):
                        for node in ast.walk(ast.parse(source)):
                            names = []
                            if isinstance(node, ast.Import):
                                names = [alias.name for alias in node.names]
                            elif isinstance(node, ast.ImportFrom):
                                names = [node.module or ""]
                            for name in names:
                                self.assertIn(name.split(".")[0], stdlib, name)
                    else:
                        self.assertNotRegex(source, DEPENDENCY_TOOLS)
                        self.assertNotRegex(source, r"\b(source|bash|python3?) ")

    def test_unprivileged_jobs_get_no_secrets_or_oidc(self):
        privileged = privileged_jobs()
        for path in sorted(WORKFLOWS.glob("*.yml")):
            for name, body in jobs(path):
                if f"{path.name}:{name}" not in privileged:
                    if re.search(r"^    uses: \./\.github/workflows/", body, re.M):
                        continue
                    with self.subTest(job=f"{path.name}:{name}"):
                        self.assertNotIn("id-token: write", body)
                        self.assertNotIn("secrets.", body)

    def test_auto_merge_runs_master_copy_for_dependabot_only(self):
        workflow = (WORKFLOWS / "dependabot-auto-merge.yml").read_text(encoding="utf-8")
        trigger = workflow.split("\npermissions:", 1)[0]
        self.assertIn("pull_request_target:", trigger)
        self.assertNotRegex(trigger, r"\n  pull_request:")
        self.assertNotIn("pull_request.head", workflow)
        self.assertIn(
            "if: github.event.pull_request.user.login == 'dependabot[bot]' "
            "&& github.actor == 'dependabot[bot]'",
            workflow,
        )
        self.assertIn('all(.author.login == "dependabot[bot]"', workflow)
        self.assertIn('gh pr merge --auto --squash "$PR_URL"', workflow)
        self.assertIn("DELETE https://api.github.com/installation/token", workflow)


if __name__ == "__main__":
    unittest.main()
