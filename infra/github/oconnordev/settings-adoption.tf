# Adopted from docs/assets/github-settings-observed.json; required status checks are added policy.
# Singular resources leave any unlisted labels externally owned.
locals {
  repository_labels = {
    "bug" = {
      color       = "d73a4a"
      description = "Something isn't working"
    }
    "duplicate" = {
      color       = "cfd3d7"
      description = "This issue or pull request already exists"
    }
    "enhancement" = {
      color       = "a2eeef"
      description = "New feature or request"
    }
    "good first issue" = {
      color       = "7057ff"
      description = "Good for newcomers"
    }
    "help wanted" = {
      color       = "008672"
      description = "Extra attention is needed"
    }
    "invalid" = {
      color       = "e4e669"
      description = "This doesn't seem right"
    }
    "question" = {
      color       = "d876e3"
      description = "Further information is requested"
    }
    "wontfix" = {
      color       = "ffffff"
      description = "This will not be worked on"
    }
  }

  github_actions_app_id = 15368
  required_status_checks = [
    "Agent and infrastructure unit tests",
    "Block known-vulnerable dependency changes",
    "Checkov scan",
    "Format, workflow lint, and affected-root validation",
    "TFLint",
    "Thundermail image / Build and smoke-test",
    "drumrollworld / Lint, format, build and test",
    "oconnordev / Lint, format, build and test",
  ]
}

resource "github_issue_label" "observed" {
  for_each = local.repository_labels

  repository  = "oconnordev"
  name        = each.key
  color       = each.value.color
  description = each.value.description

  lifecycle {
    prevent_destroy = true
  }
}


resource "github_repository_ruleset" "master" {
  repository  = "oconnordev"
  name        = "master"
  target      = "branch"
  enforcement = "active"

  # Explicitly empty in the authenticated detail; zero optional bypass blocks.
  # The v6.13.0 schema uses blocks, not a bypass_actors = [] argument.

  conditions {
    ref_name {
      include = ["~DEFAULT_BRANCH"]
      exclude = []
    }
  }

  rules {
    deletion         = true
    non_fast_forward = true
    pull_request {
      allowed_merge_methods             = ["squash"]
      dismiss_stale_reviews_on_push     = false
      require_code_owner_review         = false
      require_last_push_approval        = false
      required_approving_review_count   = 0
      required_review_thread_resolution = false
    }
    required_status_checks {
      strict_required_status_checks_policy = false

      dynamic "required_check" {
        for_each = toset(local.required_status_checks)
        content {
          context        = required_check.value
          integration_id = local.github_actions_app_id
        }
      }
    }
  }

  lifecycle {
    prevent_destroy = true
  }
}

# Standalone resources avoid unreadable github_repository administration defaults.
resource "github_branch_default" "observed" {
  repository      = "oconnordev"
  branch          = "master"
  rename          = false
  wait_for_rename = false

  lifecycle {
    prevent_destroy = true
  }
}

# Authoritative for topics only; observed complete empty list, not unknown.
resource "github_repository_topics" "observed" {
  repository = "oconnordev"
  topics     = []

  lifecycle {
    prevent_destroy = true
  }
}
