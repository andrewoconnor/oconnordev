"""Tests for prior-secret and API-key read/write behavior."""

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
    "API_KEY_PARAMETER_NAME": "api-key-parameter",
    "TOKEN_SECRET_ID": "session-token-secret",
    "GRAPHQL_ENDPOINT": "https://example.invalid/graphql",
    "VERIFY_ENDPOINT": "https://example.invalid/mcp",
    "VERIFY_EXPECTED_TOOLS_JSON": '["discover", "provider", "query"]',
}


def jwt_with_claims(**claims):
    import base64

    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"e30.{payload}.signature"


def load_rotation_module():
    boto3_stub = types.ModuleType("boto3")
    boto3_stub.__dict__["client"] = Mock()
    spec = importlib.util.spec_from_file_location(
        "rot_secret_under_test", ROTATION_MODULE
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load Lambda module")
    module = importlib.util.module_from_spec(spec)
    with (
        patch.dict(os.environ, TEST_ENV),
        patch.dict(sys.modules, {"boto3": boto3_stub}),
    ):
        spec.loader.exec_module(module)
    return module


class SessionTokenSecretTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rotation = load_rotation_module()

    def setUp(self):
        self.secrets = Mock()
        self.ssm = Mock()
        self.ssm.get_parameter.return_value = {
            "Parameter": {
                "Value": json.dumps(
                    {"api_key_id": "test-id", "api_key_secret": "test-secret"}
                )
            }
        }
        self.cloudwatch = Mock()
        self.rotation.boto3.client = Mock(
            side_effect=lambda service, **kwargs: {
                "secretsmanager": self.secrets,
                "ssm": self.ssm,
                "cloudwatch": self.cloudwatch,
            }[service]
        )
        self.new_token = jwt_with_claims(iat=900, exp=2000)
        self.previous_token = jwt_with_claims(iat=800, exp=2000)
        self.previous_secret_error = None

        def get_secret_value(*, SecretId):
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

    def test_api_key_is_read_from_ssm_only(self):
        self.run_successful_rotation()
        self.ssm.get_parameter.assert_called_once_with(
            Name="api-key-parameter", WithDecryption=True
        )
        self.secrets.get_secret_value.assert_called_once_with(
            SecretId="session-token-secret"
        )

    def test_changed_expiry_is_reported_as_observed_data(self):
        self.previous_token = jwt_with_claims(iat=800, exp=1500)

        result = self.run_successful_rotation()

        self.assertTrue(result["expiry_changed"])

    def test_missing_previous_secret_allows_initial_publish(self):
        class SecretNotFoundError(RuntimeError):
            response = {"Error": {"Code": "ResourceNotFoundException"}}

        self.previous_secret_error = SecretNotFoundError("no current version")

        result = self.run_successful_rotation()

        self.assertFalse(result["token_unchanged"])
        self.secrets.put_secret_value.assert_called_once()

    def test_previous_secret_read_failure_stops_rotation(self):
        self.previous_secret_error = RuntimeError("not available")

        with (
            patch.object(self.rotation.time, "time", return_value=1000),
            patch.object(self.rotation, "_mint", return_value=self.new_token),
            patch.object(self.rotation, "_log"),
            self.assertRaisesRegex(
                self.rotation.RotationError, "token_secret_read_failed"
            ),
        ):
            self.rotation.handler({}, None)

        self.secrets.put_secret_value.assert_not_called()
        self.cloudwatch.put_metric_data.assert_not_called()

    def test_malformed_previous_token_has_unknown_expiry(self):
        self.previous_token = "not-a-jwt"

        result = self.run_successful_rotation()

        self.assertFalse(result["expiry_changed"])

    def test_api_key_read_failure_stops_before_minting_or_writing(self):
        self.ssm.get_parameter.side_effect = RuntimeError("secret read failed")
        mint = Mock()

        with (
            patch.object(self.rotation, "_mint", mint),
            patch.object(self.rotation, "_log"),
            self.assertRaisesRegex(RuntimeError, "secret read failed"),
        ):
            self.rotation.handler({}, None)

        mint.assert_not_called()
        self.secrets.put_secret_value.assert_not_called()

    def test_secret_write_failure_does_not_publish_success_metric(self):
        self.previous_token = jwt_with_claims(iat=800, exp=1900)
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
