output "gateway_id" {
  value = aws_bedrockagentcore_gateway.agents.gateway_id
}

output "gateway_arn" {
  value = aws_bedrockagentcore_gateway.agents.gateway_arn
}

output "gateway_url" {
  value = aws_bedrockagentcore_gateway.agents.gateway_url
}

output "role_arn" {
  value = aws_iam_role.agents.arn
}
