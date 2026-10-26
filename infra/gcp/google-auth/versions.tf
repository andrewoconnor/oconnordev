terraform {
  required_version = ">= 1.13.1, < 2.0.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "8.8.1"
    }
  }
}
