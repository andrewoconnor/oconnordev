variable "drumrollworld_tools_github_actions_broker_role_arn" {
  description = "Dedicated DrumrollWorld broker output from TOOLS; required before workflow cutover."
  type        = string
}

resource "github_actions_variable" "drumrollworld_tools_broker" {
  repository    = "oconnordev"
  variable_name = "DRUMROLLWORLD_TOOLS_GITHUB_ACTIONS_BROKER_ROLE_ARN"
  value         = var.drumrollworld_tools_github_actions_broker_role_arn
}
