# This root discovers an existing project; it owns no Google resources.
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
