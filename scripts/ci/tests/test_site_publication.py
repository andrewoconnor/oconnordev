"""Execute publication Bash and the real AWS CLI deletion planner offline."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[3]


class SitePublicationTests(unittest.TestCase):
    def test_cp_once_and_real_size_only_sync_deletes_only_stale_root(self):
        aws = shutil.which("aws")
        self.assertIsNotNone(
            aws, "Run with mise exec so the pinned AWS CLI is available"
        )
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            dist = directory / "dist"
            files = {
                "index.html": "tested html",
                "styles.css": "stable css",
                "assets/main-ABCDEFGH.js": "hashed js",
                "assets/main-unhashed.js": "mutable js",
                "assets/css/resume-" + "a" * 64 + ".css": "hashed css",
                "assets/question-image.svg": "mutable image",
                "assets/basis-1.50.0-no-eval/basis_transcoder.js": "mutable runtime",
            }
            for name, data in files.items():
                path = dist / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(data)
            calls = directory / "calls.jsonl"
            objects = directory / "objects.json"
            objects.write_text(
                json.dumps(
                    {
                        "stale.html": 10,
                        "build-meta.json": 20,
                        "assets/main-OLDHASH1.js": 30,
                        "images/globe/earthmap2k.ktx2": 40,
                    }
                )
            )

            class S3Listing(BaseHTTPRequestHandler):
                def do_GET(self):
                    contents = "".join(
                        "<Contents><Key>" + escape(key) + "</Key>"
                        "<LastModified>2020-01-01T00:00:00.000Z</LastModified>"
                        '<ETag>"test"</ETag><Size>' + str(size) + "</Size>"
                        "<StorageClass>STANDARD</StorageClass></Contents>"
                        for key, size in sorted(json.loads(objects.read_text()).items())
                    )
                    body = (
                        "<ListBucketResult "
                        'xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
                        "<Name>test-site</Name><Prefix></Prefix><KeyCount>20</KeyCount>"
                        "<MaxKeys>1000</MaxKeys><IsTruncated>false</IsTruncated>"
                        + contents
                        + "</ListBucketResult>"
                    ).encode()
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)

                def log_message(self, *args):
                    pass

            server = ThreadingHTTPServer(("127.0.0.1", 0), S3Listing)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                recorder = directory / "aws"
                recorder.write_text(
                    f"#!{sys.executable}\n"
                    "import json, os, pathlib, subprocess, sys\n"
                    "args = sys.argv[1:]\n"
                    "with open(os.environ['CALLS'], 'a') as file:\n"
                    " file.write(json.dumps(args) + '\n')\n".replace("'\n'", "'\\n'")
                    + "if args[:2] == ['s3', 'cp']:\n"
                    " path = pathlib.Path(os.environ['OBJECTS'])\n"
                    " objects = json.loads(path.read_text())\n"
                    " key = args[3].split('/', 3)[3]\n"
                    " objects[key] = pathlib.Path(args[2]).stat().st_size\n"
                    " path.write_text(json.dumps(objects))\n"
                    "else:\n"
                    " assert args[:2] == ['s3', 'sync']\n"
                    " result = subprocess.run([os.environ['REAL_AWS'], "
                    "*args, '--dryrun', '--no-sign-request', "
                    "'--endpoint-url', os.environ['ENDPOINT']], "
                    "capture_output=True, text=True)\n"
                    " pathlib.Path(os.environ['SYNC_OUTPUT']).write_text("
                    "result.stdout + result.stderr)\n"
                    " sys.exit(result.returncode)\n"
                )
                recorder.chmod(0o700)
                output = directory / "sync.txt"
                result = subprocess.run(
                    [
                        "bash",
                        str(ROOT / "scripts/ci/publish_site.sh"),
                        str(dist),
                        "test-site",
                    ],
                    env=dict(
                        os.environ,
                        PATH=f"{directory}:{os.environ['PATH']}",
                        CALLS=str(calls),
                        OBJECTS=str(objects),
                        REAL_AWS=aws,
                        ENDPOINT=f"http://127.0.0.1:{server.server_port}",
                        SYNC_OUTPUT=str(output),
                        AWS_EC2_METADATA_DISABLED="true",
                        AWS_DEFAULT_REGION="us-east-1",
                        AWS_CONFIG_FILE=os.devnull,
                        AWS_SHARED_CREDENTIALS_FILE=os.devnull,
                    ),
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                recorded = [json.loads(line) for line in calls.read_text().splitlines()]
                uploads = [call for call in recorded if call[1] == "cp"]
                self.assertEqual(len(uploads), len(files))
                self.assertEqual(len({call[3] for call in uploads}), len(files))
                for call in uploads:
                    key = call[3].split("/", 3)[3]
                    expected = (
                        "public,max-age=31536000,immutable"
                        if key
                        in (
                            "assets/main-ABCDEFGH.js",
                            "assets/css/resume-" + "a" * 64 + ".css",
                        )
                        else "public,max-age=0,must-revalidate"
                    )
                    self.assertEqual(
                        call[call.index("--cache-control") + 1], expected, key
                    )
                planned = output.read_text()
                self.assertNotIn("upload:", planned)
                self.assertIn("delete: s3://test-site/stale.html", planned)
                self.assertIn("delete: s3://test-site/build-meta.json", planned)
                self.assertNotIn("OLDHASH1", planned)
                self.assertNotIn("earthmap2k", planned)
            finally:
                server.shutdown()
                server.server_close()
                thread.join()
