# Local static-site module

Both workload roots use `source = "../../modules/static-site"`. The module stays
in this repository; no Spacelift private registry, paid feature, registry token
or external publication is required.

The caller supplies `name`, `domain_name`, `bucket_name`, `origin_id`, `zone_id`,
`broker_role_arn` and its byte-exact `content_security_policy`. The module owns
private/versioned/AES256 S3 storage and its TLS/distribution-scoped OAC policy,
CloudFront delivery/security headers, apex/www A and AAAA aliases, and the
broker-only deploy role/policy. It inherits the root's AWS provider; current
roots use the same PRODUCTION account and us-east-1 role configuration.

`error_responses` is a list of objects containing `error_code`, `response_code`,
`response_page_path`, `error_caching_min_ttl`. Both current sites supply 403/404
-> `/404.html`, HTTP 404, 10 seconds. Publish the page before applying.

`extra_deploy_statements` defaults to an empty list. Each object has `sid`,
`effect`, `actions`, `object_suffixes`; suffixes resolve under this site's
bucket ARN, not arbitrary cross-site resources. DrumrollWorld supplies its
existing Deny on `s3:DeleteObject` for `images/*`; resume supplies no extension.
No repair/read privilege is added.

`existing_certificate_arn` defaults to null: create and validate the site's
apex/wildcard ACM certificate in the caller's us-east-1 provider. Resume instead
supplies the validated production-owned wildcard certificate shared with Hermes
MCP; that certificate and validation remain at their existing production state
addresses. Hosted zones and DNSSEC signing resources remain root-owned.

Public deployment/DNS outputs are `deploy_role_arn`, `distribution_id`,
`distribution_domain_name`, `certificate_arn`, `bucket_name`, `apex_fqdn`,
`www_fqdn`. Additional settings/resource outputs support the actual-provider
mock contracts without duplicating the implementation.

Managed-CachingOptimized is pinned by its AWS-defined ID
`658327ea-f89d-4fab-a63d-7e88639e58f6`; compression is always enabled. Policy TTLs
are 1/86400/31536000 seconds, not the old behavior TTLs. Both sites preserve
OAC/SigV4, HTTPS redirect, TLSv1.2_2021, existing price/geo restrictions and
security headers; site CSP is an explicit input, not generalized permissions.

**Existing resources require state migration, never a fresh apply.** See
[the owner-operated handoff](../../../docs/static-site-state-migration.md) for
same-state Drumroll moves, fail-closed cross-state resume transfer, shared
certificate/zone ownership and non-reproducible external-image recovery risks.
`prevent_destroy` also protects the bucket and distribution, but is not a
substitute for verifying the real state and zero-replacement plans.
