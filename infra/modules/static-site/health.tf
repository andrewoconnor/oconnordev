resource "aws_route53_health_check" "site" {
  fqdn              = var.domain_name
  port              = 443
  type              = "HTTPS_STR_MATCH"
  resource_path     = "/"
  search_string     = var.health_check_search_string
  enable_sni        = true
  request_interval  = 30
  failure_threshold = 3
  regions           = ["us-east-1", "us-west-1", "us-west-2"]

  tags = {
    Name = "${var.name}-site"
  }
}

resource "aws_cloudwatch_metric_alarm" "site_unhealthy" {
  alarm_name          = "${var.name}-site-unhealthy"
  alarm_description   = "Route 53 health checkers could not load https://${var.domain_name}/ with the expected content for five consecutive minutes."
  namespace           = "AWS/Route53"
  metric_name         = "HealthCheckStatus"
  statistic           = "Minimum"
  period              = 60
  evaluation_periods  = 5
  threshold           = 1
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "breaching"
  alarm_actions       = [var.alert_topic_arn]
  ok_actions          = [var.alert_topic_arn]

  dimensions = {
    HealthCheckId = aws_route53_health_check.site.id
  }
}
