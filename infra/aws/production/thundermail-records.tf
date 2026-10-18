locals {
  thundermail_records = {
    "oconnor.dev_MX" = {
      name    = "oconnor.dev."
      type    = "MX"
      ttl     = 300
      records = ["10 mail.thundermail.com."]
    }
    "oconnor.dev_TXT" = {
      name = "oconnor.dev."
      type = "TXT"
      ttl  = 300
      records = [
        "v=spf1 include:spf.thundermail.com -all",
        "google-site-verification=IOTKLU1HKY0BJVrAqx6cz17AaIgZH-FT8Mgzb2B2wEs",
      ]
    }
    "_dmarc.oconnor.dev_TXT" = {
      name    = "_dmarc.oconnor.dev."
      type    = "TXT"
      ttl     = 300
      records = ["v=DMARC1; p=none;"]
    }
    "tm1._domainkey.oconnor.dev_CNAME" = {
      name    = "tm1._domainkey.oconnor.dev."
      type    = "CNAME"
      ttl     = 300
      records = ["tm1.oconnor.dev.dkim.thunderhosted.com."]
    }
    "tm2._domainkey.oconnor.dev_CNAME" = {
      name    = "tm2._domainkey.oconnor.dev."
      type    = "CNAME"
      ttl     = 300
      records = ["tm2.oconnor.dev.dkim.thunderhosted.com."]
    }
    "tm3._domainkey.oconnor.dev_CNAME" = {
      name    = "tm3._domainkey.oconnor.dev."
      type    = "CNAME"
      ttl     = 300
      records = ["tm3.oconnor.dev.dkim.thunderhosted.com."]
    }
    "_mta-sts.oconnor.dev_TXT" = {
      name    = "_mta-sts.oconnor.dev."
      type    = "TXT"
      ttl     = 300
      records = ["v=STSv1; id=18139500144460329770"]
    }
    "_caldavs._tcp.oconnor.dev_SRV" = {
      name    = "_caldavs._tcp.oconnor.dev."
      type    = "SRV"
      ttl     = 300
      records = ["0 0 443 mail.thundermail.com"]
    }
    "_carddavs._tcp.oconnor.dev_SRV" = {
      name    = "_carddavs._tcp.oconnor.dev."
      type    = "SRV"
      ttl     = 300
      records = ["0 0 443 mail.thundermail.com"]
    }
    "_imaps._tcp.oconnor.dev_SRV" = {
      name    = "_imaps._tcp.oconnor.dev."
      type    = "SRV"
      ttl     = 300
      records = ["0 0 993 mail.thundermail.com"]
    }
    "_jmap._tcp.oconnor.dev_SRV" = {
      name    = "_jmap._tcp.oconnor.dev."
      type    = "SRV"
      ttl     = 300
      records = ["0 0 443 mail.thundermail.com"]
    }
    "_submission._tcp.oconnor.dev_SRV" = {
      name    = "_submission._tcp.oconnor.dev."
      type    = "SRV"
      ttl     = 300
      records = ["0 0 587 mail.thundermail.com"]
    }
    "_smtp._tls.oconnor.dev_TXT" = {
      name    = "_smtp._tls.oconnor.dev."
      type    = "TXT"
      ttl     = 300
      records = ["v=TLSRPTv1; rua=mailto:postmaster@oconnor.dev"]
    }
  }
}

resource "aws_route53_record" "thundermail" {
  for_each = local.thundermail_records

  zone_id = aws_route53_zone.oconnordev.zone_id
  name    = each.value.name
  type    = each.value.type
  ttl     = each.value.ttl
  records = each.value.records
}

variable "import_thundermail_records" {
  description = "Adopt existing mail records; disabled only for offline provider mocks."
  type        = bool
  default     = true
}

import {
  for_each = var.import_thundermail_records ? local.thundermail_records : {}
  to       = aws_route53_record.thundermail[each.key]
  id       = "Z02434432RXWI3WCMIEA2_${each.key}"
}
