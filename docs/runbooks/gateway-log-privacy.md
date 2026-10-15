# Shared AgentCore Gateway log privacy

## Decision and status

The owner explicitly approved disabling shared Gateway body logging through a
separate IaC PR #118, now merged and applied. TOOLS apply run
`01M50PH738EP65ZF66HKX7CZMT0` is `FINISHED`, with **0 add, 0 change, 1 destroy**;
`aws_cloudwatch_log_delivery.gateway_application_logs` was removed from managed
state. The privacy apply gate is cleared on that apply/state evidence. This is
not independent direct AWS enumeration, proof against out-of-band deliveries, or
an end-to-end no-logging guarantee. The metadata-only checks below remain the
procedure for stronger direct AWS verification. Microsoft365 runtime stays
disabled while OAuth/cache bootstrap and separate activation proofs are pending.

Remove only `aws_cloudwatch_log_delivery.gateway_application_logs`. Preserve the
APPLICATION_LOGS source and destination metadata, existing log group
`/aws/vendedlogs/bedrock-agentcore/gateway/hermes`, its seven days default retention,
and the native `AWS/Bedrock-AgentCore` `UserErrors` alarm. Source/destination
metadata without a connecting delivery is inert. No new sink, subscription,
service, Gateway replacement, auth/Cognito change or Cedar change is introduced.

## Capability evidence and tradeoff

Current official AWS references:

* [Gateway observability data](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-gateway-metrics.html)
  documents vended MCP request/response bodies, with `requestBody` and
  `responseBody` nested within `body`, as well as independently published native
  invocation/error metrics.
* [CreateDelivery](https://docs.aws.amazon.com/AmazonCloudWatchLogs/latest/APIReference/API_CreateDelivery.html)
  defines a delivery as the source-to-destination connection. `recordFields` is a
  list of record fields, with source-mandatory fields required; this is not a
  documented nested `body.requestBody`/`body.responseBody` redaction setting.
* [DescribeConfigurationTemplates](https://docs.aws.amazon.com/AmazonCloudWatchLogs/latest/APIReference/API_DescribeConfigurationTemplates.html)
  returns source-specific allowed/mandatory fields and defaults. A generic API
  field is not proof that a metadata-only selection works for this source.
* [DeleteDelivery](https://docs.aws.amazon.com/AmazonCloudWatchLogs/latest/APIReference/API_DeleteDelivery.html)
  removes the source/destination connection, not the retained log group.

The actual initialized, lockfile-pinned AWS **6.66.0** provider schema was inspected
with `tofu providers schema -json`. `aws_cloudwatch_log_delivery` exposes
`record_fields`, `field_delimiter`, destination/source references and S3 delivery
configuration, but no body-exclusion switch. Its delivery-source schema has no
body-exclusion configuration either. We did **not** establish an exact supported
and proven Gateway metadata-only setting; do not invent one or claim AWS has no
field-selection API. The conservative approved implementation disables this
APPLICATION_LOGS delivery entirely, including diagnostic/error and policy-related
log detail, rather than preserving an unproven payload-free subset. The native
metrics/alarm remain; log-derived diagnostics from this delivery do not.

## Owner plan/apply and verification gate

1. Review the separate PR and exact-head checks. With the prior delivery managed
   and no unrelated drift, expect **0 add, 0 change, 1 destroy**, solely
   `aws_cloudwatch_log_delivery.gateway_application_logs`. This is the expected
   shape, now matched by the recorded apply above. Stop on Gateway/auth/Cedar
   replacement,
   log-group deletion, retention change, replacement sink or unrelated changes.
2. Owner merges and applies the reviewed TOOLS plan (`autodeploy=false`). No apply,
   deploy, mail access, secret read, log-event read or live write is authorized by
   this implementation. Do not use a manual DeleteDelivery call to bypass IaC.
3. Using the approved read-only TOOLS identity in us-east-1, enumerate **all pages**
   of delivery sources and deliveries. Match the Gateway ARN and APPLICATION_LOGS
   source(s), not merely the historical delivery ID/name; require no connection
   to CloudWatch Logs, S3 or Firehose for this Gateway's APPLICATION_LOGS. An extra
   out-of-band delivery is a failed gate, not covered by this resource removal.
4. Read metadata only: verify the retained log group still exists with
   `retentionInDays=7`, source/destination metadata remains, and the UserErrors
   alarm still targets the same Gateway/native namespace. Confirm no replacement
   subscription/sink was introduced. Do not read log events or mailbox payloads.
   Metadata verification proves configuration, not an end-to-end absence of data.
5. Record actual apply/run revision, verification time and sanitized metadata
   results before allowing the separate Microsoft365 activation procedure. This
   runbook does not enable that runtime or authorize a live mailbox test.

## Historical data and limits

Disabling delivery is **not a retroactive purge**. Prior request/response bodies
remain under the existing seven days retention/expiration policy. CloudWatch
expiry is not an instantaneous secure deletion guarantee: AWS documents that
physical deletion typically takes up to 72 hours after expiry, sometimes longer
([retention behavior](https://docs.aws.amazon.com/AmazonCloudWatchLogs/latest/APIReference/API_PutRetentionPolicy.html)).
Do not delete the group, streams, or mail payload data as part of this change.
Any historical copies/exports outside this group are not purged by this change.

The recorded apply removes the configured Gateway APPLICATION_LOGS delivery;
independent metadata enumeration is still needed to exclude out-of-band delivery.
It does not prove absence of sensitive data in runtime, Lambda,
client/adapter, upstream, trace/span or other logs. Runtime log suppression does
not suppress Gateway logs; conversely removing Gateway delivery does not suppress
runtime logs. No end-to-end no-mailbox-logging guarantee is made.

## Rollback

Recreating the prior delivery restores body-bearing application logging for every
shared Gateway target. Do not do that silently: disable/pause mail activation,
obtain explicit owner privacy approval, review a separate IaC plan and verify its
metadata after owner apply. Existing source/destination/group remain available;
no new paid logging service or alternate payload sink is needed or approved.
