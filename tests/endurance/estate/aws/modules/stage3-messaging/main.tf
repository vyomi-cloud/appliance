# Stage 3 - messaging + events: sqs.*, sns.*, eventbridge.*
terraform {
  required_providers { aws = { source = "hashicorp/aws" } }
}
variable "name" { default = "endurance" }
variable "kms_key_arn" {}
locals { tags = { Estate = "vyomi-endurance", Stage = "3-messaging-events" } }

# ---- SQS (sqs.queue.crud/attributes/fifo/dlq-redrive/tags/redrive-allow-policy)
resource "aws_sqs_queue" "dlq" {
  name = "${var.name}-orders-dlq"
  tags = local.tags
}
resource "aws_sqs_queue" "orders" {
  name                       = "${var.name}-orders"
  visibility_timeout_seconds = 45
  message_retention_seconds  = 86400
  receive_wait_time_seconds  = 5
  redrive_policy = jsonencode({ deadLetterTargetArn = aws_sqs_queue.dlq.arn, maxReceiveCount = 4 })
  tags = local.tags
}
resource "aws_sqs_queue_redrive_allow_policy" "dlq" {
  queue_url = aws_sqs_queue.dlq.id
  redrive_allow_policy = jsonencode({ redrivePermission = "byQueue", sourceQueueArns = [aws_sqs_queue.orders.arn] })
}
resource "aws_sqs_queue" "fifo" {
  name                        = "${var.name}-ledger.fifo"
  fifo_queue                  = true
  content_based_deduplication = true
  tags                        = local.tags
}

# ---- SNS (sns.topic.crud/tags/access-policy, sns.subscription.crud/filter-policy/raw-delivery)
resource "aws_sns_topic" "events" {
  name = "${var.name}-events"
  tags = local.tags
}
resource "aws_sqs_queue_policy" "orders_from_sns" {
  queue_url = aws_sqs_queue.orders.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow", Principal = { Service = "sns.amazonaws.com" }, Action = "sqs:SendMessage", Resource = aws_sqs_queue.orders.arn,
      Condition = { ArnEquals = { "aws:SourceArn" = aws_sns_topic.events.arn } }
    }]
  })
}
resource "aws_sns_topic_subscription" "orders" {
  topic_arn            = aws_sns_topic.events.arn
  protocol             = "sqs"
  endpoint             = aws_sqs_queue.orders.arn
  raw_message_delivery = true
  filter_policy        = jsonencode({ kind = ["order"] })
}

# ---- EventBridge (eventbridge.bus.crud, rule.crud, rule.targets)
resource "aws_cloudwatch_event_bus" "app" {
  name = "${var.name}-bus"
  tags = local.tags
}
resource "aws_cloudwatch_event_rule" "orders" {
  name           = "${var.name}-orders-rule"
  event_bus_name = aws_cloudwatch_event_bus.app.name
  event_pattern  = jsonencode({ source = ["endurance.orders"], "detail-type" = ["OrderPlaced"] })
  tags           = local.tags
}
resource "aws_cloudwatch_event_target" "to_sns" {
  rule           = aws_cloudwatch_event_rule.orders.name
  event_bus_name = aws_cloudwatch_event_bus.app.name
  target_id      = "fanout"
  arn            = aws_sns_topic.events.arn
}
resource "aws_cloudwatch_event_rule" "nightly" {
  name                = "${var.name}-nightly"
  schedule_expression = "rate(1 day)"
  tags                = local.tags
}

output "orders_queue_url" { value = aws_sqs_queue.orders.id }
output "topic_arn" { value = aws_sns_topic.events.arn }
output "bus_name" { value = aws_cloudwatch_event_bus.app.name }
