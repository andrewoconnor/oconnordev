provider "google" {
  project = "adept-presence-510022-p7"
  # Match resource policy on import read: avoids PREVENT -> ABANDON plan update.
  deletion_policy                 = "ABANDON"
  add_terraform_attribution_label = false
  default_labels                  = {}
}
