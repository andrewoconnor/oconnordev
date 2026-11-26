resource "aws_sns_topic" "alerts" {
  # checkov:skip=CKV_AWS_26:CloudWatch alarms can publish to an encrypted topic only through a customer-managed KMS key, and the AWS managed SNS key cannot grant them access. Alerts carry alarm names and metric values and are delivered by email, so the topic stays unencrypted to avoid a monthly key charge.
  name = "oconnordev-alerts"
}

resource "aws_sns_topic_subscription" "alerts_email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = "andrew@oconnor.dev"
}
