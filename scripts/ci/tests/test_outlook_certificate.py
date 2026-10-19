import base64
import datetime
import hashlib
import importlib.util
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location(
    "outlook_certificate", ROOT / "scripts/bootstrap/outlook/build_certificate.py"
)
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


@unittest.skipUnless(shutil.which("openssl"), "openssl is required")
class OutlookCertificateTests(unittest.TestCase):
    def test_certificate_is_valid_self_signed_x509_with_matching_thumbprint(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            key = directory / "key.pem"
            subprocess.run(
                [
                    "openssl",
                    "genpkey",
                    "-algorithm",
                    "RSA",
                    "-pkeyopt",
                    "rsa_keygen_bits:2048",
                    "-out",
                    str(key),
                ],
                check=True,
                capture_output=True,
            )
            spki = subprocess.run(
                ["openssl", "pkey", "-in", str(key), "-pubout", "-outform", "DER"],
                check=True,
                capture_output=True,
            ).stdout

            def sign(digest: bytes) -> bytes:
                return subprocess.run(
                    [
                        "openssl",
                        "pkeyutl",
                        "-sign",
                        "-inkey",
                        str(key),
                        "-pkeyopt",
                        "digest:sha256",
                    ],
                    input=digest,
                    check=True,
                    capture_output=True,
                ).stdout

            start = datetime.datetime(2026, 10, 19, tzinfo=datetime.UTC)
            cert = build.certificate(spki, sign, start, 3650)
            path = directory / "cert.pem"
            path.write_text(build.pem(cert))
            text = subprocess.run(
                ["openssl", "x509", "-in", str(path), "-noout", "-subject", "-enddate"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            self.assertIn("hermes-outlook-agentcore", text)
            self.assertIn("2036", text)
            verified = subprocess.run(
                [
                    "openssl",
                    "verify",
                    "-partial_chain",
                    "-CAfile",
                    str(path),
                    str(path),
                ],
                capture_output=True,
                text=True,
            )
            self.assertIn("OK", verified.stdout, verified.stderr)
            expected = base64.urlsafe_b64encode(hashlib.sha256(cert).digest()).rstrip(
                b"="
            )
            self.assertEqual(build.thumbprint(cert), expected.decode())

    def test_long_validity_switches_to_generalized_time(self):
        self.assertEqual(build.time(datetime.datetime(2049, 1, 1))[0], 0x17)
        self.assertEqual(build.time(datetime.datetime(2050, 1, 1))[0], 0x18)
