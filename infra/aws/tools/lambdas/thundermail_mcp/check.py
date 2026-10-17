"""Use an explicit isolated Rust 1.90 toolchain; never install globally."""

import os
import shutil
import subprocess
from pathlib import Path

RUNTIME = Path(__file__).resolve().parent


def main():
    cargo = os.environ.get("THUNDERMAIL_CARGO") or shutil.which("cargo")
    if not cargo:
        raise SystemExit(
            "Rust unavailable: supply THUNDERMAIL_CARGO="
            "/isolated/rust-1.90.0/bin/cargo; see docs/runbooks/thundermail-mcp.md. "
            "No implicit download/install."
        )
    version = subprocess.check_output([cargo, "--version"], text=True)
    if not version.startswith("cargo 1.90.0 "):
        raise SystemExit("Use the reviewed Rust/Cargo 1.90.0 toolchain")
    env = dict(os.environ, CARGO_BUILD_JOBS="1", CARGO_INCREMENTAL="0")
    env["PATH"] = str(Path(cargo).resolve().parent) + os.pathsep + env.get("PATH", "")
    manifest = RUNTIME / "Cargo.toml"
    for command in [
        [cargo, "fmt", "--manifest-path", str(manifest), "--check"],
        [cargo, "test", "--locked", "--manifest-path", str(manifest)],
    ]:
        subprocess.run(command, check=True, env=env)


if __name__ == "__main__":
    main()
