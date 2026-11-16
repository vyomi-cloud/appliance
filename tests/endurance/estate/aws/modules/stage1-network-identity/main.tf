# Vyomi Reference Estate - AWS stage 1: network + identity + keys + secrets.
# Every resource here maps to capability ids in ../../coverage-map.json (status planned until a green run proves it).
variable "name" { default = "endurance" }

locals { tags = { Estate = "vyomi-endurance", Stage = "1-network-identity" } }

# ---------------------------------------------------------------- network (aws.vpc.*, ec2.security-groups, ec2.elastic-ips)
resource "aws_vpc" "main" {
  cidr_block           = "10.60.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = merge(local.tags, { Name = "${var.name}-vpc" })
}
resource "aws_vpc_dhcp_options" "main" {
  domain_name         = "endurance.internal"
  domain_name_servers = ["AmazonProvidedDNS"]
  tags                = local.tags
}
resource "aws_vpc_dhcp_options_association" "main" {
  vpc_id          = aws_vpc.main.id
  dhcp_options_id = aws_vpc_dhcp_options.main.id
}
resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
  tags   = local.tags
}
resource "aws_subnet" "public" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = "10.60.1.0/24"
  availability_zone       = "us-east-1a"
  map_public_ip_on_launch = true
  tags                    = merge(local.tags, { Name = "${var.name}-public" })
}
resource "aws_subnet" "private" {
  vpc_id            = aws_vpc.main.id
  cidr_block        = "10.60.2.0/24"
  availability_zone = "us-east-1a"
  tags              = merge(local.tags, { Name = "${var.name}-private" })
}
resource "aws_subnet" "private_b" {
  vpc_id            = aws_vpc.main.id
  cidr_block        = "10.60.3.0/24"
  availability_zone = "us-east-1b"
  tags              = merge(local.tags, { Name = "${var.name}-private-b" })
}
resource "aws_eip" "nat" {
  domain = "vpc"
  tags   = local.tags
}
resource "aws_nat_gateway" "main" {
  allocation_id = aws_eip.nat.id
  subnet_id     = aws_subnet.public.id
  tags          = local.tags
  depends_on    = [aws_internet_gateway.main]
}
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id
  tags   = merge(local.tags, { Name = "${var.name}-public-rt" })
}
resource "aws_route" "public_default" {
  route_table_id         = aws_route_table.public.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.main.id
}
resource "aws_route_table_association" "public" {
  subnet_id      = aws_subnet.public.id
  route_table_id = aws_route_table.public.id
}
resource "aws_route_table" "private" {
  vpc_id = aws_vpc.main.id
  tags   = merge(local.tags, { Name = "${var.name}-private-rt" })
}
resource "aws_route" "private_default" {
  route_table_id         = aws_route_table.private.id
  destination_cidr_block = "0.0.0.0/0"
  nat_gateway_id         = aws_nat_gateway.main.id
}
resource "aws_route_table_association" "private" {
  subnet_id      = aws_subnet.private.id
  route_table_id = aws_route_table.private.id
}
resource "aws_route_table_association" "private_b" {
  subnet_id      = aws_subnet.private_b.id
  route_table_id = aws_route_table.private.id
}
resource "aws_security_group" "web" {
  name        = "${var.name}-web"
  description = "web tier"
  vpc_id      = aws_vpc.main.id
  tags        = local.tags
}
resource "aws_vpc_security_group_ingress_rule" "web_https" {
  security_group_id = aws_security_group.web.id
  cidr_ipv4         = "0.0.0.0/0"
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
}
resource "aws_vpc_security_group_egress_rule" "web_all" {
  security_group_id = aws_security_group.web.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
}
resource "aws_security_group" "db" {
  name        = "${var.name}-db"
  description = "db tier"
  vpc_id      = aws_vpc.main.id
  tags        = local.tags
}
resource "aws_vpc_security_group_ingress_rule" "db_from_web" {
  security_group_id            = aws_security_group.db.id
  referenced_security_group_id = aws_security_group.web.id
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
}
resource "aws_network_acl" "private" {
  vpc_id     = aws_vpc.main.id
  subnet_ids = [aws_subnet.private.id]
  tags       = local.tags
}
resource "aws_network_acl_rule" "private_in" {
  network_acl_id = aws_network_acl.private.id
  rule_number    = 100
  egress         = false
  protocol       = "tcp"
  rule_action    = "allow"
  cidr_block     = "10.60.0.0/16"
  from_port      = 1024
  to_port        = 65535
}
resource "aws_ec2_managed_prefix_list" "office" {
  name           = "${var.name}-office"
  address_family = "IPv4"
  max_entries    = 5
  entry {
    cidr        = "203.0.113.0/24"
    description = "office"
  }
  tags = local.tags
}

# ---------------------------------------------------------------- keys (kms.*)
resource "aws_kms_key" "data" {
  description             = "endurance data key"
  enable_key_rotation     = true
  deletion_window_in_days = 7
  tags                    = local.tags
}
resource "aws_kms_alias" "data" {
  name          = "alias/${var.name}-data"
  target_key_id = aws_kms_key.data.key_id
}

# ---------------------------------------------------------------- identity (iam.*)
data "aws_iam_policy_document" "assume_lambda" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}
resource "aws_iam_role" "app" {
  name               = "${var.name}-app"
  assume_role_policy = data.aws_iam_policy_document.assume_lambda.json
  tags               = local.tags
}
data "aws_iam_policy_document" "app_access" {
  statement {
    actions   = ["secretsmanager:GetSecretValue", "kms:Decrypt"]
    resources = ["*"]
  }
}
resource "aws_iam_policy" "app" {
  name   = "${var.name}-app-access"
  policy = data.aws_iam_policy_document.app_access.json
}
resource "aws_iam_role_policy_attachment" "app" {
  role       = aws_iam_role.app.name
  policy_arn = aws_iam_policy.app.arn
}
resource "aws_iam_instance_profile" "app" {
  name = "${var.name}-app"
  role = aws_iam_role.app.name
}
resource "aws_iam_user" "ops" {
  name = "${var.name}-ops"
  tags = local.tags
}
resource "aws_iam_group" "ops" { name = "${var.name}-ops" }
resource "aws_iam_group_membership" "ops" {
  name  = "${var.name}-ops"
  users = [aws_iam_user.ops.name]
  group = aws_iam_group.ops.name
}
resource "aws_iam_access_key" "ops" { user = aws_iam_user.ops.name }

# ---------------------------------------------------------------- secrets (secretsmanager.*)
resource "aws_secretsmanager_secret" "db" {
  name                    = "${var.name}/db-password"
  kms_key_id              = aws_kms_key.data.arn
  recovery_window_in_days = 0
  tags                    = local.tags
}
resource "aws_secretsmanager_secret_version" "db" {
  secret_id     = aws_secretsmanager_secret.db.id
  secret_string = jsonencode({ username = "app", password = "endurance-not-a-real-password" })
}

output "vpc_id" { value = aws_vpc.main.id }
output "public_subnet_id" { value = aws_subnet.public.id }
output "private_subnet_ids" { value = [aws_subnet.private.id, aws_subnet.private_b.id] }
output "web_sg_id" { value = aws_security_group.web.id }
output "db_sg_id" { value = aws_security_group.db.id }
output "kms_key_id" { value = aws_kms_key.data.key_id }
output "instance_profile_name" { value = aws_iam_instance_profile.app.name }
output "private_subnet_id" { value = aws_subnet.private.id }
output "kms_key_arn" { value = aws_kms_key.data.arn }
output "app_role_arn" { value = aws_iam_role.app.arn }
