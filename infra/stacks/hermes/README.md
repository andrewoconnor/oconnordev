# Shared Hermes AgentCore Gateway

The Hermes account stack owns one Cognito-authenticated AgentCore Gateway and one attached Cedar policy engine. GitHub remains a target of that shared Gateway. Future integrations should add their own Gateway target, outbound credential provider/secret and narrowly scoped IAM grant, plus target/tool-specific Cedar policies; they should not create another Gateway or inbound Cognito client.

The shared Gateway role now separates common AgentCore permissions from GitHub-only API-key and secret access. The Gateway remains in `ENFORCE` mode, Cedar validation remains `FAIL_ON_ANY_FINDINGS`, and unmatched requests remain denied. Any Cedar `forbid` continues to override permits.

## Naming/state migration

The old GitHub-specific Terraform addresses are migrated with `moved` blocks. Physical names change for the AgentCore Gateway (`hermes-github` → `hermes`), policy engine (`hermes_github_policy_engine` → `hermes_policy_engine`), Gateway role (`hermes-github-agentcore-gateway` → `hermes-agentcore-gateway`), and alarm (`hermes-github-gateway-user-errors` → `hermes-gateway-user-errors`). These require replacements: expect a new Gateway ID/URL and policy-engine ID, recreation/rebinding of its target and Cedar policies, and recreation of the role and its inline policies. This is intentionally a coordinated cutover before adding more targets; review the actual state-backed plan before applying. The previously noted console-created `test` policy must be identified and reconciled/imported or deliberately handled before deleting/replacing the existing policy engine; its ID is not guessed here.

Cognito resource Terraform addresses are generalized, but their existing physical pool/domain/client names, resource-server identifier, and scope are retained to avoid additional token-endpoint or authorization changes. Generic output names are added; the former `hermes_github_*` outputs remain as compatibility aliases. No live Hermes configuration or credentials are changed by this PR.

## Custom endpoint and account boundary

AgentCore Gateway does not have a native custom-domain Terraform resource; AWS documents CloudFront as the reverse proxy. The current repository places `oconnor.dev`, its ACM certificate, and its Route53 zone in the production stack/account, while AgentCore is in the Hermes stack/account. Accordingly, CloudFront and DNS are managed in the production stack and the origin hostname is passed from Hermes through a non-secret Spacelift stack-dependency output reference.

The existing production certificate covers `oconnor.dev` and `*.oconnor.dev`; it does **not** cover `mcp.hermes.oconnor.dev`. The endpoint selected here is `https://mcp.oconnor.dev/mcp`, which is covered by the existing wildcard. To use `mcp.hermes.oconnor.dev`, first add that exact name or `*.hermes.oconnor.dev` to the ACM certificate and complete DNS validation.

The CloudFront distribution forwards MCP methods and viewer headers except `Host`, disables caching, uses the managed security-headers response policy, and uses HTTPS to the Gateway origin. The default root object maps `/` to `/mcp` as a convenience. The endpoint does not bypass Cognito or Cedar authorization. The distribution is conditionally absent while the Spacelift-provided Gateway hostname input is empty, so the production stack can still validate before its upstream output exists. Checkov exceptions are documented inline for the single-origin/no-failover design, worldwide client access, no WAF fixed cost, and intentionally disabled access logs.

## Deployment sequence (not performed by this PR)

1. Inspect the current Hermes state and remote policy-engine contents. Reconcile the console-created `test` policy first; review a state-backed plan and confirm all address moves and expected replacements, then apply the Hermes stack to publish the new Gateway hostname.
2. Apply the Spacelift management stack so the Hermes output is wired to the production stack input.
3. Review and apply the production stack to create the CloudFront distribution and `A`/`AAAA` alias records. Wait for CloudFront deployment and DNS propagation before switching clients.
4. Test Cognito authentication, MCP initialize/tools/list/call through `https://mcp.oconnor.dev/mcp`, CloudFront forwarding of `Authorization` and MCP headers, and Cedar allow/deny behavior. Do not remove the existing direct GitHub path until those tests pass.

This PR adds no new MCP target and does not generalize the local GitHub-only adapter/tool allowlist. Future integrations can be attached to the shared Gateway, but Hermes-side exposure of their tools requires a separate adapter/manifest change. No plan, apply, DNS change, deployment, or client cutover has been performed.
