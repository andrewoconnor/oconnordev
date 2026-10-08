# Cross-account CloudWatch log queries

## Architecture and scope

SECURITY (`482921124454`) is the monitoring account. TOOLS (`421680664125`)
and PRODUCTION (`767397796791`) each create a logs-only OAM link to SECURITY's
`oconnordev-security-logs` sink in **us-east-1**, matching all three AWS roots'
provider region. All existing and future log groups in those source accounts
and that region are shared. Other regions are not configured by this change.

OAM shares visibility without copying log records, changing source retention,
or enabling log delivery for services that currently do not emit logs. Metrics,
traces, organization-wide enrollment, subscription filters, Firehose, S3 log
exports, and Athena log catalogs are not added. Production services with no
CloudWatch log group remain invisible until their logging is separately enabled.

The sink policy permits only TOOLS and PRODUCTION, only `CreateLink` and
`UpdateLink`, and only `AWS::Logs::LogGroup`. The source deploy roles already
have AdministratorAccess; the SECURITY AWS MCP role keeps its existing
ReadOnlyAccess plus explicit secret, KMS-decrypt, and assume-role denies.
Live IAM simulation confirmed `logs:StartQuery`, `logs:GetQueryResults`,
`logs:DescribeLogGroups`, and `oam:ListSinks` are already allowed. No broader
MCP IAM permissions are introduced. Log messages may contain sensitive payloads:
sharing all source groups is intentional, so redact credentials at emission.

`aws_athena_workgroup.hermes_analytics` moves to generic `athena.tf` without
changing its resource address or configuration. Athena remains the billing
query engine; CloudWatch Logs Insights queries logs directly, not via Athena.

## Verified renewal observation

On 2026-10-08, queries from SECURITY successfully read TOOLS's
`/aws/lambda/hermes-spacelift-session-token-rotation` log group. The sampled
24-hour poll query returned 1,439 successful checks, 13 expiry-advancing
publications, and 1,426 same-expiry checks without publication. Observed lifetime
was 10 hours; minimum remaining lifetime was about 7.62 hours. This verifies
TOOLS log-query access, not the existence of PRODUCTION log emitters or a
provider guarantee about renewal timing. See the
[session-token runbook](runbooks/spacelift-session-token.md) for query evidence,
caveats, the 15-minute default cadence, alarm windows, and post-apply checks.

## Cost

CloudWatch cross-account observability for logs has **no additional charge**
and creates no second storage copy. Existing source ingestion/storage charges
remain. Logs Insights queries still incur normal data-scanned charges (AWS's
representative rate is $0.005/GB; verify the region and applicable free tier);
restrict time ranges and select specific groups. A result `limit` is not a
scan-cost cap. This is not covered by Athena's scan
cutoff, and neither the OAM link nor this configuration imposes a query budget.

References:
- https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch-Unified-Cross-Account.html
- https://aws.amazon.com/cloudwatch/pricing/
- https://docs.aws.amazon.com/AmazonCloudWatchLogs/latest/APIReference/API_DescribeLogGroups.html
- https://docs.aws.amazon.com/AmazonCloudWatchLogs/latest/APIReference/API_StartQuery.html

## Rollout after merge

1. Apply the Spacelift root (`oconnordev`) to add sink output references and the
   production-to-security dependency. TOOLS reuses its existing security edge.
2. Apply SECURITY to create its sink and logs-only sink policy. The exported
   `cloudwatch_logs_sink_arn` waits for the policy resource.
3. Apply TOOLS, then PRODUCTION. Spacelift supplies
   `TF_VAR_security_logs_sink_arn` from SECURITY's output. Empty inputs create
   no link during initial setup/PR plans; rerun consumers after the reference
   resolves. A resolved link is not proof of working queries: verify below.
4. For manual runs, set `security_logs_sink_arn` to SECURITY's exact sink output.
   Its validation rejects a different account or region.

No console/API bootstrap is required. OAM is regional and allows only one sink
per monitoring account/region: import an existing sink rather than creating a
second if live state has changed. To delete the sink, remove both source links
first. Destroying a link does not delete source logs.

## Verify through AWS MCP in SECURITY

1. `sts:GetCallerIdentity` must return account `482921124454`.
2. `oam:ListSinks`, then `oam:ListAttachedLinks` with `SinkIdentifier` set to the
   sink ARN must show both source accounts and logs-only resource types.
3. `logs:DescribeLogGroups` in `us-east-1` with `includeLinkedAccounts=true` and
   `accountIdentifiers=["421680664125", "767397796791"]` discovers shared groups.
   No groups from PRODUCTION may simply mean that account has no log emitters;
   do not claim log delivery exists based on a link alone.
4. Start a narrow Logs Insights query through `logs:StartQuery`:

```json
{
  "logGroupIdentifiers": ["arn:aws:logs:us-east-1:421680664125:log-group:/aws/vendedlogs/bedrock-agentcore/gateway/hermes"],
  "startTime": 0,
  "endTime": 1,
  "queryString": "fields @timestamp, @message, @log | sort @timestamp desc | limit 20",
  "limit": 20
}
```

Replace the example epoch bounds with a recent short window and select a real
ARN returned by discovery. Use `logGroupArn`, or strip only a trailing `:*`
from `arn`; cross-account `logGroupIdentifiers` require full source ARNs without
that suffix. Poll `logs:GetQueryResults` with the returned `queryId` until
Complete/Failed/Cancelled/Timeout, and report real status, rows, and bytes scanned.
Do not interpret an empty result as an access failure or invent log events.

The current `kms:Decrypt` deny remains intentional. Customer-managed KMS log
or query-result encryption can require separate KMS policy/permission work;
do not relax it without checking the actual group and approved requirement.
Post-apply verification is required; local mocked tests exercise Terraform's
sink policy and link gates but cannot prove AWS cross-account query execution.
