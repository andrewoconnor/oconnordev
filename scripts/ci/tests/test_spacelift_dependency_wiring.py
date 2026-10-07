from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DEPENDENCIES_FILE = REPO_ROOT / "infra/spacelift/dependencies.tf"


def resource_body(resource_type: str, resource_name: str) -> str:
    source = DEPENDENCIES_FILE.read_text(encoding="utf-8")
    match = re.search(
        rf'resource\s+"{re.escape(resource_type)}"\s+"{re.escape(resource_name)}"\s*\{{(.*?)\n\}}',
        source,
        flags=re.DOTALL,
    )
    if match is None:
        raise AssertionError(
            f"Missing {resource_type}.{resource_name} in {DEPENDENCIES_FILE}"
        )
    return match.group(1)


class SpaceliftDependencyWiringTests(unittest.TestCase):
    def test_required_stack_dependency_edges_are_declared(self):
        expected = {
            "production_tools_gateway": (
                'spacelift_stack.accounts["production"].id',
                'spacelift_stack.accounts["tools"].id',
            ),
            "tools_security_gateway": (
                'spacelift_stack.accounts["tools"].id',
                'spacelift_stack.accounts["security"].id',
            ),
            "github_repository_config_production": (
                "spacelift_stack.github_repository_config[0].id",
                'spacelift_stack.accounts["production"].id',
            ),
            "github_repository_config_tools": (
                "spacelift_stack.github_repository_config[0].id",
                'spacelift_stack.accounts["tools"].id',
            ),
        }
        for name, (stack_id, depends_on_stack_id) in expected.items():
            with self.subTest(dependency=name):
                body = resource_body("spacelift_stack_dependency", name)
                self.assertIn(f"stack_id            = {stack_id}", body)
                self.assertIn(f"depends_on_stack_id = {depends_on_stack_id}", body)

    def test_required_outputs_are_wired_to_the_consumer_inputs(self):
        expected = {
            "production_tools_gateway_origin": (
                "production_tools_gateway",
                "tools_gateway_origin_hostname",
                "TF_VAR_hermes_gateway_origin_hostname",
            ),
            "tools_security_gateway_url": (
                "tools_security_gateway",
                "security_gateway_url",
                "TF_VAR_security_gateway_url",
            ),
            "tools_security_gateway_arn": (
                "tools_security_gateway",
                "security_gateway_arn",
                "TF_VAR_security_gateway_arn",
            ),
            "github_repository_config_deploy_role_arn": (
                "github_repository_config_production[0]",
                "oconnordev_site_deploy_role_arn",
                "TF_VAR_oconnordev_site_deploy_role_arn",
            ),
            "github_repository_config_cloudfront_id": (
                "github_repository_config_production[0]",
                "oconnordev_cloudfront_distribution_id",
                "TF_VAR_oconnordev_cloudfront_distribution_id",
            ),
            "github_repository_config_tools_broker_role_arn": (
                "github_repository_config_tools[0]",
                "tools_github_actions_broker_role_arn",
                "TF_VAR_oconnordev_tools_github_actions_broker_role_arn",
            ),
        }
        for name, (dependency, output_name, input_name) in expected.items():
            with self.subTest(reference=name):
                body = resource_body("spacelift_stack_dependency_reference", name)
                self.assertIn(f"spacelift_stack_dependency.{dependency}.id", body)
                self.assertIn(f'output_name         = "{output_name}"', body)
                self.assertIn(f'input_name          = "{input_name}"', body)

    def test_optional_repository_configuration_edges_share_the_stack_gate(self):
        for name in (
            "github_repository_config_production",
            "github_repository_config_deploy_role_arn",
            "github_repository_config_cloudfront_id",
            "github_repository_config_tools",
            "github_repository_config_tools_broker_role_arn",
        ):
            with self.subTest(resource=name):
                body = resource_body(
                    "spacelift_stack_dependency"
                    if name.endswith(("production", "tools"))
                    else "spacelift_stack_dependency_reference",
                    name,
                )
                self.assertIn(
                    "count = var.enable_github_repository_config ? 1 : 0", body
                )


if __name__ == "__main__":
    unittest.main()
