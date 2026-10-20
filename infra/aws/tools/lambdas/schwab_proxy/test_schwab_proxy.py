import io
import unittest
import urllib.error
from email.message import Message

import schwab_proxy


def event(path, method="GET", query="", authorization="Bearer t"):
    headers = {"Authorization": authorization, "Content-Type": "application/json"}
    return {
        "rawPath": path,
        "rawQueryString": query,
        "headers": headers,
        "requestContext": {"http": {"method": method}},
    }


class Response(io.BytesIO):
    status = 200
    headers = Message()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class SchwabProxyTests(unittest.TestCase):
    def test_forwards_get_without_content_type(self):
        sent = []

        def opener(request, timeout):
            sent.append(request)
            return Response(b'{"ok": true}')

        result = schwab_proxy.handle(
            event("/marketdata/v1/quotes", query="symbols=SPCX&fields=quote"), opener
        )
        self.assertEqual(result["statusCode"], 200)
        self.assertEqual(result["body"], '{"ok": true}')
        request = sent[0]
        self.assertEqual(
            request.full_url,
            "https://api.schwabapi.com/marketdata/v1/quotes?symbols=SPCX&fields=quote",
        )
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(request.get_header("Authorization"), "Bearer t")
        self.assertEqual(request.get_header("Accept"), "application/json")
        self.assertIsNone(request.get_header("Content-type"))

    def test_rejects_writes_other_paths_and_missing_tokens_without_calls(self):
        calls = []
        for bad, status in [
            (event("/trader/v1/accounts/abc/orders", method="POST"), 403),
            (event("/trader/v1/orders"), 403),
            (event("/marketdata/v1/../../trader/v1/orders"), 403),
            (event("//evil.example/x"), 403),
            (event("/marketdata/v1/quotes", authorization=""), 401),
        ]:
            result = schwab_proxy.handle(bad, lambda *a, **k: calls.append(a))
            self.assertEqual(result["statusCode"], status)
        self.assertEqual(calls, [])

    def test_passes_schwab_errors_through(self):
        def opener(request, timeout):
            raise urllib.error.HTTPError(
                request.full_url, 401, "Unauthorized", Message(), io.BytesIO(b"expired")
            )

        result = schwab_proxy.handle(event("/trader/v1/accounts"), opener)
        self.assertEqual((result["statusCode"], result["body"]), (401, "expired"))
