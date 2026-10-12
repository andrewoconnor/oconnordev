variable "site_state_handoff_complete" {
  description = "Owner confirmation after both locked states have been transferred and zero-destroy plans reviewed. See docs/static-site-state-migration.md."
  type        = bool
  default     = false
}
resource "terraform_data" "site_state_handoff_guard" {
  input = var.site_state_handoff_complete
  lifecycle {
    precondition {
      condition     = var.site_state_handoff_complete
      error_message = "STOP: mandatory owner-operated cross-state transfer is not complete. Freeze both stacks and follow docs/static-site-state-migration.md before enabling applies."
    }
  }
}
