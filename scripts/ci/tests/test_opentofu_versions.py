"""Keep runtime pins aligned without blocking administrative self-upgrade."""

import re
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


class OpenTofuVersionTests(unittest.TestCase):
    def test_runtime_and_lock_pins_match(self):
        version = tomllib.loads((ROOT / "mise.toml").read_text())["tools"]["opentofu"]
        self.assertEqual(version, "1.13.2")
        lock = tomllib.loads((ROOT / "mise.lock").read_text())["tools"]["opentofu"]
        self.assertEqual({entry["version"] for entry in lock}, {version})
        source = (ROOT / "infra/spacelift/main.tf").read_text()
        self.assertIn(f'tofu_version = "{version}"', source)

    def test_constraints_allow_administrative_self_upgrade(self):
        admin = ROOT / "infra/spacelift/versions.tf"
        for path in (ROOT / "infra").rglob("versions.tf"):
            with self.subTest(path=path):
                value = re.search(r'required_version\s*=\s*"([^"]+)"', path.read_text())
                if value is None:
                    self.fail("Missing required_version")
                minimum = "1.12.0" if path == admin else "1.13.1"
                self.assertEqual(value.group(1), f">= {minimum}, < 2.0.0")
