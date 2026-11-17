# Stage 8 - lifecycle / cost / ops: backup, budgets, resource groups, tag policy
terraform {
  required_providers { aws = { source = "hashicorp/aws" } }
}
variable "name" { default = "endurance" }
variable "kms_key_arn" {}
variable "topic_arn" {}
variable "backup_role_arn" {}
variable "table_arn" {}
variable "db_arn" {}
locals { tags = { Estate = "vyomi-endurance", Stage = "8-lifecycle" } }

resource "aws_backup_vault" "main" {
  name        = "${var.name}-vault"
  kms_key_arn = var.kms_key_arn
  tags        = local.tags
}
resource "aws_backup_plan" "daily" {
  name = "${var.name}-daily"
  rule {
    rule_name         = "daily-35d"
    target_vault_name = aws_backup_vault.main.name
    schedule          = "cron(0 5 * * ? *)"
    start_window      = 60
    completion_window = 180
    lifecycle { delete_after = 35 }
  }
  tags = local.tags
}
resource "aws_backup_selection" "data" {
  name         = "${var.name}-data-tier"
  plan_id      = aws_backup_plan.daily.id
  iam_role_arn = var.backup_role_arn
  resources    = [var.table_arn, var.db_arn]
}
resource "aws_budgets_budget" "monthly" {
  name         = "${var.name}-monthly"
  budget_type  = "COST"
  limit_amount = "500"
  limit_unit   = "USD"
  time_unit    = "MONTHLY"
  notification {
    comparison_operator       = "GREATER_THAN"
    threshold                 = 80
    threshold_type            = "PERCENTAGE"
    notification_type         = "ACTUAL"
    subscriber_email_addresses = ["finops@example.com"]
  }
}
resource "aws_resourcegroups_group" "estate" {
  name = "${var.name}-estate"
  resource_query {
    query = jsonencode({ ResourceTypeFilters = ["AWS::AllSupported"], TagFilters = [{ Key = "Estate", Values = ["vyomi-endurance"] }] })
  }
  tags = local.tags
}
output "vault" { value = aws_backup_vault.main.name }
