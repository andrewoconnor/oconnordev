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

run "gzip_preserves_legacy_cache_behavior" {
  command = plan

  assert {
    condition     = aws_cloudfront_distribution.drumrollworld.default_cache_behavior[0].compress == true
    error_message = "CloudFront must compress eligible responses."
  }

  assert {
    condition = (
      aws_cloudfront_distribution.drumrollworld.default_cache_behavior[0].min_ttl == 0 &&
      aws_cloudfront_distribution.drumrollworld.default_cache_behavior[0].default_ttl == 3600 &&
      aws_cloudfront_distribution.drumrollworld.default_cache_behavior[0].max_ttl == 86400 &&
      aws_cloudfront_distribution.drumrollworld.default_cache_behavior[0].forwarded_values[0].query_string == false &&
      aws_cloudfront_distribution.drumrollworld.default_cache_behavior[0].forwarded_values[0].cookies[0].forward == "none" &&
      length(aws_cloudfront_distribution.drumrollworld.default_cache_behavior[0].forwarded_values[0].headers) == 0 &&
      aws_cloudfront_distribution.drumrollworld.default_cache_behavior[0].cache_policy_id == null
    )
    error_message = "Keep legacy forwarding and TTLs; do not migrate to a cache policy."
  }
}

run "missing_objects_return_real_html_404" {
  command = plan

  assert {
    condition = (
      length(aws_cloudfront_distribution.drumrollworld.custom_error_response) == 2 &&
      toset([for response in aws_cloudfront_distribution.drumrollworld.custom_error_response : response.error_code]) == toset([403, 404]) &&
      alltrue([for response in aws_cloudfront_distribution.drumrollworld.custom_error_response :
        response.response_code == 404 && response.response_page_path == "/404.html" && response.error_caching_min_ttl == 10
      ])
    )
    error_message = "Both S3 missing-object cases must return /404.html with HTTP 404 and a short 10-second error TTL, never the app shell or HTTP 200."
  }
}
