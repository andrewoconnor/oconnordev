import importlib.util
import unittest
from pathlib import Path


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
