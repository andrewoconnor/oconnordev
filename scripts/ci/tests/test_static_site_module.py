"""Offline structural contracts; provider-backed plans exercise rendered behavior."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


class StaticSiteModuleTests(unittest.TestCase):
    def test_both_sites_inherit_one_delivery_implementation(self):
        module = ROOT / "infra/modules/static-site"
        self.assertTrue(module.is_dir(), "shared static-site module is missing")
        delivery = (module / "delivery.tf").read_text()
        self.assertIn("compress                   = true", delivery)
        self.assertIn("658327ea-f89d-4fab-a63d-7e88639e58f6", delivery)
        self.assertNotIn("forwarded_values", delivery)
        self.assertIn('dynamic "custom_error_response"', delivery)
        for site in ("drumrollworld", "oconnordev"):
            source = (ROOT / f"infra/aws/{site}/site.tf").read_text()
            self.assertIn("../../modules/static-site", source)
            self.assertIn("403", source)
            self.assertIn("404", source)
        records = re.findall(r'resource "aws_route53_record" "([^"]+)"', delivery)
        self.assertTrue({"apex", "www", "apex_ipv6", "www_ipv6"} <= set(records))

    def test_cross_state_handoff_is_fail_closed_and_keeps_shared_zone(self):
        production = ROOT / "infra/aws/production"
        self.assertTrue(
            (production / "site-handoff.tf").exists(),
            "safe cross-state handoff missing",
        )
        source = (production / "site-handoff.tf").read_text()
        self.assertIn("destroy = false", source)
        self.assertNotIn("from = aws_route53_zone.oconnordev", source)
        self.assertNotIn(
            "from = aws_acm_certificate.oconnordev",
            source,
            "shared wildcard certificate stays with Hermes to avoid a dependency cycle",
        )
        self.assertIn(
            "aws_acm_certificate", (production / "site-certificate.tf").read_text()
        )
        self.assertIn("precondition", source)
        self.assertRegex(source, r"default\s*=\s*false")
        self.assertTrue((ROOT / "scripts/infra/transfer_static_site_state.py").exists())
        drum = (ROOT / "infra/aws/drumrollworld/moved.tf").read_text()
        self.assertIn("from = aws_cloudfront_distribution.drumrollworld", drum)
        self.assertRegex(
            drum, r"to\s*=\s*module\.site\.aws_cloudfront_distribution\.site"
        )

    def test_shared_module_changes_select_both_consumers(self):
        import sys

        sys.path.insert(0, str(ROOT / "scripts/ci"))
        from path_selection import roots_for_paths

        self.assertEqual(
            roots_for_paths(["infra/modules/static-site/delivery.tf"]),
            ("infra/aws/drumrollworld", "infra/aws/oconnordev"),
        )
        dependencies = (ROOT / "infra/spacelift/dependencies.tf").read_text()
        self.assertIn("TF_VAR_dnssec_key_arn", dependencies)
        self.assertIn("TF_VAR_site_zone_id", dependencies)
        self.assertIn('accounts["oconnordev"]', dependencies)
        config = (ROOT / ".tflint.hcl").read_text()
        self.assertIn('plugin "aws"', config)
        self.assertIn('preset = "recommended"', config)


if __name__ == "__main__":
    unittest.main()
