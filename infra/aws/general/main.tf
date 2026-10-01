terraform {
  required_version = ">= 1.12.0, < 2.0.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.66.0"
    }
  }
}

provider "aws" {
  region = "us-east-1"
}

#resource "aws_budgets_budget" "cost" {
#  budget_type  = "COST"
#  limit_amount = "100"
#  limit_unit   = "USD"
#  time_unit    = "MONTHLY"
#  name         = "Monthly Budget"
#}
