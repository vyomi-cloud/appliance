# Stage 6 - AI: bedrock.* (guardrails, agents, model invocation logging)
terraform {
  required_providers { aws = { source = "hashicorp/aws" } }
}
variable "name" { default = "endurance" }
variable "kms_key_arn" {}
variable "log_bucket" {}
locals { tags = { Estate = "vyomi-endurance", Stage = "6-ai" } }

data "aws_caller_identity" "me" {}

resource "aws_bedrock_guardrail" "app" {
  name                      = "${var.name}-guardrail"
  blocked_input_messaging   = "Blocked by endurance guardrail."
  blocked_outputs_messaging = "Blocked by endurance guardrail."
  description               = "endurance reference guardrail"
  content_policy_config {
    filters_config {
      type            = "HATE"
      input_strength  = "HIGH"
      output_strength = "HIGH"
    }
  }
  word_policy_config {
    words_config { text = "forbidden-word" }
  }
  tags = local.tags
}
resource "aws_bedrock_guardrail_version" "v1" {
  guardrail_arn = aws_bedrock_guardrail.app.guardrail_arn
  description   = "v1"
}

resource "aws_iam_role" "agent" {
  name = "AmazonBedrockExecutionRoleForAgents_${var.name}"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "bedrock.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
  tags = local.tags
}
resource "aws_bedrockagent_agent" "app" {
  agent_name                  = "${var.name}-agent"
  agent_resource_role_arn     = aws_iam_role.agent.arn
  foundation_model            = "vyomi.qwen2.5-3b"
  instruction                 = "You are the endurance reference assistant. Answer briefly and politely."
  idle_session_ttl_in_seconds = 600
  prepare_agent               = true
  tags                        = local.tags
}
resource "aws_bedrockagent_agent_alias" "live" {
  agent_alias_name = "live"
  agent_id         = aws_bedrockagent_agent.app.agent_id
  description      = "live alias"
  tags             = local.tags
}

resource "aws_bedrock_model_invocation_logging_configuration" "logs" {
  logging_config {
    embedding_data_delivery_enabled = true
    text_data_delivery_enabled      = true
    s3_config {
      bucket_name = var.log_bucket
      key_prefix  = "bedrock-logs"
    }
  }
}

output "guardrail_id" { value = aws_bedrock_guardrail.app.guardrail_id }
output "agent_id" { value = aws_bedrockagent_agent.app.agent_id }
