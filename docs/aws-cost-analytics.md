# AWS organization cost analytics for Hermes

## Ownership and paths

The repository account map (`infra/aws/accounts.json`) assigns GENERAL `905418422177` and SECURITY `482921124454`; GENERAL is the organization management/payer root by repository convention. The SECURITY execution role is read from `infra/aws/security/gateway.tf`: `arn:aws:iam::482921124454:role/oconnordev-security-gateway`. This change does **not** check live AWS account ownership, organization status, role deployment, or effective SCPs. Verify those before applying.

The General root (us-east-1) creates the organization CUR 2.0 `COST_AND_USAGE_REPORT` export, bucket `oconnordev-org-cost-usage-905418422177`, and `billing/oconnordev-org-cost-usage/data/` export path. SECURITY (us-east-1) creates `oconnordev-athena-results-482921124454`, with Athena results under `hermes-analytics/`, Glue database `org_billing`, table `cost_usage`, and enforced Athena workgroup `hermes-analytics`. The table reads `s3://oconnordev-org-cost-usage-905418422177/billing/oconnordev-org-cost-usage/data/`; billing-period partitions use uppercase `BILLING_PERIOD=YYYY-MM/`.

Spacelift order is configuration update, GENERAL export, then SECURITY analytics via the existing GENERAL → SECURITY stack dependency; there is no SECURITY → GENERAL edge. Apply configuration output-reference changes first if required. No MCP/Cedar manifest update is indicated: the existing adapter already exposes `aws___run_script`. Gateway IAM grants only query execution/status/result/stop/workgroup access on the named workgroup, read-only Glue metadata for the billing catalog, CUR prefix reads, and SECURITY results prefix reads/writes. Existing `ReadOnlyAccess` is broader read access beyond this new scope; existing credential-return, KMS decrypt, and STS AssumeRole denies must remain. IAM scope is not SELECT-only: Athena accepts SQL execution. Catalog/data mutation and unrestricted Athena execution remain absent.

## Queries

Always specify `WorkGroup="hermes-analytics"`, `Database="org_billing"`, and table `org_billing.cost_usage`. Saved queries use `line_item_unblended_cost` (not amortized cost), group currency, retain all line-item types (credits, refunds, fees, taxes), and filter `billing_period` for partition pruning. Unblended values are not a promise of invoice reconciliation. Do not sum unlike usage units.

Monthly account/service:

```sql
SELECT line_item_usage_account_id, line_item_usage_account_name,
       line_item_product_code, line_item_currency_code,
       SUM(line_item_unblended_cost) AS unblended_cost
FROM org_billing.cost_usage
WHERE billing_period = '2026-10'
GROUP BY 1,2,3,4;
```

Daily current-month costs: select `date(line_item_usage_start_date)`, `line_item_currency_code`, and `SUM(line_item_unblended_cost)`; filter `billing_period='YYYY-MM'`; group by day and currency. Usage dimensions: group account, service, usage type, operation, pricing unit, and currency, summing usage and cost only within each unit/currency group.

If `line_item_resource_id` is populated for the selected records, example resource-level cost query:

```sql
SELECT line_item_resource_id, line_item_currency_code,
       SUM(line_item_unblended_cost) AS unblended_cost
FROM org_billing.cost_usage
WHERE billing_period = 'YYYY-MM' AND line_item_resource_id <> ''
GROUP BY 1,2 ORDER BY unblended_cost DESC;
```

## Hermes execution through the real gateway

Use Hermes `aws___run_script` (boto3) in the SECURITY gateway role; never use local AWS credentials or GENERAL assume-role. Start with `athena.start_query_execution(QueryString=..., QueryExecutionContext={'Database':'org_billing'}, WorkGroup='hermes-analytics')`, return its `QueryExecutionId`. In a subsequent bounded script, poll `get_query_execution` until `SUCCEEDED`, `FAILED`, or `CANCELLED` with a deadline and sleep interval; surface `StateChangeReason` and `AthenaError` on failure. Then page `get_query_results` with `NextToken`, stop after an explicit row maximum (including header row), and report `Statistics.DataScannedInBytes`. For long execution separate start, status, and result retrieval into calls keyed by execution ID. Do not report an unbounded result set.

First delivery can take up to 24 hours; updates are at least daily. Verify the Data Exports manifest and Parquet files before trusting the provisioned table: manifest-selected columns and schema must match the shared source and physical Parquet primitive types; confirm actual `BILLING_PERIOD=YYYY-MM/` S3 path. Only then run bounded SELECT through Hermes. Confirm that the gateway identity cannot write to GENERAL's export bucket. No apply or billable Athena query is part of this change.

## Future CloudTrail / Config (not granted here)

Existing SECURITY source buckets are `oconnordev-cloudtrail` and `oconnordev-config`. CloudTrail object layout is `AWSLogs/<organization-id>/...` (account/region/date below it); AWS Config delivery objects use `AWSLogs/<account-id>/Config/<region>/...` and snapshots/history subpaths. Their existing bucket policies must separately grant only the SECURITY gateway principal `s3:ListBucket` constrained to the relevant prefixes and `s3:GetObject` on that source prefix, plus any needed location access; do not broaden the CUR policy. Add distinct Glue databases/tables with specific table ARNs and scoped `glue:GetDatabase`/`GetTable`/`GetTables` metadata access; partition projection or a managed partition mechanism must match each actual key layout. Add explicit dataset-specific read statements in the role policy and test no cross-source access. The shared workgroup can be reused; keep Athena query permissions workgroup-scoped. Inspect current bucket policies/layout and verify AWS delivery formats before implementing those separate changes.
