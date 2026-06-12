"""Azure-portal-style multi-step create wizards for every simulated service.

Each entry under WIZARDS is keyed by the catalog ``key`` (vm, storage, sql,
servicebus, cosmos, functionapp, apim, vnet, rbac). The schema mirrors how the
real Azure portal organizes "Create" blades: a sequence of tabs (Basics →
service-specific → Tags → Review + create), each tab grouped into sections,
each section holding typed fields.

The frontend (static/azure-console.html) renders the wizard when ``svc.wizard``
is present and falls back to the flat ``createFields`` form otherwise. This
keeps SDK consumers + automation paths backward-compatible (they POST the same
ARM body) while giving humans a portal-faithful UX.

Field shape::

    {
      "name":      <dotted ARM body path, e.g. "properties.hardwareProfile.vmSize">,
      "label":     <user-visible label>,
      "type":      "text" (default) | "select" | "number" | "password"
                   | "boolean" | "radio" | "vmSize" | "cidr"
                   | "tagsEditor" | "subnetEditor" | "info" | "help",
      "default":   <initial value; __UUID__ token expands to a fresh UUID>,
      "required":  <bool>,
      "options":   <[ {value,label,help?} ... ] for select/radio>,
      "validate":  {"regex": "...", "message": "...", "min": ..., "max": ...},
      "help":      <inline help text under the field>,
      "ifEquals":  {<other-field-name>: <value>}  # conditional show
    }

Field type ``info`` is a read-only display (used for Subscription / RG).
Field type ``help`` renders a banner string with no input.
Field type ``tagsEditor`` produces ``{key:value}`` and writes to ``tags``.
Field type ``subnetEditor`` produces a list of ``{name, properties:{addressPrefix}}``
records and writes to ``properties.subnets``.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Shared field-builder helpers — keep schemas terse.
# ---------------------------------------------------------------------------

def _name(label: str, default: str, regex: str = r"^[a-z][a-z0-9-]{2,62}$",
          msg: str = "3-63 chars, lowercase letters/digits/hyphens, start with a letter") -> dict:
    return {"name": "name", "label": label, "default": default, "required": True,
            "validate": {"regex": regex, "message": msg}}


def _location() -> dict:
    return {"name": "__loc__", "label": "Region", "type": "select", "required": True,
            "default": "eastus", "options": [
                {"value": "eastus", "label": "East US"},
                {"value": "eastus2", "label": "East US 2"},
                {"value": "westus", "label": "West US"},
                {"value": "westus2", "label": "West US 2"},
                {"value": "westus3", "label": "West US 3"},
                {"value": "centralus", "label": "Central US"},
                {"value": "northeurope", "label": "North Europe"},
                {"value": "westeurope", "label": "West Europe"},
                {"value": "uksouth", "label": "UK South"},
                {"value": "southeastasia", "label": "Southeast Asia"},
                {"value": "japaneast", "label": "Japan East"},
                {"value": "australiaeast", "label": "Australia East"},
            ]}


def _project_section() -> dict:
    """The "Project details" section that every Create blade opens with."""
    return {"label": "Project details", "fields": [
        {"name": "__sub__", "label": "Subscription", "type": "info",
         "help": "Active subscription (set globally in the console header)."},
        {"name": "__rg__", "label": "Resource group", "type": "info",
         "help": "Target resource group (set globally in the console header)."},
    ]}


def _tags_tab() -> dict:
    return {"key": "tags", "label": "Tags", "sections": [
        {"label": "Tags", "fields": [
            {"name": "__help__", "type": "help",
             "value": "Tags are name/value pairs that help you organize and identify resources for billing, automation, and access control."},
            {"name": "tags", "type": "tagsEditor", "default": {}},
        ]},
    ]}


def _review_tab() -> dict:
    return {"key": "review", "label": "Review + create", "auto": True,
            "sections": [{"label": "Summary", "fields": []}]}


# ---------------------------------------------------------------------------
# VM — closest portal parity (8 tabs: Basics, Disks, Networking, Management,
# Monitoring, Advanced, Tags, Review+create).
# ---------------------------------------------------------------------------
_VM_WIZARD = {
    "tabs": [
        {"key": "basics", "label": "Basics", "sections": [
            _project_section(),
            {"label": "Instance details", "fields": [
                _name("Virtual machine name", "vm-demo"),
                _location(),
                {"name": "__availability__", "label": "Availability options", "type": "select",
                 "default": "none", "options": [
                    {"value": "none", "label": "No infrastructure redundancy required"},
                    {"value": "az", "label": "Availability zone"},
                    {"value": "vmss", "label": "Virtual machine scale set"},
                 ]},
                {"name": "__security__", "label": "Security type", "type": "select",
                 "default": "standard", "options": [
                    {"value": "standard", "label": "Standard"},
                    {"value": "trusted", "label": "Trusted launch virtual machines"},
                    {"value": "confidential", "label": "Confidential virtual machines"},
                 ]},
                {"name": "__image__", "label": "Image", "type": "select",
                 "default": "ubuntu-2204", "options": [
                    {"value": "ubuntu-2204", "label": "Ubuntu Server 22.04 LTS - x64 Gen2"},
                    {"value": "ubuntu-2404", "label": "Ubuntu Server 24.04 LTS - x64 Gen2"},
                    {"value": "rhel-9", "label": "Red Hat Enterprise Linux 9 - x64 Gen2"},
                    {"value": "windows-2022", "label": "Windows Server 2022 Datacenter: Azure Edition - x64 Gen2"},
                 ]},
                {"name": "properties.hardwareProfile.vmSize", "label": "Size",
                 "type": "vmSize", "default": "Standard_B1s", "required": True,
                 "help": "VM size from the simulator's Azure catalog — host-clamped on actual launch."},
            ]},
            {"label": "Administrator account", "fields": [
                {"name": "__authType__", "label": "Authentication type", "type": "radio",
                 "default": "ssh", "options": [
                    {"value": "ssh", "label": "SSH public key"},
                    {"value": "password", "label": "Password"},
                 ]},
                {"name": "properties.osProfile.adminUsername", "label": "Username",
                 "default": "azureuser", "required": True,
                 "validate": {"regex": r"^[a-z][a-z0-9_-]{0,31}$",
                              "message": "lowercase, ≤32 chars, start with a letter"}},
                {"name": "__sshKey__", "label": "SSH public key source", "type": "select",
                 "default": "generate", "ifEquals": {"__authType__": "ssh"}, "options": [
                    {"value": "generate", "label": "Generate new key pair"},
                    {"value": "existing", "label": "Use existing public key"},
                 ]},
                {"name": "properties.osProfile.adminPassword", "label": "Password",
                 "type": "password", "ifEquals": {"__authType__": "password"},
                 "validate": {"regex": r"^.{12,72}$",
                              "message": "12-72 characters; mix upper/lower/digit/special"}},
            ]},
            {"label": "Inbound port rules", "fields": [
                {"name": "__publicInbound__", "label": "Public inbound ports", "type": "radio",
                 "default": "selected", "options": [
                    {"value": "none", "label": "None"},
                    {"value": "selected", "label": "Allow selected ports"},
                 ]},
                {"name": "__inboundPorts__", "label": "Select inbound ports", "type": "select",
                 "default": "ssh", "ifEquals": {"__publicInbound__": "selected"}, "options": [
                    {"value": "ssh", "label": "SSH (22)"},
                    {"value": "http", "label": "HTTP (80)"},
                    {"value": "https", "label": "HTTPS (443)"},
                    {"value": "rdp", "label": "RDP (3389)"},
                 ]},
            ]},
        ]},
        {"key": "disks", "label": "Disks", "sections": [
            {"label": "VM disk encryption", "fields": [
                {"name": "__diskEncryption__", "label": "Encryption type", "type": "select",
                 "default": "msmk", "options": [
                    {"value": "msmk", "label": "(Default) Encryption at-rest with a platform-managed key"},
                    {"value": "cmk", "label": "Encryption at-rest with a customer-managed key"},
                    {"value": "double", "label": "Double encryption with platform-managed and customer-managed keys"},
                 ]},
            ]},
            {"label": "OS disk", "fields": [
                {"name": "__osDiskType__", "label": "OS disk type", "type": "select",
                 "default": "Premium_LRS", "options": [
                    {"value": "Premium_LRS", "label": "Premium SSD (locally-redundant)"},
                    {"value": "StandardSSD_LRS", "label": "Standard SSD (locally-redundant)"},
                    {"value": "Standard_LRS", "label": "Standard HDD (locally-redundant)"},
                    {"value": "Premium_ZRS", "label": "Premium SSD (zone-redundant)"},
                 ]},
                {"name": "__osDiskDelete__", "label": "Delete with VM",
                 "type": "boolean", "default": True},
            ]},
        ]},
        {"key": "networking", "label": "Networking", "sections": [
            {"label": "Network interface", "fields": [
                {"name": "__vnet__", "label": "Virtual network", "type": "text",
                 "default": "vnet-demo",
                 "help": "Pick existing or simulate a new VNet (creates a record under Microsoft.Network/virtualNetworks)."},
                {"name": "__subnet__", "label": "Subnet", "type": "text", "default": "default (10.0.0.0/24)"},
                {"name": "__publicIp__", "label": "Public IP", "type": "radio",
                 "default": "new", "options": [
                    {"value": "new", "label": "(new) — auto-assign"},
                    {"value": "none", "label": "None"},
                 ]},
                {"name": "__nsg__", "label": "NIC network security group", "type": "radio",
                 "default": "basic", "options": [
                    {"value": "none", "label": "None"},
                    {"value": "basic", "label": "Basic"},
                    {"value": "advanced", "label": "Advanced"},
                 ]},
            ]},
            {"label": "Load balancing", "fields": [
                {"name": "__loadBalancing__", "label": "Place this virtual machine behind an existing load balancing solution?",
                 "type": "boolean", "default": False},
            ]},
        ]},
        {"key": "management", "label": "Management", "sections": [
            {"label": "Identity", "fields": [
                {"name": "__managedIdentity__", "label": "Enable system-assigned managed identity",
                 "type": "boolean", "default": False},
            ]},
            {"label": "Microsoft Entra ID", "fields": [
                {"name": "__entraLogin__", "label": "Login with Microsoft Entra ID",
                 "type": "boolean", "default": False},
            ]},
            {"label": "Auto-shutdown", "fields": [
                {"name": "__autoShutdown__", "label": "Enable auto-shutdown",
                 "type": "boolean", "default": False},
                {"name": "__shutdownTime__", "label": "Shutdown time (HH:MM)", "default": "19:00",
                 "ifEquals": {"__autoShutdown__": True}},
            ]},
            {"label": "Backup", "fields": [
                {"name": "__enableBackup__", "label": "Enable backup",
                 "type": "boolean", "default": False},
            ]},
        ]},
        {"key": "monitoring", "label": "Monitoring", "sections": [
            {"label": "Diagnostics", "fields": [
                {"name": "__bootDiag__", "label": "Boot diagnostics", "type": "radio",
                 "default": "managed", "options": [
                    {"value": "managed", "label": "Enable with managed storage account (recommended)"},
                    {"value": "custom", "label": "Enable with custom storage account"},
                    {"value": "disable", "label": "Disable"},
                 ]},
            ]},
            {"label": "Application Insights", "fields": [
                {"name": "__appInsights__", "label": "Enable Application Insights",
                 "type": "boolean", "default": False},
            ]},
        ]},
        {"key": "advanced", "label": "Advanced", "sections": [
            {"label": "Extensions", "fields": [
                {"name": "__help__", "type": "help",
                 "value": "Extensions provide post-deployment configuration and automation. (Not configurable here yet.)"},
            ]},
            {"label": "Custom data", "fields": [
                {"name": "__customData__", "label": "Custom data (cloud-init)", "type": "text",
                 "default": "", "help": "Base-64 encoded cloud-init script — leave blank to skip."},
            ]},
        ]},
        _tags_tab(),
        _review_tab(),
    ],
    # When the wizard submits, these synthetic field values are translated
    # to real ARM body paths. The frontend evaluates this map and rewrites the
    # outbound body so the dispatcher gets clean canonical paths.
    "synthetic_map": {
        "__image__": {
            "ubuntu-2204": {"properties.storageProfile.imageReference": {
                "publisher": "Canonical", "offer": "0001-com-ubuntu-server-jammy",
                "sku": "22_04-lts", "version": "latest"}},
            "ubuntu-2404": {"properties.storageProfile.imageReference": {
                "publisher": "Canonical", "offer": "0001-com-ubuntu-server-noble",
                "sku": "24_04-lts", "version": "latest"}},
            "rhel-9": {"properties.storageProfile.imageReference": {
                "publisher": "RedHat", "offer": "RHEL", "sku": "9-lvm", "version": "latest"}},
            "windows-2022": {"properties.storageProfile.imageReference": {
                "publisher": "MicrosoftWindowsServer", "offer": "WindowsServer",
                "sku": "2022-datacenter-azure-edition", "version": "latest"}},
        },
        "__osDiskType__": {"*": {"properties.storageProfile.osDisk.managedDisk.storageAccountType": "$value",
                                  "properties.storageProfile.osDisk.createOption": "FromImage"}},
    },
}


# ---------------------------------------------------------------------------
# Storage account — 7 tabs.
# ---------------------------------------------------------------------------
_STORAGE_WIZARD = {
    "tabs": [
        {"key": "basics", "label": "Basics", "sections": [
            _project_section(),
            {"label": "Instance details", "fields": [
                _name("Storage account name", "stcloudlearn",
                      r"^[a-z0-9]{3,24}$",
                      "3-24 chars, lowercase letters and digits only"),
                _location(),
                {"name": "__performance__", "label": "Performance", "type": "radio",
                 "default": "standard", "options": [
                    {"value": "standard", "label": "Standard — recommended for most scenarios"},
                    {"value": "premium", "label": "Premium — recommended for low-latency scenarios"},
                 ]},
                {"name": "sku.name", "label": "Redundancy", "type": "select",
                 "default": "Standard_LRS", "options": [
                    {"value": "Standard_LRS", "label": "Locally-redundant storage (LRS)"},
                    {"value": "Standard_ZRS", "label": "Zone-redundant storage (ZRS)"},
                    {"value": "Standard_GRS", "label": "Geo-redundant storage (GRS)"},
                    {"value": "Standard_RAGRS", "label": "Read-access geo-redundant storage (RA-GRS)"},
                    {"value": "Standard_GZRS", "label": "Geo-zone-redundant storage (GZRS)"},
                    {"value": "Standard_RAGZRS", "label": "Read-access geo-zone-redundant storage (RA-GZRS)"},
                 ]},
            ]},
        ]},
        {"key": "advanced", "label": "Advanced", "sections": [
            {"label": "Security", "fields": [
                {"name": "properties.supportsHttpsTrafficOnly", "label": "Require secure transfer for REST API operations",
                 "type": "boolean", "default": True},
                {"name": "properties.allowBlobPublicAccess", "label": "Allow enabling anonymous access on individual containers",
                 "type": "boolean", "default": False},
                {"name": "properties.allowSharedKeyAccess", "label": "Enable storage account key access",
                 "type": "boolean", "default": True},
                {"name": "properties.defaultToOAuthAuthentication", "label": "Default to Microsoft Entra authorization in the Azure portal",
                 "type": "boolean", "default": False},
                {"name": "properties.minimumTlsVersion", "label": "Minimum TLS version", "type": "select",
                 "default": "TLS1_2", "options": [
                    {"value": "TLS1_0", "label": "Version 1.0"},
                    {"value": "TLS1_1", "label": "Version 1.1"},
                    {"value": "TLS1_2", "label": "Version 1.2"},
                 ]},
            ]},
            {"label": "Data Lake Storage Gen2", "fields": [
                {"name": "properties.isHnsEnabled", "label": "Enable hierarchical namespace",
                 "type": "boolean", "default": False},
            ]},
            {"label": "Blob storage", "fields": [
                {"name": "properties.accessTier", "label": "Access tier", "type": "radio",
                 "default": "Hot", "options": [
                    {"value": "Hot", "label": "Hot — optimized for frequently accessed data"},
                    {"value": "Cool", "label": "Cool — optimized for infrequently accessed data"},
                 ]},
            ]},
        ]},
        {"key": "networking", "label": "Networking", "sections": [
            {"label": "Network connectivity", "fields": [
                {"name": "__networkAccess__", "label": "Public network access", "type": "radio",
                 "default": "allAll", "options": [
                    {"value": "allAll", "label": "Enable public access from all networks"},
                    {"value": "selected", "label": "Enable public access from selected virtual networks and IP addresses"},
                    {"value": "disabled", "label": "Disable public access and use private access"},
                 ]},
            ]},
            {"label": "Network routing", "fields": [
                {"name": "__routing__", "label": "Routing preference", "type": "radio",
                 "default": "microsoft", "options": [
                    {"value": "microsoft", "label": "Microsoft network routing"},
                    {"value": "internet", "label": "Internet routing"},
                 ]},
            ]},
        ]},
        {"key": "dataprotection", "label": "Data protection", "sections": [
            {"label": "Recovery", "fields": [
                {"name": "__softDeleteBlobs__", "label": "Enable soft delete for blobs",
                 "type": "boolean", "default": True},
                {"name": "__softDeleteBlobsDays__", "label": "Days to retain deleted blobs",
                 "type": "number", "default": 7, "validate": {"min": 1, "max": 365},
                 "ifEquals": {"__softDeleteBlobs__": True}},
                {"name": "__softDeleteContainers__", "label": "Enable soft delete for containers",
                 "type": "boolean", "default": True},
                {"name": "__softDeleteShares__", "label": "Enable soft delete for file shares",
                 "type": "boolean", "default": True},
            ]},
            {"label": "Tracking", "fields": [
                {"name": "__versioning__", "label": "Enable versioning for blobs",
                 "type": "boolean", "default": False},
                {"name": "__changeFeed__", "label": "Enable blob change feed",
                 "type": "boolean", "default": False},
            ]},
        ]},
        {"key": "encryption", "label": "Encryption", "sections": [
            {"label": "Encryption", "fields": [
                {"name": "__encryptionType__", "label": "Encryption type", "type": "radio",
                 "default": "msmk", "options": [
                    {"value": "msmk", "label": "Microsoft-managed keys (MMK)"},
                    {"value": "cmk", "label": "Customer-managed keys (CMK)"},
                 ]},
                {"name": "__infraEncryption__", "label": "Enable infrastructure encryption",
                 "type": "boolean", "default": False},
            ]},
        ]},
        _tags_tab(),
        _review_tab(),
    ],
    "synthetic_map": {},
}


# ---------------------------------------------------------------------------
# SQL server — 5 tabs.
# ---------------------------------------------------------------------------
_SQL_WIZARD = {
    "tabs": [
        {"key": "basics", "label": "Basics", "sections": [
            _project_section(),
            {"label": "Server details", "fields": [
                _name("Server name", "sql-cloudlearn",
                      r"^[a-z][a-z0-9-]{2,62}$",
                      "3-63 chars, lowercase, start with a letter"),
                _location(),
            ]},
            {"label": "Authentication", "fields": [
                {"name": "__authMethod__", "label": "Authentication method", "type": "radio",
                 "default": "sql", "options": [
                    {"value": "sql", "label": "Use SQL authentication"},
                    {"value": "entra", "label": "Use Microsoft Entra-only authentication"},
                    {"value": "both", "label": "Use both SQL and Microsoft Entra authentication"},
                 ]},
                {"name": "properties.administratorLogin", "label": "Server admin login",
                 "default": "sqladmin", "required": True,
                 "ifEquals": {"__authMethod__": "sql"},
                 "validate": {"regex": r"^[A-Za-z][A-Za-z0-9_]{0,127}$",
                              "message": "letters/digits/underscore, start with a letter"}},
                {"name": "properties.administratorLoginPassword", "label": "Password",
                 "type": "password", "ifEquals": {"__authMethod__": "sql"},
                 "validate": {"regex": r"^.{12,128}$",
                              "message": "12-128 characters; mix upper/lower/digit/special"}},
            ]},
        ]},
        {"key": "networking", "label": "Networking", "sections": [
            {"label": "Network connectivity", "fields": [
                {"name": "__connectivity__", "label": "Connectivity method", "type": "radio",
                 "default": "public", "options": [
                    {"value": "none", "label": "No access"},
                    {"value": "public", "label": "Public endpoint"},
                    {"value": "private", "label": "Private endpoint"},
                 ]},
            ]},
            {"label": "Firewall rules", "fields": [
                {"name": "__allowAzure__", "label": "Allow Azure services and resources to access this server",
                 "type": "boolean", "default": True, "ifEquals": {"__connectivity__": "public"}},
                {"name": "__addClientIp__", "label": "Add current client IP address",
                 "type": "boolean", "default": True, "ifEquals": {"__connectivity__": "public"}},
            ]},
        ]},
        {"key": "security", "label": "Security", "sections": [
            {"label": "Microsoft Defender for SQL", "fields": [
                {"name": "__defender__", "label": "Enable Microsoft Defender for SQL",
                 "type": "radio", "default": "noEnable", "options": [
                    {"value": "noEnable", "label": "Not now"},
                    {"value": "enable", "label": "Start free trial"},
                 ]},
            ]},
            {"label": "Ledger", "fields": [
                {"name": "__ledger__", "label": "Enable for all future databases (preview)",
                 "type": "boolean", "default": False},
            ]},
        ]},
        {"key": "additional", "label": "Additional settings", "sections": [
            {"label": "Data source", "fields": [
                {"name": "__dataSource__", "label": "Use existing data", "type": "radio",
                 "default": "none", "options": [
                    {"value": "none", "label": "None"},
                    {"value": "backup", "label": "Backup"},
                    {"value": "sample", "label": "Sample (AdventureWorksLT)"},
                 ]},
            ]},
            {"label": "Database collation", "fields": [
                {"name": "__collation__", "label": "Collation", "type": "text",
                 "default": "SQL_Latin1_General_CP1_CI_AS"},
            ]},
            {"label": "Maintenance window", "fields": [
                {"name": "__maintenance__", "label": "Maintenance window", "type": "select",
                 "default": "system", "options": [
                    {"value": "system", "label": "System default (5pm to 8am)"},
                    {"value": "weekend", "label": "Weekend (10pm Friday to 7am Monday)"},
                    {"value": "weekday", "label": "Weekday (10pm to 6am)"},
                 ]},
            ]},
        ]},
        _tags_tab(),
        _review_tab(),
    ],
    "synthetic_map": {},
}


# ---------------------------------------------------------------------------
# Service Bus — 3 tabs.
# ---------------------------------------------------------------------------
_SERVICEBUS_WIZARD = {
    "tabs": [
        {"key": "basics", "label": "Basics", "sections": [
            _project_section(),
            {"label": "Instance details", "fields": [
                _name("Namespace name", "sb-cloudlearn",
                      r"^[A-Za-z][A-Za-z0-9-]{4,49}[A-Za-z0-9]$",
                      "6-50 chars, start with a letter, end alphanumeric, no '-sb' suffix"),
                _location(),
                {"name": "sku.name", "label": "Pricing tier", "type": "select",
                 "default": "Standard", "options": [
                    {"value": "Basic", "label": "Basic — message size 256 KB, queues only"},
                    {"value": "Standard", "label": "Standard — message size 256 KB, queues + topics"},
                    {"value": "Premium", "label": "Premium — message size 100 MB, dedicated resources"},
                 ]},
            ]},
        ]},
        {"key": "advanced", "label": "Advanced", "sections": [
            {"label": "Geo-replication", "fields": [
                {"name": "__geoReplication__", "label": "Enable geo-replication (Premium only)",
                 "type": "boolean", "default": False,
                 "ifEquals": {"sku.name": "Premium"}},
            ]},
            {"label": "Minimum TLS version", "fields": [
                {"name": "properties.minimumTlsVersion", "label": "Minimum TLS version",
                 "type": "select", "default": "1.2", "options": [
                    {"value": "1.0", "label": "1.0"},
                    {"value": "1.1", "label": "1.1"},
                    {"value": "1.2", "label": "1.2"},
                 ]},
            ]},
            {"label": "Local authentication", "fields": [
                {"name": "properties.disableLocalAuth", "label": "Disable local authentication",
                 "type": "boolean", "default": False,
                 "help": "Disabling local auth requires SAS keys to be replaced with Microsoft Entra-based authentication."},
            ]},
        ]},
        _tags_tab(),
        _review_tab(),
    ],
    "synthetic_map": {},
}


# ---------------------------------------------------------------------------
# Cosmos DB — 6 tabs.
# ---------------------------------------------------------------------------
_COSMOS_WIZARD = {
    "tabs": [
        {"key": "basics", "label": "Basics", "sections": [
            _project_section(),
            {"label": "Instance details", "fields": [
                _name("Account name", "cosmos-cloudlearn",
                      r"^[a-z0-9][a-z0-9-]{1,42}[a-z0-9]$",
                      "3-44 chars, lowercase, digits, hyphens; start+end alphanumeric"),
                _location(),
                {"name": "kind", "label": "API", "type": "select",
                 "default": "GlobalDocumentDB", "options": [
                    {"value": "GlobalDocumentDB", "label": "Azure Cosmos DB for NoSQL"},
                    {"value": "MongoDB", "label": "Azure Cosmos DB for MongoDB"},
                    {"value": "Cassandra", "label": "Azure Cosmos DB for Apache Cassandra"},
                    {"value": "GlobalRest", "label": "Azure Cosmos DB for Table"},
                    {"value": "GraphDB", "label": "Azure Cosmos DB for Apache Gremlin"},
                 ]},
                {"name": "__capacityMode__", "label": "Capacity mode", "type": "radio",
                 "default": "provisioned", "options": [
                    {"value": "provisioned", "label": "Provisioned throughput"},
                    {"value": "serverless", "label": "Serverless"},
                 ]},
                {"name": "__freeTier__", "label": "Apply Free Tier discount",
                 "type": "radio", "default": "no",
                 "ifEquals": {"__capacityMode__": "provisioned"}, "options": [
                    {"value": "yes", "label": "Apply"},
                    {"value": "no", "label": "Do Not Apply"},
                 ]},
            ]},
        ]},
        {"key": "globaldist", "label": "Global distribution", "sections": [
            {"label": "Geo-redundancy", "fields": [
                {"name": "__geoRedundancy__", "label": "Geo-Redundancy", "type": "radio",
                 "default": "disable", "options": [
                    {"value": "enable", "label": "Enable"},
                    {"value": "disable", "label": "Disable"},
                 ]},
            ]},
            {"label": "Multi-region writes", "fields": [
                {"name": "__multiWrite__", "label": "Multi-region Writes", "type": "radio",
                 "default": "disable", "options": [
                    {"value": "enable", "label": "Enable"},
                    {"value": "disable", "label": "Disable"},
                 ]},
            ]},
            {"label": "Availability zones", "fields": [
                {"name": "__azs__", "label": "Availability Zones", "type": "radio",
                 "default": "disable", "options": [
                    {"value": "enable", "label": "Enable"},
                    {"value": "disable", "label": "Disable"},
                 ]},
            ]},
        ]},
        {"key": "networking", "label": "Networking", "sections": [
            {"label": "Network connectivity", "fields": [
                {"name": "__connectivity__", "label": "Connectivity method", "type": "radio",
                 "default": "publicAll", "options": [
                    {"value": "publicAll", "label": "All networks"},
                    {"value": "publicSelected", "label": "Public endpoint (selected networks)"},
                    {"value": "private", "label": "Private endpoint"},
                 ]},
            ]},
        ]},
        {"key": "backup", "label": "Backup policy", "sections": [
            {"label": "Backup policy", "fields": [
                {"name": "__backupType__", "label": "Backup policy type", "type": "radio",
                 "default": "periodic", "options": [
                    {"value": "periodic", "label": "Periodic"},
                    {"value": "continuous7", "label": "Continuous (7 days)"},
                    {"value": "continuous30", "label": "Continuous (30 days)"},
                 ]},
                {"name": "__backupInterval__", "label": "Backup interval (minutes)",
                 "type": "number", "default": 240, "validate": {"min": 60, "max": 1440},
                 "ifEquals": {"__backupType__": "periodic"}},
                {"name": "__backupRetention__", "label": "Backup retention (hours)",
                 "type": "number", "default": 8, "validate": {"min": 8, "max": 720},
                 "ifEquals": {"__backupType__": "periodic"}},
                {"name": "__backupStorage__", "label": "Backup storage redundancy", "type": "select",
                 "default": "Geo", "options": [
                    {"value": "Geo", "label": "Geo-redundant backup storage"},
                    {"value": "Zone", "label": "Zone-redundant backup storage"},
                    {"value": "Local", "label": "Locally-redundant backup storage"},
                 ]},
            ]},
        ]},
        {"key": "encryption", "label": "Encryption", "sections": [
            {"label": "Data encryption", "fields": [
                {"name": "__encryptionKey__", "label": "Data encryption", "type": "radio",
                 "default": "msmk", "options": [
                    {"value": "msmk", "label": "Service-managed key"},
                    {"value": "cmk", "label": "Customer-managed key"},
                 ]},
            ]},
        ]},
        _tags_tab(),
        _review_tab(),
    ],
    "synthetic_map": {},
}


# ---------------------------------------------------------------------------
# Function app — 6 tabs.
# ---------------------------------------------------------------------------
_FUNCTIONAPP_WIZARD = {
    "tabs": [
        {"key": "basics", "label": "Basics", "sections": [
            _project_section(),
            {"label": "Instance details", "fields": [
                _name("Function app name", "fn-cloudlearn",
                      r"^[a-z][a-z0-9-]{1,58}[a-z0-9]$",
                      "2-60 chars, lowercase, digits, hyphens"),
                {"name": "__deploymentModel__", "label": "Do you want to deploy code or container image?",
                 "type": "radio", "default": "code", "options": [
                    {"value": "code", "label": "Code"},
                    {"value": "container", "label": "Container Image"},
                 ]},
                {"name": "properties.runtime", "label": "Runtime stack", "type": "select",
                 "default": "python", "options": [
                    {"value": "node", "label": "Node.js"},
                    {"value": "python", "label": "Python"},
                    {"value": "dotnet-isolated", "label": ".NET (isolated worker model)"},
                    {"value": "java", "label": "Java"},
                    {"value": "powershell", "label": "PowerShell Core"},
                    {"value": "custom", "label": "Custom Handler"},
                 ]},
                {"name": "__runtimeVersion__", "label": "Version", "type": "select",
                 "default": "3.11", "options": [
                    {"value": "3.11", "label": "3.11"},
                    {"value": "3.12", "label": "3.12"},
                    {"value": "3.10", "label": "3.10"},
                 ]},
                _location(),
                {"name": "__osType__", "label": "Operating System", "type": "radio",
                 "default": "linux", "options": [
                    {"value": "linux", "label": "Linux"},
                    {"value": "windows", "label": "Windows"},
                 ]},
            ]},
            {"label": "Hosting plan", "fields": [
                {"name": "__hostingPlan__", "label": "Hosting plan", "type": "radio",
                 "default": "consumption", "options": [
                    {"value": "consumption", "label": "Consumption (Serverless)"},
                    {"value": "flex", "label": "Flex Consumption"},
                    {"value": "premium", "label": "Functions Premium"},
                    {"value": "appservice", "label": "App Service plan"},
                 ]},
            ]},
        ]},
        {"key": "storage", "label": "Storage", "sections": [
            {"label": "Storage", "fields": [
                {"name": "__storageAccount__", "label": "Storage account", "type": "text",
                 "default": "stfunclearn",
                 "help": "Required for runtime state. Will be created as Microsoft.Storage/storageAccounts."},
            ]},
        ]},
        {"key": "networking", "label": "Networking", "sections": [
            {"label": "Network injection", "fields": [
                {"name": "__networkInjection__", "label": "Enable network injection",
                 "type": "boolean", "default": False},
            ]},
            {"label": "Network access", "fields": [
                {"name": "__networkAccess__", "label": "Enable public access",
                 "type": "boolean", "default": True},
            ]},
        ]},
        {"key": "monitoring", "label": "Monitoring", "sections": [
            {"label": "Application Insights", "fields": [
                {"name": "__appInsights__", "label": "Enable Application Insights",
                 "type": "boolean", "default": True},
            ]},
        ]},
        {"key": "deployment", "label": "Deployment", "sections": [
            {"label": "GitHub Actions", "fields": [
                {"name": "__ghActions__", "label": "Continuous deployment",
                 "type": "boolean", "default": False},
                {"name": "__ghRepo__", "label": "GitHub repository", "type": "text",
                 "default": "", "ifEquals": {"__ghActions__": True}},
            ]},
        ]},
        _tags_tab(),
        _review_tab(),
    ],
    "synthetic_map": {},
}


# ---------------------------------------------------------------------------
# API Management — 4 tabs.
# ---------------------------------------------------------------------------
_APIM_WIZARD = {
    "tabs": [
        {"key": "basics", "label": "Basics", "sections": [
            _project_section(),
            {"label": "Instance details", "fields": [
                _name("Resource name", "apim-cloudlearn",
                      r"^[a-z][a-z0-9-]{0,48}[a-z0-9]$",
                      "1-50 chars, lowercase, start with a letter"),
                _location(),
                {"name": "properties.publisherEmail", "label": "Organization email",
                 "default": "admin@vyomi.cloud", "required": True,
                 "validate": {"regex": r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
                              "message": "valid email address"}},
                {"name": "properties.publisherName", "label": "Organization name",
                 "default": "Vyomi", "required": True},
                {"name": "sku.name", "label": "Pricing tier", "type": "select",
                 "default": "Developer", "options": [
                    {"value": "Consumption", "label": "Consumption — pay-per-call, serverless"},
                    {"value": "Developer", "label": "Developer — non-production"},
                    {"value": "Basic", "label": "Basic — entry-level production"},
                    {"value": "BasicV2", "label": "Basic v2 — entry-level production (v2)"},
                    {"value": "Standard", "label": "Standard — medium-volume production"},
                    {"value": "StandardV2", "label": "Standard v2 — medium-volume production (v2)"},
                    {"value": "Premium", "label": "Premium — high-scale + VNet"},
                 ]},
            ]},
        ]},
        {"key": "monitoring", "label": "Monitoring", "sections": [
            {"label": "Application Insights", "fields": [
                {"name": "__appInsights__", "label": "Enable Application Insights",
                 "type": "boolean", "default": False},
            ]},
        ]},
        _tags_tab(),
        _review_tab(),
    ],
    "synthetic_map": {},
}


# ---------------------------------------------------------------------------
# Virtual network — 4 tabs.
# ---------------------------------------------------------------------------
_VNET_WIZARD = {
    "tabs": [
        {"key": "basics", "label": "Basics", "sections": [
            _project_section(),
            {"label": "Instance details", "fields": [
                _name("Virtual network name", "vnet-cloudlearn",
                      r"^[A-Za-z][A-Za-z0-9._-]{1,63}$",
                      "2-64 chars, letters/digits/dot/underscore/hyphen, start with a letter"),
                _location(),
            ]},
        ]},
        {"key": "security", "label": "Security", "sections": [
            {"label": "Azure Bastion", "fields": [
                {"name": "__bastion__", "label": "Enable Azure Bastion",
                 "type": "boolean", "default": False},
            ]},
            {"label": "Azure Firewall", "fields": [
                {"name": "__firewall__", "label": "Enable Azure Firewall",
                 "type": "boolean", "default": False},
            ]},
            {"label": "Azure DDoS Network Protection", "fields": [
                {"name": "__ddos__", "label": "Enable DDoS Network Protection",
                 "type": "boolean", "default": False},
            ]},
        ]},
        {"key": "ips", "label": "IP addresses", "sections": [
            {"label": "Address space", "fields": [
                {"name": "properties.addressSpace.addressPrefixes.0", "label": "IPv4 address space",
                 "type": "cidr", "default": "10.0.0.0/16", "required": True,
                 "validate": {"regex": r"^\d{1,3}(\.\d{1,3}){3}/\d{1,2}$",
                              "message": "valid CIDR notation, e.g. 10.0.0.0/16"}},
            ]},
            {"label": "Subnets", "fields": [
                {"name": "properties.subnets", "type": "subnetEditor",
                 "default": [{"name": "default", "properties": {"addressPrefix": "10.0.0.0/24"}}]},
            ]},
        ]},
        _tags_tab(),
        _review_tab(),
    ],
    "synthetic_map": {},
}


# ---------------------------------------------------------------------------
# Event Grid topic — 4 tabs.
# ---------------------------------------------------------------------------
_EVENTGRID_WIZARD = {
    "tabs": [
        {"key": "basics", "label": "Basics", "sections": [
            _project_section(),
            {"label": "Topic details", "fields": [
                _name("Topic name", "egtopic-cloudlearn",
                      r"^[a-zA-Z][a-zA-Z0-9-]{2,49}[a-zA-Z0-9]$",
                      "3-50 chars, alphanumerics + hyphens"),
                _location(),
                {"name": "properties.inputSchema", "label": "Input schema", "type": "select",
                 "default": "EventGridSchema", "options": [
                    {"value": "EventGridSchema", "label": "Event Grid Schema"},
                    {"value": "CloudEventSchemaV1_0", "label": "Cloud Event Schema v1.0"},
                    {"value": "CustomEventSchema", "label": "Custom Event Schema"},
                 ]},
            ]},
        ]},
        {"key": "networking", "label": "Networking", "sections": [
            {"label": "Network access", "fields": [
                {"name": "properties.publicNetworkAccess", "label": "Public network access",
                 "type": "radio", "default": "Enabled", "options": [
                    {"value": "Enabled", "label": "All networks"},
                    {"value": "SecuredByPerimeter", "label": "Selected networks (Network Security Perimeter)"},
                    {"value": "Disabled", "label": "Disable public access"},
                 ]},
                {"name": "properties.minimumTlsVersionAllowed", "label": "Minimum TLS version",
                 "type": "select", "default": "1.2", "options": [
                    {"value": "1.0", "label": "1.0"},
                    {"value": "1.1", "label": "1.1"},
                    {"value": "1.2", "label": "1.2"},
                 ]},
            ]},
            {"label": "Local authentication", "fields": [
                {"name": "properties.disableLocalAuth", "label": "Disable local authentication",
                 "type": "boolean", "default": False,
                 "help": "Disabling local auth requires Entra-based authentication for publishing events."},
            ]},
        ]},
        _tags_tab(),
        _review_tab(),
    ],
    "synthetic_map": {},
}


# ---------------------------------------------------------------------------
# Key Vault — 5 tabs.
# ---------------------------------------------------------------------------
_KEYVAULT_WIZARD = {
    "tabs": [
        {"key": "basics", "label": "Basics", "sections": [
            _project_section(),
            {"label": "Instance details", "fields": [
                _name("Key vault name", "kv-cloudlearn",
                      r"^[a-zA-Z][a-zA-Z0-9-]{1,22}[a-zA-Z0-9]$",
                      "3-24 chars, alphanumerics + hyphens, start with a letter"),
                _location(),
                {"name": "properties.sku.name", "label": "Pricing tier", "type": "select",
                 "default": "standard", "options": [
                    {"value": "standard", "label": "Standard"},
                    {"value": "premium", "label": "Premium (HSM-protected keys)"},
                 ]},
            ]},
            {"label": "Recovery options", "fields": [
                {"name": "properties.enableSoftDelete", "label": "Enable soft-delete",
                 "type": "boolean", "default": True,
                 "help": "Required by Azure; cannot be disabled on new vaults."},
                {"name": "properties.softDeleteRetentionInDays", "label": "Soft-delete retention (days)",
                 "type": "number", "default": 90, "validate": {"min": 7, "max": 90}},
                {"name": "properties.enablePurgeProtection", "label": "Enable purge protection",
                 "type": "boolean", "default": False,
                 "help": "Once enabled, cannot be disabled. Soft-deleted vaults can't be purged until retention expires."},
            ]},
        ]},
        {"key": "accessconfig", "label": "Access configuration", "sections": [
            {"label": "Permission model", "fields": [
                {"name": "properties.enableRbacAuthorization", "label": "Permission model",
                 "type": "radio", "default": False, "options": [
                    {"value": False, "label": "Vault access policy (legacy)"},
                    {"value": True,  "label": "Azure role-based access control (recommended)"},
                 ]},
            ]},
            {"label": "Resource access", "fields": [
                {"name": "properties.enabledForDeployment", "label": "Azure Virtual Machines for deployment",
                 "type": "boolean", "default": False,
                 "help": "Allow Azure VMs to retrieve secrets stored as certificates."},
                {"name": "properties.enabledForDiskEncryption", "label": "Azure Disk Encryption for volume encryption",
                 "type": "boolean", "default": False},
                {"name": "properties.enabledForTemplateDeployment", "label": "Azure Resource Manager for template deployment",
                 "type": "boolean", "default": False},
            ]},
        ]},
        {"key": "networking", "label": "Networking", "sections": [
            {"label": "Network connectivity", "fields": [
                {"name": "__networkAccess__", "label": "Connectivity method", "type": "radio",
                 "default": "publicAll", "options": [
                    {"value": "publicAll", "label": "Enable public access from all networks"},
                    {"value": "publicSelected", "label": "Enable public access from specific virtual networks and IP addresses"},
                    {"value": "private", "label": "Disable public access"},
                 ]},
            ]},
        ]},
        _tags_tab(),
        _review_tab(),
    ],
    "synthetic_map": {},
}


# ---------------------------------------------------------------------------
# RBAC role assignment — Add role assignment is its own flow in portal.
# 3 tabs (Role + Members + Review). Tags tab is N/A for role assignments.
# ---------------------------------------------------------------------------
_RBAC_WIZARD = {
    "tabs": [
        {"key": "role", "label": "Role", "sections": [
            {"label": "Role", "fields": [
                {"name": "properties.roleDefinitionId", "label": "Role", "type": "select",
                 "default": "Contributor", "required": True, "options": [
                    {"value": "Owner", "label": "Owner — full access including assigning roles"},
                    {"value": "Contributor", "label": "Contributor — full access except role assignment"},
                    {"value": "Reader", "label": "Reader — view-only access"},
                    {"value": "UserAccessAdministrator", "label": "User Access Administrator — manage user access"},
                    {"value": "StorageBlobDataOwner", "label": "Storage Blob Data Owner"},
                    {"value": "StorageBlobDataContributor", "label": "Storage Blob Data Contributor"},
                    {"value": "StorageBlobDataReader", "label": "Storage Blob Data Reader"},
                    {"value": "VirtualMachineContributor", "label": "Virtual Machine Contributor"},
                    {"value": "NetworkContributor", "label": "Network Contributor"},
                    {"value": "KeyVaultSecretsUser", "label": "Key Vault Secrets User"},
                 ]},
            ]},
        ]},
        {"key": "members", "label": "Members", "sections": [
            {"label": "Assign access to", "fields": [
                {"name": "properties.principalType", "label": "Principal type", "type": "radio",
                 "default": "User", "options": [
                    {"value": "User", "label": "User, group, or service principal"},
                    {"value": "ManagedIdentity", "label": "Managed identity"},
                 ]},
                {"name": "properties.principalId", "label": "Principal (object id or email)",
                 "default": "user@cloudlearn.dev", "required": True},
            ]},
            {"label": "Assignment name", "fields": [
                {"name": "name", "label": "Assignment name (GUID)", "default": "__UUID__", "required": True},
            ]},
        ]},
        {"key": "conditions", "label": "Conditions", "sections": [
            {"label": "Conditions (preview)", "fields": [
                {"name": "__help__", "type": "help",
                 "value": "Add a condition to constrain the role assignment. (Not configurable here yet.)"},
            ]},
        ]},
        _review_tab(),
    ],
    "synthetic_map": {},
}


# ---------------------------------------------------------------------------
# Export — keyed by catalog ``key`` (so azure_services.py can merge in place).
# ---------------------------------------------------------------------------
WIZARDS: dict[str, dict] = {
    "vm": _VM_WIZARD,
    "storage": _STORAGE_WIZARD,
    "sql": _SQL_WIZARD,
    "servicebus": _SERVICEBUS_WIZARD,
    "cosmos": _COSMOS_WIZARD,
    "functionapp": _FUNCTIONAPP_WIZARD,
    "apim": _APIM_WIZARD,
    "vnet": _VNET_WIZARD,
    "keyvault": _KEYVAULT_WIZARD,
    "eventgrid": _EVENTGRID_WIZARD,
    "rbac": _RBAC_WIZARD,
}
