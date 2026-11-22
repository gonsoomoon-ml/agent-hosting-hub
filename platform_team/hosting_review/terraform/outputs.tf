output "bucket" {
  value = aws_s3_bucket.inbox.bucket
}

# A new rule misses events for a while: whoever reads the machine's ARN (the platform's SSM value) waits for it.
output "machine_arn" {
  value      = aws_sfn_state_machine.review.arn
  depends_on = [time_sleep.rule_settles]
}
