"""Real local Git remotes: no network or credentials."""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "site_freshness.py"


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

            def check(sha=tested):
                return subprocess.run(
                    [sys.executable, str(SCRIPT), "drumrollworld", sha],
                    cwd=repo,
                    capture_output=True,
                    text=True,
                )

            (repo / "README.md").write_text("documentation successor")
            (repo / "infra/aws/production").mkdir(parents=True)
            (repo / "infra/aws/production/account.tf").write_text("infra successor")
            git("add", ".")
            git("commit", "-m", "docs and unrelated infra")
            git("checkout", "--detach", "-q", tested)
            self.assertEqual(check().returncode, 0, check().stderr)
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
                "scripts/drumrollworld/shared.mjs",
                "infra/modules/static-site/delivery.tf",
                "infra/aws/drumrollworld/site.tf",
            ]:
                path = repo / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("changed")
                git("add", ".")
                git("commit", "-m", name)
                self.assertNotEqual(check().returncode, 0, name)
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


if __name__ == "__main__":
    unittest.main()
