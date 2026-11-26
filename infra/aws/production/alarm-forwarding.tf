locals {
  tools_default_event_bus_arn = "arn:aws:events:us-east-1:${local.accounts["TOOLS"]}:event-bus/default"
}

resource "aws_iam_role" "alarm_forwarding" {
  name = "oconnordev-alarm-forwarding"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "events.amazonaws.com" }
      Condition = { StringEquals = { "aws:SourceAccount" = local.accounts["PRODUCTION"] } }
    }]
  })
}

resource "aws_iam_role_policy" "alarm_forwarding" {
  name = "put-events-on-tools-default-bus"
  role = aws_iam_role.alarm_forwarding.id
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = "events:PutEvents", Resource = local.tools_default_event_bus_arn }]
  })
}

resource "aws_cloudwatch_event_rule" "alarm_forwarding" {
  name        = "oconnordev-alarm-forwarding"
  description = "Forwards ALARM and OK state changes to the TOOLS default bus for the Hermes alarm webhook."
  event_pattern = jsonencode({
    source        = ["aws.cloudwatch"]
    "detail-type" = ["CloudWatch Alarm State Change"]
    detail        = { state = { value = ["ALARM", "OK"] } }
  })
}

resource "aws_cloudwatch_event_target" "alarm_forwarding" {
  rule     = aws_cloudwatch_event_rule.alarm_forwarding.name
  arn      = local.tools_default_event_bus_arn
  role_arn = aws_iam_role.alarm_forwarding.arn
}
