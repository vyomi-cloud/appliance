"""GCP catalog for the standalone /console/gcp SPA.

Mirrors providers/aws_catalog.py shape so the same console-renderer pattern
works across providers. Each service entry has:

    - service:          GCP service name (compute, storage, sql, pubsub, …)
    - namespace:        Display prefix (GCP/Compute, GCP/Storage, …)
    - collection_path:  GET → list, POST → create  ({project}/{region}/{zone}
                        placeholders filled at request time from active space)
    - resource_path:    GET/PATCH/DELETE — single resource ({name} placeholder)
    - name_field:       Attribute on the response that holds the canonical name
    - api_paths:        Per-action method+URL templates (start/stop/restart/...)
    - rail_items:       Left-rail items for this service (GCP's hierarchical
                        groups), each with type primary/child/link/stub. Same
                        shape as AWS rail_items.
    - children:         Child collections referenced by some sub-blades
    - columns:          Grid columns
    - createFields:     Flat backward-compat fields
    - wizard:           Multi-step (or collapsible) wizard from core/gcp_wizards
    - subBlades:        Detail-page left sub-nav from core/gcp_subblades

GCP "Project" maps to our "Space" — project name comes from the active space's
``active_account`` (or "cloudlearn" default). The frontend substitutes it at
request time.
"""
from __future__ import annotations


# Top-level catalog (frontend reads this via /api/gcp/catalog).
RESOURCE_CATALOG_GCP = [
    {
        "key": "compute", "label": "Compute Engine", "icon": "computer",
        "namespace": "GCP/Compute", "service": "compute",
        "collection_path": "/api/gcp/compute/v1/projects/{project}/zones/{zone}/instances",
        "resource_path":   "/api/gcp/compute/v1/projects/{project}/zones/{zone}/instances/{name}",
        "name_field":      "name",
        "create_method":   "POST",
        "api_paths": {
            "start":      {"method": "POST",   "path": "/api/gcp/compute/v1/projects/{project}/zones/{zone}/instances/{name}/start"},
            "stop":       {"method": "POST",   "path": "/api/gcp/compute/v1/projects/{project}/zones/{zone}/instances/{name}/stop"},
            "reset":      {"method": "POST",   "path": "/api/gcp/compute/v1/projects/{project}/zones/{zone}/instances/{name}/reset"},
            "delete":     {"method": "DELETE", "path": "/api/gcp/compute/v1/projects/{project}/zones/{zone}/instances/{name}"},
            "disks":      {"method": "GET",    "path": "/api/gcp/compute/v1/projects/{project}/zones/{zone}/disks"},
            "snapshots":  {"method": "GET",    "path": "/api/gcp/compute/v1/projects/{project}/global/snapshots"},
            "images":     {"method": "GET",    "path": "/api/gcp/compute/v1/projects/{project}/global/images"},
            "instanceGroups": {"method": "GET","path": "/api/gcp/compute/v1/projects/{project}/zones/{zone}/instanceGroups"},
        },
        "columns": [
            ["name",              "Name"],
            ["zone",              "Zone"],
            ["machineType",       "Machine type"],
            ["status",            "Status"],
            ["internalIp",        "Internal IP"],
            ["externalIp",        "External IP"],
        ],
        "createFields": [
            {"name": "name", "label": "Name", "default": "instance-1"},
            {"name": "machineType", "label": "Machine type", "default": "e2-medium"},
        ],
    },
    {
        "key": "storage", "label": "Cloud Storage", "icon": "storage",
        "namespace": "GCP/Storage", "service": "storage",
        "collection_path": "/api/gcp/storage/v1/b",
        "resource_path":   "/api/gcp/storage/v1/b/{name}",
        "name_field":      "name",
        "create_method":   "POST",
        "api_paths": {
            "list":    {"method": "GET",  "path": "/api/gcp/storage/v1/b"},
            "objects": {"method": "GET",  "path": "/api/gcp/storage/v1/b/{name}/o"},
            "iam":     {"method": "GET",  "path": "/api/gcp/storage/v1/b/{name}/iam"},
            "delete":  {"method": "DELETE","path": "/api/gcp/storage/v1/b/{name}"},
        },
        "children": [{"type": "objects", "label": "Objects", "icon": "folder"}],
        "columns": [
            ["name",         "Name"],
            ["location",     "Location"],
            ["storageClass", "Storage class"],
            ["timeCreated",  "Created"],
        ],
        "createFields": [
            {"name": "name", "label": "Bucket name", "default": "my-bucket"},
        ],
    },
    {
        "key": "cloudsql", "label": "Cloud SQL", "icon": "database",
        "namespace": "GCP/CloudSQL", "service": "sql",
        "collection_path": "/api/gcp/rds/databases",
        "resource_path":   "/api/gcp/rds/databases/{name}",
        "name_field":      "name",
        "create_method":   "POST",
        "api_paths": {
            "start":    {"method": "POST",  "path": "/api/gcp/rds/databases/{name}/start"},
            "stop":     {"method": "POST",  "path": "/api/gcp/rds/databases/{name}/stop"},
            "restart":  {"method": "POST",  "path": "/api/gcp/rds/databases/{name}/reboot"},
            "delete":   {"method": "DELETE","path": "/api/gcp/rds/databases/{name}"},
            "backups":  {"method": "GET",   "path": "/api/gcp/rds/databases/{name}/backups"},
            "patch":    {"method": "PATCH", "path": "/api/gcp/sql/v1beta4/projects/{project}/instances/{name}"},
        },
        "columns": [
            ["name",            "Name"],
            ["databaseVersion", "Engine"],
            ["region",          "Region"],
            ["state",           "Status"],
            ["tier",            "Tier"],
        ],
        "createFields": [
            {"name": "name", "label": "Instance ID", "default": "my-sql-instance"},
            {"name": "databaseVersion", "label": "Engine", "default": "POSTGRES_16"},
        ],
    },
    {
        "key": "pubsub", "label": "Pub/Sub", "icon": "campaign",
        "namespace": "GCP/PubSub", "service": "pubsub",
        "collection_path": "/api/gcp/pubsub/v1/projects/{project}/topics",
        "resource_path":   "/api/gcp/pubsub/v1/projects/{project}/topics/{name}",
        "name_field":      "name",
        # Real GCP supports BOTH `PUT /topics/{topic}` (id-in-path, canonical
        # REST) and `POST /topics` (alias method, id in body). We pick POST
        # to match the SDK auto-generated client default and avoid forcing
        # the catalog consumer to construct a {name} URL before knowing it.
        "create_method":   "POST",
        "api_paths": {
            "subscriptions": {"method": "GET",  "path": "/api/gcp/pubsub/v1/projects/{project}/subscriptions"},
            "publish":       {"method": "POST", "path": "/api/gcp/pubsub/v1/projects/{project}/topics/{name}:publish"},
            "delete":        {"method": "DELETE","path": "/api/gcp/pubsub/v1/projects/{project}/topics/{name}"},
        },
        "columns": [
            ["name",                       "Topic ID"],
            ["messageRetentionDuration",   "Retention"],
            ["kmsKeyName",                 "Encryption"],
            ["subscriptionCount",          "Subscriptions"],
        ],
        "createFields": [
            {"name": "name", "label": "Topic ID", "default": "my-topic"},
        ],
    },
    {
        "key": "firestore", "label": "Firestore", "icon": "table_rows",
        "namespace": "GCP/Firestore", "service": "firestore",
        "collection_path": "/api/gcp/firestore/v1/projects/{project}/databases",
        "resource_path":   "/api/gcp/firestore/v1/projects/{project}/databases/{name}",
        "name_field":      "name",
        "create_method":   "POST",
        "api_paths": {
            "documents": {"method": "GET", "path": "/api/gcp/firestore/v1/projects/{project}/databases/{name}/documents"},
            "indexes":   {"method": "GET", "path": "/api/gcp/firestore/v1/projects/{project}/databases/{name}/collectionGroups/-/indexes"},
            "delete":    {"method": "DELETE","path": "/api/gcp/firestore/v1/projects/{project}/databases/{name}"},
        },
        "columns": [
            ["name",      "Database ID"],
            ["type",      "Type"],
            ["locationId","Location"],
            ["state",     "State"],
        ],
        "createFields": [
            {"name": "name", "label": "Database ID", "default": "(default)"},
        ],
    },
    {
        "key": "functions", "label": "Cloud Functions", "icon": "bolt",
        "namespace": "GCP/Functions", "service": "functions",
        "collection_path": "/api/gcp/cloudfunctions/v2/projects/{project}/locations/{region}/functions",
        "resource_path":   "/api/gcp/cloudfunctions/v2/projects/{project}/locations/{region}/functions/{name}",
        "name_field":      "name",
        "create_method":   "POST",
        "api_paths": {
            "call":   {"method": "POST",   "path": "/api/gcp/cloudfunctions/v2/projects/{project}/locations/{region}/functions/{name}:call"},
            "update": {"method": "PATCH",  "path": "/api/gcp/cloudfunctions/v2/projects/{project}/locations/{region}/functions/{name}"},
            "delete": {"method": "DELETE", "path": "/api/gcp/cloudfunctions/v2/projects/{project}/locations/{region}/functions/{name}"},
        },
        "columns": [
            ["name",        "Name"],
            ["runtime",     "Runtime"],
            ["state",       "Status"],
            ["entryPoint",  "Entry point"],
            ["updateTime",  "Last deployed"],
        ],
        "createFields": [
            {"name": "name",       "label": "Function name", "default": "my-function"},
            {"name": "runtime",    "label": "Runtime",       "default": "python312"},
            {"name": "entryPoint", "label": "Entry point",   "default": "hello_world"},
        ],
    },
    {
        "key": "apigateway", "label": "API Gateway", "icon": "api",
        "namespace": "GCP/ApiGateway", "service": "apigateway",
        "collection_path": "/api/gcp/apigateway/v1/projects/{project}/locations/global/apis",
        "resource_path":   "/api/gcp/apigateway/v1/projects/{project}/locations/global/apis/{name}",
        "name_field":      "name",
        "create_method":   "POST",
        "api_paths": {
            "configs":  {"method": "GET",  "path": "/api/gcp/apigateway/v1/projects/{project}/locations/global/apis/{name}/configs"},
            "gateways": {"method": "GET",  "path": "/api/gcp/apigateway/v1/projects/{project}/locations/global/gateways"},
            "delete":   {"method": "DELETE","path": "/api/gcp/apigateway/v1/projects/{project}/locations/global/apis/{name}"},
        },
        "columns": [
            ["name",        "API ID"],
            ["displayName", "Display name"],
            ["state",       "State"],
            ["createTime",  "Created"],
        ],
        "createFields": [
            {"name": "name",        "label": "API ID",       "default": "my-api"},
            {"name": "displayName", "label": "Display name", "default": "My API"},
        ],
    },
    {
        "key": "vpc", "label": "VPC Network", "icon": "lan",
        "namespace": "GCP/VPC", "service": "vpc",
        "collection_path": "/api/gcp/compute/v1/projects/{project}/global/networks",
        "resource_path":   "/api/gcp/compute/v1/projects/{project}/global/networks/{name}",
        "name_field":      "name",
        "create_method":   "POST",
        "api_paths": {
            "subnetworks": {"method": "GET",   "path": "/api/gcp/compute/v1/projects/{project}/regions/{region}/subnetworks"},
            "firewalls":   {"method": "GET",   "path": "/api/gcp/compute/v1/projects/{project}/global/firewalls"},
            "delete":      {"method": "DELETE","path": "/api/gcp/compute/v1/projects/{project}/global/networks/{name}"},
            "patch":       {"method": "PATCH", "path": "/api/gcp/compute/v1/projects/{project}/global/networks/{name}"},
        },
        "children": [
            {"type": "subnetworks", "label": "Subnets",        "icon": "view_module"},
            {"type": "firewalls",   "label": "Firewall rules", "icon": "shield"},
        ],
        "columns": [
            ["name",                 "Name"],
            ["autoCreateSubnetworks","Mode"],
            ["routingConfig.routingMode", "Routing mode"],
            ["subnetworkCount",      "Subnets"],
        ],
        "createFields": [
            {"name": "name", "label": "Network name", "default": "my-vpc"},
        ],
    },
    {
        "key": "iam", "label": "IAM & Admin", "icon": "admin_panel_settings",
        "namespace": "GCP/IAM", "service": "iam",
        "collection_path": "/api/gcp/iam/v1/projects/{project}/serviceAccounts",
        "resource_path":   "/api/gcp/iam/v1/projects/{project}/serviceAccounts/{name}",
        "name_field":      "email",
        "create_method":   "POST",
        "api_paths": {
            "policy":      {"method": "GET", "path": "/api/gcp/iam/v1/projects/{project}:getIamPolicy"},
            "setPolicy":   {"method": "POST","path": "/api/gcp/iam/v1/projects/{project}:setIamPolicy"},
            "delete":      {"method": "DELETE","path":"/api/gcp/iam/v1/projects/{project}/serviceAccounts/{name}"},
        },
        "columns": [
            ["email",       "Email"],
            ["displayName", "Display name"],
            ["uniqueId",    "Unique ID"],
            ["disabled",    "State"],
        ],
        "createFields": [
            {"name": "name",        "label": "Service account name", "default": "my-service-account"},
            {"name": "displayName", "label": "Display name",         "default": "My service account"},
        ],
    },
    # ========================================================================
    # Eventarc — events from GCP services + 3rd parties to destinations
    # (Cloud Run, Functions, Workflows). Backed by /api/gcp/extras/eventarc/...
    # ========================================================================
    {
        "key": "eventarc", "label": "Eventarc", "icon": "hub",
        "namespace": "GCP/Eventarc", "service": "eventarc",
        "collection_path": "/api/gcp/extras/eventarc/triggers",
        "resource_path":   "/api/gcp/extras/eventarc/triggers/{name}",
        "name_field":      "name",
        "create_method":   "POST",
        "api_paths": {
            "triggers":  {"method": "GET", "path": "/api/gcp/extras/eventarc/triggers"},
            "channels":  {"method": "GET", "path": "/api/gcp/extras/eventarc/channels"},
            "providers": {"method": "GET", "path": "/api/gcp/extras/eventarc/providers"},
            "delete":    {"method": "DELETE","path": "/api/gcp/extras/eventarc/triggers/{name}"},
        },
        "columns": [
            ["name",            "Name"],
            ["event_provider",  "Event provider"],
            ["destination",     "Destination"],
            ["region",          "Region"],
            ["state",           "State"],
        ],
        "createFields": [
            {"name": "name", "label": "Trigger name", "default": "my-trigger"},
        ],
    },
    # ========================================================================
    # Secret Manager — encrypted secrets with replication + rotation
    # ========================================================================
    {
        "key": "secretmanager", "label": "Secret Manager", "icon": "key",
        "namespace": "GCP/SecretManager", "service": "secretmanager",
        "collection_path": "/api/gcp/extras/secretmanager/secrets",
        "resource_path":   "/api/gcp/extras/secretmanager/secrets/{name}",
        "name_field":      "name",
        "create_method":   "POST",
        "api_paths": {
            "secrets":  {"method": "GET", "path": "/api/gcp/extras/secretmanager/secrets"},
            "versions": {"method": "GET", "path": "/api/gcp/extras/secretmanager/versions"},
            "rotation": {"method": "GET", "path": "/api/gcp/extras/secretmanager/rotation"},
            "delete":   {"method": "DELETE","path": "/api/gcp/extras/secretmanager/secrets/{name}"},
        },
        "columns": [
            ["name",           "Name"],
            ["replication",    "Replication"],
            ["created",        "Created"],
            ["latest_version", "Latest version"],
        ],
        "createFields": [
            {"name": "name", "label": "Name", "default": "my-secret"},
        ],
    },
    # ========================================================================
    # Cloud KMS — keys + key rings + versions + EKM
    # ========================================================================
    {
        "key": "kms", "label": "Cloud KMS", "icon": "enhanced_encryption",
        "namespace": "GCP/KMS", "service": "kms",
        "collection_path": "/api/gcp/extras/kms/keys",
        "resource_path":   "/api/gcp/extras/kms/keys/{name}",
        "name_field":      "name",
        "create_method":   "POST",
        "api_paths": {
            "keys":           {"method": "GET", "path": "/api/gcp/extras/kms/keys"},
            "keyrings":       {"method": "GET", "path": "/api/gcp/extras/kms/keyrings"},
            "keyversions":    {"method": "GET", "path": "/api/gcp/extras/kms/keyversions"},
            "importJobs":     {"method": "GET", "path": "/api/gcp/extras/kms/importJobs"},
            "ekmConnections": {"method": "GET", "path": "/api/gcp/extras/kms/ekmConnections"},
            "delete":         {"method": "DELETE","path": "/api/gcp/extras/kms/keys/{name}"},
        },
        "columns": [
            ["name",       "Key name"],
            ["keyring",    "Key ring"],
            ["purpose",    "Purpose"],
            ["algorithm",  "Algorithm"],
            ["protection", "Protection level"],
            ["state",      "State"],
        ],
        "createFields": [
            {"name": "name",    "label": "Key name",  "default": "my-key"},
            {"name": "keyring", "label": "Key ring",  "default": "my-keyring"},
        ],
    },
]

_BY_KEY = {c["key"]: c for c in RESOURCE_CATALOG_GCP}


def catalog_for_console() -> list[dict]:
    """Return the GCP catalog augmented with wizard + sub-blade schemas, same
    shape as providers.aws_catalog.catalog_for_console."""
    from core.gcp_wizards import WIZARDS
    from core.gcp_subblades import SUB_BLADES
    out = []
    for c in RESOURCE_CATALOG_GCP:
        entry = {
            "key": c["key"], "label": c["label"], "icon": c["icon"],
            "namespace": c["namespace"], "service": c["service"],
            "collection_path": c["collection_path"],
            "resource_path":   c["resource_path"],
            "name_field":      c["name_field"],
            "create_method":   c["create_method"],
            "api_paths":       c["api_paths"],
            "columns":         c["columns"],
            "createFields":    c["createFields"],
            "children":        c.get("children", []),
        }
        if c["key"] in WIZARDS:
            entry["wizard"] = WIZARDS[c["key"]]
        if c["key"] in SUB_BLADES:
            entry["subBlades"] = SUB_BLADES[c["key"]]
        out.append(entry)
    return out


def build_console_payload(active_project: str = "cloudlearn",
                          active_region: str = "us-central1",
                          active_zone: str = "us-central1-a") -> dict:
    """Full payload for /api/gcp/catalog. Project comes from the active
    space's account/project setting; region/zone default to us-central1/-a
    which most GCP defaults use.

    `extras` carries per-stub schemas for the new Eventarc/Secret Manager/
    Cloud KMS services backed by /api/gcp/extras/...
    """
    from core.gcp_rail_extras import EXTRAS
    slim_extras = {k: {**v, "seed": None} for k, v in EXTRAS.items()}
    return {
        "project": active_project,
        "region":  active_region,
        "zone":    active_zone,
        "services": catalog_for_console(),
        "extras":   slim_extras,
    }
