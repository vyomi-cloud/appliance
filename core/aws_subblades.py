"""AWS-Management-Console-style detail-blade sub-navigation schemas.

Mirrors ``core/azure_subblades.py`` shape so the same SPA renderer can drive
both providers. Each service gets a left sub-nav with grouped sections, same
as the real AWS console's "service navigation" left panel.

Universal renderer types (same names as Azure for shared code):
    overview, activityLog, iam, tags, json, properties, locks, metrics

AWS-specific renderer types:
    sgRules         — Security Group rule editor (VPC)
    routeTables     — Route table → routes editor (VPC)
    subnets         — Subnets list (VPC)
    igws            — Internet gateways (VPC)
    bucketObjects   — Drill into S3 bucket objects
    bucketVersioning — Versioning editor (S3)
    bucketNotifications — Event notifications editor (S3)
    lambdaCode      — Inline code editor (Lambda)
    lambdaInvoke    — Test invocation form (Lambda)
    lambdaPerms     — Resource-based policy editor (Lambda)
    sqsMessages     — Send/Receive message form (SQS)
    sqsDLQ          — DLQ configuration (SQS)
    dynamoItems     — Item viewer/editor (DynamoDB)
    dynamoQuery     — Query/Scan builder (DynamoDB)
    rdsSnapshots    — Snapshots sub-grid (RDS)
    rdsParameterGroups — Parameter groups sub-grid (RDS)
    iamUsers        — Users list (IAM composite)
    iamGroups       — Groups list (IAM composite)
    iamRoles        — Roles list (IAM composite)
    iamPolicies     — Policies list (IAM composite)
    apiResources    — Resources tree (API Gateway)
    apiStages       — Stages (API Gateway)

``type: "stub"`` renders a "Coming soon" placeholder card to match real AWS
console navigation even where the data isn't wired yet.
"""
from __future__ import annotations


# ---------- shared top items ----------

_UNIVERSAL_TOP = [
    {"key": "overview",    "label": "Overview",      "icon": "dashboard",            "type": "overview"},
    {"key": "activityLog", "label": "Activity",      "icon": "list_alt",             "type": "activityLog"},
    {"key": "tags",        "label": "Tags",          "icon": "sell",                 "type": "tags"},
]

def _settings_props_locks():
    return [
        {"key": "properties", "label": "Properties", "icon": "info",  "type": "properties"},
        {"key": "iam",        "label": "Permissions","icon": "admin_panel_settings", "type": "iam"},
    ]


# ===========================================================================
# EC2 — instance detail
# ===========================================================================
_EC2_SUB = [
    *_UNIVERSAL_TOP,
    {"group": "Instance", "items": [
        {"key": "details",        "label": "Details",                "icon": "info",          "type": "overview"},
        {"key": "statusChecks",   "label": "Status and alarms",      "icon": "monitor_heart", "type": "metrics"},
        {"key": "monitoring",     "label": "Monitoring",             "icon": "show_chart",    "type": "metrics"},
        {"key": "networking",     "label": "Networking",             "icon": "lan",           "type": "ec2Networking"},
        {"key": "security",       "label": "Security",               "icon": "shield",        "type": "ec2Security"},
        {"key": "storage",        "label": "Storage",                "icon": "storage",       "type": "ec2Storage"},
    ]},
    {"group": "Connect", "items": [
        {"key": "connect",        "label": "Connect",                "icon": "terminal",      "type": "connect"},
        {"key": "console",        "label": "EC2 serial console",     "icon": "terminal",      "type": "stub"},
    ]},
    {"group": "Operations", "items": [
        {"key": "userData",       "label": "User data",              "icon": "code",          "type": "stub"},
        {"key": "iam",            "label": "IAM role",               "icon": "admin_panel_settings", "type": "stub"},
        *_settings_props_locks(),
    ]},
]


# ===========================================================================
# S3 — bucket detail
# ===========================================================================
_S3_SUB = [
    *_UNIVERSAL_TOP,
    {"group": "Objects", "items": [
        {"key": "objects",        "label": "Objects",                "icon": "folder",        "type": "bucketObjects"},
        {"key": "versions",       "label": "Versions",               "icon": "history",       "type": "stub"},
    ]},
    {"group": "Properties", "items": [
        {"key": "versioning",     "label": "Bucket Versioning",      "icon": "history_edu",   "type": "bucketVersioning"},
        {"key": "notifications",  "label": "Event notifications",    "icon": "notifications", "type": "bucketNotifications"},
        {"key": "lifecycle",      "label": "Lifecycle rules",        "icon": "history_toggle_off", "type": "stub"},
        {"key": "encryption",     "label": "Default encryption",     "icon": "enhanced_encryption", "type": "stub"},
    ]},
    {"group": "Permissions", "items": [
        {"key": "blockPublic",    "label": "Block Public Access",    "icon": "shield",        "type": "stub"},
        {"key": "iam",            "label": "Bucket Policy",          "icon": "policy",        "type": "iam"},
        {"key": "cors",           "label": "Cross-origin resource sharing (CORS)", "icon": "open_in_new", "type": "stub"},
    ]},
    {"group": "Management", "items": [
        {"key": "metrics",        "label": "Metrics",                "icon": "show_chart",    "type": "metrics"},
        *_settings_props_locks(),
    ]},
]


# ===========================================================================
# IAM — composite (users / groups / roles / policies)
# ===========================================================================
_IAM_SUB = [
    {"key": "overview",   "label": "Overview", "icon": "dashboard", "type": "overview"},
    {"group": "Access management", "items": [
        {"key": "users",       "label": "Users",                 "icon": "person",          "type": "iamUsers"},
        {"key": "groups",      "label": "User groups",           "icon": "group",           "type": "iamGroups"},
        {"key": "roles",       "label": "Roles",                 "icon": "badge",           "type": "iamRoles"},
        {"key": "policies",    "label": "Policies",              "icon": "policy",          "type": "iamPolicies"},
        {"key": "providers",   "label": "Identity providers",    "icon": "verified_user",   "type": "stub"},
    ]},
    {"group": "Account settings", "items": [
        {"key": "passwordPolicy","label":"Password policy",       "icon": "vpn_key",         "type": "stub"},
        {"key": "accessAdvisor","label":"Access Analyzer",        "icon": "find_in_page",    "type": "stub"},
    ]},
]


# ===========================================================================
# RDS — DB instance detail
# ===========================================================================
_RDS_SUB = [
    *_UNIVERSAL_TOP,
    {"group": "Connectivity & security", "items": [
        {"key": "endpoints",   "label": "Endpoints",          "icon": "lan",         "type": "rdsEndpoints"},
        {"key": "networking",  "label": "Networking",         "icon": "vpn_lock",    "type": "ec2Networking"},
        {"key": "iam",         "label": "Permissions",        "icon": "admin_panel_settings", "type": "iam"},
    ]},
    {"group": "Configuration", "items": [
        {"key": "configuration","label":"Configuration",      "icon": "tune",        "type": "properties"},
        {"key": "modify",       "label":"Modify",             "icon": "edit",        "type": "stub"},
        {"key": "parameterGroups","label":"Parameter groups", "icon": "settings",    "type": "rdsParameterGroups"},
    ]},
    {"group": "Maintenance & backups", "items": [
        {"key": "snapshots",   "label": "Snapshots",          "icon": "photo_camera","type": "rdsSnapshots"},
        {"key": "backups",     "label": "Automated backups",  "icon": "backup",      "type": "stub"},
        {"key": "maintenance", "label": "Maintenance",        "icon": "build",       "type": "stub"},
    ]},
    {"group": "Monitoring", "items": [
        {"key": "monitoring",  "label": "Monitoring",         "icon": "show_chart",  "type": "metrics"},
        {"key": "logs",        "label": "Logs & events",      "icon": "list_alt",    "type": "stub"},
        {"key": "queryInsights","label":"Performance Insights","icon": "insights",   "type": "stub"},
    ]},
]


# ===========================================================================
# DynamoDB — table detail
# ===========================================================================
_DYNAMODB_SUB = [
    *_UNIVERSAL_TOP,
    {"group": "Tables", "items": [
        {"key": "items",       "label": "Explore items",      "icon": "table_view",  "type": "dynamoItems"},
        {"key": "query",       "label": "Query/Scan",         "icon": "search",      "type": "dynamoQuery"},
        {"key": "indexes",     "label": "Indexes",            "icon": "format_indent_increase", "type": "stub"},
        {"key": "streams",     "label": "Streams and triggers","icon": "stream",     "type": "stub"},
    ]},
    {"group": "Settings", "items": [
        {"key": "capacity",    "label": "Read/write capacity","icon": "speed",       "type": "stub"},
        {"key": "encryption",  "label": "Encryption at rest", "icon": "enhanced_encryption", "type": "stub"},
        {"key": "ttl",         "label": "Time to live",       "icon": "schedule",    "type": "stub"},
        *_settings_props_locks(),
    ]},
    {"group": "Backup", "items": [
        {"key": "backups",     "label": "Backups",            "icon": "backup",      "type": "stub"},
        {"key": "pitr",        "label": "Point-in-time recovery", "icon": "history", "type": "stub"},
    ]},
    {"group": "Monitoring", "items": [
        {"key": "monitoring",  "label": "Monitor",            "icon": "show_chart",  "type": "metrics"},
        {"key": "insights",    "label": "Insights",           "icon": "insights",    "type": "stub"},
    ]},
]


# ===========================================================================
# SQS — queue detail
# ===========================================================================
_SQS_SUB = [
    *_UNIVERSAL_TOP,
    {"group": "Messages", "items": [
        {"key": "sendReceive", "label": "Send and receive messages", "icon": "send", "type": "sqsMessages"},
        {"key": "purge",       "label": "Purge messages",     "icon": "delete_forever","type": "stub"},
    ]},
    {"group": "Configuration", "items": [
        {"key": "configuration","label":"Configuration",       "icon": "tune",        "type": "properties"},
        {"key": "deadLetter",  "label": "Dead-letter queue",   "icon": "warning",     "type": "sqsDLQ"},
        {"key": "encryption",  "label": "Encryption",          "icon": "enhanced_encryption","type": "stub"},
        {"key": "iam",         "label": "Access policy",       "icon": "policy",      "type": "iam"},
    ]},
    {"group": "Monitoring", "items": [
        {"key": "monitoring",  "label": "Monitoring",          "icon": "show_chart",  "type": "metrics"},
    ]},
]


# ===========================================================================
# Lambda — function detail
# ===========================================================================
_LAMBDA_SUB = [
    *_UNIVERSAL_TOP,
    {"group": "Function", "items": [
        {"key": "code",        "label": "Code",                "icon": "code",        "type": "lambdaCode"},
        {"key": "test",        "label": "Test",                "icon": "play_arrow",  "type": "lambdaInvoke"},
        {"key": "envVars",     "label": "Environment variables","icon": "settings",   "type": "stub"},
        {"key": "configuration","label":"Configuration",       "icon": "tune",        "type": "properties"},
    ]},
    {"group": "Aliases & versions", "items": [
        {"key": "versions",    "label": "Versions",            "icon": "history",     "type": "stub"},
        {"key": "aliases",     "label": "Aliases",             "icon": "alternate_email","type": "stub"},
    ]},
    {"group": "Permissions", "items": [
        {"key": "perms",       "label": "Resource-based policy","icon": "policy",     "type": "lambdaPerms"},
        {"key": "iam",         "label": "Execution role",      "icon": "badge",       "type": "iam"},
    ]},
    {"group": "Monitoring", "items": [
        {"key": "monitoring",  "label": "Monitor",             "icon": "show_chart",  "type": "metrics"},
        {"key": "invocations", "label": "Invocations",         "icon": "history",     "type": "activityLog"},
    ]},
]


# ===========================================================================
# API Gateway — API detail
# ===========================================================================
_APIGW_SUB = [
    *_UNIVERSAL_TOP,
    {"group": "Development", "items": [
        {"key": "resources",   "label": "Resources",           "icon": "account_tree","type": "apiResources"},
        {"key": "authorizers", "label": "Authorizers",         "icon": "lock_person", "type": "stub"},
        {"key": "models",      "label": "Models",              "icon": "schema",      "type": "stub"},
    ]},
    {"group": "Publishing", "items": [
        {"key": "stages",      "label": "Stages",              "icon": "rocket_launch","type": "apiStages"},
        {"key": "deployments", "label": "Deployments",         "icon": "history",     "type": "stub"},
    ]},
    {"group": "Settings", "items": [
        {"key": "settings",    "label": "Settings",            "icon": "settings",    "type": "properties"},
        {"key": "iam",         "label": "Resource policy",     "icon": "policy",      "type": "iam"},
    ]},
    {"group": "Monitoring", "items": [
        {"key": "monitoring",  "label": "Dashboard",           "icon": "show_chart",  "type": "metrics"},
        {"key": "logs",        "label": "Logs/Tracing",        "icon": "list_alt",    "type": "stub"},
    ]},
]


# ===========================================================================
# VPC — composite (VPCs / Subnets / SGs / Route tables / IGWs)
# ===========================================================================
_VPC_SUB = [
    {"key": "overview",   "label": "Overview",   "icon": "dashboard", "type": "overview"},
    {"group": "Virtual private cloud", "items": [
        {"key": "details",          "label": "VPC details",            "icon": "info",         "type": "overview"},
        {"key": "subnets",          "label": "Subnets",                "icon": "view_module",  "type": "subnets"},
        {"key": "routeTables",      "label": "Route tables",           "icon": "route",        "type": "routeTables"},
        {"key": "internetGateways", "label": "Internet gateways",      "icon": "language",     "type": "igws"},
        {"key": "natGateways",      "label": "NAT gateways",           "icon": "swap_horiz",   "type": "stub"},
        {"key": "endpoints",        "label": "Endpoints",              "icon": "hub",          "type": "stub"},
    ]},
    {"group": "Security", "items": [
        {"key": "securityGroups",   "label": "Security groups",        "icon": "shield",       "type": "sgRules"},
        {"key": "nacls",            "label": "Network ACLs",           "icon": "verified_user","type": "stub"},
    ]},
    {"group": "Monitoring", "items": [
        {"key": "flowLogs",         "label": "Flow logs",              "icon": "list_alt",     "type": "stub"},
        {"key": "metrics",          "label": "Metrics",                "icon": "show_chart",   "type": "metrics"},
    ]},
]


# ===========================================================================
# EventBridge — rule detail (rules are the primary entity)
# ===========================================================================
_EVENTBRIDGE_SUB = [
    *_UNIVERSAL_TOP,
    {"group": "Rule", "items": [
        {"key": "details",       "label": "Rule details",           "icon": "info",          "type": "overview"},
        {"key": "targets",       "label": "Targets",                "icon": "send",          "type": "stub"},
        {"key": "eventPattern",  "label": "Event pattern",          "icon": "code",          "type": "stub"},
    ]},
    {"group": "Operations", "items": [
        {"key": "invocations",   "label": "Invocations",            "icon": "history",       "type": "activityLog"},
        {"key": "deadletter",    "label": "Dead-letter queue",      "icon": "warning",       "type": "stub"},
        *_settings_props_locks(),
    ]},
    {"group": "Monitoring", "items": [
        {"key": "metrics",       "label": "Metrics",                "icon": "show_chart",    "type": "metrics"},
        {"key": "logs",          "label": "Trace logs",             "icon": "subject",       "type": "stub"},
    ]},
]


# ===========================================================================
# Secrets Manager — secret detail
# ===========================================================================
_SECRETSMANAGER_SUB = [
    *_UNIVERSAL_TOP,
    {"group": "Secret", "items": [
        {"key": "value",         "label": "Secret value",           "icon": "key",           "type": "secretvalue"},
        {"key": "versions",      "label": "Versions",               "icon": "history",       "type": "stub"},
        {"key": "rotation",      "label": "Rotation",               "icon": "autorenew",     "type": "stub"},
        {"key": "replication",   "label": "Replication",            "icon": "public",        "type": "stub"},
    ]},
    {"group": "Settings", "items": [
        {"key": "resourcePolicy","label": "Resource policy",        "icon": "policy",        "type": "iam"},
        {"key": "kmsKey",        "label": "Encryption key",         "icon": "enhanced_encryption", "type": "stub"},
        *_settings_props_locks(),
    ]},
    {"group": "Monitoring", "items": [
        {"key": "metrics",       "label": "Metrics",                "icon": "show_chart",    "type": "metrics"},
    ]},
]


# ===========================================================================
# KMS — key detail
# ===========================================================================
_KMS_SUB = [
    *_UNIVERSAL_TOP,
    {"group": "Key", "items": [
        {"key": "details",       "label": "General configuration",  "icon": "info",          "type": "kmsconfig"},
        {"key": "policy",        "label": "Key policy",             "icon": "policy",        "type": "iam"},
        {"key": "aliases",       "label": "Aliases",                "icon": "label",         "type": "stub"},
        {"key": "rotation",      "label": "Key rotation",           "icon": "autorenew",     "type": "stub"},
    ]},
    {"group": "Permissions", "items": [
        {"key": "keyUsers",      "label": "Key users",              "icon": "group",         "type": "stub"},
        {"key": "keyAdmins",     "label": "Key administrators",     "icon": "admin_panel_settings","type": "stub"},
        {"key": "grants",        "label": "Grants",                 "icon": "fact_check",    "type": "stub"},
        *_settings_props_locks(),
    ]},
    {"group": "Monitoring", "items": [
        {"key": "metrics",       "label": "Metrics",                "icon": "show_chart",    "type": "metrics"},
    ]},
]


# ---------------------------------------------------------------------------
# Public registry
# ---------------------------------------------------------------------------
SUB_BLADES: dict[str, list] = {
    "ec2":            _EC2_SUB,
    "s3":             _S3_SUB,
    "iam":            _IAM_SUB,
    "rds":            _RDS_SUB,
    "dynamodb":       _DYNAMODB_SUB,
    "sqs":            _SQS_SUB,
    "lambda":         _LAMBDA_SUB,
    "apigateway":     _APIGW_SUB,
    "vpc":            _VPC_SUB,
    "eventbridge":    _EVENTBRIDGE_SUB,
    "secretsmanager": _SECRETSMANAGER_SUB,
    "kms":            _KMS_SUB,
}
