from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


class OpenTofuLockfileTests(unittest.TestCase):
    def test_every_provider_lock_uses_the_opentofu_registry_namespace(self):
        lockfiles = sorted(
            path
            for path in REPO_ROOT.rglob(".terraform.lock.hcl")
            if ".git" not in path.parts and ".terraform" not in path.parts
        )
        self.assertTrue(lockfiles, "No OpenTofu provider lockfiles found")

        for lockfile in lockfiles:
            with self.subTest(lockfile=lockfile.relative_to(REPO_ROOT)):
                providers = re.findall(
                    r'^provider\s+"([^"]+)"\s*\{',
                    lockfile.read_text(encoding="utf-8"),
                    flags=re.MULTILINE,
                )
                self.assertTrue(providers, "Lockfile contains no provider entries")
                self.assertTrue(
                    all(
                        provider.startswith("registry.opentofu.org/")
                        for provider in providers
                    ),
                    f"Expected OpenTofu registry addresses, found: {providers}",
                )


if __name__ == "__main__":
    unittest.main()
