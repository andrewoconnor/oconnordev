# Preservation-only adoption; evidence: docs/assets/github-settings-observed.json.
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

import {
  for_each = local.repository_labels
  to       = github_issue_label.observed[each.key]
  id       = "oconnordev:${each.key}"
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
  }

  lifecycle {
    prevent_destroy = true
  }
}

import {
  to = github_repository_ruleset.master
  id = "oconnordev:24274432"
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

import {
  to = github_branch_default.observed
  id = "oconnordev"
}

# Authoritative for topics only; observed complete empty list, not unknown.
resource "github_repository_topics" "observed" {
  repository = "oconnordev"
  topics     = []

  lifecycle {
    prevent_destroy = true
  }
}

import {
  to = github_repository_topics.observed
  id = "oconnordev"
}
