# ADR: explicit AgentCore security boundaries

## Decision

Keep shared Hermes Gateway, Cognito authentication, policy-engine authorization, and generic gateway IAM separate from target-specific credentials, upstream targets, and Cedar actions. Keep security-account AWS_IAM Gateway/trust policies and the S3 policies for CloudTrail and Config directly visible in Terraform.

## Rationale

The OAuth Gateway and the AWS_IAM security Gateway have different authentication and authorization models. Combining them in a GitHub-target file obscures ownership. Target-scoped API credentials and tool policies should remain reviewable alongside their upstream target, while gateway-wide policies must not be mistaken for GitHub-specific grants.

## Constraints

This is a file-layout and deduplication decision only. Do not change Gateway names, target names, resource addresses, authentication mode, IAM grants, Cedar conditions, or bucket-policy principals as part of the move. There are no new modules.