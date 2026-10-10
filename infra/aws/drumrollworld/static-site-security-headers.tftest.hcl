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
  spacelift_run_id = "offline-delivery-test"
}

run "static_security_headers" {
  command = plan

  assert {
    condition     = try(aws_cloudfront_response_headers_policy.drumrollworld.security_headers_config[0].content_security_policy[0].content_security_policy == "default-src 'none'; script-src 'self' 'wasm-unsafe-eval'; script-src-attr 'none'; style-src 'self' 'sha256-47DEQpj8HBSa+/TImW+5JCeuQeRkm5NMpJWZG3hSuFU=' 'sha256-1OVkcrOQP7NV9SqPTIZQMVnSWqtceFiWV3g5XyDm98A=' 'sha256-9xjtvxMT1ApHlgn9ohbh2FNfvK5Tqtzy94BjfXBeMSY=' 'sha256-yfc2FhpkFR0EAy3T+zDsaAFGXSP9B3ELNvaJKDzNhkk=' 'sha256-GRFgt45UbKYCV14/Fqy6H9EB3zlAwSnH4xbsYt03Q6M='; style-src-attr 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; worker-src blob:; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'" && aws_cloudfront_response_headers_policy.drumrollworld.security_headers_config[0].content_security_policy[0].override, false)
    error_message = "Enforce the exact compatible Drumroll CSP, including WASM-only compilation and narrow style hashes. Resume must remain strict."
  }

  assert {
    condition     = try(anytrue([for item in aws_cloudfront_response_headers_policy.drumrollworld.custom_headers_config[0].items : item.header == "Permissions-Policy" && item.override && item.value == "accelerometer=(), autoplay=(), camera=(), display-capture=(), encrypted-media=(), fullscreen=(), geolocation=(), gyroscope=(), magnetometer=(), microphone=(), midi=(), payment=(), picture-in-picture=(), publickey-credentials-get=(), screen-wake-lock=(), usb=(), xr-spatial-tracking=()"]), false)
    error_message = "Sensitive capabilities must be disabled and origin headers overridden."
  }

  assert {
    condition     = aws_cloudfront_response_headers_policy.drumrollworld.security_headers_config[0].strict_transport_security[0].access_control_max_age_sec == 31536000 && aws_cloudfront_response_headers_policy.drumrollworld.security_headers_config[0].strict_transport_security[0].include_subdomains && aws_cloudfront_response_headers_policy.drumrollworld.security_headers_config[0].strict_transport_security[0].preload && aws_cloudfront_response_headers_policy.drumrollworld.security_headers_config[0].strict_transport_security[0].override && aws_cloudfront_response_headers_policy.drumrollworld.security_headers_config[0].content_type_options[0].override && aws_cloudfront_response_headers_policy.drumrollworld.security_headers_config[0].frame_options[0].frame_option == "DENY" && aws_cloudfront_response_headers_policy.drumrollworld.security_headers_config[0].frame_options[0].override && aws_cloudfront_response_headers_policy.drumrollworld.security_headers_config[0].referrer_policy[0].referrer_policy == "strict-origin-when-cross-origin" && aws_cloudfront_response_headers_policy.drumrollworld.security_headers_config[0].referrer_policy[0].override
    error_message = "Preserve all existing security headers."
  }

  assert {
    condition     = aws_cloudfront_distribution.drumrollworld.default_cache_behavior[0].min_ttl == 0 && aws_cloudfront_distribution.drumrollworld.default_cache_behavior[0].default_ttl == 3600 && aws_cloudfront_distribution.drumrollworld.default_cache_behavior[0].max_ttl == 86400 && aws_cloudfront_distribution.drumrollworld.default_cache_behavior[0].viewer_protocol_policy == "redirect-to-https" && aws_cloudfront_distribution.drumrollworld.default_cache_behavior[0].forwarded_values[0].query_string == false && aws_cloudfront_distribution.drumrollworld.default_cache_behavior[0].forwarded_values[0].cookies[0].forward == "none" && aws_cloudfront_origin_access_control.drumrollworld.signing_behavior == "always" && aws_cloudfront_origin_access_control.drumrollworld.signing_protocol == "sigv4"
    error_message = "Preserve TTLs, forwarding, HTTPS redirects and origin authentication."
  }
}
