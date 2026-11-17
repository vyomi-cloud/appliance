# Stage 7 - observability / security / governance: cloudwatch.*, logs, ssm, cloudtrail, cost
terraform {
  required_providers { aws = { source = "hashicorp/aws" } }
}
variable "name" { default = "endurance" }
variable "kms_key_arn" {}
variable "queue_name" {}
variable "dlq_name" {}
variable "table_name" {}
variable "db_identifier" {}
variable "instance_id" {}
variable "topic_arn" {}
variable "log_bucket" {}
locals { tags = { Estate = "vyomi-endurance", Stage = "7-observability-ops" } }

# ---- Log groups with retention (aws.cloudwatch.logs.groups)
resource "aws_cloudwatch_log_group" "app" {
  name              = "/${var.name}/app"
  retention_in_days = 30
  kms_key_id        = var.kms_key_arn
  tags              = local.tags
}
resource "aws_cloudwatch_log_group" "audit" {
  name              = "/${var.name}/audit"
  retention_in_days = 365
  tags              = local.tags
}
resource "aws_cloudwatch_log_stream" "app" {
  name           = "web"
  log_group_name = aws_cloudwatch_log_group.app.name
}
# ---- Metric filter -> metric -> alarm (logs.metric-filters, alarms.metric)
resource "aws_cloudwatch_log_metric_filter" "errors" {
  name           = "${var.name}-errors"
  log_group_name = aws_cloudwatch_log_group.app.name
  pattern        = "ERROR"
  metric_transformation {
    name      = "AppErrors"
    namespace = "Endurance/App"
    value     = "1"
  }
}
resource "aws_cloudwatch_log_resource_policy" "app" {
  policy_name     = "${var.name}-logs-policy"
  policy_document = jsonencode({
    Version = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "es.amazonaws.com" }, Action = ["logs:PutLogEvents", "logs:CreateLogStream"], Resource = "*" }]
  })
}
resource "aws_cloudwatch_query_definition" "errors" {
  name            = "${var.name}/recent-errors"
  log_group_names = [aws_cloudwatch_log_group.app.name]
  query_string    = "fields @timestamp, @message | filter @message like /ERROR/ | sort @timestamp desc | limit 20"
}

# ---- Alarms on the stage 2/3 resources (alarms.metric, alarms.composite, alarms.actions)
resource "aws_cloudwatch_metric_alarm" "queue_depth" {
  alarm_name          = "${var.name}-orders-depth"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 60
  statistic           = "Average"
  threshold           = 100
  dimensions          = { QueueName = var.queue_name }
  alarm_actions       = [var.topic_arn]
  ok_actions          = [var.topic_arn]
  treat_missing_data  = "notBreaching"
  tags                = local.tags
}
resource "aws_cloudwatch_metric_alarm" "dlq_not_empty" {
  alarm_name          = "${var.name}-dlq-not-empty"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 60
  statistic           = "Maximum"
  threshold           = 0
  dimensions          = { QueueName = var.dlq_name }
  alarm_actions       = [var.topic_arn]
  tags                = local.tags
}
resource "aws_cloudwatch_metric_alarm" "ddb_throttle" {
  alarm_name          = "${var.name}-ddb-throttles"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "ThrottledRequests"
  namespace           = "AWS/DynamoDB"
  period              = 300
  statistic           = "Sum"
  threshold           = 5
  dimensions          = { TableName = var.table_name }
  alarm_actions       = [var.topic_arn]
  tags                = local.tags
}
resource "aws_cloudwatch_metric_alarm" "rds_cpu" {
  alarm_name          = "${var.name}-rds-cpu"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "CPUUtilization"
  namespace           = "AWS/RDS"
  period              = 300
  statistic           = "Average"
  threshold           = 80
  dimensions          = { DBInstanceIdentifier = var.db_identifier }
  alarm_actions       = [var.topic_arn]
  tags                = local.tags
}
resource "aws_cloudwatch_metric_alarm" "app_errors" {
  alarm_name          = "${var.name}-app-errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = aws_cloudwatch_log_metric_filter.errors.metric_transformation[0].name
  namespace           = "Endurance/App"
  period              = 60
  statistic           = "Sum"
  threshold           = 10
  alarm_actions       = [var.topic_arn]
  tags                = local.tags
}
resource "aws_cloudwatch_metric_alarm" "ec2_status" {
  alarm_name          = "${var.name}-ec2-status"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "StatusCheckFailed"
  namespace           = "AWS/EC2"
  period              = 60
  statistic           = "Maximum"
  threshold           = 0
  dimensions          = { InstanceId = var.instance_id }
  alarm_actions       = [var.topic_arn]
  tags                = local.tags
}
resource "aws_cloudwatch_composite_alarm" "data_tier" {
  alarm_name        = "${var.name}-data-tier-degraded"
  alarm_description = "any data-tier alarm"
  alarm_rule        = "ALARM(${aws_cloudwatch_metric_alarm.ddb_throttle.alarm_name}) OR ALARM(${aws_cloudwatch_metric_alarm.rds_cpu.alarm_name})"
  alarm_actions     = [var.topic_arn]
  tags              = local.tags
}

# ---- Dashboard (cloudwatch.dashboards)
resource "aws_cloudwatch_dashboard" "app" {
  dashboard_name = "${var.name}-overview"
  dashboard_body = jsonencode({
    widgets = [
      { type = "metric", x = 0, y = 0, width = 12, height = 6, properties = {
        title = "Orders queue", region = "us-east-1", stat = "Average", period = 60,
        metrics = [["AWS/SQS", "ApproximateNumberOfMessagesVisible", "QueueName", var.queue_name]] } },
      { type = "metric", x = 12, y = 0, width = 12, height = 6, properties = {
        title = "RDS CPU", region = "us-east-1", stat = "Average", period = 300,
        metrics = [["AWS/RDS", "CPUUtilization", "DBInstanceIdentifier", var.db_identifier]] } },
    ]
  })
}

# ---- SSM (ssm.* parameters, documents, maintenance windows)
resource "aws_ssm_parameter" "app_env" {
  name  = "/${var.name}/app/environment"
  type  = "String"
  value = "production"
  tags  = local.tags
}
resource "aws_ssm_parameter" "db_endpoint" {
  name  = "/${var.name}/app/db-identifier"
  type  = "String"
  value = var.db_identifier
  tags  = local.tags
}
resource "aws_ssm_parameter" "api_token" {
  name   = "/${var.name}/app/api-token"
  type   = "SecureString"
  value  = "endurance-secret-token"
  key_id = var.kms_key_arn
  tags   = local.tags
}
resource "aws_ssm_document" "patch" {
  name          = "${var.name}-run-shell"
  document_type = "Command"
  content = jsonencode({
    schemaVersion = "2.2"
    description   = "endurance shell runner"
    mainSteps     = [{ action = "aws:runShellScript", name = "run", inputs = { runCommand = ["echo endurance"] } }]
  })
  tags = local.tags
}
resource "aws_ssm_maintenance_window" "weekly" {
  name     = "${var.name}-weekly"
  schedule = "cron(0 2 ? * SUN *)"
  duration = 3
  cutoff   = 1
  tags     = local.tags
}

# ---- CloudTrail to the existing bucket (cloudtrail trail)
resource "aws_s3_bucket_policy" "trail" {
  bucket = var.log_bucket
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Sid = "AclCheck", Effect = "Allow", Principal = { Service = "cloudtrail.amazonaws.com" }, Action = "s3:GetBucketAcl", Resource = "arn:aws:s3:::${var.log_bucket}" },
      { Sid = "Write", Effect = "Allow", Principal = { Service = "cloudtrail.amazonaws.com" }, Action = "s3:PutObject", Resource = "arn:aws:s3:::${var.log_bucket}/trail/AWSLogs/123456789012/*", Condition = { StringEquals = { "s3:x-amz-acl" = "bucket-owner-full-control" } } },
    ]
  })
}
resource "aws_cloudtrail" "main" {
  name                          = "${var.name}-trail"
  s3_bucket_name                = var.log_bucket
  s3_key_prefix                 = "trail"
  include_global_service_events = true
  is_multi_region_trail         = false
  enable_log_file_validation    = true
  tags                          = local.tags
  depends_on                    = [aws_s3_bucket_policy.trail]
}

output "alarm_names" { value = [aws_cloudwatch_metric_alarm.queue_depth.alarm_name, aws_cloudwatch_composite_alarm.data_tier.alarm_name] }
output "log_group" { value = aws_cloudwatch_log_group.app.name }
