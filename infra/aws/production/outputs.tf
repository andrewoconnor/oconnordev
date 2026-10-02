output "hermes_mcp_endpoint" {
  description = "Custom HTTPS endpoint for the shared Hermes AgentCore Gateway; null until the upstream Gateway hostname is available."
  value       = local.hermes_mcp_enabled ? "https://${local.hermes_mcp_domain_name}/mcp" : null
}
