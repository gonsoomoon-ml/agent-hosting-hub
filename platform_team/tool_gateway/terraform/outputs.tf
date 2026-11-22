output "gateway_id" {
  value = aws_bedrockagentcore_gateway.tools.gateway_id
}

# Policies name this gateway's tools, so whoever uses the ARN waits until the targets exist.
output "gateway_arn" {
  value      = aws_bedrockagentcore_gateway.tools.gateway_arn
  depends_on = [aws_bedrockagentcore_gateway_target.tool]
}

output "gateway_url" {
  value = aws_bedrockagentcore_gateway.tools.gateway_url
}
