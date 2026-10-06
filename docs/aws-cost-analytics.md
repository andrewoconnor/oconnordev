# AWS organization cost analytics for Hermes

## Ownership and paths

`infra/aws/accounts.json` maps GENERAL to `905418422177` and SECURITY to `482921124454`; the repository treats GENERAL as the organization management/payer root. `infra/aws/security/gateway.tf` declares the gateway execution role as `arn:aws:iam::482921124454:role/oconnordev-security-gateway`. **Live AWS account ownership, organization status, deployed role, and effective SCPs have not been checked.** Verify them before applying.

GENERAL creates the us-east-1 CUR 2.0 `COST_AND_USAGE_REPORT` Data Export and bucket `oconnordev-org-cost-usage-905418422177`, with delivery beneath `billing/oconnordev-org-cost-usage/data/`. SECURITY creates `oconnordev-athena-results-482921124454`; query outputs use `hermes-analytics/`. Glue database/table: `org_billing.cost_usage`. Athena workgroup: `hermes-analytics`, engine 3. Partition path uses `BILLING_PERIOD=YYYY-MM/`.

Spacelift order: configure dependency outputs if needed, apply GENERAL export, then SECURITY analytics using the existing GENERAL → SECURITY dependency. No reverse stack dependency is added. The existing adapter exposes `aws___run_script`; no speculative MCP/Cedar grant is added. The new inline policy allows query operations only on the named workgroup, read-only billing Glue metadata, CUR-prefix reads, and result-prefix reads/writes. The role's existing `ReadOnlyAccess` is broader than these additions. Existing credential-return, KMS decrypt, and STS AssumeRole explicit denies remain. IAM does not make Athena SQL SELECT-only: it accepts SQL query statements, while catalog/data mutation and unrestricted Athena execution permissions remain absent.

## Saved and example queries

Use `WorkGroup="hermes-analytics"`, `Database="org_billing"`, and `org_billing.cost_usage`. Saved queries use `line_item_unblended_cost`, retain all line-item types including credits/refunds/fees/taxes, group by currency, and filter `billing_period` for projection pruning. Unblended cost is not amortized cost and is not promised to reconcile exactly to an invoice. Do not aggregate unlike usage units.

```sql
SELECT line_item_usage_account_id, line_item_usage_account_name,
       line_item_product_code, line_item_currency_code,
       SUM(line_item_unblended_cost) AS unblended_cost
FROM org_billing.cost_usage
WHERE billing_period = '2026-10'
GROUP BY 1,2,3,4;
```

For daily month-to-date costs, select `date(line_item_usage_start_date)`, currency, and summed unblended cost; filter the partition and group by day and currency. For usage, group account, service, usage type, operation, pricing unit, and currency before summing usage/cost. If `line_item_resource_id` is populated:

```sql
SELECT line_item_resource_id, line_item_currency_code,
       SUM(line_item_unblended_cost) AS unblended_cost
FROM org_billing.cost_usage
WHERE billing_period = 'YYYY-MM' AND line_item_resource_id <> ''
GROUP BY 1,2 ORDER BY unblended_cost DESC;
```

## Hermes `aws___run_script` flow

Use boto3 via the real SECURITY gateway identity. Start with `athena.start_query_execution(QueryString=sql, QueryExecutionContext={'Database':'org_billing'}, WorkGroup='hermes-analytics')` and retain the returned `QueryExecutionId`. In a bounded follow-up script, poll `get_query_execution` until `SUCCEEDED`, `FAILED`, or `CANCELLED`, with a deadline and sleep interval; on failure report `StateChangeReason` and `AthenaError`. Retrieve `get_query_results` through `NextToken` pagination, cap returned rows explicitly (including the header), and report `Statistics.DataScannedInBytes`. If one script cannot wait long enough, use separate start/status/results calls keyed by execution ID. The per-query scan threshold is not a monthly cost cap.

First delivery may take up to 24 hours; delivery updates are at least daily. After apply, inspect the Data Exports manifest and actual Parquet schema/physical types, verify the uppercase partition path, then run a bounded SELECT using Hermes's actual gateway identity. Verify that identity cannot write to GENERAL's export bucket. No apply or live billable Athena query was run for this change.

## Future CloudTrail / Config (not included)

Existing SECURITY buckets are `oconnordev-cloudtrail` and `oconnordev-config`; inspect their current policies before extension. CloudTrail objects use `AWSLogs/<organization-id>/...` with account/region/time structure. Config objects are delivered below `AWSLogs/<account-id>/Config/<region>/...`, including history/snapshot structures. A future source needs its own exact-prefix `s3:ListBucket` condition, `s3:GetObject` grant for only its object prefix, any verified bucket-location permission, and distinct Glue database/table ARNs with only required GetDatabase/GetTable/GetTables metadata actions. Its projection/table schema must follow verified object layout. Reuse the workgroup, not a broad source permission. Do not grant or alter either bucket for this billing implementation.
