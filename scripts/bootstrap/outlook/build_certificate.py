#!/usr/bin/env python3
"""Build the Outlook Entra app certificate from the KMS signing key.

Usage: build_certificate.py KMS_KEY_ARN [DAYS]

Reads the public key with kms:GetPublicKey, signs a self-signed X.509
certificate with kms:Sign, writes outlook-oauth.pem in the current directory
and prints the x5t#S256 thumbprint. The private key never leaves KMS. Needs
tools-account AWS credentials and the AWS CLI.
"""

from __future__ import annotations

import base64
import datetime
import hashlib
import json
import subprocess
import sys
from collections.abc import Callable

SHA256_WITH_RSA = "1.2.840.113549.1.1.11"
COMMON_NAME = "2.5.4.3"
SUBJECT = "hermes-outlook-agentcore"


def der(tag: int, content: bytes) -> bytes:
    size = len(content)
    if size < 0x80:
        return bytes([tag, size]) + content
    encoded = size.to_bytes((size.bit_length() + 7) // 8, "big")
    return bytes([tag, 0x80 | len(encoded)]) + encoded + content


def sequence(*items: bytes) -> bytes:
    return der(0x30, b"".join(items))


def integer(value: int) -> bytes:
    raw = value.to_bytes(value.bit_length() // 8 + 1, "big")
    return der(0x02, raw)


def oid(dotted: str) -> bytes:
    first, second, *rest = (int(part) for part in dotted.split("."))
    body = bytearray([40 * first + second])
    for number in rest:
        chunk = [number & 0x7F]
        while number > 0x7F:
            number >>= 7
            chunk.append(0x80 | (number & 0x7F))
        body.extend(reversed(chunk))
    return der(0x06, bytes(body))


def time(moment: datetime.datetime) -> bytes:
    if moment.year < 2050:
        return der(0x17, moment.strftime("%y%m%d%H%M%SZ").encode())
    return der(0x18, moment.strftime("%Y%m%d%H%M%SZ").encode())


def name(common_name: str) -> bytes:
    attribute = sequence(oid(COMMON_NAME), der(0x0C, common_name.encode()))
    return sequence(der(0x31, attribute))


def certificate(
    spki: bytes,
    sign: Callable[[bytes], bytes],
    not_before: datetime.datetime,
    days: int,
) -> bytes:
    algorithm = sequence(oid(SHA256_WITH_RSA), der(0x05, b""))
    serial = int.from_bytes(hashlib.sha256(spki).digest()[:16], "big") >> 1
    tbs = sequence(
        der(0xA0, integer(2)),
        integer(serial),
        algorithm,
        name(SUBJECT),
        sequence(time(not_before), time(not_before + datetime.timedelta(days=days))),
        name(SUBJECT),
        spki,
    )
    signature = sign(hashlib.sha256(tbs).digest())
    return sequence(tbs, algorithm, der(0x03, b"\x00" + signature))


def thumbprint(cert: bytes) -> str:
    digest = hashlib.sha256(cert).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def pem(cert: bytes) -> str:
    body = base64.b64encode(cert).decode()
    lines = [body[i : i + 64] for i in range(0, len(body), 64)]
    return (
        "-----BEGIN CERTIFICATE-----\n"
        + "\n".join(lines)
        + "\n-----END CERTIFICATE-----\n"
    )


def aws(*args: str) -> dict:
    output = subprocess.run(
        ["aws", "kms", *args, "--region", "us-east-1", "--output", "json"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return json.loads(output)


def main() -> int:
    if len(sys.argv) not in (2, 3):
        print(__doc__.strip().splitlines()[2], file=sys.stderr)
        return 2
    key = sys.argv[1]
    days = int(sys.argv[2]) if len(sys.argv) == 3 else 3650
    spki = base64.b64decode(aws("get-public-key", "--key-id", key)["PublicKey"])

    def sign(digest: bytes) -> bytes:
        response = aws(
            "sign",
            "--key-id",
            key,
            "--message-type",
            "DIGEST",
            "--signing-algorithm",
            "RSASSA_PKCS1_V1_5_SHA_256",
            "--message",
            base64.b64encode(digest).decode(),
        )
        return base64.b64decode(response["Signature"])

    now = datetime.datetime.now(datetime.UTC).replace(microsecond=0)
    cert = certificate(spki, sign, now - datetime.timedelta(minutes=5), days)
    with open("outlook-oauth.pem", "w", encoding="ascii") as handle:
        handle.write(pem(cert))
    print("Wrote outlook-oauth.pem. Upload it to the Entra app's Certificates.")
    print(f"x5t#S256: {thumbprint(cert)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
