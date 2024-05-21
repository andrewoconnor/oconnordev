variable "spacelift_run_id" {}

terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.50.0"
    }
  }
}

provider "aws" {
  assume_role {
    role_arn     = arn:aws:iam::767397796791:role/spacelift
    session_name = var.spacelift_run_id
    external_id  = "spacelift"
  }

  region = "us-east-1"
}

# Create a VPC
resource "aws_vpc" "example" {
  cidr_block = "10.18.0.0/16"
}
