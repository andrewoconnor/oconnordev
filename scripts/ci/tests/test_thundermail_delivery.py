import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


class ThundermailDeliveryTests(unittest.TestCase):
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
