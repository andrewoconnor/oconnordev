# Offline fixture only: runner copies production configuration except imports.tf.
# OpenTofu 1.13 mocks cannot import. This is NOT a live/no-change import plan.
mock_provider "google" {
  mock_resource "google_iam_workload_identity_pool" {
    defaults = {
      name  = "projects/693193037198/locations/global/workloadIdentityPools/spacelift"
      state = "ACTIVE"
    }
  }
  mock_resource "google_iam_workload_identity_pool_provider" {
    defaults = {
      name  = "projects/693193037198/locations/global/workloadIdentityPools/spacelift/providers/spacelift"
      state = "ACTIVE"
    }
  }
  mock_resource "google_service_account" {
    defaults = {
      email     = "spacelift-google-auth@adept-presence-510022-p7.iam.gserviceaccount.com"
      unique_id = "109396950295423788712"
    }
  }
  mock_resource "google_project" {
    defaults = {
      number = "693193037198"
    }
  }
  mock_data "google_project" {
    defaults = {
      number    = "693193037198"
      name      = "oconnordev-tools"
      org_id    = ""
      folder_id = ""
      labels    = {}
    }
  }
}

run "exact_project_succeeds" {
  command = plan

  assert {
    condition     = google_project_iam_member.wif_viewer_native.project == "adept-presence-510022-p7" && google_project_iam_member.wif_viewer_native.role == "roles/iam.workloadIdentityPoolViewer" && google_project_iam_member.wif_viewer_native.member == "serviceAccount:gcp-01m4xs8mrej8cdgz286edc0ab2@spacelift.iam.gserviceaccount.com" && length(google_project_iam_member.wif_viewer_native.condition) == 0
    error_message = "Only the existing unconditional project WIF reader is allowed."
  }
  assert {
    condition     = google_service_account_iam_member.viewer_native.service_account_id == "projects/adept-presence-510022-p7/serviceAccounts/spacelift-google-auth@adept-presence-510022-p7.iam.gserviceaccount.com" && google_service_account_iam_member.viewer_native.role == "roles/iam.serviceAccountViewer" && google_service_account_iam_member.viewer_native.member == "serviceAccount:gcp-01m4xs8mrej8cdgz286edc0ab2@spacelift.iam.gserviceaccount.com" && length(google_service_account_iam_member.viewer_native.condition) == 0
    error_message = "SA Viewer is restricted to only the manual account and native member."
  }

  assert {
    condition     = google_iam_workload_identity_pool.spacelift.disabled == false && google_iam_workload_identity_pool.spacelift.display_name == "Spacelift" && google_iam_workload_identity_pool.spacelift.deletion_policy == "ABANDON"
    error_message = "Preserve the active pool, display name and deletion policy."
  }
  assert {
    condition     = google_iam_workload_identity_pool_provider.spacelift.display_name == "spacelift" && google_iam_workload_identity_pool_provider.spacelift.attribute_condition == "assertion.callerType == 'stack' && assertion.callerId == 'oconnordev-gcp-google-auth'" && google_iam_workload_identity_pool_provider.spacelift.attribute_mapping == tomap({ "attribute.stack" = "assertion.callerId", "google.subject" = "assertion.sub" })
    error_message = "Preserve the exact provider name and stack trust."
  }
  assert {
    condition     = google_iam_workload_identity_pool_provider.spacelift.oidc[0].issuer_uri == "https://andrewoconnor.app.spacelift.io" && google_iam_workload_identity_pool_provider.spacelift.oidc[0].allowed_audiences == tolist(["andrewoconnor.app.spacelift.io"]) && google_iam_workload_identity_pool_provider.spacelift.disabled == false && google_iam_workload_identity_pool_provider.spacelift.deletion_policy == "ABANDON"
    error_message = "Preserve exact issuer, audience and provider policies."
  }
  assert {
    condition     = coalesce(google_service_account.bootstrap.display_name, "absent") == "absent" && google_service_account.bootstrap.disabled == false && google_service_account.bootstrap.deletion_policy == "ABANDON"
    error_message = "Do not add missing service-account metadata or disable it."
  }
  assert {
    condition     = google_project_iam_member.browser_manual.member == "serviceAccount:spacelift-google-auth@adept-presence-510022-p7.iam.gserviceaccount.com" && google_project_iam_member.browser_native.member == "serviceAccount:gcp-01m4xs8mrej8cdgz286edc0ab2@spacelift.iam.gserviceaccount.com" && google_project_iam_member.browser_manual.role == "roles/browser" && google_project_iam_member.browser_native.role == "roles/browser"
    error_message = "Adopt only the two existing browser members."
  }
  assert {
    condition     = google_project.google_auth.deletion_policy == "ABANDON"
    error_message = "State removal must never delete the existing project."
  }
  assert {
    condition     = output.project_id == "adept-presence-510022-p7" && output.project_number == "693193037198" && output.project_name == "oconnordev-tools"
    error_message = "Discovery must return the exact approved project identity."
  }
}

run "wrong_number_fails" {
  command = plan
  override_data {
    target = data.google_project.google_auth
    values = {
      number = "693193037199"
      name   = "oconnordev-tools"
    }
  }
  expect_failures = [data.google_project.google_auth]
}

run "wrong_name_fails" {
  command = plan
  override_data {
    target = data.google_project.google_auth
    values = {
      number = "693193037198"
      name   = "another-project"
    }
  }
  expect_failures = [data.google_project.google_auth]
}

run "wrong_pool_state_fails" {
  command = plan
  override_resource {
    target = google_iam_workload_identity_pool.spacelift
    values = { state = "DELETED" }
  }
  expect_failures = [google_iam_workload_identity_pool.spacelift]
}

run "wrong_provider_name_fails" {
  command = plan
  override_resource {
    target = google_iam_workload_identity_pool_provider.spacelift
    values = { name = "projects/693193037198/locations/global/workloadIdentityPools/spacelift/providers/wrong" }
  }
  expect_failures = [google_iam_workload_identity_pool_provider.spacelift]
}

run "wrong_service_account_identity_fails" {
  command = plan
  override_resource {
    target = google_service_account.bootstrap
    values = { unique_id = "109396950295423788713" }
  }
  expect_failures = [google_service_account.bootstrap]
}

run "wrong_managed_number_fails" {
  command = plan
  override_resource {
    target = google_project.google_auth
    values = { number = "693193037199" }
  }
  expect_failures = [google_project.google_auth]
}
