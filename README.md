# oconnordev

Infrastructure and agent code for oconnordev.

## Repository layout

```
.
├── .github/workflows/        CI: Checkov, TFLint, adapter tests
├── agents/                   Application code, grouped by agent
│   └── hermes/
│       └── adapter/          Hermes MCP adapters (GitHub, AWS) and their tests
├── infra/                    Infrastructure, grouped by cloud provider
│   ├── aws/                  One directory per AWS account/stack
│   │   ├── drumrollworld/
│   │   ├── general/
│   │   ├── hermes/
│   │   └── production/
│   ├── gcp/                  GCP stacks (none yet)
│   └── spacelift/            The Spacelift management stack
└── README.md
```

Each directory under `infra/aws/` and `infra/gcp/` is its own OpenTofu root
module and maps one-to-one to a Spacelift stack. The mapping lives in
`infra/spacelift/main.tf`, where each `spacelift_stack` sets `project_root` to
the stack's directory — for example `project_root = "infra/aws/hermes"`.

Application code lives under `agents/` rather than inside a Terraform stack.
The Hermes stack reads its tool manifests from `agents/hermes/adapter/` via the
`local.adapter_root` local in `infra/aws/hermes/main.tf`.

The stack that manages Spacelift itself is `infra/spacelift` and is
intentionally not under `infra/aws` or `infra/gcp`, because it manages the
platform rather than a cloud account.

## Porkbun DNSSEC config

Only fill out the following fields, leave everything else blank:

- Key Tag
- Algorithm
- Digest Type
- Digest