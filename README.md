# oconnordev

Infrastructure and agent code for oconnordev.

## Development commands

Install [mise](https://mise.jdx.dev/) and run these from the repository root:

```sh
mise trust
mise install --locked
mise run fmt
mise run lint
mise run validate
mise run workflow-lint
mise run lint:python
mise run fmt:site
mise run checkov
mise run test
```

`mise.toml` is the source of CLI versions: OpenTofu, TFLint, actionlint,
Python, Ruff, Deno, Checkov, and the AWS CLI. CI installs the same locked tools
through `jdx/mise-action`; it does not separately install Deno or Checkov or
rely on the runner's AWS CLI. Checkov uses the Aqua standalone release, so its
bundled Python dependencies are isolated from repository application libraries.
Keep application/library dependencies in their existing dependency files, not
in mise. Git, Bash, and standard POSIX utilities are host prerequisites; Hermes
is the externally managed runtime for the opt-in live adapter smoke test.

`mise run checkov` preserves a failing exit code for findings and writes
`results.sarif` for CI upload. It scans the whole repository, like the previous
Checkov action. `mise run test:python` runs only the offline Python tests;
`mise run test` also initializes providers and runs OpenTofu boundary tests.
`mise run validate` chooses affected roots in CI and all roots locally.
Deployment commands require the existing AWS role chain and are not part of
local validation; installing the AWS CLI grants no credentials.

When adding or updating a CLI, pin its version in `mise.toml`, run `mise lock`
to refresh `mise.lock`, and commit both files. Existing lock targets cover
Linux x64 and macOS x64/arm64; Checkov's macOS arm64 release uses Rosetta.
Run `mise install --locked` and the affected tasks before opening a PR.

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
│   │   ├── drumrollworld/   Static-site workload (PRODUCTION account)
│   │   ├── general/         Organizations management account
│   │   ├── tools/           Shared AgentCore gateway and target policies
│   │   ├── production/      Public MCP endpoint
│   │   └── security/        Central audit and security gateway
│   ├── gcp/
│   └── spacelift/           Spacelift management stack
└── README.md
```

Every directory under `infra/aws/` and `infra/gcp/` is an independent OpenTofu root module and maps to a Spacelift stack. `infra/spacelift/main.tf` owns the mapping and its explicit stack dependencies. OpenTofu configuration in each AWS root is organized around versions, providers, locals, feature resources, and outputs. No new modules are introduced. Every root commits a `.terraform.lock.hcl` with providers resolved from `registry.opentofu.org`; CI checks that lockfiles keep using the OpenTofu registry namespace.

AWS account identifiers and the Organizations ID are centralized in `infra/aws/accounts.json`. A stack uses `data.aws_caller_identity.current.account_id` for its own account; the JSON map is for cross-account references. Spacelift dependencies remain only where one stack consumes a generated output, such as the AgentCore gateway URL/ARN.

The Hermes adapter is application code under `agents/hermes/adapter/`. It registers once against the shared gateway and checks the union of target manifests; adding a gateway target does not grant it to an existing target's Cedar policy.

See [architecture](docs/architecture/README.md) for trust boundaries and dependency ordering, and [runbooks](docs/runbooks/infrastructure-bootstrap.md) for bootstrap and state-safety procedures.
