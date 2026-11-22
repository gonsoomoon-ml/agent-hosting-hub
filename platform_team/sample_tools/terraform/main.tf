# The in-house tools: one Lambda for every tool target of the tool gateway (synthetic data only).
# The code is the hub's package (build/platform_team.zip); the handler uses the standard library only.

resource "aws_iam_role" "tools" {
  name = "${var.prefix}-tools-lambda-role"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "lambda.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
}

# Terraform owns the log group, so `terraform destroy` removes it too.
resource "aws_cloudwatch_log_group" "tools" {
  name              = "/aws/lambda/${var.prefix}-tools"
  retention_in_days = 14
}

resource "aws_iam_role_policy" "tools" {
  name = "logs"
  role = aws_iam_role.tools.id
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = "${aws_cloudwatch_log_group.tools.arn}:*" }]
  })
}

resource "aws_lambda_function" "tools" {
  function_name    = "${var.prefix}-tools"
  description      = "Sample in-house tools behind the tool gateway (synthetic data)"
  role             = aws_iam_role.tools.arn
  runtime          = "python3.13"
  handler          = "platform_team.sample_tools.tool_handler.handler"
  filename         = var.code_zip
  source_code_hash = filebase64sha256(var.code_zip)
  timeout          = 10
  depends_on       = [aws_iam_role_policy.tools, aws_cloudwatch_log_group.tools]
}
