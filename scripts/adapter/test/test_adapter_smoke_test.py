import io
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

from scripts.adapter.adapter_smoke_test import load_gateway_validation, main


class EntrypointTests(unittest.TestCase):
    def test_reorganized_entrypoints_support_help_and_no_live_without_dependencies(
        self,
    ):
        root = Path(__file__).resolve().parents[3]
        script = root / "scripts" / "adapter" / "adapter_smoke_test.py"
        with tempfile.TemporaryDirectory() as temporary:
            for command, cwd in (
                ([sys.executable, "-S", str(script)], temporary),
                (
                    [sys.executable, "-S", "-m", "scripts.adapter.adapter_smoke_test"],
                    root,
                ),
            ):
                for options, status in ((["--help"], 0), ([], 2)):
                    with self.subTest(command=command, options=options):
                        result = subprocess.run(
                            command + options,
                            cwd=cwd,
                            capture_output=True,
                            text=True,
                            check=False,
                        )
                        self.assertEqual(result.returncode, status, result.stderr)
                        self.assertIn("opt-in", (result.stdout + result.stderr).lower())

    def test_library_load_uses_selected_checkout_not_cached_namesake(self):
        root = Path(__file__).resolve().parents[3]
        with tempfile.TemporaryDirectory() as temporary:
            checkout = Path(temporary)
            library = (
                checkout / "agents" / "hermes" / "adapter" / "gateway_validation.py"
            )
            library.parent.mkdir(parents=True)
            library.write_text(
                (root / "agents/hermes/adapter/gateway_validation.py").read_text()
                + "\nCHECKOUT_MARKER = 'selected-checkout'\n",
                encoding="utf-8",
            )
            with mock.patch.dict(sys.modules, {"gateway_validation": mock.Mock()}):
                validation = load_gateway_validation(checkout)
            self.assertEqual(Path(validation.__file__), library)
            self.assertEqual(validation.CHECKOUT_MARKER, "selected-checkout")
            self.assertTrue(callable(validation.run_gateway_checks))

    def test_missing_selected_library_does_not_fall_back_to_local_library(self):
        with (
            tempfile.TemporaryDirectory() as temporary,
            self.assertRaises(FileNotFoundError),
        ):
            load_gateway_validation(Path(temporary))


class LiveOptInTests(unittest.TestCase):
    def test_default_invocation_skips_network_and_is_not_a_pass(self):
        stderr = io.StringIO()
        with (
            mock.patch.object(sys, "argv", ["adapter_smoke_test.py"]),
            mock.patch("scripts.adapter.adapter_smoke_test.discover") as discover,
            redirect_stderr(stderr),
        ):
            self.assertEqual(main(), 2)
        discover.assert_not_called()
        self.assertIn("opt-in", stderr.getvalue())

    def test_live_invocation_fails_before_network_when_server_credentials_are_missing(
        self,
    ):
        argv = [
            "adapter_smoke_test.py",
            "--live",
            "--hermes",
            sys.executable,
            "--github-owner",
            "andrewoconnor",
            "--github-repo",
            "oconnordev",
        ]
        stderr = io.StringIO()
        hidden_value = "never-print-this-client-secret"
        environment = {"HERMES_AGENTCORE_COGNITO_CLIENT_SECRET": hidden_value}
        with (
            mock.patch.object(sys, "argv", argv),
            mock.patch(
                "scripts.adapter.adapter_smoke_test.load_hermes_server_environment",
                return_value=environment,
            ),
            mock.patch("scripts.adapter.adapter_smoke_test.discover") as discover,
            redirect_stderr(stderr),
        ):
            self.assertEqual(main(), 2)
        discover.assert_not_called()
        self.assertIn("HERMES_AGENTCORE_GATEWAY_URL", stderr.getvalue())
        self.assertNotIn(hidden_value, stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
