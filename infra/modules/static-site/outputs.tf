output "deploy_role_arn" { value = aws_iam_role.github_actions_site_deploy.arn }
output "distribution_id" { value = aws_cloudfront_distribution.site.id }
output "distribution_domain_name" { value = aws_cloudfront_distribution.site.domain_name }
output "certificate_arn" { value = var.existing_certificate_arn != null ? var.existing_certificate_arn : aws_acm_certificate.site[0].arn }
output "bucket_name" { value = aws_s3_bucket.web.id }
output "apex_fqdn" { value = aws_route53_record.apex.fqdn }
output "www_fqdn" { value = aws_route53_record.www.fqdn }
output "content_security_policy" { value = aws_cloudfront_response_headers_policy.site.security_headers_config[0].content_security_policy[0].content_security_policy }
output "compression_enabled" { value = aws_cloudfront_distribution.site.default_cache_behavior[0].compress }
output "cache_policy_id" { value = aws_cloudfront_distribution.site.default_cache_behavior[0].cache_policy_id }
output "error_responses" { value = aws_cloudfront_distribution.site.custom_error_response }
# Provider-backed offline contracts inspect the effective inherited settings.
output "distribution" { value = aws_cloudfront_distribution.site }
output "security_headers" { value = aws_cloudfront_response_headers_policy.site }
output "origin_access_control" { value = aws_cloudfront_origin_access_control.site }
output "dns_records" {
  value = {
    apex      = aws_route53_record.apex
    www       = aws_route53_record.www
    apex_ipv6 = aws_route53_record.apex_ipv6
    www_ipv6  = aws_route53_record.www_ipv6
  }
}
