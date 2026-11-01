"""Azure ARM control-plane core (substrate-free) for Vyomi-Nano.

A faithful port of ``providers/azure_services.handle_arm``: a GENERIC Azure
Resource Manager CRUD over a flat in-memory store keyed by the lower-cased
resource id, parameterized by the RESOURCE_CATALOG dumped verbatim from the
appliance (``core/azure_arm_data.py``). Unlike AWS/GCP in Nano (which ride the
generic ``/api/{cloud}/{service}`` collection-path ResourceStore), the Azure
console speaks real ARM —
    PUT/GET/DELETE /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.X/{type}/{name}?api-version=
— so this core handles those paths directly.

Stripped vs the appliance handler (no substrate): FastAPI Request/Response,
CloudSim sync, usage recording, real backend provisioning, host-budget + tier
quantity/size caps. VM lifecycle actions become metadata-only (no LXD in a
browser). Pure stdlib → runs identically on host CPython and under Pyodide.

Entry point:
    AzureArm().handle(method, path, query=None, body=None)
      -> {"status": int, "headers": dict, "body": dict | None}
where ``path`` is the request path (``/subscriptions/...`` or
``/api/azure/operations/{id}``) AFTER any bundle base-prefix is stripped.
"""
from __future__ import annotations

import base64
import datetime
import re
import uuid
from urllib.parse import urlsplit

try:                                              # host: package import
    from core.azure_arm_data import CATALOG, ROLES
except ImportError:                               # Pyodide: cores are flat on sys.path
    from azure_arm_data import CATALOG, ROLES      # type: ignore

try:                                              # Container Apps engine (Microsoft.App)
    from core import azure_app_core as app_engine
except ImportError:
    import azure_app_core as app_engine            # type: ignore

try:                                              # App Service engine (Microsoft.Web: web apps, function apps, plans)
    from core import azure_webapp_core as web_engine
except ImportError:
    import azure_webapp_core as web_engine          # type: ignore

try:                                              # App Configuration engine (Microsoft.AppConfiguration)
    from core import azure_appconfiguration_core as appconfig_engine
except ImportError:
    import azure_appconfiguration_core as appconfig_engine   # type: ignore

try:                                              # Cognitive Services engine (Microsoft.CognitiveServices)
    from core import azure_cognitiveservices_core as cogs_engine
except ImportError:
    import azure_cognitiveservices_core as cogs_engine   # type: ignore

try:                                              # Azure DNS engine (Microsoft.Network/dnsZones)
    from core import azure_dns_core as dns_engine
except ImportError:
    import azure_dns_core as dns_engine            # type: ignore

try:                                              # Azure Monitor engine (Microsoft.Insights)
    from core import azure_monitor_core as monitor_engine
except ImportError:
    import azure_monitor_core as monitor_engine    # type: ignore

try:                                              # Azure Log Analytics engine (Microsoft.OperationalInsights)
    from core import azure_operationalinsights_core as oi_engine
except ImportError:
    import azure_operationalinsights_core as oi_engine   # type: ignore

try:                                              # Azure Cost Management + Consumption engine
    from core import azure_cost_core as cost_engine
except ImportError:
    import azure_cost_core as cost_engine          # type: ignore
try:                                              # Event Grid event subscriptions (Microsoft.EventGrid, scoped to a topic)
    from core import azure_eventgrid_core as eventgrid_engine
except ImportError:
    import azure_eventgrid_core as eventgrid_engine       # type: ignore

try:                                              # Management locks (Microsoft.Authorization/locks, scoped to ANY resource)
    from core import azure_locks_core as locks_engine
except ImportError:
    import azure_locks_core as locks_engine        # type: ignore

try:                                              # checkAccess decision algorithm (wildcard + scope-inheritance +
    from core import azure_iam_core as iam_engine  # notActions/deny) — reused for role assignments created as real
except ImportError:                               # ARM resources scoped to a resource group (this module's own store,
    import azure_iam_core as iam_engine            # type: ignore   not azure_iam_core's separate directory-role store).

try:                                              # Microsoft Defender for Cloud (Microsoft.Security), live over this state
    from core import azure_security_core as security_engine
except ImportError:
    import azure_security_core as security_engine  # type: ignore

try:                                              # AKS Kubernetes object store + kubectl (runCommand)
    from core import azure_aks_k8s_core as k8s_engine
    from core import kubescape_core as kubescape_engine
except ImportError:
    import azure_aks_k8s_core as k8s_engine        # type: ignore
    import kubescape_core as kubescape_engine      # type: ignore

try:                                              # VM size catalog (vcpu/ram/family per real Azure size name)
    from core import instance_catalog
except ImportError:
    import instance_catalog                        # type: ignore

DEFAULT_SUBSCRIPTION = "00000000-0000-0000-0000-cloudlearn01"
DEFAULT_RG = "cloudlearn-rg"
DEFAULT_LOCATION = "eastus"

# The one simulated subscription's offer — a fixed Pay-As-You-Go quota, same shape real ARM's
# GET /subscriptions/{id} returns under subscriptionPolicies. The portal's Overview blade reads
# "Offer"/"Offer ID" off quotaId through its own static offer-name catalog, not a separate field.
SUBSCRIPTION_POLICIES = {"locationPlacementId": "Public_2014-09-01", "quotaId": "PayAsYouGo_2014-09-01", "spendingLimit": "Off"}

_BY_TYPE = {(c["namespace"].lower(), c["type"].lower()): c for c in CATALOG}


def _record_activity(resource_name: str, action: str, detail: str = "") -> None:
    """Best-effort: append to the shared cloudsim event log (core/nano_events.py) so a
    resource's "Activity log" panel has something real to show. Lazily imported — nano_events
    loads AFTER azure_arm_core in the Nano boot order (wasm/nano-boot.js), so a module-level
    import would fail there; by the time a request is served, boot has finished and the
    deferred import always succeeds."""
    try:
        try:
            from core import nano_events
        except ImportError:
            import nano_events  # type: ignore
        nano_events.record("azure", "arm", resource_name, action, "ok", detail)
    except Exception:
        pass


def _parse_odata_ts(s: str):
    try:
        d = datetime.datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=datetime.timezone.utc)   # naive = UTC (comparable)



def _activity_log_query(query: dict) -> dict:
    """GET /subscriptions/{sub}/providers/Microsoft.Insights/eventtypes/management/values —
    the real ARM activity-log read API every resource's "Activity log" blade calls, scoped
    via an OData $filter containing ``resourceUri eq '{id}'`` and/or the timespan picker's
    ``eventTimestamp ge/le '{iso}'`` predicates (ENFORCED — a narrower timespan really narrows
    the result). The rest of the OData grammar (severity/category, other operators) is not
    understood; with no resourceUri filter the unfiltered feed (every resource) is returned,
    matching the subscription-wide Activity log page."""
    try:
        try:
            from core import nano_events
        except ImportError:
            import nano_events  # type: ignore
    except Exception:
        return _ok({"value": []})
    filt = query.get("$filter") or ""
    m = re.search(r"resourceUri\s+eq\s+'([^']*)'", filt)
    resource = (m.group(1).rstrip("/").split("/")[-1]) if m else None
    events = nano_events.list_events(resource=resource)
    since = _parse_odata_ts(m.group(1)) if (m := re.search(r"eventTimestamp\s+ge\s+'([^']*)'", filt)) else None
    until = _parse_odata_ts(m.group(1)) if (m := re.search(r"eventTimestamp\s+le\s+'([^']*)'", filt)) else None
    if since is not None or until is not None:
        def _in_range(e):
            ts = _parse_odata_ts(e["ts"])
            if ts is None:
                return True
            if since is not None and ts < since:
                return False
            if until is not None and ts > until:
                return False
            return True
        events = [e for e in events if _in_range(e)]
    value = [{
        "eventName": {"value": e["action"], "localizedValue": e["action"]},
        "operationName": {"value": e["action"], "localizedValue": f"{e['action']}: {e['detail']}" if e["detail"] else e["action"]},
        "status": {"value": e["status"], "localizedValue": e["status"]},
        "eventTimestamp": e["ts"], "submissionTimestamp": e["ts"],
        "subscriptionId": DEFAULT_SUBSCRIPTION,
        "caller": "vyomi-console",
        "resourceId": e["resource"],
        "resourceGroupName": DEFAULT_RG,
        "level": "Informational",
        "id": str(e["id"]),
    } for e in events]
    return _ok({"value": value})


def vault_properties(state: dict | None, vault: str) -> dict:
    """Look up a Microsoft.KeyVault/vaults resource's `properties` by vault name alone (the
    Key Vault Keys/Secrets/Certificates data planes never learn the subscription/resource
    group — same read-only-snapshot pattern as azure_sql_core._server_props). Returns {} if
    `vault` is blank or no such vault exists (callers must treat that as "not enforced", not
    "denied" — an unknown vault name is not evidence of a network restriction)."""
    if not state or not vault:
        return {}
    want = f"/vaults/{vault}".lower()
    for rec in state.values():
        if isinstance(rec, dict) and rec.get("_type", "").lower() == "microsoft.keyvault/vaults" \
                and rec.get("id", "").lower().endswith(want):
            return rec.get("properties") or {}
    return {}


def keyvault_network_denied(state: dict | None, vault: str) -> bool:
    """True when this vault's ARM-configured networking (Networking blade /
    azure.keyvaults.networking) would reject a data-plane call from the console: public
    network access disabled, or the firewall default action is Deny (Vyomi has no caller
    IP/VNet to match an allow-list entry against, so Deny blocks unconditionally — the same
    simplification real Azure makes for an unrecognized caller)."""
    p = vault_properties(state, vault)
    if not p:
        return False
    if p.get("publicNetworkAccess") == "Disabled":
        return True
    return (p.get("networkAcls") or {}).get("defaultAction") == "Deny"


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _tz_offset_minutes(tz_label: str) -> int:
    """Parse the UTC offset embedded in an Azure-style display string, e.g.
    '(UTC-08:00) Pacific Time (US & Canada)' -> -480. Bare 'UTC' / '(UTC) ...' -> 0
    (no IANA/Windows tz database in stdlib, but every offset Azure shows is spelled
    out in the label itself, so no database is needed)."""
    m = re.match(r"\(UTC([+-]\d{2}):(\d{2})\)", tz_label or "")
    if not m:
        return 0
    sign = 1 if m.group(1)[0] == "+" else -1
    return sign * (int(m.group(1)[1:]) * 60 + int(m.group(2)))


def _apply_auto_shutdown(rec: dict) -> None:
    """azure.vms.auto_shutdown, ENFORCED: if the stored schedule's local time has already
    passed today, flip the virtual machine's own logical power state to stopped — lazily, on
    read, since there is no real background scheduler. `_autoShutdownFiredDate` is a
    once-per-calendar-day guard: without it, a manual Start after the scheduled time would get
    immediately re-stopped by the very next GET."""
    sched = ((rec.get("properties") or {}).get("autoShutdown")) or {}
    if not sched.get("enabled"):
        return
    try:
        hh, mm = (int(x) for x in str(sched.get("time", "")).split(":")[:2])
    except ValueError:
        return
    now_local = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=_tz_offset_minutes(sched.get("timeZone")))
    today = now_local.date().isoformat()
    if now_local.time() >= datetime.time(hh, mm) and rec.get("_autoShutdownFiredDate") != today:
        rec.setdefault("properties", {})["powerState"] = "PowerState/stopped"
        rec["_autoShutdownFiredDate"] = today


# ── pure helpers (ported verbatim from azure_services) ─────────────────────
def _set_path(obj: dict, dotted: str, value):
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


def _get_path(obj, dotted: str):
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


def _public_ip() -> str:
    """A public IPv4 for a new Microsoft.Network/publicIPAddresses (Azure-ish 20.x range)."""
    h = uuid.uuid4().int
    return f"20.{(h >> 8) % 200 + 10}.{(h >> 16) % 254 + 1}.{(h >> 24) % 254 + 1}"


def _expand_tokens(obj, name: str, base: str):
    if isinstance(obj, str):
        return (obj.replace("__UUID__", str(uuid.uuid4()))
                   .replace("__NAME__", name)
                   .replace("__BASE__", base)
                   .replace("__NOW__", _now())
                   .replace("__PUBLICIP__", _public_ip()))
    if isinstance(obj, dict):
        return {k: _expand_tokens(v, name, base) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_expand_tokens(v, name, base) for v in obj]
    return obj


# ── ARM template deployment: literal [parameters('x')] / [variables('y')] substitution only
# (no expression language, no resourceId()/concat()/etc, no dependsOn ordering beyond
# template order) — a bounded but real evaluator, see AzureArm._execute_deployment.
_PARAM_EXPR = re.compile(r"^\[\s*parameters\(\s*'([^']*)'\s*\)\s*\]$")
_VAR_EXPR = re.compile(r"^\[\s*variables\(\s*'([^']*)'\s*\)\s*\]$")


def _resolve_template_expr(value, params: dict, variables: dict):
    if isinstance(value, str):
        m = _PARAM_EXPR.match(value.strip())
        if m:
            return params.get(m.group(1))
        m = _VAR_EXPR.match(value.strip())
        if m:
            return variables.get(m.group(1))
        return value
    if isinstance(value, dict):
        return {k: _resolve_template_expr(v, params, variables) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_template_expr(v, params, variables) for v in value]
    return value


_APIM_DEFAULT_POLICY = ("<policies>\r\n  <inbound />\r\n  <backend>\r\n    <forward-request />\r\n"
                        "  </backend>\r\n  <outbound />\r\n  <on-error />\r\n</policies>")


def _apim_default_policy(type_chain, names, state, rid=""):
    """A new API Management service ships with the default global policy, so
    GET .../service/{n}/policies/policy returns it instead of 404 until PUT."""
    if (len(type_chain) == 3 and len(names) == 2 and names[1].lower() == "policy"
            and type_chain[1].lower() == "service" and type_chain[2].lower() == "policies"
            and type_chain[0].lower() == "microsoft.apimanagement"):
        parent = rid.rsplit("/policies/", 1)[0].lower()
        if parent in state:
            return {"id": rid, "name": "policy", "type": "Microsoft.ApiManagement/service/policies",
                    "properties": {"format": "xml", "value": _APIM_DEFAULT_POLICY}}
    return None


def _canonical_id(sub: str, rg, type_chain, names) -> str:
    seg = [f"/subscriptions/{sub}"]
    if rg:
        seg.append(f"resourceGroups/{rg}")
    seg.append("providers")
    ns = type_chain[0]
    seg.append(ns)
    rest_types = type_chain[1:]
    seg.append(rest_types[0])
    for i, nm in enumerate(names):
        seg.append(nm)
        if i + 1 < len(rest_types):
            seg.append(rest_types[i + 1])
    return "/".join(seg)


def _role_assignment_marker(chain):
    """Index of a re-entrant, LIST-only ``['providers', 'Microsoft.Authorization',
    'roleAssignments']`` marker in `chain` (`AzureArm._arm`'s split of everything after the
    FIRST namespace token) — i.e. GET .../<some resource>/providers/Microsoft.Authorization/
    roleAssignments, same shape as the locks/diagnosticSettings extension resources. A bare
    name after the marker (reading ONE assignment scoped that way) isn't modelled and falls
    through to the generic subscription-scoped catalog alternation instead."""
    for i in range(len(chain) - 2):
        if (chain[i].lower() == "providers" and chain[i + 1].lower() == "microsoft.authorization"
                and chain[i + 2].lower() == "roleassignments" and i + 3 == len(chain)):
            return i
    return None


def _check_access_marker(chain):
    """Index of a re-entrant ``['providers', 'Microsoft.Authorization', 'checkAccess']``
    marker in `chain`, same shape as `_role_assignment_marker` — i.e. POST .../<some
    resource>/providers/Microsoft.Authorization/checkAccess, the decision call behind any
    resource's own "Access control (IAM) > Check access / My access" tab (not just the
    resource-group/subscription scope the dedicated branch above already handled)."""
    for i in range(len(chain) - 2):
        if (chain[i].lower() == "providers" and chain[i + 1].lower() == "microsoft.authorization"
                and chain[i + 2].lower() == "checkaccess" and i + 3 == len(chain)):
            return i
    return None


def _parse_kv_secret_identifier(secret_id: str):
    """`https://{vault}.vault.azure.net/secrets/{name}[/{version}]` -> (name, version|None),
    the same shape the azure-keyvault-secrets SDK parses a secret `id` back out of
    (core/azure_keyvault_secrets_core.py) — used in reverse here to resolve an APIM named
    value's `keyVault.secretIdentifier` against this space's own KV secrets store."""
    try:
        segs = [s for s in urlsplit(secret_id).path.split("/") if s]
    except Exception:
        return None, None
    if len(segs) < 2 or segs[0] != "secrets":
        return None, None
    return segs[1], (segs[2] if len(segs) > 2 else None)


def _view(rec: dict) -> dict:
    if rec.get("_type", "").lower() == "microsoft.compute/virtualmachines":
        _apply_auto_shutdown(rec)
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def _rg_from_id(rid: str):
    parts = rid.split("/")
    for i, p in enumerate(parts):
        if p.lower() == "resourcegroups" and i + 1 < len(parts):
            return parts[i + 1]
    return None


# GET .../Microsoft.Compute/locations/{location}/vmSizes and GET .../virtualMachines/{vm}/vmSizes
# (azure.vms.size): real ARM VirtualMachineSize shape plus two reference-only extras (series,
# maxIops) the console's Size table shows — all numbers derived from instance_catalog.AZURE
# (the same catalog CloudSimBridge uses), never baked into the console itself.
_VM_SIZE_OS_DISK_MB = 1047552  # real Azure constant: max OS disk size for a generalized image
_SERIES_LABEL = {"burstable": "B-series", "general": "Dsv5-series", "compute": "Fsv2-series",
                  "memory": "Esv5-series", "storage": "Lsv3-series", "gpu": "NC-series"}
# Real published Azure max uncached disk IOPS, by vCPU count — shared across the general /
# compute / memory families at the same vCPU count (confirmed against Dsv5/Fsv2/Esv5 docs).
_IOPS_BY_VCPU = {1: 400, 2: 3750, 4: 6400, 8: 12800, 16: 25600, 32: 51200}
_IOPS_BURSTABLE = {1: 400, 2: 1300, 4: 2400, 8: 4800}


def _max_iops(family: str, vcpu: int) -> int:
    if family == "burstable":
        return _IOPS_BURSTABLE.get(vcpu, min(vcpu * 600, 4800))
    if family in ("storage", "gpu"):
        return 20000
    return _IOPS_BY_VCPU.get(vcpu, min(vcpu * 1600, 80000))


def _vm_size_entry(name: str, shape: dict) -> dict:
    vcpu, ram_mb, family = shape["vcpu"], shape["ram_mb"], shape["family"]
    max_data_disks = min(vcpu * (4 if family == "gpu" else 2), 64 if family == "gpu" else 32)
    resource_disk_gib = {"burstable": vcpu * 4, "storage": vcpu * 240, "gpu": vcpu * 55}.get(family, 0)
    series = "M-series" if name.startswith("Standard_M") else _SERIES_LABEL.get(family, "General purpose")
    return {
        "name": name, "numberOfCores": vcpu, "memoryInMB": ram_mb,
        "osDiskSizeInMB": _VM_SIZE_OS_DISK_MB, "resourceDiskSizeInMB": resource_disk_gib * 1024,
        "maxDataDiskCount": max_data_disks, "series": series, "maxIops": _max_iops(family, vcpu),
    }


def _vm_sizes() -> list:
    return [_vm_size_entry(name, shape) for name, shape in sorted(instance_catalog.AZURE.items())]


def _ok(body, status=200, headers=None):
    return {"status": status, "headers": headers or {}, "body": body}


def _err(status: int, code: str, message: str):
    return {"status": status, "headers": {}, "body": {"error": {"code": code, "message": message}}}


class AzureArm:
    """In-memory Azure Resource Manager control plane (one per Nano instance)."""

    def __init__(self, base: str = ""):
        self.state: dict = {}
        self.operations: dict = {}
        self._base = base                       # endpoint/LRO URL prefix (relative by default)
        self.sub_names: dict = {}               # subscription id (lower) -> displayName (Microsoft.Subscription/rename)
        self.sub_tags: dict = {}                # subscription id (lower) -> tags (Microsoft.Resources/tags/default)
        self.providers: dict = {}               # namespace (lower) -> "Registered" | "NotRegistered"
        self.kv_secrets_store = None             # set by aws_wire_router.py: this space's Key Vault secrets store (APIM named-value listValue)
        self.sql_store = None                    # set by the platform: the Azure SQL data plane's SqlStore (database export/import)
        self.blob_store = None                   # set by the platform: the simulator's Azure Blob store (.bacpac target/source)

    # ── per-resource ARM activity entries (Microsoft.Insights/eventtypes rows) ──
    # Kept IN self.state (so they persist with the rest of ARM, offline and Nano alike) by the one
    # writer, azure_webapp_core._record_event — the Microsoft.Web engine records its own writes
    # through it, and anything else here can via _record_activity. Read back by the single
    # eventtypes handler in _arm, merged with the shared nano_events feed.
    def _record_activity(self, rid: str, operation_name: str, sub: str, status: str = "Succeeded"):
        web_engine._record_event(self.state, sub, _rg_from_id(rid), rid, operation_name, operation_name, status)

    def _activity_log(self, method: str, query: dict, sub: str = DEFAULT_SUBSCRIPTION):
        if method != "GET":
            return _err(405, "MethodNotAllowed", "The activity log supports GET only.")
        r = monitor_engine.dispatch(self.state, "GET", sub, None, ["eventtypes", "management", "values"], [], {}, query)
        return {"status": r["status"], "headers": {}, "body": r["body"]}

    # ── public entry ──────────────────────────────────────────────────────
    def handle(self, method: str, path: str, query=None, body=None):
        method = (method or "GET").upper()
        query = query or {}
        # LRO poll — every operation completes immediately in the sim.
        if "/api/azure/operations/" in path:
            op_id = path.split("/api/azure/operations/", 1)[1].split("?", 1)[0].strip("/")
            op = self.operations.get(op_id)
            base = {"status": "Succeeded", "properties": {"provisioningState": "Succeeded"}}
            if op:
                base.update({"id": op["id"], "name": op["name"], "startTime": op["startTime"], "endTime": op["endTime"]})
                base.update(op.get("result") or {})
            return _ok(base)
        i = path.find("/subscriptions/")
        if i == -1:
            return _err(404, "NotFound", f"Not an ARM path: {path}")
        rest = path[i + len("/subscriptions/"):].split("?", 1)[0]
        return self._arm(method, rest, query, body if isinstance(body, dict) else {})

    # ── ARM dispatcher (port of handle_arm) ───────────────────────────────
    def _arm(self, method, rest, query, payload):
        base = self._base
        segs = [s for s in rest.split("/") if s != ""]
        if not segs:
            return _err(400, "BadRequest", "Missing subscription id.")
        sub = segs[0]
        rest_segs = segs[1:]

        if not rest_segs:
            return _ok({"id": f"/subscriptions/{sub}", "subscriptionId": sub,
                        "displayName": self.sub_names.get(sub.lower(), "CloudLearn Subscription"),
                        "state": "Enabled", "tags": self.sub_tags.get(sub.lower(), {}),
                        "subscriptionPolicies": SUBSCRIPTION_POLICIES})

        # resource groups
        if rest_segs[0].lower() == "resourcegroups" and len(rest_segs) <= 2:
            if len(rest_segs) == 1:
                if method == "GET":
                    return _ok({"value": self._list_resource_groups(sub)})
                return _err(405, "MethodNotAllowed", "Use PUT /resourcegroups/{name}.")
            return self._resource_group_item(method, sub, rest_segs[1], payload)

        rg = None
        idx = 0
        if rest_segs[0].lower() == "resourcegroups":
            if len(rest_segs) < 2:
                return _err(400, "BadRequest", "Missing resource group name.")
            rg = rest_segs[1]
            idx = 2

        # GET .../resourceGroups/{rg}/resources — the generic "resources in this group"
        # list every resource-group blade's Overview/Resources tab and delete confirmation
        # call (az resource list -g / Resources.list_by_resource_group), scoped across every
        # catalog type at once (not alternating type/name like the "providers" branch below).
        if rg is not None and idx < len(rest_segs) and rest_segs[idx].lower() == "resources" and len(rest_segs) == idx + 1:
            if method != "GET":
                return _err(405, "MethodNotAllowed", "Use GET to list resources in a resource group.")
            items = [_view(r) for r in self.state.values()
                     if r.get("_sub") == sub and (r.get("_rg") or "").lower() == rg.lower()
                     and r.get("_type", "").lower() not in ("microsoft.resources/resourcegroups", web_engine.EVENT_TYPE)
                     and not r.get("_type", "").lower().startswith(security_engine.TYPE_PREFIX)]
            return _ok({"value": items})

        # GET /subscriptions/{sub}/resources — every resource across every resource group in
        # the subscription (az resource list / Resources.list), the Subscription blade's
        # Settings > Resources panel.
        if rg is None and idx < len(rest_segs) and rest_segs[idx].lower() == "resources" and len(rest_segs) == idx + 1:
            if method != "GET":
                return _err(405, "MethodNotAllowed", "Use GET to list resources in a subscription.")
            items = [_view(r) for r in self.state.values()
                     if r.get("_sub") == sub
                     and r.get("_type", "").lower() not in ("microsoft.resources/resourcegroups", web_engine.EVENT_TYPE)
                     and not r.get("_type", "").lower().startswith(security_engine.TYPE_PREFIX)]
            return _ok({"value": items})

        if idx >= len(rest_segs) or rest_segs[idx].lower() != "providers":
            return _err(400, "BadRequest", f"Unrecognized ARM path: /subscriptions/{rest}")
        after = rest_segs[idx + 1:]

        # provider registration probes (Settings > Resource providers: Register/Unregister/Refresh)
        if len(after) == 0 and method == "GET":
            return _ok({"value": [self._provider_info(n) for n in sorted({c["namespace"] for c in CATALOG})]})
        if len(after) == 1 and method == "GET":
            return _ok(self._provider_info(after[0]))
        if len(after) == 2 and after[1].lower() == "register" and method == "POST":
            self.providers[after[0].lower()] = "Registered"
            return _ok(self._provider_info(after[0]))
        if len(after) == 2 and after[1].lower() == "unregister" and method == "POST":
            self.providers[after[0].lower()] = "NotRegistered"
            return _ok(self._provider_info(after[0]))
        if len(after) < 2:
            return _err(400, "BadRequest", "Missing provider namespace/type.")

        namespace = after[0]
        chain = after[1:]

        # Microsoft.Subscription/rename: the subscription blade's "Rename" header action.
        if namespace.lower() == "microsoft.subscription" and chain and chain[0].lower() == "rename":
            if method != "POST":
                return _err(405, "MethodNotAllowed", "Use POST to rename a subscription.")
            name = (payload or {}).get("subscriptionName")
            if not name:
                return _err(400, "BadRequest", "subscriptionName is required.")
            self.sub_names[sub.lower()] = name
            _record_activity(sub, "Update", f"Microsoft.Subscription rename to '{name}'")
            return _ok({"id": f"/subscriptions/{sub}", "subscriptionId": sub, "displayName": name,
                        "state": "Enabled", "tags": self.sub_tags.get(sub.lower(), {}),
                        "subscriptionPolicies": SUBSCRIPTION_POLICIES})

        # Microsoft.Resources/tags/default: tags at subscription scope (Tags - CreateOrUpdateAtScope),
        # the subscription blade's Tags panel (Microsoft.Authorization/locks aside, subscriptions
        # aren't a PUT/PATCH-able catalog resource, so tags live on this generic extension instead).
        if namespace.lower() == "microsoft.resources" and chain[:1] == ["tags"] and chain[1:2] == ["default"] and len(chain) == 2:
            key = sub.lower()
            if method == "GET":
                return _ok({"id": f"/subscriptions/{sub}/providers/Microsoft.Resources/tags/default",
                            "type": "Microsoft.Resources/tags", "properties": {"tags": self.sub_tags.get(key, {})}})
            if method in ("PUT", "PATCH"):
                tags = (payload or {}).get("properties", {}).get("tags")
                if not isinstance(tags, dict):
                    return _err(400, "BadRequest", "properties.tags is required.")
                self.sub_tags[key] = dict(tags) if method == "PUT" else _merge(self.sub_tags.get(key, {}), tags)
                _record_activity(sub, "Update", "Microsoft.Resources/tags 'default'")
                return _ok({"id": f"/subscriptions/{sub}/providers/Microsoft.Resources/tags/default",
                            "type": "Microsoft.Resources/tags", "properties": {"tags": self.sub_tags[key]}})
            if method == "DELETE":
                self.sub_tags.pop(key, None)
                return _ok(None, status=200)
            return _err(405, "MethodNotAllowed", f"{method} not allowed.")
        # Microsoft.Compute/.../vmSizes (azure.vms.size): subscription+location scoped
        # (.../providers/Microsoft.Compute/locations/{location}/vmSizes) or resource-scoped to
        # an existing VM (.../virtualMachines/{vm}/vmSizes) — a derived read, not a stored
        # resource, so it's caught before the generic type/name alternation below (which would
        # 404 "locations" as an unknown Microsoft.Compute type).
        if namespace.lower() == "microsoft.compute" and chain and chain[-1].lower() == "vmsizes":
            if method != "GET":
                return _err(405, "MethodNotAllowed", "vmSizes supports GET only.")
            return _ok({"value": _vm_sizes()})

        # Microsoft.Insights/eventtypes/management/values: the subscription-wide ARM activity
        # log read API (not resource-scoped — no "providers" re-entry — so it must be caught
        # before the generic type/name alternation below, which would misparse it).
        if namespace.lower() == "microsoft.insights" and chain and chain[0].lower() == "eventtypes":
            if method != "GET":
                return _err(405, "MethodNotAllowed", "Activity log supports GET only.")
            # One feed, two sources: the per-resource ARM entries this engine records
            # (eventtypes rows in self.state — e.g. Microsoft.Web writes) and the shared cloudsim event log
            # (nano_events — e.g. Event Grid / locks). Newest first, same $filter scoping.
            own = self._activity_log(method, query, sub)["body"].get("value", [])
            shared = _activity_log_query(query)["body"].get("value", [])
            seen = {e.get("id") for e in own}
            events = own + [e for e in shared if e.get("id") not in seen]
            # the timespan picker (eventTimestamp ge/le) narrows BOTH sources
            filt = query.get("$filter") or ""
            since = _parse_odata_ts(m.group(1)) if (m := re.search(r"eventTimestamp\s+ge\s+'([^']*)'", filt)) else None
            until = _parse_odata_ts(m.group(1)) if (m := re.search(r"eventTimestamp\s+le\s+'([^']*)'", filt)) else None
            if since is not None or until is not None:
                def _in_range(e):
                    ts = _parse_odata_ts(str(e.get("eventTimestamp") or ""))
                    return ts is None or ((since is None or ts >= since) and (until is None or ts <= until))
                events = [e for e in events if _in_range(e)]
            # sort by the parsed instant: the two sources write ms vs µs precision, which
            # string order gets wrong ("…47.463Z" > "…47.463441Z")
            _epoch = datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)
            events.sort(key=lambda e: _parse_odata_ts(str(e.get("eventTimestamp") or "")) or _epoch, reverse=True)
            return _ok({"value": events})

        # Microsoft.Authorization/locks scoped directly to the RESOURCE GROUP (or, with no
        # resourceGroups segment, the SUBSCRIPTION) itself — not a resource inside it:
        # .../resourceGroups/{rg}/providers/Microsoft.Authorization/locks or
        # .../subscriptions/{sub}/providers/Microsoft.Authorization/locks — namespace IS
        # Microsoft.Authorization already (no resource type precedes it), so the marker search
        # below (which looks for a re-entrant "providers" INSIDE chain) never fires; caught
        # here instead, scope_rid = the resource group's (or subscription's) own id.
        if namespace.lower() == "microsoft.authorization" and chain and chain[0].lower() == "locks":
            scope_rid = f"/subscriptions/{sub}/resourceGroups/{rg}" if rg is not None else f"/subscriptions/{sub}"
            return self._locks_crud(method, scope_rid, chain[1:], payload, rg or sub)

        # Microsoft.Authorization/checkAccess at the resource-group (or subscription) scope
        # itself — the real decision call behind the "Access control (IAM) > Check access" /
        # "My access" tabs: resolves the principal's role assignments AT OR ABOVE this scope
        # against the role's actions/notActions, same wildcard + explicit-deny-wins algorithm
        # azure_iam_core.py's checkAccess uses, applied to THIS store's own roleAssignments
        # (created as real, resource-group-scoped ARM resources — see the generic PUT branch
        # below, which stamps `properties.scope` from the containing resource group).
        if namespace.lower() == "microsoft.authorization" and chain and chain[0].lower() == "checkaccess":
            if method != "POST":
                return _err(405, "MethodNotAllowed", "checkAccess is a POST-only action.")
            scope_rid = f"/subscriptions/{sub}/resourceGroups/{rg}" if rg is not None else f"/subscriptions/{sub}"
            return self._check_access(sub, scope_rid, payload)

        # Microsoft.Authorization/roleDefinitions collection GET: the built-in Owner /
        # Contributor / Reader / … roles (ROLES, core/azure_arm_data.py — never provisioned as
        # catalog records, so the generic engine's own store never carries them) merged with
        # any custom role definitions created via PUT (which DO live in the generic catalog).
        if (namespace.lower() == "microsoft.authorization" and chain
                and chain[0].lower() == "roledefinitions" and len(chain) == 1):
            if method != "GET":
                return _err(405, "MethodNotAllowed", "Collection supports GET only.")
            return self._role_definitions_list(sub)

        # Microsoft Defender for Cloud (Microsoft.Security): subscription / resource-group scope,
        # computed live over this state (core/azure_security_core.py).
        if namespace.lower() == "microsoft.security":
            return self._security(method, sub, rg, chain, payload, query, None)
        # ...and resource-scoped (.../{type}/{name}/providers/Microsoft.Security/assessments[/…]).
        sec_marker = security_engine.find_marker(chain)
        if sec_marker is not None:
            stc, snames = [namespace], []
            for n, token in enumerate(chain[:sec_marker]):
                (stc if n % 2 == 0 else snames).append(token)
            scope_rid = _canonical_id(sub, rg, stc, snames)
            if self.state.get(scope_rid.lower()) is None:
                return _err(404, "ResourceNotFound", f"Resource '{scope_rid}' not found.")
            return self._security(method, sub, rg, chain[sec_marker + 2:], payload, query, scope_rid)

        # Microsoft.Authorization/locks: a real ARM extension resource scoped to ANY other
        # resource's own id (the chain re-enters "providers", like Event Grid's event
        # subscriptions) — generic over every catalog type, so caught before the alternation.
        lock_marker = locks_engine.find_marker(chain)
        if lock_marker is not None:
            return self._locks(method, sub, rg, namespace, chain, lock_marker, payload)

        # Microsoft.Insights/diagnosticSettings: a real ARM extension resource scoped to ANY
        # other resource's own id (chain re-enters "providers", same shape as locks above) —
        # generic over every catalog type, so caught before the alternation too.
        diag_marker = monitor_engine.find_diagnostic_marker(chain)
        if diag_marker is not None:
            return self._diagnostic_settings(method, sub, rg, namespace, chain, diag_marker, payload)

        # Microsoft.Insights/metrics: a real ARM extension resource scoped to ANY other
        # resource's own id (same shape as diagnosticSettings above) — v4 WAVE 5b, see
        # monitor_engine.get_storage_metrics / find_metrics_marker.
        metrics_marker = monitor_engine.find_metrics_marker(chain)
        if metrics_marker is not None:
            return self._metrics(method, sub, rg, namespace, chain, metrics_marker, query)

        # Microsoft.Authorization/roleAssignments: a real ARM extension resource that can be
        # READ scoped to ANY other resource's own id (chain re-enters "providers", same shape
        # as locks/diagnostic settings above) — real Azure's IAM blade lists assignments at that
        # exact scope plus its subscription/resource-group ancestors (inherited access), not the
        # whole subscription. Generic over every catalog type; GET-only (assignments are still
        # CREATED at the subscription scope, matching how az role assignment create/Entra work
        # today — this only narrows the READ for a resource's own IAM blade).
        role_marker = _role_assignment_marker(chain)
        if role_marker is not None:
            if method != "GET":
                return _err(405, "MethodNotAllowed", "Use the subscription-scoped roleAssignments path to write.")
            stc, snames = [namespace], []
            for n, token in enumerate(chain[:role_marker]):
                (stc if n % 2 == 0 else snames).append(token)
            scope_rid = _canonical_id(sub, rg, stc, snames).lower()
            ancestors = {scope_rid, f"/subscriptions/{sub}".lower()}
            if rg is not None:
                ancestors.add(f"/subscriptions/{sub}/resourcegroups/{rg}".lower())
            items = [_view(r) for r in self.state.values()
                     if r.get("_type", "").lower() == "microsoft.authorization/roleassignments"
                     and ((r.get("properties") or {}).get("scope") or "").rstrip("/").lower() in ancestors | {""}]
            return _ok({"value": items})

        # Microsoft.Authorization/checkAccess, resource-scoped: same re-entrant shape as the
        # roleAssignments READ above, generic over every catalog type — the decision call
        # behind any resource's own "Check access" / "My access" tab (the dedicated branch
        # near the top of this method only covers the resource-group/subscription scope).
        check_marker = _check_access_marker(chain)
        if check_marker is not None:
            if method != "POST":
                return _err(405, "MethodNotAllowed", "checkAccess is a POST-only action.")
            stc, snames = [namespace], []
            for n, token in enumerate(chain[:check_marker]):
                (stc if n % 2 == 0 else snames).append(token)
            scope_rid = _canonical_id(sub, rg, stc, snames)
            return self._check_access(sub, scope_rid, payload)

        # ARM type path alternates type/name: providers/<ns>/<t1>/<n1>/<t2>/<n2>...
        type_chain = [namespace]
        names: list = []
        for n, token in enumerate(chain):
            if n % 2 == 0:
                type_chain.append(token)
            else:
                names.append(token)
        is_collection = (len(chain) % 2 == 1)

        # Microsoft.AppConfiguration: the substrate-free engine owns the store / key-value semantics;
        # this class's flat store is its resource map (so it persists with the rest of ARM).
        if namespace.lower() == "microsoft.appconfiguration":
            return self._appconfig(method, sub, rg, chain, payload, query)

        # Microsoft.Network/dnsZones (+ record sets): the Azure DNS engine owns the zone semantics.
        if namespace.lower() == "microsoft.network" and dns_engine.handles(chain):
            return self._dns(method, sub, rg, chain, payload, query)

        # Microsoft.Insights (action groups, metric / activity log alerts, autoscale): the Azure Monitor engine.
        if namespace.lower() == "microsoft.insights" and monitor_engine.handles(chain):
            return self._monitor(method, sub, rg, chain, payload, query)

        # Microsoft.OperationalInsights (Log Analytics workspaces, saved searches, tables, data sources).
        if namespace.lower() == "microsoft.operationalinsights" and oi_engine.handles(chain):
            return self._oi(method, sub, rg, chain, payload, query)

        if namespace.lower() == "microsoft.cognitiveservices":
            return self._cogs(method, sub, rg, chain, payload, query)

        # Microsoft.CostManagement (cost query, alerts, exports) / Microsoft.Consumption
        # (budgets): the Cost Management engine owns both namespaces, sub/RG scoped, no
        # per-resource-group catalog entry (real Cost Management has none either).
        if namespace.lower() == "microsoft.costmanagement":
            return self._cost_cm(method, sub, rg, chain, payload, query)
        if namespace.lower() == "microsoft.consumption":
            return self._cost_consumption(method, sub, rg, chain, payload, query)
        if namespace.lower() == "microsoft.billingbenefits":
            return self._cost_billingbenefits(method, sub, rg, chain, payload, query)
        if namespace.lower() == "microsoft.capacity":
            return self._cost_capacity(method, sub, rg, chain, payload, query)
        # Microsoft.EventGrid/topics/{name}/providers/Microsoft.EventGrid/eventSubscriptions/{name}:
        # a real ARM extension resource (scoped to the topic), so the chain re-enters "providers"
        # instead of alternating type/name — the eventgrid engine owns that shape.
        if namespace.lower() == "microsoft.eventgrid" and eventgrid_engine.handles(chain):
            return self._eventgrid(method, sub, rg, chain, payload, query)

        # Microsoft.Web (App Service: web apps + function apps by `kind`, App Service plans): the
        # substrate-free engine owns the semantics (and writes the Activity log rows the
        # Microsoft.Insights eventtypes feed in the monitor engine reads back); this class's flat
        # store is its resource map (so it persists with the rest of ARM).
        if namespace.lower() == "microsoft.web":
            return self._web(method, sub, rg, chain, payload, query)

        top = _BY_TYPE.get((namespace.lower(), type_chain[1].lower()))
        if top is None:
            supported = ", ".join(sorted(c["namespace"] + "/" + c["type"] for c in CATALOG))
            return _err(404, "ResourceTypeNotSupported",
                        f"Type '{namespace}/{type_chain[1]}' is not simulated. Supported: {supported}.")

        # Microsoft.App (Container Apps): the substrate-free engine owns the semantics; this
        # class's flat store is its resource map (so it persists with the rest of ARM).
        if namespace.lower() == "microsoft.app":
            return self._app(method, sub, rg, chain, payload, query)

        # Network Watcher diagnostics → the shared netsim evaluator (same engine as Nano + enforcement)
        if (method == "POST" and namespace.lower() == "microsoft.network" and len(chain) == 3
                and chain[0].lower() == "networkwatchers" and chain[2].lower() in ("ipflowverify", "nexthop", "connectivitycheck")):
            if self.state.get(_canonical_id(sub, rg, type_chain[:2], names[:1]).lower()) is None:
                return _err(404, "ResourceNotFound", f"Network watcher '{names[0]}' not found.")
            return self._network_watcher(chain[2].lower(), payload or {})
        # POST action verbs (listKeys / start / powerOff / runCommand / …)
        if method == "POST" and is_collection and len(type_chain) >= 3 and names:
            parent_rid = _canonical_id(sub, rg, type_chain[:-1], names)
            return self._arm_action(type_chain[-1].lower(), type_chain, names[-1], parent_rid, payload, sub=sub, rg=rg)

        full_type = "/".join(type_chain)
        if is_collection:
            if method != "GET":
                return _err(405, "MethodNotAllowed", "Collection supports GET only.")
            # Nested child resources (e.g. registries/{reg}/webhooks) alternate type/name one
            # level deeper than their top catalog type — scope the list to the specific parent
            # instance, else two sibling parents' children would bleed into each other's list.
            parent_prefix = _canonical_id(sub, rg, type_chain[:-1], names).lower() + "/" if len(type_chain) > 2 else None
            return self._list(sub, rg, full_type, parent_prefix)

        rid = _canonical_id(sub, rg, type_chain, names)
        key = rid.lower()
        leaf_name = names[-1]
        api_version = query.get("api-version") or top.get("api_version") or "2023-01-01"
        lro = (len(type_chain) == 2 and namespace.lower() != "microsoft.authorization")

        if method == "GET":
            rec = self.state.get(key)
            if not rec:
                rec = _apim_default_policy(type_chain, names, self.state, rid)
            if not rec:
                return _err(404, "ResourceNotFound", f"Resource '{rid}' not found.")
            return _ok(_view(rec))
        if method in ("PUT", "PATCH"):
            blocked = self._lock_block(rid, full_type, for_delete=False)
            if blocked:
                return blocked
            blocked = self._servicebus_tier_block(type_chain, names, payload, sub, rg)
            if blocked:
                return blocked
            blocked = self._aks_stopped_block(type_chain, names, sub, rg)
            if blocked:
                return blocked
            blocked = self._aks_namespace_block(type_chain, names, payload, sub, rg)
            if blocked:
                return blocked
            blocked = self._storage_encryption_block(type_chain, names, payload, sub, rg)
            if blocked:
                return blocked
            blocked = self._storage_hns_block(type_chain, names, payload, sub, rg)
            if blocked:
                return blocked
            blocked = self._cosmos_validate_block(type_chain, names, payload, sub, rg)
            if blocked:
                return blocked
            blocked = self._apim_tier_block(type_chain, names, payload, sub, rg)
            if blocked:
                return blocked
            if full_type.lower() == "microsoft.authorization/roleassignments":
                # Real ARM derives a role assignment's scope from the resource ID it was PUT
                # under — not from a client-supplied properties.scope — so checkAccess and the
                # Role assignments list are genuinely scoped to the resource group they were
                # created at, instead of trusting whatever the caller sent (or sent nothing).
                # A client scope NARROWER than the path (a resource inside this group/subscription —
                # role assignments are written at the subscription/group path here) is kept;
                # anything else (missing, wider, unrelated) becomes the path's own scope.
                payload = dict(payload or {})
                path_scope = f"/subscriptions/{sub}/resourceGroups/{rg}" if rg is not None else f"/subscriptions/{sub}"
                asked = str((payload.get("properties") or {}).get("scope") or "").rstrip("/")
                inside = asked.lower().startswith(path_scope.lower() + "/")
                payload["properties"] = {**(payload.get("properties") or {}),
                                         "scope": asked if inside else path_scope}
            resp = self._upsert(rid, key, full_type, leaf_name, top, payload, base, patch=(method == "PATCH"))
            if resp["status"] >= 300:          # validation error from a type hook (e.g. NIC IP allocation)
                return resp
            if full_type.lower() == "microsoft.resources/deployments":
                # A bounded but REAL template evaluator (literal parameter/variable
                # substitution only — no expression language, no dependsOn ordering, no
                # nested/linked templates): every resource listed in properties.template.resources
                # is actually PUT through this same ARM dispatcher, not just stored inert.
                provisioned, errors = self._execute_deployment(sub, rg, self.state[key])
                rec = self.state[key]
                rec["properties"]["outputResources"] = provisioned
                if errors:
                    rec["properties"]["provisioningState"] = "Failed"
                    rec["properties"]["error"] = {"code": "DeploymentFailed", "details": errors}
                resp["body"] = _view(rec)
            if lro:
                resp["status"] = 200
                op_id = self._make_operation(rid, method)
                url = f"{base}/api/azure/operations/{op_id}?api-version={api_version}"
                resp["headers"].update({"Azure-AsyncOperation": url, "Location": url, "Retry-After": "0"})
            # One ARM-native eventtypes row per mutation (exact resourceId + real
            # resourceGroupName) — supersedes the generic nano_events feed for this call site,
            # so a resource group's Activity log can aggregate every resource inside it.
            self._record_activity(rid, f"{full_type}/write", sub)
            return resp
        if method == "DELETE":
            blocked = self._lock_block(rid, full_type, for_delete=True)
            if blocked:
                return blocked
            blocked = self._aks_stopped_block(type_chain, names, sub, rg)
            if blocked:
                return blocked
            rec = self.state.pop(key, None)
            if rec is not None:
                # Both extension resources (locks, … keyed "{parent id}/providers/<ext ns>/…")
                # and plain nested children (e.g. managedClusters/{c}/agentPools/{p}, keyed
                # "{parent id}/agentPools/{p}") cascade-delete with their parent in real ARM —
                # but NOT its own Activity log rows ("/__event__/" keys): real Azure keeps a
                # deleted resource's history in the log, it doesn't erase it.
                prefix = key + "/"
                for child_key in [k for k in self.state if k.startswith(prefix) and "/__event__/" not in k]:
                    del self.state[child_key]
                self._record_activity(rid, f"{full_type}/delete", sub)
            return _ok(None, status=200 if rec is not None else 204)
        return _err(405, "MethodNotAllowed", f"{method} not allowed.")

    def _lock_block(self, rid, full_type, for_delete):
        # Enforcement is scoped to Microsoft.ServiceBus (namespaces/queues/topics) and
        # Microsoft.EventGrid/topics only — every other resource type in this generic engine
        # still leaves Microsoft.Authorization/locks config_only (stored, not enforced),
        # matching their own capability registries.
        ft = full_type.lower()
        if not (ft.startswith("microsoft.servicebus/") or ft == "microsoft.eventgrid/topics"):
            return None
        levels = {(r.get("properties") or {}).get("level")
                  for r in self.state.values() if r.get("_lock_scope") == rid.lower()}
        if not levels:
            return None
        if for_delete or "ReadOnly" in levels:
            verb = "delete" if for_delete else "write"
            return _err(409, "ScopeLocked",
                        f"The scope '{rid}' cannot perform {verb} operation because the "
                        f"following scope(s) are locked: '{rid}'. Please remove the lock and try again.")
        return None

    def _servicebus_tier_block(self, type_chain, names, payload, sub, rg):
        # Real Service Bus rejects topics and session/duplicate-detection queues on a Basic
        # namespace, and messaging units / partitions are a Premium-only field — Vyomi now
        # ENFORCES those tier limits instead of just round-tripping whatever sku/properties
        # the caller sends (azure.servicebus.namespace.scale).
        if type_chain[0].lower() != "microsoft.servicebus" or type_chain[1].lower() != "namespaces":
            return None
        props = (payload or {}).get("properties") or {}
        if len(type_chain) == 2:
            existing = self.state.get(_canonical_id(sub, rg, type_chain, names).lower())
            sku = (payload or {}).get("sku") or {}
            tier = sku.get("tier") or sku.get("name") or (existing or {}).get("sku", {}).get("tier")
            if tier != "Premium":
                if sku.get("capacity") is not None:
                    return _err(400, "BadRequest",
                                "Messaging units (sku.capacity) require a Premium namespace.")
                if props.get("premiumMessagingPartitions") is not None:
                    return _err(400, "BadRequest",
                                "premiumMessagingPartitions requires a Premium namespace.")
            return None
        if len(type_chain) == 3 and type_chain[2].lower() in ("queues", "topics"):
            parent = self.state.get(_canonical_id(sub, rg, type_chain[:-1], names[:-1]).lower())
            tier = (parent or {}).get("sku", {}).get("tier")
            if tier != "Basic":
                return None
            if type_chain[2].lower() == "topics":
                return _err(400, "BadRequest",
                            "Topics are not supported on a Basic-tier Service Bus namespace.")
            if props.get("requiresSession"):
                return _err(400, "BadRequest",
                            "Sessions are not supported on a Basic-tier Service Bus namespace.")
            if props.get("requiresDuplicateDetection"):
                return _err(400, "BadRequest",
                            "Duplicate detection is not supported on a Basic-tier Service Bus namespace.")
        return None

    def _apim_tier_block(self, type_chain, names, payload, sub, rg):
        """Microsoft.ApiManagement/service sku.capacity — real APIM rejects a scale unit count
        the tier doesn't allow: Consumption is serverless (no scale units at all) and Developer
        is capped at exactly 1 (no scale-out, no SLA) — Vyomi now ENFORCES both instead of
        storing whatever sku the caller sends (azure.apim.scaletier). Checked against the
        EFFECTIVE sku (payload over existing), so a tier-only PATCH that would leave a stale,
        now-invalid capacity in place is rejected too, not just a capacity-only PATCH."""
        if type_chain[0].lower() != "microsoft.apimanagement" or type_chain[1].lower() != "service" or len(type_chain) != 2:
            return None
        sku = (payload or {}).get("sku")
        if not isinstance(sku, dict):
            return None
        existing_sku = (self.state.get(_canonical_id(sub, rg, type_chain, names).lower()) or {}).get("sku") or {}
        tier = sku.get("name", existing_sku.get("name"))
        capacity = sku.get("capacity", existing_sku.get("capacity"))
        if tier == "Consumption" and capacity not in (None, 0):
            return _err(400, "BadRequest", "The Consumption tier has no scale units — sku.capacity must be 0.")
        if tier == "Developer" and capacity not in (None, 1):
            return _err(400, "BadRequest", "The Developer tier is capped at exactly 1 unit (no scale-out, no SLA).")
        return None

    def _aks_stopped_block(self, type_chain, names, sub, rg):
        # Real AKS rejects node-pool create/scale/upgrade/delete while the cluster itself is
        # Stopped ("start the cluster before performing this operation") — Vyomi now ENFORCES
        # that instead of letting agentPools writes silently succeed against a stopped cluster
        # (azure.aks.cluster.power / azure.aks.node_pools.crud).
        if len(type_chain) != 3 or type_chain[0].lower() != "microsoft.containerservice" \
                or type_chain[1].lower() != "managedclusters" or type_chain[2].lower() != "agentpools":
            return None
        cluster = self.state.get(_canonical_id(sub, rg, type_chain[:-1], names[:-1]).lower())
        if (cluster or {}).get("properties", {}).get("powerState", {}).get("code") == "Stopped":
            return _err(409, "ClusterNotRunning",
                        "The cluster is stopped. Start the cluster before performing operations on its node pools.")
        return None

    _AKS_PROTECTED_NAMESPACES = {"default", "kube-system", "kube-public", "kube-node-lease"}

    def _aks_namespace_block(self, type_chain, names, payload, sub, rg):
        # A write to properties.namespaces goes through the cluster's own generic PUT/PATCH
        # (api.js's addNamespace/deleteNamespace send the whole array back) — this is the one
        # AKS-specific validation layered on top of that: the console's Namespaces blade never
        # lets default/kube-system/kube-public/kube-node-lease be deleted (same restriction the
        # real "Managed namespaces" preview enforces), and a namespace write needs the same
        # running API server a node-pool write does (azure.aks.namespaces).
        if len(type_chain) != 2 or type_chain[0].lower() != "microsoft.containerservice" \
                or type_chain[1].lower() != "managedclusters":
            return None
        new_ns = (payload or {}).get("properties", {}).get("namespaces")
        if new_ns is None:
            return None
        rid = _canonical_id(sub, rg, type_chain, names)
        cluster = self.state.get(rid.lower())
        current = {n.get("name") for n in (cluster or {}).get("properties", {}).get("namespaces") or []}
        requested = {n.get("name") for n in new_ns}
        removed = current - requested
        protected_removed = removed & self._AKS_PROTECTED_NAMESPACES
        if protected_removed:
            return _err(409, "ProtectedNamespace",
                        f"The namespace(s) {', '.join(sorted(protected_removed))} are system namespaces and cannot be deleted.")
        if removed or (requested - current):
            if (cluster or {}).get("properties", {}).get("powerState", {}).get("code") == "Stopped":
                return _err(409, "ClusterNotRunning",
                            "The cluster is stopped. Start the cluster before creating or deleting namespaces.")
        return None

    _VAULT_URI_RE = re.compile(r"^https?://([a-z0-9-]+)\.vault\.azure\.net/?$", re.I)

    def _storage_encryption_block(self, type_chain, names, payload, sub, rg):
        # v4 WAVE 5b (azure.storage.encryption): real Azure rejects a customer-managed-key
        # selection that doesn't actually name a Key Vault key — Vyomi now ENFORCES the
        # structural shape (keyvaulturi + keyname required) and that the vault URI resolves
        # to a REAL Key Vault in this subscription, instead of round-tripping whatever
        # encryption.keySource/keyvaultproperties the caller sends. The named KEY's own
        # existence/enabled state inside that vault is still not checked (core/azure_arm_core.py
        # has no reference to the Key Vault keys data-plane store) — an honest, narrower gap.
        if type_chain[0].lower() != "microsoft.storage" or type_chain[1].lower() != "storageaccounts" \
                or len(type_chain) != 2:
            return None
        props = (payload or {}).get("properties") or {}
        enc = props.get("encryption")
        if not isinstance(enc, dict) or enc.get("keySource") != "Microsoft.Keyvault":
            return None
        kv = enc.get("keyvaultproperties") or {}
        uri, key_name = kv.get("keyvaulturi"), kv.get("keyname")
        if not uri or not key_name:
            return _err(400, "BadRequest",
                        "encryption.keyvaultproperties.keyvaulturi and .keyname are required "
                        "when encryption.keySource is 'Microsoft.Keyvault'.")
        m = self._VAULT_URI_RE.match(uri)
        vault_exists = bool(m) and any(
            r.get("_type", "").lower() == "microsoft.keyvault/vaults"
            and r.get("id", "").lower().endswith(f"/vaults/{m.group(1).lower()}")
            for r in self.state.values())
        if not vault_exists:
            return _err(400, "BadRequest",
                        f"The Key Vault referenced by encryption.keyvaultproperties.keyvaulturi "
                        f"('{uri}') does not exist in this subscription.")
        return None

    def _storage_hns_block(self, type_chain, names, payload, sub, rg):
        # v4 WAVE 5b (azure.storage.datalakegen2upgrade): the Data Lake Gen2 upgrade flips
        # isHnsEnabled false -> true on an EXISTING account — a one-way migration real Azure
        # only allows from a general-purpose v2 (or Premium block blob) account. Vyomi now
        # ENFORCES both the eligibility and the one-way-ness instead of round-tripping
        # whatever isHnsEnabled the caller sends.
        if type_chain[0].lower() != "microsoft.storage" or type_chain[1].lower() != "storageaccounts" \
                or len(type_chain) != 2:
            return None
        props = (payload or {}).get("properties") or {}
        if "isHnsEnabled" not in props:
            return None
        existing = self.state.get(_canonical_id(sub, rg, type_chain, names).lower())
        was = bool((existing or {}).get("properties", {}).get("isHnsEnabled"))
        now = bool(props["isHnsEnabled"])
        if was == now:
            return None
        if was and not now:
            return _err(400, "BadRequest",
                        "Hierarchical namespace cannot be disabled once enabled (Data Lake "
                        "Gen2 upgrade is one-way).")
        kind = (payload or {}).get("kind") or (existing or {}).get("kind")
        if existing is not None and kind not in ("StorageV2", "BlockBlobStorage"):
            return _err(400, "BadRequest",
                        "Hierarchical namespace (Data Lake Gen2) requires a general-purpose v2 "
                        "or premium block blob storage account.")
        return None

    def _cosmos_validate_block(self, type_chain, names, payload, sub, rg):
        # Real Cosmos DB ARM rejects an invalid consistencyPolicy / backupPolicy / locations
        # shape outright — Vyomi now ENFORCES that contract instead of round-tripping whatever
        # the caller sends (azure.cosmos.default_consistency, azure.cosmos.backup_restore,
        # azure.cosmos.replicate_data_globally); the underlying behaviour (read consistency,
        # taking/restoring a backup, provisioning a second region) is still not simulated.
        if type_chain[0].lower() != "microsoft.documentdb" or type_chain[1].lower() != "databaseaccounts" or len(type_chain) != 2:
            return None
        existing_props = (self.state.get(_canonical_id(sub, rg, type_chain, names).lower()) or {}).get("properties") or {}
        payload_props = (payload or {}).get("properties") or {}
        props = _merge(existing_props, payload_props) if payload_props else existing_props

        cp = props.get("consistencyPolicy")
        if isinstance(cp, dict):
            level = cp.get("defaultConsistencyLevel", "Session")
            if level not in ("Strong", "BoundedStaleness", "Session", "ConsistentPrefix", "Eventual"):
                return _err(400, "BadRequest", f"Unsupported consistencyPolicy.defaultConsistencyLevel '{level}'.")
            if level == "BoundedStaleness":
                prefix, interval = cp.get("maxStalenessPrefix"), cp.get("maxIntervalInSeconds")
                if not isinstance(prefix, int) or not isinstance(interval, int):
                    return _err(400, "BadRequest",
                                "BoundedStaleness requires integer consistencyPolicy.maxStalenessPrefix and maxIntervalInSeconds.")
                if not (10 <= prefix <= 2147483647):
                    return _err(400, "BadRequest", "consistencyPolicy.maxStalenessPrefix must be between 10 and 2147483647.")
                if not (5 <= interval <= 86400):
                    return _err(400, "BadRequest", "consistencyPolicy.maxIntervalInSeconds must be between 5 and 86400.")

        bp = props.get("backupPolicy")
        if isinstance(bp, dict):
            btype = bp.get("type", "Periodic")
            if btype not in ("Periodic", "Continuous"):
                return _err(400, "BadRequest", f"Unsupported backupPolicy.type '{btype}'.")
            existing_type = (existing_props.get("backupPolicy") or {}).get("type", "Periodic")
            if existing_type == "Continuous" and btype == "Periodic":
                return _err(400, "BadRequest",
                            "Migrating an account's backup policy from Continuous to Periodic mode is not supported.")
            if btype == "Periodic":
                pm = bp.get("periodicModeProperties") or {}
                interval = pm.get("backupIntervalInMinutes", 240)
                retention = pm.get("backupRetentionIntervalInHours", 8)
                redundancy = pm.get("backupStorageRedundancy", "Geo")
                if not isinstance(interval, int) or not (60 <= interval <= 1440):
                    return _err(400, "BadRequest", "periodicModeProperties.backupIntervalInMinutes must be between 60 and 1440.")
                if not isinstance(retention, int) or not (8 <= retention <= 720):
                    return _err(400, "BadRequest", "periodicModeProperties.backupRetentionIntervalInHours must be between 8 and 720.")
                if redundancy not in ("Geo", "Zone", "Local"):
                    return _err(400, "BadRequest", f"Unsupported periodicModeProperties.backupStorageRedundancy '{redundancy}'.")
            else:
                tier = (bp.get("continuousModeProperties") or {}).get("tier", "Continuous30Days")
                if tier not in ("Continuous7Days", "Continuous30Days"):
                    return _err(400, "BadRequest", f"Unsupported continuousModeProperties.tier '{tier}'.")

        locations = props.get("locations")
        if isinstance(locations, list) and locations:
            loc_names = [l.get("locationName") for l in locations]
            if len(set(loc_names)) != len(loc_names):
                return _err(400, "BadRequest", "properties.locations cannot repeat the same locationName.")
            prios = sorted(l.get("failoverPriority") for l in locations)
            if prios != list(range(len(locations))):
                return _err(400, "BadRequest",
                            "properties.locations.failoverPriority must be a 0-based, gap-free sequence with exactly one region at priority 0.")
        return None

    def _security(self, method, sub, rg, chain, payload, query, scope_rid):
        r = security_engine.dispatch(self.state, method, sub, rg, chain, payload or {}, query or {}, scope_rid)
        if r["status"] < 300 and method in ("PUT", "PATCH") and chain[:1] and chain[0].lower() == "pricings":
            self._record_activity(f"/subscriptions/{sub}/providers/Microsoft.Security/pricings/{chain[1] if len(chain) > 1 else ''}",
                                  "Microsoft.Security/pricings/write", sub)
        return {"status": r["status"], "headers": r.get("headers") or {}, "body": r["body"]}

    def _locks(self, method, sub, rg, namespace, chain, marker, payload):
        # Replay the SAME type/name alternation the main dispatcher uses (see `_arm` above)
        # over everything before the "providers/Microsoft.Authorization/locks" marker.
        stc, snames = [namespace], []
        for n, token in enumerate(chain[:marker]):
            (stc if n % 2 == 0 else snames).append(token)
        scope_rid = _canonical_id(sub, rg, stc, snames)
        rest = chain[marker + 3:]
        return self._locks_crud(method, scope_rid, rest, payload, snames[-1] if snames else scope_rid)

    def _locks_crud(self, method, scope_rid, rest, payload, activity_name):
        if not rest:
            if method != "GET":
                return _err(405, "MethodNotAllowed", "Collection supports GET only.")
            r = locks_engine.list_for(self.state, scope_rid)
        else:
            name = rest[0]
            if method == "GET":
                r = locks_engine.get(self.state, scope_rid, name)
            elif method in ("PUT", "PATCH"):
                r = locks_engine.upsert(self.state, scope_rid, name, payload)
                if r["status"] in (200, 201):
                    _record_activity(activity_name, "Create lock" if r["status"] == 201 else "Update lock", name)
            elif method == "DELETE":
                r = locks_engine.remove(self.state, scope_rid, name)
                if r["status"] == 200:
                    _record_activity(activity_name, "Delete lock", name)
            else:
                return _err(405, "MethodNotAllowed", f"{method} not allowed.")
        return {"status": r["status"], "headers": {}, "body": r["body"]}

    # ── Azure RBAC (role assignments created as real, resource-group-scoped ARM resources) ──
    def _role_catalog(self, sub):
        """{roleName: {actions, notActions, custom, description, id}} — the built-in roles
        (ROLES, never provisioned as catalog records) merged with any custom role definitions
        created via PUT .../roleDefinitions/{name} (which DO live in self.state)."""
        out = {}
        for r in ROLES:
            props = r["properties"]
            actions, not_actions = [], []
            for p in props.get("permissions") or []:
                actions.extend(p.get("actions") or [])
                not_actions.extend(p.get("notActions") or [])
            out[props["roleName"]] = {"roleName": props["roleName"], "actions": actions, "notActions": not_actions,
                                      "custom": False, "description": props.get("description", ""), "id": r["id"]}
        for rec in self.state.values():
            if rec.get("_type", "").lower() != "microsoft.authorization/roledefinitions" or rec.get("_sub") != sub:
                continue
            props = rec.get("properties") or {}
            actions, not_actions = [], []
            for p in props.get("permissions") or []:
                actions.extend(p.get("actions") or [])
                not_actions.extend(p.get("notActions") or [])
            out[rec["name"]] = {"roleName": rec["name"], "actions": actions, "notActions": not_actions,
                                "custom": True, "description": props.get("description", ""), "id": rec["id"]}
        return out

    def _role_assignments(self, sub):
        return [rec for rec in self.state.values()
                if rec.get("_type", "").lower() == "microsoft.authorization/roleassignments" and rec.get("_sub") == sub]

    def _role_definitions_list(self, sub):
        roles = self._role_catalog(sub)
        counts = {}
        for rec in self._role_assignments(sub):
            props = rec.get("properties") or {}
            if str(props.get("kind", "allow")).lower() == "deny":
                continue
            role_name = props.get("roleName") or (props.get("roleDefinitionId") or "").rsplit("/", 1)[-1]
            counts[role_name] = counts.get(role_name, 0) + 1
        value = [{
            "id": info["id"], "name": name,
            "properties": {
                "roleName": name, "type": "CustomRole" if info["custom"] else "BuiltInRole",
                "description": info["description"], "assignableScopes": ["/"],
                "permissions": [{"actions": info["actions"], "notActions": info["notActions"]}],
            },
            "assignmentCount": counts.get(name, 0),
        } for name, info in roles.items()]
        return _ok({"value": value})

    def _check_access(self, sub, scope_rid, payload):
        payload = payload or {}
        subject = payload.get("subject") or {}
        principal_id = payload.get("principalId") or subject.get("principalId") or ""
        actions = payload.get("actions")
        if actions is None:
            single = payload.get("action") or ""
            actions = [{"id": single}] if single else []
        roles = self._role_catalog(sub)
        assignments = self._role_assignments(sub)
        results = []
        for a in actions:
            act = a.get("id") if isinstance(a, dict) else str(a)
            allowed, denied, granting = False, False, []
            for rec in assignments:
                props = rec.get("properties") or {}
                if props.get("principalId") != principal_id:
                    continue
                if not iam_engine._scope_covers(props.get("scope", "/"), scope_rid):
                    continue
                if str(props.get("kind", "allow")).lower() == "deny":
                    if iam_engine._matches_any(props.get("denyActions"), act):
                        denied = True
                    continue
                role_name = props.get("roleName") or (props.get("roleDefinitionId") or "").rsplit("/", 1)[-1]
                role = roles.get(role_name)
                if not role:
                    continue
                if iam_engine._matches_any(role["actions"], act) and not iam_engine._matches_any(role["notActions"], act):
                    allowed = True
                    granting.append(role_name)
            results.append({"actionId": act, "accessDecision": "Allowed" if (allowed and not denied) else "NotAllowed",
                            "roles": granting})
        return _ok({"value": results})

    # ── deployments (Microsoft.Resources/deployments): a bounded real template evaluator ────
    def _execute_deployment(self, sub, rg, rec):
        """PUT every resource listed in properties.template.resources through THIS SAME ARM
        dispatcher — so a deployment actually provisions something, not just stores a record
        of what was asked for. [parameters('x')] / [variables('y')] resolve to literal values
        (properties.parameters, falling back to the template's own defaultValue); any other
        ARM template function (concat/resourceId/reference/copy loops) is left as-is, so that
        resource's own PUT will fail its own validation rather than silently "succeed"."""
        props = rec.get("properties") or {}
        template = props.get("template") or {}
        resources = template.get("resources")
        if not isinstance(resources, list) or not resources:
            return [], []
        values = {k: v.get("defaultValue") for k, v in (template.get("parameters") or {}).items()}
        for k, v in (props.get("parameters") or {}).items():
            values[k] = v.get("value", v) if isinstance(v, dict) else v
        variables = template.get("variables") or {}
        provisioned, errors = [], []
        for entry in resources:
            entry = _resolve_template_expr(entry, values, variables)
            rtype, rname = entry.get("type"), entry.get("name")
            if not rtype or not rname:
                errors.append({"error": "a template resource is missing type/name"})
                continue
            path = (f"/subscriptions/{sub}/resourceGroups/{rg}/providers/{rtype}/{rname}" if rg is not None
                   else f"/subscriptions/{sub}/providers/{rtype}/{rname}")
            body = {k: v for k, v in entry.items() if k not in ("type", "name", "apiVersion", "dependsOn", "condition", "comments")}
            resp = self.handle("PUT", path, {"api-version": entry.get("apiVersion")} if entry.get("apiVersion") else {}, body)
            if resp["status"] >= 400:
                errors.append({"resource": f"{rtype}/{rname}", "status": resp["status"], "error": resp["body"]})
            else:
                provisioned.append({"id": resp["body"].get("id", path), "resourceType": rtype, "resourceName": rname})
        return provisioned, errors

    def _deployment_action(self, action, name, rid, sub, rg):
        rec = self.state.get(rid.lower())
        if not rec:
            return _err(404, "DeploymentNotFound", f"Deployment '{name}' could not be found.")
        if action == "cancel":
            # Every simulated deployment completes synchronously (see the generic PUT branch),
            # so by the time a Cancel call can reach it, it is already in a terminal state —
            # the same conflict a real deployment that finished before Cancel arrived returns.
            state_now = (rec.get("properties") or {}).get("provisioningState", "Succeeded")
            return _err(409, "DeploymentNotCancellable",
                        f"Deployment '{name}' cannot be cancelled: it is already in the terminal "
                        f"state '{state_now}'.")
        # redeploy: re-run the SAME stored template/parameters against current state.
        provisioned, errors = self._execute_deployment(sub, rg, rec)
        rec["properties"]["outputResources"] = provisioned
        if errors:
            rec["properties"]["provisioningState"] = "Failed"
            rec["properties"]["error"] = {"code": "DeploymentFailed", "details": errors}
        else:
            rec["properties"]["provisioningState"] = "Succeeded"
            rec["properties"].pop("error", None)
        rec["properties"]["timestamp"] = _now()
        self._record_activity(rid, "Microsoft.Resources/deployments/redeploy/action", sub)
        return _ok(_view(rec))

    def _diagnostic_settings(self, method, sub, rg, namespace, chain, marker, payload):
        # Replay the SAME type/name alternation the main dispatcher uses (see `_arm` above)
        # over everything before the "providers/Microsoft.Insights/diagnosticSettings" marker.
        stc, snames = [namespace], []
        for n, token in enumerate(chain[:marker]):
            (stc if n % 2 == 0 else snames).append(token)
        scope_rid = _canonical_id(sub, rg, stc, snames)
        rest = chain[marker + 3:]
        activity_name = snames[-1] if snames else scope_rid
        if not rest:
            if method != "GET":
                return _err(405, "MethodNotAllowed", "Collection supports GET only.")
            r = monitor_engine.list_diagnostic_settings(self.state, scope_rid)
        else:
            name = rest[0]
            if method == "GET":
                r = monitor_engine.get_diagnostic_setting(self.state, scope_rid, name)
            elif method in ("PUT", "PATCH"):
                r = monitor_engine.upsert_diagnostic_setting(self.state, scope_rid, name, payload)
                if r["status"] in (200, 201):
                    _record_activity(activity_name, "Create diagnostic setting" if r["status"] == 201 else "Update diagnostic setting", name)
            elif method == "DELETE":
                r = monitor_engine.remove_diagnostic_setting(self.state, scope_rid, name)
                if r["status"] == 200:
                    _record_activity(activity_name, "Delete diagnostic setting", name)
            else:
                return _err(405, "MethodNotAllowed", f"{method} not allowed.")
        return {"status": r["status"], "headers": dict(r["headers"]), "body": r["body"]}

    def _metrics(self, method, sub, rg, namespace, chain, marker, query):
        # v4 WAVE 5b — Microsoft.Insights/metrics, read-only (see monitor_engine.get_storage_metrics).
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Metrics supports GET only.")
        stc, snames = [namespace], []
        for n, token in enumerate(chain[:marker]):
            (stc if n % 2 == 0 else snames).append(token)
        scope_rid = _canonical_id(sub, rg, stc, snames)
        rec = self.state.get(scope_rid.lower())
        if rec is None:
            return _err(404, "ResourceNotFound", f"Resource '{scope_rid}' not found.")
        if rec.get("_type", "").lower() != "microsoft.storage/storageaccounts" or self.blob_store is None:
            # Genuinely not modelled for any other resource type yet (see azure_monitor_core
            # docstring) — an empty, valid series, not an error.
            return _ok({"cost": 0, "timespan": query.get("timespan", ""), "interval": "PT1H", "value": []})
        r = monitor_engine.get_storage_metrics(self.blob_store, snames[-1].lower(), query)
        return {"status": r["status"], "headers": dict(r["headers"]), "body": r["body"]}

    def _dns(self, method, sub, rg, chain, payload, query):
        dn = dns_engine
        r = dn.dispatch(self.state, method, sub, rg, chain, [], payload, query, base=self._base)
        resp = {"status": r["status"], "headers": {}, "body": r["body"]}
        if r["lro"] and r["status"] < 300:
            op_id = self._make_operation(r["rid"], method)
            url = f"{self._base}/api/azure/operations/{op_id}?api-version={query.get('api-version') or dn.API_VERSION}"
            resp["headers"].update({"Azure-AsyncOperation": url, "Location": url, "Retry-After": "0"})
        return resp

    def _monitor(self, method, sub, rg, chain, payload, query):
        r = monitor_engine.dispatch(self.state, method, sub, rg, chain, [], payload, query, base=self._base)
        return {"status": r["status"], "headers": dict(r["headers"]), "body": r["body"]}

    def _oi(self, method, sub, rg, chain, payload, query):
        r = oi_engine.dispatch(self.state, method, sub, rg, chain, [], payload, query, base=self._base)
        resp = {"status": r["status"], "headers": dict(r["headers"]), "body": r["body"]}
        if r["lro"] and r["status"] < 300:
            op_id = self._make_operation(r["rid"], method)
            url = f"{self._base}/api/azure/operations/{op_id}?api-version={query.get('api-version') or oi_engine.API_VERSION}"
            resp["headers"].update({"Azure-AsyncOperation": url, "Location": url, "Retry-After": "0"})
        # oi_engine owns workspace CRUD itself (unlike the generic alternating-type path above,
        # which stamps every write/delete via self._record_activity at the call site) — stamp the
        # SAME eventtypes row here so a workspace's own Activity log panel (and the generic
        # subscription-wide feed the KQL AzureActivity table reads) see workspace mutations too.
        if r.get("rid") and r["status"] < 300:
            self._record_activity(r["rid"], f"{oi_engine.WS_TYPE}/{'delete' if r['verb'] == 'delete' else 'write'}", sub)
        return resp

    def _cogs(self, method, sub, rg, chain, payload, query):
        cs = cogs_engine
        r = cs.dispatch(self.state, method, sub, rg, chain, [], payload, query)
        resp = {"status": r["status"], "headers": {}, "body": r["body"]}
        if r["lro"] and r["status"] < 300:
            resp["status"] = 200 if r["status"] == 201 else r["status"]
            op_id = self._make_operation(r["rid"], method)
            url = f"{self._base}/api/azure/operations/{op_id}?api-version={query.get('api-version') or cs.API_VERSION}"
            resp["headers"].update({"Azure-AsyncOperation": url, "Location": url, "Retry-After": "0"})
        return resp

    def _eventgrid(self, method, sub, rg, chain, payload, query):
        r = eventgrid_engine.dispatch(self.state, method, sub, rg, chain, [], payload, query, base=self._base)
        # chain: ['topics', '<topic>', 'providers', 'Microsoft.EventGrid', 'eventSubscriptions', '<name>?']
        if method in ("PUT", "PATCH", "DELETE") and r["status"] in (200, 201, 204) and len(chain) >= 6:
            verb = {"PUT": "Update" if r["status"] == 200 else "Create", "PATCH": "Update", "DELETE": "Delete"}[method]
            _record_activity(chain[1], f"{verb} subscription", chain[5])
        return {"status": r["status"], "headers": dict(r["headers"]), "body": r["body"]}

    def _appconfig(self, method, sub, rg, chain, payload, query):
        ac = appconfig_engine
        r = ac.dispatch(self.state, method, sub, rg, chain, [], payload, query)
        resp = {"status": r["status"], "headers": {}, "body": r["body"]}
        if r["lro"] and r["status"] < 300:
            resp["status"] = 200 if r["status"] == 201 else r["status"]
            op_id = self._make_operation(r["rid"], method)
            url = f"{self._base}/api/azure/operations/{op_id}?api-version={query.get('api-version') or ac.API_VERSION}"
            resp["headers"].update({"Azure-AsyncOperation": url, "Location": url, "Retry-After": "0"})
        return resp

    def _app(self, method, sub, rg, chain, payload, query):
        app = app_engine
        r = app.dispatch(self.state, method, sub, rg, chain, [], payload, query)
        resp = {"status": r["status"], "headers": {}, "body": r["body"]}
        if r["lro"] and r["status"] < 300:
            resp["status"] = 200 if r["status"] == 201 else r["status"]
            result = r["body"] if r["verb"] == "start" and chain[0].lower() == "jobs" else None
            op_id = self._make_operation(r["rid"], method, result)
            url = f"{self._base}/api/azure/operations/{op_id}?api-version={query.get('api-version') or app.API_VERSION}"
            resp["headers"].update({"Azure-AsyncOperation": url, "Location": url, "Retry-After": "0"})
        return resp

    def _cost_cm(self, method, sub, rg, chain, payload, query):
        r = cost_engine.dispatch_costmanagement(self.state, method, sub, rg, chain, payload, query, base=self._base)
        return {"status": r["status"], "headers": dict(r["headers"]), "body": r["body"]}

    def _cost_consumption(self, method, sub, rg, chain, payload, query):
        r = cost_engine.dispatch_consumption(self.state, method, sub, rg, chain, payload, query, base=self._base)
        return {"status": r["status"], "headers": dict(r["headers"]), "body": r["body"]}

    def _cost_billingbenefits(self, method, sub, rg, chain, payload, query):
        r = cost_engine.dispatch_billingbenefits(self.state, method, sub, chain, payload, query, base=self._base)
        return {"status": r["status"], "headers": dict(r["headers"]), "body": r["body"]}

    def _cost_capacity(self, method, sub, rg, chain, payload, query):
        r = cost_engine.dispatch_capacity(self.state, method, sub, chain, payload, query, base=self._base)
        return {"status": r["status"], "headers": dict(r["headers"]), "body": r["body"]}

    def _web(self, method, sub, rg, chain, payload, query):
        r = web_engine.dispatch(self.state, method, sub, rg, chain, [], payload, query)
        resp = {"status": r["status"], "headers": {}, "body": r["body"]}
        if r["lro"] and r["status"] < 300:
            resp["status"] = 200 if r["status"] == 201 else r["status"]
            op_id = self._make_operation(r["rid"], method)
            url = f"{self._base}/api/azure/operations/{op_id}?api-version={query.get('api-version') or web_engine.API_VERSION}"
            resp["headers"].update({"Azure-AsyncOperation": url, "Location": url, "Retry-After": "0"})
        return resp

    # ── CRUD primitives ───────────────────────────────────────────────────
    def _list(self, sub, rg, full_type, parent_prefix=None):
        ft = full_type.lower()
        items = []
        for rec in self.state.values():
            if rec.get("_type", "").lower() != ft:
                continue
            if rec.get("_sub") != sub:
                continue
            if rg is not None and (rec.get("_rg") or "").lower() != rg.lower():
                continue
            if parent_prefix and not rec.get("id", "").lower().startswith(parent_prefix):
                continue
            items.append(_view(rec))
        return _ok({"value": items})

    def _upsert(self, rid, key, full_type, name, catalog, payload, base, patch=False):
        existed = key in self.state
        is_top = full_type.lower() == (catalog["namespace"] + "/" + catalog["type"]).lower()
        defaults = _expand_tokens(catalog.get("defaults", {}), name, base) if is_top else {"properties": {"provisioningState": "Succeeded"}}
        endpoints = catalog.get("endpoints", {}) if is_top else {}

        if patch and existed:
            rec = self.state[key]
        else:
            rec = {"id": rid, "name": name, "type": full_type,
                   "location": payload.get("location") or DEFAULT_LOCATION,
                   "tags": {}, "properties": {},
                   "_type": full_type, "_sub": rid.split("/")[2],
                   "_rg": _rg_from_id(rid), "_created": _now()}
            for dk, dv in defaults.items():
                rec[dk] = dv if not isinstance(dv, dict) else dict(dv)

        for fld in ("location", "kind"):
            if payload.get(fld) is not None:
                rec[fld] = payload[fld]
        if isinstance(payload.get("tags"), dict):
            rec["tags"] = _merge(rec.get("tags", {}), payload["tags"])
        if isinstance(payload.get("sku"), dict):
            rec["sku"] = _merge(rec.get("sku", {}), payload["sku"])
        if isinstance(payload.get("identity"), dict):
            rec["identity"] = _merge(rec.get("identity", {}), payload["identity"])
        if isinstance(payload.get("properties"), dict):
            rec["properties"] = _merge(rec.get("properties", {}), payload["properties"])

        rec.setdefault("properties", {})
        rec["properties"].setdefault("provisioningState", "Succeeded")
        for path_expr, suffix in endpoints.items():
            if _get_path(rec, path_expr) in (None, ""):
                _set_path(rec, path_expr, base + suffix.replace("__NAME__", name))
        # systemData.createdAt/lastModifiedAt: real ARM returns this on every resource; the
        # Overview "Created"/"Updated" fields some blades show read it back.
        rec["systemData"] = {"createdAt": rec.get("_created", _now()), "lastModifiedAt": _now()}

        if full_type.lower() == "microsoft.network/networkinterfaces":
            bad = self._nic_ips(key, rec)
            if bad is not None:
                if not existed:
                    self.state.pop(key, None)
                return bad
        if full_type.lower() == "microsoft.network/virtualnetworks":
            self._sync_inline_subnets(rid, rec)
        self.state[key] = rec
        return _ok(_view(rec), status=200 if existed else 201)

    def _sync_inline_subnets(self, vnet_rid, vnet_rec):
        """A virtualNetwork PUT/PATCH may define its subnets inline (properties.subnets) —
        real Azure's much more common pattern than the dedicated .../subnets/{name} PUT, and
        treats both the same: one shared subnet collection, individually gettable and listable
        either way. Mirror each inline subnet into its own flat state entry (the same shape
        the dedicated PUT creates) so GET/LIST on the nested subnets path — and anything built
        on it, e.g. the NSG blade's Subnets/Effective security rules association scan — sees it too."""
        for s in (vnet_rec.get("properties") or {}).get("subnets") or []:
            name = s.get("name")
            if not name:
                continue
            sid = f"{vnet_rid}/subnets/{name}"
            key = sid.lower()
            rec = self.state.get(key) or {
                "id": sid, "name": name, "type": "Microsoft.Network/virtualNetworks/subnets",
                "_type": "microsoft.network/virtualnetworks/subnets",
                "_sub": vnet_rec.get("_sub"), "_rg": vnet_rec.get("_rg"), "_created": _now(),
            }
            rec["properties"] = dict(s.get("properties") or {})
            rec["properties"].setdefault("provisioningState", "Succeeded")
            rec["systemData"] = {"createdAt": rec.get("_created", _now()), "lastModifiedAt": _now()}
            self.state[key] = rec

    # ── netsim: NIC private-IP allocation + Network Watcher (IP flow verify / next hop) ──
    def _subnet_prefix(self, subnet_id: str):
        sid = str(subnet_id or "").lower()
        rec = self.state.get(sid)
        if rec:
            p = rec.get("properties") or {}
            return p.get("addressPrefix") or (p.get("addressPrefixes") or [None])[0]
        vnet_id, _, name = sid.rpartition("/subnets/")
        vnet = self.state.get(vnet_id)
        for s in ((vnet or {}).get("properties") or {}).get("subnets") or []:
            if str(s.get("name", "")).lower() == name:
                p = s.get("properties") or {}
                return p.get("addressPrefix") or (p.get("addressPrefixes") or [None])[0]
        return None

    def _nic_ips(self, key: str, rec: dict):
        """Azure allocates a NIC ipConfiguration's private IP from its subnet (first four and the
        last address reserved); a Static address must be in the subnet and free."""
        import ipaddress
        used = {}
        for k, other in self.state.items():
            if k == key or "/providers/microsoft.network/networkinterfaces/" not in k or k.count("/") != 8:
                continue
            for ipc in (other.get("properties") or {}).get("ipConfigurations") or []:
                p = ipc.get("properties") or {}
                used.setdefault(str((p.get("subnet") or {}).get("id", "")).lower(), set()).add(p.get("privateIPAddress"))
        for ipc in (rec.get("properties") or {}).get("ipConfigurations") or []:
            p = ipc.setdefault("properties", {})
            sid = str((p.get("subnet") or {}).get("id", "")).lower()
            prefix = self._subnet_prefix(sid) if sid else None
            if not prefix:
                continue
            net = ipaddress.ip_network(prefix, strict=False)
            taken = used.setdefault(sid, set())
            want = p.get("privateIPAddress")
            static = str(p.get("privateIPAllocationMethod", "Dynamic")).lower() == "static"
            if want and (static or ipaddress.ip_address(want) in net):
                ip = ipaddress.ip_address(want)
                if ip not in net or not (int(net.network_address) + 4 <= int(ip) <= int(net.broadcast_address) - 1):
                    return _err(400, "PrivateIPAddressNotInSubnet",
                                f"IP address {want} is not within the usable range of subnet {sid}.")
                if want in taken:
                    return _err(400, "PrivateIPAddressInUse", f"IP configuration {ipc.get('name')} is using the private IP "
                                                              f"address {want} which is already allocated.")
                taken.add(want)
                p.setdefault("privateIPAllocationMethod", "Static" if static else "Dynamic")
                continue
            for n in range(int(net.network_address) + 4, int(net.broadcast_address)):
                cand = str(ipaddress.ip_address(n))
                if cand not in taken:
                    p["privateIPAddress"], p["privateIPAllocationMethod"] = cand, "Dynamic"
                    taken.add(cand)
                    break
            else:
                return _err(400, "SubnetIsFull", f"Subnet {sid} has no free IP addresses.")
            p.setdefault("privateIPAddressVersion", "IPv4")
        return None

    def _nw_target_iface(self, topo, payload: dict):
        nic = str(payload.get("targetNicResourceId") or "").lower()
        if nic and nic in topo.interfaces:
            return topo.interfaces[nic]
        target = str(payload.get("targetResourceId") or "").lower()
        if target in topo.interfaces:
            return topo.interfaces[target]
        vm = self.state.get(target)
        for n in (((vm or {}).get("properties") or {}).get("networkProfile") or {}).get("networkInterfaces") or []:
            nid = str(n.get("id", "")).lower()
            if nid in topo.interfaces:
                return topo.interfaces[nid]
        return None

    def _nw_connectivity_check(self, topo, ev, payload: dict):
        """Microsoft.Network/networkWatchers/{nw}/connectivityCheck — real Azure's
        source/destination shape ({source: {resourceId}, destination: {resourceId|address, port},
        protocol}), answered by the SAME netsim `reach()` the AWS Reachability Analyzer / GCP
        Connectivity Tests analyzers use. `hops[].type` carries this evaluator's own component
        names (route-table / nsg / peering / ...), not real Network Watcher's hop-type enum —
        see the azure.vnets.network_watcher limitation."""
        source = payload.get("source") or {}
        src_iface = self._nw_target_iface(topo, {"targetResourceId": source.get("resourceId"),
                                                 "targetNicResourceId": source.get("networkInterfaceId")})
        if src_iface is None:
            return _err(400, "InvalidSourceResource", "source.resourceId must be a virtual machine (or NIC) "
                                                      "with a network interface in a simulated subnet.")
        destination = payload.get("destination") or {}
        dst_iface = self._nw_target_iface(topo, {"targetResourceId": destination.get("resourceId")}) if destination.get("resourceId") else None
        dst = dst_iface if dst_iface is not None else str(destination.get("address") or "")
        if not dst:
            return _err(400, "InvalidDestination", "destination.resourceId or destination.address is required.")
        port = destination.get("port")
        protocol = str(payload.get("protocol", "TCP")).lower()
        v = ev.reach(topo, src_iface, dst, protocol, int(port) if str(port).isdigit() else None)
        hops = [{"type": h.component, "id": h.id, "address": "", "issues": [] if h.decision != "deny" else
                [{"origin": "Outbound", "severity": "Error", "type": h.decision, "context": [{"key": "detail", "value": h.detail}]}]}
                for h in v.hops]
        reachable = v.reachable
        return _ok({"hops": hops, "connectionStatus": "Reachable" if reachable else "Unreachable",
                    "avgLatencyInMs": 1 if reachable else 0, "minLatencyInMs": 1 if reachable else 0,
                    "maxLatencyInMs": 1 if reachable else 0, "probesSent": 100, "probesFailed": 0 if reachable else 100})

    def _network_watcher(self, verb: str, payload: dict):
        try:
            from core.netsim import evaluate as ev, from_azure as fz, model as nm
        except ImportError:                              # pragma: no cover - flat layout
            from netsim import evaluate as ev, from_azure as fz, model as nm   # type: ignore
        topo = fz.from_azure(self.state)
        if verb == "connectivitycheck":
            return self._nw_connectivity_check(topo, ev, payload or {})
        iface = self._nw_target_iface(topo, payload or {})
        if iface is None:
            return _err(400, "InvalidTargetResource", "targetResourceId must be a virtual machine (or targetNicResourceId a NIC) "
                                                      "with a network interface in a simulated subnet.")
        if verb == "nexthop":
            dst = str(payload.get("destinationIPAddress") or "")
            r = ev.route_lookup(topo, topo.subnet_of(iface), dst, iface)
            kind_map = {nm.LOCAL: "VnetLocal", nm.IGW: "Internet", nm.PEERING: "VNetPeering", nm.BLACKHOLE: "None",
                        nm.INSTANCE: "VirtualAppliance", nm.NAT: "Internet"}
            if r is None:
                return _ok({"nextHopType": "None", "nextHopIpAddress": "", "routeTableId": "System Route"})
            hop_ip = topo.interfaces[r.target].ip if r.kind == nm.INSTANCE and r.target in topo.interfaces else ""
            rt = r.name.split("/routes/")[0] if r.origin == "user" and "/routes/" in r.name else "System Route"
            return _ok({"nextHopType": kind_map.get(r.kind, "VirtualNetworkGateway"), "nextHopIpAddress": hop_ip,
                        "routeTableId": rt})
        # ipFlowVerify: NSG verdict (subnet NSG + NIC NSG) for one packet in one direction
        direction = nm.INGRESS if str(payload.get("direction", "Inbound")).lower() == "inbound" else nm.EGRESS
        proto = str(payload.get("protocol", "TCP")).lower()
        lport, rport = str(payload.get("localPort", "")), str(payload.get("remotePort", ""))
        remote = str(payload.get("remoteIPAddress") or "")
        dport = int(lport if direction == nm.INGRESS else rport) if (lport if direction == nm.INGRESS else rport).isdigit() else None
        sport = int(rport if direction == nm.INGRESS else lport) if (rport if direction == nm.INGRESS else lport).isdigit() else None
        remote_iface = topo.iface_by_ip(remote)
        v = ev.Verdict()
        ok = ev._layers(topo, iface, direction, proto, dport, remote, remote_iface, True, v, sport)
        rule_name = ""
        hop = next((h for h in v.hops if h.decision == "deny"), None) if not ok else (v.hops[-1] if v.hops else None)
        if hop is not None:
            name = hop.detail.split(" ")[0]
            rs = topo.rulesets.get(hop.id)
            rule = next((r for r in (rs.rules if rs else []) if r.name == name), None)
            if rule is not None:
                rule_name = f"{'defaultSecurityRules' if rule.implied else 'securityRules'}/{name}"
        return _ok({"access": "Allow" if ok else "Deny", "ruleName": rule_name})

    def _arm_action(self, action, type_chain, resource_name, parent_rid="", payload=None, sub=None, rg=None):
        ns = type_chain[0].lower() if type_chain else ""
        typ = type_chain[1].lower() if len(type_chain) > 1 else ""
        if ns == "microsoft.resources" and typ == "deployments" and action in ("cancel", "redeploy"):
            return self._deployment_action(action, resource_name, parent_rid, sub, rg)
        if ns == "microsoft.containerregistry" and typ == "registries" and action in ("listcredentials", "regeneratecredential"):
            rec = self.state.get(parent_rid.lower()) if parent_rid else None
            if not rec:
                return _err(404, "ResourceNotFound", f"Registry '{resource_name}' not found.")
            if not rec.get("properties", {}).get("adminUserEnabled"):
                return _err(400, "AdminUserCredentialsNotEnabled", "Admin user is not enabled on this registry.")
            creds = rec.setdefault("_credentials", {"password": uuid.uuid4().hex, "password2": uuid.uuid4().hex})
            if action == "regeneratecredential":
                target = (payload or {}).get("name", "password")
                if target not in creds:
                    return _err(400, "BadRequest", f"Unknown credential name '{target}'.")
                creds[target] = uuid.uuid4().hex
            return _ok({"username": resource_name, "passwords": [
                {"name": "password", "value": creds["password"]},
                {"name": "password2", "value": creds["password2"]},
            ]})
        if ns == "microsoft.sql" and typ == "servers" and action in ("export", "import"):
            return self._sql_import_export(action, type_chain, parent_rid, payload or {}, sub, rg)
        if ns == "microsoft.containerservice" and typ == "managedclusters":
            return self._aks_action(action, resource_name, parent_rid, payload or {})
        if ns == "microsoft.documentdb" and typ == "databaseaccounts" and action in (
                "listkeys", "listreadonlykeys", "listconnectionstrings", "regeneratekey"):
            return self._cosmos_keys_action(action, resource_name, parent_rid, payload or {})
        if ns == "microsoft.documentdb" and typ == "databaseaccounts" and action == "failoverprioritychange":
            return self._cosmos_failover_action(resource_name, parent_rid, payload or {})
        if ns == "microsoft.apimanagement" and typ == "service" and len(type_chain) > 2 and type_chain[2].lower() == "namedvalues" and action == "listvalue":
            return self._apim_namedvalue_listvalue(resource_name, parent_rid)
        if action in ("start", "poweroff", "restart", "deallocate"):
            if ns != "microsoft.compute" or typ != "virtualmachines":
                return _err(400, "ActionNotSupported",
                            f"Action '{action}' is only supported on Microsoft.Compute/virtualMachines.")
            rec = self.state.get(parent_rid.lower()) if parent_rid else None
            if not rec:
                return _err(404, "ResourceNotFound", f"Virtual machine '{resource_name}' not found.")
            new_status = {"start": "running", "restart": "running",
                          "poweroff": "stopped", "deallocate": "deallocated"}[action]
            props = rec.setdefault("properties", {})
            props.setdefault("runtime", {})["containerStatus"] = new_status
            props["powerState"] = f"PowerState/{new_status}"
            return _ok({"status": "Succeeded", "action": action, "containerStatus": new_status,
                        "note": "metadata-only (no runtime backing in-browser); logical state updated"})
        if action in ("listkeys", "regeneratekey"):
            return _ok({"keys": [{"keyName": "key1", "value": "c2ltdWxhdGVk", "permissions": "FULL"},
                                 {"keyName": "key2", "value": "c2ltdWxhdGVk", "permissions": "FULL"}]})
        if action == "listconnectionstrings":
            return _ok({"connectionStrings": []})
        if action == "listsecrets":
            return _ok({})
        return _ok({})

    def _sql_import_export(self, action, type_chain, parent_rid, payload, sub, rg):
        """Microsoft.Sql database export (POST .../databases/{db}/export) and import
        (POST .../databases/{db}/import, or .../servers/{s}/import for a new database):
        the .bacpac goes to / comes from the SIMULATOR's Azure Blob store at storageUri
        (core/azure_sql_core.export_database / import_database) — never the internet."""
        from core import azure_sql_core as az_sql
        on_database = len(type_chain) >= 4 and type_chain[2].lower() == "databases"
        parts = parent_rid.split("/")
        low = [x.lower() for x in parts]
        server = parts[low.index("servers") + 1] if "servers" in low else ""
        if not self.state.get(parent_rid.lower()):
            what = "Database" if on_database else "Server"
            return _err(404, "ResourceNotFound", f"{what} '{parts[-1]}' not found.")
        uri = str(payload.get("storageUri") or "").strip()
        if not uri:
            return _err(400, "InvalidParameterValue", "storageUri is required.")
        if on_database:
            database = parts[-1]
        else:
            database = str(payload.get("databaseName") or "").strip()
            if not database:
                return _err(400, "InvalidParameterValue", "databaseName is required to import a new database.")
        if self.sql_store is None or self.blob_store is None:
            return _err(503, "ServiceUnavailable", "Database import/export is not wired on this platform.")
        if action == "export":
            ok, code, message, _size = az_sql.export_database(self.sql_store, server, database, self.blob_store,
                                                             uri, arm_state=self.state)
        else:
            ok, code, message = az_sql.import_database(self.sql_store, server, database, self.blob_store,
                                                       uri, arm_state=self.state)
        if not ok:
            return _err(404 if code.endswith("NotFound") else 400, code, message)
        db_rid = (parent_rid if on_database else
                  f"{parent_rid}/databases/{database}")
        if not on_database and not self.state.get(db_rid.lower()):
            server_rec = self.state.get(parent_rid.lower()) or {}
            self.handle("PUT", db_rid, {"api-version": "2021-11-01"},
                        {"location": server_rec.get("location", "eastus"), "properties": {}})
        self._record_activity(db_rid, f"Microsoft.Sql/servers/databases/{action}/action", sub)
        return _ok({"id": f"{db_rid}/importExportOperationResults/{uuid.uuid4()}",
                    "type": "Microsoft.Sql/servers/databases/importExportOperationResults",
                    "properties": {"requestType": "Export" if action == "export" else "Import",
                                   "serverName": server, "databaseName": database, "status": "Succeeded",
                                   "lastModifiedTime": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                                   "blobUri": uri, "errorMessage": None}})

    def _cosmos_keys_action(self, action, account_name, parent_rid, payload):
        """Microsoft.DocumentDB/databaseAccounts listKeys / listReadOnlyKeys /
        listConnectionStrings / regenerateKey — the real Cosmos ARM response shapes
        (NOT the generic storage-style {"keys": [...]}), so the account's Keys blade
        shows the same fields az cosmosdb / azure-mgmt-cosmosdb would get back."""
        rec = self.state.get(parent_rid.lower()) if parent_rid else None
        if not rec:
            return _err(404, "ResourceNotFound", f"Database account '{account_name}' not found.")
        keys = rec.setdefault("_cosmoskeys", {
            k: base64.b64encode(uuid.uuid4().bytes + uuid.uuid4().bytes).decode()
            for k in ("primaryMasterKey", "secondaryMasterKey", "primaryReadonlyMasterKey", "secondaryReadonlyMasterKey")
        })
        if action == "listkeys":
            return _ok({k: keys[k] for k in ("primaryMasterKey", "secondaryMasterKey", "primaryReadonlyMasterKey", "secondaryReadonlyMasterKey")})
        if action == "listreadonlykeys":
            return _ok({k: keys[k] for k in ("primaryReadonlyMasterKey", "secondaryReadonlyMasterKey")})
        if action == "listconnectionstrings":
            uri = f"https://{account_name}.documents.azure.com:443/"
            cs = lambda desc, key: {"connectionString": f"AccountEndpoint={uri};AccountKey={key};", "description": desc}
            return _ok({"connectionStrings": [
                cs("Primary SQL Connection String", keys["primaryMasterKey"]),
                cs("Secondary SQL Connection String", keys["secondaryMasterKey"]),
                cs("Primary Read-Only SQL Connection String", keys["primaryReadonlyMasterKey"]),
                cs("Secondary Read-Only SQL Connection String", keys["secondaryReadonlyMasterKey"]),
            ]})
        # regenerateKey: body {"keyKind": "primary" | "secondary" | "primaryReadonly" | "secondaryReadonly"}
        field = {"primary": "primaryMasterKey", "secondary": "secondaryMasterKey",
                "primaryreadonly": "primaryReadonlyMasterKey", "secondaryreadonly": "secondaryReadonlyMasterKey",
                }.get(str(payload.get("keyKind", "primary")).lower())
        if not field:
            return _err(400, "BadRequest", f"Unknown keyKind '{payload.get('keyKind')}'.")
        keys[field] = base64.b64encode(uuid.uuid4().bytes + uuid.uuid4().bytes).decode()
        return _ok({"status": "Succeeded"})

    def _cosmos_failover_action(self, account_name, parent_rid, payload):
        """Microsoft.DocumentDB/databaseAccounts/{name}/failoverPriorityChange — the real
        action behind the Replicate data globally blade's Manual Failover button. ENFORCED for
        real: it reassigns which configured region is the write region (failoverPriority 0) and
        updates location/writeLocations/readLocations to match — Vyomi still has one logical
        region underneath, so the promoted region doesn't get its own separate data-plane copy
        (azure.cosmos.replicate_data_globally)."""
        rec = self.state.get(parent_rid.lower()) if parent_rid else None
        if not rec:
            return _err(404, "ResourceNotFound", f"Database account '{account_name}' not found.")
        policies = payload.get("failoverPolicies")
        if not isinstance(policies, list) or not policies:
            return _err(400, "BadRequest", "failoverPolicies is required.")
        locations = rec.get("properties", {}).get("locations") or []
        by_name = {l.get("locationName"): dict(l) for l in locations}
        if not by_name:
            return _err(400, "BadRequest", "This account has no configured regions to fail over between.")
        seen = set()
        for p in policies:
            name, prio = p.get("locationName"), p.get("failoverPriority")
            if name not in by_name:
                return _err(400, "BadRequest", f"Location '{name}' is not configured on this account.")
            if not isinstance(prio, int) or prio < 0:
                return _err(400, "BadRequest", "failoverPriority must be a non-negative integer.")
            by_name[name]["failoverPriority"] = prio
            seen.add(name)
        if seen != set(by_name.keys()):
            return _err(400, "BadRequest", "failoverPolicies must list every region configured on the account.")
        prios = sorted(l["failoverPriority"] for l in by_name.values())
        if prios != list(range(len(prios))):
            return _err(400, "BadRequest",
                        "failoverPriority values must be a 0-based, gap-free sequence with exactly one region at priority 0.")
        new_locations = sorted(by_name.values(), key=lambda l: l["failoverPriority"])
        rec["properties"]["locations"] = new_locations
        primary = new_locations[0]["locationName"]
        rec["location"] = primary
        rec["properties"]["writeLocations"] = [{"locationName": primary, "failoverPriority": 0}]
        rec["properties"]["readLocations"] = [{"locationName": l["locationName"], "failoverPriority": l["failoverPriority"]} for l in new_locations]
        _record_activity(account_name, "Failover", f"Microsoft.DocumentDB/databaseAccounts '{account_name}' promoted '{primary}' to the write region")
        return _ok(None, status=202)

    def _apim_namedvalue_listvalue(self, nv_name, parent_rid):
        """Microsoft.ApiManagement/service/namedValues/{name}/listValue — the real action behind
        a named value's "Show value" eye icon. For a plain/secret named value this is just
        `properties.value`; for a Key Vault reference (`properties.keyVault.secretIdentifier`)
        the real portal resolves it against the live vault — ENFORCED here for real against
        THIS space's OWN Key Vault secrets store (azure_keyvault_secrets_core's KvStore, shared
        via aws_wire_router.AwsWireRouter.__init__), since a Key Vault reference pointing at a
        vault/secret that was never created (or has been deleted) is a genuine 400 in Azure too
        (azure.apim.namedvalues.keyvaultref)."""
        rec = self.state.get(parent_rid.lower()) if parent_rid else None
        if not rec:
            return _err(404, "ResourceNotFound", f"Named value '{nv_name}' not found.")
        props = rec.get("properties") or {}
        secret_id = (props.get("keyVault") or {}).get("secretIdentifier")
        if not secret_id:
            return _ok({"value": props.get("value") or ""})
        secret_name, version = _parse_kv_secret_identifier(secret_id)
        store = self.kv_secrets_store
        secret_rec = store.get_secret(secret_name) if store and secret_name else None
        if not secret_rec or secret_rec.get("deleted") or not secret_rec.get("versions"):
            return _err(400, "KeyVaultErrorSecretNotFound",
                        f"Named value '{nv_name}' references Key Vault secret '{secret_name}', which was not found.")
        ver = secret_rec["versions"].get(version or secret_rec["current"])
        if not ver:
            return _err(400, "KeyVaultErrorSecretNotFound",
                        f"Named value '{nv_name}' references a version of '{secret_name}' that was not found.")
        return _ok({"value": ver.get("value") or ""})

    def _aks_action(self, action, cluster_name, parent_rid, payload):
        """POST actions on Microsoft.ContainerService/managedClusters/{name}/<action> — start/stop
        (metadata-only power state, same convention as VM start/poweroff), runCommand (the AKS
        `az aks command invoke` action: kubectl against the cluster's Kubernetes object store in
        core/azure_aks_k8s_core.py — objects are stored, never scheduled; an object change triggers
        a Kubescape rescan for Defender for Cloud when its Containers plan is on) and the two
        listCluster*Credential actions (a deterministic, clearly-fake kubeconfig — enough for the
        "Connect" blade to show *something* shaped like the real response)."""
        rec = self.state.get(parent_rid.lower()) if parent_rid else None
        if not rec:
            return _err(404, "ResourceNotFound", f"Managed cluster '{cluster_name}' not found.")
        props = rec.setdefault("properties", {})
        if action in ("start", "stop"):
            props["powerState"] = {"code": "Running" if action == "start" else "Stopped"}
            return _ok({"status": "Succeeded", "action": action, "powerState": props["powerState"],
                        "note": "metadata-only (no node VMs backing this cluster in-browser); logical state updated"})
        if action == "runcommand":
            if props.get("powerState", {}).get("code") == "Stopped":
                return _err(409, "ClusterNotRunning",
                            "The cluster is stopped. Start the cluster before running a command against it.")
            command = (payload or {}).get("command", "")
            if not str(command).strip():
                return _err(400, "InvalidParameter", "The value of parameter command is invalid: it must not be empty.")
            # kubectl against the cluster's Kubernetes object store (core/azure_aks_k8s_core.py):
            # objects are stored, never scheduled — no kubelet or container runtime runs.
            started = _now()
            res = k8s_engine.run_command(rec, str(command), (payload or {}).get("context"))
            if res["changed"]:
                sub = parent_rid.split("/")[2] if parent_rid.count("/") >= 2 else DEFAULT_SUBSCRIPTION
                if security_engine.plan_on(self.state, sub, "Containers"):
                    kubescape_engine.on_objects_changed(rec, rec.get("id") or parent_rid)
            rid = str(uuid.uuid4()).replace("-", "")
            result = {"provisioningState": "Succeeded", "exitCode": res["exitCode"], "startedAt": started,
                      "finishedAt": _now(), "logs": res["logs"], "reason": "" if res["exitCode"] == 0 else "CommandFailed"}
            # RunCommandResult ({id, properties}) as az aks command invoke reads it, plus the flat
            # fields earlier Vyomi clients read.
            return _ok({"id": rid, "properties": result, **result})
        if action in ("listclusterusercredential", "listclusteradmincredential"):
            user = "clusterUser" if action == "listclusterusercredential" else "clusterAdmin"
            fqdn = props.get("fqdn") or f"{cluster_name}.hcp.azmk8s.io"
            kubeconfig = (
                "apiVersion: v1\nkind: Config\nclusters:\n- name: " + cluster_name +
                "\n  cluster:\n    server: https://" + fqdn + ":443\n    certificate-authority-data: c2ltdWxhdGVk\n"
                "users:\n- name: " + user + "_" + cluster_name +
                "\n  user:\n    token: c2ltdWxhdGVk-not-a-real-credential\n"
                "contexts:\n- name: " + cluster_name + "\n  context:\n    cluster: " + cluster_name +
                "\n    user: " + user + "_" + cluster_name + "\ncurrent-context: " + cluster_name + "\n"
            )
            import base64
            return _ok({"kubeconfigs": [{"name": user, "value": base64.b64encode(kubeconfig.encode()).decode()}]})
        return _ok({})

    def _provider_info(self, namespace):
        types = [{"resourceType": c["type"], "apiVersions": [c["api_version"]],
                  "locations": [DEFAULT_LOCATION], "capabilities": "None"}
                 for c in CATALOG if c["namespace"].lower() == namespace.lower()]
        return {"id": f"/subscriptions/{DEFAULT_SUBSCRIPTION}/providers/{namespace}",
                "namespace": namespace, "registrationState": self.providers.get(namespace.lower(), "Registered"),
                "registrationPolicy": "RegistrationRequired", "resourceTypes": types}

    def _rg_key(self, sub, rg):
        return f"/subscriptions/{sub}/resourcegroups/{rg}".lower()

    def _default_rg_view(self, sub, rg):
        return {"id": f"/subscriptions/{sub}/resourceGroups/{rg}", "name": rg,
                "type": "Microsoft.Resources/resourceGroups", "location": DEFAULT_LOCATION,
                "tags": {}, "properties": {"provisioningState": "Succeeded"}}

    def _list_resource_groups(self, sub):
        out, seen = [], set()
        for rec in self.state.values():
            if rec.get("_sub") == sub and rec.get("_type", "").lower() == "microsoft.resources/resourcegroups":
                out.append(_view(rec))
                seen.add(rec["name"])
        for rec in self.state.values():   # implicit groups: resources created without an explicit PUT on the group
            if rec.get("_sub") == sub and rec.get("_rg") and rec["_rg"] not in seen:
                seen.add(rec["_rg"])
                out.append(self._default_rg_view(sub, rec["_rg"]))
        if DEFAULT_RG not in seen:
            out.append(self._default_rg_view(sub, DEFAULT_RG))
        return out

    def _resource_group_item(self, method, sub, rg, payload):
        payload = payload or {}
        key = self._rg_key(sub, rg)
        rid = f"/subscriptions/{sub}/resourceGroups/{rg}"
        implicit = any(r.get("_sub") == sub and r.get("_rg") == rg for r in self.state.values()) or rg == DEFAULT_RG

        if method == "GET":
            rec = self.state.get(key)
            if rec:
                return _ok(_view(rec))
            if implicit:
                return _ok(self._default_rg_view(sub, rg))
            return _err(404, "ResourceGroupNotFound", f"Resource group '{rg}' could not be found.")

        if method in ("PUT", "PATCH"):
            prior = self.state.get(key)
            # A PUT replaces the tag set exactly (like any generic catalog resource — see
            # AzureArm._upsert); a PATCH on an existing group merges it instead.
            rec = dict(prior) if (method == "PATCH" and prior) else {
                "id": rid, "name": rg, "type": "Microsoft.Resources/resourceGroups",
                "location": DEFAULT_LOCATION, "tags": {},
                "_type": "Microsoft.Resources/resourceGroups", "_sub": sub, "_created": _now(),
            }
            if payload.get("location"):
                rec["location"] = payload["location"]
            if isinstance(payload.get("tags"), dict):
                rec["tags"] = _merge(rec.get("tags", {}), payload["tags"]) if (method == "PATCH" and prior) else dict(payload["tags"])
            rec["id"], rec["name"], rec["type"] = rid, rg, "Microsoft.Resources/resourceGroups"
            rec["properties"] = {"provisioningState": "Succeeded"}
            self.state[key] = rec
            self._record_activity(rid, "Microsoft.Resources/resourceGroups/write", sub)
            return _ok(_view(rec), status=200)

        if method == "DELETE":
            existed = self.state.pop(key, None) is not None
            # Deleting a resource group cascades to every resource it contains (real ARM
            # behaviour) — including that group's own locks, extension resources, … but NOT
            # Activity log rows ("/__event__/" keys): real Azure keeps a deleted group's
            # history in the subscription-wide feed, it doesn't erase it.
            removed_any = False
            for k in [k for k, r in self.state.items()
                      if "/__event__/" not in k
                      and ((r.get("_sub") == sub and (r.get("_rg") or "") == rg) or k.startswith(key + "/providers/"))]:
                del self.state[k]
                removed_any = True
            if not (existed or removed_any or implicit):
                return _err(404, "ResourceGroupNotFound", f"Resource group '{rg}' could not be found.")
            self._record_activity(rid, "Microsoft.Resources/resourceGroups/delete", sub)
            return _ok(None, status=200)

        return _err(405, "MethodNotAllowed", f"{method} not allowed.")

    def _make_operation(self, resource_id, method, result=None):
        op_id = uuid.uuid4().hex
        now = _now()
        self.operations[op_id] = {"id": op_id, "name": op_id, "status": "Succeeded",
                                   "startTime": now, "endTime": now,
                                   "resourceId": resource_id, "method": method}
        if result:
            self.operations[op_id]["result"] = result
        return op_id
