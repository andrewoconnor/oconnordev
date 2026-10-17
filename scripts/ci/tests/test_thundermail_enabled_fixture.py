"""Inspect enabled boundaries only in an isolated, offline test source copy.

OpenTofu omits a failed-precondition resource and its dependents from the plan.
Production remains source-blocked; this fixture overrides a local only in a
throwaway directory, never an externally configurable production input.
"""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


class ThundermailEnabledFixtureTests(unittest.TestCase):
    def test_enabled_resources_with_test_only_readiness_source(self):
        source = ROOT / "infra/aws/tools"
        boundary = (source / "thundermail-boundary.tftest.hcl").read_text()
        header = boundary.split('run "default_zero"', 1)[0]
        assertions = (
            ROOT / "scripts/ci/fixtures/thundermail-enabled.tftest.hcl"
        ).read_text()
        with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as temporary:
            fixture = Path(temporary) / "tools"
            fixture.mkdir()
            (Path(temporary) / "accounts.json").symlink_to(
                source.parent / "accounts.json"
            )
            for path in source.glob("*.tf"):
                (fixture / path.name).write_text(path.read_text())
            for name in (".terraform", ".terraform.lock.hcl", "lambdas"):
                (fixture / name).symlink_to(source / name)
            # Test source only. All lifecycle preconditions remain present.
            (fixture / "override.tf").write_text(
                "locals {\n  thundermail_activation_ready = true\n"
                f'  repo_root = "{ROOT}"\n}}\n'
            )
            (fixture / "enabled.tftest.hcl").write_text(header + assertions)
            result = subprocess.run(
                ["tofu", "test", "-no-color"],
                cwd=fixture,
                capture_output=True,
                text=True,
                timeout=180,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("1 passed, 0 failed", result.stdout)
