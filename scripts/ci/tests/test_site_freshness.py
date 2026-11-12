"""Real local Git remotes: no network or credentials."""

import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/ci/site_freshness.py"
sys.path.insert(0, str(SCRIPT.parent))

from site_freshness import SITES, deployment_inputs  # noqa: E402


class FreshnessTests(unittest.TestCase):
    def test_infra_successor_allowed_but_changed_app_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)

            def git(*args):
                return subprocess.check_output(
                    ["git", "-C", str(repo), *args], text=True
                ).strip()

            git("init", "-b", "master")
            git("config", "user.email", "test@example.invalid")
            git("config", "user.name", "Fixture")
            (repo / "README.md").write_text("initial")
            git("add", ".")
            git("commit", "-m", "initial")
            tested = git("rev-parse", "HEAD")
            git("remote", "add", "origin", str(repo))

            output = Path(temp) / "github-output"

            def check(sha=tested):
                output.write_text("")
                return subprocess.run(
                    [sys.executable, str(SCRIPT), "drumrollworld", sha],
                    cwd=repo,
                    capture_output=True,
                    text=True,
                    env={**os.environ, "GITHUB_OUTPUT": str(output)},
                )

            (repo / "README.md").write_text("documentation successor")
            (repo / "infra/aws/production").mkdir(parents=True)
            (repo / "infra/aws/production/account.tf").write_text("infra successor")
            git("add", ".")
            git("commit", "-m", "docs and unrelated infra")
            git("checkout", "--detach", "-q", tested)
            self.assertEqual(check().returncode, 0, check().stderr)
            self.assertEqual(output.read_text(), "deploy=true\n")
            self.assertEqual(git("rev-parse", "HEAD"), tested)
            self.assertNotEqual(git("rev-parse", "HEAD"), git("rev-parse", "master"))
            git("checkout", "-q", "master")
            for name in [
                "apps/drumrollworld/main.js",
                "scripts/ci/shared.py",
                "scripts/security/static-site-headers.test.cjs",
                "mise.toml",
                "mise.lock",
                "biome.json",
                ".github/workflows/drumrollworld-site.yml",
                ".github/workflows/site.yml",
                "scripts/drumrollworld/shared.mjs",
                "infra/modules/static-site/delivery.tf",
                "infra/aws/drumrollworld/site.tf",
            ]:
                path = repo / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("changed")
                git("add", ".")
                git("commit", "-m", name)
                newer = git("rev-parse", "HEAD")
                stale = check()
                self.assertEqual(stale.returncode, 0, name + stale.stderr)
                self.assertEqual(output.read_text(), "deploy=false\n", name)
                self.assertIn(f"Skipped: newer master commit {newer}", stale.stdout)
                self.assertIn(name, stale.stdout)
                git("reset", "--hard", tested)
            for watched_change in (True, False):
                git("checkout", "-q", "--orphan", f"rewritten-{watched_change}")
                if watched_change:
                    (repo / "apps/drumrollworld").mkdir(parents=True, exist_ok=True)
                    (repo / "apps/drumrollworld/main.js").write_text("unrelated")
                else:
                    (repo / "README.md").write_text("unrelated history, same inputs")
                git("add", ".")
                git("commit", "-m", "history without the tested commit")
                git("branch", "-f", "master", "HEAD")
                git("checkout", "-q", "master")
                diverged = check()
                self.assertNotEqual(diverged.returncode, 0, watched_change)
                self.assertEqual(output.read_text(), "", watched_change)
                git("reset", "--hard", tested)
            missing = check("f" * 40)
            self.assertNotEqual(missing.returncode, 0)
            self.assertIn("git", missing.stderr)
            self.assertNotEqual(check("master").returncode, 0)
            self.assertNotEqual(check("--upload-pack=evil").returncode, 0)
            git("remote", "set-url", "origin", str(repo / "missing"))
            fetch_error = check()
            self.assertNotEqual(fetch_error.returncode, 0)
            self.assertIn("git", fetch_error.stderr)


def glob_regex(glob):
    parts = re.split(r"(\*\*|\*)", glob)
    return "".join(
        ".*" if part == "**" else "[^/]*" if part == "*" else re.escape(part)
        for part in parts
    )


class PushTriggerTests(unittest.TestCase):
    def test_every_watched_input_starts_its_site_deploy(self):
        for site in SITES:
            workflow = (ROOT / f".github/workflows/{site}-site.yml").read_text()
            push = re.search(r"^  push:\n((?:    .*\n)+)", workflow, re.M).group(1)
            globs = re.findall(r'^      - "([^"]+)"$', push, re.M)
            self.assertTrue(globs, site)
            for watched in deployment_inputs(site):
                sample = watched + "any/file" if watched.endswith("/") else watched
                with self.subTest(site=site, input=watched):
                    self.assertTrue(
                        any(re.fullmatch(glob_regex(g), sample) for g in globs),
                        f"{watched} changes would skip {site} without a newer deploy",
                    )


if __name__ == "__main__":
    unittest.main()
