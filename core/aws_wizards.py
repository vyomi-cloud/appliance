"""AWS-Management-Console-style multi-step Create wizards.

Mirrors :mod:`core.azure_wizards` shape so the same SPA renderer can drive
both providers. Each entry under WIZARDS is keyed by the AWS catalog ``key``
(ec2, s3, iam, rds, dynamodb, sqs, lambda, apigateway, vpc).

The frontend (``static/aws-console.html``) renders the wizard when
``svc.wizard`` is present. Submission produces an AWS-flavored body
(see ``core/aws_catalog.py::RESOURCE_CATALOG_AWS`` for the submit URLs).

Field shape — identical to Azure's; reuse types: text, select, number,
password, boolean, radio, vmSize, cidr, tagsEditor, info, help.

Synthetic fields (prefix ``__``) are UI-only; ``synthetic_map`` translates
chosen values to real body paths just like Azure's wizard.
"""
from __future__ import annotations


# ---------- shared helpers (same shape as core/azure_wizards) ----------

def _name(label: str, default: str, regex: str = r"^[a-z][a-z0-9-]{2,62}$",
          msg: str = "3-63 chars, lowercase letters/digits/hyphens, start with a letter") -> dict:
    return {"name": "name", "label": label, "default": default, "required": True,
            "validate": {"regex": regex, "message": msg}}


def _region() -> dict:
    return {"name": "__region__", "label": "Region", "type": "select", "required": True,
            "default": "us-east-1", "options": [
                {"value": "us-east-1", "label": "US East (N. Virginia) — us-east-1"},
                {"value": "us-east-2", "label": "US East (Ohio) — us-east-2"},
                {"value": "us-west-1", "label": "US West (N. California) — us-west-1"},
                {"value": "us-west-2", "label": "US West (Oregon) — us-west-2"},
                {"value": "eu-west-1", "label": "Europe (Ireland) — eu-west-1"},
                {"value": "eu-central-1","label": "Europe (Frankfurt) — eu-central-1"},
                {"value": "ap-southeast-1","label": "Asia Pacific (Singapore) — ap-southeast-1"},
                {"value": "ap-northeast-1","label": "Asia Pacific (Tokyo) — ap-northeast-1"},
            ]}


def _account_section() -> dict:
    return {"label": "Account details", "fields": [
        {"name": "__account__", "label": "AWS account", "type": "info",
         "help": "Active AWS account (set by the active simulator space)."},
        _region(),
    ]}


def _tags_tab() -> dict:
    return {"key": "tags", "label": "Tags", "sections": [
        {"label": "Tags", "fields": [
            {"name": "__help__", "type": "help",
             "value": "Tags are key-value pairs that help organize, search, and apply policies to your AWS resources."},
            {"name": "tags", "type": "tagsEditor", "default": {}},
        ]},
    ]}


def _review_tab() -> dict:
    return {"key": "review", "label": "Review and create", "auto": True,
            "sections": [{"label": "Summary", "fields": []}]}


# ===========================================================================
# EC2 — Launch instance (mirrors AWS console "Launch instance" multi-section)
# ===========================================================================
_EC2_WIZARD = {
    "tabs": [
        {"key": "basics", "label": "Name and tags", "sections": [
            _account_section(),
            {"label": "Name and tags", "fields": [
                _name("Instance name", "my-ec2-instance",
                      r"^[\w][\w .:/=+-@]{0,254}$",
                      "1-255 chars; letters, digits, spaces, and . : / = + - @"),
            ]},
        ]},
        {"key": "ami", "label": "Application and OS Image (AMI)", "sections": [
            {"label": "Quick Start", "fields": [
                {"name": "__os__", "label": "Operating system", "type": "radio",
                 "default": "amzn2023", "options": [
                    {"value": "amzn2023", "label": "Amazon Linux 2023 (HVM, SSD)"},
                    {"value": "amzn2",    "label": "Amazon Linux 2 (HVM, SSD)"},
                    {"value": "ubuntu24", "label": "Ubuntu Server 24.04 LTS"},
                    {"value": "ubuntu22", "label": "Ubuntu Server 22.04 LTS"},
                    {"value": "rhel9",    "label": "Red Hat Enterprise Linux 9"},
                    {"value": "windows2022","label": "Windows Server 2022"},
                 ]},
                {"name": "architecture", "label": "Architecture", "type": "select",
                 "default": "x86_64", "options": [
                    {"value": "x86_64", "label": "64-bit (x86)"},
                    {"value": "arm64",  "label": "64-bit (Arm)"},
                 ]},
            ]},
        ]},
        {"key": "instance", "label": "Instance type", "sections": [
            {"label": "Instance type", "fields": [
                {"name": "instance_type", "label": "Instance type", "type": "vmSize",
                 "default": "t3.micro", "required": True,
                 "help": "Instance type from the simulator's AWS catalog — host-clamped on launch."},
            ]},
        ]},
        {"key": "keypair", "label": "Key pair (login)", "sections": [
            {"label": "Key pair", "fields": [
                {"name": "key_name", "label": "Key pair name", "default": "",
                 "help": "Leave blank to proceed without a key pair (simulator generates SSH access via lxc exec)."},
                {"name": "__keyAck__", "label": "Proceed without a key pair", "type": "boolean", "default": True,
                 "help": "Required if Key pair name is blank — confirms you understand SSH/RDP login won't be available."},
            ]},
        ]},
        {"key": "network", "label": "Network settings", "sections": [
            {"label": "Network", "fields": [
                {"name": "__vpc__", "label": "VPC", "type": "text", "default": "default",
                 "help": "VPC ID; default VPC is auto-created in the simulator."},
                {"name": "__subnet__", "label": "Subnet", "type": "text", "default": "(no preference)"},
                {"name": "__autoIp__", "label": "Auto-assign public IP", "type": "select",
                 "default": "use_subnet_setting", "options": [
                    {"value": "enable",  "label": "Enable"},
                    {"value": "disable", "label": "Disable"},
                    {"value": "use_subnet_setting", "label": "Use subnet setting (Enable)"},
                 ]},
            ]},
            {"label": "Firewall (security groups)", "fields": [
                {"name": "__sgChoice__", "label": "Firewall", "type": "radio",
                 "default": "create", "options": [
                    {"value": "create", "label": "Create security group"},
                    {"value": "select", "label": "Select existing security group"},
                 ]},
                {"name": "__sgName__", "label": "Security group name", "default": "launch-wizard-1",
                 "ifEquals": {"__sgChoice__": "create"}},
                {"name": "__sgDesc__", "label": "Description", "default": "launch-wizard-1 created 2026-05-28",
                 "ifEquals": {"__sgChoice__": "create"}},
                {"name": "__allowSsh__", "label": "Allow SSH traffic from", "type": "select",
                 "default": "0.0.0.0/0", "ifEquals": {"__sgChoice__": "create"}, "options": [
                    {"value": "0.0.0.0/0", "label": "Anywhere"},
                    {"value": "10.0.0.0/16", "label": "Within VPC"},
                 ]},
                {"name": "__allowHttp__", "label": "Allow HTTPS traffic from the internet",
                 "type": "boolean", "default": False, "ifEquals": {"__sgChoice__": "create"}},
                {"name": "__allowHttpsBasic__", "label": "Allow HTTP traffic from the internet",
                 "type": "boolean", "default": False, "ifEquals": {"__sgChoice__": "create"}},
            ]},
        ]},
        {"key": "storage", "label": "Configure storage", "sections": [
            {"label": "Root volume", "fields": [
                {"name": "__rootSize__", "label": "Size (GiB)", "type": "number", "default": 8,
                 "validate": {"min": 1, "max": 16384}},
                {"name": "__rootType__", "label": "Volume type", "type": "select",
                 "default": "gp3", "options": [
                    {"value": "gp3",     "label": "General Purpose SSD (gp3) — recommended"},
                    {"value": "gp2",     "label": "General Purpose SSD (gp2)"},
                    {"value": "io1",     "label": "Provisioned IOPS SSD (io1)"},
                    {"value": "standard","label": "Magnetic (standard)"},
                 ]},
                {"name": "__rootEncrypt__", "label": "Encrypted", "type": "boolean", "default": True},
            ]},
        ]},
        {"key": "advanced", "label": "Advanced details", "sections": [
            {"label": "IAM instance profile", "fields": [
                {"name": "iam_instance_profile", "label": "IAM instance profile", "default": "",
                 "help": "ARN or name of an IAM role to attach to this instance."},
            ]},
            {"label": "Detailed monitoring", "fields": [
                {"name": "__detailedMon__", "label": "Enable detailed monitoring",
                 "type": "boolean", "default": False,
                 "help": "Sends metric data every 1 minute instead of 5 minutes (extra cost in real AWS)."},
            ]},
            {"label": "User data", "fields": [
                {"name": "user_data", "label": "User data (cloud-init script)", "type": "text", "default": "",
                 "help": "Base-64 encoded shell script that runs on first boot."},
            ]},
        ]},
        _tags_tab(),
        _review_tab(),
    ],
    "synthetic_map": {
        "__os__": {
            "amzn2023":   {"image_id": "ami-amzn2023-x86_64"},
            "amzn2":      {"image_id": "ami-amzn2-x86_64"},
            "ubuntu24":   {"image_id": "ami-ubuntu-24.04-x86_64"},
            "ubuntu22":   {"image_id": "ami-ubuntu-22.04-x86_64"},
            "rhel9":      {"image_id": "ami-rhel-9-x86_64"},
            "windows2022":{"image_id": "ami-windows-2022-x86_64"},
        },
    },
}


# ===========================================================================
# S3 — Create bucket
# ===========================================================================
_S3_WIZARD = {
    "tabs": [
        {"key": "basics", "label": "General configuration", "sections": [
            _account_section(),
            {"label": "General configuration", "fields": [
                _name("Bucket name", "my-bucket-cloudlearn",
                      r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$",
                      "3-63 chars, lowercase, digits, hyphens, periods; globally unique"),
                {"name": "__copySettings__", "label": "Copy settings from existing bucket",
                 "default": "", "help": "Optional — bucket name to clone settings from."},
            ]},
        ]},
        {"key": "objectownership", "label": "Object Ownership", "sections": [
            {"label": "Object Ownership", "fields": [
                {"name": "__ownership__", "label": "Object Ownership", "type": "radio",
                 "default": "BucketOwnerEnforced", "options": [
                    {"value": "BucketOwnerEnforced", "label": "ACLs disabled (recommended)"},
                    {"value": "BucketOwnerPreferred","label": "ACLs enabled — Bucket owner preferred"},
                    {"value": "ObjectWriter",        "label": "ACLs enabled — Object writer"},
                 ]},
            ]},
        ]},
        {"key": "publicaccess", "label": "Block Public Access", "sections": [
            {"label": "Block Public Access settings for this bucket", "fields": [
                {"name": "__blockAll__", "label": "Block all public access",
                 "type": "boolean", "default": True,
                 "help": "Strongly recommended — turning off requires explicit acknowledgement."},
                {"name": "__ack__", "label": "I acknowledge that the current settings might result in this bucket becoming public.",
                 "type": "boolean", "default": False, "ifEquals": {"__blockAll__": False}},
            ]},
        ]},
        {"key": "versioning", "label": "Versioning and encryption", "sections": [
            {"label": "Bucket Versioning", "fields": [
                {"name": "versioning_enabled", "label": "Bucket Versioning", "type": "radio",
                 "default": False, "options": [
                    {"value": False, "label": "Disable"},
                    {"value": True,  "label": "Enable"},
                 ]},
            ]},
            {"label": "Default encryption", "fields": [
                {"name": "__encryption__", "label": "Encryption type", "type": "radio",
                 "default": "SSE-S3", "options": [
                    {"value": "SSE-S3",  "label": "Server-side encryption with Amazon S3 managed keys (SSE-S3)"},
                    {"value": "SSE-KMS", "label": "Server-side encryption with AWS Key Management Service keys (SSE-KMS)"},
                    {"value": "DSSE-KMS","label": "Dual-layer server-side encryption with AWS KMS keys (DSSE-KMS)"},
                 ]},
                {"name": "__bucketKey__", "label": "Bucket Key", "type": "radio",
                 "default": "Enable", "ifEquals": {"__encryption__": "SSE-KMS"}, "options": [
                    {"value": "Enable",  "label": "Enable — reduces KMS costs"},
                    {"value": "Disable", "label": "Disable"},
                 ]},
            ]},
        ]},
        _tags_tab(),
        _review_tab(),
    ],
    "synthetic_map": {},
}


# ===========================================================================
# IAM — Create user (the most common IAM create flow). Users/groups/roles/
# policies all have their own create wizards in real AWS but unifying here.
# ===========================================================================
_IAM_WIZARD = {
    "tabs": [
        {"key": "basics", "label": "Specify user details", "sections": [
            _account_section(),
            {"label": "User details", "fields": [
                _name("User name", "new-user",
                      r"^[\w+=,.@-]{1,64}$",
                      "1-64 chars; letters, digits, +=,.@_-"),
                {"name": "__consoleAccess__", "label": "Provide user access to the AWS Management Console",
                 "type": "boolean", "default": False,
                 "help": "If enabled, this user can sign in to the console with a password."},
                {"name": "__pwdReset__", "label": "Users must create a new password at next sign-in",
                 "type": "boolean", "default": True, "ifEquals": {"__consoleAccess__": True}},
            ]},
        ]},
        {"key": "permissions", "label": "Set permissions", "sections": [
            {"label": "Permissions options", "fields": [
                {"name": "__permsMethod__", "label": "How to grant permissions", "type": "radio",
                 "default": "addToGroup", "options": [
                    {"value": "addToGroup",  "label": "Add user to group"},
                    {"value": "copyFrom",    "label": "Copy permissions from existing user"},
                    {"value": "attachPolicy","label": "Attach policies directly"},
                 ]},
                {"name": "__group__", "label": "User groups", "default": "Administrators",
                 "ifEquals": {"__permsMethod__": "addToGroup"}},
                {"name": "__copyFromUser__", "label": "Existing user", "default": "",
                 "ifEquals": {"__permsMethod__": "copyFrom"}},
                {"name": "__attachedPolicy__", "label": "Managed policy ARN", "default": "arn:aws:iam::aws:policy/ReadOnlyAccess",
                 "ifEquals": {"__permsMethod__": "attachPolicy"}},
            ]},
            {"label": "Permissions boundary", "fields": [
                {"name": "permissions_boundary", "label": "Permissions boundary", "default": "",
                 "help": "Optional — ARN of a managed policy to set the maximum permissions for this user."},
            ]},
        ]},
        _tags_tab(),
        _review_tab(),
    ],
    "synthetic_map": {},
}


# ===========================================================================
# RDS — Create database
# ===========================================================================
_RDS_WIZARD = {
    "tabs": [
        {"key": "basics", "label": "Engine options", "sections": [
            _account_section(),
            {"label": "Engine options", "fields": [
                {"name": "engine", "label": "Engine type", "type": "radio",
                 "default": "postgres", "options": [
                    {"value": "postgres", "label": "PostgreSQL"},
                    {"value": "mysql",    "label": "MySQL"},
                    {"value": "mariadb",  "label": "MariaDB"},
                    {"value": "aurora-postgresql","label": "Amazon Aurora (PostgreSQL-compatible)"},
                    {"value": "aurora-mysql","label": "Amazon Aurora (MySQL-compatible)"},
                 ]},
                {"name": "engine_version", "label": "Version", "type": "select",
                 "default": "16.4", "options": [
                    {"value": "16.4",  "label": "PostgreSQL 16.4 (latest)"},
                    {"value": "15.8",  "label": "PostgreSQL 15.8"},
                    {"value": "14.13", "label": "PostgreSQL 14.13"},
                    {"value": "8.0.39","label": "MySQL 8.0.39"},
                ]},
            ]},
        ]},
        {"key": "template", "label": "Templates", "sections": [
            {"label": "Templates", "fields": [
                {"name": "__template__", "label": "Use case", "type": "radio",
                 "default": "dev", "options": [
                    {"value": "production","label": "Production — defaults for HA + fast performance"},
                    {"value": "dev",       "label": "Dev/Test — defaults for development"},
                    {"value": "free",      "label": "Free tier — db.t3.micro, single AZ, no backups"},
                 ]},
            ]},
        ]},
        {"key": "settings", "label": "Settings", "sections": [
            {"label": "DB instance identifier", "fields": [
                _name("DB instance identifier", "database-1",
                      r"^[a-z][a-z0-9-]{0,62}$",
                      "1-63 chars, lowercase, must begin with a letter, hyphens but not consecutive"),
            ]},
            {"label": "Credentials settings", "fields": [
                {"name": "master_username", "label": "Master username", "default": "postgres", "required": True,
                 "validate": {"regex": r"^[A-Za-z][A-Za-z0-9]{0,15}$",
                              "message": "1-16 chars, letters/digits, start with a letter"}},
                {"name": "__credsMgmt__", "label": "Credentials management", "type": "radio",
                 "default": "selfManaged", "options": [
                    {"value": "selfManaged","label": "Self managed"},
                    {"value": "secretsManager","label": "Managed in AWS Secrets Manager"},
                 ]},
                {"name": "master_password", "label": "Master password", "type": "password",
                 "ifEquals": {"__credsMgmt__": "selfManaged"},
                 "validate": {"regex": r"^[ -~]{8,128}$",
                              "message": "8-128 printable ASCII characters"}},
            ]},
        ]},
        {"key": "instance", "label": "Instance configuration", "sections": [
            {"label": "DB instance class", "fields": [
                {"name": "instance_class", "label": "DB instance class", "type": "select",
                 "default": "db.t3.micro", "options": [
                    {"value": "db.t3.micro",  "label": "db.t3.micro — 2 vCPU, 1 GiB"},
                    {"value": "db.t3.small",  "label": "db.t3.small — 2 vCPU, 2 GiB"},
                    {"value": "db.t3.medium", "label": "db.t3.medium — 2 vCPU, 4 GiB"},
                    {"value": "db.r5.large",  "label": "db.r5.large — 2 vCPU, 16 GiB"},
                    {"value": "db.r5.xlarge", "label": "db.r5.xlarge — 4 vCPU, 32 GiB"},
                    {"value": "db.r6g.large", "label": "db.r6g.large — 2 vCPU, 16 GiB (Graviton)"},
                 ]},
            ]},
        ]},
        {"key": "storage", "label": "Storage", "sections": [
            {"label": "Storage configuration", "fields": [
                {"name": "__storageType__", "label": "Storage type", "type": "select",
                 "default": "gp3", "options": [
                    {"value": "gp3",      "label": "General Purpose SSD (gp3)"},
                    {"value": "gp2",      "label": "General Purpose SSD (gp2)"},
                    {"value": "io1",      "label": "Provisioned IOPS SSD (io1)"},
                    {"value": "standard", "label": "Magnetic"},
                 ]},
                {"name": "allocated_storage", "label": "Allocated storage (GiB)", "type": "number",
                 "default": 20, "validate": {"min": 20, "max": 65536}},
                {"name": "__autoscaling__", "label": "Enable storage autoscaling",
                 "type": "boolean", "default": True},
            ]},
        ]},
        {"key": "connectivity", "label": "Connectivity", "sections": [
            {"label": "VPC", "fields": [
                {"name": "__vpc__", "label": "VPC", "type": "text", "default": "default"},
                {"name": "__subnetGroup__", "label": "DB subnet group", "type": "text", "default": "default"},
                {"name": "publicly_accessible", "label": "Public access", "type": "radio",
                 "default": False, "options": [
                    {"value": True,  "label": "Yes — RDS will assign a public IP address"},
                    {"value": False, "label": "No — RDS will not assign a public IP address"},
                 ]},
            ]},
        ]},
        {"key": "backup", "label": "Backup", "sections": [
            {"label": "Backup", "fields": [
                {"name": "backup_retention_period", "label": "Backup retention (days)", "type": "number",
                 "default": 7, "validate": {"min": 0, "max": 35}},
                {"name": "__backupWindow__", "label": "Backup window", "type": "select",
                 "default": "default", "options": [
                    {"value": "default", "label": "No preference"},
                    {"value": "select",  "label": "Select window"},
                 ]},
            ]},
        ]},
        _tags_tab(),
        _review_tab(),
    ],
    "synthetic_map": {},
}


# ===========================================================================
# DynamoDB — Create table
# ===========================================================================
_DYNAMODB_WIZARD = {
    "tabs": [
        {"key": "basics", "label": "Table details", "sections": [
            _account_section(),
            {"label": "Table details", "fields": [
                _name("Table name", "Music",
                      r"^[a-zA-Z0-9_.-]{3,255}$",
                      "3-255 chars, letters, digits, underscore, dot, hyphen"),
                {"name": "partition_key", "label": "Partition key", "default": "Artist", "required": True,
                 "validate": {"regex": r"^[\w-]{1,255}$", "message": "1-255 chars, letters/digits/underscore/hyphen"}},
                {"name": "partition_key_type", "label": "Partition key type", "type": "select",
                 "default": "S", "options": [
                    {"value": "S", "label": "String"},
                    {"value": "N", "label": "Number"},
                    {"value": "B", "label": "Binary"},
                 ]},
                {"name": "sort_key", "label": "Sort key (optional)", "default": "",
                 "help": "Combined with partition key forms the primary key. Leave blank for partition-key-only."},
                {"name": "sort_key_type", "label": "Sort key type", "type": "select",
                 "default": "S", "options": [
                    {"value": "S", "label": "String"},
                    {"value": "N", "label": "Number"},
                    {"value": "B", "label": "Binary"},
                 ]},
            ]},
        ]},
        {"key": "settings", "label": "Table settings", "sections": [
            {"label": "Settings", "fields": [
                {"name": "__settings__", "label": "Settings", "type": "radio",
                 "default": "default", "options": [
                    {"value": "default",     "label": "Default settings — fastest"},
                    {"value": "customize",   "label": "Customize settings"},
                 ]},
            ]},
            {"label": "Table class", "fields": [
                {"name": "table_class", "label": "Table class", "type": "radio",
                 "default": "STANDARD", "options": [
                    {"value": "STANDARD",       "label": "DynamoDB Standard"},
                    {"value": "STANDARD_INFREQUENT_ACCESS","label": "DynamoDB Standard-IA"},
                 ]},
            ]},
            {"label": "Read/write capacity settings", "fields": [
                {"name": "billing_mode", "label": "Capacity mode", "type": "radio",
                 "default": "PAY_PER_REQUEST", "options": [
                    {"value": "PAY_PER_REQUEST", "label": "On-demand"},
                    {"value": "PROVISIONED",     "label": "Provisioned"},
                 ]},
                {"name": "read_capacity", "label": "Read capacity units", "type": "number",
                 "default": 5, "validate": {"min": 1, "max": 40000},
                 "ifEquals": {"billing_mode": "PROVISIONED"}},
                {"name": "write_capacity", "label": "Write capacity units", "type": "number",
                 "default": 5, "validate": {"min": 1, "max": 40000},
                 "ifEquals": {"billing_mode": "PROVISIONED"}},
            ]},
        ]},
        _tags_tab(),
        _review_tab(),
    ],
    "synthetic_map": {},
}


# ===========================================================================
# SQS — Create queue
# ===========================================================================
_SQS_WIZARD = {
    "tabs": [
        {"key": "basics", "label": "Details", "sections": [
            _account_section(),
            {"label": "Details", "fields": [
                {"name": "queue_type", "label": "Type", "type": "radio",
                 "default": "Standard", "options": [
                    {"value": "Standard", "label": "Standard — at-least-once delivery, best-effort ordering"},
                    {"value": "FIFO",     "label": "FIFO — exactly-once processing, strict FIFO order"},
                 ]},
                _name("Name", "MyQueue",
                      r"^[a-zA-Z0-9_-]{1,80}(\.fifo)?$",
                      "1-80 chars, letters/digits/hyphens/underscores; FIFO queues must end with .fifo"),
            ]},
        ]},
        {"key": "configuration", "label": "Configuration", "sections": [
            {"label": "Visibility and retention", "fields": [
                {"name": "visibility_timeout", "label": "Visibility timeout (seconds)", "type": "number",
                 "default": 30, "validate": {"min": 0, "max": 43200}},
                {"name": "message_retention_period", "label": "Message retention period (seconds)", "type": "number",
                 "default": 345600, "validate": {"min": 60, "max": 1209600}},
                {"name": "delay_seconds", "label": "Delivery delay (seconds)", "type": "number",
                 "default": 0, "validate": {"min": 0, "max": 900}},
                {"name": "maximum_message_size", "label": "Maximum message size (bytes)", "type": "number",
                 "default": 262144, "validate": {"min": 1024, "max": 262144}},
                {"name": "receive_message_wait_time_seconds", "label": "Receive message wait time (seconds)",
                 "type": "number", "default": 0, "validate": {"min": 0, "max": 20}},
            ]},
            {"label": "FIFO settings", "fields": [
                {"name": "__contentDedup__", "label": "Content-based deduplication", "type": "boolean",
                 "default": False, "ifEquals": {"queue_type": "FIFO"}},
                {"name": "__highThroughput__", "label": "High throughput FIFO", "type": "boolean",
                 "default": False, "ifEquals": {"queue_type": "FIFO"}},
            ]},
        ]},
        {"key": "deadletter", "label": "Dead-letter queue", "sections": [
            {"label": "Dead-letter queue", "fields": [
                {"name": "__useDLQ__", "label": "Enable", "type": "boolean", "default": False},
                {"name": "dlq_arn", "label": "Dead-letter queue ARN", "default": "",
                 "ifEquals": {"__useDLQ__": True}},
                {"name": "max_receive_count", "label": "Maximum receives", "type": "number",
                 "default": 5, "validate": {"min": 1, "max": 1000},
                 "ifEquals": {"__useDLQ__": True}},
            ]},
        ]},
        _tags_tab(),
        _review_tab(),
    ],
    "synthetic_map": {},
}


# ===========================================================================
# Lambda — Create function
# ===========================================================================
_LAMBDA_WIZARD = {
    "tabs": [
        {"key": "basics", "label": "Basic information", "sections": [
            _account_section(),
            {"label": "Function details", "fields": [
                {"name": "__author__", "label": "Author", "type": "radio",
                 "default": "scratch", "options": [
                    {"value": "scratch",   "label": "Author from scratch"},
                    {"value": "blueprint", "label": "Use a blueprint"},
                    {"value": "container", "label": "Container image"},
                 ]},
                _name("Function name", "my-function",
                      r"^[a-zA-Z0-9-_]{1,64}$",
                      "1-64 chars, letters/digits/hyphens/underscores"),
                {"name": "runtime", "label": "Runtime", "type": "select",
                 "default": "python3.12", "options": [
                    {"value": "python3.12", "label": "Python 3.12"},
                    {"value": "python3.11", "label": "Python 3.11"},
                    {"value": "python3.10", "label": "Python 3.10"},
                    {"value": "nodejs20.x", "label": "Node.js 20.x"},
                    {"value": "nodejs18.x", "label": "Node.js 18.x"},
                    {"value": "java21",     "label": "Java 21"},
                    {"value": "java17",     "label": "Java 17"},
                    {"value": "dotnet8",    "label": ".NET 8"},
                    {"value": "go1.x",      "label": "Go 1.x"},
                    {"value": "ruby3.3",    "label": "Ruby 3.3"},
                 ]},
                {"name": "architecture", "label": "Architecture", "type": "radio",
                 "default": "x86_64", "options": [
                    {"value": "x86_64", "label": "x86_64"},
                    {"value": "arm64",  "label": "arm64"},
                 ]},
            ]},
        ]},
        {"key": "permissions", "label": "Permissions", "sections": [
            {"label": "Execution role", "fields": [
                {"name": "__roleChoice__", "label": "Execution role", "type": "radio",
                 "default": "newRole", "options": [
                    {"value": "newRole",      "label": "Create a new role with basic Lambda permissions"},
                    {"value": "existingRole", "label": "Use an existing role"},
                    {"value": "fromPolicy",   "label": "Create a new role from AWS policy templates"},
                 ]},
                {"name": "role", "label": "Existing role", "default": "",
                 "ifEquals": {"__roleChoice__": "existingRole"}},
            ]},
        ]},
        {"key": "advanced", "label": "Advanced settings", "sections": [
            {"label": "Function configuration", "fields": [
                {"name": "handler", "label": "Handler", "default": "lambda_function.lambda_handler"},
                {"name": "timeout", "label": "Timeout (seconds)", "type": "number",
                 "default": 3, "validate": {"min": 1, "max": 900}},
                {"name": "memory_size", "label": "Memory (MB)", "type": "number",
                 "default": 128, "validate": {"min": 128, "max": 10240}},
            ]},
            {"label": "Code", "fields": [
                {"name": "code", "label": "Function code", "type": "text",
                 "default": "def lambda_handler(event, context):\n    return {'statusCode': 200, 'body': 'Hello from Lambda!'}",
                 "help": "Inline Python code or paste any runtime's entry-point."},
            ]},
        ]},
        _tags_tab(),
        _review_tab(),
    ],
    "synthetic_map": {},
}


# ===========================================================================
# API Gateway — Create REST API
# ===========================================================================
_APIGW_WIZARD = {
    "tabs": [
        {"key": "basics", "label": "Create API", "sections": [
            _account_section(),
            {"label": "API details", "fields": [
                {"name": "__apiType__", "label": "API type", "type": "radio",
                 "default": "REST", "options": [
                    {"value": "REST", "label": "REST API"},
                    {"value": "REST_PRIVATE", "label": "REST API (private)"},
                    {"value": "HTTP", "label": "HTTP API"},
                    {"value": "WEBSOCKET", "label": "WebSocket API"},
                 ]},
                _name("API name", "MyApi"),
                {"name": "description", "label": "Description", "default": ""},
                {"name": "endpoint_type", "label": "Endpoint type", "type": "select",
                 "default": "REGIONAL", "options": [
                    {"value": "REGIONAL", "label": "Regional"},
                    {"value": "EDGE",     "label": "Edge-optimized"},
                    {"value": "PRIVATE",  "label": "Private"},
                 ]},
            ]},
            {"label": "Getting started", "fields": [
                {"name": "__seedHello__", "label": "Seed sample MOCK /hello route",
                 "type": "boolean", "default": True,
                 "help": "Creates a starter /hello resource with a MOCK integration responding with {\"message\":\"Hello, world\"}."},
            ]},
        ]},
        _tags_tab(),
        _review_tab(),
    ],
    "synthetic_map": {},
}


# ===========================================================================
# VPC — Create VPC (also supports "VPC + more" wizard scope)
# ===========================================================================
_VPC_WIZARD = {
    "tabs": [
        {"key": "basics", "label": "VPC settings", "sections": [
            _account_section(),
            {"label": "Resources to create", "fields": [
                {"name": "__resourcesScope__", "label": "Resources to create", "type": "radio",
                 "default": "vpcOnly", "options": [
                    {"value": "vpcOnly", "label": "VPC only"},
                    {"value": "vpcAndMore", "label": "VPC, subnets, etc. — multi-AZ defaults"},
                 ]},
            ]},
            {"label": "Name and IPv4 CIDR", "fields": [
                _name("Name tag", "my-vpc"),
                {"name": "cidr_block", "label": "IPv4 CIDR block", "type": "cidr",
                 "default": "10.0.0.0/16", "required": True,
                 "validate": {"regex": r"^\d{1,3}(\.\d{1,3}){3}/\d{1,2}$",
                              "message": "valid IPv4 CIDR notation"}},
                {"name": "__ipv6__", "label": "IPv6 CIDR block", "type": "radio",
                 "default": "none", "options": [
                    {"value": "none", "label": "No IPv6 CIDR block"},
                    {"value": "amazon", "label": "Amazon-provided IPv6 CIDR block"},
                 ]},
                {"name": "__tenancy__", "label": "Tenancy", "type": "select",
                 "default": "default", "options": [
                    {"value": "default", "label": "Default"},
                    {"value": "dedicated", "label": "Dedicated"},
                 ]},
            ]},
        ]},
        {"key": "subnets", "label": "Subnets", "sections": [
            {"label": "Availability Zones and Subnets",
             "fields": [
                {"name": "__help__", "type": "help",
                 "value": "When 'VPC, subnets, etc.' is selected on the first tab, AWS will create subnets across the chosen AZs. In VPC-only mode subnets are added later from the Subnets sub-blade."},
                {"name": "__azCount__", "label": "Number of Availability Zones (AZs)", "type": "select",
                 "default": "2", "ifEquals": {"__resourcesScope__": "vpcAndMore"},
                 "options": [{"value": "1","label":"1"}, {"value": "2","label":"2"}, {"value": "3","label":"3"}]},
                {"name": "__publicSubnets__", "label": "Number of public subnets", "type": "select",
                 "default": "2", "ifEquals": {"__resourcesScope__": "vpcAndMore"},
                 "options": [{"value": "0","label":"0"}, {"value": "1","label":"1"}, {"value": "2","label":"2"}, {"value": "3","label":"3"}]},
                {"name": "__privateSubnets__", "label": "Number of private subnets", "type": "select",
                 "default": "2", "ifEquals": {"__resourcesScope__": "vpcAndMore"},
                 "options": [{"value": "0","label":"0"}, {"value": "1","label":"1"}, {"value": "2","label":"2"}, {"value": "3","label":"3"}]},
            ]},
        ]},
        {"key": "dns", "label": "DNS options", "sections": [
            {"label": "DNS resolution", "fields": [
                {"name": "enable_dns_hostnames", "label": "Enable DNS hostnames",
                 "type": "boolean", "default": True},
                {"name": "enable_dns_support", "label": "Enable DNS resolution",
                 "type": "boolean", "default": True},
            ]},
        ]},
        _tags_tab(),
        _review_tab(),
    ],
    "synthetic_map": {},
}


# ===========================================================================
# EventBridge — Create rule (most common EB action; bus creation is rarer)
# ===========================================================================
_EVENTBRIDGE_WIZARD = {
    "tabs": [
        {"key": "basics", "label": "Define rule detail", "sections": [
            _account_section(),
            {"label": "Rule detail", "fields": [
                _name("Name", "my-eventbridge-rule",
                      r"^[a-zA-Z0-9._-]{1,64}$",
                      "1-64 chars, letters, digits, dots, underscores, hyphens"),
                {"name": "description", "label": "Description", "default": ""},
                {"name": "event_bus_name", "label": "Event bus", "type": "select",
                 "default": "default", "options": [
                    {"value": "default", "label": "default (AWS service events)"},
                    {"value": "custom-app-bus", "label": "custom-app-bus"},
                 ]},
                {"name": "rule_type", "label": "Rule type", "type": "radio",
                 "default": "EventPattern", "options": [
                    {"value": "EventPattern", "label": "Rule with an event pattern"},
                    {"value": "Schedule",     "label": "Schedule (rate or cron expression)"},
                 ]},
            ]},
        ]},
        {"key": "pattern", "label": "Build event pattern", "sections": [
            {"label": "Event pattern", "fields": [
                {"name": "__patternSource__", "label": "Creation method", "type": "radio",
                 "default": "service",
                 "ifEquals": {"rule_type": "EventPattern"}, "options": [
                    {"value": "service", "label": "Use schema (AWS service)"},
                    {"value": "json",    "label": "Custom pattern (JSON editor)"},
                 ]},
                {"name": "event_source", "label": "AWS service",
                 "default": "aws.ec2",
                 "ifEquals": {"__patternSource__": "service"},
                 "help": "Examples: aws.ec2, aws.s3, aws.lambda, aws.rds"},
                {"name": "event_pattern", "label": "Event pattern (JSON)",
                 "type": "text", "default": '{"source": ["aws.ec2"], "detail-type": ["EC2 Instance State-change Notification"]}',
                 "ifEquals": {"__patternSource__": "json"},
                 "help": "Pattern that incoming events must match to trigger this rule."},
                {"name": "schedule_expression", "label": "Schedule expression",
                 "default": "rate(5 minutes)",
                 "ifEquals": {"rule_type": "Schedule"},
                 "help": 'Examples: rate(5 minutes), cron(0 12 * * ? *)'},
            ]},
        ]},
        {"key": "targets", "label": "Select target(s)", "sections": [
            {"label": "Target 1", "fields": [
                {"name": "target_type", "label": "Target type", "type": "select",
                 "default": "lambda", "options": [
                    {"value": "lambda",        "label": "AWS Lambda function"},
                    {"value": "sqs",           "label": "SQS queue"},
                    {"value": "sns",           "label": "SNS topic"},
                    {"value": "stepfunctions", "label": "Step Functions state machine"},
                    {"value": "ecs",           "label": "ECS task"},
                    {"value": "kinesis",       "label": "Kinesis stream"},
                    {"value": "api_dest",      "label": "API destination"},
                 ]},
                {"name": "target_arn", "label": "Target ARN or name",
                 "default": "arn:aws:lambda:us-east-1:123456789012:function:my-function",
                 "required": True},
                {"name": "__retryPolicy__", "label": "Maximum age of event (seconds)",
                 "type": "number", "default": 86400, "validate": {"min": 60, "max": 86400}},
            ]},
        ]},
        _tags_tab(),
        _review_tab(),
    ],
    "synthetic_map": {},
}


# ===========================================================================
# Secrets Manager — Store a new secret
# ===========================================================================
_SECRETSMANAGER_WIZARD = {
    "tabs": [
        {"key": "basics", "label": "Choose secret type", "sections": [
            _account_section(),
            {"label": "Secret type", "fields": [
                {"name": "secret_type", "label": "Secret type", "type": "radio",
                 "default": "Other", "options": [
                    {"value": "RdsCredentials",       "label": "Credentials for Amazon RDS database"},
                    {"value": "RedshiftCredentials",  "label": "Credentials for Amazon Redshift cluster"},
                    {"value": "DocDbCredentials",     "label": "Credentials for Amazon DocumentDB"},
                    {"value": "OtherDb",              "label": "Credentials for other database"},
                    {"value": "Other",                "label": "Other type of secret (API keys, OAuth tokens, etc.)"},
                 ]},
            ]},
            {"label": "Key/value pairs", "fields": [
                {"name": "username", "label": "User name", "default": "admin",
                 "ifEquals": {"secret_type": "RdsCredentials"}},
                {"name": "password", "label": "Password", "type": "password",
                 "ifEquals": {"secret_type": "RdsCredentials"},
                 "validate": {"regex": r"^.{8,1024}$", "message": "8-1024 chars"}},
                {"name": "secret_string", "label": "Secret value — JSON object, e.g. {\"username\":\"admin\",\"password\":\"s3cr3t\"}",
                 "type": "text",
                 "default": '{"key1":"value1","key2":"value2"}',
                 "ifEquals": {"secret_type": "Other"}},
            ]},
            {"label": "Encryption key", "fields": [
                {"name": "kms_key_id", "label": "Encryption key", "type": "select",
                 "default": "aws/secretsmanager", "options": [
                    {"value": "aws/secretsmanager", "label": "aws/secretsmanager (AWS managed key)"},
                    {"value": "custom",             "label": "Customer managed key"},
                 ]},
                {"name": "kms_custom_key_arn", "label": "Customer managed key ARN",
                 "default": "", "ifEquals": {"kms_key_id": "custom"}},
            ]},
        ]},
        {"key": "configure", "label": "Configure secret", "sections": [
            {"label": "Secret name and description", "fields": [
                _name("Secret name", "my-secret",
                      r"^[a-zA-Z0-9/_+=.@-]{1,512}$",
                      "1-512 chars, letters, digits, /_+=.@-"),
                {"name": "description", "label": "Description", "default": ""},
            ]},
            {"label": "Resource permissions (optional)", "fields": [
                {"name": "__resourcePolicy__", "label": "Edit permissions",
                 "type": "boolean", "default": False,
                 "help": "Resource policy controls which AWS accounts and IAM users can access this secret."},
            ]},
            {"label": "Replicate secret (optional)", "fields": [
                {"name": "__replicaRegions__", "label": "Replica Regions (comma-separated)",
                 "default": "",
                 "help": "e.g. us-west-2,eu-west-1"},
            ]},
        ]},
        {"key": "rotation", "label": "Configure rotation", "sections": [
            {"label": "Automatic rotation", "fields": [
                {"name": "__rotationEnabled__", "label": "Automatic rotation",
                 "type": "boolean", "default": False},
                {"name": "rotation_lambda_arn", "label": "Lambda rotation function",
                 "default": "",
                 "ifEquals": {"__rotationEnabled__": True},
                 "help": "ARN of the Lambda that rotates this secret."},
                {"name": "__rotationSchedule__", "label": "Rotation schedule (days)",
                 "type": "number", "default": 30, "validate": {"min": 1, "max": 365},
                 "ifEquals": {"__rotationEnabled__": True}},
            ]},
        ]},
        _tags_tab(),
        _review_tab(),
    ],
    "synthetic_map": {},
}


# ===========================================================================
# KMS — Create key
# ===========================================================================
_KMS_WIZARD = {
    "tabs": [
        {"key": "configuration", "label": "Configure key", "sections": [
            _account_section(),
            {"label": "Key type", "fields": [
                {"name": "key_spec", "label": "Key type", "type": "radio",
                 "default": "SYMMETRIC_DEFAULT", "options": [
                    {"value": "SYMMETRIC_DEFAULT", "label": "Symmetric — single key for both encrypt and decrypt"},
                    {"value": "RSA_2048",          "label": "Asymmetric (RSA 2048)"},
                    {"value": "RSA_3072",          "label": "Asymmetric (RSA 3072)"},
                    {"value": "RSA_4096",          "label": "Asymmetric (RSA 4096)"},
                    {"value": "ECC_NIST_P256",     "label": "Asymmetric (ECC NIST P-256)"},
                    {"value": "HMAC_256",          "label": "HMAC (256-bit)"},
                 ]},
            ]},
            {"label": "Key usage", "fields": [
                {"name": "key_usage", "label": "Key usage", "type": "radio",
                 "default": "ENCRYPT_DECRYPT", "options": [
                    {"value": "ENCRYPT_DECRYPT", "label": "Encrypt and decrypt"},
                    {"value": "SIGN_VERIFY",     "label": "Sign and verify (asymmetric only)"},
                    {"value": "GENERATE_VERIFY_MAC", "label": "Generate and verify MAC (HMAC only)"},
                 ]},
            ]},
            {"label": "Advanced options", "fields": [
                {"name": "origin", "label": "Key material origin", "type": "select",
                 "default": "AWS_KMS", "options": [
                    {"value": "AWS_KMS",       "label": "KMS (default — managed by AWS)"},
                    {"value": "EXTERNAL",      "label": "External (you import key material)"},
                    {"value": "AWS_CLOUDHSM",  "label": "Custom key store (CloudHSM)"},
                 ]},
                {"name": "multi_region", "label": "Multi-Region key",
                 "type": "boolean", "default": False,
                 "help": "Replicate this key to other Regions later."},
            ]},
        ]},
        {"key": "labels", "label": "Add labels", "sections": [
            {"label": "Alias", "fields": [
                _name("Alias", "my-kms-key",
                      r"^[a-zA-Z0-9/_-]{1,256}$",
                      "1-256 chars. Will be prefixed with 'alias/'."),
                {"name": "description", "label": "Description", "default": ""},
            ]},
            {"label": "Tags", "fields": [
                {"name": "tags", "type": "tagsEditor", "default": {}},
            ]},
        ]},
        {"key": "admin", "label": "Define key administrative permissions", "sections": [
            {"label": "Key administrators", "fields": [
                {"name": "__keyAdmins__", "label": "Key administrators (IAM user/role ARNs, comma-separated)",
                 "default": "arn:aws:iam::123456789012:root"},
                {"name": "__allowAdminsDelete__", "label": "Allow key administrators to delete this key",
                 "type": "boolean", "default": True},
            ]},
        ]},
        {"key": "usage", "label": "Define key usage permissions", "sections": [
            {"label": "Key users", "fields": [
                {"name": "__keyUsers__", "label": "Key users (IAM user/role ARNs, comma-separated)",
                 "default": ""},
                {"name": "__externalAccounts__", "label": "Other AWS accounts (account IDs, comma-separated)",
                 "default": ""},
            ]},
        ]},
        _review_tab(),
    ],
    "synthetic_map": {},
}


# ---------------------------------------------------------------------------
# Public registry — keyed by AWS catalog ``key``
# ---------------------------------------------------------------------------
WIZARDS: dict[str, dict] = {
    "ec2":            _EC2_WIZARD,
    "s3":             _S3_WIZARD,
    "iam":            _IAM_WIZARD,
    "rds":            _RDS_WIZARD,
    "dynamodb":       _DYNAMODB_WIZARD,
    "sqs":            _SQS_WIZARD,
    "lambda":         _LAMBDA_WIZARD,
    "apigateway":     _APIGW_WIZARD,
    "vpc":            _VPC_WIZARD,
    "eventbridge":    _EVENTBRIDGE_WIZARD,
    "secretsmanager": _SECRETSMANAGER_WIZARD,
    "kms":            _KMS_WIZARD,
}
