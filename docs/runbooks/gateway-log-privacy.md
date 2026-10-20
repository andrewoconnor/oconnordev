# Shared AgentCore Gateway diagnostics

The TOOLS Gateway delivers `APPLICATION_LOGS` to its existing
`/aws/vendedlogs/bedrock-agentcore/gateway/hermes` CloudWatch log group in us-east-1.
The existing OAM link makes that group readable from SECURITY without copying logs.
Retention stays at seven days, and the native `UserErrors` alarm is unchanged.
No new bucket, forwarding service, log group, or IAM permissions are required.

Delivery is temporarily enabled for Schwab troubleshooting. These logs can contain
request/response bodies for every shared target, not just Schwab. Pause unrelated
mail and financial reads; inspect only relevant bounded events and redact secrets
before sharing diagnostics. `record_fields` is not assumed to redact nested bodies.

## Apply and verify

1. Apply `oconnordev-tools`; only the connecting log-delivery resource is added.
2. Issue one bounded Schwab request. Through the existing AgentCore AWS reader in
   SECURITY, discover the group using `includeLinkedAccounts=true`, then read its
   full log-group ARN without the trailing `:*`. Verify fresh timestamps and the
   matching tool/error; a successful apply alone is not evidence of delivered logs.

## Disable after troubleshooting

Remove `aws_cloudwatch_log_delivery.gateway_application_logs` and apply TOOLS again.
Keep the source, destination, log group, seven-day retention, OAM link and alarm.
Enumerate all delivery pages to confirm no other connection remains for the source.
Stopping delivery does not purge existing records or external copies.

Gateway `exception_level = "DEBUG"` controls error detail returned to callers;
it is separate from application-log delivery. Disable caller-facing DEBUG separately
when diagnosis is complete. Neither control proves absence of payloads in other logs.

References: [Gateway logs](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-gateway-metrics.html),
[Gateway DEBUG](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-debug-messages.html),
[CloudWatch cross-account observability](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch-Unified-Cross-Account.html).
