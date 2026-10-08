# Spacelift session-token renewal

## Ownership and runtime behavior

TOOLS owns `hermes-spacelift-session-token-rotation`. Its EventBridge rule polls
Spacelift's `apiKeyUser` mutation using the read-only API key, verifies the
candidate through MCP tool discovery and a useful read, then conditionally
writes the separate session-token secret. AgentCore's EXTERNAL credential
provider reads that secret on outbound requests; no gateway update is required.

Every successful check emits `rotation_checked`, including checks that do not
publish anything. Historical logs used `rotated` for the same event. Use
`token_published` to count secret writes, not the event name. The runtime derives
lifetime from JWT claims, never assumes a fixed provider lifetime, and logs only
metadata, not API keys or token strings.

The publication safeguards remain unchanged:

- Reject expired candidates, malformed expiry claims, and regressed expiry.
- Verify the candidate before publication.
- When a different candidate has the same expiry, also verify the stored token.
  Keep a healthy stored token; a definitive authentication rejection permits a
  verified replacement at the same expiry. Transport failures do not permit it.
- Publish a different candidate if the expiry advances or no valid stored expiry
  is available. Preserve the current secret when verification fails.
- Emit the remaining-lifetime metric after a successful check; serialize Lambda
  invocations and retain the existing bounded HTTP/execution timeouts.

## Observed behavior, not a provider guarantee

On **2026-10-08**, CloudWatch Logs Insights queries through the SECURITY AWS MCP
successfully read the TOOLS log group in `us-east-1`:

`arn:aws:logs:us-east-1:421680664125:log-group:/aws/lambda/hermes-spacelift-session-token-rotation`

The 24-hour poll-behavior query ending shortly after **18:20 UTC** completed and
returned these aggregates (timestamps below are successful events, not exact
query bounds):

- 1,439 successful checks, approximately one per minute.
- 13 checks advanced expiry and published a token.
- 1,426 checks returned a different token string with the same expiry and did
  not publish it. Different token bytes alone do not prove renewal.
- Observed JWT lifetime was 36,000 seconds (10 hours).
- Minimum remaining lifetime was 27,421.072 seconds (about 7.62 hours).
- Most expiry advances were roughly 2–2.4 hours apart, with some shorter gaps.
- The last sampled check, **2026-10-08 18:20:11.732 UTC**, had
  `expiry_changed=false`, `token_published=false`, `tool_count=3`, and
  `remaining_seconds=29040.88`.
- The runtime-error query completed with zero matches in its 24-hour window;
  the separate failure query also completed with zero matches. This is a bounded
  observation, not proof that failures cannot occur or every invocation succeeded.

Evidence: poll-behavior query `faaf8617-4c2a-407e-ad9b-43ca9bd5c3ed`
scanned 1,059,604 bytes; runtime-error query
`55af598a-f23c-4572-9311-37bcb9ed7db5` and failure query
`ce4042fc-525b-450e-a1f8-dde82d8ad82c` both completed with empty results.
Query IDs are audit references, not durable storage; re-run the queries below
within source log retention (14 days by default).

These observations support less frequent polling. They do **not** establish a
contractual renewal cadence or show recovery after renewal fails through actual
expiry: early renewal prevented observing that boundary. Keep all safeguards.

## Cadence and alarms

The default `hermes_spacelift_rotation_interval_minutes` is **15**, producing
`rate(15 minutes)`. Whole-number overrides from **1 through 15** are allowed;
use 1 for diagnosis/rollback rather than adding sleeps or expiry-driven scheduling.
The theoretical schedule drops from 1,440 to 96 checks/day (about 93% fewer),
not a guaranteed invocation count or a dollar savings estimate.

Alarm periods follow the interval: **900 seconds** by default. Preserve the
**7,200-second (two-hour)** remaining-lifetime threshold and missing-data handling.
The stale alarm evaluates two consecutive periods (a nominal **30-minute**
evaluation window rather than two minutes); it treats missing metric data as
breaching. The Lambda Errors alarm evaluates one period (15 minutes by default).
These are evaluation windows, not guaranteed detection/delivery deadlines.
Existing alarms do not gain new notification actions in this change.

## Apply and verify

1. Merge, then apply the existing **`oconnordev-tools`** Spacelift stack. This
   updates the EventBridge schedule, alarm periods, and Lambda code/event name;
   it does not create a replacement gateway, role, or secret. Check for an
   explicit `TF_VAR_hermes_spacelift_rotation_interval_minutes` override: the new
   default does not override an existing stack/context value.
2. Verify the rule is enabled with `rate(15 minutes)`, both alarm periods are
   900 seconds, and the stale threshold remains 7,200 seconds. Confirm a new
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

Use SECURITY credentials and the full source ARN above, without a trailing
`:*`. Set explicit recent epoch bounds and inspect final query status and
`statistics.bytesScanned`; a result limit does not cap scan cost. See
[the cross-account log-query runbook](../aws-cloudwatch-log-sharing.md).

Successful checks, compatible with both event names:

```text
filter event in ["rotated", "rotation_checked"]
| stats count(*) as polls, min(remaining_seconds) as min_remaining_seconds,
    min(lifetime_seconds) as min_lifetime_seconds,
    max(lifetime_seconds) as max_lifetime_seconds
    by expiry_changed, token_unchanged, token_published
```

Actual publications and metadata (no token strings):

```text
filter event in ["rotated", "rotation_checked"] and token_published = true
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
