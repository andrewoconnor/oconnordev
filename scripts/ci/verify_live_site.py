"""Check that the live site serves exactly the tested release with its headers."""

import hashlib
import re
import secrets
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
IMMUTABLE = (
    re.compile(r"^assets/main-[A-Z0-9]{8}\.js$"),
    re.compile(r"^assets/css/resume-[a-f0-9]{64}\.css$"),
)
FIXED_HEADERS = {
    "strict-transport-security": "max-age=31536000; includeSubDomains; preload",
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "strict-origin-when-cross-origin",
}


def expected_headers(site):
    site_tf = (ROOT / f"infra/aws/{site}/site.tf").read_text()
    delivery = (ROOT / "infra/modules/static-site/delivery.tf").read_text()
    csp = re.search(r'content_security_policy\s*=\s*"([^"]+)"', site_tf).group(1)
    permissions = re.search(r'value\s*=\s*"(accelerometer=[^"]+)"', delivery).group(1)
    return {
        **FIXED_HEADERS,
        "content-security-policy": csp,
        "permissions-policy": permissions,
    }


def cache_control(key):
    if any(pattern.match(key) for pattern in IMMUTABLE):
        return "public,max-age=31536000,immutable"
    return "public,max-age=0,must-revalidate"


def fetch(url, attempts=4, delay=5):
    request = urllib.request.Request(
        url, headers={"User-Agent": "oconnordev-live-check"}
    )
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.status, response.headers, response.read()
        except urllib.error.HTTPError as error:
            if error.code < 500:
                return error.code, error.headers, error.read()
            failure = error
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            failure = error
        if attempt < attempts:
            time.sleep(delay * attempt)
    raise RuntimeError(f"{url}: {failure}")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def wait_for_release(url, index, timeout=600, interval=15):
    deadline = time.monotonic() + timeout
    while True:
        status, _, body = fetch(f"{url}/")
        if status == 200 and digest(body) == digest(index):
            return
        if time.monotonic() >= deadline:
            raise RuntimeError(f"{url}/ still serves another release after {timeout}s")
        time.sleep(interval)


def verify(site, url, dist):
    dist = Path(dist)
    files = sorted(path for path in dist.rglob("*") if path.is_file())
    if not (dist / "index.html").is_file():
        raise ValueError("Tested release has no index.html")
    wait_for_release(url, (dist / "index.html").read_bytes())
    errors = []
    headers_expected = expected_headers(site)
    for path in files:
        key = path.relative_to(dist).as_posix()
        status, headers, body = fetch(f"{url}/{'' if key == 'index.html' else key}")
        if status != 200:
            errors.append(f"{key}: HTTP {status}")
            continue
        if digest(body) != digest(path.read_bytes()):
            errors.append(f"{key}: live bytes differ from the tested release")
        if headers.get("cache-control") != cache_control(key):
            errors.append(f"{key}: cache-control {headers.get('cache-control')!r}")
        for name, value in headers_expected.items():
            if headers.get(name) != value:
                errors.append(f"{key}: {name} {headers.get(name)!r}")
    status, _, body = fetch(f"{url}/live-check-missing-{secrets.token_hex(8)}")
    if status != 404 or body != (dist / "404.html").read_bytes():
        errors.append(f"unknown path: HTTP {status}, not the tested 404 page")
    if errors:
        raise RuntimeError("\n".join(errors))
    print(f"{url} serves all {len(files)} tested files with the expected headers")


if __name__ == "__main__":
    try:
        verify(*sys.argv[1:])
    except (ValueError, TypeError, RuntimeError) as error:
        sys.exit(f"Live check failed:\n{error}")
