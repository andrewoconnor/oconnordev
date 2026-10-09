"""Evaluate production HCL with the locked schema and mock GitHub, never live writes.

Import blocks are checked separately and stripped only in temporary offline fixtures.
These mocked create plans are NOT evidence of a live import-only adoption plan.
"""

import hashlib
import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CONFIG = ROOT / "infra/github/oconnordev"
OBSERVED = json.loads((ROOT / "docs/assets/github-settings-observed.json").read_text())
CAPTURE = json.loads(
    (
        Path(__file__).parent / "fixtures/github-adoption-provider-schema.json"
    ).read_text()
)
INIT = ["tofu", "init", "-backend=false", "-input=false", "-lockfile=readonly"]


class GitHubSettingsAdoptionTests(unittest.TestCase):
    def command(self, directory, arguments):
        result = subprocess.run(
            arguments, cwd=directory, capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def initialize(self, directory):
        for name in ("versions.tf", ".terraform.lock.hcl"):
            (directory / name).write_text((CONFIG / name).read_text())
        self.command(directory, INIT)

    def offline_plan(self, source, checks):
        with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as temp:
            directory = Path(temp)
            (directory / "main.tf").write_text(
                re.sub(r"^import \{.*?^\}\n?", "", source, flags=re.M | re.S)
            )
            assertions = "\n".join(
                f"assert {{\n condition = {check}\n"
                ' error_message = "Observed settings must be preserved."\n}'
                for check in checks
            )
            (directory / "settings.tftest.hcl").write_text(
                'mock_provider "github" {}\nrun "preserve" {\ncommand = plan\n'
                + assertions
                + "\n}\n"
            )
            self.initialize(directory)
            self.command(directory, ["tofu", "test", "-no-color"])

    def test_locked_schema_and_existing_variable_inputs_are_unchanged(self):
        self.assertEqual(CAPTURE["provider_version"], "6.13.0")
        with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as temp:
            directory = Path(temp)
            self.initialize(directory)
            result = self.command(directory, ["tofu", "providers", "schema", "-json"])
        actual = json.loads(result)["provider_schemas"][CAPTURE["provider_address"]][
            "resource_schemas"
        ]
        for name, expected in CAPTURE["resource_schemas"].items():
            self.assertEqual(actual[name], expected)
        for name, expected in CAPTURE["unchanged_input_files_sha256"].items():
            self.assertEqual(
                hashlib.sha256((ROOT / name).read_bytes()).hexdigest(), expected, name
            )
        self.assertEqual(len(OBSERVED["already_managed_addresses"]), 5)

    def test_import_scope_counts_no_duplicates_and_destroy_guards(self):
        source = (CONFIG / "settings-adoption.tf").read_text()
        resources = re.findall(r'^resource "([^"]+)" "([^"]+)"', source, re.M)
        self.assertEqual(
            set(resources),
            {
                ("github_issue_label", "observed"),
                ("github_repository_ruleset", "master"),
                ("github_branch_default", "observed"),
                ("github_repository_topics", "observed"),
            },
        )
        self.assertEqual(len(resources), 4)
        for block in re.findall(r"^resource .*?^\}", source, re.M | re.S):
            self.assertIn("prevent_destroy = true", block)
        self.assertNotIn("ignore_changes", source)
        blocks = re.findall(r"^import \{(.*?)^\}", source, re.M | re.S)
        self.assertEqual(len(blocks), 4)
        addresses = [
            f"github_issue_label.observed[{json.dumps(label['name'])}]"
            for label in OBSERVED["labels"]
        ]
        ids = ["oconnordev:" + label["name"] for label in OBSERVED["labels"]]
        for block in blocks:
            if "for_each" not in block:
                target = re.search(r"to\s*= (\S+)", block)
                identifier = re.search(r'id\s*= "([^"]+)"', block)
                self.assertIsNotNone(target)
                self.assertIsNotNone(identifier)
                addresses.append(target.group(1))
                ids.append(identifier.group(1))
        self.assertEqual(len(addresses), 11)
        self.assertEqual(len(set(addresses)), 11)
        self.assertEqual(len(set(zip(addresses, ids, strict=True))), 11)
        self.assertFalse(set(addresses) & set(OBSERVED["already_managed_addresses"]))
        self.assertEqual(ids.count("oconnordev"), 2)  # Separate resource families.
        for file in CONFIG.glob("*.tf"):
            if file.name != "settings-adoption.tf":
                self.assertNotRegex(file.read_text(), r"(?m)^import \{")

    def test_ruleset_default_branch_and_topics_preserve_complete_fields(self):
        source = (CONFIG / "settings-adoption.tf").read_text()
        self.assertIn('resource "github_repository_ruleset" "master"', source)
        self.assertEqual(len(OBSERVED["rulesets"]), 1)
        ruleset = OBSERVED["rulesets"][0]
        coverage = OBSERVED["coverage"]["rulesets"]
        self.assertTrue(coverage["complete"] and coverage["bypass_actors_explicit"])
        self.assertTrue(coverage["terminal_page_empty"])
        self.assertEqual(ruleset["bypass_actors"], [])
        prefix = "github_repository_ruleset.master"
        rules = prefix + ".rules[0]"
        ref = prefix + ".conditions[0].ref_name[0]"
        checks = [
            f"{prefix}.{key} == {json.dumps(ruleset[key])}"
            for key in ("name", "target", "enforcement")
        ]
        checks += [
            f'{prefix}.repository == "oconnordev"',
            f"length({prefix}.bypass_actors) == 0",
            f'{ref}.include == tolist(["~DEFAULT_BRANCH"])',
            f"length({ref}.exclude) == 0",
            f"{rules}.deletion",
            f"{rules}.non_fast_forward",
            'github_branch_default.observed.branch == "master"',
            "!github_branch_default.observed.rename",
            "!github_branch_default.observed.wait_for_rename",
            "length(github_repository_topics.observed.topics) == 0",
        ]
        self.assertEqual(
            ruleset["conditions"]["ref_name"],
            {"include": ["~DEFAULT_BRANCH"], "exclude": []},
        )
        parameters = next(
            rule["parameters"]
            for rule in ruleset["rules"]
            if rule["type"] == "pull_request"
        )
        for key, value in parameters.items():
            expected = json.dumps(value)
            if isinstance(value, list):
                expected = f"tolist({expected})"
            checks.append(f"{rules}.pull_request[0].{key} == {expected}")
        schema = CAPTURE["resource_schemas"]["github_repository_ruleset"]["block"][
            "block_types"
        ]["rules"]["block"]
        self.assertEqual(
            {rule["type"] for rule in ruleset["rules"]},
            {"deletion", "non_fast_forward", "pull_request"},
        )
        for key in schema["attributes"]:
            if key not in {"deletion", "non_fast_forward"}:
                checks.append(f"!coalesce({rules}.{key}, false)")
        for key in schema["block_types"]:
            if key != "pull_request":
                checks.append(f"length({rules}.{key}) == 0")
        checks.append(f"length({rules}.pull_request[0].required_reviewers) == 0")
        self.assertEqual(OBSERVED["repository_metadata"]["default_branch"], "master")
        self.assertEqual(OBSERVED["topics"], [])
        self.offline_plan(source, checks)
        self.assertRegex(
            source,
            r"(?s)import \{\s*to\s*="
            r" github_repository_ruleset.master\s*id\s*="
            r' "oconnordev:24274432"\s*\}',
        )
        for resource in ("github_branch_default", "github_repository_topics"):
            self.assertRegex(
                source,
                rf"(?s)import \{{\s*to\s*= {resource}.observed"
                r'\s*id\s*= "oconnordev"\s*\}',
            )

    def test_labels_preserve_inventory_and_import_exact_names(self):
        source = (CONFIG / "settings-adoption.tf").read_text()
        labels = {
            item["name"]: {key: item[key] for key in ("color", "description")}
            for item in OBSERVED["labels"]
        }
        self.assertEqual(len(labels), 8)
        self.assertEqual(len(labels), OBSERVED["coverage"]["labels"]["reported_total"])
        self.assertTrue(OBSERVED["coverage"]["labels"]["complete"])
        expected = json.dumps(json.dumps(labels))
        checks = [
            "jsonencode(local.repository_labels) == "
            f"jsonencode(jsondecode({expected}))",
            "alltrue([for name, label in github_issue_label.observed : "
            'label.name == name && label.repository == "oconnordev" && '
            "label.color == local.repository_labels[name].color && "
            "label.description == local.repository_labels[name].description])",
        ]
        self.offline_plan(source, checks)
        self.assertRegex(
            source,
            r"(?s)import \{\s*for_each = local.repository_labels"
            r"\s*to\s*= github_issue_label.observed\[each.key\]"
            r'\s*id\s*= "oconnordev:\$\{each.key\}"\s*\}',
        )


if __name__ == "__main__":
    unittest.main()
