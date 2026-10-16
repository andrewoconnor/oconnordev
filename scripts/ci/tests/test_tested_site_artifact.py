"""Exercise the release transport without credentials or network."""

import hashlib
import io
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/ci/site_artifact.py"


class TestedSiteArtifactTests(unittest.TestCase):
    def test_exact_bytes_round_trip_and_tamper_fails_before_extract(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            dist = root / "dist"
            (dist / "assets").mkdir(parents=True)
            (dist / "index.html").write_bytes(b"tested HTML")
            (dist / "assets/main-ABCDEFGH.js").write_bytes(b"tested JS")
            archive = root / "release.tar"
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "pack", str(dist), str(archive)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            self.assertEqual(result.stdout.strip(), digest)
            target = root / "downloaded"
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "verify",
                    str(archive),
                    digest,
                    str(target),
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            for path in dist.rglob("*"):
                if path.is_file():
                    self.assertEqual(
                        path.read_bytes(),
                        (target / path.relative_to(dist)).read_bytes(),
                    )
            archive.write_bytes(archive.read_bytes() + b"tampered")
            target2 = root / "rejected"
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "verify",
                    str(archive),
                    digest,
                    str(target2),
                ],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(target2.exists())

    def test_pack_rejects_private_build_metadata_and_symlinks(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            dist = root / "dist"
            dist.mkdir()
            (dist / "index.html").write_bytes(b"tested HTML")
            for name in ("build-meta.json", "link"):
                path = dist / name
                if name == "link":
                    path.symlink_to("/etc/passwd")
                else:
                    path.write_text("private")
                result = subprocess.run(
                    [
                        sys.executable,
                        str(SCRIPT),
                        "pack",
                        str(dist),
                        str(root / "release.tar"),
                    ],
                    capture_output=True,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(b"Private metadata or symlink", result.stderr)
                self.assertFalse((root / "release.tar").exists())
                path.unlink()

    def test_digest_matched_unsafe_archives_fail_before_extraction(self):
        cases = (
            ("absolute", "/outside.html", tarfile.REGTYPE, "Unsafe release member"),
            ("traversal", "../outside.html", tarfile.REGTYPE, "Unsafe release member"),
            ("symlink", "link", tarfile.SYMTYPE, "Unsafe release member"),
            ("hardlink", "link", tarfile.LNKTYPE, "Unsafe release member"),
            ("duplicate", "index.html", tarfile.REGTYPE, "duplicate archive members"),
            ("metadata", "build-meta.json", tarfile.REGTYPE, "Unsafe release member"),
            (
                "nested_metadata",
                "assets/build-meta.json",
                tarfile.REGTYPE,
                "Unsafe release member",
            ),
            ("missing_index", "main.js", tarfile.REGTYPE, "Missing site index"),
            (
                "existing_destination",
                "main.js",
                tarfile.REGTYPE,
                "Extraction destination already exists",
            ),
        )
        for case, name, kind, error in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                archive = root / "release.tar"
                target = root / "downloaded"
                # Use an absolute target under this test's temporary directory.
                if case == "absolute":
                    name = str(root / "outside.html")
                with tarfile.open(archive, "w") as bundle:
                    if case != "missing_index":
                        index = tarfile.TarInfo("index.html")
                        index.size = len(b"tested HTML")
                        bundle.addfile(index, io.BytesIO(b"tested HTML"))
                    member = tarfile.TarInfo(name)
                    member.type = kind
                    if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE):
                        member.linkname = "../outside.html"
                        bundle.addfile(member)
                    else:
                        member.size = len(b"unsafe bytes")
                        bundle.addfile(member, io.BytesIO(b"unsafe bytes"))
                if case == "existing_destination":
                    target.mkdir()
                    (target / "sentinel").write_bytes(b"preserve me")
                # A correct digest must reach member/destination validation,
                # rather than passing merely because the digest mismatched.
                digest = hashlib.sha256(archive.read_bytes()).hexdigest()
                result = subprocess.run(
                    [
                        sys.executable,
                        str(SCRIPT),
                        "verify",
                        str(archive),
                        digest,
                        str(target),
                    ],
                    capture_output=True,
                    text=True,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(error, result.stderr)
                self.assertNotIn("SHA256 mismatch", result.stderr)
                self.assertFalse((root / "outside.html").exists())
                if case == "existing_destination":
                    self.assertEqual(list(target.iterdir()), [target / "sentinel"])
                    self.assertEqual((target / "sentinel").read_bytes(), b"preserve me")
                else:
                    self.assertFalse(target.exists())

    def test_bootstrap_protects_and_verifies_environments_before_iam_trust(self):
        runbook = (ROOT / "docs/runbooks/infrastructure-bootstrap.md").read_text()
        heading = "## Tested-artifact environment bootstrap"
        self.assertIn(heading, runbook)
        bootstrap = runbook.split(heading, 1)[1]
        stages = (
            "Stage both GitHub environments before any IAM environment trust",
            "Read back and test both environment gates before IAM changes",
            "Activate IAM environment trust only after both gates pass",
            "Apply the full repository-configuration stack",
            "Merge/re-enable workflows only after those checks",
        )
        for stage in stages:
            self.assertIn(stage, bootstrap)
        positions = [bootstrap.index(stage) for stage in stages]
        self.assertEqual(positions, sorted(positions))
        staging = bootstrap[positions[0] : positions[1]]
        for required in (
            "oconnordev-production",
            "drumrollworld-production",
            "GitHub UI bootstrap",
            "Do not run the dependent repository stack yet",
            "branch `master`",
            "no tag policy",
            "TOOLS and DrumrollWorld",
        ):
            self.assertIn(required, staging)
        gate = bootstrap[positions[1] : positions[2]]
        self.assertIn("non-master", gate)
        self.assertIn("before starting", gate)
        self.assertIn("OIDC token", gate)
        self.assertIn("Stop bootstrap", gate)
