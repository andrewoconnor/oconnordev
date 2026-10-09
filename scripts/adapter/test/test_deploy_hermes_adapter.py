import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "deploy_hermes_adapter.sh"


class DeploymentSummaryTests(unittest.TestCase):
    def run_deployment(self, *, live=False, smoke_exit=0):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            checkout = root / "checkout"
            checkout.mkdir()
            (checkout / ".git").mkdir()
            bin_dir = root / "bin"
            bin_dir.mkdir()
            marker = root / "live-smoke-invoked"
            (bin_dir / "git").write_text(
                "#!/bin/sh\n"
                'case "$*" in\n'
                "  *'rev-parse --quiet --verify HEAD'*) exit 0 ;;\n"
                "  *'status --porcelain'*) exit 0 ;;\n"
                "  *'rev-parse --short HEAD'*) printf 'abc123\\n'; exit 0 ;;\n"
                "  *'fetch --quiet origin master'*) exit 0 ;;\n"
                "  *'merge --ff-only --quiet origin/master'*) exit 0 ;;\n"
                "  *) printf 'unexpected git invocation: %s\\n' \"$*\" >&2; exit 2 ;;\n"
                "esac\n",
                encoding="utf-8",
            )
            (bin_dir / "python3").write_text(
                "#!/bin/sh\n"
                'printf \'%s\\n\' "$*" >> "$SMOKE_MARKER"\n'
                'exit "$SMOKE_EXIT_CODE"\n',
                encoding="utf-8",
            )
            (bin_dir / "git").chmod(0o755)
            (bin_dir / "python3").chmod(0o755)
            environment = os.environ.copy()
            environment.update(
                {
                    "PATH": str(bin_dir) + os.pathsep + environment.get("PATH", ""),
                    "PYTHON": "python3",
                    "SMOKE_MARKER": str(marker),
                    "SMOKE_EXIT_CODE": str(smoke_exit),
                }
            )
            arguments = [
                "bash",
                str(SCRIPT),
                "--checkout",
                str(checkout),
                "--skip-tests",
                "--reloaded",
            ]
            if live:
                arguments.append("--live-smoke")
            result = subprocess.run(
                arguments, capture_output=True, text=True, env=environment, check=False
            )
            return result, marker.read_text(encoding="utf-8") if marker.exists() else ""

    def test_skipped_live_check_is_reported_as_skipped(self):
        result, smoke_calls = self.run_deployment()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("live gateway validation skipped", result.stdout.lower())
        self.assertNotIn("live gateway validation passed", result.stdout.lower())
        self.assertEqual(smoke_calls, "")

    def test_live_check_is_reported_as_passed_only_after_success(self):
        result, smoke_calls = self.run_deployment(live=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("live gateway validation passed", result.stdout.lower())
        self.assertIn("--live", smoke_calls)

    def test_failed_live_check_never_reports_passed(self):
        result, smoke_calls = self.run_deployment(live=True, smoke_exit=1)
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("live gateway validation passed", result.stdout.lower())
        self.assertIn("the live adapter/gateway checks failed", result.stderr)
        self.assertIn("--live", smoke_calls)


if __name__ == "__main__":
    unittest.main()
