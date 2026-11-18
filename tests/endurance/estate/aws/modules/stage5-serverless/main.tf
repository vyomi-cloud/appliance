# Stage 5 - serverless API tier: lambda.*, apigateway.* (REST + HTTP), aws.states.*
terraform {
  required_providers {
    aws     = { source = "hashicorp/aws" }
    archive = { source = "hashicorp/archive" }
  }
}
variable "name" { default = "endurance" }
variable "kms_key_arn" {}
variable "orders_table_name" {}
variable "orders_table_arn" {}
variable "orders_queue_arn" {}
variable "dlq_arn" {}
variable "topic_arn" {}
variable "bus_name" {}
locals { tags = { Estate = "vyomi-endurance", Stage = "5-serverless-api" } }

# ---- execution role (iam.role.* is stage 1; this role is the function's identity)
resource "aws_iam_role" "fn" {
  name = "${var.name}-lambda-exec"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "lambda.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
  tags = local.tags
}
resource "aws_iam_role_policy_attachment" "basic" {
  role       = aws_iam_role.fn.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}
resource "aws_iam_role_policy" "data" {
  name = "orders-data-access"
  role = aws_iam_role.fn.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:Query"], Resource = [var.orders_table_arn, "${var.orders_table_arn}/index/*"] },
      { Effect = "Allow", Action = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes", "sqs:SendMessage"], Resource = [var.orders_queue_arn, var.dlq_arn] },
      { Effect = "Allow", Action = ["sns:Publish"], Resource = var.topic_arn },
    ]
  })
}
resource "aws_iam_role" "sfn" {
  name = "${var.name}-sfn-exec"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "states.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
  tags = local.tags
}

# ---- packaging
data "archive_file" "orders" {
  type        = "zip"
  source_file = "${path.module}/src/orders.py"
  output_path = "${path.module}/build/orders.zip"
}
data "archive_file" "processor" {
  type        = "zip"
  source_file = "${path.module}/src/processor.py"
  output_path = "${path.module}/build/processor.zip"
}
data "archive_file" "layer" {
  type        = "zip"
  source_dir  = "${path.module}/layer"
  output_path = "${path.module}/build/layer.zip"
}

# ---- lambda.layers
resource "aws_lambda_layer_version" "common" {
  layer_name          = "${var.name}-common"
  description         = "shared helpers"
  filename            = data.archive_file.layer.output_path
  source_code_hash    = data.archive_file.layer.output_base64sha256
  compatible_runtimes = ["python3.12"]
}

# ---- lambda.function.crud / tags / concurrency / aliases-versions
resource "aws_cloudwatch_log_group" "orders" {
  name              = "/aws/lambda/${var.name}-orders-api"
  retention_in_days = 14
  tags              = local.tags
}
resource "aws_lambda_function" "orders" {
  function_name    = "${var.name}-orders-api"
  description      = "Orders REST/HTTP backend"
  role             = aws_iam_role.fn.arn
  runtime          = "python3.12"
  handler          = "orders.handler"
  filename         = data.archive_file.orders.output_path
  source_code_hash = data.archive_file.orders.output_base64sha256
  memory_size      = 256
  timeout          = 15
  publish          = true
  layers           = [aws_lambda_layer_version.common.arn]
  kms_key_arn      = var.kms_key_arn
  architectures    = ["x86_64"]
  environment { variables = { TABLE_NAME = var.orders_table_name, LOG_LEVEL = "INFO" } }
  tracing_config { mode = "Active" }
  dead_letter_config { target_arn = var.dlq_arn }
  tags       = local.tags
  depends_on = [aws_cloudwatch_log_group.orders, aws_iam_role_policy.data]
}
resource "aws_lambda_alias" "live" {
  name             = "live"
  description      = "production traffic"
  function_name    = aws_lambda_function.orders.function_name
  function_version = aws_lambda_function.orders.version
}
resource "aws_lambda_function_event_invoke_config" "orders" {
  function_name                = aws_lambda_function.orders.function_name
  maximum_retry_attempts       = 1
  maximum_event_age_in_seconds = 3600
}
resource "aws_lambda_function_url" "orders" {
  function_name      = aws_lambda_function.orders.function_name
  qualifier          = aws_lambda_alias.live.name
  authorization_type = "NONE"
  cors {
    allow_origins = ["https://example.com"]
    allow_methods = ["GET", "POST"]
  }
}
resource "aws_lambda_permission" "url_public" {
  statement_id           = "AllowPublicUrl"
  action                 = "lambda:InvokeFunctionUrl"
  function_name          = aws_lambda_function.orders.function_name
  qualifier              = aws_lambda_alias.live.name
  principal              = "*"
  function_url_auth_type = "NONE"
}

resource "aws_lambda_function" "processor" {
  function_name                  = "${var.name}-order-processor"
  role                           = aws_iam_role.fn.arn
  runtime                        = "python3.12"
  handler                        = "processor.handler"
  filename                       = data.archive_file.processor.output_path
  source_code_hash               = data.archive_file.processor.output_base64sha256
  reserved_concurrent_executions = 5
  timeout                        = 30
  tags                           = local.tags
  depends_on                     = [aws_iam_role_policy.data]
}
# ---- lambda.triggers (event source mapping)
resource "aws_lambda_event_source_mapping" "orders_queue" {
  event_source_arn                   = var.orders_queue_arn
  function_name                      = aws_lambda_function.processor.arn
  batch_size                         = 5
  maximum_batching_window_in_seconds = 2
}

# ---- EventBridge rule -> Lambda
resource "aws_cloudwatch_event_rule" "audit" {
  name           = "${var.name}-order-audit"
  event_bus_name = var.bus_name
  event_pattern  = jsonencode({ source = ["endurance.orders"], "detail-type" = ["OrderShipped"] })
  tags           = local.tags
}
resource "aws_cloudwatch_event_target" "audit" {
  rule           = aws_cloudwatch_event_rule.audit.name
  event_bus_name = var.bus_name
  target_id      = "processor"
  arn            = aws_lambda_function.processor.arn
}
resource "aws_lambda_permission" "events" {
  statement_id  = "AllowEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.processor.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.audit.arn
}

# ---- apigateway.rest.* + usageplans + apikeys
resource "aws_api_gateway_rest_api" "orders" {
  name        = "${var.name}-orders-rest"
  description = "Orders REST API"
  endpoint_configuration { types = ["REGIONAL"] }
  tags = local.tags
}
resource "aws_api_gateway_resource" "orders" {
  rest_api_id = aws_api_gateway_rest_api.orders.id
  parent_id   = aws_api_gateway_rest_api.orders.root_resource_id
  path_part   = "orders"
}
resource "aws_api_gateway_method" "get" {
  rest_api_id      = aws_api_gateway_rest_api.orders.id
  resource_id      = aws_api_gateway_resource.orders.id
  http_method      = "GET"
  authorization    = "NONE"
  api_key_required = true
}
resource "aws_api_gateway_integration" "get" {
  rest_api_id             = aws_api_gateway_rest_api.orders.id
  resource_id             = aws_api_gateway_resource.orders.id
  http_method             = aws_api_gateway_method.get.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.orders.invoke_arn
}
resource "aws_lambda_permission" "rest" {
  statement_id  = "AllowRestInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.orders.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.orders.execution_arn}/*/*"
}
resource "aws_api_gateway_deployment" "orders" {
  rest_api_id = aws_api_gateway_rest_api.orders.id
  triggers    = { redeploy = sha1(jsonencode([aws_api_gateway_method.get.id, aws_api_gateway_integration.get.id])) }
  lifecycle { create_before_destroy = true }
}
resource "aws_api_gateway_stage" "prod" {
  rest_api_id   = aws_api_gateway_rest_api.orders.id
  deployment_id = aws_api_gateway_deployment.orders.id
  stage_name    = "prod"
  variables     = { lambdaAlias = "live" }
  tags          = local.tags
}
resource "aws_api_gateway_api_key" "partner" {
  name = "${var.name}-partner"
  tags = local.tags
}
resource "aws_api_gateway_usage_plan" "partner" {
  name = "${var.name}-partner-plan"
  api_stages {
    api_id = aws_api_gateway_rest_api.orders.id
    stage  = aws_api_gateway_stage.prod.stage_name
  }
  throttle_settings {
    burst_limit = 50
    rate_limit  = 25
  }
  quota_settings {
    limit  = 10000
    period = "MONTH"
  }
  tags = local.tags
}
resource "aws_api_gateway_usage_plan_key" "partner" {
  key_id        = aws_api_gateway_api_key.partner.id
  key_type      = "API_KEY"
  usage_plan_id = aws_api_gateway_usage_plan.partner.id
}

# ---- apigateway.http.api (v2)
resource "aws_apigatewayv2_api" "http" {
  name          = "${var.name}-orders-http"
  protocol_type = "HTTP"
  cors_configuration {
    allow_origins = ["https://example.com"]
    allow_methods = ["GET", "POST"]
  }
  tags = local.tags
}
resource "aws_apigatewayv2_integration" "http" {
  api_id                 = aws_apigatewayv2_api.http.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.orders.invoke_arn
  payload_format_version = "2.0"
}
resource "aws_apigatewayv2_authorizer" "jwt" {
  api_id           = aws_apigatewayv2_api.http.id
  authorizer_type  = "JWT"
  name             = "${var.name}-jwt"
  identity_sources = ["$request.header.Authorization"]
  jwt_configuration {
    audience = ["orders"]
    issuer   = "https://issuer.example.com/"
  }
}
resource "aws_apigatewayv2_route" "get" {
  api_id             = aws_apigatewayv2_api.http.id
  route_key          = "GET /orders"
  target             = "integrations/${aws_apigatewayv2_integration.http.id}"
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.jwt.id
}
resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.http.id
  name        = "$default"
  auto_deploy = true
  tags        = local.tags
}
resource "aws_lambda_permission" "http" {
  statement_id  = "AllowHttpInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.orders.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.http.execution_arn}/*/*"
}

# ---- aws.states.* (workflow: validate -> process -> notify)
resource "aws_cloudwatch_log_group" "sfn" {
  name              = "/aws/vendedlogs/states/${var.name}-order-flow"
  retention_in_days = 7
  tags              = local.tags
}
resource "aws_sfn_state_machine" "flow" {
  name     = "${var.name}-order-flow"
  role_arn = aws_iam_role.sfn.arn
  type     = "STANDARD"
  definition = jsonencode({
    Comment = "order fulfilment"
    StartAt = "Process"
    States = {
      Process = { Type = "Task", Resource = aws_lambda_function.processor.arn, Next = "Done" }
      Done    = { Type = "Succeed" }
    }
  })
  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.sfn.arn}:*"
    include_execution_data = true
    level                  = "ERROR"
  }
  tracing_configuration { enabled = true }
  tags = local.tags
}

output "orders_function" { value = aws_lambda_function.orders.function_name }
output "rest_api_id" { value = aws_api_gateway_rest_api.orders.id }
output "http_api_id" { value = aws_apigatewayv2_api.http.id }
output "state_machine_arn" { value = aws_sfn_state_machine.flow.arn }
