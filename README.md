# oconnordev

Infrastructure and agent code for oconnordev.

## Repository layout

```
.
├── .github/workflows/        CI: Checkov, TFLint, adapter tests
├── agents/hermes/adapter/    AgentCore MCP adapter and target manifests
├── docs/
│   ├── architecture/        System boundaries and stack dependencies
│   ├── decisions/           Architecture decision records
│   └── runbooks/            Bootstrap and operations
├── infra/
│   ├── aws/
│   │   ├── accounts.json    Account and organization identifiers
│   │   ├── drumrollworld/   Static-site account stack
│   │   ├── general/         Organizations management account
│   │   ├── tools/           Shared AgentCore gateway and target policies
│   │   ├── production/      Public MCP endpoint
│   │   └── security/        Central audit and security gateway
│   ├── gcp/
│   └── spacelift/           Spacelift management stack
└── README.md
```

Each directory under `infra/aws/` and `infra/gcp/` is an independent OpenTofu root module and maps to a Spacelift stack. `infra/spacelift/main.tf` owns the mapping and its explicit stack dependencies. Terraform/OpenTofu files in each AWS root are organized around versions, providers, locals, feature resources, and outputs. No new Terraform modules are introduced.

AWS account identifiers and the Organizations ID are centralized in `infra/aws/accounts.json`. A stack uses `data.aws_caller_identity.current.account_id` for its own account; the JSON map is for cross-account references. Spacelift dependencies remain only where one stack consumes a generated output, such as the AgentCore gateway URL/ARN.

The Hermes adapter is application code under `agents/hermes/adapter/`. It registers once against the shared gateway and checks the union of target manifests; adding a gateway target does not grant it to an existing target's Cedar policy.

See [architecture](docs/architecture/README.md) for trust boundaries and dependency ordering, and [runbooks](docs/runbooks/infrastructure-bootstrap.md) for bootstrap and state-safety procedures.
