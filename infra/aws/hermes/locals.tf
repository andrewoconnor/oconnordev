locals {
  repo_root    = "${path.root}/../../.."
  adapter_root = "${local.repo_root}/agents/hermes/adapter"
}

locals {
  accounts = jsondecode(file("${path.module}/../accounts.json"))
}
