## Summary
- Create a GENERAL-owned organization CUR 2.0 Data Export in us-east-1 with dedicated private SSE-S3 source bucket and exact SECURITY gateway-role reads.
- Create SECURITY Athena engine 3 workgroup, dedicated results bucket, Glue org_billing.cost_usage table with monthly partition projection, saved queries, and narrow IAM policy.
- Wire GENERAL outputs to SECURITY over existing one-way Spacelift dependency; share schema source and add offline boundary/path-selection tests and Hermes runbook.

## Apply order
1. Spacelift output references if needed.
2. GENERAL export resources.
3. SECURITY analytics resources.
4. Gateway/MCP changes only if actual MCP/Cedar policy requires them; no speculative updates included.

## Verification
OpenTofu formatting/offline validation, TFLint, Checkov, OpenTofu tools tests, and Python adapter/rotation/CI tests passed. No Terraform apply or live Athena query was run.

## Limitations / post-apply
Account IDs and execution-role ARN come from repository sources; live account ownership, role deployment, and effective SCPs have not been checked. Verify delivery, manifest/schema physical Parquet types, and partition paths before querying. Use the real Hermes gateway identity for bounded SELECT and verify it cannot write to GENERAL. Athena IAM is not SELECT-only. Existing ReadOnlyAccess is broader read scope; credential-return, KMS decrypt, and STS AssumeRole denies remain. CloudTrail/Config are not granted.
