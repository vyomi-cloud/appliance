# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Azure App Service core (``Microsoft.Web``) — substrate-independent.

Speaks the ARM control-plane REST API of the ``web`` resource provider
(azure-rest-api-specs ``specification/web``), so the native ``azure-mgmt-web`` /
``armappservice`` / ``com.azure.resourcemanager.appservice`` SDKs and
``az webapp`` / ``az appservice plan`` / ``az rest`` work unchanged against it.

NO fastapi / azure-sdk / socket / subprocess imports → loads under Pyodide, so the SAME
file runs offline and in Nano. It does not own a store: it mutates the ARM resource map
the dispatchers already keep (``{lower-cased resource id: record}``), which is
space-scoped and persisted by the existing seams (offline ``azure_arm_state``; Nano
``az_arm`` via core/nano_persist).

Resource types
    Microsoft.Web/serverfarms   (App Service plans)
    Microsoft.Web/sites         (Web Apps) + start/stop/restart/slotsswap,
                                 config/web, config/appsettings, config/connectionstrings,
                                 config/logs, slots, hostNameBindings,
                                 providers/Microsoft.Authorization/locks (resource-scoped locks)

App settings, connection strings, deployment-slot content and resource locks live INSIDE
the site's ARM record (underscore keys, never serialised to clients) so cost/portal views
stay faithful to real ARM (those are separate sub-resources on the wire, GET on the site
itself never returns them).

Every mutating call also drops a ``Microsoft.Insights/eventtypes`` record into the same
shared ARM map (``_record_event``) — the resource's Activity Log blade reads these back
through core/azure_monitor_core.py's ``eventtypes/management/values`` feed, the real API
``az monitor activity-log list`` / the portal's Activity Log use.

Errors use the ARM shape ``{"error":{"code","message"}}``. ``dispatch`` returns
``{"status","headers","body","lro","rid","verb"}``; the caller adds the Azure-AsyncOperation
headers when ``lro`` is true and records the activity/CloudSim event.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

NAMESPACE = "Microsoft.Web"
API_VERSION = "2023-12-01"
DEFAULT_LOCATION = "eastus"
DOMAIN = "azurewebsites.net"

PLAN_SKUS = {
    "F1": ("Free", 1), "D1": ("Shared", 1), "B1": ("Basic", 1), "B2": ("Basic", 2), "B3": ("Basic", 3),
    "S1": ("Standard", 1), "S2": ("Standard", 2), "S3": ("Standard", 3),
    "P1v2": ("PremiumV2", 1), "P2v2": ("PremiumV2", 2), "P3v2": ("PremiumV2", 3),
    "P1v3": ("PremiumV3", 1), "P2v3": ("PremiumV3", 2), "P3v3": ("PremiumV3", 3),
}
DEFAULT_LOGS = {"applicationLogs": {"fileSystem": {"level": "Off"}},
                "httpLogs": {"fileSystem": {"retentionInMb": 35, "retentionInDays": 0, "enabled": False}},
                "detailedErrorMessages": {"enabled": False}, "failedRequestsTracing": {"enabled": False}}


class _E(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _record_event(state, sub, rg, resource_id, op_value, op_text, status="Succeeded"):
    """Append an Activity Log entry (``Microsoft.Insights/eventtypes``) for one mutating call on
    ``resource_id``. Read back by core/azure_monitor_core.py's eventtypes/management/values feed
    (``$filter=resourceUri eq '{resourceId}'``), which is the real Activity Log blade's native call."""
    eid = f"{resource_id}/__event__/{uuid.uuid4().hex}"
    state[eid.lower()] = {
        "id": eid, "_type": "microsoft.insights/eventtypes", "_sub": sub,
        "eventTimestamp": _now(), "resourceId": resource_id, "subscriptionId": sub, "resourceGroupName": rg,
        "caller": "admin@vyomi.local",
        "eventName": {"value": "EndRequest", "localizedValue": "End request"},
        "operationName": {"value": op_value, "localizedValue": op_text},
        "status": {"value": status, "localizedValue": status},
    }


def _view(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def _ok(body=None, status=200, headers=None, lro=False, rid="", verb=""):
    return {"status": status, "headers": headers or {}, "body": body, "lro": lro, "rid": rid, "verb": verb}


def _err(status, code, message):
    return {"status": status, "headers": {}, "body": {"error": {"code": code, "message": message}},
            "lro": False, "rid": "", "verb": ""}


def _merge(a, b):
    out = dict(a)
    for k, v in (b or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def _to_bool(v, default=False):
    if v is None:
        return default
    return v if isinstance(v, bool) else str(v).strip().lower() in ("true", "1", "yes", "on")


def _to_int(v, default=None):
    if isinstance(v, bool):
        return default
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _canon(sub, rg, chain, names):
    seg = ["/subscriptions/" + sub] + (["resourceGroups/" + rg] if rg else []) + ["providers", NAMESPACE]
    for i, t in enumerate(chain):
        seg.append(t)
        if i < len(names):
            seg.append(names[i])
    return "/".join(seg)


def _not_found(kind, name, rg):
    return _E(404, "ResourceNotFound",
              f"The Resource '{NAMESPACE}/{kind}/{name}' under resource group '{rg}' was not found.")


def _validate_name(name, what="Web app"):
    if not name or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,58}[A-Za-z0-9]|[A-Za-z0-9]{1,2}", name):
        raise _E(400, "InvalidResourceName",
                 f"{what} name '{name}' is invalid: use 1-60 letters, digits or hyphens, "
                 "and don't start or end with a hyphen.")


# ── App Service plans (Microsoft.Web/serverfarms) ──────────────────────────
def _plan_defaults(sub, rg, name, payload):
    sku_name = (payload.get("sku") or {}).get("name") or "B1"
    tier, cap = PLAN_SKUS.get(sku_name, ("Basic", 1))
    is_linux = _to_bool((payload.get("properties") or {}).get("reserved"))
    rid = _canon(sub, rg, ["serverfarms"], [name])
    return {
        "id": rid, "name": name, "type": f"{NAMESPACE}/serverfarms",
        "location": payload.get("location") or DEFAULT_LOCATION, "kind": "linux" if is_linux else "app",
        "tags": payload.get("tags") or {},
        "sku": {"name": sku_name, "tier": tier, "size": sku_name, "family": sku_name[0], "capacity": cap},
        "properties": {"reserved": is_linux, "maximumNumberOfWorkers": 30 if tier != "Free" else 1,
                       "zoneRedundant": _to_bool((payload.get("properties") or {}).get("zoneRedundant")),
                       "provisioningState": "Succeeded", "status": "Ready"},
        "_type": f"{NAMESPACE}/serverfarms", "_sub": sub, "_rg": rg, "_created": _now(),
    }


def _plan_view(state, rec):
    v = _view(rec)
    n = sum(1 for r in state.values() if str(r.get("_type", "")).lower() == f"{NAMESPACE}/sites".lower()
            and (r.get("properties") or {}).get("serverFarmId", "").lower() == rec["id"].lower())
    v = dict(v)
    v["properties"] = dict(v["properties"], numberOfSites=n)
    return v


def _plan_ops(state, sub, rg, chain, method, payload):
    if len(chain) == 1:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        items = [_plan_view(state, r) for r in state.values()
                 if str(r.get("_type", "")).lower() == f"{NAMESPACE}/serverfarms".lower() and r.get("_sub") == sub
                 and (rg is None or (r.get("_rg") or "").lower() == (rg or "").lower())]
        return _ok({"value": items})
    name = chain[1]
    rid = _canon(sub, rg, ["serverfarms"], [name])
    rec = state.get(rid.lower())
    if method == "GET":
        if not rec:
            raise _not_found("serverfarms", name, rg)
        return _ok(_plan_view(state, rec))
    if method in ("PUT", "PATCH"):
        if rg is None:
            return _err(400, "InvalidResourceId", "App Service plans must be created in a resource group.")
        _validate_name(name, "App Service plan")
        if method == "PATCH" and rec:
            if isinstance(payload.get("tags"), dict):
                rec["tags"] = payload["tags"]
            if (payload.get("sku") or {}).get("name"):
                tier, cap = PLAN_SKUS.get(payload["sku"]["name"], (rec["sku"]["tier"], rec["sku"]["capacity"]))
                rec["sku"] = {"name": payload["sku"]["name"], "tier": tier, "size": payload["sku"]["name"], "family": payload["sku"]["name"][0], "capacity": cap}
        else:
            existed = rec is not None
            rec = _plan_defaults(sub, rg, name, payload)
            state[rid.lower()] = rec
            return _ok(_plan_view(state, rec), 200 if existed else 201, lro=True, rid=rid, verb=method.lower())
        return _ok(_plan_view(state, rec), 200)
    if method == "DELETE":
        if rec:
            in_use = [r for r in state.values() if str(r.get("_type", "")).lower() == f"{NAMESPACE}/sites".lower()
                      and (r.get("properties") or {}).get("serverFarmId", "").lower() == rid.lower()]
            if in_use:
                raise _E(409, "ServerFarmInUse", f"App Service plan '{name}' still has {len(in_use)} web app(s). Delete them first.")
        state.pop(rid.lower(), None)
        return _ok(None, 200 if rec else 204, rid=rid, verb="delete")
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


def _ensure_plan(state, sub, rg, site_name, payload):
    """Sites created without an explicit serverFarmId get one auto-provisioned
    (the real portal always creates/reuses a plan as part of the Web App wizard)."""
    sf = (payload.get("properties") or {}).get("serverFarmId")
    if sf:
        rec = state.get(sf.lower())
        if not rec or str(rec.get("_type", "")).lower() != f"{NAMESPACE}/serverfarms".lower():
            raise _E(400, "ServerFarmNotFound", f"App Service plan '{sf}' was not found.")
        return sf
    plan_name = f"{site_name}-plan"
    rid = _canon(sub, rg, ["serverfarms"], [plan_name])
    is_linux = "linux" in (payload.get("kind") or "").lower()
    if rid.lower() not in state:
        state[rid.lower()] = _plan_defaults(sub, rg, plan_name, {"location": payload.get("location"), "properties": {"reserved": is_linux}})
    return rid


# ── Web Apps (Microsoft.Web/sites) ──────────────────────────────────────────
def _default_site_config(is_linux):
    cfg = {
        "numberOfWorkers": 1, "defaultDocuments": ["Default.htm", "Default.html", "Default.asp", "index.htm", "index.html", "iisstart.htm"],
        "netFrameworkVersion": "v4.0", "phpVersion": "", "pythonVersion": "", "linuxFxVersion": "",
        "requestTracingEnabled": False, "remoteDebuggingEnabled": False, "httpLoggingEnabled": False,
        "alwaysOn": False, "use32BitWorkerProcess": True, "webSocketsEnabled": False,
        "managedPipelineMode": "Integrated", "ftpsState": "AllAllowed", "http20Enabled": False,
        "minTlsVersion": "1.2", "scmMinTlsVersion": "1.2", "clientCertEnabled": False, "clientCertMode": "Required",
        "healthCheckPath": "", "scmType": "None", "appCommandLine": "",
        "scmBasicAuthEnabled": True, "ftpBasicAuthEnabled": True, "sessionAffinityEnabled": True,
        "continuousDeploymentEnabled": False, "basicAuthEnabled": False,
    }
    if is_linux:
        cfg["use32BitWorkerProcess"] = False
    return cfg


def _site_defaults(sub, rg, name, payload, plan_id):
    is_linux = "linux" in (payload.get("kind") or "").lower()
    rid = _canon(sub, rg, ["sites"], [name])
    host = f"{name}.{DOMAIN}"
    cfg = _merge(_default_site_config(is_linux), (payload.get("properties") or {}).get("siteConfig") or {})
    runtime = (payload.get("properties") or {}).get("siteConfig", {}).get("linuxFxVersion") or ""
    return {
        "id": rid, "name": name, "type": f"{NAMESPACE}/sites",
        "location": payload.get("location") or DEFAULT_LOCATION, "kind": payload.get("kind") or ("app,linux" if is_linux else "app"),
        "tags": payload.get("tags") or {},
        "properties": {
            "serverFarmId": plan_id, "state": "Running", "enabled": True,
            "defaultHostName": host, "hostNames": [host], "enabledHostNames": [host, f"{name}.scm.{DOMAIN}"],
            "repositorySiteName": name, "usageState": "Normal", "availabilityState": "Normal",
            "httpsOnly": _to_bool((payload.get("properties") or {}).get("httpsOnly")),
            "clientAffinityEnabled": _to_bool((payload.get("properties") or {}).get("clientAffinityEnabled"), True),
            "publicNetworkAccess": (payload.get("properties") or {}).get("publicNetworkAccess") or "Enabled",
            "siteConfig": cfg, "outboundIpAddresses": "10.10.0.4,10.10.0.5,10.10.0.6",
            "possibleOutboundIpAddresses": "10.10.0.4,10.10.0.5,10.10.0.6,10.10.0.7,10.10.0.8",
            "provisioningState": "Succeeded", "runtime": runtime,
        },
        "_type": f"{NAMESPACE}/sites", "_sub": sub, "_rg": rg, "_created": _now(),
        "_appsettings": dict((payload.get("_appsettings")) or {}),
        "_connectionstrings": {},
        "_logs": dict(DEFAULT_LOGS),
        "_slots": {},
        "_locks": {},
        "_hostnamebindings": {},
    }


def _slot_view(site, slot_name, slot):
    host = f"{site['name']}-{slot_name}.{DOMAIN}"
    return {
        "id": f"{site['id']}/slots/{slot_name}", "name": f"{site['name']}/{slot_name}",
        "type": f"{NAMESPACE}/sites/slots", "location": site["location"], "kind": site["kind"], "tags": {},
        "properties": {
            "serverFarmId": site["properties"]["serverFarmId"], "state": slot.get("state", "Running"),
            "enabled": True, "defaultHostName": host, "hostNames": [host],
            "siteConfig": slot.get("siteConfig") or _default_site_config("linux" in site["kind"]),
            "targetSwapSlot": None, "provisioningState": "Succeeded",
        },
    }


def _site_ops(state, sub, rg, chain, method, payload):
    if len(chain) == 1:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        items = [_view(r) for r in state.values() if str(r.get("_type", "")).lower() == f"{NAMESPACE}/sites".lower()
                 and r.get("_sub") == sub and (rg is None or (r.get("_rg") or "").lower() == (rg or "").lower())]
        return _ok({"value": items})
    name = chain[1]
    rid = _canon(sub, rg, ["sites"], [name])
    rec = state.get(rid.lower())
    rest = chain[2:]
    if rest:
        if rec is None:
            raise _not_found("sites", name, rg)
        return _site_subresource(state, rec, rest, method, payload)
    if method == "GET":
        if not rec:
            raise _not_found("sites", name, rg)
        return _ok(_view(rec))
    if method in ("PUT", "PATCH"):
        if rg is None:
            return _err(400, "InvalidResourceId", "Web Apps must be created in a resource group.")
        _validate_name(name)
        if method == "PATCH" and rec:
            if isinstance(payload.get("tags"), dict):
                rec["tags"] = payload["tags"]
            props = payload.get("properties") or {}
            if "siteConfig" in props:
                rec["properties"]["siteConfig"] = _merge(rec["properties"]["siteConfig"], props["siteConfig"])
            for fld in ("httpsOnly", "clientAffinityEnabled", "enabled"):
                if fld in props:
                    rec["properties"][fld] = _to_bool(props[fld])
            if "publicNetworkAccess" in props:
                rec["properties"]["publicNetworkAccess"] = props["publicNetworkAccess"]
            return _ok(_view(rec), 200)
        existed = rec is not None
        plan_id = _ensure_plan(state, sub, rg, name, payload)
        if existed:
            rec["location"] = payload.get("location") or rec["location"]
            if isinstance(payload.get("tags"), dict):
                rec["tags"] = payload["tags"]
            props = payload.get("properties") or {}
            rec["properties"]["serverFarmId"] = plan_id
            if "siteConfig" in props:
                rec["properties"]["siteConfig"] = _merge(rec["properties"]["siteConfig"], props["siteConfig"])
            for fld in ("httpsOnly", "clientAffinityEnabled"):
                if fld in props:
                    rec["properties"][fld] = _to_bool(props[fld])
            if "publicNetworkAccess" in props:
                rec["properties"]["publicNetworkAccess"] = props["publicNetworkAccess"]
        else:
            rec = _site_defaults(sub, rg, name, payload, plan_id)
            state[rid.lower()] = rec
        _record_event(state, sub, rg, rid, f"{NAMESPACE}/sites/write", f"{'Update' if existed else 'Create'} Web App '{name}'")
        return _ok(_view(rec), 200 if existed else 201, lro=True, rid=rid, verb=method.lower())
    if method == "DELETE":
        state.pop(rid.lower(), None)
        if rec:
            _record_event(state, sub, rg, rid, f"{NAMESPACE}/sites/delete", f"Delete Web App '{name}'")
        return _ok(None, 200 if rec else 204, rid=rid, verb="delete")
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


def _swap(rec, target, slots):
    if target == "production":
        prod_cfg = {"siteConfig": rec["properties"]["siteConfig"], "appsettings": rec["_appsettings"], "connectionstrings": rec["_connectionstrings"]}
        slot = slots.get(target)
    else:
        slot = slots.get(target)
        if slot is None:
            raise _E(404, "SlotNotFound", f"Deployment slot '{target}' was not found.")
        prod_cfg = {"siteConfig": rec["properties"]["siteConfig"], "appsettings": rec["_appsettings"], "connectionstrings": rec["_connectionstrings"]}
        rec["properties"]["siteConfig"] = slot.get("siteConfig") or _default_site_config("linux" in rec["kind"])
        rec["_appsettings"] = slot.get("appsettings") or {}
        rec["_connectionstrings"] = slot.get("connectionstrings") or {}
        slot["siteConfig"], slot["appsettings"], slot["connectionstrings"] = prod_cfg["siteConfig"], prod_cfg["appsettings"], prod_cfg["connectionstrings"]


def _site_subresource(state, rec, rest, method, payload):
    r0 = rest[0].lower()
    if r0 in ("start", "stop", "restart") and method == "POST":
        rec["properties"]["state"] = "Stopped" if r0 == "stop" else "Running"
        _record_event(state, rec["_sub"], rec["_rg"], rec["id"], f"{NAMESPACE}/sites/{r0}/action", f"{r0.capitalize()} Web App '{rec['name']}'")
        return _ok(None, 200)
    if r0 == "slotsswap" and method == "POST":
        target = (payload or {}).get("targetSlot") or "production"
        _swap(rec, target, rec["_slots"])
        _record_event(state, rec["_sub"], rec["_rg"], rec["id"], f"{NAMESPACE}/sites/slotsswap/action", f"Swap Web App '{rec['name']}' deployment slots")
        return _ok(None, 200, lro=True, rid=rec["id"], verb="slotsswap")
    if r0 == "config":
        return _config_ops(state, rec, rest[1:], method, payload)
    if r0 == "slots":
        return _slot_ops(state, rec, rest[1:], method, payload)
    if r0 == "hostnamebindings":
        return _hostname_ops(state, rec, rest[1:], method, payload)
    if r0 == "providers" and len(rest) >= 3 and rest[1].lower() == "microsoft.authorization" and rest[2].lower() == "locks":
        return _lock_ops(state, rec, rest[3:], method, payload)
    return _err(404, "ResourceTypeNotSupported", f"'{'/'.join(rest)}' is not supported on sites.")


_CONFIG_LABELS = {"web": "configuration", "appsettings": "application settings", "connectionstrings": "connection strings", "logs": "App Service logs"}


def _config_ops(state, rec, rest, method, payload):
    if not rest:
        return _err(404, "NotFound", "Missing config name.")
    kind = rest[0].lower()
    tail = rest[1:]
    is_list = tail and tail[0].lower() == "list"

    def saved():
        _record_event(state, rec["_sub"], rec["_rg"], rec["id"], f"{NAMESPACE}/sites/config/write",
                       f"Update {_CONFIG_LABELS[kind]} for Web App '{rec['name']}'")

    if kind == "web":
        if method == "GET":
            return _ok({"properties": rec["properties"]["siteConfig"]})
        if method in ("PUT", "PATCH"):
            rec["properties"]["siteConfig"] = _merge(rec["properties"]["siteConfig"], payload.get("properties") or payload or {})
            saved()
            return _ok({"properties": rec["properties"]["siteConfig"]}, 200)
    elif kind == "appsettings":
        if method == "GET" or (method == "POST" and is_list):
            return _ok({"properties": dict(rec["_appsettings"])})
        if method == "PUT":
            rec["_appsettings"] = dict((payload.get("properties") or payload) or {})
            saved()
            return _ok({"properties": dict(rec["_appsettings"])}, 200)
    elif kind == "connectionstrings":
        if method == "GET" or (method == "POST" and is_list):
            return _ok({"properties": dict(rec["_connectionstrings"])})
        if method == "PUT":
            rec["_connectionstrings"] = dict((payload.get("properties") or payload) or {})
            saved()
            return _ok({"properties": dict(rec["_connectionstrings"])}, 200)
    elif kind == "logs":
        if method == "GET":
            return _ok({"properties": rec["_logs"]})
        if method in ("PUT", "PATCH"):
            rec["_logs"] = _merge(rec["_logs"], payload.get("properties") or payload or {})
            saved()
            return _ok({"properties": rec["_logs"]}, 200)
    else:
        return _err(404, "ResourceTypeNotSupported", f"config/{kind} is not supported.")
    return _err(405, "MethodNotAllowed", f"{method} not allowed on config/{kind}.")


def _slot_ops(state, rec, rest, method, payload):
    if not rest:
        if method == "GET":
            return _ok({"value": [_slot_view(rec, n, s) for n, s in sorted(rec["_slots"].items())]})
        return _err(405, "MethodNotAllowed", "Collection supports GET only.")
    name = rest[0]
    tail = rest[1:]
    if tail:
        if name not in rec["_slots"]:
            raise _E(404, "SlotNotFound", f"Deployment slot '{name}' was not found.")
        if tail[0].lower() in ("start", "stop", "restart") and method == "POST":
            rec["_slots"][name]["state"] = "Stopped" if tail[0].lower() == "stop" else "Running"
            return _ok(None, 200)
        return _err(404, "ResourceTypeNotSupported", f"slots/{tail[0]} is not supported.")
    if method == "GET":
        if name not in rec["_slots"]:
            raise _E(404, "SlotNotFound", f"Deployment slot '{name}' was not found.")
        return _ok(_slot_view(rec, name, rec["_slots"][name]))
    if method == "PUT":
        existed = name in rec["_slots"]
        rec["_slots"][name] = {"state": "Running", "siteConfig": dict(rec["properties"]["siteConfig"]), "appsettings": {}, "connectionstrings": {}}
        _record_event(state, rec["_sub"], rec["_rg"], rec["id"], f"{NAMESPACE}/sites/slots/write",
                      f"{'Update' if existed else 'Create'} deployment slot '{name}' on Web App '{rec['name']}'")
        return _ok(_slot_view(rec, name, rec["_slots"][name]), 200 if existed else 201, lro=True, rid=f"{rec['id']}/slots/{name}", verb=method.lower())
    if method == "DELETE":
        had = rec["_slots"].pop(name, None)
        if had:
            _record_event(state, rec["_sub"], rec["_rg"], rec["id"], f"{NAMESPACE}/sites/slots/delete", f"Delete deployment slot '{name}' on Web App '{rec['name']}'")
        return _ok(None, 200 if had else 204)
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


def _hostname_ops(state, rec, rest, method, payload):
    if not rest:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        items = [{"id": f"{rec['id']}/hostNameBindings/{h}", "name": h, "type": f"{NAMESPACE}/sites/hostNameBindings",
                  "properties": {"siteName": rec["name"], "hostNameType": "Verified", "sslState": b.get("sslState", "Disabled")}}
                 for h, b in rec["_hostnamebindings"].items()]
        return _ok({"value": items})
    host = rest[0]
    if method == "GET":
        if host not in rec["_hostnamebindings"]:
            raise _E(404, "HostNameBindingNotFound", f"Custom domain '{host}' was not found.")
        b = rec["_hostnamebindings"][host]
        return _ok({"id": f"{rec['id']}/hostNameBindings/{host}", "name": host, "type": f"{NAMESPACE}/sites/hostNameBindings",
                    "properties": {"siteName": rec["name"], "hostNameType": "Verified", "sslState": b.get("sslState", "Disabled")}})
    if method == "PUT":
        existed = host in rec["_hostnamebindings"]
        rec["_hostnamebindings"][host] = {"sslState": (payload.get("properties") or payload or {}).get("sslState", "Disabled")}
        rec["properties"]["hostNames"] = sorted(set(rec["properties"]["hostNames"]) | {host})
        _record_event(state, rec["_sub"], rec["_rg"], rec["id"], f"{NAMESPACE}/sites/hostNameBindings/write",
                      f"Add custom domain '{host}' to Web App '{rec['name']}'")
        return _ok({"id": f"{rec['id']}/hostNameBindings/{host}", "name": host, "properties": rec["_hostnamebindings"][host]}, 200 if existed else 201)
    if method == "DELETE":
        had = rec["_hostnamebindings"].pop(host, None)
        if had is not None:
            rec["properties"]["hostNames"] = [h for h in rec["properties"]["hostNames"] if h != host]
            _record_event(state, rec["_sub"], rec["_rg"], rec["id"], f"{NAMESPACE}/sites/hostNameBindings/delete",
                          f"Remove custom domain '{host}' from Web App '{rec['name']}'")
        return _ok(None, 200 if had else 204)
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


_LOCK_LEVELS = ("CanNotDelete", "ReadOnly")


def _lock_ops(state, rec, rest, method, payload):
    if not rest:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        items = [{"id": f"{rec['id']}/providers/Microsoft.Authorization/locks/{n}", "name": n,
                  "type": "Microsoft.Authorization/locks", "properties": lk} for n, lk in rec["_locks"].items()]
        return _ok({"value": items})
    name = rest[0]
    if method == "GET":
        if name not in rec["_locks"]:
            raise _E(404, "LockNotFound", f"Lock '{name}' was not found.")
        return _ok({"id": f"{rec['id']}/providers/Microsoft.Authorization/locks/{name}", "name": name,
                    "type": "Microsoft.Authorization/locks", "properties": rec["_locks"][name]})
    if method in ("PUT", "PATCH"):
        props = payload.get("properties") or payload or {}
        level = props.get("level") or "CanNotDelete"
        if level not in _LOCK_LEVELS:
            return _err(400, "InvalidLockLevel", f"Lock level must be one of {_LOCK_LEVELS}.")
        existed = name in rec["_locks"]
        rec["_locks"][name] = {"level": level, "notes": props.get("notes", "")}
        _record_event(state, rec["_sub"], rec["_rg"], rec["id"], "Microsoft.Authorization/locks/write",
                      f"Create a lock '{name}' on Web App '{rec['name']}'")
        return _ok({"id": f"{rec['id']}/providers/Microsoft.Authorization/locks/{name}", "name": name, "properties": rec["_locks"][name]}, 200 if existed else 201)
    if method == "DELETE":
        had = rec["_locks"].pop(name, None)
        if had:
            _record_event(state, rec["_sub"], rec["_rg"], rec["id"], "Microsoft.Authorization/locks/delete",
                          f"Delete lock '{name}' on Web App '{rec['name']}'")
        return _ok(None, 200 if had else 204)
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


# ── dispatch ─────────────────────────────────────────────────────────────────
def dispatch(state, method, sub, rg, chain, names, payload=None, query=None):
    """Handle one ``Microsoft.Web`` ARM request.

    ``chain`` = path tokens after the namespace, e.g. ``["sites", "my-app", "config", "web"]``
    ``state`` = the ARM resource map (lower-cased id → record), shared with the rest of ARM.
    """
    method = (method or "GET").upper()
    payload = payload if isinstance(payload, dict) else {}
    try:
        kind = chain[0].lower() if chain else ""
        if kind == "serverfarms":
            return _plan_ops(state, sub, rg, chain, method, payload)
        if kind == "sites":
            return _site_ops(state, sub, rg, chain, method, payload)
        return _err(404, "ResourceTypeNotSupported", f"The resource type '{NAMESPACE}/{chain[0] if chain else ''}' is not supported.")
    except _E as e:
        return _err(e.status, e.code, e.message)


def handles(chain):
    return bool(chain) and chain[0].lower() in ("serverfarms", "sites")
