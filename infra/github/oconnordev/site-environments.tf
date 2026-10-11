locals {
  production_site_environments = toset(["oconnordev-production", "drumrollworld-production"])
}

# Environment subjects do not encode a branch. GitHub's protection gate must
# reject non-master deployment jobs before a runner can request their OIDC token.
resource "github_repository_environment" "site" {
  for_each    = local.production_site_environments
  repository  = "oconnordev"
  environment = each.key

  deployment_branch_policy {
    protected_branches     = false
    custom_branch_policies = true
  }
}

resource "github_repository_environment_deployment_policy" "master" {
  for_each       = local.production_site_environments
  repository     = "oconnordev"
  environment    = github_repository_environment.site[each.key].environment
  branch_pattern = "master"
}
