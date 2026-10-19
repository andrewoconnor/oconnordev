import importlib.util
import json
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location(
    "oauth_consent", ROOT / "scripts/bootstrap/oauth/consent.py"
)
consent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(consent)

ELICITATION = {
    "jsonrpc": "2.0",
    "id": 2,
    "error": {
        "code": -32042,
        "message": "Authorization required",
        "data": {
            "elicitations": [
                {
                    "mode": "url",
                    "elicitationId": "e1",
                    "url": "https://bedrock-agentcore.us-east-1.amazonaws.com/identities/oauth2/authorize?request_uri=x",
                }
            ]
        },
    },
}


class OAuthConsentTests(unittest.TestCase):
    def test_reads_json_and_event_stream_responses(self):
        body = json.dumps(ELICITATION).encode()
        self.assertEqual(consent.messages(body, "application/json"), [ELICITATION])
        stream = b"event: message\ndata: " + body + b"\n\n"
        self.assertEqual(consent.messages(stream, "text/event-stream"), [ELICITATION])

    def test_finds_only_https_url_elicitations(self):
        self.assertTrue(consent.elicitation_url([ELICITATION]).startswith("https://"))
        for other in [
            {"jsonrpc": "2.0", "id": 2, "result": {"content": []}},
            {
                "error": {
                    "code": -32042,
                    "data": {"elicitations": [{"mode": "url", "url": "http://x"}]},
                }
            },
        ]:
            self.assertIsNone(consent.elicitation_url([other]))

    def test_finds_authorize_url_in_other_response_shapes(self):
        url = ELICITATION["error"]["data"]["elicitations"][0]["url"]
        text_result = {
            "result": {
                "isError": True,
                "content": [{"type": "text", "text": f"Visit {url}"}],
            }
        }
        self.assertEqual(consent.elicitation_url([text_result]), url)

    def test_success_requires_a_non_error_result(self):
        self.assertTrue(consent.succeeded([{"result": {"content": []}}]))
        for failed in [
            [ELICITATION],
            [{"result": {"isError": True, "content": []}}],
            [{"error": {"code": -32601, "message": "Method not found"}}],
            [],
        ]:
            self.assertFalse(consent.succeeded(failed))

    def test_callback_returns_session_id_and_rejects_other_paths(self):
        with mock.patch.object(consent, "PORT", 0):
            original = consent.http.server.HTTPServer
            servers = []

            def capture(*args, **kwargs):
                server = original(*args, **kwargs)
                servers.append(server)
                return server

            with mock.patch.object(consent.http.server, "HTTPServer", capture):
                result = {}
                worker = threading.Thread(
                    target=lambda: result.update(id=consent.wait_for_session_id())
                )
                worker.start()
                while not servers:
                    time.sleep(0.01)
                port = servers[0].server_address[1]
                with self.assertRaises(urllib.error.HTTPError):
                    urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/other?session_id=a"
                    )
                urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/oauth2/callback?session_id=urn%3Aabc"
                )
                worker.join(5)
        self.assertEqual(result["id"], "urn:abc")
