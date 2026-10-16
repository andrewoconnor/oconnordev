# Spacelift session-token renewal

## Ownership and runtime behavior

TOOLS owns `hermes-spacelift-session-token-rotation`. Its EventBridge rule polls
Spacelift's `apiKeyUser` mutation using the read-only API key, verifies the
candidate through MCP tool discovery and a useful read, then conditionally
writes the separate session-token secret. AgentCore's EXTERNAL credential
provider reads that secret on outbound requests; no gateway update is required.

Every successful check emits `rotation_checked`, including checks that do not
publish anything. Use
`token_published` to count secret writes, not the event name. The runtime derives
lifetime from JWT claims, never assumes a fixed provider lifetime, and logs only
metadata, not API keys or token strings.

The publication safeguards are mandatory:

- Reject expired candidates, malformed expiry claims, and regressed expiry.
- Verify the candidate before publication.
- When a different candidate has the same expiry, also verify the stored token.
  Keep a healthy stored token; a definitive authentication rejection permits a
  verified replacement at the same expiry. Transport failures do not permit it.
- Publish a different candidate if the expiry advances or no valid stored expiry
  is available. Preserve the current secret when verification fails.
- Emit the remaining-lifetime metric after a successful check; serialize Lambda
  invocations and retain the existing bounded HTTP/execution timeouts.

## Cadence and alarms

The default `hermes_spacelift_rotation_interval_minutes` is **60**, producing
`rate(60 minutes)`. Whole-number overrides from **1 through 60** are allowed;
use 1 for diagnosis/rollback rather than adding sleeps or expiry-driven scheduling.
Scheduling does not guarantee invocation counts or provider renewal timing.

Alarm periods follow the interval: **3,600 seconds** by default. Preserve the
**7,200-second (two-hour)** remaining-lifetime threshold and missing-data handling.
The stale alarm evaluates two consecutive periods: **2 × 3,600 = 7,200 seconds
(two hours)**, not three hours. It treats missing metric data as breaching.
The Lambda Errors alarm evaluates one period (**one hour** by default) and treats
missing data as not breaching. Poll spacing, metric arrival and CloudWatch's
retrieval of older datapoints can affect when an alarm changes state; do not
add a poll interval to the nominal window and call it a detection guarantee.
These are evaluation windows, not guaranteed detection/delivery deadlines.
Inspect alarm notification wiring separately; alarm evaluation does not guarantee delivery.

## Apply and verify

1. Review the actual TOOLS plan and inspect any
   `TF_VAR_hermes_spacelift_rotation_interval_minutes` override. Only the owner
   applies the existing `oconnordev-tools` stack; defaults do not override inputs.
2. Verify the rule is enabled with `rate(60 minutes)`, both alarm periods are
   3,600 seconds, and the stale threshold remains 7,200 seconds. Confirm a new
   `rotation_checked` event after Lambda deployment.
3. Query several hours of logs through SECURITY and inspect check spacing,
   actual expiry advances, failures, and remaining lifetime. Continue through
   multiple renewal cycles; do not infer success from the Terraform plan alone.
4. If checks become unreliable or remaining lifetime approaches the floor,
   set the interval to **1** through the stack's managed inputs and apply TOOLS.
   This restores one-minute polling and 60-second alarm periods without changing
   publication rules. Diagnose API-key access, minting, verification, secret
   access/write, and metric emission before relaxing safeguards.

## Reproducible Logs Insights queries

Use SECURITY credentials and source ARN
`arn:aws:logs:us-east-1:421680664125:log-group:/aws/lambda/hermes-spacelift-session-token-rotation`, without a trailing
`:*`. Set explicit recent epoch bounds and inspect final query status and
`statistics.bytesScanned`; a result limit does not cap scan cost. See
[the cross-account log-query runbook](../aws-cloudwatch-log-sharing.md).

Successful checks:

```text
filter event = "rotation_checked"
| stats count(*) as polls, min(remaining_seconds) as min_remaining_seconds,
    min(lifetime_seconds) as min_lifetime_seconds,
    max(lifetime_seconds) as max_lifetime_seconds
    by expiry_changed, token_unchanged, token_published
```

Actual publications and metadata (no token strings):

```text
filter event = "rotation_checked" and token_published = true
| fields @timestamp, iat, exp, previous_exp, lifetime_seconds,
    remaining_seconds, expiry_changed, token_published, tool_count
| sort @timestamp asc
| limit 1000
```

Failures, rejected stored tokens, and common runtime-error signals:

```text
filter event in ["failed", "stored_token_unauthenticated"]
    or @message like /Task timed out|Runtime\.|\[ERROR\]|Traceback/
| fields @timestamp, event, stage, error
| sort @timestamp desc
| limit 100
```

A stored-token authentication rejection can be successfully repaired in the same
invocation; distinguish it from an unhandled failure and inspect the subsequent
`token_published` flag. Inspect AWS/Lambda Errors and alarm state separately;
log-pattern matching alone is not exhaustive failure monitoring.
