# The custom guardrail: the company's own rules of a fixed form, in one Amazon Bedrock Guardrails resource, and the
# interceptor Lambda that applies it on the agent gateway to every request and every answer. A banned code name is
# blocked; an employee ID is masked and the call goes on. The interceptor is attached to the gateway by an API call
# (guardrail.sh attach), not here: the agent gateway's Terraform ignores its interceptor setting.
# The Lambda's role may apply this one guardrail (bedrock:ApplyGuardrail on its ARN) and write its own log group;
# nothing else. The code is the hub's package (build/platform_team.zip), which carries the bedrock-runtime API model.

resource "aws_bedrock_guardrail" "company" {
  name                      = "${var.prefix}-company-guardrail"
  description               = "Company rules of a fixed form: banned code names are blocked, employee IDs are masked"
  blocked_input_messaging   = "Blocked by the company guardrail."
  blocked_outputs_messaging = "Blocked by the company guardrail."

  word_policy_config {
    dynamic "words_config" {
      for_each = var.code_names
      content {
        text           = words_config.value
        input_action   = "BLOCK"
        input_enabled  = true
        output_action  = "BLOCK"
        output_enabled = true
      }
    }
  }

  sensitive_information_policy_config {
    # Without the input and output settings the pattern would be masked in answers only.
    regexes_config {
      name           = "employee_id"
      description    = "Employee ID"
      pattern        = var.employee_id_pattern
      action         = "ANONYMIZE"
      input_action   = "ANONYMIZE"
      input_enabled  = true
      output_action  = "ANONYMIZE"
      output_enabled = true
    }
  }
}

# The interceptor applies a fixed version, not the working draft. A change of the rules updates the draft, and this
# makes a new version from it. create_before_destroy orders the replacement: the new version, then the Lambda's
# GUARDRAIL_VERSION, then the old version is deleted. Destroy-first would delete the version the Lambda still names,
# and while it does every request through the agent gateway is refused (the interceptor fails closed).
# Not skip_destroy: Terraform deletes each version itself, as `make destroy` did in the run (the version, then the
# guardrail). Terraform applies create_before_destroy to the guardrail too; no argument of aws_bedrock_guardrail
# forces a replacement (provider 6.73.0), so it is only ever updated in place.
resource "aws_bedrock_guardrail_version" "company" {
  guardrail_arn = aws_bedrock_guardrail.company.guardrail_arn
  description   = "The rules the interceptor applies"
  lifecycle {
    create_before_destroy = true
    replace_triggered_by  = [aws_bedrock_guardrail.company]
  }
}

resource "aws_iam_role" "guardrail" {
  name = "${var.prefix}-guardrail-role"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "lambda.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
}

# Terraform owns the log group, so `terraform destroy` removes it too.
resource "aws_cloudwatch_log_group" "guardrail" {
  name              = "/aws/lambda/${var.prefix}-guardrail"
  retention_in_days = 14
}

resource "aws_iam_role_policy" "guardrail" {
  name = "guardrail"
  role = aws_iam_role.guardrail.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["bedrock:ApplyGuardrail"], Resource = [aws_bedrock_guardrail.company.guardrail_arn] },
      { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = "${aws_cloudwatch_log_group.guardrail.arn}:*" },
    ]
  })
}

# The name is the one the agent gateway's role may invoke (agent_gateway/terraform, lambda:InvokeFunction).
resource "aws_lambda_function" "guardrail" {
  function_name    = "${var.prefix}-guardrail"
  description      = "Custom guardrail: the agent gateway's interceptor (Amazon Bedrock Guardrails on every request and answer)"
  role             = aws_iam_role.guardrail.arn
  runtime          = "python3.13"
  handler          = "platform_team.custom_guardrail.interceptor_lambda.handler"
  filename         = var.code_zip
  source_code_hash = filebase64sha256(var.code_zip)
  timeout          = 8
  memory_size      = 256
  environment {
    variables = {
      GUARDRAIL_ID      = aws_bedrock_guardrail.company.guardrail_id
      GUARDRAIL_VERSION = aws_bedrock_guardrail_version.company.version
    }
  }
  depends_on = [aws_iam_role_policy.guardrail, aws_cloudwatch_log_group.guardrail]
}

# While the interceptor fails, the agent gateway refuses every request (fail closed): one error in a minute alerts.
resource "aws_cloudwatch_metric_alarm" "guardrail_errors" {
  alarm_name          = "${var.prefix}-guardrail-errors"
  alarm_description   = "The custom guardrail's interceptor failed: while it fails, the agent gateway refuses every request"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.guardrail.function_name }
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [var.topic_arn]
}
