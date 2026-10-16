# OpenTofu runtime management

`mise.toml` and Spacelift runtime targets pin OpenTofu **1.13.1**. Workload roots
and the shared module require >=1.13.1; the administrative root retains a >=1.12.0
compatibility floor so it can manage runtime settings. A minimum constraint is
not the execution target. Provider versions and checksums are pinned separately
in each root's `.terraform.lock.hcl`.

For a runtime change, update the mise pin/lock and Spacelift targets together,
run offline validation and boundary tests, then have the owner review/apply the
administrative `oconnordev` stack first. Hold workload runs until runtime settings
read back correctly; discard/replan queued runs selecting an incompatible runtime.
Review fresh plans before any owner apply. Never infer deployed settings from a
local tool version or a successful offline test.
