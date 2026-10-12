"""Real provider-free OpenTofu state transfer and plan safety fixtures.

Synthetic IDs below are test data, never imports or claimed live infrastructure.
No backend, AWS credentials, network, or AWS provider is involved.
"""

from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import transfer_static_site_state as migration
from transfer_static_site_state import STATE_MAP, transfer

TOFU = os.environ.get("TOFU", shutil.which("tofu") or "tofu")
MAP = json.loads(STATE_MAP.read_text())


def snapshot(resources: list[dict]) -> dict:
    return {
        "version": 4,
        "terraform_version": "1.12.6",
        "serial": 1,
        "lineage": str(uuid.uuid4()),
        "outputs": {},
        "resources": resources,
    }


def resource(address: str) -> dict:
    typ, name = address.split(".")
    return {
        "mode": "managed",
        "type": typ,
        "name": name,
        "provider": 'provider["registry.opentofu.org/hashicorp/aws"]',
        "instances": [
            {
                "schema_version": 0,
                "attributes": {"id": "fixture-only:" + address},
                "sensitive_attributes": [],
                "private": "",
            }
        ],
    }


class StateHandoffTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR"))
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / "source.tfstate"
        self.destination = self.root / "destination.tfstate"
        self.retained = [
            "aws_route53_zone.oconnordev",
            "aws_kms_key.dnssec",
            "aws_acm_certificate.oconnordev",
            "aws_route53_record.oconnordev_validation",
            "aws_acm_certificate_validation.oconnordev",
            "aws_cloudfront_distribution.hermes_mcp",
        ]
        self.source_data = snapshot([resource(a) for a in [*MAP, *self.retained]])
        self.destination_data = snapshot([])
        self.source.write_text(json.dumps(self.source_data))
        self.destination.write_text(json.dumps(self.destination_data))

    def test_native_state_transfer_preserves_every_instance_and_shared_resources(self):
        report = transfer(self.source, self.destination, self.root / "prepared", TOFU)
        self.assertEqual(report["resource_count"], len(MAP))
        src = json.loads((self.root / "prepared/production.tfstate").read_text())
        dst = json.loads((self.root / "prepared/resume.tfstate").read_text())
        self.assertEqual(
            {f"{r['type']}.{r['name']}" for r in src["resources"]}, set(self.retained)
        )
        self.assertEqual(len(dst["resources"]), len(MAP))
        self.assertEqual(src["lineage"], self.source_data["lineage"])
        self.assertEqual(dst["lineage"], self.destination_data["lineage"])
        self.assertEqual(json.loads(self.source.read_text()), self.source_data)
        self.assertEqual(
            json.loads(self.destination.read_text()), self.destination_data
        )

    def test_native_dependency_metadata_is_not_provider_corruption(self):
        distribution = self.source_data["resources"][0]
        distribution["instances"][0]["dependencies"] = [
            "aws_cloudfront_origin_access_control.oconnordev",
            "aws_acm_certificate.oconnordev",
        ]
        distribution["instances"][0].update(
            schema_version=3,
            attributes={
                "id": "fixture-only:distribution",
                "nested": {"secret": "value"},
            },
            sensitive_attributes=[[{"type": "get_attr", "value": "nested"}]],
            private="cHJpdmF0ZQ==",
            index_key="fixture-key",
        )
        distribution["instances"].append(copy.deepcopy(distribution["instances"][0]))
        distribution["instances"][1]["index_key"] = "second-key"
        # This last move references resources already moved: native mv retains
        # these dependencies, rather than indiscriminately clearing all edges.
        self.source_data["resources"][len(MAP) - 1]["instances"][0]["dependencies"] = [
            "aws_s3_bucket.web",
            "aws_route53_zone.oconnordev",
        ]
        self.source.write_text(json.dumps(self.source_data))
        before = self.source.read_bytes()
        transfer(self.source, self.destination, self.root / "prepared", TOFU)
        dst = json.loads((self.root / "prepared/resume.tfstate").read_text())
        instances = {r["type"]: r["instances"][0] for r in dst["resources"]}
        self.assertNotIn("dependencies", instances["aws_cloudfront_distribution"])
        self.assertEqual(
            instances["aws_iam_role_policy"]["dependencies"],
            ["aws_s3_bucket.web", "aws_route53_zone.oconnordev"],
        )
        self.assertEqual(self.source.read_bytes(), before)
        self.assertTrue((self.root / "prepared/manifest.json").is_file())

    def test_generated_provider_free_dependencies_survive_native_handoff(self):
        fixture = self.root / "dependent-native"
        fixture.mkdir()
        projected = {
            f"terraform_data.{old.replace('.', '_')}": (
                "module.site.terraform_data."
                + new.removeprefix("module.site.").replace(".", "_")
            )
            for old, new in MAP.items()
        }
        names = [address.split(".")[1] for address in projected]
        config = []
        for position, name in enumerate(names):
            value = (
                f"terraform_data.{names[1]}.output"
                if position in (0, len(names) - 1)
                else f'"{name}"'
            )
            config.append(f'resource "terraform_data" "{name}" {{ input = {value} }}')
        (fixture / "main.tf").write_text("\n".join(config))
        self.run_tofu(fixture, "init", "-backend=false")
        self.run_tofu(fixture, "apply", "-auto-approve")
        state = json.loads(self.run_tofu(fixture, "state", "pull"))
        native = {r["name"]: r for r in state["resources"]}
        for name in (names[0], names[-1]):
            self.assertEqual(
                native[name]["instances"][0]["dependencies"],
                [f"terraform_data.{names[1]}"],
            )
        # No synthetic dependency metadata: both the IDs and edges above came
        # directly from the installed OpenTofu builtin provider's apply.
        self.source.write_text(json.dumps(state))
        map_file = self.root / "native-map.json"
        map_file.write_text(json.dumps(projected))
        with patch.object(migration, "STATE_MAP", map_file):
            transfer(self.source, self.destination, self.root / "prepared", TOFU)
        dst = json.loads((self.root / "prepared/resume.tfstate").read_text())
        moved = {r["name"]: r for r in dst["resources"]}
        for old, new in projected.items():
            before = native[old.split(".")[1]]
            after = moved[new.split(".")[-1]]
            self.assertEqual(before["provider"], after["provider"])
            self.assertEqual(
                before["instances"][0]["attributes"],
                after["instances"][0]["attributes"],
            )
        self.assertNotIn(
            "dependencies",
            moved[projected[list(projected)[0]].split(".")[-1]]["instances"][0],
        )
        self.assertEqual(
            moved[projected[list(projected)[-1]].split(".")[-1]]["instances"][0][
                "dependencies"
            ],
            [f"terraform_data.{names[1]}"],
        )
        print(
            "NATIVE: applied terraform_data dependency edges; "
            "early edge cleared, late edge retained"
        )

    def test_dependency_and_provider_payload_corruption_stays_fail_closed(self):
        first = self.source_data["resources"][0]["instances"][0]
        first.update(
            schema_version=3,
            attributes={
                "id": "fixture-only:distribution",
                "nested": {"secret": "value"},
            },
            sensitive_attributes=[[{"type": "get_attr", "value": "nested"}]],
            private="cHJpdmF0ZQ==",
            index_key="fixture-key",
            dependencies=[list(MAP)[1], "aws_acm_certificate.oconnordev"],
        )
        last = self.source_data["resources"][len(MAP) - 1]["instances"][0]
        last["dependencies"] = ["aws_s3_bucket.web", "aws_route53_zone.oconnordev"]
        self.source.write_text(json.dumps(self.source_data))
        cases = {
            "attributes": {"id": "injected"},
            "schema_version": 4,
            "sensitive_attributes": [],
            "private": "aW5qZWN0ZWQ=",
            "index_key": "other-key",
            "dependencies": ["aws_iam_role.injected"],
        }
        for field, value in cases.items():
            with self.subTest(field=field):
                self.assert_corruption_rejected(
                    lambda state, field=field, value=value: state["resources"][0][
                        "instances"
                    ][0].__setitem__(field, value)
                )
                shutil.rmtree(self.root / "prepared")
        # Changing, selectively dropping, remapping or clearing an edge retained
        # by native mv is not the proved whole-list reset of an affected instance.
        for dependencies in (
            [],
            ["aws_s3_bucket.web"],
            ["module.site.aws_s3_bucket.web", "aws_route53_zone.oconnordev"],
            [
                "aws_s3_bucket.web",
                "aws_route53_zone.oconnordev",
                "aws_iam_role.injected",
            ],
        ):
            with self.subTest(dependencies=dependencies):

                def corrupt(state, dependencies=dependencies):
                    policy = next(
                        r
                        for r in state["resources"]
                        if r["type"] == "aws_iam_role_policy"
                    )
                    policy["instances"][0]["dependencies"] = dependencies

                self.assert_corruption_rejected(corrupt)
                shutil.rmtree(self.root / "prepared")

    def test_failed_native_move_leaves_no_completion_manifest(self):
        native_run = subprocess.run
        calls = 0

        def run(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise subprocess.CalledProcessError(1, args[0])
            return native_run(*args, **kwargs)

        with (
            patch.object(migration.subprocess, "run", side_effect=run),
            self.assertRaises(subprocess.CalledProcessError),
        ):
            transfer(self.source, self.destination, self.root / "prepared", TOFU)
        self.assertTrue((self.root / "prepared/resume.tfstate").exists())
        self.assertFalse((self.root / "prepared/manifest.json").exists())

    def test_changed_provider_address_never_produces_completion_manifest(self):
        def corrupt(state):
            state["resources"][0]["provider"] = (
                'provider["registry.opentofu.org/hashicorp/aws"].other'
            )

        self.assert_corruption_rejected(corrupt)

    def assert_corruption_rejected(self, corrupt):
        prepared = self.root / "prepared"
        native_run = subprocess.run

        def run(*args, **kwargs):
            result = native_run(*args, **kwargs)
            if args[0][-2] == list(MAP)[-1]:
                path = prepared / "resume.tfstate"
                state = json.loads(path.read_text())
                corrupt(state)
                path.write_text(json.dumps(state))
            return result

        with (
            patch.object(migration.subprocess, "run", side_effect=run),
            self.assertRaisesRegex(ValueError, "NEVER push"),
        ):
            transfer(self.source, self.destination, prepared, TOFU)
        self.assertFalse((prepared / "manifest.json").exists())
        self.assertEqual(json.loads(self.source.read_text()), self.source_data)
        self.assertEqual(
            json.loads(self.destination.read_text()), self.destination_data
        )

    def test_empty_state_bootstrap_creates_no_managed_objects(self):
        fixture = self.root / "empty-bootstrap"
        fixture.mkdir()
        (fixture / "main.tf").write_text(
            'output "state_bootstrap" { value = "empty-resume-state" }\n'
        )
        self.run_tofu(fixture, "init", "-backend=false")
        self.run_tofu(fixture, "apply", "-auto-approve")
        state = json.loads(self.run_tofu(fixture, "state", "pull"))
        self.assertEqual(state["version"], 4)
        self.assertTrue(state["lineage"])
        self.assertEqual(state["resources"], [])
        self.destination.write_text(json.dumps(state))
        transfer(self.source, self.destination, self.root / "prepared", TOFU)

    def test_missing_source_address_fails_without_output(self):
        data = copy.deepcopy(self.source_data)
        data["resources"].pop(0)
        self.source.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "Missing live source address"):
            transfer(self.source, self.destination, self.root / "prepared", TOFU)
        self.assertFalse((self.root / "prepared").exists())

    def test_destination_owner_collision_fails_without_output(self):
        data = copy.deepcopy(self.destination_data)
        data["resources"] = [resource("aws_s3_bucket.web")]
        self.destination.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "no managed resources"):
            transfer(self.source, self.destination, self.root / "prepared", TOFU)
        self.assertFalse((self.root / "prepared").exists())

    def test_real_plans_prove_moves_and_non_destructive_removal(self):
        # Project every load-bearing address into terraform_data: this tests
        # core state semantics, not AWS service behavior or fabricated live IDs.
        fixture = self.root / "plans"
        fixture.mkdir()
        names = [a.replace(".", "_") for a in MAP]
        names.append("shared_zone_and_hermes")
        old = "".join(
            f'resource "terraform_data" "{name}" {{ input = "{name}" }}\n'
            for name in names
        )
        (fixture / "main.tf").write_text(old)
        self.run_tofu(fixture, "init", "-backend=false")
        self.run_tofu(fixture, "apply", "-auto-approve")
        (fixture / "site").mkdir()
        projected = [
            (old.replace(".", "_"), new.removeprefix("module.site.").replace(".", "_"))
            for old, new in MAP.items()
        ]
        (fixture / "site/main.tf").write_text(
            "".join(
                f'resource "terraform_data" "{new}" {{ input = "{old}" }}\n'
                for old, new in projected
            )
        )
        moves = "".join(
            f"moved {{\n from = terraform_data.{old}\n"
            f" to = module.site.terraform_data.{new}\n}}\n"
            for old, new in projected
        )
        retained = (
            'resource "terraform_data" "shared_zone_and_hermes" {\n'
            ' input = "shared_zone_and_hermes"\n}\n'
        )
        (fixture / "main.tf").write_text(
            'module "site" { source = "./site" }\n' + retained + moves
        )
        self.run_tofu(fixture, "init", "-backend=false")
        plan = self.plan_json(fixture)
        changes = plan["resource_changes"]
        self.assertFalse(any("delete" in c["change"]["actions"] for c in changes))
        self.assertEqual(sum("previous_address" in c for c in changes), len(MAP))
        self.assertTrue(all(c["change"]["actions"] == ["no-op"] for c in changes))
        # Test the production detach declaration against the original state.
        removed = "".join(
            f"removed {{\n from = terraform_data.{old.replace('.', '_')}\n"
            " lifecycle { destroy = false }\n}\n"
            for old in MAP
        )
        (fixture / "main.tf").write_text(retained + removed)
        plan = self.plan_json(fixture)
        self.assertFalse(
            any("delete" in c["change"]["actions"] for c in plan["resource_changes"])
        )
        self.assertEqual(
            sum(c["change"]["actions"] == ["forget"] for c in plan["resource_changes"]),
            len(MAP),
        )
        print(
            f"FIXTURE: {len(MAP)} address moves no-op; {len(MAP)} removed forget-only; "
            "shared zone/endpoint retained; zero destroys"
        )

    def test_drumroll_moves_include_indexed_certificate_and_dns_instances(self):
        import re

        repo = Path(__file__).resolve().parents[2]
        moves_source = (repo / "infra/aws/drumrollworld/moved.tf").read_text()
        moves = re.findall(r"from\s*=\s*([^\s]+)\s+to\s*=\s*([^\s]+)", moves_source)
        self.assertEqual(len(moves), 16)
        fixture = self.root / "drum-plans"
        fixture.mkdir()
        module = fixture / "site"
        module.mkdir()
        old_config, new_config, moved_config = [], [], []
        for old, new in moves:
            old_name = old.replace(".", "_")
            new_name = (
                new.removeprefix("module.site.").removesuffix("[0]").replace(".", "_")
            )
            is_validation_record = old == "aws_route53_record.drumrollworld_validation"
            index_input = "each.key" if is_validation_record else f'"{old_name}"'
            for_each = (
                'for_each = toset(["*.drumroll.world"])\n'
                if is_validation_record
                else ""
            )
            count = "count = 1\n" if new.endswith("[0]") else ""
            old_config.append(
                f'resource "terraform_data" "{old_name}" {{\n'
                f" {for_each} input = {index_input}\n}}\n"
            )
            new_config.append(
                f'resource "terraform_data" "{new_name}" {{\n'
                f" {for_each}{count} input = {index_input}\n}}\n"
            )
            index = "[0]" if new.endswith("[0]") else ""
            moved_config.append(
                f"moved {{\n from = terraform_data.{old_name}\n"
                f" to = module.site.terraform_data.{new_name}{index}\n}}\n"
            )
        (fixture / "main.tf").write_text("".join(old_config))
        self.run_tofu(fixture, "init", "-backend=false")
        self.run_tofu(fixture, "apply", "-auto-approve")
        (module / "main.tf").write_text("".join(new_config))
        (fixture / "main.tf").write_text(
            'module "site" { source = "./site" }\n' + "".join(moved_config)
        )
        self.run_tofu(fixture, "init", "-backend=false")
        changes = self.plan_json(fixture)["resource_changes"]
        self.assertEqual(len(changes), 16)
        self.assertTrue(all(c["change"]["actions"] == ["no-op"] for c in changes))
        self.assertEqual(sum("previous_address" in c for c in changes), 16)
        print(
            "FIXTURE: all 16 Drumroll moves (certificate [0], wildcard DNS key) "
            "no-op; zero destroys/replacements"
        )

    @staticmethod
    def run_tofu(root: Path, *args: str) -> str:
        result = subprocess.run(
            [TOFU, f"-chdir={root}", *args, "-no-color"],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        return result.stdout

    def plan_json(self, root: Path) -> dict:
        self.run_tofu(root, "plan", "-refresh=false", "-out=fixture.plan")
        return json.loads(
            subprocess.run(
                [TOFU, f"-chdir={root}", "show", "-json", "fixture.plan"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
