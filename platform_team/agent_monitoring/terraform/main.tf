# Where alerts go: one SNS topic. A failed hosting review and the hub's alarms publish here.
# An email subscription is optional; the checks that read an alert make their own queue and subscribe it for the run.
# The alarm on one tool's calls per minute, which tells the platform team that an agent may be looping.
# And what the two gateways record: their logs into a log group each, their traces into X-Ray.

data "aws_caller_identity" "me" {}
data "aws_region" "here" {}

locals {
  account = data.aws_caller_identity.me.account_id
  region  = data.aws_region.here.region
  # the gateways whose logs and traces are delivered, by the last part of their log group's name
  gateways = {
    agents = var.agent_gateway_arn
    tools  = var.tool_gateway_arn
  }
}

resource "aws_sns_topic" "alerts" {
  name = "${var.prefix}-alerts"
}

resource "aws_sns_topic_subscription" "email" {
  count     = var.alert_email == "" ? 0 : 1
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# The tool gateway counts each tool's calls (Invocations, one datapoint a minute, with the tool's name as a dimension).
# The watched tool is the one the incident's loop calls; the count is of every caller of that tool.
resource "aws_cloudwatch_metric_alarm" "tool_calls" {
  alarm_name        = "${var.prefix}-tool-calls"
  alarm_description = "More calls of ${var.watched_tool} in one minute than normal use makes: an agent may be asking again and again"
  namespace         = "AWS/Bedrock-AgentCore"
  metric_name       = "Invocations"
  dimensions = {
    Method    = "tools/call"
    Name      = var.watched_tool
    Operation = "InvokeGateway"
    Protocol  = "MCP"
    Resource  = var.tool_gateway_arn
  }
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 1
  comparison_operator = "GreaterThanThreshold"
  threshold           = var.tool_calls_per_minute
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

# ------------------------------------------------------------------ the gateways' logs and traces
# AgentCore makes no log destination for a gateway by itself ("Add observability to your Amazon Bedrock AgentCore
# resources", AgentCore developer guide, read on 2026-11-22). So each gateway gets two CloudWatch Logs log
# deliveries, each a source on the gateway, a destination and the delivery between them: its application logs into
# the log group /aws/vendedlogs/bedrock-agentcore/<prefix>-<agents or tools>, its traces into X-Ray. With Transaction
# Search on, X-Ray keeps spans in the log group aws/spans, which belongs to the account, not to the hub.

resource "aws_cloudwatch_log_group" "gateway" {
  for_each          = local.gateways
  name              = "/aws/vendedlogs/bedrock-agentcore/${var.prefix}-${each.key}"
  retention_in_days = 14
}

# The delivery writes into a log group only under a resource policy that lets delivery.logs.amazonaws.com write
# there. With none, it adds a statement to the account's shared policy, which `terraform destroy` would leave
# behind (the state machine's log in hosting_review has a policy of its own for the same reason).
resource "aws_cloudwatch_log_resource_policy" "gateway_logs" {
  policy_name = "${var.prefix}-gateway-logs"
  policy_document = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "delivery.logs.amazonaws.com" }
      Action    = ["logs:CreateLogStream", "logs:PutLogEvents"]
      Resource  = [for g in aws_cloudwatch_log_group.gateway : "${g.arn}:log-stream:*"]
      Condition = {
        StringEquals = { "aws:SourceAccount" = local.account }
        ArnLike      = { "aws:SourceArn" = "arn:aws:logs:${local.region}:${local.account}:*" }
      }
    }]
  })
}

resource "aws_cloudwatch_log_delivery_source" "gateway_logs" {
  for_each     = local.gateways
  name         = "${var.prefix}-${each.key}-logs"
  log_type     = "APPLICATION_LOGS"
  resource_arn = each.value
}

resource "aws_cloudwatch_log_delivery_destination" "gateway_logs" {
  for_each = local.gateways
  name     = "${var.prefix}-${each.key}-logs"
  delivery_destination_configuration {
    destination_resource_arn = aws_cloudwatch_log_group.gateway[each.key].arn
  }
}

resource "aws_cloudwatch_log_delivery" "gateway_logs" {
  for_each                 = local.gateways
  delivery_source_name     = aws_cloudwatch_log_delivery_source.gateway_logs[each.key].name
  delivery_destination_arn = aws_cloudwatch_log_delivery_destination.gateway_logs[each.key].arn
  depends_on               = [aws_cloudwatch_log_resource_policy.gateway_logs]
}

resource "aws_cloudwatch_log_delivery_source" "gateway_traces" {
  for_each     = local.gateways
  name         = "${var.prefix}-${each.key}-traces"
  log_type     = "TRACES"
  resource_arn = each.value
}

# X-Ray takes no destination configuration (the provider refuses one with the type XRAY)
resource "aws_cloudwatch_log_delivery_destination" "gateway_traces" {
  for_each                  = local.gateways
  name                      = "${var.prefix}-${each.key}-traces"
  delivery_destination_type = "XRAY"
}

resource "aws_cloudwatch_log_delivery" "gateway_traces" {
  for_each                 = local.gateways
  delivery_source_name     = aws_cloudwatch_log_delivery_source.gateway_traces[each.key].name
  delivery_destination_arn = aws_cloudwatch_log_delivery_destination.gateway_traces[each.key].arn
}
