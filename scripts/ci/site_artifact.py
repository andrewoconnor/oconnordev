"""Package tested public bytes; verify the check-job digest before extraction."""

import hashlib
import re
import sys
import tarfile
from pathlib import Path


def pack(dist: Path, archive: Path) -> str:
    files = sorted(dist.rglob("*"))
    if not files or not (dist / "index.html").is_file():
        raise ValueError("Missing tested site")
    for path in files:
        if path.is_symlink() or path.name == "build-meta.json":
            raise ValueError("Private metadata or symlink in public release")
    archive.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "w") as bundle:
        for path in files:
            if path.is_file():
                bundle.add(path, arcname=path.relative_to(dist), recursive=False)
    return hashlib.sha256(archive.read_bytes()).hexdigest()


def verify(archive: Path, expected: str, dist: Path) -> None:
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ValueError("Invalid expected SHA256")
    if hashlib.sha256(archive.read_bytes()).hexdigest() != expected:
        raise ValueError("Tested artifact SHA256 mismatch")
    if dist.exists():
        raise ValueError("Extraction destination already exists")
    with tarfile.open(archive) as bundle:
        members = bundle.getmembers()
        names = [member.name for member in members]
        if not members or len(set(names)) != len(names):
            raise ValueError("Empty or duplicate archive members")
        for member in members:
            path = Path(member.name)
            if (
                not member.isfile()
                or path.is_absolute()
                or ".." in path.parts
                or path.name == "build-meta.json"
            ):
                raise ValueError("Unsafe release member")
        if "index.html" not in names:
            raise ValueError("Missing site index")
        dist.mkdir(parents=True)
        bundle.extractall(dist, filter="data")


if __name__ == "__main__":
    if sys.argv[1] == "pack":
        print(pack(Path(sys.argv[2]), Path(sys.argv[3])))
    elif sys.argv[1] == "verify":
        verify(Path(sys.argv[2]), sys.argv[3], Path(sys.argv[4]))
    else:
        raise ValueError("Expected pack or verify")
