# Independent live discovery prevents a configured name from masking drift.
data "google_project" "google_auth" {
  project_id = "adept-presence-510022-p7"

  # Google 8.7.0 rejects projects not in ACTIVE state in its data-source read.
  # It exports no lifecycle_state attribute; do not fabricate one here.
  lifecycle {
    postcondition {
      condition     = self.project_id == "adept-presence-510022-p7"
      error_message = "Refusing discovery: unexpected project ID."
    }
    postcondition {
      condition     = self.name == "oconnordev-tools"
      error_message = "Refusing discovery: project name must be oconnordev-tools."
    }
    postcondition {
      condition     = self.number == "693193037198"
      error_message = "Refusing discovery: project number must be 693193037198."
    }
  }
}

resource "google_project" "google_auth" {
  project_id      = "adept-presence-510022-p7"
  name            = "oconnordev-tools"
  deletion_policy = "ABANDON"

  # No billing, parent, labels, services, IAM or network management is introduced.
  lifecycle {
    prevent_destroy = true
    # Import sets this creation-only flag true, not a network inventory result.
    # Never use false: provider creation would enable Compute and delete default.
    ignore_changes = [auto_create_network]

    precondition {
      condition     = data.google_project.google_auth.project_id == "adept-presence-510022-p7" && data.google_project.google_auth.number == "693193037198" && data.google_project.google_auth.name == "oconnordev-tools"
      error_message = "Refusing adoption: live discovery identity mismatch."
    }
    postcondition {
      condition     = self.project_id == "adept-presence-510022-p7" && self.number == "693193037198" && self.name == "oconnordev-tools"
      error_message = "Refusing adoption: managed project identity mismatch."
    }
  }
}
