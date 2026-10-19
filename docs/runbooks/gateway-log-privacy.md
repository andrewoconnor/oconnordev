# Shared AgentCore Gateway log privacy

## Configuration and boundary

No APPLICATION_LOGS delivery is configured for the shared TOOLS Gateway.
The APPLICATION_LOGS source and destination metadata remain, together with
`/aws/vendedlogs/bedrock-agentcore/gateway/hermes`, seven days default retention,
and the native `AWS/Bedrock-AgentCore` `UserErrors` alarm. Metadata without a
connecting delivery is inert. There is no replacement subscription or sink.
Native metrics remain available; body-bearing application-log diagnostics do not.

Gateway application logs can include MCP request and response bodies. Generic
`record_fields` support is not a proven nested-body redaction mechanism. Do not
assume a metadata-only delivery is payload-free or silently enable one.

## Metadata-only verification

Use an approved read-only TOOLS identity in us-east-1:

1. Enumerate **all pages** of delivery sources and deliveries. Match the Gateway
   ARN and every APPLICATION_LOGS source; require no connection to CloudWatch
   Logs, S3 or Firehose. Out-of-band delivery fails the privacy check.
2. Verify the retained group and `retentionInDays=7`, source/destination metadata,
   and the same Gateway's native UserErrors alarm. Check for replacement sinks
   and subscriptions. Do not read log events or mailbox payloads.
3. Record revision, verification time and sanitized metadata. Repository source
   and successful apply status alone do not exclude out-of-band deliveries.

## Retention and consent limits

Disabling delivery is **not a retroactive purge**. Existing records remain under
retention/expiry; expiry is not instantaneous secure deletion. Copies or exports
outside this group are not covered. The configuration does not prove absence of
sensitive data in runtime, Lambda, client/adapter, upstream, trace/span or other logs.
Runtime suppression and Gateway delivery controls are independent.
No end-to-end no-mailbox-logging guarantee is made.

Re-enabling body-bearing delivery affects every shared target. Pause mail access,
obtain explicit owner privacy approval, review a separate IaC plan, and verify
metadata after owner apply. Mail consent and live verification remain separately authorized operations; see
[Outlook](outlook-mcp.md) and [Google](google-mcp.md).

References: [Gateway observability](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-gateway-metrics.html),
[delivery API](https://docs.aws.amazon.com/AmazonCloudWatchLogs/latest/APIReference/API_CreateDelivery.html),
[configuration templates](https://docs.aws.amazon.com/AmazonCloudWatchLogs/latest/APIReference/API_DescribeConfigurationTemplates.html),
[retention behavior](https://docs.aws.amazon.com/AmazonCloudWatchLogs/latest/APIReference/API_PutRetentionPolicy.html).
