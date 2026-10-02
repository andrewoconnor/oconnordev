locals {
  accounts = jsondecode(file("${path.module}/../accounts.json"))
}
