"""Run isolated host proof with persistent dependencies and hard disk/time budgets.
Usage: mise exec rust -- PYTHON verify.py /path/to/thundermail-native-proof
The invoking Python needs the MCP SDK solely to validate synthetic results.
No AWS/mail credential environment is passed to the Rust child processes.
"""

import hashlib
import json
import os
import pathlib
import re
import shutil
import signal
import subprocess
import sys
import time
import tomllib

ROOT = pathlib.Path(__file__).resolve().parent
BASE = pathlib.Path(sys.argv[1]).resolve()
RESERVE = 314572800
EVIDENCE = (
    pathlib.Path(sys.argv[2]).resolve()
    if len(sys.argv) > 2
    else BASE / "production-evidence"
)
EVIDENCE.mkdir(parents=True, exist_ok=True)
assert not EVIDENCE.is_relative_to(ROOT), (
    "execution evidence must remain outside delivery source"
)
for name in ("home", "tmp", "cargo", "target"):
    (BASE / name).mkdir(exist_ok=True)
env = {
    "PATH": os.path.dirname(shutil.which("cargo")) + ":/usr/bin:/bin",
    "RUSTUP_HOME": os.environ.get("RUSTUP_HOME", str(pathlib.Path.home() / ".rustup")),
    **{k: os.environ[k] for k in ("RUSTUP_TOOLCHAIN",) if k in os.environ},
    "HOME": str(BASE / "home"),
    "CARGO_HOME": str(BASE / "cargo"),
    "CARGO_TARGET_DIR": str(BASE / "target"),
    "TMPDIR": str(BASE / "tmp"),
    "CARGO_PROFILE_DEV_DEBUG": "0",
    "CARGO_PROFILE_TEST_DEBUG": "0",
    "CARGO_INCREMENTAL": "0",
    "CARGO_BUILD_JOBS": "1",
    "LANG": "C.UTF-8",
}
minimum = shutil.disk_usage(BASE).free
initial = minimum
runs = []


def run(label, command, seconds=180):
    global minimum
    path = EVIDENCE / (label + ".log")
    start = time.monotonic()
    with path.open("w") as log:
        p = subprocess.Popen(
            command,
            cwd=ROOT,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            while p.poll() is None:
                free = shutil.disk_usage(BASE).free
                minimum = min(minimum, free)
                assert free >= RESERVE, f"disk reserve reached: {free}"
                assert time.monotonic() - start < seconds, (
                    f"time budget exceeded: {label}"
                )
                time.sleep(0.2)
            assert p.returncode == 0, f"{label} exit={p.returncode}, see {path}"
        finally:
            if p.poll() is None:
                os.killpg(p.pid, signal.SIGKILL)
                p.wait()
    runs.append(
        {
            "label": label,
            "exit_code": p.returncode,
            "seconds": round(time.monotonic() - start, 3),
        }
    )
    return path.read_text()


run("format", ["cargo", "fmt", "--all", "--", "--check"])
tests = run("unit-tests", ["cargo", "test", "--locked"])
counts = re.findall(r"test result: ok\. (\d+) passed; 0 failed; (\d+) ignored", tests)
assert counts, tests
passed = sum(int(a) for a, b in counts)
ignored = sum(int(b) for a, b in counts)
assert passed == 14 and ignored == 1, (passed, ignored)
run("host-build", ["cargo", "build", "--locked"])
artifacts = run(
    "test-artifact", ["cargo", "test", "--locked", "--no-run", "--message-format=json"]
)
executables = []
for line in artifacts.splitlines():
    try:
        record = json.loads(line)
    except ValueError:
        continue
    if (
        record.get("reason") == "compiler-artifact"
        and record.get("target", {}).get("kind") == ["lib"]
        and record.get("executable")
    ):
        executables.append(record["executable"])
assert len(executables) == 1, executables
run("clippy", ["cargo", "clippy", "--locked", "--all-targets", "--", "-D", "warnings"])
run(
    "native-imap-runtime",
    [
        sys.executable,
        str(ROOT / "native_imap_runtime_test.py"),
        executables[0],
        str(BASE),
        str(EVIDENCE),
    ],
    40,
)
result = json.loads((EVIDENCE / "native-imap-runtime-result.json").read_text())
assert result["passed"] == 3 and result["seen_after"] is False
lock = tomllib.loads((ROOT / "Cargo.lock").read_text())["package"]
assert not {p["name"] for p in lock}.intersection(
    {"aws-lc-sys", "lettre", "pdf-extract", "rmcp", "reqwest"}
)


def sha(p):
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


binary = BASE / "target/debug/thundermail-native-read"
source = {
    str(p.relative_to(ROOT)): sha(p)
    for p in ROOT.rglob("*")
    if p.is_file()
    and "evidence" not in p.relative_to(ROOT).parts
    and p.suffix not in (".stderr",)
    and "__pycache__" not in p.parts
}
report = {
    "status": "HOST_NATIVE_UPSTREAM_READ_PROOF_PASS_NOT_DEPLOYED",
    "synthetic_only": True,
    "locked_packages": len(lock),
    "unit_tests_passed": passed,
    "unit_tests_ignored": ignored,
    "native_runtime_mail_reads_passed": result["passed"],
    "mcp_sdk_version": __import__("importlib.metadata", fromlist=["version"]).version(
        "mcp"
    ),
    "production_binary": str(binary),
    "production_binary_sha256": sha(binary),
    "test_worker_sha256": sha(executables[0]),
    "initial_free_bytes": initial,
    "minimum_free_bytes": minimum,
    "final_free_bytes": shutil.disk_usage(BASE).free,
    "safety_reserve_bytes": RESERVE,
    "runs": runs,
    "source_sha256": source,
    "remaining_gates": [
        "production AWS/TLS integration",
        "live AgentCore wrapping/forwarding and canary",
        "explicit rollout approval; preserve existing integrations",
    ],
}
(EVIDENCE / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps({k: v for k, v in report.items() if k != "source_sha256"}, indent=2))
