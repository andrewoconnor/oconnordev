# Exercise the production workload HCL offline, without credentials or apply.
mock_provider "aws" {
  mock_data "aws_partition" {
    defaults = { partition = "aws" }
  }
  mock_resource "aws_iam_role" {
    defaults = { arn = "arn:aws:iam::767397796791:role/offline-test" }
  }
  mock_resource "aws_kms_key" {
    defaults = { arn = "arn:aws:kms:us-east-1:767397796791:key/00000000-0000-0000-0000-000000000000" }
  }
  mock_data "aws_kms_key" {
    defaults = {
      arn = "arn:aws:kms:us-east-1:767397796791:key/00000000-0000-0000-0000-000000000000"
    }
  }
  mock_data "aws_iam_policy_document" {
    defaults = {
      json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}"
    }
  }
  mock_resource "aws_acm_certificate" {
    defaults = {
      arn = "arn:aws:acm:us-east-1:767397796791:certificate/00000000-0000-0000-0000-000000000000"
    }
  }
}

variables {
  spacelift_run_id = "offline-delivery-test"
}


run "handoff_blocks_production_apply" {
  command         = plan
  expect_failures = [terraform_data.site_state_handoff_guard]
}
run "shared_zone_certificate_and_dnssec_stay_production" {
  command = plan
  variables { site_state_handoff_complete = true }
  assert {
    condition     = aws_route53_zone.oconnordev.name == "oconnor.dev" && aws_acm_certificate.oconnordev.domain_name == "oconnor.dev" && contains(aws_acm_certificate.oconnordev.subject_alternative_names, "*.oconnor.dev") && aws_route53_key_signing_key.oconnordev.key_management_service_arn == aws_kms_key.dnssec.arn
    error_message = "Shared zone, wildcard certificate and DNSSEC must stay in production for Hermes MCP."
  }
}
