# Existing project history: already adopted, so this must be a no-op, not import six.
import {
  to = google_project.google_auth
  id = "adept-presence-510022-p7"
}

# Project ID in importer paths preserves the configured project field; API names
# read back use project number 693193037198. Both identify the same project.
import {
  to = google_iam_workload_identity_pool.spacelift
  id = "projects/adept-presence-510022-p7/locations/global/workloadIdentityPools/spacelift"
}

import {
  to = google_iam_workload_identity_pool_provider.spacelift
  id = "projects/adept-presence-510022-p7/locations/global/workloadIdentityPools/spacelift/providers/spacelift"
}

import {
  to = google_service_account.bootstrap
  id = "projects/adept-presence-510022-p7/serviceAccounts/spacelift-google-auth@adept-presence-510022-p7.iam.gserviceaccount.com"
}

import {
  to = google_project_iam_member.browser_manual
  id = "adept-presence-510022-p7 roles/browser serviceAccount:spacelift-google-auth@adept-presence-510022-p7.iam.gserviceaccount.com"
}

import {
  to = google_project_iam_member.browser_native
  id = "adept-presence-510022-p7 roles/browser serviceAccount:gcp-01m4xs8mrej8cdgz286edc0ab2@spacelift.iam.gserviceaccount.com"
}
