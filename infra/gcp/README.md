# GCP stacks

This directory holds Google Cloud OpenTofu stacks, mirroring the
`infra/aws/<stack>` layout.

There are no GCP stacks yet. A new one belongs at `infra/gcp/<stack>/`, and its
Spacelift stack must set `project_root = "infra/gcp/<stack>"` in
`infra/spacelift/main.tf`.

This file exists only so the directory is tracked by git.
