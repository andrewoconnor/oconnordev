import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = ROOT / ".github/workflows"
AUTO_MERGE = WORKFLOWS / "dependabot-auto-merge.yml"


def jobs(workflow):
    section = workflow.split("\njobs:\n", 1)[1]
    return re.findall(r"^  [\w-]+:\n((?:(?:    .*)?\n)*)", section, re.M)


def actions(text):
    return set(re.findall(r"uses: ([\w.-]+/[\w./-]+)@", text))


class DependabotAutoMergeTests(unittest.TestCase):
    def setUp(self):
        self.workflow = AUTO_MERGE.read_text(encoding="utf-8")

    def test_runs_only_for_dependabot_without_pull_request_code(self):
        trigger = self.workflow.split("\npermissions:", 1)[0]
        self.assertIn("pull_request_target:", trigger)
        self.assertNotRegex(trigger, r"\n  pull_request:")
        self.assertNotIn("actions/checkout", self.workflow)
        self.assertNotIn("pull_request.head", self.workflow)
        self.assertIn(
            "if: github.event.pull_request.user.login == 'dependabot[bot]' "
            "&& github.actor == 'dependabot[bot]'",
            self.workflow,
        )

    def test_actions_are_pinned_and_merge_waits_for_required_checks(self):
        for use in re.findall(r"uses: (\S+)", self.workflow):
            self.assertRegex(use, r"^[\w.-]+/[\w.-]+@[0-9a-f]{40}$")
        self.assertIn('run: gh pr merge --auto --squash "$PR_URL"', self.workflow)
        self.assertIn("GH_TOKEN: ${{ steps.app-token.outputs.token }}", self.workflow)
        self.assertNotIn("skip-commit-verification", self.workflow)

    def test_actions_pull_request_ci_never_runs_are_not_auto_merged(self):
        untested_runs, tested_runs = set(), set()
        for path in WORKFLOWS.glob("*.yml"):
            content = path.read_text(encoding="utf-8")
            base_branch_copy = "pull_request_target:" in content
            for body in jobs(content):
                gate = re.search(r"^    if: (.+)$", body, re.M)
                if base_branch_copy or (gate and "refs/heads/master" in gate.group(1)):
                    untested_runs |= actions(body)
                else:
                    tested_runs |= actions(body)
        listed = re.search(
            r"UNTESTED_BEFORE_MERGE: >-\n((?:            .*\n)+)", self.workflow
        ).group(1)
        self.assertTrue(untested_runs - tested_runs)
        self.assertEqual(set(listed.split()), untested_runs - tested_runs)


if __name__ == "__main__":
    unittest.main()
