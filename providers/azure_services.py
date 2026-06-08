"""Azure Resource Manager (ARM) control-plane simulator.

Azure's REST surface is uniform: every resource is addressed by a canonical id
``/subscriptions/{sub}/resourceGroups/{rg}/providers/{ns}/{type}/{name}`` and
manipulated with PUT (upsert) / GET / DELETE / LIST. So instead of bespoke
handlers per service we expose ONE generic dispatcher that parses any ARM URL
and CRUDs a flat in-memory store keyed by the lower-cased resource id. This
covers all 9 first-class services plus arbitrary nested children (SQL
databases, Service Bus queues, VNet subnets, Cosmos SQL databases) with no
extra code.

The 9-service ``RESOURCE_CATALOG`` is the single source of truth shared by this
API, the Swagger split, and the Azure portal-style console.
"""
from __future__ import annotations

import time
import uuid
from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, Response

DEFAULT_SUBSCRIPTION = "00000000-0000-0000-0000-cloudlearn01"
DEFAULT_RG = "cloudlearn-rg"
DEFAULT_LOCATION = "eastus"

# resource-id (lower-cased) -> stored record {id, name, type, location, tags, sku, kind, properties, _created}
_state: dict[str, dict] = {}

# Azure-AsyncOperation store: opId -> {status, startTime, endTime, resourceId, method}
# Real Azure SDKs (and Terraform azurerm) treat top-level PUT/DELETE as
# long-running: the response carries an `Azure-AsyncOperation`/`Location` header
# pointing at an operation-status URL the client polls until terminal. We
# resolve immediately (status "Succeeded") so the poller completes in one round
# trip while still exercising the real LRO code path.
_operations: dict[str, dict] = {}


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S.0000000Z", time.gmtime())


def _public_base(request: Request | None) -> str:
    if request is None:
        return "http://localhost:9000"
    host = request.headers.get("host") or (request.url.netloc if request.url else "") or "localhost:9000"
    scheme = request.headers.get("x-forwarded-proto") or (request.url.scheme if request.url else "http") or "http"
    return f"{scheme}://{host}"


# --- 9-service catalog (single source of truth) ---------------------------
# Each entry drives default property synthesis, the console grids/forms and the
# Swagger example paths. `endpoints` maps a property path to a host suffix that
# is rendered against the live simulator origin (so metadata points at the sim,
# not *.azure.com — consistent with the GCP "metadata = simulator IP" rule).
RESOURCE_CATALOG: list[dict] = [
    {
        "key": "vm", "label": "Virtual Machines", "icon": "computer",
        "namespace": "Microsoft.Compute", "type": "virtualMachines",
        "api_version": "2023-09-01", "scope": "rg",
        "columns": [["name", "Name"], ["location", "Location"],
                    ["properties.hardwareProfile.vmSize", "Size"],
                    ["properties.provisioningState", "Status"]],
        "create_fields": [
            {"name": "name", "label": "Virtual machine name", "default": "vm-demo"},
            {"name": "properties.hardwareProfile.vmSize", "label": "Size", "default": "Standard_B1s"},
            {"name": "properties.osProfile.computerName", "label": "Computer name", "default": "vm-demo"},
        ],
        "defaults": {
            "properties": {
                "hardwareProfile": {"vmSize": "Standard_B1s"},
                "storageProfile": {"imageReference": {"publisher": "Canonical", "offer": "0001-com-ubuntu-server-jammy", "sku": "22_04-lts", "version": "latest"}},
                "osProfile": {"computerName": "vm-demo", "adminUsername": "azureuser"},
                "provisioningState": "Succeeded",
                "vmId": "__UUID__",
            },
        },
    },
    {
        "key": "storage", "label": "Storage accounts", "icon": "storage",
        "namespace": "Microsoft.Storage", "type": "storageAccounts",
        "api_version": "2023-01-01", "scope": "rg",
        "columns": [["name", "Name"], ["location", "Location"],
                    ["sku.name", "SKU"], ["kind", "Kind"],
                    ["properties.provisioningState", "Status"]],
        "create_fields": [
            {"name": "name", "label": "Storage account name", "default": "stcloudlearn"},
            {"name": "sku.name", "label": "Performance/redundancy", "default": "Standard_LRS"},
            {"name": "kind", "label": "Kind", "default": "StorageV2"},
        ],
        "defaults": {
            "sku": {"name": "Standard_LRS", "tier": "Standard"}, "kind": "StorageV2",
            "properties": {"provisioningState": "Succeeded", "accessTier": "Hot"},
        },
        "endpoints": {"properties.primaryEndpoints.blob": "/azure-data/blob/__NAME__/",
                      "properties.primaryEndpoints.queue": "/azure-data/queue/__NAME__/",
                      "properties.primaryEndpoints.table": "/azure-data/table/__NAME__/"},
    },
    {
        "key": "sql", "label": "SQL servers", "icon": "database",
        "namespace": "Microsoft.Sql", "type": "servers",
        "api_version": "2023-05-01-preview", "scope": "rg",
        "children": [{"type": "databases", "label": "Databases", "icon": "database"}],
        "columns": [["name", "Name"], ["location", "Location"],
                    ["properties.administratorLogin", "Admin"],
                    ["properties.state", "Status"]],
        "create_fields": [
            {"name": "name", "label": "Server name", "default": "sql-cloudlearn"},
            {"name": "properties.administratorLogin", "label": "Admin login", "default": "sqladmin"},
            {"name": "properties.version", "label": "Version", "default": "12.0"},
        ],
        "defaults": {
            "properties": {"administratorLogin": "sqladmin", "version": "12.0", "state": "Ready"},
        },
        "endpoints": {"properties.fullyQualifiedDomainName": "/azure-data/sql/__NAME__"},
    },
    {
        "key": "servicebus", "label": "Service Bus", "icon": "queue",
        "namespace": "Microsoft.ServiceBus", "type": "namespaces",
        "api_version": "2022-10-01-preview", "scope": "rg",
        "notes": "CloudLearn Service Bus supports REST messaging protocol. AMQP (Advanced Message Queuing Protocol) is not supported — use HTTP REST endpoints for send/receive operations.",
        "children": [{"type": "queues", "label": "Queues", "icon": "queue"},
                     {"type": "topics", "label": "Topics", "icon": "campaign"}],
        "columns": [["name", "Name"], ["location", "Location"],
                    ["sku.name", "Tier"], ["properties.provisioningState", "Status"]],
        "create_fields": [
            {"name": "name", "label": "Namespace name", "default": "sb-cloudlearn"},
            {"name": "sku.name", "label": "Pricing tier", "default": "Standard"},
        ],
        "defaults": {
            "sku": {"name": "Standard", "tier": "Standard"},
            "properties": {
                "provisioningState": "Succeeded",
                "status": "Active",
                "serviceBusEndpoint": "http://localhost:9000/azure-data/servicebus/__NAME__",
                "messagingProtocol": "REST (AMQP not supported in simulator)",
            },
        },
        "endpoints": {"properties.serviceBusEndpoint": "/azure-data/servicebus/__NAME__/"},
    },
    {
        "key": "cosmos", "label": "Cosmos DB", "icon": "hub",
        "namespace": "Microsoft.DocumentDB", "type": "databaseAccounts",
        "api_version": "2024-05-15", "scope": "rg",
        "children": [{"type": "sqlDatabases", "label": "SQL databases", "icon": "database"}],
        "columns": [["name", "Name"], ["location", "Location"],
                    ["kind", "Kind"], ["properties.provisioningState", "Status"]],
        "create_fields": [
            {"name": "name", "label": "Account name", "default": "cosmos-cloudlearn"},
            {"name": "kind", "label": "API", "default": "GlobalDocumentDB"},
        ],
        "defaults": {
            "kind": "GlobalDocumentDB",
            "properties": {"provisioningState": "Succeeded", "databaseAccountOfferType": "Standard",
                           "consistencyPolicy": {"defaultConsistencyLevel": "Session"}},
        },
        "endpoints": {"properties.documentEndpoint": "/azure-data/cosmos/__NAME__/"},
    },
    {
        "key": "functionapp", "label": "Function apps", "icon": "bolt",
        "namespace": "Microsoft.Web", "type": "sites",
        "api_version": "2023-12-01", "scope": "rg",
        "columns": [["name", "Name"], ["location", "Location"],
                    ["kind", "Kind"], ["properties.state", "Status"]],
        "create_fields": [
            {"name": "name", "label": "Function app name", "default": "fn-cloudlearn"},
            {"name": "properties.runtime", "label": "Runtime", "default": "python"},
        ],
        "defaults": {
            "kind": "functionapp",
            "properties": {"state": "Running", "runtime": "python", "enabled": True},
        },
        "endpoints": {"properties.defaultHostName": "/azure-data/functions/__NAME__"},
    },
    {
        "key": "apim", "label": "API Management", "icon": "api",
        "namespace": "Microsoft.ApiManagement", "type": "service",
        "api_version": "2023-05-01-preview", "scope": "rg",
        "children": [
            {"type": "apis", "label": "APIs", "icon": "api"},
            {"type": "products", "label": "Products", "icon": "inventory_2"},
            {"type": "subscriptions", "label": "Subscriptions", "icon": "subscriptions"},
        ],
        "columns": [["name", "Name"], ["location", "Location"],
                    ["sku.name", "Tier"], ["properties.provisioningState", "Status"]],
        "create_fields": [
            {"name": "name", "label": "Service name", "default": "apim-cloudlearn"},
            {"name": "sku.name", "label": "Tier", "default": "Developer"},
            {"name": "properties.publisherEmail", "label": "Publisher email", "default": "admin@cloudlearn.dev"},
        ],
        "defaults": {
            "sku": {"name": "Developer", "capacity": 1},
            "properties": {"provisioningState": "Succeeded", "publisherEmail": "admin@cloudlearn.dev",
                           "publisherName": "CloudLearn"},
        },
        "endpoints": {"properties.gatewayUrl": "/azure-data/apim/__NAME__"},
    },
    {
        "key": "vnet", "label": "Virtual networks", "icon": "lan",
        "namespace": "Microsoft.Network", "type": "virtualNetworks",
        "api_version": "2023-11-01", "scope": "rg",
        "children": [{"type": "subnets", "label": "Subnets", "icon": "lan"}],
        "columns": [["name", "Name"], ["location", "Location"],
                    ["properties.addressSpace.addressPrefixes.0", "Address space"],
                    ["properties.provisioningState", "Status"]],
        "create_fields": [
            {"name": "name", "label": "Virtual network name", "default": "vnet-cloudlearn"},
            {"name": "properties.addressSpace.addressPrefixes.0", "label": "Address space (CIDR)", "default": "10.0.0.0/16"},
        ],
        "defaults": {
            "properties": {"provisioningState": "Succeeded",
                           "addressSpace": {"addressPrefixes": ["10.0.0.0/16"]}, "subnets": []},
        },
    },
    {
        "key": "nsg",
        "label": "Network Security Group",
        "icon": "security",
        "namespace": "Microsoft.Network",
        "type": "networkSecurityGroups",
        "api_version": "2023-11-01",
        "scope": "rg",
        "columns": [
            ["name", "Name"],
            ["location", "Location"],
            ["properties.provisioningState", "Status"],
        ],
        "create_fields": [
            {"name": "name", "label": "Name", "type": "text", "required": True},
            {"name": "location", "label": "Location", "type": "text", "default": "eastus"},
        ],
        "defaults": {
            "properties": {
                "provisioningState": "Succeeded",
                "securityRules": [],
            }
        },
        "children": [
            {
                "type": "securityRules",
                "key": "security_rule",
                "label": "Security Rule",
                "columns": [
                    ["name", "Name"],
                    ["properties.priority", "Priority"],
                    ["properties.direction", "Direction"],
                    ["properties.access", "Access"],
                    ["properties.protocol", "Protocol"],
                    ["properties.destinationPortRange", "Port"],
                ],
                "create_fields": [
                    {"name": "name", "label": "Name", "type": "text", "required": True},
                    {"name": "properties.priority", "label": "Priority", "type": "number", "default": 100},
                    {"name": "properties.direction", "label": "Direction", "type": "select", "options": ["Inbound", "Outbound"], "default": "Inbound"},
                    {"name": "properties.access", "label": "Access", "type": "select", "options": ["Allow", "Deny"], "default": "Allow"},
                    {"name": "properties.protocol", "label": "Protocol", "type": "select", "options": ["Tcp", "Udp", "Icmp", "*"], "default": "*"},
                    {"name": "properties.sourceAddressPrefix", "label": "Source", "type": "text", "default": "*"},
                    {"name": "properties.destinationAddressPrefix", "label": "Destination", "type": "text", "default": "*"},
                    {"name": "properties.sourcePortRange", "label": "Source Port", "type": "text", "default": "*"},
                    {"name": "properties.destinationPortRange", "label": "Destination Port", "type": "text", "default": "*"},
                ],
                "defaults": {
                    "properties": {
                        "provisioningState": "Succeeded",
                        "priority": 100,
                        "direction": "Inbound",
                        "access": "Allow",
                        "protocol": "*",
                        "sourceAddressPrefix": "*",
                        "destinationAddressPrefix": "*",
                        "sourcePortRange": "*",
                        "destinationPortRange": "*",
                    }
                }
            }
        ],
    },
    {
        "key": "eventgrid", "label": "Event Grid topics", "icon": "hub",
        "namespace": "Microsoft.EventGrid", "type": "topics",
        "api_version": "2024-06-01-preview", "scope": "rg",
        "children": [{"type": "eventSubscriptions", "label": "Event subscriptions", "icon": "subscriptions"}],
        "columns": [["name", "Name"], ["location", "Location"],
                    ["properties.inputSchema", "Input schema"],
                    ["properties.publicNetworkAccess", "Network access"],
                    ["properties.provisioningState", "Status"]],
        "create_fields": [
            {"name": "name", "label": "Topic name", "default": "egtopic-cloudlearn"},
            {"name": "properties.inputSchema", "label": "Input schema", "default": "EventGridSchema"},
        ],
        "defaults": {
            "properties": {
                "inputSchema": "EventGridSchema",
                "publicNetworkAccess": "Enabled",
                "minimumTlsVersionAllowed": "1.2",
                "disableLocalAuth": False,
                "provisioningState": "Succeeded",
            },
        },
        "endpoints": {"properties.endpoint": "/azure-data/eventgrid/__NAME__/api/events"},
    },
    {
        "key": "keyvault", "label": "Key vaults", "icon": "vpn_key",
        "namespace": "Microsoft.KeyVault", "type": "vaults",
        "api_version": "2023-07-01", "scope": "rg",
        "children": [{"type": "secrets", "label": "Secrets", "icon": "key"},
                     {"type": "keys", "label": "Keys", "icon": "lock"}],
        "columns": [["name", "Name"], ["location", "Location"],
                    ["properties.sku.name", "Pricing tier"],
                    ["properties.provisioningState", "Status"]],
        "create_fields": [
            {"name": "name", "label": "Key vault name", "default": "kv-cloudlearn"},
            {"name": "properties.tenantId", "label": "Tenant ID",
             "default": "00000000-0000-0000-0000-000000000000"},
            {"name": "properties.sku.name", "label": "Pricing tier", "default": "standard"},
        ],
        "defaults": {
            "properties": {
                "tenantId": "00000000-0000-0000-0000-000000000000",
                "sku": {"family": "A", "name": "standard"},
                "accessPolicies": [],
                "enabledForDeployment": False,
                "enabledForDiskEncryption": False,
                "enabledForTemplateDeployment": False,
                "enableSoftDelete": True,
                "softDeleteRetentionInDays": 90,
                "enableRbacAuthorization": False,
                "enablePurgeProtection": False,
                "provisioningState": "Succeeded",
            },
        },
        "endpoints": {"properties.vaultUri": "/azure-data/keyvault/__NAME__/"},
    },
    {
        "key": "role_definition",
        "label": "Role Definition",
        "icon": "admin_panel_settings",
        "namespace": "Microsoft.Authorization",
        "type": "roleDefinitions",
        "api_version": "2022-04-01",
        "scope": "sub",
        "columns": [
            ["name", "Name"],
            ["properties.roleName", "Role Name"],
            ["properties.type", "Type"],
        ],
        "create_fields": [
            {"name": "properties.roleName", "label": "Role Name", "type": "text", "required": True},
            {"name": "properties.description", "label": "Description", "type": "text"},
            {"name": "properties.type", "label": "Type", "type": "select", "options": ["BuiltInRole", "CustomRole"], "default": "CustomRole"},
        ],
        "defaults": {
            "properties": {
                "type": "CustomRole",
                "permissions": [{"actions": ["*"], "notActions": []}],
                "assignableScopes": ["/"],
            }
        },
    },
    {
        "key": "rbac", "label": "Entra ID / RBAC", "icon": "admin_panel_settings",
        "namespace": "Microsoft.Authorization", "type": "roleAssignments",
        "api_version": "2022-04-01", "scope": "rg",
        "columns": [["name", "Assignment id"],
                    ["properties.principalId", "Principal"],
                    ["properties.roleDefinitionId", "Role"]],
        "create_fields": [
            {"name": "name", "label": "Assignment name (GUID)", "default": "__UUID__"},
            {"name": "properties.principalId", "label": "Principal (object id)", "default": "user@cloudlearn.dev"},
            {"name": "properties.roleDefinitionId", "label": "Role", "default": "Contributor"},
        ],
        "defaults": {
            "properties": {"principalType": "User", "scope": ""},
        },
    },
]

_BY_TYPE = {(c["namespace"].lower(), c["type"].lower()): c for c in RESOURCE_CATALOG}


# --- helpers ---------------------------------------------------------------
def _set_path(obj: dict, dotted: str, value: Any) -> None:
    """Set a value at a dotted path, creating dicts/lists as needed. Numeric
    segments index into a list (auto-extended)."""
    parts = dotted.split(".")
    cur = obj
    for i, p in enumerate(parts):
        last = i == len(parts) - 1
        nxt = parts[i + 1] if not last else None
        if p.isdigit():
            idx = int(p)
            if not isinstance(cur, list):
                return
            while len(cur) <= idx:
                cur.append({} if (nxt is not None and not nxt.isdigit()) else ([] if nxt is not None else None))
            if last:
                cur[idx] = value
            else:
                if not isinstance(cur[idx], (dict, list)):
                    cur[idx] = [] if nxt.isdigit() else {}
                cur = cur[idx]
        else:
            if last:
                cur[p] = value
            else:
                if not isinstance(cur.get(p), (dict, list)):
                    cur[p] = [] if (nxt and nxt.isdigit()) else {}
                cur = cur[p]


def _get_path(obj: Any, dotted: str) -> Any:
    cur = obj
    for p in dotted.split("."):
        if isinstance(cur, list) and p.isdigit():
            idx = int(p)
            cur = cur[idx] if idx < len(cur) else None
        elif isinstance(cur, dict):
            cur = cur.get(p)
        else:
            return None
        if cur is None:
            return None
    return cur


def _merge(base: dict, overlay: dict) -> dict:
    out = dict(base)
    for k, v in (overlay or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def _expand_tokens(obj: Any, name: str, base: str) -> Any:
    if isinstance(obj, str):
        return (obj.replace("__UUID__", str(uuid.uuid4()))
                   .replace("__NAME__", name)
                   .replace("__BASE__", base))
    if isinstance(obj, dict):
        return {k: _expand_tokens(v, name, base) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_expand_tokens(v, name, base) for v in obj]
    return obj


def _canonical_id(sub: str, rg: str | None, type_chain: list[str], names: list[str]) -> str:
    seg = [f"/subscriptions/{sub}"]
    if rg:
        seg.append(f"resourceGroups/{rg}")
    seg.append("providers")
    # interleave type/name
    ns = type_chain[0]
    seg.append(ns)
    rest_types = type_chain[1:]
    seg.append(rest_types[0])
    for i, nm in enumerate(names):
        seg.append(nm)
        if i + 1 < len(rest_types):
            seg.append(rest_types[i + 1])
    return "/".join(seg)


def _view(rec: dict) -> dict:
    # Return a copy without the internal bookkeeping keys.
    return {k: v for k, v in rec.items() if not k.startswith("_")}


# Map ARM resource type → CloudSim bundle key for non-compute services.
_ARM_TYPE_BUNDLE: dict[str, str] = {
    "microsoft.sql/servers": "azure_sql",
    "microsoft.sql/servers/databases": "azure_sql",
    "microsoft.storage/storageaccounts": "azure_storage",
    "microsoft.web/sites": "azure_functions",
    "microsoft.servicebus/namespaces": "azure_servicebus",
    "microsoft.documentdb/databaseaccounts": "azure_cosmos",
    "microsoft.apimanagement/service": "azure_apim",
    "microsoft.eventgrid/topics": "azure_eventgrid",
    "microsoft.network/virtualnetworks": "azure_vnet",
}


def _cloudsim_sync_arm_service(full_type: str, rid: str, leaf_name: str,
                               location: str, action: str = "upsert") -> None:
    """Sync non-compute ARM resources to CloudSim via the generic helper."""
    bundle_key = _ARM_TYPE_BUNDLE.get(full_type.lower())
    if not bundle_key:
        return
    try:
        import server as _srv
        resource = {"name": leaf_name, "location": location}
        service = bundle_key.replace("azure_", "")
        _srv._cloudsim_sync_service_resource(
            "azure", service, full_type, rid, resource, bundle_key, action=action, region=location,
        )
    except Exception:
        pass


# --- generic ARM dispatcher ------------------------------------------------
def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


def _record_usage(event: str, detail: dict | None = None) -> None:
    """Notify the platform of a control-plane mutation so the CloudSim resource
    graph + summary rebuild from the DB (same hook AWS/GCP handlers use). Never
    breaks the request."""
    try:
        from core.app_context import record_usage
        record_usage(event, detail or {})
    except Exception:
        pass


def _make_operation(resource_id: str, method: str) -> str:
    op_id = uuid.uuid4().hex
    now = _now()
    _operations[op_id] = {"id": op_id, "name": op_id, "status": "Succeeded",
                          "startTime": now, "endTime": now,
                          "resourceId": resource_id, "method": method}
    return op_id


def _lro_headers(base: str, op_id: str, api_version: str) -> dict:
    url = f"{base}/api/azure/operations/{op_id}?api-version={api_version}"
    return {"Azure-AsyncOperation": url, "Location": url, "Retry-After": "0"}


def _is_lro_type(namespace: str, type_chain: list[str]) -> bool:
    # Top-level resources are long-running, except RBAC role assignments
    # (synchronous in real Azure).
    return len(type_chain) == 2 and namespace.lower() != "microsoft.authorization"


async def handle_arm(request: Request, rest: str) -> JSONResponse:
    """Parse `/subscriptions/{rest}` and CRUD the in-memory ARM store."""
    base = _public_base(request)
    method = request.method.upper()
    segs = [s for s in rest.split("/") if s != ""]
    if not segs:
        return _error(400, "BadRequest", "Missing subscription id.")
    sub = segs[0]
    rest_segs = segs[1:]

    # GET /subscriptions/{sub}
    if not rest_segs:
        return JSONResponse({"id": f"/subscriptions/{sub}", "subscriptionId": sub,
                             "displayName": "CloudLearn Subscription", "state": "Enabled"})

    # Resource-group collection / item: /subscriptions/{sub}/resourcegroups[/{rg}]
    if rest_segs[0].lower() == "resourcegroups" and (len(rest_segs) == 1 or
                                                      (len(rest_segs) == 2)):
        if len(rest_segs) == 1:
            if method == "GET":
                return JSONResponse({"value": _list_resource_groups(sub)})
            return _error(405, "MethodNotAllowed", "Use PUT /resourcegroups/{name}.")
        rg = rest_segs[1]
        return _resource_group_item(method, sub, rg, await _safe_json(request))

    # Provider resources. Two scopes:
    #   subscription scope: /subscriptions/{sub}/providers/{ns}/{type}[/{name}...]
    #   RG scope:           /subscriptions/{sub}/resourceGroups/{rg}/providers/{ns}/{type}[/...]
    rg = None
    idx = 0
    if rest_segs[0].lower() == "resourcegroups":
        if len(rest_segs) < 2:
            return _error(400, "BadRequest", "Missing resource group name.")
        rg = rest_segs[1]
        idx = 2
    if idx >= len(rest_segs) or rest_segs[idx].lower() != "providers":
        return _error(400, "BadRequest", f"Unrecognized ARM path: /subscriptions/{rest}")
    after = rest_segs[idx + 1:]
    # Provider registration endpoints (some fluent SDKs probe these):
    #   GET  /subscriptions/{sub}/providers                  -> list providers
    #   GET  /subscriptions/{sub}/providers/{ns}             -> provider info
    #   POST /subscriptions/{sub}/providers/{ns}/register    -> register
    if len(after) == 0 and method == "GET":
        return JSONResponse({"value": [_provider_info(n) for n in sorted({c["namespace"] for c in RESOURCE_CATALOG})]})
    if len(after) == 1 and method == "GET":
        return JSONResponse(_provider_info(after[0]))
    if len(after) == 2 and after[1].lower() == "register" and method == "POST":
        return JSONResponse(_provider_info(after[0]))
    if len(after) < 2:
        return _error(400, "BadRequest", "Missing provider namespace/type.")
    namespace = after[0]
    # after = [ns, type, name?, childType?, childName?, ...]
    chain = after[1:]
    # Split into (type_chain, names): types at even positions, names at odd.
    type_chain = [namespace]
    names: list[str] = []
    for i, token in enumerate(chain):
        if i % 2 == 0:
            type_chain.append(token)
        else:
            names.append(token)
    is_collection = (len(chain) % 2 == 1)  # ends on a type → LIST

    top = _BY_TYPE.get((namespace.lower(), type_chain[1].lower()))
    if top is None:
        return _error(404, "ResourceTypeNotSupported",
                      f"Type '{namespace}/{type_chain[1]}' is not simulated. "
                      f"Supported: {', '.join(sorted(c['namespace']+'/'+c['type'] for c in RESOURCE_CATALOG))}.")

    # POST action verbs (listKeys, regenerateKey, listConnectionStrings, …):
    # the trailing type segment is the action, names[-1] the target resource.
    if method == "POST" and is_collection and len(type_chain) >= 3 and names:
        # Compute the parent resource's canonical id (drop the action segment)
        # so action handlers can locate the record they're operating on.
        parent_rid = _canonical_id(sub, rg, type_chain[:-1], names)
        return _arm_action(type_chain[-1].lower(), type_chain, names[-1], parent_rid)

    full_type = "/".join(type_chain)
    if is_collection:
        if method != "GET":
            return _error(405, "MethodNotAllowed", "Collection supports GET only.")
        return _list(sub, rg, full_type)

    rid = _canonical_id(sub, rg, type_chain, names)
    key = rid.lower()
    leaf_name = names[-1]

    api_version = request.query_params.get("api-version") or top.get("api_version") or "2023-01-01"
    lro = _is_lro_type(namespace, type_chain)

    if method == "GET":
        rec = _state.get(key)
        if not rec:
            return _error(404, "ResourceNotFound", f"Resource '{rid}' not found.")
        return JSONResponse(_view(rec))
    if method in ("PUT", "PATCH"):
        payload = await _safe_json(request)
        # Host-budget gate for Azure VMs (clamp 30%-50% of host CPU+RAM). Run
        # BEFORE _upsert so over-budget creates don't leave dangling metadata.
        # Only on new-create (key not in _state) so updates aren't double-billed.
        if (method == "PUT" and full_type.lower() == "microsoft.compute/virtualmachines"
                and key not in _state):
            vm_size = ""
            props = payload.get("properties") if isinstance(payload.get("properties"), dict) else {}
            hw = props.get("hardwareProfile") if isinstance(props, dict) and isinstance(props.get("hardwareProfile"), dict) else {}
            if isinstance(hw, dict):
                vm_size = str(hw.get("vmSize") or "")
            try:
                from server import _check_budget_for_launch
                _check_budget_for_launch(vm_size, "azure")  # raises HTTPException(403)
            except Exception as exc:
                # Re-raise HTTPException; surface other failures as 500.
                if isinstance(exc, HTTPException):
                    raise
                raise HTTPException(status_code=500, detail=f"budget check failed: {exc}")
        # Tier quantity-cap gate — runs before the upsert so an over-cap create
        # doesn't leave a half-created record. ONLY enforced on first-time
        # creates (key not already in _state) so PATCH/repeat-PUT updates
        # don't get blocked.
        if key not in _state and method == "PUT":
            try:
                import server as _srv_qty
                _enforce_azure_quantity_cap(_srv_qty, full_type, method)
            except HTTPException:
                raise
            except Exception:
                pass
        # Tier size-cap gate for Azure VMs — parity with EC2 + GCE.
        # Free=small (≤B1s/B2s); Student=medium; Developer=large; Enterprise=huge.
        if (method == "PUT" and key not in _state
                and full_type.lower() == "microsoft.compute/virtualmachines"):
            try:
                from core.app_context import enforce_size_cap
                vm_size = ""
                props = payload.get("properties") if isinstance(payload.get("properties"), dict) else {}
                hw = props.get("hardwareProfile") if isinstance(props, dict) and isinstance(props.get("hardwareProfile"), dict) else {}
                if isinstance(hw, dict):
                    vm_size = str(hw.get("vmSize") or "")
                if vm_size:
                    enforce_size_cap("vm", "azure", vm_size)
            except HTTPException:
                raise
            except Exception:
                pass
        resp = _upsert(rid, key, full_type, leaf_name, top, payload, base, patch=(method == "PATCH"))
        # Data-plane provisioning hooks (real Postgres for SQL, etc.).
        _provision_on_create(full_type, _state.get(key), base)
        if lro:
            # Generated SDK LRO create methods accept only a subset of 2xx for
            # the initial response (armstorage→{200,202}, armcompute→{200,201});
            # 200 is the common intersection. 201 breaks armstorage.
            resp.status_code = 200
            op_id = _make_operation(rid, method)
            for hk, hv in _lro_headers(base, op_id, api_version).items():
                resp.headers[hk] = hv
        # resource_id makes per-resource activity filtering in the SPA possible.
        _record_usage(f"azure.{method.lower()}", {"type": full_type, "name": leaf_name, "resource_id": rid})
        _cloudsim_sync_arm_service(full_type, rid, leaf_name, str(payload.get("location") or DEFAULT_LOCATION), action="upsert")
        return resp
    if method == "DELETE":
        rec = _state.pop(key, None)
        _deprovision_on_delete(full_type, rec)
        if rec is not None:
            _record_usage("azure.delete", {"type": full_type, "name": leaf_name, "resource_id": rid})
            _cloudsim_sync_arm_service(full_type, rid, leaf_name, str((rec or {}).get("location") or DEFAULT_LOCATION), action="delete")
        # Terminal success with NO async header: compatible with both sync
        # Delete clients (storage/functionapp expect 200/204) and BeginDelete
        # pollers (a header-less terminal status = immediately complete). The
        # create path above carries the Azure-AsyncOperation header that
        # exercises real LRO polling.
        return Response(status_code=200 if rec is not None else 204)
    return _error(405, "MethodNotAllowed", f"{method} not allowed.")


def _provider_info(namespace: str) -> dict:
    types = []
    for c in RESOURCE_CATALOG:
        if c["namespace"].lower() == namespace.lower():
            types.append({"resourceType": c["type"], "apiVersions": [c["api_version"]],
                          "locations": [DEFAULT_LOCATION], "capabilities": "None"})
    return {"id": f"/subscriptions/{DEFAULT_SUBSCRIPTION}/providers/{namespace}",
            "namespace": namespace, "registrationState": "Registered",
            "registrationPolicy": "RegistrationRequired", "resourceTypes": types}


def _arm_action(action: str, type_chain: list[str], resource_name: str,
                parent_rid: str = "") -> JSONResponse:
    """Handle POST action verbs. Two flavors:
    1. Stateful lifecycle actions (start/powerOff/restart/deallocate on VMs):
       look up the Azure record by `parent_rid`, call into the runtime layer
       to actually start/stop the backing LXD/multipass container, and update
       `properties.runtime.containerStatus` + `properties.powerState`.
    2. Synthesized stub actions (listKeys / regenerateKey / listConnectionStrings
       / listSecrets) that return a stable response shape so clients don't 500."""
    # VM lifecycle — drive the backing container via the runtime helpers.
    if action in ("start", "poweroff", "restart", "deallocate"):
        ns = type_chain[0].lower() if type_chain else ""
        typ = type_chain[1].lower() if len(type_chain) > 1 else ""
        if ns != "microsoft.compute" or typ != "virtualmachines":
            return _error(400, "ActionNotSupported",
                f"Action '{action}' is only supported on Microsoft.Compute/virtualMachines.")
        rec = _state.get(parent_rid.lower()) if parent_rid else None
        if not rec:
            return _error(404, "ResourceNotFound",
                f"Virtual machine '{resource_name}' not found.")
        props = rec.setdefault("properties", {})
        rt = props.setdefault("runtime", {})
        container = rt.get("containerName")
        backend = rt.get("backend")
        if not container or backend not in ("lxd", "multipass"):
            # Metadata-only VM (no host runtime). Update logical state so the
            # console still reflects the action; just no real container call.
            new_status = {"start": "running", "restart": "running",
                          "poweroff": "stopped", "deallocate": "deallocated"}[action]
            rt["containerStatus"] = new_status
            props["powerState"] = f"PowerState/{new_status}"
            try:
                import server as _srv
                _srv._cloudsim_sync_azure_vm_resource(rec, "upsert")
            except Exception:
                pass
            # Activity log: record even the metadata-only transition.
            _record_usage(f"azure.vm.{action}",
                          {"vm": resource_name, "container": "(simulated)",
                           "resource_id": parent_rid})
            return JSONResponse({"status": "Succeeded", "action": action,
                                 "containerStatus": new_status,
                                 "note": "metadata-only (no runtime backing); logical state updated"})
        try:
            import server as _srv_rt
            run = _srv_rt._lxd_run_checked if backend == "lxd" else _srv_rt._multipass_run_checked
            cmd_map = {"start": "start", "poweroff": "stop", "restart": "restart", "deallocate": "stop"}
            run([cmd_map[action], container], timeout=120)
        except Exception as exc:
            return _error(500, "ActionFailed", f"{action} failed: {str(exc)[:200]}")
        new_status = {"start": "running", "restart": "running",
                      "poweroff": "stopped", "deallocate": "deallocated"}[action]
        rt["containerStatus"] = new_status
        props["powerState"] = f"PowerState/{new_status}"
        try:
            import server as _srv
            _srv._cloudsim_sync_azure_vm_resource(rec, "upsert")
        except Exception:
            pass
        # Trigger graph + summary refresh + persist.
        _record_usage(f"azure.vm.{action}",
                      {"vm": resource_name, "container": container, "resource_id": parent_rid})
        return JSONResponse({"status": "Succeeded", "action": action,
                             "container": container, "containerStatus": new_status})

    # Stateless action stubs (used by SDKs for keys, connection strings, etc.).
    if action in ("listkeys", "regeneratekey"):
        try:
            from core import azure_dataplane as _dp
            return JSONResponse(_dp.storage_keys(resource_name))
        except Exception:
            return JSONResponse({"keys": [{"keyName": "key1", "value": "c2ltdWxhdGVk", "permissions": "FULL"}]})
    if action == "listconnectionstrings":
        return JSONResponse({"connectionStrings": []})
    if action == "listsecrets":
        return JSONResponse({})
    return JSONResponse({})


async def _safe_json(request: Request) -> dict:
    try:
        body = await request.json()
        return body if isinstance(body, dict) else {}
    except Exception:
        return {}


def _list(sub: str, rg: str | None, full_type: str) -> JSONResponse:
    ft = full_type.lower()
    items = []
    for rec in _state.values():
        if rec.get("_type", "").lower() != ft:
            continue
        if rec.get("_sub") != sub:
            continue
        if rg is not None and (rec.get("_rg") or "").lower() != rg.lower():
            continue
        items.append(_view(rec))
    return JSONResponse({"value": items})


# Azure ARM resource type → tier quantity-cap bucket. Used by the create-side
# gate to enforce Free=1 VM, 1 DB, 1 storage account, 1 APIM, 1 Function App
# per space. Tiers higher than Free relax these.
_AZURE_TYPE_TO_QUANTITY_KEY = {
    "microsoft.compute/virtualmachines":       "vm",
    "microsoft.sql/servers/databases":         "database",
    "microsoft.storage/storageaccounts":       "bucket",
    "microsoft.servicebus/namespaces/queues":  "queue",
    "microsoft.apimanagement/service":         "api_gateway",
    "microsoft.web/sites":                     "lambda_function",
    "microsoft.keyvault/vaults":               "kms_key",
}


def _enforce_azure_quantity_cap(_srv_mod_unused, full_type: str, method: str) -> None:
    """Call into enforce_quantity_cap for Azure ARM create/PATCH ops."""
    if method not in ("PUT", "PATCH"):
        return
    rt = _AZURE_TYPE_TO_QUANTITY_KEY.get(full_type.lower())
    if rt:
        from core.app_context import enforce_quantity_cap
        enforce_quantity_cap(rt)


def _upsert(rid: str, key: str, full_type: str, name: str, catalog: dict,
            payload: dict, base: str, patch: bool = False) -> JSONResponse:
    existed = key in _state
    # Only the top-level type carries rich defaults; nested children get a
    # minimal shell so any nested resource still works.
    is_top = full_type.lower() == (catalog["namespace"] + "/" + catalog["type"]).lower()
    defaults = _expand_tokens(catalog.get("defaults", {}), name, base) if is_top else {"properties": {"provisioningState": "Succeeded"}}
    endpoints = catalog.get("endpoints", {}) if is_top else {}

    if patch and existed:
        rec = _state[key]
    else:
        rec = {
            "id": rid, "name": name, "type": full_type,
            "location": payload.get("location") or DEFAULT_LOCATION,
            "tags": {}, "properties": {},
            "_type": full_type,
            "_sub": rid.split("/")[2],
            "_rg": _rg_from_id(rid),
            "_created": _now(),
        }
        # seed defaults
        for dk, dv in defaults.items():
            rec[dk] = dv if not isinstance(dv, dict) else dict(dv)

    # overlay client payload (location/tags/sku/kind/properties)
    for fld in ("location", "kind"):
        if payload.get(fld) is not None:
            rec[fld] = payload[fld]
    if isinstance(payload.get("tags"), dict):
        rec["tags"] = _merge(rec.get("tags", {}), payload["tags"])
    if isinstance(payload.get("sku"), dict):
        rec["sku"] = _merge(rec.get("sku", {}), payload["sku"])
    if isinstance(payload.get("properties"), dict):
        rec["properties"] = _merge(rec.get("properties", {}), payload["properties"])

    rec.setdefault("properties", {})
    rec["properties"].setdefault("provisioningState", "Succeeded")

    # fill simulator-origin endpoints if not provided
    for path_expr, suffix in endpoints.items():
        if _get_path(rec, path_expr) in (None, ""):
            _set_path(rec, path_expr, base + suffix.replace("__NAME__", name))

    _state[key] = rec
    return JSONResponse(status_code=200 if existed else 201, content=_view(rec))


def _rg_from_id(rid: str) -> str | None:
    parts = rid.split("/")
    for i, p in enumerate(parts):
        if p.lower() == "resourcegroups" and i + 1 < len(parts):
            return parts[i + 1]
    return None


def _list_resource_groups(sub: str) -> list[dict]:
    names: dict[str, bool] = {DEFAULT_RG: True}
    for rec in _state.values():
        if rec.get("_sub") == sub and rec.get("_rg"):
            names[rec["_rg"]] = True
    return [{"id": f"/subscriptions/{sub}/resourceGroups/{n}", "name": n,
             "type": "Microsoft.Resources/resourceGroups", "location": DEFAULT_LOCATION,
             "properties": {"provisioningState": "Succeeded"}} for n in names]


def _resource_group_item(method: str, sub: str, rg: str, payload: dict) -> JSONResponse:
    body = {"id": f"/subscriptions/{sub}/resourceGroups/{rg}", "name": rg,
            "type": "Microsoft.Resources/resourceGroups",
            "location": (payload or {}).get("location") or DEFAULT_LOCATION,
            "tags": (payload or {}).get("tags", {}),
            "properties": {"provisioningState": "Succeeded"}}
    if method == "DELETE":
        return JSONResponse(status_code=200, content=None)
    return JSONResponse(status_code=200 if method in ("PUT", "PATCH", "GET") else 405, content=body)


# --- console support -------------------------------------------------------
def catalog_for_console() -> list[dict]:
    """Catalog trimmed to what the console needs (no python defaults objects
    the browser doesn't use beyond rendering). Includes the multi-step Create
    wizard schema (Phase B) when one is defined for the service; the SPA
    renders it as a portal-style tabbed wizard, falling back to the flat
    ``createFields`` form when ``wizard`` is absent."""
    from core.azure_wizards import WIZARDS
    from core.azure_subblades import SUB_BLADES
    out = []
    for c in RESOURCE_CATALOG:
        entry = {
            "key": c["key"], "label": c["label"], "icon": c["icon"],
            "namespace": c["namespace"], "type": c["type"],
            "apiVersion": c["api_version"], "scope": c["scope"],
            "columns": c["columns"], "createFields": c["create_fields"],
            "children": c.get("children", []),
        }
        if c["key"] in WIZARDS:
            entry["wizard"] = WIZARDS[c["key"]]
        if c["key"] in SUB_BLADES:
            # Phase C — left sub-nav for the resource detail blade. The SPA
            # renders this as the portal-style two-pane layout (sub-nav left,
            # content swap right).
            entry["subBlades"] = SUB_BLADES[c["key"]]
        out.append(entry)
    return out


_BUILTIN_ROLES = [
    {"id": "owner", "name": "Owner", "properties": {"roleName": "Owner", "type": "BuiltInRole", "description": "Full access to all resources", "permissions": [{"actions": ["*"], "notActions": []}]}},
    {"id": "contributor", "name": "Contributor", "properties": {"roleName": "Contributor", "type": "BuiltInRole", "description": "Create and manage all resources, but cannot grant access", "permissions": [{"actions": ["*"], "notActions": ["Microsoft.Authorization/*/Write", "Microsoft.Authorization/*/Delete"]}]}},
    {"id": "reader", "name": "Reader", "properties": {"roleName": "Reader", "type": "BuiltInRole", "description": "View all resources", "permissions": [{"actions": ["*/read"], "notActions": []}]}},
    {"id": "vm-contributor", "name": "Virtual Machine Contributor", "properties": {"roleName": "Virtual Machine Contributor", "type": "BuiltInRole", "description": "Manage VMs but not access", "permissions": [{"actions": ["Microsoft.Compute/*"], "notActions": []}]}},
    {"id": "storage-contributor", "name": "Storage Account Contributor", "properties": {"roleName": "Storage Account Contributor", "type": "BuiltInRole", "description": "Manage storage accounts", "permissions": [{"actions": ["Microsoft.Storage/*"], "notActions": []}]}},
    {"id": "sql-contributor", "name": "SQL DB Contributor", "properties": {"roleName": "SQL DB Contributor", "type": "BuiltInRole", "description": "Manage SQL databases", "permissions": [{"actions": ["Microsoft.Sql/*"], "notActions": []}]}},
]


def seed() -> None:
    """Populate one example resource per top-level service so grids aren't
    empty on first load. Idempotent."""
    if _state:
        return
    sub, rg, base = DEFAULT_SUBSCRIPTION, DEFAULT_RG, "http://localhost:9000"
    samples = {
        "vm": "vm-web-01", "storage": "stcloudlearndemo", "sql": "sql-cloudlearn",
        "servicebus": "sb-cloudlearn", "cosmos": "cosmos-cloudlearn",
        "functionapp": "fn-orders", "apim": "apim-cloudlearn",
        "vnet": "vnet-cloudlearn", "rbac": "11111111-1111-1111-1111-111111111111",
        "role_definition": "owner",
    }
    for c in RESOURCE_CATALOG:
        name = samples.get(c["key"])
        if name is None:
            continue
        full_type = c["namespace"] + "/" + c["type"]
        rid = f"/subscriptions/{sub}/resourceGroups/{rg}/providers/{full_type}/{name}"
        _upsert(rid, rid.lower(), full_type, name, c, {}, base)
    # a couple of nested children for richer grids
    sql_db = f"/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Sql/servers/sql-cloudlearn/databases/appdb"
    _upsert(sql_db, sql_db.lower(), "Microsoft.Sql/servers/databases", "appdb",
            _BY_TYPE[("microsoft.sql", "servers")], {"properties": {"status": "Online"}}, base)
    sb_q = f"/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.ServiceBus/namespaces/sb-cloudlearn/queues/orders"
    _upsert(sb_q, sb_q.lower(), "Microsoft.ServiceBus/namespaces/queues", "orders",
            _BY_TYPE[("microsoft.servicebus", "namespaces")], {"properties": {"status": "Active"}}, base)
    # Seed built-in role definitions
    role_def_catalog = _BY_TYPE.get(("microsoft.authorization", "roledefinitions"))
    if role_def_catalog:
        for role in _BUILTIN_ROLES:
            full_type = "Microsoft.Authorization/roleDefinitions"
            rid = f"/subscriptions/{sub}/providers/{full_type}/{role['id']}"
            _upsert(rid, rid.lower(), full_type, role["name"], role_def_catalog,
                    {"properties": role["properties"]}, base)


def _provision_on_create(full_type: str, rec: dict | None, base: str) -> None:
    """Data-plane provisioning hook (real Postgres DB for SQL, etc.). Never
    breaks the control plane — failures are swallowed."""
    if not rec:
        return
    try:
        from core import azure_dataplane as _dp
        _dp.on_create(full_type, rec, base)
    except Exception:
        pass


def _deprovision_on_delete(full_type: str, rec: dict | None) -> None:
    if not rec:
        return
    try:
        from core import azure_dataplane as _dp
        _dp.on_delete(full_type, rec)
    except Exception:
        pass


def operation_status(op_id: str) -> dict | None:
    return _operations.get(op_id)


def build_openapi() -> dict:
    """Synthesize an OpenAPI 3 spec for the Azure ARM surface from the catalog
    (the live endpoints are served by the generic catch-all, which isn't in the
    FastAPI schema — so we describe them here for the Azure Swagger console)."""
    sub_p = {"name": "subscriptionId", "in": "path", "required": True,
             "schema": {"type": "string", "default": DEFAULT_SUBSCRIPTION}}
    rg_p = {"name": "resourceGroupName", "in": "path", "required": True,
            "schema": {"type": "string", "default": DEFAULT_RG}}

    def apiver(default: str):
        return {"name": "api-version", "in": "query", "required": True,
                "schema": {"type": "string", "default": default}}

    def name_p(label: str):
        return {"name": "resourceName", "in": "path", "required": True,
                "schema": {"type": "string"}, "description": label}

    paths: dict[str, dict] = {}
    paths["/subscriptions/{subscriptionId}/resourcegroups"] = {
        "get": {"tags": ["Resource Groups"], "summary": "List resource groups",
                "parameters": [sub_p, apiver("2021-04-01")],
                "responses": {"200": {"description": "OK"}}}}

    for c in RESOURCE_CATALOG:
        ns, typ, ver, label = c["namespace"], c["type"], c["api_version"], c["label"]
        coll = f"/subscriptions/{{subscriptionId}}/resourceGroups/{{resourceGroupName}}/providers/{ns}/{typ}"
        item = coll + "/{resourceName}"
        body_example = {"location": DEFAULT_LOCATION, **{k: v for k, v in c.get("defaults", {}).items()}}
        paths[coll] = {
            "get": {"tags": [label], "summary": f"List {label}",
                    "parameters": [sub_p, rg_p, apiver(ver)],
                    "responses": {"200": {"description": "OK"}}}}
        paths[item] = {
            "get": {"tags": [label], "summary": f"Get {label[:-1] if label.endswith('s') else label}",
                    "parameters": [sub_p, rg_p, name_p(c["label"]), apiver(ver)],
                    "responses": {"200": {"description": "OK"}, "404": {"description": "Not found"}}},
            "put": {"tags": [label], "summary": f"Create or update {label[:-1] if label.endswith('s') else label}",
                    "parameters": [sub_p, rg_p, name_p(c["label"]), apiver(ver)],
                    "requestBody": {"required": True, "content": {"application/json": {
                        "schema": {"type": "object"}, "example": body_example}}},
                    "responses": {"200": {"description": "Updated"}, "201": {"description": "Created"}}},
            "delete": {"tags": [label], "summary": f"Delete {label[:-1] if label.endswith('s') else label}",
                       "parameters": [sub_p, rg_p, name_p(c["label"]), apiver(ver)],
                       "responses": {"200": {"description": "Deleted"}, "204": {"description": "No content"}}}}
        for child in c.get("children", []):
            ccoll = item + f"/{child['type']}"
            citem = ccoll + "/{childName}"
            cn = {"name": "childName", "in": "path", "required": True, "schema": {"type": "string"}}
            paths[ccoll] = {"get": {"tags": [label], "summary": f"List {child['label']} ({label})",
                                    "parameters": [sub_p, rg_p, name_p(c["label"]), apiver(ver)],
                                    "responses": {"200": {"description": "OK"}}}}
            paths[citem] = {
                "put": {"tags": [label], "summary": f"Create/update {child['label'][:-1] if child['label'].endswith('s') else child['label']}",
                        "parameters": [sub_p, rg_p, name_p(c["label"]), cn, apiver(ver)],
                        "requestBody": {"content": {"application/json": {"schema": {"type": "object"}, "example": {"properties": {}}}}},
                        "responses": {"200": {"description": "OK"}, "201": {"description": "Created"}}},
                "delete": {"tags": [label], "summary": f"Delete {child['label'][:-1] if child['label'].endswith('s') else child['label']}",
                           "parameters": [sub_p, rg_p, name_p(c["label"]), cn, apiver(ver)],
                           "responses": {"200": {"description": "Deleted"}}}}

    return {
        "openapi": "3.0.2",
        "info": {"title": "CloudLearn — Azure API",
                 "version": "2.0.0",
                 "description": "Azure Resource Manager (ARM) control plane — 9 simulated services. "
                                "Set `api-version` (pre-filled). All endpoints accept fake credentials."},
        "paths": paths,
    }


def register(app, _h=None) -> None:
    """Register the generic ARM catch-all + console catalog endpoint.

    No global seed: Azure resources are space-scoped + persisted (server injects
    a _SpaceScopedDictProxy as `_state`), so each space starts empty and fills
    as the user/SDK creates resources — exactly like AWS/GCP."""

    @app.get("/api/azure/catalog", include_in_schema=False)
    def azure_catalog():
        return {"subscription": DEFAULT_SUBSCRIPTION, "resourceGroup": DEFAULT_RG,
                "location": DEFAULT_LOCATION, "services": catalog_for_console()}

    @app.get("/api/azure/operations/{op_id}", include_in_schema=False)
    def azure_operation(op_id: str):
        op = operation_status(op_id)
        if not op:
            # Unknown ops are treated as already-completed (idempotent poll).
            return {"status": "Succeeded"}
        return {"id": op["id"], "name": op["name"], "status": op["status"],
                "startTime": op["startTime"], "endTime": op["endTime"],
                "properties": {"provisioningState": op["status"]}}

    # Data-plane sub-apps (Blob REST, SQL connect, Service Bus, Cosmos).
    try:
        from core import azure_dataplane as _dp
        _dp.register(app)
    except Exception:
        pass

    @app.api_route("/subscriptions/{rest:path}",
                   methods=["GET", "PUT", "POST", "PATCH", "DELETE"],
                   include_in_schema=False)
    async def arm_dispatch(rest: str, request: Request):
        return await handle_arm(request, rest)
