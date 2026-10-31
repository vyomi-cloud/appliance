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

try:                                              # VM size catalog (vcpu/ram/family per real Azure size name)
    from core import instance_catalog
except ImportError:
    import instance_catalog                        # type: ignore

DEFAULT_SUBSCRIPTION = "00000000-0000-0000-0000-cloudlearn01"
DEFAULT_RG = "cloudlearn-rg"
DEFAULT_LOCATION = "eastus"

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


def _activity_log_query(query: dict) -> dict:
    """GET /subscriptions/{sub}/providers/Microsoft.Insights/eventtypes/management/values —
    the real ARM activity-log read API every resource's "Activity log" blade calls, scoped
    via an OData $filter containing ``resourceUri eq '{id}'``. Only that scoping predicate is
    understood (not the full OData grammar); with no resourceUri filter the unfiltered feed
    (every resource) is returned, matching the subscription-wide Activity log page."""
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


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


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


def _expand_tokens(obj, name: str, base: str):
    if isinstance(obj, str):
        return (obj.replace("__UUID__", str(uuid.uuid4()))
                   .replace("__NAME__", name)
                   .replace("__BASE__", base)
                   .replace("__NOW__", _now()))
    if isinstance(obj, dict):
        return {k: _expand_tokens(v, name, base) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_expand_tokens(v, name, base) for v in obj]
    return obj


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


def _view(rec: dict) -> dict:
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
                        "state": "Enabled", "tags": self.sub_tags.get(sub.lower(), {})})

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
                     and r.get("_type", "").lower() != "microsoft.resources/resourcegroups"]
            return _ok({"value": items})

        # GET /subscriptions/{sub}/resources — every resource across every resource group in
        # the subscription (az resource list / Resources.list), the Subscription blade's
        # Settings > Resources panel.
        if rg is None and idx < len(rest_segs) and rest_segs[idx].lower() == "resources" and len(rest_segs) == idx + 1:
            if method != "GET":
                return _err(405, "MethodNotAllowed", "Use GET to list resources in a subscription.")
            items = [_view(r) for r in self.state.values()
                     if r.get("_sub") == sub and r.get("_type", "").lower() != "microsoft.resources/resourcegroups"]
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
                        "state": "Enabled", "tags": self.sub_tags.get(sub.lower(), {})})

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
            events.sort(key=lambda e: str(e.get("eventTimestamp") or ""), reverse=True)
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

        # POST action verbs (listKeys / start / powerOff / runCommand / …)
        if method == "POST" and is_collection and len(type_chain) >= 3 and names:
            parent_rid = _canonical_id(sub, rg, type_chain[:-1], names)
            return self._arm_action(type_chain[-1].lower(), type_chain, names[-1], parent_rid, payload)

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
            existed_before = key in self.state
            blocked = self._lock_block(rid, full_type, for_delete=False)
            if blocked:
                return blocked
            blocked = self._servicebus_tier_block(type_chain, names, payload, sub, rg)
            if blocked:
                return blocked
            resp = self._upsert(rid, key, full_type, leaf_name, top, payload, base, patch=(method == "PATCH"))
            if lro:
                resp["status"] = 200
                op_id = self._make_operation(rid, method)
                url = f"{base}/api/azure/operations/{op_id}?api-version={api_version}"
                resp["headers"].update({"Azure-AsyncOperation": url, "Location": url, "Retry-After": "0"})
            _record_activity(leaf_name, "Update" if existed_before else "Create", f"{full_type} '{leaf_name}'")
            return resp
        if method == "DELETE":
            blocked = self._lock_block(rid, full_type, for_delete=True)
            if blocked:
                return blocked
            rec = self.state.pop(key, None)
            if rec is not None:
                _record_activity(leaf_name, "Delete", f"{full_type} '{leaf_name}'")
                # Both extension resources (locks, … keyed "{parent id}/providers/<ext ns>/…")
                # and plain nested children (e.g. managedClusters/{c}/agentPools/{p}, keyed
                # "{parent id}/agentPools/{p}") cascade-delete with their parent in real ARM.
                prefix = key + "/"
                for child_key in [k for k in self.state if k.startswith(prefix)]:
                    del self.state[child_key]
            return _ok(None, status=200 if rec is not None else 204)
        return _err(405, "MethodNotAllowed", f"{method} not allowed.")

    def _lock_block(self, rid, full_type, for_delete):
        # Enforcement is scoped to Microsoft.ServiceBus (namespaces/queues/topics) only —
        # every other resource type in this generic engine still leaves Microsoft.Authorization/
        # locks config_only (stored, not enforced), matching their own capability registries.
        if not full_type.lower().startswith("microsoft.servicebus/"):
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

        self.state[key] = rec
        return _ok(_view(rec), status=200 if existed else 201)

    def _arm_action(self, action, type_chain, resource_name, parent_rid="", payload=None):
        ns = type_chain[0].lower() if type_chain else ""
        typ = type_chain[1].lower() if len(type_chain) > 1 else ""
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
        if ns == "microsoft.containerservice" and typ == "managedclusters":
            return self._aks_action(action, resource_name, parent_rid, payload or {})
        if ns == "microsoft.documentdb" and typ == "databaseaccounts" and action in (
                "listkeys", "listreadonlykeys", "listconnectionstrings", "regeneratekey"):
            return self._cosmos_keys_action(action, resource_name, parent_rid, payload or {})
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

    def _aks_action(self, action, cluster_name, parent_rid, payload):
        """POST actions on Microsoft.ContainerService/managedClusters/{name}/<action> — start/stop
        (metadata-only power state, same convention as VM start/poweroff), runCommand (the AKS
        `az aks command invoke` action: no live kubelet in-browser, so it returns an honest
        canned acknowledgement rather than real command output) and the two
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
            command = (payload or {}).get("command", "")
            return _ok({"id": str(uuid.uuid4()), "provisioningState": "Succeeded",
                        "exitCode": 0, "startedAt": _now(), "finishedAt": _now(),
                        "logs": (f"$ {command}\n" if command else "") +
                                "Vyomi does not run a real kubelet, so runCommand is simulated: "
                                "the command was accepted but not executed against a live API server."})
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
            existed = key in self.state
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
            _record_activity(rg, "Update" if (existed or implicit) else "Create", f"Microsoft.Resources/resourceGroups '{rg}'")
            return _ok(_view(rec), status=200)

        if method == "DELETE":
            existed = self.state.pop(key, None) is not None
            # Deleting a resource group cascades to every resource it contains (real ARM
            # behaviour) — including that group's own locks, extension resources, …
            removed_any = False
            for k in [k for k, r in self.state.items()
                      if (r.get("_sub") == sub and (r.get("_rg") or "") == rg) or k.startswith(key + "/providers/")]:
                del self.state[k]
                removed_any = True
            if not (existed or removed_any or implicit):
                return _err(404, "ResourceGroupNotFound", f"Resource group '{rg}' could not be found.")
            _record_activity(rg, "Delete", f"Microsoft.Resources/resourceGroups '{rg}'")
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
