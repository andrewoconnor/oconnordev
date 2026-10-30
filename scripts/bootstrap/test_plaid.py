import importlib.util
import unittest
from pathlib import Path


class ImportTests(unittest.TestCase):
    def test_builds_private_bundle_without_losing_existing_items(self):
        path = Path(__file__).with_name("plaid.py")
        self.assertTrue(path.exists(), "Repo-managed Plaid bootstrap is missing")
        spec = importlib.util.spec_from_file_location("plaid_bootstrap", path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        old = {
            "client_id": "test-client",
            "secret": "test-secret",
            "items": {
                "usaa": {
                    "access_token": "test-existing",
                    "institution_name": "USAA",
                    "products": ["transactions"],
                }
            },
        }
        items = [
            {
                "institution_name": "Capital One",
                "institution_id": "ins_test",
                "access_token": "test-token",
                "products": ["transactions"],
            }
        ]
        bundle = module.build_bundle(items, "test-client", "test-secret", old)
        self.assertEqual(set(bundle["items"]), {"usaa", "capital-one"})
        self.assertEqual(bundle["items"]["capital-one"]["access_token"], "test-token")
        self.assertEqual(old["items"]["usaa"]["access_token"], "test-existing")

    def test_rejects_duplicate_alias_and_invalid_products(self):
        spec = importlib.util.spec_from_file_location(
            "plaid_bootstrap", Path(__file__).with_name("plaid.py")
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        item = {
            "institution_name": "Capital One",
            "access_token": "test-token",
            "products": ["transactions"],
        }
        with self.assertRaises(ValueError):
            module.build_bundle([item, item], "test-client", "test-secret")
        for products in [
            [],
            "transactions",
            ["transfer"],
            ["transactions", "auth"],
            ["transactions_recurring"],
            ["transactions", "transactions"],
        ]:
            with self.subTest(products=products), self.assertRaises(ValueError):
                module.build_bundle(
                    [{**item, "products": products}], "test-client", "test-secret"
                )

    def test_import_is_dry_run_by_default_and_apply_reads_back(self):
        spec = importlib.util.spec_from_file_location(
            "plaid_bootstrap", Path(__file__).with_name("plaid.py")
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        item = {
            "institution_name": "Capital One",
            "access_token": "test-token",
            "products": ["transactions"],
        }

        class FakeSecrets:
            value = {"client_id": "test-client", "secret": "test-secret", "items": {}}
            writes = 0

            def get_secret_value(self, **kwargs):
                import json

                return {"SecretString": json.dumps(self.value)}

            def put_secret_value(self, **kwargs):
                import json

                self.value = json.loads(kwargs["SecretString"])
                self.writes += 1

        fake = FakeSecrets()
        preview = module.import_items(
            fake, "/hermes/plaid/credentials", [item], "test-client", "test-secret"
        )
        self.assertEqual(fake.writes, 0)
        self.assertNotIn("test-token", str(preview))
        applied = module.import_items(
            fake,
            "/hermes/plaid/credentials",
            [item],
            "test-client",
            "test-secret",
            apply=True,
        )
        self.assertEqual(fake.writes, 1)
        self.assertTrue(applied["verified"])
        module.import_items(
            fake,
            "/hermes/plaid/credentials",
            [item],
            "test-client",
            "test-secret",
            apply=True,
        )
        self.assertEqual(fake.writes, 1)

    def test_cli_help_runs_without_credentials_and_private_files(self):
        import os
        import subprocess
        import sys

        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("PLAID_", "AWS_"))
        }
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).resolve().with_name("plaid.py")),
                    "--help",
                ],
                capture_output=True,
                text=True,
                env=env,
                cwd=directory,
                check=False,
            )
        self.assertEqual(result.returncode, 0)
        self.assertIn("--apply", result.stdout)
        self.assertIn("verify", result.stdout)

    def test_existing_institutions_match_gateway_aliases(self):
        spec = importlib.util.spec_from_file_location(
            "plaid_bootstrap", Path(__file__).with_name("plaid.py")
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        items = [
            {
                "institution_name": name,
                "access_token": "test-token",
                "products": ["transactions"],
            }
            for name in [
                "USAA",
                "Capital One",
                "American Express",
                "Empower Retirement",
            ]
        ]
        bundle = module.build_bundle(items, "test-client", "test-secret")
        self.assertEqual(
            set(bundle["items"]), {"usaa", "capital-one", "amex", "empower"}
        )

    def test_rejects_invalid_preserved_records_before_write(self):
        spec = importlib.util.spec_from_file_location(
            "plaid_bootstrap", Path(__file__).with_name("plaid.py")
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        incoming = {
            "institution_name": "USAA",
            "access_token": "test-usaa",
            "products": ["transactions"],
        }
        valid = {
            "client_id": "test-client",
            "secret": "test-secret",
            "items": {
                "amex": {
                    "institution_name": "American Express",
                    "access_token": "test-amex",
                    "products": ["transactions"],
                }
            },
        }
        import copy

        for broken in [
            "extra-item-field",
            "extra-root-field",
            "bad-product",
            "unknown-alias",
        ]:
            old = copy.deepcopy(valid)
            if broken == "extra-item-field":
                old["items"]["amex"]["extra"] = "invalid"
            if broken == "extra-root-field":
                old["extra"] = "invalid"
            if broken == "bad-product":
                old["items"]["amex"]["products"] = ["transfer"]
            if broken == "unknown-alias":
                old["items"]["unknown"] = old["items"].pop("amex")
            with self.subTest(broken=broken), self.assertRaises(ValueError):
                module.build_bundle([incoming], "test-client", "test-secret", old)

    def test_bundle_parser_rejects_duplicate_keys_and_nonfinite_values(self):
        from unittest.mock import Mock

        spec = importlib.util.spec_from_file_location(
            "plaid_bootstrap", Path(__file__).with_name("plaid.py")
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for raw in [
            '{"items":{},"items":{}}',
            '{"items":{"usaa":{"products":[],"products":[]}}}',
            '{"items":NaN}',
            '{"items":Infinity}',
        ]:
            client = Mock()
            client.get_secret_value.return_value = {"SecretString": raw}
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                module.read_bundle(client, "/hermes/plaid/credentials")
            client.put_secret_value.assert_not_called()


if __name__ == "__main__":
    unittest.main()
