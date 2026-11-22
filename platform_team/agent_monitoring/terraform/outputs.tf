output "topic_arn" {
  value = aws_sns_topic.alerts.arn
}

output "tool_alarm_name" {
  value = aws_cloudwatch_metric_alarm.tool_calls.alarm_name
}
