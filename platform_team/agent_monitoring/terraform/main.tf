# Where alerts go: one SNS topic. A failed hosting review and (later) alarms publish here.
# The SQS inbox behind it lets checks read what was sent; an email subscription is optional.

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
