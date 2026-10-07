"""Regression tests for equal-expiry token verification."""

import json
import unittest
from unittest.mock import Mock, patch

from test_spacelift_session_token import jwt_with_claims, load_rotation_module


class StoredTokenVerificationTests(unittest.TestCase):
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
        self.new_token = jwt_with_claims(iat=900, exp=1010)
        self.previous_token = jwt_with_claims(iat=800, exp=1010)

        def get_secret_value(*, SecretId):
            if SecretId == "api-key-secret":
                return {
                    "SecretString": json.dumps(
                        {"api_key_id": "test-id", "api_key_secret": "test-secret"}
                    )
                }
            return {"SecretString": json.dumps({"token": self.previous_token})}

        self.secrets.get_secret_value.side_effect = get_secret_value

    def run_rotation(self, verifier_results):
        with (
            patch.object(self.rotation.time, "time", return_value=1000),
            patch.object(self.rotation, "_mint", return_value=self.new_token),
            patch.object(
                self.rotation, "_verify", side_effect=verifier_results
            ) as verify,
            patch.object(self.rotation, "_log"),
        ):
            result = self.rotation.handler({}, None)
        return result, verify

    def test_rejected_stored_token_is_replaced_at_same_expiry(self):
        for rejection in ("verify_http_401", "verify_read_http_401"):
            with self.subTest(rejection=rejection):
                self.secrets.put_secret_value.reset_mock()
                self.cloudwatch.put_metric_data.reset_mock()
                result, verify = self.run_rotation(
                    [["query"], self.rotation.RotationError(rejection)]
                )

                self.assertTrue(result["token_published"])
                self.assertEqual(verify.call_count, 2)
                self.assertEqual(verify.call_args_list[0].args[0], self.new_token)
                self.assertEqual(verify.call_args_list[1].args[0], self.previous_token)
                self.secrets.put_secret_value.assert_called_once_with(
                    SecretId="session-token-secret",
                    SecretString=json.dumps({"token": self.new_token}),
                )

    def test_transport_failure_verifying_stored_token_propagates(self):
        with self.assertRaisesRegex(
            self.rotation.RotationError, "verify_read_transport_TimeoutError"
        ):
            self.run_rotation(
                [
                    ["query"],
                    self.rotation.RotationError("verify_read_transport_TimeoutError"),
                ]
            )

        self.secrets.put_secret_value.assert_not_called()
        self.cloudwatch.put_metric_data.assert_not_called()


if __name__ == "__main__":
    unittest.main()
