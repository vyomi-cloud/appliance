"""Google-Cloud-Console-style Create wizards.

GCP wizards in the real console are mostly **single-page forms with
collapsible sections** plus a sticky right-side summary card (cost estimate +
"Equivalent code" expander). NOT stepped wizards like Azure portal.

This module mirrors :mod:`core.aws_wizards` / :mod:`core.azure_wizards`
shape so the renderer can dispatch by service key. GCP-C will add rich
sections; this baseline gives every service: Basics → Labels → Review.

Field shape identical to AWS/Azure (text/select/number/password/boolean/
radio/vmSize/cidr/labelsEditor/info/help). `labelsEditor` is GCP's name for
the kv editor (renders identically to tagsEditor).
"""
from __future__ import annotations


def _name(label: str, default: str, regex: str = r"^[a-z][a-z0-9-]{0,61}[a-z0-9]$",
          msg: str = "1-63 chars, lowercase, digits, hyphens; start with letter, end alphanumeric"):
    return {"name": "name", "label": label, "default": default, "required": True,
            "validate": {"regex": regex, "message": msg}}


def _region():
    return {"name": "__region__", "label": "Region", "type": "select", "required": True,
            "default": "us-central1", "options": [
                {"value": "us-central1",       "label": "us-central1 (Iowa)"},
                {"value": "us-east1",          "label": "us-east1 (South Carolina)"},
                {"value": "us-east4",          "label": "us-east4 (Northern Virginia)"},
                {"value": "us-west1",          "label": "us-west1 (Oregon)"},
                {"value": "us-west2",          "label": "us-west2 (Los Angeles)"},
                {"value": "europe-west1",      "label": "europe-west1 (Belgium)"},
                {"value": "europe-west2",      "label": "europe-west2 (London)"},
                {"value": "europe-west4",      "label": "europe-west4 (Netherlands)"},
                {"value": "asia-east1",        "label": "asia-east1 (Taiwan)"},
                {"value": "asia-northeast1",   "label": "asia-northeast1 (Tokyo)"},
                {"value": "asia-southeast1",   "label": "asia-southeast1 (Singapore)"},
            ]}


def _zone():
    return {"name": "__zone__", "label": "Zone", "type": "select", "required": True,
            "default": "us-central1-a", "options": [
                {"value": "us-central1-a", "label": "us-central1-a"},
                {"value": "us-central1-b", "label": "us-central1-b"},
                {"value": "us-central1-c", "label": "us-central1-c"},
                {"value": "us-east1-b",    "label": "us-east1-b"},
                {"value": "us-east1-c",    "label": "us-east1-c"},
                {"value": "us-east1-d",    "label": "us-east1-d"},
                {"value": "us-west1-a",    "label": "us-west1-a"},
                {"value": "us-west1-b",    "label": "us-west1-b"},
                {"value": "europe-west1-b","label": "europe-west1-b"},
            ]}


def _project_section():
    return {"label": "Project", "fields": [
        {"name": "__project__", "label": "Project", "type": "info",
         "help": "Active project (set by the simulator space)."},
    ]}


def _labels_section():
    # GCP calls them labels, not tags. Field type is labelsEditor — frontend
    # renders identically to tagsEditor.
    return {"label": "Labels", "fields": [
        {"name": "__help__", "type": "help",
         "value": "Labels help you organize and filter your resources. Each label is a key-value pair."},
        {"name": "labels", "type": "labelsEditor", "default": {}},
    ]}


def _review_section():
    return {"label": "Equivalent code", "fields": [
        {"name": "__help__", "type": "help",
         "value": "Use gcloud CLI, REST, or Terraform with the equivalent code shown in the right summary card before creating."},
    ]}


def _basic_wizard(name_field, name_default, region_or_zone="zone", regex=None, msg=None,
                  extra_basic_fields=None, sections=None):
    """Build a minimal 3-section wizard (Basics → Labels → Review) shared by
    most services. GCP-C will replace with richer service-specific sections."""
    basics_fields = [name_field if name_field else _name("Name", name_default, regex, msg)]
    if region_or_zone == "region":
        basics_fields.append(_region())
    elif region_or_zone == "zone":
        basics_fields.append(_region()); basics_fields.append(_zone())
    if extra_basic_fields:
        basics_fields.extend(extra_basic_fields)
    return {
        "tabs": [
            {"key": "basics", "label": "Basics", "sections": [
                _project_section(),
                {"label": "Configuration", "fields": basics_fields},
                *(sections or []),
            ]},
            {"key": "labels", "label": "Labels", "sections": [_labels_section()]},
            {"key": "review", "label": "Review and create", "auto": True,
             "sections": [{"label": "Summary", "fields": []}]},
        ],
        "synthetic_map": {},
    }


# ============================================================================
# Compute Engine — Create VM instance
# ============================================================================
_COMPUTE_WIZARD = _basic_wizard(
    name_field=_name("Name", "instance-1"),
    name_default="instance-1", region_or_zone="zone",
    extra_basic_fields=[
        {"name": "machineType", "label": "Machine type", "type": "vmSize",
         "default": "e2-medium", "required": True,
         "help": "Machine type from the simulator's GCP catalog. Host-clamped on actual launch."},
    ],
    sections=[
        {"label": "Boot disk", "fields": [
            {"name": "__os__", "label": "Operating system", "type": "select",
             "default": "debian-12", "options": [
                {"value": "debian-12",  "label": "Debian 12 (bookworm)"},
                {"value": "debian-11",  "label": "Debian 11 (bullseye)"},
                {"value": "ubuntu-2204","label": "Ubuntu 22.04 LTS"},
                {"value": "ubuntu-2404","label": "Ubuntu 24.04 LTS"},
                {"value": "rhel-9",     "label": "Red Hat Enterprise Linux 9"},
                {"value": "rocky-9",    "label": "Rocky Linux 9"},
                {"value": "cos-stable", "label": "Container-Optimized OS (stable)"},
             ]},
            {"name": "__bootDiskSize__", "label": "Size (GB)", "type": "number",
             "default": 10, "validate": {"min": 10, "max": 65536}},
            {"name": "__bootDiskType__", "label": "Boot disk type", "type": "select",
             "default": "pd-balanced", "options": [
                {"value": "pd-balanced", "label": "Balanced persistent disk (recommended)"},
                {"value": "pd-ssd",      "label": "SSD persistent disk"},
                {"value": "pd-standard", "label": "Standard persistent disk"},
                {"value": "hyperdisk-balanced", "label": "Hyperdisk Balanced"},
             ]},
        ]},
        {"label": "Identity and API access", "fields": [
            {"name": "__serviceAccount__", "label": "Service account", "type": "select",
             "default": "compute-default", "options": [
                {"value": "compute-default", "label": "Compute Engine default service account"},
                {"value": "none",            "label": "No service account"},
             ]},
            {"name": "__scopes__", "label": "Access scopes", "type": "radio",
             "default": "default", "options": [
                {"value": "default",  "label": "Allow default access"},
                {"value": "full",     "label": "Allow full access to all Cloud APIs"},
                {"value": "custom",   "label": "Set access for each API"},
             ]},
        ]},
        {"label": "Firewall", "fields": [
            {"name": "__allowHttp__",  "label": "Allow HTTP traffic",  "type": "boolean", "default": False},
            {"name": "__allowHttps__", "label": "Allow HTTPS traffic", "type": "boolean", "default": False},
        ]},
    ],
)


# ============================================================================
# Cloud Storage — Create bucket
# ============================================================================
_STORAGE_WIZARD = _basic_wizard(
    name_field=_name("Name your bucket", "my-bucket",
                     r"^[a-z0-9][a-z0-9._-]{1,61}[a-z0-9]$",
                     "3-63 chars, lowercase, digits, dots, hyphens, underscores; start+end alphanumeric"),
    name_default="my-bucket", region_or_zone="region",
    extra_basic_fields=[
        {"name": "__locationType__", "label": "Location type", "type": "radio",
         "default": "region", "options": [
            {"value": "region",    "label": "Region — Lowest latency within a single region"},
            {"value": "dual-region","label": "Dual-region — High availability across two regions"},
            {"value": "multi-region","label": "Multi-region — Highest availability across a large geographic area"},
         ]},
        {"name": "__storageClass__", "label": "Default storage class", "type": "select",
         "default": "STANDARD", "options": [
            {"value": "STANDARD", "label": "Standard — Best for short-term storage"},
            {"value": "NEARLINE", "label": "Nearline — Best for backups (30-day minimum)"},
            {"value": "COLDLINE", "label": "Coldline — Best for disaster recovery (90-day minimum)"},
            {"value": "ARCHIVE",  "label": "Archive — Best for long-term archiving (365-day minimum)"},
         ]},
        {"name": "__accessControl__", "label": "Access control", "type": "radio",
         "default": "uniform", "options": [
            {"value": "uniform",    "label": "Uniform — Ensures uniform access at bucket level (recommended)"},
            {"value": "fine-grained","label": "Fine-grained — Object-level access with ACLs"},
         ]},
    ],
)


# ============================================================================
# Cloud SQL — Create instance
# ============================================================================
_CLOUDSQL_WIZARD = _basic_wizard(
    name_field=_name("Instance ID", "my-sql-instance",
                     r"^[a-z][a-z0-9-]{0,97}$",
                     "1-98 chars, lowercase, digits, hyphens; start with letter"),
    name_default="my-sql-instance", region_or_zone="region",
    extra_basic_fields=[
        {"name": "databaseVersion", "label": "Database engine", "type": "select",
         "default": "POSTGRES_16", "options": [
            {"value": "POSTGRES_16", "label": "PostgreSQL 16"},
            {"value": "POSTGRES_15", "label": "PostgreSQL 15"},
            {"value": "POSTGRES_14", "label": "PostgreSQL 14"},
            {"value": "MYSQL_8_0",   "label": "MySQL 8.0"},
            {"value": "MYSQL_5_7",   "label": "MySQL 5.7"},
            {"value": "SQLSERVER_2022_STANDARD", "label": "SQL Server 2022 Standard"},
         ]},
        {"name": "rootPassword", "label": "Password for the postgres user", "type": "password",
         "required": True,
         "validate": {"regex": r"^.{8,99}$", "message": "8-99 characters"}},
    ],
    sections=[
        {"label": "Choose a Cloud SQL edition", "fields": [
            {"name": "edition", "label": "Edition", "type": "radio",
             "default": "ENTERPRISE", "options": [
                {"value": "ENTERPRISE",      "label": "Enterprise — Production workloads"},
                {"value": "ENTERPRISE_PLUS", "label": "Enterprise Plus — Performance-critical workloads"},
             ]},
        ]},
        {"label": "Choose preset", "fields": [
            {"name": "__preset__", "label": "Edition preset", "type": "radio",
             "default": "sandbox", "options": [
                {"value": "production",  "label": "Production — High availability"},
                {"value": "development", "label": "Development — Single zone"},
                {"value": "sandbox",     "label": "Sandbox — Smallest size, for evaluation"},
             ]},
        ]},
        {"label": "Machine configuration", "fields": [
            {"name": "tier", "label": "Machine tier", "type": "select",
             "default": "db-f1-micro", "options": [
                {"value": "db-f1-micro",      "label": "db-f1-micro (shared, 0.6 GB)"},
                {"value": "db-g1-small",      "label": "db-g1-small (shared, 1.7 GB)"},
                {"value": "db-custom-1-3840", "label": "db-custom-1-3840 (1 vCPU, 3.75 GB)"},
                {"value": "db-custom-2-7680", "label": "db-custom-2-7680 (2 vCPU, 7.5 GB)"},
                {"value": "db-custom-4-15360","label": "db-custom-4-15360 (4 vCPU, 15 GB)"},
             ]},
        ]},
    ],
)


# ============================================================================
# Pub/Sub — Create topic
# ============================================================================
_PUBSUB_WIZARD = _basic_wizard(
    name_field=_name("Topic ID", "my-topic"),
    name_default="my-topic", region_or_zone=None,
    extra_basic_fields=[
        {"name": "__addDefaultSub__", "label": "Add a default subscription",
         "type": "boolean", "default": True,
         "help": "Auto-create '{topic}-sub' with default settings (recommended)."},
    ],
    sections=[
        {"label": "Encryption", "fields": [
            {"name": "__encryption__", "label": "Encryption", "type": "radio",
             "default": "google-managed", "options": [
                {"value": "google-managed",  "label": "Google-managed encryption key (no configuration required)"},
                {"value": "customer-managed","label": "Customer-managed encryption key (CMEK)"},
             ]},
        ]},
        {"label": "Schema", "fields": [
            {"name": "__schemaName__", "label": "Use a schema", "default": "",
             "help": "Optional. Specify a schema name to enforce a structure on messages."},
        ]},
        {"label": "Message retention", "fields": [
            {"name": "messageRetentionDuration", "label": "Retain published messages (seconds)",
             "type": "number", "default": 604800,  # 7 days
             "validate": {"min": 600, "max": 2678400}},
        ]},
    ],
)


# ============================================================================
# Firestore — Create database
# ============================================================================
_FIRESTORE_WIZARD = _basic_wizard(
    name_field=_name("Database ID", "(default)",
                     r"^(\(default\)|[a-z][a-z0-9-]{3,62})$",
                     "(default) OR 4-63 chars, lowercase, digits, hyphens"),
    name_default="(default)", region_or_zone="region",
    extra_basic_fields=[
        {"name": "type", "label": "Database type", "type": "radio",
         "default": "FIRESTORE_NATIVE", "options": [
            {"value": "FIRESTORE_NATIVE",    "label": "Native mode — Realtime updates, mobile/web SDKs"},
            {"value": "DATASTORE_MODE",      "label": "Datastore mode — Server-side, App Engine-compatible"},
         ]},
        {"name": "concurrencyMode", "label": "Concurrency mode", "type": "radio",
         "default": "OPTIMISTIC", "options": [
            {"value": "OPTIMISTIC",  "label": "Optimistic — Better for high-contention workloads"},
            {"value": "PESSIMISTIC", "label": "Pessimistic — Lock acquired before transaction"},
         ]},
    ],
)


# ============================================================================
# Cloud Functions — Create function
# ============================================================================
_FUNCTIONS_WIZARD = _basic_wizard(
    name_field=_name("Function name", "my-function",
                     r"^[a-z][a-z0-9-]{0,62}$"),
    name_default="my-function", region_or_zone="region",
    extra_basic_fields=[
        {"name": "__environment__", "label": "Environment", "type": "radio",
         "default": "2nd gen", "options": [
            {"value": "2nd gen", "label": "2nd gen — Backed by Cloud Run; more features, longer timeouts"},
            {"value": "1st gen", "label": "1st gen — Legacy event-driven functions"},
         ]},
        {"name": "runtime", "label": "Runtime", "type": "select",
         "default": "python312", "options": [
            {"value": "python312",  "label": "Python 3.12"},
            {"value": "python311",  "label": "Python 3.11"},
            {"value": "nodejs20",   "label": "Node.js 20"},
            {"value": "nodejs18",   "label": "Node.js 18"},
            {"value": "go121",      "label": "Go 1.21"},
            {"value": "java21",     "label": "Java 21"},
            {"value": "dotnet8",    "label": ".NET 8"},
            {"value": "ruby32",     "label": "Ruby 3.2"},
         ]},
        {"name": "entryPoint", "label": "Entry point",
         "default": "hello_world",
         "help": "The name of your function within your code (must match what's exported)."},
    ],
    sections=[
        {"label": "Trigger", "fields": [
            {"name": "__triggerType__", "label": "Trigger type", "type": "select",
             "default": "https", "options": [
                {"value": "https",     "label": "HTTPS"},
                {"value": "pubsub",    "label": "Cloud Pub/Sub"},
                {"value": "storage",   "label": "Cloud Storage"},
                {"value": "firestore", "label": "Firestore"},
                {"value": "eventarc",  "label": "Eventarc"},
             ]},
            {"name": "__allowUnauth__", "label": "Allow unauthenticated invocations",
             "type": "boolean", "default": False,
             "ifEquals": {"__triggerType__": "https"},
             "help": "Check this if you intend to expose this function as a public endpoint."},
        ]},
        {"label": "Runtime, build, connections and security settings", "fields": [
            {"name": "memory", "label": "Memory allocated", "type": "select",
             "default": "256Mi", "options": [
                {"value": "128Mi",  "label": "128 MiB"},
                {"value": "256Mi",  "label": "256 MiB"},
                {"value": "512Mi",  "label": "512 MiB"},
                {"value": "1Gi",    "label": "1 GiB"},
                {"value": "2Gi",    "label": "2 GiB"},
                {"value": "4Gi",    "label": "4 GiB"},
                {"value": "8Gi",    "label": "8 GiB"},
             ]},
            {"name": "timeoutSeconds", "label": "Timeout (seconds)", "type": "number",
             "default": 60, "validate": {"min": 1, "max": 540}},
        ]},
    ],
)


# ============================================================================
# API Gateway — Create gateway
# ============================================================================
_APIGW_WIZARD = _basic_wizard(
    name_field=_name("Display name", "my-gateway"),
    name_default="my-gateway", region_or_zone="region",
    extra_basic_fields=[
        {"name": "apiConfig", "label": "API config",
         "default": "", "required": True,
         "help": "Reference an existing API config (OpenAPI 2.0/3.0 spec) by name."},
        {"name": "__serviceAccount__", "label": "Service account",
         "default": "", "required": True,
         "help": "Service account email used to invoke backend services."},
    ],
)


# ============================================================================
# VPC Network — Create VPC network
# ============================================================================
_VPC_WIZARD = _basic_wizard(
    name_field=_name("Name", "my-vpc"),
    name_default="my-vpc", region_or_zone=None,
    extra_basic_fields=[
        {"name": "__description__", "label": "Description", "default": ""},
        {"name": "__subnetCreationMode__", "label": "Subnet creation mode", "type": "radio",
         "default": "auto", "options": [
            {"value": "auto",   "label": "Automatic — One subnet per region, auto-assigned"},
            {"value": "custom", "label": "Custom — Define your own subnets and ranges"},
         ]},
    ],
    sections=[
        {"label": "Firewall rules", "fields": [
            {"name": "__help__", "type": "help",
             "value": "Default firewall rules are pre-populated; you can edit them after creation. To learn more, see VPC firewall rules."},
            {"name": "__addDefaultFirewalls__", "label": "Add default rules (allow-icmp, allow-internal, allow-ssh, allow-rdp)",
             "type": "boolean", "default": True},
        ]},
        {"label": "Dynamic routing mode", "fields": [
            {"name": "__routingMode__", "label": "Routing mode", "type": "radio",
             "default": "regional", "options": [
                {"value": "regional", "label": "Regional — Cloud Routers learn routes only in the region they're in"},
                {"value": "global",   "label": "Global — Cloud Routers learn routes from all regions"},
             ]},
        ]},
    ],
)


# ============================================================================
# IAM — Create service account
# ============================================================================
_IAM_WIZARD = _basic_wizard(
    name_field=_name("Service account name", "my-service-account",
                     r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$",
                     "6-30 chars, lowercase, digits, hyphens; start with letter, end alphanumeric"),
    name_default="my-service-account", region_or_zone=None,
    extra_basic_fields=[
        {"name": "displayName", "label": "Service account display name",
         "default": "My service account"},
        {"name": "description", "label": "Service account description",
         "default": "Describe what this service account does."},
    ],
    sections=[
        {"label": "Grant this service account access to project (optional)", "fields": [
            {"name": "__role__", "label": "Role", "type": "select",
             "default": "roles/viewer", "options": [
                {"value": "roles/viewer",       "label": "Viewer"},
                {"value": "roles/editor",       "label": "Editor"},
                {"value": "roles/owner",        "label": "Owner"},
                {"value": "roles/storage.admin","label": "Storage Admin"},
                {"value": "roles/compute.admin","label": "Compute Admin"},
                {"value": "roles/cloudsql.admin","label": "Cloud SQL Admin"},
                {"value": "roles/pubsub.publisher","label": "Pub/Sub Publisher"},
                {"value": "roles/iam.serviceAccountUser","label": "Service Account User"},
             ]},
        ]},
        {"label": "Grant users access to this service account (optional)", "fields": [
            {"name": "__userAccess__", "label": "Service account users role",
             "default": "",
             "help": "Email of a user or group who can use this service account."},
            {"name": "__adminAccess__", "label": "Service account admins role",
             "default": "",
             "help": "Email of a user or group who can administer this service account."},
        ]},
    ],
)


# ============================================================================
# Public registry — keyed by catalog `key`
# ============================================================================
# ============================================================================
# Eventarc — Create trigger (most common Eventarc action)
# ============================================================================
_EVENTARC_WIZARD = _basic_wizard(
    name_field=_name("Trigger name", "my-trigger"),
    name_default="my-trigger", region_or_zone="region",
    extra_basic_fields=[
        {"name": "event_provider", "label": "Event provider", "type": "select",
         "default": "google.cloud.pubsub.topic.v1.messagePublished", "options": [
            {"value": "google.cloud.pubsub.topic.v1.messagePublished", "label": "Cloud Pub/Sub"},
            {"value": "google.cloud.storage.object.v1.finalized",      "label": "Cloud Storage"},
            {"value": "google.cloud.firestore.document.v1.created",    "label": "Firestore"},
            {"value": "google.cloud.bigquery.v2.job.completed",        "label": "BigQuery"},
            {"value": "google.cloud.scheduler.v1.jobs.execute",        "label": "Cloud Scheduler"},
         ]},
        {"name": "destination_type", "label": "Event destination", "type": "radio",
         "default": "cloud_run", "options": [
            {"value": "cloud_run",  "label": "Cloud Run service"},
            {"value": "cloud_function","label":"Cloud Functions function"},
            {"value": "workflows",  "label": "Workflows workflow"},
            {"value": "gke",        "label": "GKE service"},
         ]},
        {"name": "destination", "label": "Destination resource name", "required": True,
         "default": "my-service"},
    ],
    sections=[
        {"label": "Service account", "fields": [
            {"name": "service_account", "label": "Service account email",
             "default": "compute-default@cloudlearn.iam.gserviceaccount.com",
             "help": "Service account used by Eventarc to invoke the destination."},
        ]},
    ],
)


# ============================================================================
# Secret Manager — Create secret
# ============================================================================
_SECRETMANAGER_WIZARD = _basic_wizard(
    name_field=_name("Name", "my-secret",
                     r"^[A-Za-z0-9_-]{1,255}$",
                     "1-255 chars; letters, digits, underscore, hyphen"),
    name_default="my-secret", region_or_zone=None,
    extra_basic_fields=[
        {"name": "secret_value", "label": "Secret value", "type": "password",
         "required": True,
         "validate": {"regex": r"^.{1,65535}$", "message": "1-65535 chars"}},
    ],
    sections=[
        {"label": "Replication policy", "fields": [
            {"name": "replication", "label": "Replication policy", "type": "radio",
             "default": "automatic", "options": [
                {"value": "automatic",    "label": "Automatic — Google chooses locations (recommended)"},
                {"value": "user-managed", "label": "User-managed — you pick specific regions"},
             ]},
            {"name": "regions", "label": "Regions (comma-separated)",
             "default": "us-central1,us-east1",
             "ifEquals": {"replication": "user-managed"}},
        ]},
        {"label": "Encryption", "fields": [
            {"name": "__encryption__", "label": "Encryption", "type": "radio",
             "default": "google-managed", "options": [
                {"value": "google-managed",   "label": "Google-managed encryption key (recommended)"},
                {"value": "customer-managed", "label": "Customer-managed encryption key (CMEK)"},
             ]},
        ]},
        {"label": "Rotation", "fields": [
            {"name": "__rotationEnabled__", "label": "Set rotation period",
             "type": "boolean", "default": False},
            {"name": "rotation_period", "label": "Rotation period (days)", "type": "number",
             "default": 90, "validate": {"min": 1, "max": 365},
             "ifEquals": {"__rotationEnabled__": True}},
        ]},
    ],
)


# ============================================================================
# Cloud Tasks — Create queue
# ============================================================================
def _loc_select():
    r = _region()
    return {**r, "name": "location"}


_CLOUDTASKS_WIZARD = _basic_wizard(
    name_field=_name("Queue name", "my-queue", r"^[A-Za-z0-9-]{1,100}$",
                     "1-100 chars; letters, digits and hyphens"),
    name_default="my-queue", region_or_zone=None,
    extra_basic_fields=[
        {"name": "project", "label": "Project", "default": "my-project", "required": True,
         "validate": {"regex": r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$", "message": "6-30 chars, lowercase, digits, hyphens"}},
        _loc_select(),
    ],
    sections=[
        {"label": "Rate limits", "fields": [
            {"name": "max_dispatches_per_second", "label": "Max dispatches per second", "type": "number",
             "default": 500, "validate": {"min": 0, "max": 500}},
            {"name": "max_concurrent_dispatches", "label": "Max concurrent dispatches", "type": "number",
             "default": 1000, "validate": {"min": 1, "max": 5000}},
        ]},
        {"label": "Retry parameters", "fields": [
            {"name": "max_attempts", "label": "Max attempts", "type": "number",
             "default": 100, "validate": {"min": -1, "max": 1000}},
        ]},
    ],
)


# ============================================================================
# Cloud KMS — Create key
# ============================================================================
_KMS_WIZARD = _basic_wizard(
    name_field=_name("Key name", "my-key",
                     r"^[a-zA-Z0-9_-]{1,63}$",
                     "1-63 chars"),
    name_default="my-key", region_or_zone="region",
    extra_basic_fields=[
        {"name": "keyring", "label": "Key ring", "required": True,
         "default": "my-keyring",
         "help": "Existing or new key ring (scoped to the region)."},
        {"name": "protection_level", "label": "Protection level", "type": "radio",
         "default": "SOFTWARE", "options": [
            {"value": "SOFTWARE", "label": "Software — Standard symmetric/asymmetric keys"},
            {"value": "HSM",      "label": "HSM — FIPS 140-2 Level 3 hardware-backed"},
            {"value": "EXTERNAL", "label": "External — EKM connection to third-party HSM"},
         ]},
        {"name": "purpose", "label": "Purpose", "type": "select",
         "default": "ENCRYPT_DECRYPT", "options": [
            {"value": "ENCRYPT_DECRYPT",        "label": "Symmetric encrypt/decrypt"},
            {"value": "ASYMMETRIC_DECRYPT",     "label": "Asymmetric decrypt"},
            {"value": "ASYMMETRIC_SIGN",        "label": "Asymmetric sign"},
            {"value": "MAC",                    "label": "MAC (HMAC)"},
         ]},
        {"name": "algorithm", "label": "Algorithm", "type": "select",
         "default": "GOOGLE_SYMMETRIC_ENCRYPTION", "options": [
            {"value": "GOOGLE_SYMMETRIC_ENCRYPTION","label": "GOOGLE_SYMMETRIC_ENCRYPTION"},
            {"value": "AES_256_GCM",                "label": "AES-256-GCM"},
            {"value": "RSA_DECRYPT_OAEP_3072_SHA256","label":"RSA-3072 OAEP SHA256"},
            {"value": "RSA_SIGN_PSS_3072_SHA256",   "label": "RSA-3072 PSS SHA256"},
            {"value": "EC_SIGN_P256_SHA256",        "label": "EC P-256 SHA256"},
            {"value": "HMAC_SHA256",                "label": "HMAC SHA256"},
         ]},
    ],
    sections=[
        {"label": "Rotation", "fields": [
            {"name": "rotation_period", "label": "Rotation period (days)", "type": "number",
             "default": 90, "validate": {"min": 1, "max": 365},
             "help": "Symmetric keys can rotate automatically. Asymmetric keys require manual rotation."},
        ]},
    ],
)


WIZARDS: dict[str, dict] = {
    "compute":       _COMPUTE_WIZARD,
    "storage":       _STORAGE_WIZARD,
    "cloudsql":      _CLOUDSQL_WIZARD,
    "pubsub":        _PUBSUB_WIZARD,
    "firestore":     _FIRESTORE_WIZARD,
    "functions":     _FUNCTIONS_WIZARD,
    "apigateway":    _APIGW_WIZARD,
    "vpc":           _VPC_WIZARD,
    "iam":           _IAM_WIZARD,
    "eventarc":      _EVENTARC_WIZARD,
    "secretmanager": _SECRETMANAGER_WIZARD,
    "cloudtasks": _CLOUDTASKS_WIZARD,
    "kms":           _KMS_WIZARD,
}
