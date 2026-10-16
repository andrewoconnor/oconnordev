"""The mail runtime follows the tools-account Lambda source convention."""

import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RUNTIME = "infra/aws/tools/lambdas/microsoft365_mcp"


class Microsoft365LayoutTests(unittest.TestCase):
    def test_runtime_is_beside_tools_account_lambda(self):
        runtime = ROOT / RUNTIME
        self.assertTrue((runtime / "main.mjs").is_file())
        self.assertTrue((runtime.parent / "spacelift_session_token").is_dir())
        obsolete = "/".join(("infra", "tools", "lambdas", "microsoft365_mcp"))
        tracked = (
            subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
            .decode()
            .split("\0")
        )
        for relative in filter(None, tracked):
            with self.subTest(path=relative):
                self.assertFalse(relative.startswith(obsolete + "/"))
                self.assertNotIn(obsolete.encode(), (ROOT / relative).read_bytes())

    def test_image_and_bootstrap_workflows_use_account_source(self):
        image = (ROOT / ".github/workflows/microsoft365-image.yml").read_text()
        bootstrap = (ROOT / ".github/workflows/microsoft365-bootstrap.yml").read_text()
        for workflow in (image, bootstrap):
            self.assertEqual(workflow.count(f"- '{RUNTIME}/**'"), 2)
        self.assertIn(f"--load --tag microsoft365-tested:local {RUNTIME}", image)
        self.assertIn(f'source="$PWD/{RUNTIME}/test",target=/app/test,readonly', image)
        self.assertIn(f"npm ci --prefix {RUNTIME} --ignore-scripts", bootstrap)
        # All Docker COPY sources are local to this context; no parent paths.
        dockerfile = (ROOT / RUNTIME / "Dockerfile").read_text()
        self.assertIn("COPY package.json package-lock.json ./", dockerfile)
        self.assertIn("COPY *.mjs tools-manifest.json ./", dockerfile)
        self.assertNotIn("../", dockerfile)

    def test_tools_root_covers_runtime_without_external_project_glob(self):
        from scripts.ci.path_selection import roots_for_paths

        for name in ("main.mjs", "tools-manifest.json", "test/http.test.mjs"):
            self.assertEqual(
                roots_for_paths([f"{RUNTIME}/{name}"]), ("infra/aws/tools",)
            )
        stacks = (ROOT / "infra/spacelift/main.tf").read_text()
        tools = stacks.split("    tools = {", 1)[1].split("    security = {", 1)[0]
        self.assertNotIn("lambdas/", tools)
        target = (ROOT / "infra/aws/tools/target-microsoft365.tf").read_text()
        self.assertIn(f"${{local.repo_root}}/{RUNTIME}/tools-manifest.json", target)
