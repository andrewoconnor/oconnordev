import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PRODUCTION = ROOT / "infra/aws/production"


class ThundermailDnsAdoptionTests(unittest.TestCase):
    def test_adoption_configuration_exists_and_uses_declarative_imports(self):
        path = PRODUCTION / "thundermail-records.tf"
        self.assertTrue(
            path.is_file(),
            "Exported Thundermail records need an adoption configuration",
        )
        source = path.read_text()
        self.assertIn('resource "aws_route53_record" "thundermail"', source)
        self.assertIn("to       = aws_route53_record.thundermail[each.key]", source)
        self.assertIn('id       = "Z02434432RXWI3WCMIEA2_${each.key}"', source)
        self.assertIn(
            "for_each = var.import_thundermail_records ? "
            "local.thundermail_records : {}",
            source,
        )
        self.assertIn("default     = true", source)
        self.assertNotIn("allow_overwrite", source)
        self.assertNotIn('resource "aws_route53_zone"', source)

    def test_dns_fixture_preserves_mail_and_google_verification(self):
        records = json.loads(
            (PRODUCTION / "testdata/thundermail-records.json").read_text()
        )
        self.assertEqual(len(records), 13)
        self.assertEqual(
            {v["type"] for v in records.values()}, {"MX", "TXT", "CNAME", "SRV"}
        )
        for key, value in records.items():
            self.assertEqual(key, value["name"].removesuffix(".") + "_" + value["type"])
            self.assertEqual(value["ttl"], 300)
            self.assertEqual(
                len(value["records"]), 2 if key == "oconnor.dev_TXT" else 1
            )
        self.assertEqual(
            records["oconnor.dev_TXT"]["records"],
            [
                "v=spf1 include:spf.thundermail.com -all",
                "google-site-verification=IOTKLU1HKY0BJVrAqx6cz17AaIgZH-FT8Mgzb2B2wEs",
            ],
        )


if __name__ == "__main__":
    unittest.main()
