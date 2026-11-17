# Vyomi Reference Estate - AWS. One application, composed from stages. Every resource is mapped to capability ids in
# ../../coverage-map.json; `tests/endurance/run_estate.sh estate/aws <endpoint>` is the release check.
terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
    archive = { source = "hashicorp/archive" }
  }
}

variable "endpoint" { default = "http://host.docker.internal:9000" }

provider "aws" {
  region                  = "us-east-1"
  access_key              = "test"
  secret_key              = "test"
  skip_metadata_api_check = true
  s3_use_path_style       = true
  endpoints {
    ec2            = var.endpoint
    iam            = var.endpoint
    kms            = var.endpoint
    secretsmanager = var.endpoint
    sts            = var.endpoint
    logs           = var.endpoint
    s3             = var.endpoint
    rds            = var.endpoint
    dynamodb       = var.endpoint
    ecr            = var.endpoint
    sqs            = var.endpoint
    sns            = var.endpoint
    cloudwatchevents = var.endpoint
    eventbridge    = var.endpoint
    bedrock        = var.endpoint
    bedrockagent   = var.endpoint
    lambda         = var.endpoint
    apigateway     = var.endpoint
    apigatewayv2   = var.endpoint
    sfn            = var.endpoint
  }
}

module "network_identity" {
  source = "./modules/stage1-network-identity"
}

module "compute_data" {
  source                = "./modules/stage2-compute-data"
  vpc_id                = module.network_identity.vpc_id
  public_subnet_id      = module.network_identity.public_subnet_id
  private_subnet_ids    = module.network_identity.private_subnet_ids
  web_sg_id             = module.network_identity.web_sg_id
  db_sg_id              = module.network_identity.db_sg_id
  kms_key_arn           = module.network_identity.kms_key_arn
  instance_profile_name = module.network_identity.instance_profile_name
}

module "messaging" {
  source      = "./modules/stage3-messaging"
  kms_key_arn = module.network_identity.kms_key_arn
}

module "ai" {
  source      = "./modules/stage6-ai"
  kms_key_arn = module.network_identity.kms_key_arn
  log_bucket  = module.compute_data.bucket
}

module "serverless" {
  source            = "./modules/stage5-serverless"
  kms_key_arn       = module.network_identity.kms_key_arn
  orders_table_name = module.compute_data.orders_table_name
  orders_table_arn  = module.compute_data.orders_table_arn
  orders_queue_arn  = module.messaging.orders_queue_arn
  dlq_arn           = module.messaging.dlq_arn
  topic_arn         = module.messaging.topic_arn
  bus_name          = module.messaging.bus_name
}
