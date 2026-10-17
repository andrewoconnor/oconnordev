import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


class ThundermailDeliveryTests(unittest.TestCase):
    def helper(self):
        path = ROOT / "scripts/ci/thundermail_image.py"
        self.assertTrue(
            path.exists(), "native publication must guard fresh tested inputs"
        )
        spec = importlib.util.spec_from_file_location("thundermail_image", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_activation_has_no_input_override(self):
        import re

        source = (ROOT / "infra/aws/tools/thundermail-runtime.tf").read_text()
        self.assertRegex(source, r"thundermail_activation_ready\s*=\s*false\b")
        self.assertRegex(
            source, r"condition\s*=\s*local\.thundermail_activation_ready\b"
        )
        self.assertNotRegex(source, r'variable\s+"thundermail_activation_ready"')
        assignments = re.findall(r"thundermail_activation_ready\s*=", source)
        self.assertEqual(len(assignments), 1)

    def test_delivery_layout_uses_runtime_owned_paths(self):
        runtime = ROOT / "infra/aws/tools/lambdas/thundermail_mcp"
        self.assertFalse((ROOT / "delivery/thundermail").exists())
        for name in ("Dockerfile", "check.py", "native_smoke.py"):
            self.assertTrue((runtime / name).is_file())
        workflow = (ROOT / ".github/workflows/thundermail-image.yml").read_text()
        self.assertIn(
            "--file infra/aws/tools/lambdas/thundermail_mcp/Dockerfile .", workflow
        )
        self.assertIn(
            "python3 infra/aws/tools/lambdas/thundermail_mcp/native_smoke.py", workflow
        )
        self.assertIn(
            "infra/aws/tools/lambdas/thundermail_mcp/check.py",
            (ROOT / "mise.toml").read_text(),
        )
        # Build context remains repository root: every COPY source still exists.
        for line in (runtime / "Dockerfile").read_text().splitlines():
            if line.startswith("COPY ") and "--from=" not in line:
                for path in line.split()[1:-1]:
                    self.assertTrue((ROOT / path).exists(), path)

    def test_secret_path_matches_runtime_and_metadata(self):
        import re

        runtime = (
            ROOT / "infra/aws/tools/lambdas/thundermail_mcp/src/aws_secret.rs"
        ).read_text()
        iac = (ROOT / "infra/aws/tools/thundermail-runtime.tf").read_text()
        path = re.search(r'pub const SECRET_PATH: &str = "([^"]+)"', runtime)[1]
        self.assertIn(f'name                    = "{path}"', iac)
        self.assertIn(f"secret:{path}-", iac)

    def test_publication_is_review_gated_exact_archive_before_credentials(self):
        dockerfile = (
            ROOT / "infra/aws/tools/lambdas/thundermail_mcp/Dockerfile"
        ).read_text()
        self.assertIn(
            "LICENSE.upstream /usr/share/licenses/thundermail/LICENSE.upstream",
            dockerfile,
        )
        self.assertIn(
            "RUN cargo test --locked && cargo build --locked --release", dockerfile
        )
        workflow = (ROOT / ".github/workflows/thundermail-image.yml").read_text()
        publish = workflow.split("\n  publish:", 1)[1]
        gate = publish.split("\n    needs:", 1)[0]
        # Even THUNDERMAIL_ARM64_REVIEWED=true on master cannot publish the
        # known-vulnerable lock. Opening publication requires reviewed source.
        self.assertIn("if: ${{ false && github.ref == 'refs/heads/master' }}", gate)
        self.assertNotIn("vars.", gate)
        lock = (ROOT / "infra/aws/tools/lambdas/thundermail_mcp/Cargo.lock").read_text()
        self.assertIn('name = "aws-smithy-json"\nversion = "0.62.3"', lock)
        self.assertNotIn("pull_request", gate)
        credentials = publish.index("uses: aws-actions/configure-aws-credentials@")
        for check in [
            "uses: actions/download-artifact@",
            "sha256sum --check --strict",
            "docker load --input release/image.tar",
            'test "$(docker image inspect',
            "python3 scripts/ci/thundermail_image.py",
        ]:
            self.assertLess(publish.index(check), credentials)
        self.assertNotIn("docker build", publish)
        self.assertNotIn("update-function", workflow)
        self.assertNotIn("tofu apply", workflow)
        self.assertIn('test "$DIGEST" = "$PUSH_DIGEST"', publish)

    def test_freshness_covers_all_owned_inputs_and_native_architecture(self):
        helper = self.helper()
        for path in [
            "infra/aws/tools/lambdas/thundermail_mcp/Dockerfile",
            "infra/aws/tools/lambdas/thundermail_mcp/check.py",
            "infra/aws/tools/lambdas/thundermail_mcp/native_smoke.py",
            "infra/aws/tools/lambdas/thundermail_mcp/src/main.rs",
            "agents/hermes/adapter/thundermail-mcp-tools.json",
            "scripts/ci/thundermail_image.py",
            ".github/workflows/thundermail-image.yml",
        ]:
            self.assertTrue(helper.is_image_input(path))
        self.assertFalse(helper.is_image_input("apps/oconnordev/index.html"))
        good = {"Architecture": "arm64", "Os": "linux", "Id": "sha256:" + "a" * 64}
        self.assertEqual(helper.check_image_metadata(good), good["Id"])
        for bad in [
            {**good, "Architecture": "amd64"},
            {**good, "Os": "windows"},
            {**good, "Id": "latest"},
        ]:
            with self.assertRaises(ValueError):
                helper.check_image_metadata(bad)
