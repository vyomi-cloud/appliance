"""Google-Cloud-Console-style detail-page sub-navigation per service.

GCP detail pages use **both** layers (matches the cross-cloud-parity findings):

* **Left sub-nav** with sections grouped (Overview / Settings / Operations /
  Monitoring) — the user clicks an item, the right pane swaps. Real GCP shows
  a left sidebar inside the detail page; we mirror that with the same shape
  used for Azure.

* Universal renderer types reused across all three providers:
    overview, activityLog, iam, tags, json, properties, metrics

* GCP-specific renderer types (filled in GCP-C):
    networking, disks, machineSize, connect          — Compute
    bucketObjects, lifecycle, encryption             — Storage
    connectivity, backups, replicas, flags           — Cloud SQL
    subscriptions, schemas, snapshots                — Pub/Sub
    indexes, securityRules, exports                  — Firestore
    sourceCode, trigger, envVars                     — Functions
    apiConfigs, gateways                              — API Gateway
    subnetsList, firewalls, peerings, routes         — VPC
    members, customRoles, auditConfig                — IAM
"""
from __future__ import annotations


# ---------- shared shapes ----------

_UNIVERSAL_TOP = [
    {"key": "overview",    "label": "Overview",      "icon": "dashboard",   "type": "overview"},
    {"key": "activityLog", "label": "Activity",      "icon": "list_alt",    "type": "activityLog"},
    {"key": "iam",         "label": "Permissions",   "icon": "admin_panel_settings", "type": "iam"},
    {"key": "tags",        "label": "Labels",        "icon": "sell",        "type": "tags"},
]

def _settings_props():
    return [
        {"key": "properties", "label": "Properties", "icon": "info",  "type": "properties"},
    ]


# ============================================================================
# Compute Engine — VM instance detail
# ============================================================================
_COMPUTE_SUB = [
    *_UNIVERSAL_TOP,
    {"group": "Settings", "items": [
        {"key": "networking",  "label": "Networking",       "icon": "lan",        "type": "networking"},
        {"key": "disks",       "label": "Disks",            "icon": "storage",    "type": "stub"},
        {"key": "machineSize", "label": "Machine size",     "icon": "tune",       "type": "stub"},
        {"key": "metadata",    "label": "Metadata",         "icon": "data_object","type": "stub"},
        {"key": "startup",     "label": "Startup script",   "icon": "code",       "type": "stub"},
        *_settings_props(),
    ]},
    {"group": "Operations", "items": [
        {"key": "connect",     "label": "Connect",          "icon": "terminal",   "type": "stub"},
        {"key": "scheduling",  "label": "Scheduling",       "icon": "schedule",   "type": "stub"},
        {"key": "snapshots",   "label": "Snapshots",        "icon": "photo_camera","type": "stub"},
    ]},
    {"group": "Monitoring", "items": [
        {"key": "metrics",     "label": "Metrics",          "icon": "show_chart", "type": "metrics"},
        {"key": "logs",        "label": "Logs",             "icon": "subject",    "type": "stub"},
    ]},
]


# ============================================================================
# Cloud Storage — Bucket detail
# ============================================================================
_STORAGE_SUB = [
    *_UNIVERSAL_TOP,
    {"group": "Data", "items": [
        {"key": "objects",     "label": "Objects",          "icon": "folder",     "type": "objects"},
        {"key": "lifecycle",   "label": "Lifecycle",        "icon": "history_toggle_off","type":"stub"},
    ]},
    {"group": "Settings", "items": [
        {"key": "configuration","label":"Configuration",     "icon": "tune",       "type": "properties"},
        {"key": "encryption",  "label": "Encryption",       "icon": "enhanced_encryption","type":"stub"},
        {"key": "retention",   "label": "Retention",        "icon": "lock",       "type": "stub"},
        *_settings_props(),
    ]},
    {"group": "Monitoring", "items": [
        {"key": "metrics",     "label": "Metrics",          "icon": "show_chart", "type": "metrics"},
    ]},
]


# ============================================================================
# Cloud SQL — Instance detail
# ============================================================================
_CLOUDSQL_SUB = [
    *_UNIVERSAL_TOP,
    {"group": "Data", "items": [
        {"key": "databases",   "label": "Databases",        "icon": "database",   "type": "stub"},
        {"key": "users",       "label": "Users",            "icon": "person",     "type": "stub"},
        {"key": "backups",     "label": "Backups",          "icon": "backup",     "type": "stub"},
        {"key": "replicas",    "label": "Replicas",         "icon": "content_copy","type": "stub"},
    ]},
    {"group": "Settings", "items": [
        {"key": "connectivity","label":"Connectivity",      "icon": "lan",        "type": "stub"},
        {"key": "flags",       "label": "Flags",            "icon": "tune",       "type": "stub"},
        {"key": "logging",     "label": "Logging",          "icon": "subject",    "type": "stub"},
        *_settings_props(),
    ]},
    {"group": "Monitoring", "items": [
        {"key": "metrics",     "label": "Metrics",          "icon": "show_chart", "type": "metrics"},
        {"key": "insights",    "label": "Query Insights",   "icon": "insights",   "type": "stub"},
    ]},
]


# ============================================================================
# Pub/Sub — Topic detail
# ============================================================================
_PUBSUB_SUB = [
    *_UNIVERSAL_TOP,
    {"group": "Topic", "items": [
        {"key": "subscriptions","label":"Subscriptions",    "icon": "subscriptions","type": "stub"},
        {"key": "schemas",     "label": "Schema",           "icon": "schema",     "type": "stub"},
        {"key": "messages",    "label": "Messages",         "icon": "mail",       "type": "stub"},
    ]},
    {"group": "Settings", "items": [
        {"key": "encryption",  "label": "Encryption",       "icon": "enhanced_encryption","type":"stub"},
        *_settings_props(),
    ]},
    {"group": "Monitoring", "items": [
        {"key": "metrics",     "label": "Metrics",          "icon": "show_chart", "type": "metrics"},
    ]},
]


# ============================================================================
# Firestore — Database detail
# ============================================================================
_FIRESTORE_SUB = [
    *_UNIVERSAL_TOP,
    {"group": "Data", "items": [
        {"key": "data",        "label": "Data",             "icon": "data_object","type": "stub"},
        {"key": "query",       "label": "Query builder",    "icon": "search",     "type": "stub"},
        {"key": "indexes",     "label": "Indexes",          "icon": "format_indent_increase","type":"stub"},
    ]},
    {"group": "Settings", "items": [
        {"key": "rules",       "label": "Security rules",   "icon": "policy",     "type": "stub"},
        {"key": "imports",     "label": "Import / Export",  "icon": "import_export","type": "stub"},
        *_settings_props(),
    ]},
    {"group": "Monitoring", "items": [
        {"key": "metrics",     "label": "Usage",            "icon": "show_chart", "type": "metrics"},
    ]},
]


# ============================================================================
# Cloud Functions — Function detail
# ============================================================================
_FUNCTIONS_SUB = [
    *_UNIVERSAL_TOP,
    {"group": "Function", "items": [
        {"key": "sourceCode",  "label": "Source",           "icon": "code",       "type": "stub"},
        {"key": "trigger",     "label": "Trigger",          "icon": "bolt",       "type": "stub"},
        {"key": "envVars",     "label": "Variables",        "icon": "settings",   "type": "stub"},
        {"key": "testing",     "label": "Testing",          "icon": "play_arrow", "type": "stub"},
    ]},
    {"group": "Settings", "items": [
        {"key": "networking",  "label": "Networking",       "icon": "lan",        "type": "stub"},
        *_settings_props(),
    ]},
    {"group": "Monitoring", "items": [
        {"key": "metrics",     "label": "Metrics",          "icon": "show_chart", "type": "metrics"},
        {"key": "logs",        "label": "Logs",             "icon": "subject",    "type": "stub"},
    ]},
]


# ============================================================================
# API Gateway — Gateway detail
# ============================================================================
_APIGW_SUB = [
    *_UNIVERSAL_TOP,
    {"group": "Configuration", "items": [
        {"key": "apiConfigs",  "label": "Configs",          "icon": "tune",       "type": "stub"},
        {"key": "routes",      "label": "Routes",           "icon": "alt_route",  "type": "stub"},
        *_settings_props(),
    ]},
    {"group": "Monitoring", "items": [
        {"key": "metrics",     "label": "Metrics",          "icon": "show_chart", "type": "metrics"},
        {"key": "logs",        "label": "Logs",             "icon": "subject",    "type": "stub"},
    ]},
]


# ============================================================================
# VPC Network — Network detail
# ============================================================================
_VPC_SUB = [
    *_UNIVERSAL_TOP,
    {"group": "Network", "items": [
        {"key": "subnetsList", "label": "Subnets",          "icon": "view_module","type": "stub"},
        {"key": "firewalls",   "label": "Firewall rules",   "icon": "shield",     "type": "stub"},
        {"key": "routes",      "label": "Routes",           "icon": "route",      "type": "stub"},
        {"key": "peerings",    "label": "VPC peering",      "icon": "compare_arrows","type": "stub"},
        *_settings_props(),
    ]},
    {"group": "Monitoring", "items": [
        {"key": "metrics",     "label": "Network metrics",  "icon": "show_chart", "type": "metrics"},
        {"key": "flowLogs",    "label": "Flow logs",        "icon": "subject",    "type": "stub"},
    ]},
]


# ============================================================================
# IAM — Service account / role detail
# ============================================================================
_IAM_SUB = [
    {"key": "overview",   "label": "Overview", "icon": "dashboard", "type": "overview"},
    {"group": "Access", "items": [
        {"key": "members",     "label": "Members",          "icon": "group",      "type": "stub"},
        {"key": "permissions", "label": "Permissions",      "icon": "policy",     "type": "stub"},
        {"key": "keys",        "label": "Keys",             "icon": "vpn_key",    "type": "stub"},
    ]},
    {"group": "Settings", "items": [
        *_settings_props(),
    ]},
    {"group": "Audit", "items": [
        {"key": "activityLog", "label": "Activity log",     "icon": "list_alt",   "type": "activityLog"},
    ]},
]


# ============================================================================
# Eventarc — trigger detail
# ============================================================================
_EVENTARC_SUB = [
    *_UNIVERSAL_TOP,
    {"group": "Trigger", "items": [
        {"key": "matching",    "label": "Event matching",   "icon": "filter_alt", "type": "stub"},
        {"key": "destination", "label": "Destination",      "icon": "send",       "type": "stub"},
        *_settings_props(),
    ]},
    {"group": "Monitoring", "items": [
        {"key": "metrics",     "label": "Metrics",          "icon": "show_chart", "type": "metrics"},
        {"key": "logs",        "label": "Logs",             "icon": "subject",    "type": "stub"},
    ]},
]


# ============================================================================
# Secret Manager — secret detail
# ============================================================================
_SECRETMANAGER_SUB = [
    *_UNIVERSAL_TOP,
    {"group": "Secret", "items": [
        {"key": "value",       "label": "Secret value",     "icon": "key",        "type": "secretvalue"},
        {"key": "versions",    "label": "Versions",         "icon": "history",    "type": "stub"},
        {"key": "rotation",    "label": "Rotation",         "icon": "autorenew",  "type": "stub"},
        {"key": "replication", "label": "Replication",      "icon": "public",     "type": "stub"},
    ]},
    {"group": "Settings", "items": [
        {"key": "encryption",  "label": "Encryption",       "icon": "enhanced_encryption", "type": "stub"},
        *_settings_props(),
    ]},
]


# ============================================================================
# Cloud KMS — key detail
# ============================================================================
_KMS_SUB = [
    *_UNIVERSAL_TOP,
    {"group": "Key", "items": [
        {"key": "versions",    "label": "Versions",         "icon": "history",    "type": "stub"},
        {"key": "rotation",    "label": "Rotation & labels","icon": "autorenew",  "type": "kmsconfig"},
        {"key": "policy",      "label": "Key policy",       "icon": "policy",     "type": "iam"},
    ]},
    {"group": "Settings", "items": [
        {"key": "imports",     "label": "Import jobs",      "icon": "upload",     "type": "stub"},
        *_settings_props(),
    ]},
    {"group": "Monitoring", "items": [
        {"key": "metrics",     "label": "Metrics",          "icon": "show_chart", "type": "metrics"},
    ]},
]


# Public registry — keyed by catalog ``key``
SUB_BLADES: dict[str, list] = {
    "compute":       _COMPUTE_SUB,
    "storage":       _STORAGE_SUB,
    "cloudsql":      _CLOUDSQL_SUB,
    "pubsub":        _PUBSUB_SUB,
    "firestore":     _FIRESTORE_SUB,
    "functions":     _FUNCTIONS_SUB,
    "apigateway":    _APIGW_SUB,
    "vpc":           _VPC_SUB,
    "iam":           _IAM_SUB,
    "eventarc":      _EVENTARC_SUB,
    "secretmanager": _SECRETMANAGER_SUB,
    "kms":           _KMS_SUB,
}
