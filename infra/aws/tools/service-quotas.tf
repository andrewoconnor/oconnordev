# Service Quotas approval is asynchronous. First apply only this quota resource,
# confirm the increased quota is active, then run a full apply so dependent
# resources are created only after approval.
resource "aws_servicequotas_service_quota" "lambda_concurrent_executions" {
  service_code = "lambda"
  quota_code   = "L-B99A9384"
  value        = 1000
}
