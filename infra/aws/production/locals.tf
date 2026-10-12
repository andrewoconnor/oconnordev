locals {
  zone_name = "oconnor.dev"
  accounts  = jsondecode(file("${path.module}/../accounts.json"))
}
