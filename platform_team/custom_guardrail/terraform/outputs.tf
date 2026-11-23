output "interceptor_arn" {
  value = aws_lambda_function.guardrail.arn
}

output "guardrail_id" {
  value = aws_bedrock_guardrail.company.guardrail_id
}

output "guardrail_version" {
  value = aws_bedrock_guardrail_version.company.version
}
