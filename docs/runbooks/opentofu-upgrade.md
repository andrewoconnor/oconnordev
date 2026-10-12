# OpenTofu 1.13.1 upgrade

Mise and all Spacelift runtime targets use the latest stable 1.13 release checked
for this change: 1.13.1. Provider pins and provider lockfiles are unchanged; the
mise lock updates only OpenTofu archives.

Apply administrative stack `oconnordev` (`infra/spacelift`) first. It upgrades
its own runtime and every managed workload runtime. Its compatibility minimum
remains >=1.12.0: tightening that minimum before the old runner applies the
self-upgrade would prevent initialization. This is a bootstrap compatibility
floor, not an old execution target. Other roots and the shared module require
>=1.13.1. Tighten the admin floor in a follow-up after verifying its upgrade.

Hold workload runs until the administrative upgrade finishes. Discard/replan
queued runs that selected the old runtime; review fresh plans after runtime
settings read back as 1.13.1. No live runtime-setting edits or infrastructure
apply are performed by this change.

The state-handoff regression retains a 1.12.6 synthetic snapshot to test older
state compatibility. Genuine native move/dependency fixtures also passed with
1.13.1. Historical evidence is not relabeled as a new execution.
