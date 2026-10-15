# Adopt only owner-inventoried existing objects. This does not activate WIF.
resource "google_iam_workload_identity_pool" "spacelift" {
  project                   = "adept-presence-510022-p7"
  workload_identity_pool_id = "spacelift"
  display_name              = "Spacelift"
  disabled                  = false
  deletion_policy           = "ABANDON"
  # No description was returned; the provider reads it as an empty string.

  lifecycle {
    prevent_destroy = true
    postcondition {
      condition     = self.name == "projects/693193037198/locations/global/workloadIdentityPools/spacelift" && self.state == "ACTIVE"
      error_message = "Refusing adoption: unexpected pool identity or state."
    }
  }
}

resource "google_iam_workload_identity_pool_provider" "spacelift" {
  project                            = "adept-presence-510022-p7"
  workload_identity_pool_id          = google_iam_workload_identity_pool.spacelift.workload_identity_pool_id
  workload_identity_pool_provider_id = "spacelift"
  display_name                       = "spacelift"
  disabled                           = false
  deletion_policy                    = "ABANDON"
  attribute_condition                = "assertion.callerType == 'stack' && assertion.callerId == 'oconnordev-gcp-google-auth'"
  attribute_mapping = {
    "attribute.stack" = "assertion.callerId"
    "google.subject"  = "assertion.sub"
  }
  oidc {
    issuer_uri        = "https://andrewoconnor.app.spacelift.io"
    allowed_audiences = ["andrewoconnor.app.spacelift.io"]
  }

  lifecycle {
    prevent_destroy = true
    postcondition {
      condition     = self.name == "projects/693193037198/locations/global/workloadIdentityPools/spacelift/providers/spacelift" && self.state == "ACTIVE"
      error_message = "Refusing adoption: unexpected provider identity or state."
    }
  }
}

resource "google_service_account" "bootstrap" {
  project         = "adept-presence-510022-p7"
  account_id      = "spacelift-google-auth"
  disabled        = false
  deletion_policy = "ABANDON"
  # Owner read returned no displayName or description. Do not fill them in.

  lifecycle {
    prevent_destroy = true
    postcondition {
      condition     = self.email == "spacelift-google-auth@adept-presence-510022-p7.iam.gserviceaccount.com" && self.unique_id == "109396950295423788712"
      error_message = "Refusing adoption: unexpected bootstrap service account."
    }
  }
}

# Additive single members only: preserve every other member and owner policy.
resource "google_project_iam_member" "browser_manual" {
  project = "adept-presence-510022-p7"
  role    = "roles/browser"
  member  = "serviceAccount:spacelift-google-auth@adept-presence-510022-p7.iam.gserviceaccount.com"

  lifecycle {
    prevent_destroy = true
  }
}

# The native account itself remains owned by the administrative Spacelift stack.
resource "google_project_iam_member" "browser_native" {
  project = "adept-presence-510022-p7"
  role    = "roles/browser"
  member  = "serviceAccount:gcp-01m4xs8mrej8cdgz286edc0ab2@spacelift.iam.gserviceaccount.com"

  lifecycle {
    prevent_destroy = true
  }
}
