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

    def test_delivery_layout_uses_runtime_owned_paths(self):
        runtime = ROOT / "infra/aws/tools/lambdas/thundermail_mcp"
        self.assertFalse((ROOT / "delivery/thundermail").exists())
        for name in ("Dockerfile", "native_smoke.py"):
            self.assertTrue((runtime / name).is_file())
        workflow = (ROOT / ".github/workflows/thundermail-image.yml").read_text()
        self.assertIn(
            "--file infra/aws/tools/lambdas/thundermail_mcp/Dockerfile .", workflow
        )
        self.assertIn(
            "python3 infra/aws/tools/lambdas/thundermail_mcp/native_smoke.py", workflow
        )
        self.assertIn(
            'dir = "infra/aws/tools/lambdas/thundermail_mcp"',
            (ROOT / "mise.toml").read_text(),
        )
        # Build context remains repository root: every COPY source still exists.
        for line in (runtime / "Dockerfile").read_text().splitlines():
            if line.startswith("COPY ") and "--from=" not in line:
                for path in line.split()[1:-1]:
                    if not path.startswith("--"):
                        self.assertTrue((ROOT / path).exists(), path)

    def test_native_image_defaults_to_nonroot_with_uid_independent_files(self):
        dockerfile = (
            ROOT / "infra/aws/tools/lambdas/thundermail_mcp/Dockerfile"
        ).read_text()
        runtime = dockerfile.rsplit("\nFROM ", 1)[1]
        self.assertIn("\nUSER 10001:10001\n", runtime)
        self.assertIn("COPY --chmod=0755 --from=build /build/bootstrap", runtime)
        for name in ("LICENSE.upstream", "extraction.json"):
            self.assertIn(
                f"COPY --chmod=0644 infra/aws/tools/lambdas/thundermail_mcp/{name}",
                runtime,
            )
        smoke = (
            ROOT / "infra/aws/tools/lambdas/thundermail_mcp/native_smoke.py"
        ).read_text()
        self.assertIn('"10002:10002"', smoke)
        self.assertIn('"10001:10001"', smoke)

    def test_notice_directory_is_traversable_with_actual_copy_parent_modes(self):
        import os
        import re
        import subprocess
        import tempfile

        dockerfile = (
            (ROOT / "infra/aws/tools/lambdas/thundermail_mcp/Dockerfile")
            .read_text()
            .rsplit("\nFROM ", 1)[1]
        )
        # The pinned AL2023 layers leave /usr/share/licenses at 0755 and have
        # no thundermail directory. BuildKit fsutil/copy.Copy passes ci.Mode
        # to MkdirAll for missing destination parents (including 0644).
        # Source: moby/buildkit v0.24.0 vendor/.../fsutil/copy/copy.go, Copy.
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            licenses = root / "usr/share/licenses"
            licenses.mkdir(parents=True, mode=0o755)
            for line in dockerfile.splitlines():
                if line.startswith("RUN chmod 0755 "):
                    command = line.removeprefix("RUN ").split()
                    command[-1] = str(root / command[-1].lstrip("/"))
                    subprocess.run(command, check=True)
                match = re.fullmatch(r"COPY --chmod=(0644) (\S+) (\S+)", line)
                if match:
                    mode, source, destination = match.groups()
                    target = root / destination.lstrip("/")
                    if not target.parent.exists():
                        target.parent.mkdir(mode=int(mode, 8))
                    # A root image builder can populate a non-searchable parent.
                    # Temporarily allow the unprivileged fixture builder to do so.
                    parent_mode = target.parent.stat().st_mode & 0o777
                    target.parent.chmod(0o755)
                    target.write_bytes((ROOT / source).read_bytes())
                    target.chmod(int(mode, 8))
                    target.parent.chmod(parent_mode)
            directory = licenses / "thundermail"
            try:
                self.assertNotEqual(os.getuid(), 0, "run fixture as non-root")
                self.assertTrue(
                    os.access(directory, os.X_OK),
                    "notice parent is not traversable: "
                    f"{oct(directory.stat().st_mode & 0o777)}",
                )
                for name in ("LICENSE.upstream", "extraction.json"):
                    self.assertTrue(os.access(directory / name, os.R_OK), name)
            finally:
                directory.chmod(0o755)

    def test_only_lambda_inapplicable_healthcheck_is_exempted(self):
        dockerfile = (
            ROOT / "infra/aws/tools/lambdas/thundermail_mcp/Dockerfile"
        ).read_text()
        skips = [line for line in dockerfile.splitlines() if "checkov:skip=" in line]
        self.assertEqual(len(skips), 1)
        self.assertIn("checkov:skip=CKV_DOCKER_2:", skips[0])
        self.assertIn("Lambda Runtime API", skips[0])
        self.assertNotIn("\nHEALTHCHECK ", dockerfile)
        readme = (
            ROOT / "infra/aws/tools/lambdas/thundermail_mcp/README.md"
        ).read_text()
        self.assertIn("CKV_DOCKER_2", readme)
        self.assertIn("not a Lambda readiness", readme)

    def smoke_helper(self):
        path = ROOT / "infra/aws/tools/lambdas/thundermail_mcp/native_smoke.py"
        spec = importlib.util.spec_from_file_location("thundermail_smoke", path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_smoke_rejects_root_default_before_execution(self):
        from unittest.mock import patch

        smoke = self.smoke_helper()
        with (
            patch.object(smoke.subprocess, "check_output", return_value="0:0\n"),
            patch.object(smoke.subprocess, "run") as run,
        ):
            with self.assertRaisesRegex(
                AssertionError, "unexpected default image user"
            ):
                smoke.check_image_permissions("fixture")
            run.assert_not_called()

    def test_smoke_checks_default_and_override_access_without_network(self):
        from unittest.mock import patch

        smoke = self.smoke_helper()
        with (
            patch.object(
                smoke.subprocess, "check_output", return_value="10001:10001\n"
            ),
            patch.object(smoke.subprocess, "run") as run,
        ):
            smoke.check_image_permissions("fixture")
            self.assertEqual(run.call_count, 2)
            default, override = [call.args[0] for call in run.call_args_list]
            self.assertNotIn("--user", default)
            self.assertEqual(override[override.index("--user") + 1], "10002:10002")
            for call in run.call_args_list:
                self.assertIn("--network=none", call.args[0])
                self.assertIn("--read-only", call.args[0])
                self.assertTrue(call.kwargs["check"])
                self.assertEqual(call.kwargs["timeout"], 15)
                for path in (
                    "/var/runtime/bootstrap",
                    "/usr/share/licenses/thundermail/LICENSE.upstream",
                    "/usr/share/licenses/thundermail/extraction.json",
                ):
                    self.assertIn(path, call.args[0][-1])

    def test_smoke_reports_each_inaccessible_path_in_nonroot_fixture(self):
        import re
        import subprocess
        import tempfile
        from unittest.mock import patch

        smoke = self.smoke_helper()
        with (
            patch.object(
                smoke.subprocess, "check_output", return_value="10001:10001\n"
            ),
            patch.object(smoke.subprocess, "run") as run,
        ):
            smoke.check_image_permissions("fixture")
            script = run.call_args_list[0].args[0][-1]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bootstrap = root / "var/runtime/bootstrap"
            bootstrap.parent.mkdir(parents=True)
            bootstrap.write_text("fixture executable; not a production binary")
            bootstrap.chmod(0o755)
            notices = root / "usr/share/licenses/thundermail"
            notices.mkdir(parents=True)
            for name in ("LICENSE.upstream", "extraction.json"):
                (notices / name).write_text("fixture notice")
                (notices / name).chmod(0o644)
            script = re.sub(
                r"/(?:var|usr)(?:[A-Za-z0-9_./-]*)",
                lambda match: str(root) + match[0],
                script,
            )
            notices.chmod(0o644)
            try:
                result = subprocess.run(
                    ["/bin/sh", "-c", script], capture_output=True, text=True
                )
                self.assertEqual(result.returncode, 1)
                for path in (
                    notices,
                    notices / "LICENSE.upstream",
                    notices / "extraction.json",
                ):
                    self.assertIn(
                        f"FAIL -x {path}" if path == notices else f"FAIL -r {path}",
                        result.stderr,
                    )
                self.assertIn(f"PASS -x {bootstrap}", result.stdout)
            finally:
                notices.chmod(0o755)
            result = subprocess.run(
                ["/bin/sh", "-c", script], capture_output=True, text=True
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("FAIL", result.stderr)

    def test_smoke_does_not_ignore_permission_failures(self):
        import subprocess
        from unittest.mock import patch

        smoke = self.smoke_helper()
        with (
            patch.object(
                smoke.subprocess, "check_output", return_value="10001:10001\n"
            ),
            patch.object(
                smoke.subprocess,
                "run",
                side_effect=subprocess.CalledProcessError(1, "docker"),
            ),
            self.assertRaises(subprocess.CalledProcessError),
        ):
            smoke.check_image_permissions("fixture")

    def test_secret_path_matches_runtime_and_metadata(self):
        import re

        runtime = (
            ROOT / "infra/aws/tools/lambdas/thundermail_mcp/src/aws_secret.rs"
        ).read_text()
        iac = (ROOT / "infra/aws/tools/thundermail-runtime.tf").read_text()
        path = re.search(r'pub const SECRET_PATH: &str = "([^"]+)"', runtime)[1]
        self.assertIn(f'name                    = "{path}"', iac)

    def test_publication_is_review_gated_exact_archive_before_credentials(self):
        dockerfile = (
            ROOT / "infra/aws/tools/lambdas/thundermail_mcp/Dockerfile"
        ).read_text()
        self.assertIn(
            "LICENSE.upstream /usr/share/licenses/thundermail/LICENSE.upstream",
            dockerfile,
        )
        self.assertIn(
            "RUN mise exec rust -- cargo test --locked && "
            "mise exec rust -- cargo build --locked --release",
            dockerfile,
        )
        workflow = (ROOT / ".github/workflows/thundermail-image.yml").read_text()
        publish = workflow.split("\n  publish:", 1)[1]
        gate = publish.split("\n    needs:", 1)[0]
        self.assertIn("if: ${{ github.ref == 'refs/heads/master' }}", gate)
        self.assertNotIn("vars.", gate)
        lock = (ROOT / "infra/aws/tools/lambdas/thundermail_mcp/Cargo.lock").read_text()
        self.assertIn('name = "aws-smithy-json"\nversion = "0.62.7"', lock)
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
