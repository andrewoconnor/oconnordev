terraform {
  required_version = ">= 1.12.0, < 2.0.0"

  required_providers {
    spacelift = {
      source  = "spacelift-io/spacelift"
      version = "~> 1.55.0"
    }
  }
}
