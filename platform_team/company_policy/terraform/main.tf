# The hub's one policy engine. Every company policy lives here: the dev team's shared tool permit (dev_access),
# the permits the hosting review grants, and the company policies the platform team deploys.
# Both gateways enforce it.
resource "aws_bedrockagentcore_policy_engine" "hub" {
  name        = "${var.prefix}_pe"
  description = "Company policy for the AI agent hosting hub"
}
