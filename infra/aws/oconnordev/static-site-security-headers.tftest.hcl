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
  spacelift_run_id            = "offline-delivery-test"
  dnssec_key_arn              = "arn:aws:kms:us-east-1:767397796791:key/00000000-0000-0000-0000-000000000000"
  site_certificate_arn        = "arn:aws:acm:us-east-1:767397796791:certificate/00000000-0000-0000-0000-000000000000"
  site_zone_id                = "ZOFFLINE"
  site_state_handoff_complete = true
}

run "static_security_headers" {
  command = plan

  assert {
    condition     = try(module.site.security_headers.security_headers_config[0].content_security_policy[0].content_security_policy == "default-src 'none'; script-src 'sha256-4JHmSUmc1wePxlVTxsVTwn6GgpQ+Oa79jBlKuyYIE5c='; script-src-attr 'none'; style-src 'self'; style-src-attr 'none'; img-src 'self'; connect-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'" && module.site.security_headers.security_headers_config[0].content_security_policy[0].override, false)
    error_message = "Enforce the narrow resume CSP, preserving the inline JSON-LD by hash only."
  }

  assert {
    condition     = try(anytrue([for item in module.site.security_headers.custom_headers_config[0].items : item.header == "Permissions-Policy" && item.override && item.value == "accelerometer=(), autoplay=(), camera=(), display-capture=(), encrypted-media=(), fullscreen=(), geolocation=(), gyroscope=(), magnetometer=(), microphone=(), midi=(), payment=(), picture-in-picture=(), publickey-credentials-get=(), screen-wake-lock=(), usb=(), xr-spatial-tracking=()"]), false)
    error_message = "Sensitive capabilities must be disabled and origin headers overridden."
  }

  assert {
    condition     = module.site.security_headers.security_headers_config[0].strict_transport_security[0].access_control_max_age_sec == 31536000 && module.site.security_headers.security_headers_config[0].strict_transport_security[0].include_subdomains && module.site.security_headers.security_headers_config[0].strict_transport_security[0].preload && module.site.security_headers.security_headers_config[0].strict_transport_security[0].override && module.site.security_headers.security_headers_config[0].content_type_options[0].override && module.site.security_headers.security_headers_config[0].frame_options[0].frame_option == "DENY" && module.site.security_headers.security_headers_config[0].frame_options[0].override && module.site.security_headers.security_headers_config[0].referrer_policy[0].referrer_policy == "strict-origin-when-cross-origin" && module.site.security_headers.security_headers_config[0].referrer_policy[0].override
    error_message = "Preserve all existing security headers."
  }

  assert {
    condition     = module.site.distribution.default_cache_behavior[0].cache_policy_id == "658327ea-f89d-4fab-a63d-7e88639e58f6" && length(module.site.distribution.default_cache_behavior[0].forwarded_values) == 0 && module.site.distribution.default_cache_behavior[0].viewer_protocol_policy == "redirect-to-https" && module.site.origin_access_control.signing_behavior == "always" && module.site.origin_access_control.signing_protocol == "sigv4"
    error_message = "Use the managed compression-aware cache policy, HTTPS redirects and origin authentication."
  }
}
