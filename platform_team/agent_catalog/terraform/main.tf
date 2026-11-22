# The catalog: tools and agents as registry records. Approval is manual (no auto-approval rules),
# so a search finds approved records only. Records are made by API (catalog_records.py), not Terraform.
resource "aws_agentregistry_registry" "catalog" {
  name        = "${var.prefix}-registry"
  description = "Agent catalog of the AI agent hosting hub (manual approval)"
  discovery_configuration {
    authorizer_type = "AWS_IAM"
  }
}
