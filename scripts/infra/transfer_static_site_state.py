"""Prepare LOCAL state copies only. Never pushes state or talks to AWS.

The owner must freeze both stacks, export exact snapshots and review/push the
outputs using the backend's authenticated state workflow. See the runbook.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path

STATE_MAP = Path(__file__).with_name("static-site-state-map.json")


def transfer(source: Path, destination: Path, output: Path, tofu: str) -> dict:
    """Fail closed on missing source, existing destination or unknown site state."""
    mapping = json.loads(STATE_MAP.read_text())
    source_state = json.loads(source.read_text())
    destination_state = json.loads(destination.read_text())
    if source_state.get("version") != 4 or destination_state.get("version") != 4:
        raise ValueError("Only exact backend-exported v4 snapshots are supported")
    if not source_state.get("lineage") or not destination_state.get("lineage"):
        raise ValueError("Both snapshots must have backend-assigned lineages")
    if source_state["lineage"] == destination_state["lineage"]:
        raise ValueError("Independent stacks must have distinct lineages")
    if any(r.get("mode") == "managed" for r in destination_state["resources"]):
        raise ValueError("Destination must contain no managed resources before handoff")
    inventory = {
        f"{r['type']}.{r['name']}": r
        for r in source_state["resources"]
        if r.get("mode") == "managed" and not r.get("module")
    }
    for address in mapping:
        resource = inventory.get(address)
        if not resource or not resource.get("instances"):
            raise ValueError(
                f"Missing live source address: {address}; do not guess/import IDs"
            )
        if any(i.get("deposed") for i in resource["instances"]):
            raise ValueError(f"Deposed instances require manual review: {address}")
    # A new private directory prevents overwriting snapshots or previous runs.
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    src = output / "production.tfstate"
    dst = output / "resume.tfstate"
    shutil.copyfile(source, src)
    shutil.copyfile(destination, dst)
    os.chmod(src, 0o600)
    os.chmod(dst, 0o600)
    for old, new in mapping.items():
        subprocess.run(
            [tofu, "state", "mv", f"-state={src}", f"-state-out={dst}", old, new],
            cwd=output,
            check=True,
            capture_output=True,
            text=True,
        )
    final_src = json.loads(src.read_text())
    final_dst = json.loads(dst.read_text())
    if final_src["lineage"] != source_state["lineage"]:
        raise ValueError("Source lineage changed; NEVER push these files")
    if final_dst["lineage"] != destination_state["lineage"]:
        raise ValueError("Destination lineage changed; NEVER push these files")
    if any(
        f"{r['type']}.{r['name']}" in mapping
        for r in final_src["resources"]
        if r.get("mode") == "managed" and not r.get("module")
    ):
        raise ValueError("Source still owns a moved resource; NEVER push these files")
    moved = [r for r in final_dst["resources"] if r.get("mode") == "managed"]
    if len(moved) != len(mapping) or any(
        r.get("module") != "module.site" for r in moved
    ):
        raise ValueError("Unexpected destination inventory; NEVER push these files")
    for position, (old, new) in enumerate(mapping.items()):
        typ, name = new.removeprefix("module.site.").split(".")
        resource = next(r for r in moved if r["type"] == typ and r["name"] == name)
        if resource.get("provider") != inventory[old].get("provider"):
            raise ValueError(f"Provider changed at {old}; NEVER push these files")
        before = inventory[old]["instances"]
        after = resource["instances"]

        # OpenTofu 1.12.6 state mv clears the WHOLE dependency list in the
        # destination when it refers to the current move's source address.
        # Only this move and later moves can affect an instance: earlier moves
        # ran before it arrived in the destination. It does not remap edges.
        # Predict that exact transformation, not arbitrary dependency removal.
        remaining = set(list(mapping)[position:])
        expected = []
        for instance in before:
            instance = dict(instance)
            if remaining.intersection(instance.get("dependencies", [])):
                instance.pop("dependencies", None)
            expected.append(instance)

        def normalize(instances):
            return [
                {
                    **i,
                    "private": i.get("private", ""),
                    "dependencies": i.get("dependencies", []),
                }
                for i in instances
            ]

        if normalize(after) != normalize(expected):
            raise ValueError(f"Instance bytes changed at {old}; NEVER push these files")
    report = {
        "addresses": mapping,
        "resource_count": len(mapping),
        "remote_changes": False,
    }
    (output / "manifest.json").write_text(json.dumps(report, indent=2) + "\n")
    # CLI state backups contain sensitive data too.
    for path in output.iterdir():
        if path.is_file():
            os.chmod(path, 0o600)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tofu", default="tofu")
    parser.add_argument(
        "--acknowledge-stacks-locked", action="store_true", required=True
    )
    args = parser.parse_args()
    report = transfer(
        args.source.resolve(),
        args.destination.resolve(),
        args.output_dir.resolve(),
        args.tofu,
    )
    print(json.dumps(report, indent=2))
    print(
        "LOCAL ONLY. Review snapshots, push detached production then adopted resume "
        "while both stacks remain locked. No apply is authorized."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
