import io
import sys
import unittest
from contextlib import redirect_stderr
from unittest import mock

from scripts.adapter_smoke_test import main


class LiveOptInTests(unittest.TestCase):
    def test_default_invocation_skips_network_and_is_not_a_pass(self):
        stderr = io.StringIO()
        with mock.patch.object(sys, "argv", ["adapter_smoke_test.py"]), mock.patch("scripts.adapter_smoke_test.discover") as discover:
            with redirect_stderr(stderr):
                self.assertEqual(main(), 2)
        discover.assert_not_called()
        self.assertIn("opt-in", stderr.getvalue())

    def test_live_invocation_fails_before_network_when_server_credentials_are_missing(self):
        argv = ["adapter_smoke_test.py", "--live", "--hermes", sys.executable, "--github-owner", "andrewoconnor", "--github-repo", "oconnordev"]
        stderr = io.StringIO()
        hidden_value = "never-print-this-client-secret"
        environment = {"HERMES_AGENTCORE_COGNITO_CLIENT_SECRET": hidden_value}
        with mock.patch.object(sys, "argv", argv), mock.patch("scripts.adapter_smoke_test.load_hermes_server_environment", return_value=environment), mock.patch("scripts.adapter_smoke_test.discover") as discover:
            with redirect_stderr(stderr):
                self.assertEqual(main(), 2)
        discover.assert_not_called()
        self.assertIn("HERMES_AGENTCORE_GATEWAY_URL", stderr.getvalue())
        self.assertNotIn(hidden_value, stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
