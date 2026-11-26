import hashlib
import hmac
import importlib.util
import json
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock

PATH = Path(__file__).with_name("alarm_webhook.py")
URL = "https://agent.example.invalid/webhooks/aws-alarms"
SECRET = "synthetic-secret"

EVENT = {
    "id": "c4c1c1c9-6542-e61b-6ef0-8c4d36933a92",
    "detail-type": "CloudWatch Alarm State Change",
    "source": "aws.cloudwatch",
    "account": "767397796791",
    "region": "us-east-1",
    "detail": {
        "alarmName": "oconnordev-site-unhealthy",
        "state": {"value": "ALARM", "reason": "Threshold Crossed"},
        "previousState": {"value": "OK", "reason": "Threshold Crossed"},
    },
}


class AlarmWebhookTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("alarm_webhook", PATH)
        self.runtime = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.runtime)
        self.opener = MagicMock()
        self.opener.open.return_value.__enter__.return_value.status = 200

    def sent(self):
        return self.opener.open.call_args.args[0]

    def test_posts_the_alarm_fields_the_hermes_route_renders(self):
        self.runtime.handle(EVENT, URL, SECRET, self.opener, 1_800_000_000.7)
        request = self.sent()
        self.assertEqual(request.full_url, URL)
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(
            json.loads(request.data),
            {
                "AlarmName": "oconnordev-site-unhealthy",
                "NewStateValue": "ALARM",
                "OldStateValue": "OK",
                "NewStateReason": "Threshold Crossed",
                "AWSAccountId": "767397796791",
                "Region": "us-east-1",
            },
        )
        self.assertEqual(request.get_header("Content-type"), "application/json")
        self.assertEqual(request.get_header("X-request-id"), EVENT["id"])
        self.assertEqual(
            self.opener.open.call_args.kwargs["timeout"],
            self.runtime.TIMEOUT_SECONDS,
        )

    def test_signature_is_hermes_generic_v2(self):
        self.runtime.handle(EVENT, URL, SECRET, self.opener, 1_800_000_000.7)
        request = self.sent()
        timestamp = request.get_header("X-webhook-timestamp")
        self.assertEqual(timestamp, "1800000000")
        expected = hmac.new(
            SECRET.encode(), timestamp.encode() + b"." + request.data, hashlib.sha256
        ).hexdigest()
        self.assertEqual(request.get_header("X-webhook-signature-v2"), expected)
        self.assertIsNone(request.get_header("X-webhook-signature"))

    def test_secret_is_never_sent(self):
        self.runtime.handle(EVENT, URL, SECRET, self.opener, 1_800_000_000)
        request = self.sent()
        self.assertNotIn(SECRET.encode(), request.data)
        for value in request.header_items():
            self.assertNotIn(SECRET, value[1])

    def test_rejected_delivery_fails_the_invocation(self):
        self.opener.open.side_effect = urllib.error.HTTPError(
            URL, 404, "Not Found", {}, None
        )
        with self.assertRaises(urllib.error.HTTPError):
            self.runtime.handle(EVENT, URL, SECRET, self.opener, 1_800_000_000)

    def test_plain_http_is_refused_before_sending(self):
        with self.assertRaises(ValueError):
            self.runtime.handle(
                EVENT,
                "http://agent.example.invalid/webhooks/aws-alarms",
                SECRET,
                self.opener,
                1_800_000_000,
            )
        self.opener.open.assert_not_called()

    def test_redirects_are_not_followed(self):
        handler = self.runtime.NoRedirect()
        self.assertIsNone(
            handler.redirect_request(None, None, 302, "Found", {}, "https://other")
        )


if __name__ == "__main__":
    unittest.main()
