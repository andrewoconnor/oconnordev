variable "site_state_handoff_complete" {
  description = "Owner confirmation after both locked states have been transferred and zero-destroy plans reviewed. See docs/static-site-state-migration.md."
  type        = bool
  default     = false
}
resource "terraform_data" "site_state_handoff_guard" {
  input = var.site_state_handoff_complete
  lifecycle {
    precondition {
      condition     = var.site_state_handoff_complete
      error_message = "STOP: mandatory owner-operated cross-state transfer is not complete. Freeze both stacks and follow docs/static-site-state-migration.md before enabling applies."
    }
  }
}

removed {
  from = aws_cloudfront_distribution.oconnordev
  lifecycle {
    destroy = false
  }
}

removed {
  from = aws_cloudfront_origin_access_control.oconnordev
  lifecycle {
    destroy = false
  }
}

removed {
  from = aws_cloudfront_response_headers_policy.oconnordev
  lifecycle {
    destroy = false
  }
}

removed {
  from = aws_route53_record.apex
  lifecycle {
    destroy = false
  }
}

removed {
  from = aws_route53_record.www
  lifecycle {
    destroy = false
  }
}

removed {
  from = aws_s3_bucket.web
  lifecycle {
    destroy = false
  }
}

removed {
  from = aws_s3_bucket_lifecycle_configuration.web
  lifecycle {
    destroy = false
  }
}

removed {
  from = aws_s3_bucket_policy.web_tls
  lifecycle {
    destroy = false
  }
}

removed {
  from = aws_s3_bucket_public_access_block.web
  lifecycle {
    destroy = false
  }
}

removed {
  from = aws_s3_bucket_server_side_encryption_configuration.web
  lifecycle {
    destroy = false
  }
}

removed {
  from = aws_s3_bucket_versioning.web
  lifecycle {
    destroy = false
  }
}

removed {
  from = aws_iam_role.github_actions_site_deploy
  lifecycle {
    destroy = false
  }
}

removed {
  from = aws_iam_role_policy.github_actions_site_deploy
  lifecycle {
    destroy = false
  }
}
