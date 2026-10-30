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
                   .replace("__BASE__", base))
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
                        "displayName": "CloudLearn Subscription", "state": "Enabled"})

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
        if idx >= len(rest_segs) or rest_segs[idx].lower() != "providers":
            return _err(400, "BadRequest", f"Unrecognized ARM path: /subscriptions/{rest}")
        after = rest_segs[idx + 1:]

        # provider registration probes
        if len(after) == 0 and method == "GET":
            return _ok({"value": [self._provider_info(n) for n in sorted({c["namespace"] for c in CATALOG})]})
        if len(after) == 1 and method == "GET":
            return _ok(self._provider_info(after[0]))
        if len(after) == 2 and after[1].lower() == "register" and method == "POST":
            return _ok(self._provider_info(after[0]))
        if len(after) < 2:
            return _err(400, "BadRequest", "Missing provider namespace/type.")

        namespace = after[0]
        chain = after[1:]

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

        # Microsoft.Authorization/locks: a real ARM extension resource scoped to ANY other
        # resource's own id (the chain re-enters "providers", like Event Grid's event
        # subscriptions) — generic over every catalog type, so caught before the alternation.
        lock_marker = locks_engine.find_marker(chain)
        if lock_marker is not None:
            return self._locks(method, sub, rg, namespace, chain, lock_marker, payload)

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
            # A nested collection (e.g. .../managedClusters/{cluster}/agentPools) must be scoped
            # to its parent resource, not every resource of that type in the resource group —
            # the generic type/name alternation above only tells us the TYPE matches.
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
            resp = self._upsert(rid, key, full_type, leaf_name, top, payload, base, patch=(method == "PATCH"))
            if lro:
                resp["status"] = 200
                op_id = self._make_operation(rid, method)
                url = f"{base}/api/azure/operations/{op_id}?api-version={api_version}"
                resp["headers"].update({"Azure-AsyncOperation": url, "Location": url, "Retry-After": "0"})
            _record_activity(leaf_name, "Update" if existed_before else "Create", f"{full_type} '{leaf_name}'")
            return resp
        if method == "DELETE":
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

    def _locks(self, method, sub, rg, namespace, chain, marker, payload):
        # Replay the SAME type/name alternation the main dispatcher uses (see `_arm` above)
        # over everything before the "providers/Microsoft.Authorization/locks" marker.
        stc, snames = [namespace], []
        for n, token in enumerate(chain[:marker]):
            (stc if n % 2 == 0 else snames).append(token)
        scope_rid = _canonical_id(sub, rg, stc, snames)
        rest = chain[marker + 3:]
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
                    _record_activity(snames[-1] if snames else scope_rid, "Create lock" if r["status"] == 201 else "Update lock", name)
            elif method == "DELETE":
                r = locks_engine.remove(self.state, scope_rid, name)
                if r["status"] == 200:
                    _record_activity(snames[-1] if snames else scope_rid, "Delete lock", name)
            else:
                return _err(405, "MethodNotAllowed", f"{method} not allowed.")
        return {"status": r["status"], "headers": {}, "body": r["body"]}

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
            if parent_prefix is not None and not rec.get("id", "").lower().startswith(parent_prefix):
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

        self.state[key] = rec
        return _ok(_view(rec), status=200 if existed else 201)

    def _arm_action(self, action, type_chain, resource_name, parent_rid="", payload=None):
        ns = type_chain[0].lower() if type_chain else ""
        typ = type_chain[1].lower() if len(type_chain) > 1 else ""
        if ns == "microsoft.containerservice" and typ == "managedclusters":
            return self._aks_action(action, resource_name, parent_rid, payload or {})
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
                "namespace": namespace, "registrationState": "Registered",
                "registrationPolicy": "RegistrationRequired", "resourceTypes": types}

    def _list_resource_groups(self, sub):
        names = {DEFAULT_RG: True}
        for rec in self.state.values():
            if rec.get("_sub") == sub and rec.get("_rg"):
                names[rec["_rg"]] = True
        return [{"id": f"/subscriptions/{sub}/resourceGroups/{n}", "name": n,
                 "type": "Microsoft.Resources/resourceGroups", "location": DEFAULT_LOCATION,
                 "properties": {"provisioningState": "Succeeded"}} for n in names]

    def _resource_group_item(self, method, sub, rg, payload):
        body = {"id": f"/subscriptions/{sub}/resourceGroups/{rg}", "name": rg,
                "type": "Microsoft.Resources/resourceGroups",
                "location": (payload or {}).get("location") or DEFAULT_LOCATION,
                "tags": (payload or {}).get("tags", {}),
                "properties": {"provisioningState": "Succeeded"}}
        if method == "DELETE":
            return _ok(None, status=200)
        return _ok(body, status=200 if method in ("PUT", "PATCH", "GET") else 405)

    def _make_operation(self, resource_id, method, result=None):
        op_id = uuid.uuid4().hex
        now = _now()
        self.operations[op_id] = {"id": op_id, "name": op_id, "status": "Succeeded",
                                   "startTime": now, "endTime": now,
                                   "resourceId": resource_id, "method": method}
        if result:
            self.operations[op_id]["result"] = result
        return op_id
