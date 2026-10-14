mock_provider "google" {
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
