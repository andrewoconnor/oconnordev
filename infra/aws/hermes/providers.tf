provider "aws" {
  assume_role {
    role_arn     = "arn:aws:iam::${jsondecode(file("${path.module}/../accounts.json"))["HERMES"]}:role/spacelift"
    session_name = var.spacelift_run_id
    external_id  = "spacelift-general"
  }

  region = "us-east-1"
}
