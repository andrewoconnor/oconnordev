"""Provider-free plan checks for supported static-site state addresses.

Synthetic terraform_data fixtures exercise OpenTofu move semantics only.
No backend, AWS credentials, network, or AWS provider is involved.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

TOFU = os.environ.get("TOFU", shutil.which("tofu") or "tofu")
ROOT = Path(__file__).resolve().parents[2]


class StaticSiteCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR"))
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_one_off_transfer_tooling_is_retired(self):
        for name in (
            "transfer_static_site_state.py",
            "static-site-state-map.json",
            "test_static_site_state.py",
        ):
            with self.subTest(path=name):
                self.assertFalse((ROOT / "scripts/infra" / name).exists())

    def test_drumroll_moves_include_indexed_certificate_and_dns_instances(self):
        import re

        repo = Path(__file__).resolve().parents[2]
        moves_source = (repo / "infra/aws/drumrollworld/moved.tf").read_text()
        moves = re.findall(r"from\s*=\s*([^\s]+)\s+to\s*=\s*([^\s]+)", moves_source)
        self.assertEqual(len(moves), 16)
        fixture = self.root / "drum-plans"
        fixture.mkdir()
        module = fixture / "site"
        module.mkdir()
        old_config, new_config, moved_config = [], [], []
        for old, new in moves:
            old_name = old.replace(".", "_")
            new_name = (
                new.removeprefix("module.site.").removesuffix("[0]").replace(".", "_")
            )
            is_validation_record = old == "aws_route53_record.drumrollworld_validation"
            index_input = "each.key" if is_validation_record else f'"{old_name}"'
            for_each = (
                'for_each = toset(["*.drumroll.world"])\n'
                if is_validation_record
                else ""
            )
            count = "count = 1\n" if new.endswith("[0]") else ""
            old_config.append(
                f'resource "terraform_data" "{old_name}" {{\n'
                f" {for_each} input = {index_input}\n}}\n"
            )
            new_config.append(
                f'resource "terraform_data" "{new_name}" {{\n'
                f" {for_each}{count} input = {index_input}\n}}\n"
            )
            index = "[0]" if new.endswith("[0]") else ""
            moved_config.append(
                f"moved {{\n from = terraform_data.{old_name}\n"
                f" to = module.site.terraform_data.{new_name}{index}\n}}\n"
            )
        (fixture / "main.tf").write_text("".join(old_config))
        self.run_tofu(fixture, "init", "-backend=false")
        self.run_tofu(fixture, "apply", "-auto-approve")
        (module / "main.tf").write_text("".join(new_config))
        (fixture / "main.tf").write_text(
            'module "site" { source = "./site" }\n' + "".join(moved_config)
        )
        self.run_tofu(fixture, "init", "-backend=false")
        changes = self.plan_json(fixture)["resource_changes"]
        self.assertEqual(len(changes), 16)
        self.assertTrue(all(c["change"]["actions"] == ["no-op"] for c in changes))
        self.assertEqual(sum("previous_address" in c for c in changes), 16)
        print(
            "FIXTURE: all 16 Drumroll moves (certificate [0], wildcard DNS key) "
            "no-op; zero destroys/replacements"
        )

    @staticmethod
    def run_tofu(root: Path, *args: str) -> str:
        result = subprocess.run(
            [TOFU, f"-chdir={root}", *args, "-no-color"],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        return result.stdout

    def plan_json(self, root: Path) -> dict:
        self.run_tofu(root, "plan", "-refresh=false", "-out=fixture.plan")
        return json.loads(
            subprocess.run(
                [TOFU, f"-chdir={root}", "show", "-json", "fixture.plan"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
