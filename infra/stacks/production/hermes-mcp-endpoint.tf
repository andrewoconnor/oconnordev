variable "hermes_gateway_origin_hostname" {
  description = "Public AgentCore Gateway hostname exported by the Hermes stack through a Spacelift dependency reference."
  type        = string
  default     = ""

  validation {
    condition     = var.hermes_gateway_origin_hostname == "" || can(regex("^[a-z0-9-]+\\.gateway\\.bedrock-agentcore\\.[a-z0-9-]+\\.amazonaws\\.com$", var.hermes_gateway_origin_hostname))
    error_message = "Set an AgentCore Gateway hostname only (no scheme, path, or credentials)."
  }
}

data "aws_cloudfront_cache_policy" "hermes_mcp_disabled" {
  name = "Managed-CachingDisabled"
}

data "aws_cloudfront_origin_request_policy" "hermes_mcp_all_viewer_except_host" {
  name = "Managed-AllViewerExceptHostHeader"
}

data "aws_cloudfront_response_headers_policy" "hermes_mcp_security" {
  name = "Managed-SecurityHeadersPolicy"
}

locals {
  # The current production certificate covers *.oconnor.dev. It does not cover
  # mcp.hermes.oconnor.dev, so use the covered one-label name.
  hermes_mcp_domain_name = "mcp.oconnor.dev"
  hermes_mcp_enabled     = trimspace(var.hermes_gateway_origin_hostname) != ""
}

resource "aws_cloudfront_distribution" "hermes_mcp" {
  count = local.hermes_mcp_enabled ? 1 : 0

  # checkov:skip=CKV_AWS_310:Single AgentCore origin has no independent failover endpoint.
  # checkov:skip=CKV_AWS_374:This public MCP endpoint is intended for worldwide use; geo restrictions would block traveling clients.
  # checkov:skip=CKV_AWS_68:Cognito JWT authorization and Cedar enforce access; avoid fixed WAF cost for this personal endpoint.
  # checkov:skip=CKV_AWS_86:Access logs are intentionally disabled to avoid storage cost and retained request metadata.
  # checkov:skip=CKV2_AWS_47:No WAF is attached by design; AgentCore JWT authorization and Cedar policies enforce access.

  origin {
    domain_name = var.hermes_gateway_origin_hostname
    origin_id   = "hermes-agentcore-gateway"
    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }

  enabled             = true
  is_ipv6_enabled     = true
  default_root_object = "mcp"
  aliases             = [local.hermes_mcp_domain_name]
  price_class         = "PriceClass_100"

  default_cache_behavior {
    allowed_methods            = ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"]
    cached_methods             = ["GET", "HEAD"]
    target_origin_id           = "hermes-agentcore-gateway"
    cache_policy_id            = data.aws_cloudfront_cache_policy.hermes_mcp_disabled.id
    origin_request_policy_id   = data.aws_cloudfront_origin_request_policy.hermes_mcp_all_viewer_except_host.id
    response_headers_policy_id = data.aws_cloudfront_response_headers_policy.hermes_mcp_security.id
    viewer_protocol_policy     = "https-only"
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    acm_certificate_arn      = aws_acm_certificate.oconnordev.arn
    minimum_protocol_version = "TLSv1.2_2021"
    ssl_support_method       = "sni-only"
  }
}

resource "aws_route53_record" "hermes_mcp_ipv4" {
  count = local.hermes_mcp_enabled ? 1 : 0

  zone_id = aws_route53_zone.oconnordev.zone_id
  name    = local.hermes_mcp_domain_name
  type    = "A"

  alias {
    name                   = aws_cloudfront_distribution.hermes_mcp[0].domain_name
    zone_id                = aws_cloudfront_distribution.hermes_mcp[0].hosted_zone_id
    evaluate_target_health = false
  }
}

resource "aws_route53_record" "hermes_mcp_ipv6" {
  count = local.hermes_mcp_enabled ? 1 : 0

  zone_id = aws_route53_zone.oconnordev.zone_id
  name    = local.hermes_mcp_domain_name
  type    = "AAAA"

  alias {
    name                   = aws_cloudfront_distribution.hermes_mcp[0].domain_name
    zone_id                = aws_cloudfront_distribution.hermes_mcp[0].hosted_zone_id
    evaluate_target_health = false
  }
}

output "hermes_mcp_endpoint" {
  description = "Custom HTTPS endpoint for the shared Hermes AgentCore Gateway; null until the upstream Gateway hostname is available."
  value       = local.hermes_mcp_enabled ? "https://${local.hermes_mcp_domain_name}/mcp" : null
}
