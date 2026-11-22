# Where alerts go: one SNS topic. A failed hosting review and the hub's alarms publish here.
# The SQS inbox behind it lets checks read what was sent; an email subscription is optional.
# And the alarm on one tool's calls per minute, which tells the platform team that an agent may be looping.

resource "aws_sns_topic" "alerts" {
  name = "${var.prefix}-alerts"
}

resource "aws_sqs_queue" "inbox" {
  name = "${var.prefix}-alerts-inbox"
}

resource "aws_sqs_queue_policy" "inbox" {
  queue_url = aws_sqs_queue.inbox.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "sns.amazonaws.com" }
      Action    = "sqs:SendMessage"
      Resource  = aws_sqs_queue.inbox.arn
      Condition = { ArnEquals = { "aws:SourceArn" = aws_sns_topic.alerts.arn } }
    }]
  })
}

resource "aws_sns_topic_subscription" "inbox" {
  topic_arn            = aws_sns_topic.alerts.arn
  protocol             = "sqs"
  endpoint             = aws_sqs_queue.inbox.arn
  raw_message_delivery = true
  depends_on           = [aws_sqs_queue_policy.inbox]
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
