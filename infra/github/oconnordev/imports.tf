import {
  for_each = {
    "oconnordev-production"    = 62707941
    "drumrollworld-production" = 62708068
  }
  to = github_repository_environment_deployment_policy.master[each.key]
  id = "oconnordev:${each.key}:${each.value}"
}
