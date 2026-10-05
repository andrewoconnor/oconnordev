locals {
  cloudtrail_bucket_name = "oconnordev-cloudtrail"
  config_bucket_name     = "oconnordev-config"


  management_account_id = local.accounts["GENERAL"]

  cloudtrail_trail_arn = "arn:aws:cloudtrail:us-east-1:${local.accounts["GENERAL"]}:trail/oconnordev-organization"

  config_recorded_resource_types = [
    "AWS::BedrockAgentCore::Gateway",
    "AWS::BedrockAgentCore::GatewayTarget",
    "AWS::CloudFront::Distribution",
    "AWS::Cognito::UserPool",
    "AWS::IAM::Policy",
    "AWS::IAM::Role",
    "AWS::KMS::Key",
    "AWS::Lambda::Function",
    "AWS::Route53::HostedZone",
    "AWS::S3::Bucket",
    "AWS::SecretsManager::Secret",
  ]
}

locals {
  accounts = jsondecode(file("${path.module}/../accounts.json"))
}
