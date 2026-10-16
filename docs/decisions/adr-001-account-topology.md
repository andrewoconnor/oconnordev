# Architecture: centralized account topology

## Contract

Keep the four AWS account IDs and the Organizations ID in `infra/aws/accounts.json`. Use the current caller identity for the account in which a stack executes. Read the JSON map directly in provider assume-role configuration because a provider cannot depend on a data-source result.

Use direct identifiers for deterministic account and role names. Keep Spacelift dependency references only for generated gateway identifiers/URLs consumed by another stack.

## Rationale and constraints

Account topology is file-based, not Organizations discovery or cross-stack state sharing. The JSON file is repository configuration, not a live inventory source; creating or changing AWS accounts remains a separate operation.
