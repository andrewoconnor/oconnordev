import importlib.util
import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock

PATH = Path(__file__).with_name("plaid.py")


class PlaidTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(PATH.exists(), "Native Plaid runtime is missing")
        spec = importlib.util.spec_from_file_location("plaid_runtime", PATH)
        self.runtime = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.runtime)
        self.secret = {
            "client_id": "synthetic-client",
            "secret": "synthetic-secret",
            "items": {
                alias: {
                    "access_token": "synthetic-token-" + alias,
                    "institution_name": alias.title(),
                    "products": ["transactions"],
                }
                for alias in ["capital-one", "usaa", "amex", "empower"]
            },
        }
        self.store = Mock()
        self.store.get_secret_value.return_value = {
            "SecretString": json.dumps(self.secret)
        }
        self.opener = MagicMock()

    def call(self, name, args=None):
        return self.runtime.handle(
            {} if args is None else args,
            "plaid___" + name,
            self.store,
            {"SECRETS_ARN": "synthetic-arn"},
            self.opener,
        )

    def response(self, body, status=200):
        response = Mock()
        response.status = status
        response.read.return_value = json.dumps(body).encode()
        self.opener.return_value.__enter__.return_value = response
        return response

    def test_accounts_posts_only_to_fixed_production_endpoint_and_sanitizes(self):
        response = self.response(
            {
                "accounts": [
                    {
                        "account_id": "a",
                        "balances": {"current": 42},
                        "access_token": "bad",
                        "nested": {"client_id": "bad", "request_token": "bad"},
                    }
                ],
                "request_id": "safe-id",
                "echo": "synthetic-secret",
            }
        )
        result = self.call("getAccounts", {"item": "usaa"})
        request = self.opener.call_args.args[0]
        self.assertEqual(request.full_url, "https://production.plaid.com/accounts/get")
        self.assertEqual(request.method, "POST")
        self.assertEqual(
            json.loads(request.data),
            {
                "client_id": "synthetic-client",
                "secret": "synthetic-secret",
                "access_token": "synthetic-token-usaa",
            },
        )
        self.assertEqual(self.opener.call_args.kwargs, {"timeout": 10})
        self.assertEqual(result["accounts"][0]["balances"]["current"], 42)
        self.assertNotIn("bad", json.dumps(result))
        self.assertNotIn("synthetic-secret", json.dumps(result))
        response.read.assert_called_once_with(self.runtime.MAX_RESPONSE + 1)

    def test_provider_errors_and_transport_failures_are_safe(self):
        for status in [302, 400, 401, 500]:
            self.response(
                {
                    "error_code": "ITEM_LOGIN_REQUIRED",
                    "request_id": "safe-id",
                    "error_message": "synthetic-secret",
                    "access_token": "synthetic-token-usaa",
                },
                status,
            )
            result = self.call("getAccounts", {"item": "usaa"})
            self.assertTrue(result["isError"])
            self.assertIn("ITEM_LOGIN_REQUIRED", json.dumps(result))
            self.assertIn("safe-id", json.dumps(result))
            self.assertNotIn("synthetic", json.dumps(result))
        self.opener.side_effect = TimeoutError("synthetic-secret")
        self.assertNotIn(
            "synthetic", json.dumps(self.call("getAccounts", {"item": "usaa"}))
        )

    def test_redirect_handler_never_follows_location(self):
        self.assertIsNone(
            self.runtime.NoRedirect().redirect_request(
                None, None, 302, "", {}, "https://evil.test"
            )
        )

    def test_provider_payload_is_not_silently_truncated(self):
        response = self.response({})
        for raw in [b"x" * (self.runtime.MAX_RESPONSE + 1), b"not json", b"[]"]:
            response.read.return_value = raw
            self.assertTrue(self.call("getAccounts", {"item": "usaa"})["isError"])

    def test_transactions_preserve_provider_offset_and_explicit_pagination(self):
        args = {
            "item": "usaa",
            "startDate": "2026-01-01",
            "endDate": "2026-01-31",
            "count": 2,
            "offset": 7,
        }
        self.response(
            {
                "transactions": [{"transaction_id": "t8"}, {"transaction_id": "t9"}],
                "total_transactions": 12,
                "request_id": "safe",
            }
        )
        result = self.call("getTransactions", args)
        payload = json.loads(self.opener.call_args.args[0].data)
        self.assertEqual(payload["options"], {"count": 2, "offset": 7})
        self.assertEqual(payload["start_date"], args["startDate"])
        self.assertEqual(result["total_transactions"], 12)
        self.assertEqual(result["next_offset"], 9)
        self.assertEqual(result["offset"], 7)
        self.response({"transactions": [], "total_transactions": 0})
        result = self.call(
            "getTransactions",
            {k: v for k, v in args.items() if k not in {"count", "offset"}},
        )
        self.assertIsNone(result["next_offset"])
        self.assertEqual(
            json.loads(self.opener.call_args.args[0].data)["options"],
            {"count": 100, "offset": 0},
        )

    def test_inconsistent_transaction_page_fails_instead_of_skipping(self):
        for data in [
            {"transactions": [], "total_transactions": 10},
            {"transactions": [{}], "total_transactions": True},
            {"transactions": [{}]},
            {"transactions": [{}, {}], "total_transactions": 1},
        ]:
            self.response(data)
            self.assertTrue(
                self.call(
                    "getTransactions",
                    {
                        "item": "usaa",
                        "startDate": "2026-01-01",
                        "endDate": "2026-01-31",
                    },
                )["isError"]
            )

    def test_transactions_without_consent_make_no_provider_call(self):
        self.secret["items"]["usaa"]["products"] = ["investments"]
        self.store.get_secret_value.return_value = {
            "SecretString": json.dumps(self.secret)
        }
        self.response({"transactions": [], "total_transactions": 0})
        result = self.call(
            "getTransactions",
            {"item": "usaa", "startDate": "2026-10-01", "endDate": "2026-10-30"},
        )
        self.assertTrue(result.get("isError"))
        self.opener.assert_not_called()

    def test_product_gates_and_recurring_entitlement_do_not_expand_consent(self):
        self.response({"liabilities": {}, "holdings": [], "inflow_streams": []})
        for name in ["getLiabilities", "getHoldings"]:
            self.assertTrue(self.call(name, {"item": "usaa"})["isError"])
        self.opener.assert_not_called()
        result = self.call("getRecurringTransactions", {"item": "usaa"})
        self.assertIn("entitlement", result["recurring_note"])
        self.assertEqual(
            self.opener.call_args.args[0].full_url,
            "https://production.plaid.com/transactions/recurring/get",
        )
        for name, product, path in [
            ("getLiabilities", "liabilities", "/liabilities/get"),
            ("getHoldings", "investments", "/investments/holdings/get"),
        ]:
            self.secret["items"]["usaa"]["products"] = [product]
            self.store.get_secret_value.return_value = {
                "SecretString": json.dumps(self.secret)
            }
            self.assertNotIn("isError", self.call(name, {"item": "usaa"}))
            self.assertEqual(
                self.opener.call_args.args[0].full_url,
                "https://production.plaid.com" + path,
            )
        before = self.opener.call_count
        self.assertTrue(
            self.call("getRecurringTransactions", {"item": "usaa"})["isError"]
        )
        self.assertEqual(self.opener.call_count, before)

    def test_item_status_preserves_freshness_and_safe_consent_metadata(self):
        self.response(
            {
                "item": {
                    "item_id": "id",
                    "error": {
                        "error_code": "ITEM_LOGIN_REQUIRED",
                        "error_message": "synthetic-token-usaa",
                    },
                    "consented_products": ["transactions"],
                    "consent_expiration_time": "2026-12-01",
                    "access_token": "bad",
                },
                "status": {"transactions": {"last_successful_update": "2026-01-01"}},
            }
        )
        result = self.call("getItemStatus", {"item": "usaa"})
        self.assertEqual(result["item"]["error"]["error_code"], "ITEM_LOGIN_REQUIRED")
        self.assertEqual(
            result["status"]["transactions"]["last_successful_update"], "2026-01-01"
        )
        self.assertEqual(result["configured_products"], ["transactions"])
        self.assertNotIn("bad", json.dumps(result))
        self.assertNotIn("synthetic-token", json.dumps(result))

    def test_native_handler_uses_tool_context_and_redirect_disabled_opener(self):
        import sys
        from types import SimpleNamespace
        from unittest.mock import patch

        context = SimpleNamespace(
            client_context=SimpleNamespace(
                custom={"bedrockAgentCoreToolName": "plaid___listItems"}
            )
        )
        boto = Mock()
        boto.client.return_value = self.store
        with (
            patch.dict(sys.modules, {"boto3": boto, "botocore.config": Mock()}),
            patch.dict("os.environ", {"SECRETS_ARN": "synthetic-arn"}),
            patch.object(self.runtime.urllib.request, "build_opener") as build,
        ):
            result = self.runtime.handler({}, context)
        self.assertEqual(len(result["items"]), 4)
        boto.client.assert_called_once_with("secretsmanager", config=unittest.mock.ANY)
        self.assertIsInstance(build.call_args.args[0], self.runtime.NoRedirect)

    def test_discovery_redacts_credential_values_in_institution_names(self):
        self.secret["items"]["usaa"]["institution_name"] = "synthetic-secret"
        self.store.get_secret_value.return_value = {
            "SecretString": json.dumps(self.secret)
        }
        self.assertNotIn("synthetic-secret", json.dumps(self.call("listItems")))

    def test_ambiguous_secret_and_nonfinite_provider_json_are_rejected(self):
        raw = json.dumps(self.secret).replace(
            '"client_id": "synthetic-client"',
            '"client_id": "other", "client_id": "synthetic-client"',
        )
        self.store.get_secret_value.return_value = {"SecretString": raw}
        self.assertTrue(self.call("listItems")["isError"])
        self.store.get_secret_value.return_value = {
            "SecretString": json.dumps(self.secret)
        }
        response = self.response({})
        response.read.return_value = b'{"balance": NaN}'
        self.assertTrue(self.call("getAccounts", {"item": "usaa"})["isError"])

    def test_recurring_error_explains_entitlement_without_raw_description(self):
        self.response(
            {
                "error_code": "PRODUCT_NOT_READY",
                "request_id": "safe",
                "error_message": "synthetic-secret",
            },
            400,
        )
        result = self.call("getRecurringTransactions", {"item": "usaa"})
        self.assertIn("entitlement", json.dumps(result))
        self.assertNotIn("synthetic-secret", json.dumps(result))

    def test_output_expansion_and_deep_input_fail_safely(self):
        self.secret["secret"] = "x"
        self.store.get_secret_value.return_value = {
            "SecretString": json.dumps(self.secret)
        }
        self.response({"unexpected": "x" * 200000})
        self.assertTrue(self.call("getAccounts", {"item": "usaa"})["isError"])
        nested = []
        for _ in range(1100):
            nested = [nested]
        self.store.reset_mock()
        self.assertTrue(self.call("getAccounts", {"item": nested})["isError"])
        self.store.get_secret_value.assert_not_called()

    def test_invalid_arguments_fail_before_secret_lookup(self):
        cases = [
            ("unknown", {}),
            ("listItems", {"url": "https://evil.test"}),
            ("getAccounts", {}),
            ("getAccounts", {"item": True}),
            ("getAccounts", {"item": "unknown"}),
            ("getAccounts", {"item": "usaa", "secret": "x"}),
            (
                "getTransactions",
                {"item": "usaa", "startDate": "2026-02-30", "endDate": "2026-03-01"},
            ),
            (
                "getTransactions",
                {"item": "usaa", "startDate": "2026-03-02", "endDate": "2026-03-01"},
            ),
            (
                "getTransactions",
                {"item": "usaa", "startDate": "20260301", "endDate": "2026-03-02"},
            ),
        ]
        for key, values in [
            ("count", True),
            ("count", 0),
            ("count", 501),
            ("count", "1"),
            ("offset", -1),
            ("offset", False),
        ]:
            cases.append(
                (
                    "getTransactions",
                    {
                        "item": "usaa",
                        "startDate": "2026-03-01",
                        "endDate": "2026-03-02",
                        key: values,
                    },
                )
            )
        cases.extend([("getAccounts", []), ("getAccounts", {"item": "x" * 20000})])
        for tool, args in cases:
            with self.subTest(tool=tool, args=args):
                self.assertTrue(self.call(tool, args)["isError"])
        self.store.get_secret_value.assert_not_called()
        self.opener.assert_not_called()

    def test_invalid_secret_is_safe_and_never_calls_provider(self):
        for value in [
            None,
            {},
            {**self.secret, "extra": "synthetic-secret"},
            {**self.secret, "client_id": 12},
            {**self.secret, "items": {"usaa": {"access_token": "x"}}},
        ]:
            self.store.get_secret_value.return_value = {
                "SecretString": json.dumps(value)
            }
            result = self.call("listItems")
            self.assertTrue(result["isError"])
            self.assertNotIn("synthetic", json.dumps(result))
        self.opener.assert_not_called()

    def test_list_items_is_local_discovery_without_credentials(self):
        result = self.call("listItems")
        self.assertEqual(len(result["items"]), 4)
        self.assertEqual(result["items"][0]["alias"], "capital-one")
        self.assertEqual(result["items"][0]["products"], ["transactions"])
        for value in ["synthetic-token", "synthetic-client", "synthetic-secret"]:
            self.assertNotIn(value, json.dumps(result))
        self.opener.assert_not_called()
        self.store.get_secret_value.assert_called_once_with(SecretId="synthetic-arn")


if __name__ == "__main__":
    unittest.main()
