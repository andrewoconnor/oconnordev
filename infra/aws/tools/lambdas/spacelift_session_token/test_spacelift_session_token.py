"""Tests for token rotation."""

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
    "VERIFY_ENDPOINT": "https://example.invalid/mcp",
    "VERIFY_EXPECTED_TOOLS_JSON": '["discover", "provider", "query"]',
}


def jwt_with_claims(**claims):
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"e30.{payload}.signature"


def load_rotation_module():
    boto3_stub = types.ModuleType("boto3")
    boto3_stub.__dict__["client"] = Mock()
    spec = importlib.util.spec_from_file_location("rot_under_test", ROTATION_MODULE)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load Lambda module")
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

    def test_equal_expiry_is_reported_without_assuming_a_fixed_lifetime(self):
        result = self.run_successful_rotation()

        self.assertEqual(result["exp"], 2000)
        self.assertEqual(result["remaining_seconds"], 1000)
        self.assertFalse(result["expiry_changed"])
        self.secrets.put_secret_value.assert_called_once_with(
            SecretId="session-token-secret",
            SecretString=json.dumps({"token": self.new_token}),
        )

    def test_expired_minted_token_keeps_the_current_secret(self):
        self.new_token = jwt_with_claims(iat=800, exp=950)

        with (
            patch.object(self.rotation.time, "time", return_value=1000),
            patch.object(self.rotation, "_mint", return_value=self.new_token),
            patch.object(self.rotation, "_verify") as verify,
            patch.object(self.rotation, "_log"),
            self.assertRaisesRegex(self.rotation.RotationError, "minted_token_expired"),
        ):
            self.rotation.handler({}, None)

        verify.assert_not_called()
        self.secrets.put_secret_value.assert_not_called()

    def test_expiration_during_verification_prevents_publish(self):
        with (
            patch.object(self.rotation.time, "time", side_effect=[1000, 2000]),
            patch.object(self.rotation, "_mint", return_value=self.new_token),
            patch.object(self.rotation, "_verify", return_value=["query"]),
            patch.object(self.rotation, "_log"),
            self.assertRaisesRegex(self.rotation.RotationError, "minted_token_expired"),
        ):
            self.rotation.handler({}, None)

        self.secrets.put_secret_value.assert_not_called()

    def test_invalid_exp_claim_keeps_the_current_secret(self):
        for expiry in ("2000", True, float("nan"), float("inf")):
            with self.subTest(expiry=expiry):
                self.new_token = jwt_with_claims(iat=900, exp=expiry)
                with (
                    patch.object(self.rotation.time, "time", return_value=1000),
                    patch.object(self.rotation, "_mint", return_value=self.new_token),
                    patch.object(self.rotation, "_log"),
                    self.assertRaisesRegex(self.rotation.RotationError, "invalid_exp"),
                ):
                    self.rotation.handler({}, None)

                self.secrets.put_secret_value.assert_not_called()

    def test_earlier_candidate_expiry_keeps_the_current_secret(self):
        self.new_token = jwt_with_claims(iat=900, exp=1900)
        self.previous_token = jwt_with_claims(iat=800, exp=2000)

        with (
            patch.object(self.rotation.time, "time", return_value=1000),
            patch.object(self.rotation, "_mint", return_value=self.new_token),
            patch.object(self.rotation, "_log"),
            self.assertRaisesRegex(
                self.rotation.RotationError, "minted_token_expiry_regressed"
            ),
        ):
            self.rotation.handler({}, None)

        self.secrets.put_secret_value.assert_not_called()

    def test_unchanged_jwt_is_verified_without_a_secret_write(self):
        self.new_token = self.previous_token

        result = self.run_successful_rotation()

        self.assertTrue(result["token_unchanged"])
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
