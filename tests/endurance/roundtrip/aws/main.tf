# Round-trip reference app (AWS): a small web app on one Terraform template. VPC + subnets + IGW + routes + SGs, S3, IAM, Lambda behind an
# API Gateway stage, Secrets Manager, CloudWatch logs, RDS Postgres. Used by ../../run_roundtrip.sh (Terraform -> stack -> export -> fresh stack).
terraform {
  required_providers {
    aws     = { source = "hashicorp/aws", version = "~> 5.80" }
    archive = { source = "hashicorp/archive" }
  }
}
variable "endpoint" { default = "http://host.docker.internal:9000" }
provider "aws" {
  region                      = "us-east-1"
  access_key                  = "test"
  secret_key                  = "test"
  skip_credentials_validation = true
  skip_requesting_account_id  = true
  skip_metadata_api_check     = true
  s3_use_path_style           = true
  endpoints {
    s3 = var.endpoint
    ec2 = var.endpoint
    iam = var.endpoint
    sts = var.endpoint
    rds = var.endpoint
    apigateway = var.endpoint
    lambda = var.endpoint
    cloudwatchlogs = var.endpoint
    secretsmanager = var.endpoint
    kms = var.endpoint
    dynamodb = var.endpoint
  }
}

data "aws_availability_zones" "az" {}
data "archive_file" "fn" {
  type        = "zip"
  source_dir  = "${path.module}/app"
  output_path = "${path.module}/fn.zip"
}
resource "aws_vpc" "v" {
  cidr_block           = "10.42.0.0/16"
  enable_dns_hostnames = true
  enable_dns_support   = true
}
resource "aws_subnet" "pub" {
  count                   = 2
  vpc_id                  = aws_vpc.v.id
  cidr_block              = "10.42.${count.index}.0/24"
  availability_zone       = data.aws_availability_zones.az.names[count.index]
  map_public_ip_on_launch = true
}
resource "aws_subnet" "priv" {
  count             = 2
  vpc_id            = aws_vpc.v.id
  cidr_block        = "10.42.${count.index + 10}.0/24"
  availability_zone = data.aws_availability_zones.az.names[count.index]
}
resource "aws_internet_gateway" "igw" { vpc_id = aws_vpc.v.id }
resource "aws_route_table" "pub" {
  vpc_id = aws_vpc.v.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.igw.id
  }
}
resource "aws_route_table_association" "pub" {
  count          = 2
  subnet_id      = aws_subnet.pub[count.index].id
  route_table_id = aws_route_table.pub.id
}
resource "aws_security_group" "app" {
  name   = "tffull-app"
  vpc_id = aws_vpc.v.id
}
resource "aws_vpc_security_group_ingress_rule" "https" {
  security_group_id = aws_security_group.app.id
  cidr_ipv4         = "0.0.0.0/0"
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
}
resource "aws_security_group" "db" {
  name   = "tffull-db"
  vpc_id = aws_vpc.v.id
  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.app.id]
  }
}
resource "aws_s3_bucket" "b" { bucket = "tffull-assets-001" }
resource "aws_s3_bucket_versioning" "v" {
  bucket = aws_s3_bucket.b.id
  versioning_configuration { status = "Enabled" }
}
resource "aws_s3_bucket_public_access_block" "pab" {
  bucket                  = aws_s3_bucket.b.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
resource "aws_s3_object" "o" {
  bucket  = aws_s3_bucket.b.id
  key     = "hello.txt"
  content = "hi"
}
resource "aws_iam_role" "fn" {
  name = "tffull-fn"
  assume_role_policy = jsonencode({Version="2012-10-17",Statement=[{Effect="Allow",Principal={Service="lambda.amazonaws.com"},Action="sts:AssumeRole"}]})
}
resource "aws_iam_role_policy" "inline" {
  name   = "s3read"
  role   = aws_iam_role.fn.id
  policy = jsonencode({Version="2012-10-17",Statement=[{Effect="Allow",Action=["s3:GetObject"],Resource="${aws_s3_bucket.b.arn}/*"}]})
}
resource "aws_iam_role_policy_attachment" "basic" {
  role       = aws_iam_role.fn.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}
resource "aws_cloudwatch_log_group" "lg" {
  name              = "/aws/lambda/tffull-fn"
  retention_in_days = 7
}
resource "aws_secretsmanager_secret" "db" { name = "tffull-db-password" }
resource "aws_secretsmanager_secret_version" "db" {
  secret_id     = aws_secretsmanager_secret.db.id
  secret_string = "ChangeMe12345"
}
resource "aws_db_subnet_group" "g" {
  name       = "tffull-dbsg"
  subnet_ids = aws_subnet.priv[*].id
}
resource "aws_db_instance" "db" {
  identifier             = "tffull-db"
  engine                 = "postgres"
  instance_class         = "db.t3.micro"
  allocated_storage      = 20
  username               = "app"
  password               = "ChangeMe12345"
  skip_final_snapshot    = true
  db_subnet_group_name   = aws_db_subnet_group.g.name
  vpc_security_group_ids = [aws_security_group.db.id]
}
resource "aws_lambda_function" "fn" {
  function_name    = "tffull-fn"
  role             = aws_iam_role.fn.arn
  runtime          = "python3.12"
  handler          = "handler.handler"
  filename         = data.archive_file.fn.output_path
  source_code_hash = data.archive_file.fn.output_base64sha256
  environment { variables = { BUCKET = aws_s3_bucket.b.id } }
  depends_on = [aws_cloudwatch_log_group.lg]
}
resource "aws_api_gateway_rest_api" "api" { name = "tffull-api" }
resource "aws_api_gateway_resource" "items" {
  rest_api_id = aws_api_gateway_rest_api.api.id
  parent_id   = aws_api_gateway_rest_api.api.root_resource_id
  path_part   = "items"
}
resource "aws_api_gateway_method" "get" {
  rest_api_id   = aws_api_gateway_rest_api.api.id
  resource_id   = aws_api_gateway_resource.items.id
  http_method   = "GET"
  authorization = "NONE"
}
resource "aws_api_gateway_integration" "int" {
  rest_api_id             = aws_api_gateway_rest_api.api.id
  resource_id             = aws_api_gateway_resource.items.id
  http_method             = aws_api_gateway_method.get.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.fn.invoke_arn
}
resource "aws_lambda_permission" "apigw" {
  statement_id  = "AllowAPIGW"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.fn.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.api.execution_arn}/*/*"
}
resource "aws_api_gateway_deployment" "dep" {
  rest_api_id = aws_api_gateway_rest_api.api.id
  triggers    = { redeploy = sha1(jsonencode([aws_api_gateway_integration.int.id])) }
  lifecycle { create_before_destroy = true }
}
resource "aws_api_gateway_stage" "prod" {
  rest_api_id   = aws_api_gateway_rest_api.api.id
  deployment_id = aws_api_gateway_deployment.dep.id
  stage_name    = "prod"
}
