# Shared AgentCore Gateway log privacy

The TOOLS configuration has no `APPLICATION_LOGS` delivery connection. The
source, destination and `/aws/vendedlogs/bedrock-agentcore/gateway/hermes` log
group remain, with seven-day default retention, the SECURITY OAM link and the
native `UserErrors` alarm. Existing records and external copies are not purged.

Before sensitive reads, verify the applied TOOLS state and enumerate all delivery
pages to confirm no connection remains for the Gateway source. Configuration
alone does not prove the live state. Neither this control nor the Plaid Lambda's
logging behavior proves absence of payloads in other logs.

Gateway `exception_level = "DEBUG"` remains configured and controls error detail
returned to callers; it is separate from application-log delivery.

References: [Gateway logs](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-gateway-metrics.html),
[Gateway DEBUG](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-debug-messages.html),
[CloudWatch cross-account observability](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch-Unified-Cross-Account.html).
