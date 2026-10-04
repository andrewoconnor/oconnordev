moved {
  from = spacelift_stack.oconnordev_general
  to   = spacelift_stack.accounts["general"]
}

moved {
  from = spacelift_stack.oconnordev_production
  to   = spacelift_stack.accounts["production"]
}

moved {
  from = spacelift_stack.oconnordev_hermes
  to   = spacelift_stack.accounts["hermes"]
}

moved {
  from = spacelift_stack.oconnordev_security
  to   = spacelift_stack.accounts["security"]
}

moved {
  from = spacelift_stack.drumrollworld
  to   = spacelift_stack.accounts["drumrollworld"]
}

moved {
  from = spacelift_aws_integration_attachment.oconnordev_general
  to   = spacelift_aws_integration_attachment.accounts["general"]
}

moved {
  from = spacelift_aws_integration_attachment.oconnordev_production
  to   = spacelift_aws_integration_attachment.accounts["production"]
}

moved {
  from = spacelift_aws_integration_attachment.oconnordev_hermes
  to   = spacelift_aws_integration_attachment.accounts["hermes"]
}

moved {
  from = spacelift_aws_integration_attachment.oconnordev_security
  to   = spacelift_aws_integration_attachment.accounts["security"]
}

moved {
  from = spacelift_aws_integration_attachment.drumrollworld
  to   = spacelift_aws_integration_attachment.accounts["drumrollworld"]
}

# Keep the existing Spacelift stack and AWS integration attachment in place;
# only their Terraform for_each key changes from the old account label.
moved {
  from = spacelift_stack.accounts["hermes"]
  to   = spacelift_stack.accounts["tools"]
}

moved {
  from = spacelift_aws_integration_attachment.accounts["hermes"]
  to   = spacelift_aws_integration_attachment.accounts["tools"]
}

moved {
  from = spacelift_stack_dependency.production_hermes_gateway
  to   = spacelift_stack_dependency.production_tools_gateway
}

moved {
  from = spacelift_stack_dependency_reference.production_hermes_gateway_origin
  to   = spacelift_stack_dependency_reference.production_tools_gateway_origin
}

moved {
  from = spacelift_stack_dependency.hermes_security_gateway
  to   = spacelift_stack_dependency.tools_security_gateway
}

moved {
  from = spacelift_stack_dependency_reference.hermes_security_gateway_url
  to   = spacelift_stack_dependency_reference.tools_security_gateway_url
}

moved {
  from = spacelift_stack_dependency_reference.hermes_security_gateway_arn
  to   = spacelift_stack_dependency_reference.tools_security_gateway_arn
}
