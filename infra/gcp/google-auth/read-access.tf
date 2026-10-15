# Stage three adopts owner-granted existing read memberships, not new grants.
# Native auth remains unchanged; no policy/binding resource owns other members.
resource "google_project_iam_member" "wif_viewer_native" {
  project = "adept-presence-510022-p7"
  role    = "roles/iam.workloadIdentityPoolViewer"
  member  = "serviceAccount:gcp-01m4xs8mrej8cdgz286edc0ab2@spacelift.iam.gserviceaccount.com"

  lifecycle {
    prevent_destroy = true
  }
}

# Scope to ONLY the manual account, never project-wide SA Viewer.
resource "google_service_account_iam_member" "viewer_native" {
  service_account_id = "projects/adept-presence-510022-p7/serviceAccounts/spacelift-google-auth@adept-presence-510022-p7.iam.gserviceaccount.com"
  role               = "roles/iam.serviceAccountViewer"
  member             = "serviceAccount:gcp-01m4xs8mrej8cdgz286edc0ab2@spacelift.iam.gserviceaccount.com"

  lifecycle {
    prevent_destroy = true
  }
}
