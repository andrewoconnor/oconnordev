data "aws_kms_key" "dnssec" {
  key_id = "alias/dnssec"
}

resource "aws_route53_hosted_zone_dnssec" "drumrollworld" {
  depends_on = [
    aws_route53_key_signing_key.drumrollworld
  ]
  hosted_zone_id = aws_route53_key_signing_key.drumrollworld.hosted_zone_id
}

resource "aws_route53_key_signing_key" "drumrollworld" {
  hosted_zone_id             = aws_route53_zone.drumrollworld.id
  key_management_service_arn = data.aws_kms_key.dnssec.arn
  name                       = local.zone_name
}

resource "aws_route53_zone" "drumrollworld" {
  # checkov:skip=CKV2_AWS_39:Query logging would need a CloudWatch log group and pay per ingested byte, and a public zone's query log is high-volume and low-value for a personal domain whose records are all managed here.
  name = local.zone_name
}