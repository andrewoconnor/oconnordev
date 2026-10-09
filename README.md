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
mise run lint:site
mise run checkov
mise run test
```

`mise.toml` is the source of CLI versions: OpenTofu, TFLint, actionlint,
Python, Ruff, Biome, Node.js, Checkov, and the AWS CLI. CI installs the same
locked tools through `jdx/mise-action`; it does not separately install Biome or Checkov or
rely on the runner's AWS CLI. Checkov uses the Aqua standalone release, so its
bundled Python dependencies are isolated from repository application libraries.
Keep application/library dependencies in their existing dependency files, not
in mise. Git, Bash, and standard POSIX utilities are host prerequisites; Hermes
is the externally managed runtime for the opt-in live adapter smoke test.

`mise run checkov` preserves a failing exit code for findings and writes
`results.sarif` for CI upload. It scans the whole repository, like the previous
Checkov action. `mise run test:python` runs only the offline Python tests;
`mise run test` also initializes providers and runs OpenTofu boundary tests.
The Python test task installs the pinned test-only Cedar engine wheel from
`scripts/ci/requirements-test.txt`; initial dependency setup may need network,
while authorization tests themselves are offline.
`mise run validate` chooses affected roots in CI and all roots locally.
Deployment commands require the existing AWS role chain and are not part of
local validation; installing the AWS CLI grants no credentials.

When adding or updating a CLI, pin its version in `mise.toml`, run `mise lock`
to refresh `mise.lock`, and commit both files. Existing lock targets cover
Linux x64 and macOS x64/arm64; Checkov's macOS arm64 release uses Rosetta.
Run `mise install --locked` and the affected tasks before opening a PR.

`mise run fmt:site` and `mise run lint:site` check HTML, CSS, and JavaScript
under both `apps/oconnordev` and `apps/drumrollworld` using the shared `biome.json`.
Biome HTML support is explicitly enabled; see the configuration and pinned
release for its experimental support boundary.

DrumrollWorld deploys from `master` after its one-time role and Actions-variable
setup. See [the deployment runbook](docs/runbooks/drumrollworld-deployment.md),
including the external image assets that the code sync must preserve.
`mise run build:drumrollworld` installs the exact npm lock without lifecycle
scripts and bundles updated browser dependencies plus the local KTX2 decoder
into an ignored `dist/` release; `mise run test:drumrollworld` checks that release.
The production workflow publishes only that directory to the existing bucket.

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
├── scripts/
│   ├── adapter/             Adapter deploy/smoke commands and offline tests
│   ├── ci/                  CI path selection, validation, and policy tests
│   └── drumrollworld/       Image/texture asset pipelines and offline tests
└── README.md
```

Every directory under `infra/aws/` and `infra/gcp/` is an independent OpenTofu root module and maps to a Spacelift stack. `infra/spacelift/main.tf` owns the mapping and its explicit stack dependencies. OpenTofu configuration in each AWS root is organized around versions, providers, locals, feature resources, and outputs. No new modules are introduced. Every root commits a `.terraform.lock.hcl` with providers resolved from `registry.opentofu.org`; CI checks that lockfiles keep using the OpenTofu registry namespace.

AWS account identifiers and the Organizations ID are centralized in `infra/aws/accounts.json`. A stack uses `data.aws_caller_identity.current.account_id` for its own account; the JSON map is for cross-account references. Spacelift dependencies remain only where one stack consumes a generated output, such as the AgentCore gateway URL/ARN.

Operational commands live under `scripts/`, separate from application libraries:

- `scripts/adapter/`: deploy and smoke-test the Hermes adapter. The pure gateway
  validation library and its tests live alongside the adapter under
  `agents/hermes/adapter/` and `agents/hermes/adapter/test/`; operational tests
  live under `scripts/adapter/test/`.
- `scripts/ci/`: choose affected OpenTofu roots and run validation; use
  `mise run validate` and `mise run test:python` for validation and offline tests.
- `scripts/drumrollworld/`: build thumbnails and globe textures, validate published
  assets, and test asset pipelines. See the DrumrollWorld deployment runbook;
  `mise run test:drumrollworld` runs site and asset-pipeline tests.

Adapter commands (from the repository root):

```sh
python3 scripts/adapter/adapter_smoke_test.py --help
python3 -m scripts.adapter.adapter_smoke_test --help
bash scripts/adapter/deploy_hermes_adapter.sh --help
```

The smoke command also works by absolute path from another working directory;
no dependency installation is needed for help or offline tests. Without `--live`,
smoke checks make no network requests and exit **2** (skipped, not passed).
To explicitly run live discovery, allowlisted read-only calls, and non-mutating
GitHub policy-denial probes against a configured server:

```sh
python3 -m scripts.adapter.adapter_smoke_test --live --checkout /path/to/checkout \
  --server agentcore --github-owner ALLOWED_OWNER --github-repo ALLOWED_REPO
```

The selected checkout supplies the adapter/manifests and gateway-check library.
Credentials come from the selected Hermes MCP server configuration; the GitHub
owner/repository can also come from `HERMES_SMOKE_GITHUB_OWNER` and
`HERMES_SMOKE_GITHUB_REPO`. Credentials are not printed.

`bash scripts/adapter/deploy_hermes_adapter.sh --checkout /path/to/checkout`
requires a clean deployed checkout, fetches and fast-forwards it, and runs adapter
unit tests. **It changes the deployed checkout**; it is not a local validation
command. Live checks remain disabled unless `--live-smoke` is explicitly supplied.
The script exits 2 until MCP reload is confirmed with `--reloaded` after
`/reload-mcp`, or performed through `HERMES_ADAPTER_RELOAD_CMD`.

The Hermes adapter is application code under `agents/hermes/adapter/`. It registers once against the shared gateway and checks the union of target manifests; adding a gateway target does not grant it to an existing target's Cedar policy.

The [native GitHub settings-read runbook](docs/runbooks/github-settings-read.md)
describes partial ruleset/collaborator/label coverage, permission review, secure
token rotation, and gateway-before-adapter rollout. It is a prerequisite only;
no complete repository adoption/import is included.

See [architecture](docs/architecture/README.md) for trust boundaries and dependency ordering, and [runbooks](docs/runbooks/infrastructure-bootstrap.md) for bootstrap and state-safety procedures.
