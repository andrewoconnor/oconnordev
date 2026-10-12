terraform {
  required_version = ">= 1.13.1, < 2.0.0"

  required_providers {
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.8.0"
    }

    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.66.0"
    }
  }
}
