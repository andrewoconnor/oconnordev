"""Unit tests for Spacelift session-token rotation and expiry windows."""

import base64
import importlib.util
import json
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROTATION_MODULE = Path(__file__).resolve().with_name("spacelift_session_token.py")
TEST_ENV = {
    "API_KEY_SECRET_ID": "api-key-secret",
    "TOKEN_SECRET_ID": "session-token-secret",
    "GRAPHQL_ENDPOINT": "https://example.invalid/graphql",
    "METRIC_NAMESPACE": "Test/SpaceliftAuth",
    "METRIC_REMAINING": "SessionTokenRemainingSeconds",
}


def jwt_with_claims(**claims):
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"e30.{payload}.signature"


def load_rotation_module():
    boto3_stub = types.ModuleType("boto3")
    boto3_stub.client = Mock()
    spec = importlib.util.spec_from_file_location(
        "spacelift_session_token_under_test", ROTATION_MODULE
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load rotation module from {ROTATION_MODULE}")
    module = importlib.util.module_from_spec(spec)
    with (
        patch.dict(os.environ, TEST_ENV),
        patch.dict(sys.modules, {"boto3": boto3_stub}),
    ):
        spec.loader.exec_module(module)
    return module


class SessionTokenRotationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rotation = load_rotation_module()

    def setUp(self):
        self.secrets = Mock()
        self.cloudwatch = Mock()
        self.rotation.boto3.client = Mock(
            side_effect=lambda service, **kwargs: {
                "secretsmanager": self.secrets,
                "cloudwatch": self.cloudwatch,
            }[service]
        )
        self.new_token = jwt_with_claims(iat=900, exp=2000)
        self.previous_token = jwt_with_claims(iat=800, exp=2000)
        self.previous_secret_error = None

        def get_secret_value(*, SecretId):
            if SecretId == "api-key-secret":
                return {
                    "SecretString": json.dumps(
                        {"api_key_id": "test-id", "api_key_secret": "test-secret"}
                    )
                }
            if self.previous_secret_error:
                raise self.previous_secret_error
            return {"SecretString": json.dumps({"token": self.previous_token})}

        self.secrets.get_secret_value.side_effect = get_secret_value

    def run_successful_rotation(self):
        with (
            patch.object(self.rotation.time, "time", return_value=1000),
            patch.object(self.rotation, "_mint", return_value=self.new_token),
            patch.object(self.rotation, "_verify", return_value=["query"]),
            patch.object(self.rotation, "_log"),
        ):
            return self.rotation.handler({}, None)

    def test_same_expiry_means_the_existing_ten_hour_window_did_not_roll(self):
        result = self.run_successful_rotation()

        self.assertEqual(result["exp"], 2000)
        self.assertEqual(result["remaining_seconds"], 1000)
        self.assertFalse(result["window_rolled"])
        self.secrets.put_secret_value.assert_called_once_with(
            SecretId="session-token-secret",
            SecretString=json.dumps({"token": self.new_token}),
        )

    def test_unchanged_expiry_after_window_expiration_is_reported_as_stale(self):
        self.new_token = jwt_with_claims(iat=800, exp=950)
        self.previous_token = jwt_with_claims(iat=700, exp=950)

        result = self.run_successful_rotation()

        self.assertEqual(result["remaining_seconds"], -50)
        self.assertFalse(result["window_rolled"])

    def test_changed_expiry_marks_a_new_upstream_window(self):
        self.previous_token = jwt_with_claims(iat=800, exp=1500)

        result = self.run_successful_rotation()

        self.assertTrue(result["window_rolled"])

    def test_unreadable_previous_token_does_not_block_rotation(self):
        self.previous_secret_error = RuntimeError("not available")

        result = self.run_successful_rotation()

        self.assertFalse(result["window_rolled"])
        self.secrets.put_secret_value.assert_called_once()

    def test_malformed_previous_token_is_treated_as_unknown_window(self):
        self.previous_token = "not-a-jwt"

        result = self.run_successful_rotation()

        self.assertFalse(result["window_rolled"])

    def test_api_key_read_failure_stops_before_minting_or_writing(self):
        self.secrets.get_secret_value.side_effect = RuntimeError("secret read failed")
        mint = Mock()

        with (
            patch.object(self.rotation, "_mint", mint),
            patch.object(self.rotation, "_log"),
            self.assertRaisesRegex(RuntimeError, "secret read failed"),
        ):
            self.rotation.handler({}, None)

        mint.assert_not_called()
        self.secrets.put_secret_value.assert_not_called()

    def test_minted_token_without_expiry_is_not_published(self):
        token_without_exp = jwt_with_claims(iat=900)

        with (
            patch.object(self.rotation, "_mint", return_value=token_without_exp),
            patch.object(self.rotation, "_log"),
            self.assertRaisesRegex(
                self.rotation.RotationError, "minted_token_missing_exp"
            ),
        ):
            self.rotation.handler({}, None)

        self.secrets.put_secret_value.assert_not_called()

    def test_verification_failure_is_not_published(self):
        with (
            patch.object(self.rotation.time, "time", return_value=1000),
            patch.object(self.rotation, "_mint", return_value=self.new_token),
            patch.object(
                self.rotation,
                "_verify",
                side_effect=self.rotation.RotationError("verify_http_403"),
            ),
            patch.object(self.rotation, "_log"),
            self.assertRaisesRegex(self.rotation.RotationError, "verify_http_403"),
        ):
            self.rotation.handler({}, None)

        self.secrets.put_secret_value.assert_not_called()

    def test_secret_write_failure_propagates_and_does_not_publish_success_metric(self):
        self.secrets.put_secret_value.side_effect = RuntimeError("secret write failed")

        with (
            patch.object(self.rotation.time, "time", return_value=1000),
            patch.object(self.rotation, "_mint", return_value=self.new_token),
            patch.object(self.rotation, "_verify", return_value=["query"]),
            patch.object(self.rotation, "_log"),
            self.assertRaisesRegex(RuntimeError, "secret write failed"),
        ):
            self.rotation.handler({}, None)

        self.cloudwatch.put_metric_data.assert_not_called()


if __name__ == "__main__":
    unittest.main()
