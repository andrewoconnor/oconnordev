"""New native read proof, not a repeat of prior transport-only cases.
Adapted synthetic IMAP state model from thundermail-lambda-mail/synthetic-imap.py.
Only cfg(test) Rust worker permits plaintext loopback; production never does.
"""

import hashlib
import http.server
import json
import pathlib
import socketserver
import subprocess
import sys
import threading
import time

ROOT = pathlib.Path(__file__).resolve().parent
BASE = pathlib.Path(
    sys.argv[2]
).resolve()  # explicit isolated proof/cache root, never repository home
OUTPUT = (
    pathlib.Path(sys.argv[3]).resolve()
    if len(sys.argv) > 3
    else BASE / "production-evidence"
)
OUTPUT.mkdir(parents=True, exist_ok=True)
assert not OUTPUT.is_relative_to(ROOT), "evidence must remain outside delivery source"
binary = pathlib.Path(sys.argv[1]).resolve()
commands = []
seen = False
results = []
errors = []
sent = 0
done = threading.Event()
message = (
    b"From: sender@example.invalid\r\nSubject: Synthetic native Rust\r\n"
    b"\r\nLoopback fixture only.\r\n"
)
cases = [
    ("imap_list_mailboxes", {}),
    ("imap_search_messages", {"mailbox": "INBOX"}),
    (
        "imap_get_message",
        {"mailbox": "INBOX", "uid": 1, "uid_validity": 1, "max_bytes": 1024},
    ),
]


class IMAP(socketserver.StreamRequestHandler):
    def handle(self):
        global seen
        self.wfile.write(b"* OK synthetic only\r\n")
        while line := self.rfile.readline(8192):
            text = line.decode().strip()
            fields = text.split()
            tag = fields[0]
            cmd = fields[1].upper()
            commands.append(
                "LOGIN <synthetic-redacted>" if cmd == "LOGIN" else " ".join(fields[1:])
            )

            def send(s):
                self.wfile.write(s.encode() + b"\r\n")

            if cmd == "LOGIN":
                assert "oconnor@thundermail.com" in text
            elif cmd == "LIST":
                send('* LIST () "/" "INBOX"')
            elif cmd in ("SELECT", "EXAMINE"):
                if cmd == "SELECT":
                    seen = True
                send("* FLAGS (\\Seen)")
                send("* 1 EXISTS")
                send("* OK [UIDVALIDITY 1] stable")
            elif cmd == "UID" and fields[2].upper() == "SEARCH":
                send("* SEARCH 1")
            elif cmd == "UID" and fields[2].upper() == "FETCH":
                if "BODY.PEEK[]<0.1024>" not in text.upper():
                    seen = True
                flags = b"\\Seen" if seen else b""
                self.wfile.write(
                    b"* 1 FETCH (UID 1 FLAGS ("
                    + flags
                    + b") BODY[]<0> {"
                    + str(len(message)).encode()
                    + b"}\r\n"
                    + message
                    + b")\r\n"
                )
            elif "STORE" in text.upper():
                seen = True
                send(tag + " BAD forbidden")
                continue
            else:
                send(tag + " BAD unsupported")
                continue
            send(tag + " OK completed")


class IMAPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class API(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        global sent
        if sent >= len(cases):
            done.wait(10)
            self.send_error(503)
            return
        try:
            assert self.path == "/2018-06-01/runtime/invocation/next"
            tool, args = cases[sent]
            request_id = str(sent)
            sent += 1
            body = json.dumps(args).encode()
            self.send_response(200)
            for key, value in {
                "Lambda-Runtime-Aws-Request-Id": request_id,
                "Lambda-Runtime-Deadline-Ms": str(int(time.time() * 1000) + 10000),
                "Lambda-Runtime-Invoked-Function-Arn": (
                    "arn:aws:lambda:us-east-1:000000000000:function:synthetic-read"
                ),
                "Lambda-Runtime-Client-Context": json.dumps(
                    {
                        "custom": {
                            "bedrockAgentCoreToolName": "thundermail___" + tool,
                            "bedrockAgentCoreMessageVersion": "1.0",
                        }
                    }
                ),
                "Content-Length": str(len(body)),
            }.items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            errors.append(repr(e))
            done.set()

    def do_POST(self):
        try:
            index = len(results)
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            assert self.path == f"/2018-06-01/runtime/invocation/{index}/response", (
                self.path
            )
            assert body["isError"] is False, body
            assert "statusCode" not in body and "jsonrpc" not in body
            assert json.loads(body["content"][0]["text"]) == body["structuredContent"]
            from mcp.types import CallToolResult

            CallToolResult.model_validate(body)
            data = body["structuredContent"]
            if index == 0:
                assert data["mailboxes"] == ["INBOX"]
            elif index == 1:
                assert data["messages"] == [
                    {"mailbox": "INBOX", "uid": 1, "uid_validity": 1}
                ]
            elif index == 2:
                assert data["raw_utf8"] == message.decode() and data[
                    "returned_bytes"
                ] == len(message)
            results.append({"tool": cases[index][0], "passed": True, "response": body})
            self.send_response(202)
            self.send_header("Content-Length", "0")
            self.end_headers()
            if len(results) == len(cases):
                done.set()
        except Exception as e:
            errors.append(repr(e))
            done.set()
            self.send_error(500)


with (
    IMAPServer(("127.0.0.1", 0), IMAP) as imap,
    http.server.HTTPServer(("127.0.0.1", 0), API) as api,
):
    for server in (imap, api):
        threading.Thread(target=server.serve_forever, daemon=True).start()
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(BASE / "home"),
        "TMPDIR": str(BASE / "tmp"),
        "THUNDERMAIL_TEST_ADDR": f"127.0.0.1:{imap.server_address[1]}",
        "AWS_LAMBDA_RUNTIME_API": f"127.0.0.1:{api.server_port}",
        "AWS_LAMBDA_FUNCTION_NAME": "synthetic-read-proof",
        "AWS_LAMBDA_FUNCTION_MEMORY_SIZE": "128",
        "AWS_LAMBDA_FUNCTION_VERSION": "$LATEST",
    }
    with (OUTPUT / "native-imap-runtime.stderr").open("w") as log:
        process = subprocess.Popen(
            [
                str(binary),
                "--exact",
                "wire_tests::native_runtime_worker",
                "--ignored",
                "--nocapture",
            ],
            env=env,
            cwd=BASE / "home",
            stdout=log,
            stderr=log,
        )
        try:
            assert done.wait(20), "native IMAP runtime did not complete"
            assert not errors, errors
            assert len(results) == len(cases)
        finally:
            process.terminate()
            process.wait(timeout=5)
    for server in (imap, api):
        server.shutdown()
assert not seen
assert any("BODY.PEEK[]<0.1024>" in c for c in commands)
assert not any(c.startswith("SELECT ") or "STORE" in c for c in commands)
result = {
    "synthetic_only": True,
    "real_aws_calls": False,
    "real_mailbox_calls": False,
    "artifact_kind": (
        "cfg(test) native Lambda worker; same handler and extracted IMAP code"
    ),
    "test_binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
    "passed": len(results),
    "seen_before": False,
    "seen_after": seen,
    "commands": commands,
    "results": results,
}
(OUTPUT / "native-imap-runtime-result.json").write_text(
    json.dumps(result, indent=2) + "\n"
)
print(json.dumps(result, indent=2))
