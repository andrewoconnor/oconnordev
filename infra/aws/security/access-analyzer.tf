resource "aws_accessanalyzer_analyzer" "organization" {
  analyzer_name = "oconnordev-organization"
  type          = "ORGANIZATION"
}
