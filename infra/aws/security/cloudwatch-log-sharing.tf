# Regional, logs-only cross-account observability. Source log groups retain
# their existing storage, encryption and retention; no log replication occurs.
resource "aws_oam_sink" "cloudwatch_logs" {
  name = "oconnordev-security-logs"
}

resource "aws_oam_sink_policy" "cloudwatch_logs" {
  sink_identifier = aws_oam_sink.cloudwatch_logs.arn
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "ToolsAndProductionLogsOnly"
      Effect = "Allow"
      Action = ["oam:CreateLink", "oam:UpdateLink"]
      # Sink-scoped resource policy: UpdateLink authorizes a link, not a sink.
      # AWS's documented policy uses * here; account/type restrictions remain.
      Resource = "*"
      Principal = {
        AWS = [
          "arn:aws:iam::${local.accounts["TOOLS"]}:root",
          "arn:aws:iam::${local.accounts["PRODUCTION"]}:root",
        ]
      }
      Condition = {
        "ForAllValues:StringEquals" = {
          "oam:ResourceTypes" = ["AWS::Logs::LogGroup"]
        }
        "Null" = { "oam:ResourceTypes" = "false" }
      }
    }]
  })
}

output "cloudwatch_logs_sink_arn" {
  description = "Logs-only security monitoring sink, exported after its source-account policy is ready."
  value       = aws_oam_sink.cloudwatch_logs.arn
  depends_on  = [aws_oam_sink_policy.cloudwatch_logs]
}
