"""Azure-portal-style detail-blade sub-navigation schemas.

Each service gets a left sub-nav with grouped sections (Settings / Operations /
Monitoring) — same shape as the real portal. The frontend renders this list
plus a content pane that swaps on click, driven by ``type`` (the renderer key).

Universal types implemented in the SPA::

    overview      → Essentials block + properties kv-grid (default landing pane)
    activityLog   → events table filtered by this resource_id
    iam           → role assignments scoped to this resource (synthesized)
    tags          → key/value editor (PATCH on save)
    json          → raw JSON dump
    properties    → flattened recursive kv-grid of every property path
    locks         → list of resource locks (read-only stub)
    metrics       → time-series mock charts (synthesized sparklines)

Per-service types::

    networking, disks, size, connect, autoShutdown       — VM
    containers, accessKeys, encryption                   — Storage
    databases, firewalls, connStrings                    — SQL
    cosmosDatabases, replicate, backup                   — Cosmos
    configuration, authentication, identity              — Function app
    queuesList, topicsList, sharedAccess                 — Service Bus
    apisList, productsList, subscriptionsList            — APIM
    addressSpace, subnetsList, peerings, connectedDevs   — VNet
    conditions                                           — RBAC

``type: "stub"`` lets us list the nav item without an implemented renderer
(shows a "Coming soon" placeholder) so the structure matches the portal even
where the data isn't ready.
"""
from __future__ import annotations


# ---------- shared groups every service exposes ----------

_UNIVERSAL_TOP = [
    {"key": "overview",    "label": "Overview",            "icon": "dashboard",     "type": "overview"},
    {"key": "activityLog", "label": "Activity log",        "icon": "list_alt",      "type": "activityLog"},
    {"key": "iam",         "label": "Access control (IAM)","icon": "admin_panel_settings", "type": "iam"},
    {"key": "tags",        "label": "Tags",                "icon": "sell",          "type": "tags"},
    {"key": "diagnose",    "label": "Diagnose and solve problems",
                                                          "icon": "healing",        "type": "stub"},
]

def _settings_props_locks():
    """Settings group items shared by most services — properties + locks."""
    return [
        {"key": "properties", "label": "Properties", "icon": "info",      "type": "properties"},
        {"key": "locks",      "label": "Locks",      "icon": "lock",      "type": "locks"},
    ]


# ---------- per-service definitions ----------

_VM_SUB = [
    *_UNIVERSAL_TOP,
    {"group": "Settings", "items": [
        {"key": "networking",   "label": "Networking",        "icon": "lan",          "type": "networking"},
        {"key": "connect",      "label": "Connect",           "icon": "terminal",     "type": "connect"},
        {"key": "disks",        "label": "Disks",             "icon": "storage",      "type": "disks"},
        {"key": "size",         "label": "Size",              "icon": "tune",         "type": "size"},
        {"key": "identity",     "label": "Identity",          "icon": "badge",        "type": "stub"},
        *_settings_props_locks(),
    ]},
    {"group": "Operations", "items": [
        {"key": "autoShutdown", "label": "Auto-shutdown",     "icon": "schedule",     "type": "autoShutdown"},
        {"key": "backup",       "label": "Backup",            "icon": "backup",       "type": "stub"},
        {"key": "extensions",   "label": "Extensions + applications", "icon": "extension", "type": "stub"},
        {"key": "runCommand",   "label": "Run command",       "icon": "play_circle",  "type": "stub"},
    ]},
    {"group": "Monitoring", "items": [
        {"key": "insights",     "label": "Insights",          "icon": "monitoring",   "type": "metrics"},
        {"key": "alerts",       "label": "Alerts",            "icon": "notifications","type": "stub"},
        {"key": "metrics",      "label": "Metrics",           "icon": "show_chart",   "type": "metrics"},
    ]},
]

_STORAGE_SUB = [
    *_UNIVERSAL_TOP,
    {"group": "Data storage", "items": [
        {"key": "containers",   "label": "Containers",        "icon": "folder",       "type": "containers"},
        {"key": "fileShares",   "label": "File shares",       "icon": "folder_shared","type": "stub"},
        {"key": "queues",       "label": "Queues",            "icon": "queue",        "type": "storagequeues"},
        {"key": "tables",       "label": "Tables",            "icon": "table_chart",  "type": "stub"},
    ]},
    {"group": "Security + networking", "items": [
        {"key": "networking",   "label": "Networking",        "icon": "lan",          "type": "networking"},
        {"key": "encryption",   "label": "Encryption",        "icon": "enhanced_encryption", "type": "encryption"},
        {"key": "accessKeys",   "label": "Access keys",       "icon": "key",          "type": "accessKeys"},
        {"key": "sas",          "label": "Shared access signature", "icon": "vpn_key", "type": "stub"},
    ]},
    {"group": "Data management", "items": [
        {"key": "lifecycle",    "label": "Lifecycle management", "icon": "history_toggle_off", "type": "lifecycle"},
        {"key": "replication",  "label": "Geo-replication",   "icon": "public",       "type": "stub"},
    ]},
    {"group": "Settings", "items": _settings_props_locks()},
    {"group": "Monitoring", "items": [
        {"key": "insights",     "label": "Insights",          "icon": "monitoring",   "type": "metrics"},
        {"key": "metrics",      "label": "Metrics",           "icon": "show_chart",   "type": "metrics"},
    ]},
]

_SQL_SUB = [
    *_UNIVERSAL_TOP,
    {"group": "Data management", "items": [
        {"key": "databases",    "label": "Databases",         "icon": "database",     "type": "databases"},
        {"key": "pricingTier",  "label": "Pricing tier",      "icon": "monetization_on","type": "perfTier"},
        {"key": "deletedDb",    "label": "Deleted databases", "icon": "delete",       "type": "stub"},
        {"key": "failover",     "label": "Failover groups",   "icon": "swap_horiz",   "type": "stub"},
        {"key": "backups",      "label": "Backups",           "icon": "backup",       "type": "stub"},
    ]},
    {"group": "Security", "items": [
        {"key": "firewalls",    "label": "Networking",        "icon": "security",     "type": "firewalls"},
        {"key": "tde",          "label": "Transparent data encryption", "icon": "enhanced_encryption", "type": "stub"},
        {"key": "auditing",     "label": "Auditing",          "icon": "fact_check",   "type": "stub"},
        {"key": "defender",     "label": "Microsoft Defender for Cloud", "icon": "shield", "type": "stub"},
    ]},
    {"group": "Settings", "items": [
        {"key": "connStrings",  "label": "Connection strings","icon": "vpn_key",      "type": "connStrings"},
        {"key": "identity",     "label": "Identity",          "icon": "badge",        "type": "stub"},
        *_settings_props_locks(),
    ]},
    {"group": "Monitoring", "items": [
        {"key": "metrics",      "label": "Metrics",           "icon": "show_chart",   "type": "metrics"},
    ]},
]

_COSMOS_SUB = [
    *_UNIVERSAL_TOP,
    {"group": "Data Explorer", "items": [
        {"key": "cosmosDatabases","label": "Data Explorer",   "icon": "explore",      "type": "cosmosExplorer"},
    ]},
    {"group": "Settings", "items": [
        {"key": "throughput",   "label": "Throughput (RU/s)", "icon": "speed",        "type": "throughput"},
        {"key": "replicate",    "label": "Replicate data globally", "icon": "public", "type": "replicate"},
        {"key": "consistency",  "label": "Default consistency",     "icon": "tune",   "type": "stub"},
        {"key": "backup",       "label": "Backup & Restore",  "icon": "backup",       "type": "backup"},
        {"key": "networking",   "label": "Networking",        "icon": "lan",          "type": "networking"},
        {"key": "identity",     "label": "Identity",          "icon": "badge",        "type": "stub"},
        *_settings_props_locks(),
    ]},
    {"group": "Integrations", "items": [
        {"key": "defender",     "label": "Microsoft Defender","icon": "shield",       "type": "stub"},
    ]},
    {"group": "Monitoring", "items": [
        {"key": "insights",     "label": "Insights",          "icon": "monitoring",   "type": "metrics"},
        {"key": "metrics",      "label": "Metrics",           "icon": "show_chart",   "type": "metrics"},
    ]},
]

_FUNCTIONAPP_SUB = [
    *_UNIVERSAL_TOP,
    {"group": "Functions", "items": [
        {"key": "functions",    "label": "Functions",         "icon": "bolt",         "type": "stub"},
        {"key": "appKeys",      "label": "App keys",          "icon": "key",          "type": "stub"},
    ]},
    {"group": "Settings", "items": [
        {"key": "configuration","label": "Environment variables", "icon": "settings", "type": "configuration"},
        {"key": "authentication","label": "Authentication",   "icon": "lock_person",  "type": "authentication"},
        {"key": "identity",     "label": "Identity",          "icon": "badge",        "type": "identity"},
        {"key": "networking",   "label": "Networking",        "icon": "lan",          "type": "networking"},
        {"key": "tls",          "label": "TLS/SSL settings",  "icon": "https",        "type": "stub"},
        {"key": "scaleUp",      "label": "Scale up (App Service plan)", "icon": "trending_up", "type": "stub"},
        *_settings_props_locks(),
    ]},
    {"group": "Deployment", "items": [
        {"key": "slots",        "label": "Deployment slots",  "icon": "swap_horiz",   "type": "slots"},
        {"key": "deployCenter", "label": "Deployment Center", "icon": "rocket_launch","type": "deployCenter"},
    ]},
    {"group": "Monitoring", "items": [
        {"key": "appInsights",  "label": "Application Insights", "icon": "insights", "type": "metrics"},
        {"key": "logStream",    "label": "Log stream",        "icon": "stream",       "type": "stub"},
        {"key": "metrics",      "label": "Metrics",           "icon": "show_chart",   "type": "metrics"},
    ]},
]

_SERVICEBUS_SUB = [
    *_UNIVERSAL_TOP,
    {"group": "Entities", "items": [
        {"key": "queues",       "label": "Queues",            "icon": "queue",        "type": "queuesList"},
        {"key": "topics",       "label": "Topics",            "icon": "campaign",     "type": "topicsDrillDown"},
    ]},
    {"group": "Settings", "items": [
        {"key": "sharedAccess", "label": "Shared access policies", "icon": "vpn_key", "type": "sharedAccess"},
        {"key": "georecovery",  "label": "Geo-recovery",      "icon": "public",       "type": "stub"},
        {"key": "networking",   "label": "Networking",        "icon": "lan",          "type": "networking"},
        {"key": "identity",     "label": "Identity",          "icon": "badge",        "type": "stub"},
        *_settings_props_locks(),
    ]},
    {"group": "Monitoring", "items": [
        {"key": "metrics",      "label": "Metrics",           "icon": "show_chart",   "type": "metrics"},
    ]},
]

_APIM_SUB = [
    *_UNIVERSAL_TOP,
    {"group": "APIs", "items": [
        {"key": "apis",         "label": "APIs",              "icon": "api",          "type": "apisList"},
        {"key": "products",     "label": "Products",          "icon": "inventory_2",  "type": "productsList"},
        {"key": "subscriptions","label": "Subscriptions",     "icon": "card_membership", "type": "subscriptionsList"},
        {"key": "policies",     "label": "Policies",          "icon": "policy",       "type": "apimPolicies"},
        {"key": "namedValues",  "label": "Named values",      "icon": "label",        "type": "stub"},
    ]},
    {"group": "Deployment + infrastructure", "items": [
        {"key": "networking",   "label": "Virtual network",   "icon": "lan",          "type": "networking"},
        {"key": "customDomains","label": "Custom domains",    "icon": "language",     "type": "stub"},
        {"key": "backups",      "label": "Backup",            "icon": "backup",       "type": "stub"},
    ]},
    {"group": "Settings", "items": [
        *_settings_props_locks(),
    ]},
    {"group": "Monitoring", "items": [
        {"key": "appInsights",  "label": "Application Insights", "icon": "insights", "type": "metrics"},
        {"key": "metrics",      "label": "Metrics",           "icon": "show_chart",   "type": "metrics"},
    ]},
]

_VNET_SUB = [
    *_UNIVERSAL_TOP,
    {"group": "Settings", "items": [
        {"key": "addressSpace", "label": "Address space",     "icon": "tag",          "type": "addressSpace"},
        {"key": "subnets",      "label": "Subnets",           "icon": "view_module",  "type": "subnetsList"},
        {"key": "connectedDevs","label": "Connected devices", "icon": "devices",      "type": "connectedDevs"},
        {"key": "peerings",     "label": "Peerings",          "icon": "compare_arrows","type": "peerings"},
        {"key": "dnsServers",   "label": "DNS servers",       "icon": "dns",          "type": "stub"},
        {"key": "ddos",         "label": "DDoS protection",   "icon": "shield",       "type": "stub"},
        *_settings_props_locks(),
    ]},
    {"group": "Monitoring", "items": [
        {"key": "diagnostic",   "label": "Diagnostic settings", "icon": "build",      "type": "stub"},
    ]},
]

_KEYVAULT_SUB = [
    *_UNIVERSAL_TOP,
    {"group": "Objects", "items": [
        {"key": "secrets",      "label": "Secrets",           "icon": "key",          "type": "kvsecrets"},
        {"key": "keys",         "label": "Keys",              "icon": "lock",         "type": "kvkeys"},
        {"key": "certificates", "label": "Certificates",      "icon": "verified",     "type": "stub"},
    ]},
    {"group": "Settings", "items": [
        {"key": "accessPolicies","label": "Access policies",  "icon": "policy",       "type": "accessPolicies"},
        {"key": "accessConfig", "label": "Access configuration", "icon": "tune",      "type": "stub"},
        {"key": "networking",   "label": "Networking",        "icon": "lan",          "type": "networking"},
        *_settings_props_locks(),
    ]},
    {"group": "Monitoring", "items": [
        {"key": "metrics",      "label": "Metrics",           "icon": "show_chart",   "type": "metrics"},
    ]},
]

_EVENTGRID_SUB = [
    *_UNIVERSAL_TOP,
    {"group": "Events", "items": [
        {"key": "eventSubs",   "label": "Event subscriptions", "icon": "subscriptions", "type": "eventSubs"},
        {"key": "topicTypes",  "label": "Topic types",         "icon": "list",          "type": "stub"},
        {"key": "accessKeys",  "label": "Access keys",         "icon": "key",           "type": "egAccessKeys"},
    ]},
    {"group": "Settings", "items": [
        {"key": "networking",  "label": "Networking",          "icon": "lan",           "type": "networking"},
        {"key": "identity",    "label": "Identity",            "icon": "badge",         "type": "stub"},
        *_settings_props_locks(),
    ]},
    {"group": "Monitoring", "items": [
        {"key": "metrics",     "label": "Metrics",             "icon": "show_chart",    "type": "metrics"},
    ]},
]

_RBAC_SUB = [
    {"key": "overview",   "label": "Overview",   "icon": "dashboard", "type": "overview"},
    {"key": "json",       "label": "JSON view",  "icon": "code",      "type": "json"},
    {"key": "conditions", "label": "Conditions", "icon": "rule",      "type": "stub"},
]


# Public registry — keyed by catalog ``key`` so azure_services.py can attach.
SUB_BLADES: dict[str, list] = {
    "vm":          _VM_SUB,
    "storage":     _STORAGE_SUB,
    "sql":         _SQL_SUB,
    "cosmos":      _COSMOS_SUB,
    "functionapp": _FUNCTIONAPP_SUB,
    "servicebus":  _SERVICEBUS_SUB,
    "apim":        _APIM_SUB,
    "vnet":        _VNET_SUB,
    "keyvault":    _KEYVAULT_SUB,
    "eventgrid":   _EVENTGRID_SUB,
    "rbac":        _RBAC_SUB,
}
