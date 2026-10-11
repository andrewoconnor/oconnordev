# Production retains this shared zone's KSK/DNSSEC resources; do not create a second owner.
check "dnssec_key_account_and_region" {
  assert {
    condition     = startswith(var.dnssec_key_arn, "arn:aws:kms:us-east-1:${local.accounts["PRODUCTION"]}:key/")
    error_message = "DNSSEC signing key must be production's us-east-1 key ARN, never an alias lookup."
  }
}
