terraform {
  required_providers { aws = { source = "hashicorp/aws", version = "~> 5.0" } }
}
variable "endpoint" { default = "http://host.docker.internal:18741" }
provider "aws" {
  region                      = "us-east-1"
  access_key                  = "test"
  secret_key                  = "test"
  skip_credentials_validation = true
  skip_requesting_account_id  = true
  skip_metadata_api_check     = true
  s3_use_path_style           = true
  endpoints {
    ec2 = var.endpoint
    s3  = var.endpoint
    sqs = var.endpoint
    sts = var.endpoint
  }
}
resource "aws_vpc" "endurance" {
  cidr_block = "10.50.0.0/16"
  tags       = { Name = "vpc-endurance" }
}
resource "aws_subnet" "endurance" {
  vpc_id     = aws_vpc.endurance.id
  cidr_block = "10.50.1.0/24"
}
resource "aws_s3_bucket" "endurance" { bucket = "endurance-spike-bucket" }
resource "aws_sqs_queue" "endurance" { name = "endurance-spike-queue" }
