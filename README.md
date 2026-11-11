# oconnordev

Infrastructure and agent code for oconnordev.

## Development commands

Install [mise](https://mise.jdx.dev/) and run these from the repository root:

```sh
mise trust
mise install --locked
mise run fmt
mise run lint
mise run validate:opentofu
mise run scan:iac
mise run test
```

Tasks are named `<action>:<area>`, such as `lint:python`. `fmt` and `lint` run
every `fmt:*` and `lint:*` task; run one directly to check a single area.
`mise tasks ls` lists them all.

`mise.toml` is the source of CLI versions: OpenTofu, TFLint, actionlint, ShellCheck,
Python, Ruff, Biome, Node.js, Checkov, and the AWS CLI. CI installs the same
locked tools through `jdx/mise-action`; it does not separately install Biome or
Checkov. Deploy and publish jobs are the exception: they use the runner's
preinstalled AWS CLI and Python. Checkov uses the Aqua standalone release, so its
bundled Python dependencies are isolated from repository application libraries.
Keep application/library dependencies in their existing dependency files, not
in mise. Git, Bash, and standard POSIX utilities are host prerequisites; Hermes
is the externally managed runtime for the opt-in live adapter smoke test.

`mise run scan:iac` runs Checkov, preserves a failing exit code for findings and writes
`results.sarif` for CI upload. It scans the whole repository, including infrastructure and workflows. `mise run test:python` runs only the offline Python tests;
`mise run test` also initializes providers and runs OpenTofu boundary tests.
The Python test task installs the pinned test-only Cedar engine wheel from
`scripts/ci/requirements-test.txt`; initial dependency setup may need network,
while authorization tests themselves are offline.
`mise run validate:opentofu` chooses affected roots in CI and all roots locally.
Deployment commands require the existing AWS role chain and are not part of
local validation; installing the AWS CLI grants no credentials.

The dependency review workflow fails any pull request that adds or updates a
dependency with a known vulnerability of any severity, in runtime or development
scope. It reads the dependency graph, which parses the npm, Cargo, pip and
workflow files. It only checks what a pull request changes; Dependabot alerts
report new advisories for dependencies already on `master`.

`dependabot-auto-merge.yml` turns on squash auto-merge for every Dependabot pull
request, major updates included, so GitHub merges it once every required check
passes. It runs the copy on `master` through `pull_request_target`, checks that
every commit is a verified Dependabot commit, and never checks out pull request
code. It signs a short-lived GitHub App token itself (Actions secrets
`DEPENDABOT_AUTO_MERGE_CLIENT_ID` and `DEPENDABOT_AUTO_MERGE_PRIVATE_KEY`) and
revokes it afterwards, because pushes caused by `GITHUB_TOKEN` do not start the
deploy workflows. To stop automatic merges, turn off **Allow auto-merge** in the
repository settings.

Jobs that can get AWS credentials through OIDC or read a secret run no code that
Dependabot updates: no actions, `actions/checkout`, `mise` or package managers.
They fetch the tested commit with `git`, download their run's artifact with `gh`,
and use the AWS CLI, Python and other tools preinstalled on the GitHub runner, with
repository scripts that import only the standard library. Build and test jobs keep
using pinned actions and `mise`, with read-only permissions and no secrets.
`scripts/ci/tests/test_privileged_jobs.py` enforces both rules. A digest check
proves that a deploy job received the bytes its build job produced, not that a
compromised build action left those bytes unchanged.

When adding or updating a CLI, pin its version in `mise.toml`, run `mise lock`
to refresh `mise.lock`, and commit both files. Existing lock targets cover
Linux x64 and macOS x64/arm64; Checkov's macOS arm64 release uses Rosetta.
Run `mise install --locked` and the affected tasks before opening a PR.

`mise run fmt:site` and `mise run lint:site` check HTML, CSS, and JavaScript
under both `apps/oconnordev` and `apps/drumrollworld` using the shared `biome.json`.
Biome HTML support is explicitly enabled; see the configuration and pinned
release for its experimental support boundary.

DrumrollWorld deploys from `master` with its environment, role and Actions-variable
configuration. See [the deployment runbook](docs/runbooks/drumrollworld-deployment.md),
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
├── agents/hermes/plugins/    Hermes plugins, such as the mail guard
├── docs/
│   ├── architecture/        System boundaries and stack dependencies
│   ├── decisions/           Architecture decision records
│   └── runbooks/            Bootstrap and operations
├── infra/
│   ├── aws/
│   │   ├── accounts.json    Account and organization identifiers
│   │   ├── drumrollworld/   Static-site workload (PRODUCTION account)
│   │   ├── oconnordev/      Resume workload (stack oconnordev-resume)
│   │   ├── general/         Organizations management account
│   │   ├── tools/           Shared AgentCore gateway and target policies
│   │   ├── production/      Public MCP endpoint
│   │   └── security/        Central audit and security gateway
│   ├── modules/static-site/ Shared local storage/delivery/deploy module
│   ├── gcp/google-auth/     Google Auth project and scoped IAM
│   └── spacelift/           Spacelift management stack
├── scripts/
│   ├── adapter/             Adapter deploy/smoke commands and offline tests
│   ├── ci/                  CI path selection, validation, and policy tests
│   └── drumrollworld/       Image/texture asset pipelines and offline tests
└── README.md
```

Each configured workload under `infra/aws/` is an independent OpenTofu root
mapped to a Spacelift stack. `infra/spacelift/` owns stack mapping and explicit
producer dependencies. The separate `infra/gcp/google-auth/` root uses native
GCP integration; see its [runbook](docs/runbooks/gcp-google-auth-discovery.md).
Both static-site roots use `../../modules/static-site`; no registry credentials
are needed. PRODUCTION owns the shared zone, DNSSEC, wildcard certificate and
Hermes endpoint. Root lockfiles resolve providers from `registry.opentofu.org`.

AWS account identifiers and the Organizations ID are centralized in `infra/aws/accounts.json`. A stack uses `data.aws_caller_identity.current.account_id` for its own account; the JSON map is for cross-account references. Spacelift dependencies remain only where one stack consumes a generated output, such as the AgentCore gateway URL/ARN.

Operational commands live under `scripts/`, separate from application libraries:

- `scripts/adapter/`: deploy and smoke-test the Hermes adapter. The pure gateway
  validation library and its tests live alongside the adapter under
  `agents/hermes/adapter/` and `agents/hermes/adapter/test/`; operational tests
  live under `scripts/adapter/test/`.
- `scripts/ci/`: choose affected OpenTofu roots and run validation; use
  `mise run validate:opentofu` and `mise run test:python` for validation and offline tests.
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

For compatibility with strict MCP discovery clients, `tools/list` preserves
`outputSchema` only when its root explicitly declares `"type": "object"`.
Incompatible optional output schemas are omitted, not rewritten; input schemas,
other tool metadata, and tool-call results are unchanged. The optional offline
SDK proof uses a synthetic gateway and real stdio `ClientSession` discovery:

```sh
cd agents/hermes/adapter
/path/to/isolated-sdk-venv/bin/python -m unittest test.test_sdk_discovery -v
```

Install the SDK only in an isolated test environment (for example `mcp==1.30.0`);
it is not an adapter runtime dependency. The test separately checks the daemon's
strict object-root contract: that SDK release and the managed SDK pinned in
`scripts/ci/requirements-thundermail-sdk.txt` accept broader dictionaries
themselves, so neither is evidence of a strict SDK model.

The [native GitHub settings-read runbook](docs/runbooks/github-settings-read.md)
describes partial ruleset/collaborator/label coverage, permission review, secure
token rotation, and gateway-before-adapter rollout. The [repository-settings runbook](docs/runbooks/github-settings-adoption.md)
describes the dedicated provider App, managed ruleset/labels/default branch/topics,
and owner-reviewed preservation gates. Unsupported settings remain externally owned.

See [architecture](docs/architecture/README.md) for trust boundaries and dependency ordering, and [runbooks](docs/runbooks/infrastructure-bootstrap.md) for bootstrap and state-safety procedures.
