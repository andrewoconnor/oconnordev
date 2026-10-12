terraform {
  # Bootstrap compatibility: this root upgrades its own Spacelift runtime.
  # Keep the old minimum until that upgrade has applied; the runtime target is 1.13.1.
  required_version = ">= 1.12.0, < 2.0.0"

  required_providers {
    spacelift = {
      source  = "spacelift-io/spacelift"
      version = "~> 1.55.0"
    }
  }
}
