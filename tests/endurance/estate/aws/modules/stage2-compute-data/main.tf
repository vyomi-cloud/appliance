# Vyomi Reference Estate - AWS stage 2: compute, block storage, object storage, relational + NoSQL data, registry.
variable "name" { default = "endurance" }
variable "vpc_id" {}
variable "public_subnet_id" {}
variable "private_subnet_ids" { type = list(string) }
variable "web_sg_id" {}
variable "db_sg_id" {}
variable "kms_key_arn" {}
variable "instance_profile_name" {}

locals { tags = { Estate = "vyomi-endurance", Stage = "2-compute-data" } }

# ---------------------------------------------------------------- compute (ec2.*)
resource "aws_key_pair" "ops" {
  key_name   = "${var.name}-ops"
  public_key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl endurance@vyomi"
  tags       = local.tags
}
resource "aws_launch_template" "app" {
  name          = "${var.name}-app"
  image_id      = "ami-ubuntu2204"
  instance_type = "t3.micro"
  key_name      = aws_key_pair.ops.key_name
  vpc_security_group_ids = [var.web_sg_id]
  tag_specifications {
    resource_type = "instance"
    tags          = local.tags
  }
}
resource "aws_instance" "app" {
  ami                    = "ami-ubuntu2204"
  instance_type          = "t3.micro"
  subnet_id              = var.public_subnet_id
  vpc_security_group_ids = [var.web_sg_id]
  key_name               = aws_key_pair.ops.key_name
  iam_instance_profile   = var.instance_profile_name
  tags                   = merge(local.tags, { Name = "${var.name}-app" })
}
resource "aws_ebs_volume" "data" {
  availability_zone = "us-east-1a"
  size              = 8
  type              = "gp3"
  encrypted         = true
  tags              = local.tags
}
resource "aws_volume_attachment" "data" {
  device_name = "/dev/sdf"
  volume_id   = aws_ebs_volume.data.id
  instance_id = aws_instance.app.id
}
resource "aws_ebs_snapshot" "data" {
  volume_id   = aws_ebs_volume.data.id
  description = "endurance data snapshot"
  tags        = local.tags
  depends_on  = [aws_volume_attachment.data]
}

# ---------------------------------------------------------------- object storage (s3.bucket.*)
resource "aws_s3_bucket" "assets" {
  bucket        = "${var.name}-assets"
  force_destroy = true
  tags          = local.tags
}
resource "aws_s3_bucket_versioning" "assets" {
  bucket = aws_s3_bucket.assets.id
  versioning_configuration { status = "Enabled" }
}
resource "aws_s3_bucket_server_side_encryption_configuration" "assets" {
  bucket = aws_s3_bucket.assets.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = var.kms_key_arn
    }
  }
}
resource "aws_s3_bucket_public_access_block" "assets" {
  bucket                  = aws_s3_bucket.assets.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
resource "aws_s3_bucket_ownership_controls" "assets" {
  bucket = aws_s3_bucket.assets.id
  rule { object_ownership = "BucketOwnerEnforced" }
}
resource "aws_s3_bucket_lifecycle_configuration" "assets" {
  bucket = aws_s3_bucket.assets.id
  rule {
    id     = "expire-tmp"
    status = "Enabled"
    filter { prefix = "tmp/" }
    expiration { days = 7 }
    noncurrent_version_expiration { noncurrent_days = 30 }
  }
  depends_on = [aws_s3_bucket_versioning.assets]
}
resource "aws_s3_bucket_cors_configuration" "assets" {
  bucket = aws_s3_bucket.assets.id
  cors_rule {
    allowed_methods = ["GET"]
    allowed_origins = ["https://app.endurance.internal"]
    allowed_headers = ["*"]
    max_age_seconds = 3000
  }
}
resource "aws_s3_object" "readme" {
  bucket       = aws_s3_bucket.assets.id
  key          = "README.txt"
  content      = "vyomi-endurance reference estate"
  content_type = "text/plain"
}

# ---------------------------------------------------------------- relational (rds.*)
resource "aws_db_subnet_group" "main" {
  name       = "${var.name}-db"
  subnet_ids = var.private_subnet_ids
  tags       = local.tags
}
resource "aws_db_parameter_group" "pg" {
  name   = "${var.name}-pg16"
  family = "postgres16"
  parameter {
    name  = "log_min_duration_statement"
    value = "500"
  }
  tags = local.tags
}
resource "aws_db_instance" "main" {
  identifier              = "${var.name}-db"
  engine                  = "postgres"
  engine_version          = "16.3"
  instance_class          = "db.t3.micro"
  allocated_storage       = 20
  db_name                 = "orders"
  username                = "app"
  password                = "endurance-not-a-real-password"
  db_subnet_group_name    = aws_db_subnet_group.main.name
  vpc_security_group_ids  = [var.db_sg_id]
  parameter_group_name    = aws_db_parameter_group.pg.name
  storage_encrypted       = true
  kms_key_id              = var.kms_key_arn
  backup_retention_period = 1
  skip_final_snapshot     = true
  apply_immediately       = true
  tags                    = local.tags
}
resource "aws_db_snapshot" "main" {
  db_instance_identifier = aws_db_instance.main.identifier
  db_snapshot_identifier = "${var.name}-db-snap"
  tags                   = local.tags
}

# ---------------------------------------------------------------- NoSQL (dynamodb.*)
resource "aws_dynamodb_table" "orders" {
  name         = "${var.name}-orders"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "order_id"
  range_key    = "created_at"
  attribute {
    name = "order_id"
    type = "S"
  }
  attribute {
    name = "created_at"
    type = "N"
  }
  attribute {
    name = "customer_id"
    type = "S"
  }
  global_secondary_index {
    name            = "by-customer"
    hash_key        = "customer_id"
    range_key       = "created_at"
    projection_type = "ALL"
  }
  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }
  point_in_time_recovery { enabled = true }
  server_side_encryption { enabled = true }
  tags = local.tags
}

# ---------------------------------------------------------------- registry (ecr.*)
resource "aws_ecr_repository" "app" {
  name                 = "${var.name}/app"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = true
  image_scanning_configuration { scan_on_push = true }
  tags                 = local.tags
}
resource "aws_ecr_lifecycle_policy" "app" {
  repository = aws_ecr_repository.app.name
  policy = jsonencode({ rules = [{ rulePriority = 1, description = "keep 10", selection = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 10 }, action = { type = "expire" } }] })
}

output "instance_id" { value = aws_instance.app.id }
output "db_endpoint" { value = aws_db_instance.main.endpoint }
output "bucket" { value = aws_s3_bucket.assets.id }
output "table_name" { value = aws_dynamodb_table.orders.name }
output "table_arn" { value = aws_dynamodb_table.orders.arn }
output "db_identifier" { value = aws_db_instance.main.identifier }
output "db_arn" { value = aws_db_instance.main.arn }
