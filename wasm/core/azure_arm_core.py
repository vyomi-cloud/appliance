# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
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
import json
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

try:                                              # locks / identity / health / NICs / run commands …
    from core import azure_arm_ext_core as ext_engine
except ImportError:
    import azure_arm_ext_core as ext_engine        # type: ignore

try:                                              # Azure Log Analytics engine (Microsoft.OperationalInsights)
    from core import azure_operationalinsights_core as oi_engine
except ImportError:
    import azure_operationalinsights_core as oi_engine   # type: ignore

DEFAULT_SUBSCRIPTION = "00000000-0000-0000-0000-cloudlearn01"
DEFAULT_RG = "cloudlearn-rg"
DEFAULT_LOCATION = "eastus"
TENANT_ID = "00000000-0000-0000-0000-000000000000"


# ── One subscription per space ─────────────────────────────────────────────
# A space is one Azure subscription, as an account is in real Azure: `az login`
# discovers it from GET /subscriptions, the console uses it (catalog), and any
# other subscription id is SubscriptionNotFound — instead of silently getting
# its own empty store, which split the az CLI and the console apart. Shared by
# the offline handler (providers/azure_services.py) and Nano (AzureArm below).
def subscription_doc() -> dict:
    return {"id": f"/subscriptions/{DEFAULT_SUBSCRIPTION}", "authorizationSource": "RoleBased",
            "managedByTenants": [], "subscriptionId": DEFAULT_SUBSCRIPTION, "tenantId": TENANT_ID,
            "displayName": "Vyomi Subscription", "state": "Enabled",
            "subscriptionPolicies": {"locationPlacementId": "Public_2014-09-01",
                                     "quotaId": "PayAsYouGo_2014-09-01", "spendingLimit": "Off"}}


def tenants_doc() -> dict:
    return {"value": [{"id": f"/tenants/{TENANT_ID}", "tenantId": TENANT_ID, "tenantCategory": "Home",
                       "displayName": "Vyomi", "defaultDomain": "vyomi.onmicrosoft.com"}]}


def is_space_subscription(sub: str) -> bool:
    return (sub or "").lower() == DEFAULT_SUBSCRIPTION.lower()


def subscription_not_found(sub: str) -> tuple[int, dict]:
    return 404, {"error": {"code": "SubscriptionNotFound",
                           "message": f"The subscription '{sub}' could not be found."}}


_FOREIGN_SUB = re.compile(r"^/subscriptions/([^/]+)/", re.I)


def adopt_foreign_subscriptions(state) -> int:
    """Move resources stored under any other subscription id (accepted before
    there was one subscription per space) into the space's subscription, so
    nothing created through the CLI earlier disappears. Ids inside each record
    are rewritten too; a resource whose id already exists in the space's
    subscription keeps the space's copy. Returns how many records moved."""
    target = DEFAULT_SUBSCRIPTION.lower()
    moved = 0
    for key in [k for k in list(state.keys()) if (m := _FOREIGN_SUB.match(k)) and m.group(1).lower() != target]:
        old = _FOREIGN_SUB.match(key).group(1)
        new_key = f"/subscriptions/{target}/" + key[len(f"/subscriptions/{old}/"):]
        rec = state.pop(key)
        if new_key in state:
            continue
        if isinstance(rec, dict):
            rec = json.loads(re.sub(rf"/subscriptions/{re.escape(old)}(?=/|\"|$)", f"/subscriptions/{DEFAULT_SUBSCRIPTION}",
                                    json.dumps(rec), flags=re.I))
            if "_sub" in rec:
                rec["_sub"] = DEFAULT_SUBSCRIPTION
        state[new_key] = rec
        moved += 1
    # Lists match `_sub` exactly; the same id in other letter case was accepted too.
    for rec in state.values():
        if isinstance(rec, dict) and rec.get("_sub") and rec["_sub"] != DEFAULT_SUBSCRIPTION:
            rec["_sub"] = DEFAULT_SUBSCRIPTION
    return moved


def rg_key(rg: str) -> str:
    return f"/subscriptions/{DEFAULT_SUBSCRIPTION}/resourcegroups/{rg}".lower()


def list_resource_groups(state) -> list[dict]:
    """Stored resource groups (created with PUT, as in real Azure, even when
    empty) plus any group a resource names, plus the default group."""
    groups: dict[str, dict] = {DEFAULT_RG.lower(): {"name": DEFAULT_RG, "location": DEFAULT_LOCATION, "tags": {}}}
    for rec in state.values():
        if not isinstance(rec, dict):
            continue
        if rec.get("type") == "Microsoft.Resources/resourceGroups":
            groups[rec["name"].lower()] = rec
        elif rec.get("_rg"):
            groups.setdefault(rec["_rg"].lower(), {"name": rec["_rg"], "location": DEFAULT_LOCATION, "tags": {}})
    return [rg_doc(g["name"], g.get("location"), g.get("tags")) for g in groups.values()]


def rg_doc(rg: str, location=None, tags=None) -> dict:
    return {"id": f"/subscriptions/{DEFAULT_SUBSCRIPTION}/resourceGroups/{rg}", "name": rg,
            "type": "Microsoft.Resources/resourceGroups", "location": location or DEFAULT_LOCATION,
            "tags": tags or {}, "properties": {"provisioningState": "Succeeded"}}


def resource_group_item(state, method: str, rg: str, payload: dict) -> tuple[int, dict | None]:
    """PUT/PATCH store the group; GET returns it (404 ResourceGroupNotFound if
    it doesn't exist); DELETE removes it and every resource in it."""
    key = rg_key(rg)
    known = {g["name"].lower(): g for g in list_resource_groups(state)}
    if method in ("PUT", "PATCH"):
        cur = known.get(rg.lower())
        loc = (payload or {}).get("location") or (cur or {}).get("location") or DEFAULT_LOCATION
        tags = (payload or {}).get("tags", (cur or {}).get("tags") or {})
        state[key] = rg_doc(cur["name"] if cur else rg, loc, tags)
        return (200 if cur else 201), state[key]
    if method == "GET":
        if rg.lower() in known:
            return 200, known[rg.lower()]
        return 404, {"error": {"code": "ResourceGroupNotFound", "message": f"Resource group '{rg}' could not be found."}}
    if method == "DELETE":
        if rg.lower() == DEFAULT_RG.lower():
            state.pop(key, None)
            return 200, None
        for k in [k for k, r in state.items() if isinstance(r, dict) and (r.get("_rg") or "").lower() == rg.lower()]:
            state.pop(k, None)
        state.pop(key, None)
        return 200, None
    return 405, {"error": {"code": "MethodNotAllowed", "message": "Use PUT, GET or DELETE on a resource group."}}

def list_group_resources(state, rg: str) -> list[dict] | None:
    """GET /resourceGroups/{rg}/resources: generic id/name/type/location/tags of
    every resource in the group (None when the group doesn't exist)."""
    if rg.lower() not in {g["name"].lower() for g in list_resource_groups(state)}:
        return None
    out = []
    for rec in state.values():
        if isinstance(rec, dict) and rec.get("type") != "Microsoft.Resources/resourceGroups" \
                and (rec.get("_rg") or "").lower() == rg.lower():
            out.append({k: rec[k] for k in ("id", "name", "type", "location", "tags", "kind", "sku") if k in rec})
    return sorted(out, key=lambda r: (r.get("type", "").lower(), r.get("name", "").lower()))


_BY_TYPE = {(c["namespace"].lower(), c["type"].lower()): c for c in CATALOG}


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


def _event_target(rest: str):
    """(top-level resource id, full type, leaf name) of an ARM write path, for the
    activity log: a child op (database, queue, rule…) belongs to its parent."""
    segs = [x for x in rest.split("/") if x]
    if not segs:
        return "", "", ""
    sub, tail = segs[0], segs[1:]
    rg = None
    if len(tail) >= 2 and tail[0].lower() == "resourcegroups":
        rg, tail = tail[1], tail[2:]
    if not tail or tail[0].lower() != "providers" or len(tail) < 4:
        return "", "", ""
    after = tail[1:]
    top = f"/subscriptions/{sub}" + (f"/resourceGroups/{rg}" if rg else "") + "/providers/" + "/".join(after[:3])
    typ = "/".join([after[0]] + [after[k] for k in range(1, len(after), 2)])
    return top, typ, after[-1] if len(after) % 2 == 1 else after[-2]


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
        bare = path.split("?", 1)[0].rstrip("/")
        if bare.endswith("/tenants") and method == "GET":
            return _ok(tenants_doc())
        if bare.endswith("/subscriptions") and method == "GET":
            return _ok({"value": [subscription_doc()]})
        i = path.find("/subscriptions/")
        if i == -1:
            return _err(404, "NotFound", f"Not an ARM path: {path}")
        rest = path[i + len("/subscriptions/"):].split("?", 1)[0]
        self._evented = False
        resp = self._arm(method, rest, query, body if isinstance(body, dict) else {})
        if method != "GET" and resp.get("status", 500) < 300 and not self._evented:
            scope, typ, name = _event_target(rest)
            if scope:
                self._event(method, scope, typ, name)
        return resp

    # ── ARM dispatcher (port of handle_arm) ───────────────────────────────
    def _arm(self, method, rest, query, payload):
        base = self._base
        segs = [s for s in rest.split("/") if s != ""]
        if not segs:
            return _err(400, "BadRequest", "Missing subscription id.")
        if not is_space_subscription(segs[0]):
            code, err = subscription_not_found(segs[0])
            return {"status": code, "headers": {}, "body": err}
        adopt_foreign_subscriptions(self.state)
        sub = DEFAULT_SUBSCRIPTION
        rest_segs = segs[1:]

        if not rest_segs:
            return _ok(subscription_doc())

        if len(rest_segs) == 1 and rest_segs[0].lower() == "locations" and method == "GET":
            return _ok(ext_engine.subscription_locations(sub))

        # resource groups
        if rest_segs[0].lower() == "resourcegroups" and len(rest_segs) <= 2:
            if len(rest_segs) == 1:
                if method == "GET":
                    return _ok({"value": list_resource_groups(self.state)})
                return _err(405, "MethodNotAllowed", "Use PUT /resourcegroups/{name}.")
            code, body = resource_group_item(self.state, method, rest_segs[1], payload)
            return {"status": code, "headers": {}, "body": body}
        if len(rest_segs) == 3 and rest_segs[0].lower() == "resourcegroups" \
                and rest_segs[2].lower() == "resources" and method == "GET":
            res = list_group_resources(self.state, rest_segs[1])
            if res is None:
                code, body = resource_group_item(self.state, "GET", rest_segs[1], {})
                return {"status": code, "headers": {}, "body": body}
            return _ok({"value": res})

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

        # Management locks guard every write; the shared ext core models locks,
        # identities, resource health, NICs/public IPs, schedules, run commands.
        if method in ("PUT", "PATCH", "DELETE", "POST"):
            lk = ext_engine.lock_conflict(self.state, ext_engine.target_id(sub, rg, after), method)
            if lk:
                return {"status": lk["status"], "headers": {}, "body": lk["body"]}
        x = ext_engine.route(self.state, method, sub, rg, after, payload, query, executor=None,
                             blob=getattr(self, "blob_hook", None))
        if x is not None:
            if method != "GET" and x["status"] < 300 and x.get("scope"):
                self._event(method, x["scope"], x["type"], x["name"])
            return {"status": x["status"], "headers": dict(x.get("headers") or {}), "body": x["body"]}

        namespace = after[0]
        chain = after[1:]
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

        top = _BY_TYPE.get((namespace.lower(), type_chain[1].lower()))
        if top is None:
            supported = ", ".join(sorted(c["namespace"] + "/" + c["type"] for c in CATALOG))
            return _err(404, "ResourceTypeNotSupported",
                        f"Type '{namespace}/{type_chain[1]}' is not simulated. Supported: {supported}.")

        # Microsoft.App (Container Apps): the substrate-free engine owns the semantics; this
        # class's flat store is its resource map (so it persists with the rest of ARM).
        if namespace.lower() == "microsoft.app":
            return self._app(method, sub, rg, chain, payload, query)

        # POST action verbs (listKeys / start / powerOff / …)
        if method == "POST" and is_collection and len(type_chain) >= 3 and names:
            parent_rid = _canonical_id(sub, rg, type_chain[:-1], names)
            return self._arm_action(type_chain[-1].lower(), type_chain, names[-1], parent_rid)

        full_type = "/".join(type_chain)
        if is_collection:
            if method != "GET":
                return _err(405, "MethodNotAllowed", "Collection supports GET only.")
            parent = _canonical_id(sub, rg, type_chain[:-1], names) if names else None
            return self._list(sub, rg, full_type, parent)

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
            ext_engine.after_upsert(self.state, rec)
            return _ok(_view(rec))
        if method in ("PUT", "PATCH"):
            bad = ext_engine.validate_write(self.state, rid, full_type, payload)
            if bad:
                return {"status": bad["status"], "headers": {}, "body": bad["body"]}
            resp = self._upsert(rid, key, full_type, leaf_name, top, payload, base, patch=(method == "PATCH"))
            if full_type.lower() == ext_engine.VM_T and key in self.state:
                ext_engine.after_vm_upsert(self.state, self.state[key])
            if lro:
                resp["status"] = 200
                op_id = self._make_operation(rid, method)
                url = f"{base}/api/azure/operations/{op_id}?api-version={api_version}"
                resp["headers"].update({"Azure-AsyncOperation": url, "Location": url, "Retry-After": "0"})
            return resp
        if method == "DELETE":
            rec = self.state.pop(key, None)
            ext_engine.on_delete(self.state, rec)
            return _ok(None, status=200 if rec is not None else 204)
        return _err(405, "MethodNotAllowed", f"{method} not allowed.")

    def _event(self, method, scope, typ, name):
        """Activity-log hook for every successful write: ``scope`` is the resource
        whose activity log it belongs to (Nano wires ``on_event`` to core/nano_events
        through the registry; a no-op standalone)."""
        self._evented = True
        cb = getattr(self, "on_event", None)
        if cb:
            try:
                cb(method, scope, typ, name)
            except Exception:
                pass

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

    # ── CRUD primitives ───────────────────────────────────────────────────
    def _list(self, sub, rg, full_type, parent=None):
        ft = full_type.lower()
        pfx = parent.lower() + "/" if parent else None
        items = []
        for rec in list(self.state.values()):
            if rec.get("_type", "").lower() != ft:
                continue
            if pfx and not str(rec.get("id", "")).lower().startswith(pfx):
                continue
            if rec.get("_sub") != sub:
                continue
            if rg is not None and (rec.get("_rg") or "").lower() != rg.lower():
                continue
            ext_engine.after_upsert(self.state, rec)
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
        if isinstance(payload.get("properties"), dict):
            rec["properties"] = _merge(rec.get("properties", {}), payload["properties"])
        ext_engine.apply_identity(rec, payload)
        ext_engine.mark_changed(rec)

        rec.setdefault("properties", {})
        rec["properties"].setdefault("provisioningState", "Succeeded")
        ext_engine.after_upsert(self.state, rec, payload)
        for path_expr, suffix in endpoints.items():
            if _get_path(rec, path_expr) in (None, ""):
                _set_path(rec, path_expr, base + suffix.replace("__NAME__", name))

        self.state[key] = rec
        return _ok(_view(rec), status=200 if existed else 201)

    def _arm_action(self, action, type_chain, resource_name, parent_rid=""):
        if action in ("start", "poweroff", "restart", "deallocate"):
            ns = type_chain[0].lower() if type_chain else ""
            typ = type_chain[1].lower() if len(type_chain) > 1 else ""
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

    def _provider_info(self, namespace):
        types = [{"resourceType": c["type"], "apiVersions": [c["api_version"]],
                  "locations": [DEFAULT_LOCATION], "capabilities": "None"}
                 for c in CATALOG if c["namespace"].lower() == namespace.lower()]
        return {"id": f"/subscriptions/{DEFAULT_SUBSCRIPTION}/providers/{namespace}",
                "namespace": namespace, "registrationState": "Registered",
                "registrationPolicy": "RegistrationRequired", "resourceTypes": types}

    def _make_operation(self, resource_id, method, result=None):
        op_id = uuid.uuid4().hex
        now = _now()
        self.operations[op_id] = {"id": op_id, "name": op_id, "status": "Succeeded",
                                   "startTime": now, "endTime": now,
                                   "resourceId": resource_id, "method": method}
        if result:
            self.operations[op_id]["result"] = result
        return op_id
