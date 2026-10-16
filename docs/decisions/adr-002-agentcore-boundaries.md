# Architecture: explicit AgentCore security boundaries

## Contract

Keep shared Hermes Gateway, Cognito authentication, policy-engine authorization, and generic gateway IAM separate from target-specific credentials, upstream targets, and Cedar actions. Keep security-account AWS_IAM Gateway/trust policies and the S3 policies for CloudTrail and Config directly visible in OpenTofu configuration.

## Rationale

The OAuth Gateway and the AWS_IAM security Gateway have different authentication and authorization models. Combining them in a GitHub-target file obscures ownership. Target-scoped API credentials and tool policies should remain reviewable alongside their upstream target, while gateway-wide policies must not be mistaken for GitHub-specific grants.

## Constraints

Gateway/target identities, resource addresses, authentication, IAM grants, Cedar conditions and bucket-policy principals are explicit security contracts. Review changes to these boundaries independently of source-file organization.
