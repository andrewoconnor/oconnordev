import importlib.util
import unittest
from pathlib import Path


class OverviewTests(unittest.TestCase):
    def test_paginates_and_summarizes_without_retaining_transaction_rows(self):
        path = Path(__file__).with_name("overview.py")
        self.assertTrue(path.exists(), "Repo-managed gateway overview is missing")
        spec = importlib.util.spec_from_file_location("plaid_overview", path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        calls = []

        def call(tool, arguments):
            calls.append((tool, arguments))
            if tool == "listItems":
                return {
                    "items": [
                        {
                            "alias": "capital-one",
                            "institution_name": "Capital One",
                            "products": ["transactions"],
                        }
                    ]
                }
            if tool == "getAccounts":
                return {
                    "accounts": [
                        {
                            "account_id": "private-id",
                            "name": "Checking",
                            "mask": "1234",
                            "type": "depository",
                            "balances": {"current": 20, "iso_currency_code": "USD"},
                        }
                    ]
                }
            if tool == "getItemStatus":
                return {
                    "status": {
                        "transactions": {
                            "last_successful_update": "2026-10-30T12:00:00Z"
                        }
                    }
                }
            offset = arguments["offset"]
            return {
                "total_transactions": 2,
                "next_offset": 1 if offset == 0 else None,
                "transactions": [
                    {
                        "transaction_id": f"private-tx-{offset}",
                        "date": "2026-10-01",
                        "amount": -10 if offset == 0 else 3,
                        "iso_currency_code": "USD",
                        "pending": False,
                    }
                ],
            }

        report = module.collect(call, "2026-10-01", "2026-10-30")
        self.assertEqual(
            [a["offset"] for t, a in calls if t == "getTransactions"], [0, 1]
        )
        self.assertEqual(
            report["items"][0]["transactions"]["currencies"]["USD"]["posted_credits"],
            "10",
        )
        self.assertEqual(
            report["items"][0]["transactions"]["currencies"]["USD"]["posted_debits"],
            "3",
        )
        self.assertNotIn("private-id", str(report))
        self.assertNotIn("private-tx", str(report))

    def test_stops_on_nonadvancing_pagination(self):
        spec = importlib.util.spec_from_file_location(
            "plaid_overview", Path(__file__).with_name("overview.py")
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        requests = []

        def call(tool, arguments):
            if tool == "listItems":
                return {"items": [{"alias": "usaa", "institution_name": "USAA"}]}
            if tool == "getAccounts":
                return {"accounts": []}
            requests.append(arguments)
            if len(requests) > 2:
                raise RuntimeError("test guard")
            return {"transactions": [], "total_transactions": 10, "next_offset": 0}

        report = module.collect(call, "2026-10-01", "2026-10-30")
        self.assertEqual(len(requests), 1)
        self.assertIn("error", report["items"][0])

    def test_cli_help_does_not_require_credentials(self):
        import subprocess
        import sys
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).resolve().with_name("overview.py")),
                    "--help",
                ],
                capture_output=True,
                text=True,
                cwd=directory,
                check=False,
            )
        self.assertEqual(result.returncode, 0)
        self.assertIn("--checkout", result.stdout)

    def test_real_stdio_handshake_and_secret_environment_isolation(self):
        import os
        import tempfile
        from unittest.mock import patch

        spec = importlib.util.spec_from_file_location(
            "plaid_overview", Path(__file__).with_name("overview.py")
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        adapter_source = """import json, os, sys
initialized = False
for line in sys.stdin:
    request = json.loads(line)
    if request["method"] == "notifications/initialized":
        initialized = True
        continue
    if request["method"] == "initialize":
        response = {"result": {"protocolVersion": "2025-03-26"}}
    elif not initialized:
        response = {"error": {"code": -32000}}
    else:
        forbidden = any(k.startswith(("PLAID_", "AWS_")) for k in os.environ)
        data = {"items": [], "forbidden_env_present": forbidden}
        response = {"result": {"content": [{"type": "text", "text": json.dumps(data)}]}}
    print(json.dumps({"jsonrpc": "2.0", "id": request["id"], **response}), flush=True)
"""
        env = {
            "HERMES_AGENTCORE_" + key: "test-value"
            for key in [
                "GATEWAY_URL",
                "COGNITO_TOKEN_URL",
                "COGNITO_CLIENT_ID",
                "COGNITO_CLIENT_SECRET",
            ]
        }
        env.update(
            {
                "PLAID_CLIENT_SECRET": "test-private",
                "AWS_SECRET_ACCESS_KEY": "test-private",
            }
        )
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, env):
            root = Path(directory)
            adapter = root / "agents/hermes/adapter/hermes_agentcore_adapter.py"
            adapter.parent.mkdir(parents=True)
            adapter.write_text(adapter_source)
            gateway = module.Gateway(root)
            try:
                data = gateway.call("listItems", {})
                self.assertFalse(data["forbidden_env_present"])
            finally:
                gateway.close()
            self.assertIsNotNone(gateway.process.poll())


if __name__ == "__main__":
    unittest.main()
