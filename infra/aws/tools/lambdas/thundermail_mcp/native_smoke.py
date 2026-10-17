"""Exercise the packaged production bootstrap, invalid calls only, no AWS/mail.

Run on an ARM64 Docker host. This is not a valid production read proof; that
source gate unconditionally blocks publication pending independent review.
"""

import http.server
import json
import subprocess
import sys
import threading
import time

CASES = [
    ("imap_list_mailboxes", {"account": "forbidden"}),
    ("imap_search_messages", {"mailbox": "INBOX", "smtp": True}),
    ("imap_get_message", {"mailbox": "INBOX", "uid": 0, "uid_validity": 1}),
    ("imap_delete_message", {}),
]


def check_image_permissions(image):
    user = subprocess.check_output(
        ["docker", "image", "inspect", "--format", "{{.Config.User}}", image],
        text=True,
    ).strip()
    assert user == "10001:10001", f"unexpected default image user: {user!r}"
    # Exercise the default user and a different UID, as Lambda can assign its own.
    for override in ([], ["--user", "10002:10002"]):
        subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--network=none",
                "--read-only",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges",
                *override,
                "--entrypoint",
                "/bin/sh",
                image,
                "-c",
                'test "$(id -u)" != 0 '
                "&& test -x /var/runtime/bootstrap "
                "&& test -r /usr/share/licenses/thundermail/LICENSE.upstream "
                "&& test -r /usr/share/licenses/thundermail/extraction.json",
            ],
            check=True,
            timeout=15,
        )


def main(image):
    check_image_permissions(image)
    responses = []
    errors = []
    completed = threading.Event()
    sent = 0

    class RuntimeAPI(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            nonlocal sent
            if sent >= len(CASES):
                completed.wait(15)
                self.send_error(503)
                return
            name, arguments = CASES[sent]
            request_id = str(sent)
            sent += 1
            body = json.dumps(arguments).encode()
            self.send_response(200)
            for key, value in {
                "Lambda-Runtime-Aws-Request-Id": request_id,
                "Lambda-Runtime-Deadline-Ms": str(int(time.time() * 1000) + 10000),
                "Lambda-Runtime-Invoked-Function-Arn": (
                    "arn:aws:lambda:us-east-1:000000000000:function:fixture"
                ),
                "Lambda-Runtime-Client-Context": json.dumps(
                    {"custom": {"bedrockAgentCoreToolName": "thundermail___" + name}}
                ),
                "Content-Length": str(len(body)),
            }.items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            try:
                result = json.loads(
                    self.rfile.read(int(self.headers["Content-Length"]))
                )
                assert (
                    self.path
                    == f"/2018-06-01/runtime/invocation/{len(responses)}/response"
                )
                assert result["isError"] is True
                assert "statusCode" not in result and "jsonrpc" not in result
                responses.append(result)
                self.send_response(202)
                self.send_header("Content-Length", "0")
                self.end_headers()
            except Exception as error:
                errors.append(repr(error))
                completed.set()
                self.send_error(500)
            if len(responses) == len(CASES):
                completed.set()

    with http.server.HTTPServer(("127.0.0.1", 0), RuntimeAPI) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        name = "thundermail-native-smoke"
        process = subprocess.Popen(
            [
                "docker",
                "run",
                "--rm",
                "--name",
                name,
                "--network",
                "host",
                "--read-only",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges",
                "--env",
                f"AWS_LAMBDA_RUNTIME_API=127.0.0.1:{server.server_port}",
                "--env",
                "AWS_LAMBDA_FUNCTION_NAME=fixture",
                "--env",
                "AWS_LAMBDA_FUNCTION_MEMORY_SIZE=128",
                "--env",
                "AWS_LAMBDA_FUNCTION_VERSION=$LATEST",
                image,
            ]
        )
        try:
            assert completed.wait(30), "bootstrap Runtime API fixture timed out"
            assert not errors, errors
            assert len(responses) == len(CASES)
        finally:
            subprocess.run(
                ["docker", "rm", "--force", name], check=False, capture_output=True
            )
            process.wait(timeout=10)
            server.shutdown()
    print(
        json.dumps(
            {
                "production_bootstrap_invalid_calls": len(responses),
                "valid_mail_reads": 0,
                "cloud_calls": False,
            }
        )
    )


if __name__ == "__main__":
    main(sys.argv[1])
