import importlib.util
import re
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]


class ImagePublishContractTests(unittest.TestCase):
    def test_actual_publish_guard_only_allows_master_push_or_manual(self):
        workflow = (ROOT / ".github/workflows/microsoft365-image.yml").read_text()
        publish = workflow.split("  publish:\n", 1)[1]
        match = re.search(r"^    if: (.+)$", publish, re.MULTILINE)
        self.assertIsNotNone(match, "publish job must have an explicit guard")
        assert match is not None
        guard = match.group(1)
        self.assertEqual(
            guard,
            "github.ref == 'refs/heads/master' && "
            "(github.event_name == 'push' || github.event_name == 'workflow_dispatch')",
        )
        # Evaluate the actual job expression, after constraining its entire grammar
        # above, rather than duplicating the intended predicate in the test.
        expression = guard.replace("&&", "and").replace("||", "or")
        for ref in (
            "refs/heads/master",
            "refs/heads/hermes/feature",
            "refs/heads/feature",
            "refs/pull/123/merge",
        ):
            for event in (
                "push",
                "workflow_dispatch",
                "pull_request",
                "pull_request_target",
            ):
                with self.subTest(ref=ref, event=event):
                    allowed = eval(
                        expression,
                        {"__builtins__": {}},
                        {"github": SimpleNamespace(ref=ref, event_name=event)},
                    )
                    self.assertEqual(
                        allowed,
                        ref == "refs/heads/master"
                        and event in ("push", "workflow_dispatch"),
                    )

    def test_same_tested_archive_and_freshness_precede_scoped_credentials(self):
        workflow = (ROOT / ".github/workflows/microsoft365-image.yml").read_text()
        check, publish = workflow.split("  publish:\n", 1)
        self.assertNotIn("id-token: write", check)
        self.assertNotIn("configure-aws-credentials", check)
        self.assertIn("--network none", check)
        self.assertIn("docker save microsoft365-tested:local", check)
        self.assertIn("needs: check", publish)
        credentials = publish.index("uses: aws-actions/configure-aws-credentials")
        for fragment in (
            "sha256sum --check --strict",
            "docker load --input release/image.tar",
            'test "$(docker image inspect',
            'microsoft365_image.py "$EXPECTED_SHA"',
        ):
            self.assertLess(publish.index(fragment), credentials)
        self.assertNotIn("docker build", publish)
        self.assertEqual(workflow.count("name: microsoft365-${{ github.sha }}"), 2)
        self.assertIn("allowed-account-ids: '421680664125'", publish)
        self.assertIn("role/hermes-microsoft365-image-publisher", publish)
        self.assertIn("--repository-name oconnordev-tools", publish)
        self.assertIn('test "$DIGEST" = "$PUSH_DIGEST"', publish)
        for forbidden in (
            "update-function-code",
            "update-function-configuration",
            "tofu apply",
        ):
            self.assertNotIn(forbidden, workflow)


class ImageFreshnessTests(unittest.TestCase):
    def test_compares_every_application_input_before_credentials(self):
        path = Path(__file__).resolve().parents[1] / "microsoft365_image.py"
        self.assertTrue(path.exists(), "missing image publication guard")
        spec = importlib.util.spec_from_file_location("image_guard", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for item in [
            "infra/tools/lambdas/microsoft365_mcp/server.mjs",
            ".github/workflows/microsoft365-image.yml",
            "scripts/ci/microsoft365_image.py",
            "agents/hermes/adapter/microsoft365-mcp-tools.json",
        ]:
            self.assertTrue(module.is_image_input(item), item)
        self.assertFalse(module.is_image_input("apps/oconnordev/index.html"))
        self.assertEqual(
            module.check_image_metadata(
                {"Architecture": "arm64", "Os": "linux", "Id": "sha256:abc"}
            ),
            "sha256:abc",
        )
        with self.assertRaises(ValueError):
            module.check_image_metadata(
                {"Architecture": "amd64", "Os": "linux", "Id": "sha256:abc"}
            )
