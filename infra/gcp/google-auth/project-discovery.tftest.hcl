# Offline fixture only: runner copies production configuration except imports.tf.
# OpenTofu 1.13 mocks cannot import. This is NOT a live/no-change import plan.
mock_provider "google" {
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

run "wrong_managed_number_fails" {
  command = plan
  override_resource {
    target = google_project.google_auth
    values = { number = "693193037199" }
  }
  expect_failures = [google_project.google_auth]
}
