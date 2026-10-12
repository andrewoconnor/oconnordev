# Exercise the production workload HCL offline, without credentials or apply.
mock_provider "aws" {
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
  spacelift_run_id            = "offline-delivery-test"
  site_certificate_arn        = "arn:aws:acm:us-east-1:767397796791:certificate/00000000-0000-0000-0000-000000000000"
  site_zone_id                = "ZOFFLINE"
  site_state_handoff_complete = true
  dnssec_key_arn              = "arn:aws:kms:us-east-1:767397796791:key/00000000-0000-0000-0000-000000000000"
}

run "gzip_uses_managed_compression_cache_policy" {
  command = plan

  assert {
    condition     = module.site.distribution.default_cache_behavior[0].compress == true
    error_message = "CloudFront must compress eligible responses."
  }

  assert {
    condition = (
      module.site.distribution.default_cache_behavior[0].cache_policy_id == "658327ea-f89d-4fab-a63d-7e88639e58f6" &&
      length(module.site.distribution.default_cache_behavior[0].forwarded_values) == 0
    )
    error_message = "Use AWS Managed-CachingOptimized, not incompatible legacy forwarding or behavior TTLs."
  }
}

run "missing_objects_return_real_html_404" {
  command = plan

  assert {
    condition = (
      length(module.site.distribution.custom_error_response) == 2 &&
      toset([for response in module.site.distribution.custom_error_response : response.error_code]) == toset([403, 404]) &&
      alltrue([for response in module.site.distribution.custom_error_response :
        response.response_code == 404 && response.response_page_path == "/404.html" && response.error_caching_min_ttl == 10
      ])
    )
    error_message = "Both S3 missing-object cases must return /404.html with HTTP 404 and a short 10-second error TTL, never the app shell or HTTP 200."
  }
}

run "ipv6_aliases_preserve_routing" {
  command = plan
  assert {
    condition     = module.site.dns_records.apex.type == "A" && module.site.dns_records.www.type == "A" && module.site.dns_records.apex_ipv6.type == "AAAA" && module.site.dns_records.www_ipv6.type == "AAAA" && module.site.dns_records.apex.alias[0].name == module.site.dns_records.www.fqdn && module.site.dns_records.apex_ipv6.alias[0].name == module.site.dns_records.www_ipv6.fqdn
    error_message = "Both IPv4 and IPv6 retain apex -> www -> CloudFront routing."
  }
}

run "handoff_blocks_ordinary_apply" {
  command = plan
  variables {
    site_state_handoff_complete = false
  }
  expect_failures = [terraform_data.site_state_handoff_guard]
}

run "dnssec_requires_explicit_key_arn" {
  command = plan
  variables { dnssec_key_arn = "alias/dnssec" }
  expect_failures = [var.dnssec_key_arn]
}
