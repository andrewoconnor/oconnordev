"""CSP proof belongs in each site's test entrypoint, exactly once."""

import subprocess
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


class CspCiTests(unittest.TestCase):
    def test_utf8_fixture_reader(self):
        result = subprocess.run(
            ["node", "--test", "scripts/security/fixture-reader.test.cjs"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_site_specific_runner_and_infra_triggers(self):
        tasks = tomllib.loads((ROOT / "mise.toml").read_text())["tasks"]
        for site in ("drumrollworld", "oconnordev"):
            commands = tasks[f"test:{site}"]["run"]
            self.assertIn(
                f"SITES={site} node scripts/security/static-site-headers.test.cjs",
                commands,
            )
            workflow = (ROOT / f".github/workflows/{site}-site.yml").read_text()
            self.assertEqual(workflow.count('"infra/aws/*/site.tf"'), 2)
            self.assertEqual(workflow.count('"scripts/security/**"'), 2)
            self.assertEqual(workflow.count('".github/workflows/site.yml"'), 2)
            self.assertNotIn("static-site-headers.test.cjs", workflow)
        shared = (ROOT / ".github/workflows/site.yml").read_text()
        self.assertEqual(shared.count('mise run "test:$SITE"'), 1)
        self.assertNotIn("static-site-headers.test.cjs", shared)
        self.assertIn("scripts.ci.tests.test_site_freshness", shared)
        self.assertIn("scripts.ci.tests.test_site_csp_ci", shared)
        runner = (ROOT / "scripts/security/static-site-headers.test.cjs").read_text()
        self.assertNotIn("DRUMROLL_FIXTURES", runner)
        self.assertNotIn('"/usr/bin/chromium"', runner)


if __name__ == "__main__":
    unittest.main()
