# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Azure App Service core (``Microsoft.Web``) — substrate-independent, ONE engine for
Web Apps, Function Apps and App Service plans.

Speaks the ARM control-plane REST API of the ``web`` resource provider
(azure-rest-api-specs ``specification/web``, api-version 2023-12-01), so the native
``azure-mgmt-web`` / ``armappservice`` / ``com.azure.resourcemanager.appservice`` SDKs and
``az webapp`` / ``az functionapp`` / ``az appservice plan`` / ``az rest`` work unchanged
against it.

NO fastapi / azure-sdk / socket / subprocess imports → loads under Pyodide, so the SAME
file runs offline and in Nano. It does not own a store: it mutates the ARM resource map
the dispatchers already keep (``{lower-cased resource id: record}``), which is
space-scoped and persisted by the existing seams (offline ``azure_arm_state``; Nano
``az_arm`` via core/nano_persist).

Like real ARM, web apps and function apps are the SAME resource type
(``Microsoft.Web/sites``) told apart by ``kind`` (``app``, ``app,linux``, ``functionapp``…):
a sites list returns both and each portal blade filters by kind. Create-time defaults and
the kind-specific sub-resources are chosen by kind; everything else is shared.

Resource types
    Microsoft.Web/serverfarms   App Service plans (numberOfSites, in-use delete guard, SKU PATCH
                                for "Scale up"); sites PATCH serverFarmId moves a site onto
                                another existing plan ("Change App Service plan")
    Microsoft.Web/sites         both kinds:
        shared       start/stop/restart, publishxml/resetpublishxml, identity (top-level field:
                     SystemAssigned mints a stable principalId/tenantId),
                     config/web|appsettings|connectionstrings|logs|backup (GET, POST [.../list],
                     PUT, PATCH), backups/{id} (+ restore) — modelled as snapshots,
                     providers/Microsoft.Authorization/locks/{name} and the short ``locks/{name}``
                     form — both stored by core/azure_locks_core.py (one lock store for all of ARM)
        web apps     slots/{name} (+ start/stop/restart), slotsswap, hostNameBindings/{host}
        functionapp  functions/{name} (+ listkeys, keys/{name}, invoke), host/default/listkeys,
                     host/default/functionkeys|systemkeys/{name}

App settings, connection strings, functions, keys, slots and custom domains live
INSIDE the site record (underscore keys, never serialised to clients) — on the wire they
are separate sub-resources; GET on the site itself never returns them.

Activity log: every successful mutating call drops a ``Microsoft.Insights/eventtypes``
record into the same shared ARM map (``_record_event``); core/azure_monitor_core.py's
``eventtypes/management/values`` feed reads them back (the real API behind
``az monitor activity-log list`` / the portal's Activity log blade). Persisted with the
rest of ARM; capped per resource.

Function invoke is a REAL, sandboxed Python execution (no process/filesystem/network
access) — the same restricted-exec technique as core/lambda_core.py's Invoke.

Errors use the ARM shape ``{"error":{"code","message"}}``. ``dispatch`` returns
``{"status","headers","body","lro","rid","verb"}``; the caller adds the
Azure-AsyncOperation headers when ``lro`` is true.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import re
import uuid
from datetime import datetime, timezone

NAMESPACE = "Microsoft.Web"
API_VERSION = "2023-12-01"
DEFAULT_LOCATION = "eastus"
DOMAIN = "azurewebsites.net"
TYPES = ("serverfarms", "sites")
SITES_TYPE = f"{NAMESPACE}/sites"
PLANS_TYPE = f"{NAMESPACE}/serverfarms"
EVENT_TYPE = "microsoft.insights/eventtypes"
EVENTS_PER_RESOURCE = 200

PLAN_SKUS = {
    "F1": ("Free", 1), "D1": ("Shared", 1), "B1": ("Basic", 1), "B2": ("Basic", 2), "B3": ("Basic", 3),
    "S1": ("Standard", 1), "S2": ("Standard", 2), "S3": ("Standard", 3),
    "P1v2": ("PremiumV2", 1), "P2v2": ("PremiumV2", 2), "P3v2": ("PremiumV2", 3),
    "P1v3": ("PremiumV3", 1), "P2v3": ("PremiumV3", 2), "P3v3": ("PremiumV3", 3),
    "Y1": ("Dynamic", 0), "FC1": ("FlexConsumption", 0), "EP1": ("ElasticPremium", 1),
}
RUNTIME_VERSIONS = {
    ".NET": ["8.0", "6.0"], "Java": ["21", "17", "11"], "Node.js": ["20 LTS", "18 LTS"],
    "PowerShell Core": ["7.4", "7.2"], "Python": ["3.12", "3.11", "3.10", "3.9"], "Custom Handler": ["-"],
}
LOCK_LEVELS = ("CanNotDelete", "ReadOnly")
DEFAULT_LOGS = {"applicationLogs": {"fileSystem": {"level": "Off"}},
                "httpLogs": {"fileSystem": {"retentionInMb": 35, "retentionInDays": 0, "enabled": False}},
                "detailedErrorMessages": {"enabled": False}, "failedRequestsTracing": {"enabled": False}}
DEFAULT_BACKUP_CONFIG = {"enabled": False, "storageAccountUrl": "",
                         "backupSchedule": {"frequencyInterval": 1, "frequencyUnit": "Day",
                                            "keepAtLeastOneBackup": True, "retentionPeriodInDays": 30, "startTime": None}}
# Site properties a client may not set (server-computed).
_READONLY_PROPS = {"state", "defaultHostName", "hostNames", "enabledHostNames", "usageState", "availabilityState",
                   "provisioningState", "outboundIpAddresses", "possibleOutboundIpAddresses", "repositorySiteName",
                   "defaultHostNameSslState", "serverFarmId", "siteConfig", "functionAppConfig"}
_BOOL_PROPS = {"httpsOnly", "clientAffinityEnabled", "enabled", "reserved"}

# A curated safe builtins subset for function invoke — no open / exec / eval / compile /
# __import__ of anything outside _SAFE_MODULES. Mirrors core/lambda_core.py's sandbox.
_SAFE_BUILTINS = {
    name: __builtins__[name] if isinstance(__builtins__, dict) else getattr(__builtins__, name)
    for name in ("abs", "all", "any", "bool", "dict", "enumerate", "filter", "float",
                 "int", "len", "list", "map", "max", "min", "range", "reversed",
                 "round", "set", "sorted", "str", "sum", "tuple", "zip", "print",
                 "isinstance", "hasattr", "getattr", "repr", "type", "chr", "ord",
                 "Exception", "ValueError", "KeyError", "TypeError", "IndexError")
}
_SAFE_MODULES = {"json", "math", "datetime", "base64", "re", "random", "uuid",
                 "hashlib", "hmac", "itertools", "functools", "collections",
                 "string", "decimal", "statistics", "textwrap", "time"}


def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):
    if name.split(".")[0] not in _SAFE_MODULES:
        raise ImportError(f"module '{name}' is not available in the Functions sandbox")
    import importlib
    return importlib.import_module(name)


_SAFE_BUILTINS["__import__"] = _safe_import

DEFAULT_CODE = 'def main(req):\n    """HTTP trigger entry point — echoes the request back."""\n    return {"echo": req, "message": "hello from Azure Functions"}\n'


class _E(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


# ── small helpers ───────────────────────────────────────────────────────────
def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _h(*parts, n=8):
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:n]


def _guid(*parts):
    h = _h(*parts, n=32)
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


def _view(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def _ok(body=None, status=200, headers=None, lro=False, rid="", verb=""):
    return {"status": status, "headers": headers or {}, "body": body, "lro": lro, "rid": rid, "verb": verb}


def _err(status, code, message):
    return {"status": status, "headers": {}, "body": {"error": {"code": code, "message": message}},
            "lro": False, "rid": "", "verb": ""}


def _merge(a, b):
    out = dict(a or {})
    for k, v in (b or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def _to_bool(v, default=False):
    if v is None:
        return default
    return v if isinstance(v, bool) else str(v).strip().lower() in ("true", "1", "yes", "on")


def _props(payload):
    """The ``properties`` bag of a sub-resource PUT; bare bodies are accepted too."""
    payload = payload if isinstance(payload, dict) else {}
    return payload["properties"] if isinstance(payload.get("properties"), dict) else payload


def _canon(sub, rg, chain, names):
    seg = ["/subscriptions/" + sub] + (["resourceGroups/" + rg] if rg else []) + ["providers", NAMESPACE]
    for i, t in enumerate(chain):
        seg.append(t)
        if i < len(names):
            seg.append(names[i])
    return "/".join(seg)


def _not_found(kind, name, rg):
    return _E(404, "ResourceNotFound",
              f"The Resource '{NAMESPACE}/{kind}/{name}' under resource group '{rg}' was not found. "
              "For more details please go to https://aka.ms/ARMResourceNotFoundFix")


def _is_type(rec, full_type):
    return str(rec.get("_type", "")).lower() == full_type.lower()


def _is_fn(rec_or_kind):
    kind = rec_or_kind.get("kind") if isinstance(rec_or_kind, dict) else rec_or_kind
    return "functionapp" in str(kind or "").lower()


def _label(rec):
    return "Function App" if _is_fn(rec) else "Web App"


_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,58}[A-Za-z0-9]|[A-Za-z0-9]{1,2}")


def _validate_name(name, what, fn=False):
    if name and _NAME_RE.fullmatch(name):
        return
    if fn:   # `az functionapp create` surfaces the RP's BadRequest wording
        raise _E(400, "BadRequest", f"Site name '{name}' is invalid. Site names must consist of alphanumeric "
                 "characters and hyphens only, cannot start or end in a hyphen and must be <= 60 characters.")
    raise _E(400, "InvalidResourceName", f"{what} name '{name}' is invalid: use 1-60 letters, digits or hyphens, "
             "and don't start or end with a hyphen.")


# ── activity log (Microsoft.Insights/eventtypes in the shared ARM map) ─────────
_EVENT_SEQ = itertools.count()


def _record_event(state, sub, rg, resource_id, op_value, op_text, status="Succeeded"):
    """Append one Activity Log entry for ``resource_id``. Read back by core/azure_monitor_core.py's
    ``eventtypes/management/values`` feed (``$filter=resourceUri eq '{resourceId}'``)."""
    eid = f"{resource_id}/__event__/{uuid.uuid4().hex}"
    state[eid.lower()] = {
        "id": eid, "_type": EVENT_TYPE, "_sub": sub, "_seq": next(_EVENT_SEQ),
        "eventTimestamp": _now(), "submissionTimestamp": _now(),
        "resourceId": resource_id, "subscriptionId": sub, "resourceGroupName": rg or "",
        "resourceProviderName": {"value": NAMESPACE, "localizedValue": "Microsoft Web"},
        "caller": "admin@vyomi.local", "level": "Informational",
        "eventName": {"value": "EndRequest", "localizedValue": "End request"},
        "operationName": {"value": op_value, "localizedValue": op_text},
        "status": {"value": status, "localizedValue": status},
        "subStatus": {"value": "", "localizedValue": ""},
    }
    mine = [(k, r) for k, r in state.items() if _is_type(r, EVENT_TYPE)
            and str(r.get("resourceId", "")).lower() == resource_id.lower()]
    if len(mine) > EVENTS_PER_RESOURCE:
        mine.sort(key=lambda kv: (kv[1].get("eventTimestamp") or "", kv[1].get("_seq", 0)))
        for k, _ in mine[: len(mine) - EVENTS_PER_RESOURCE]:
            state.pop(k, None)


_SUB_LABELS = {"functions": "function", "keys": "function key", "host": "host key", "locks": "lock",
               "slots": "deployment slot", "hostnamebindings": "custom domain"}
_CONFIG_LABELS = {"web": "configuration", "appsettings": "application settings",
                  "connectionstrings": "connection strings", "logs": "App Service logs", "backup": "backup configuration"}
_LOGGED_ACTIONS = {"start", "stop", "restart", "slotsswap", "resetpublishxml"}
_READ_ACTIONS = {"list", "listkeys", "invoke", "publishxml"}


def _norm_rest(rest):
    """Fold the native lock path ``providers/Microsoft.Authorization/locks/{n}`` onto ``locks/{n}``."""
    if len(rest) >= 3 and rest[0].lower() == "providers" and rest[1].lower() == "microsoft.authorization" \
            and rest[2].lower() == "locks":
        return ["locks"] + list(rest[3:])
    return list(rest)


def _log_site_call(state, rec, rest, method, resp, existed_before):
    """One activity-log row per successful mutating call on a site or one of its sub-resources.
    ``operationName.value`` follows ``Microsoft.Web/sites[/{sub-path}]/{write|delete|action}``."""
    if resp["status"] >= 300 or method == "GET" or (method == "DELETE" and resp["status"] == 204):
        return
    label, name = _label(rec), rec["name"]
    if not rest:
        verb = "delete" if method == "DELETE" else "write"
        what = "Delete" if method == "DELETE" else ("Update" if existed_before else "Create")
        _record_event(state, rec["_sub"], rec["_rg"], rec["id"], f"{SITES_TYPE}/{verb}", f"{what} {label} '{name}'")
        return
    rest = _norm_rest(rest)
    head, tail = rest[0].lower(), rest[-1].lower()
    if len(rest) == 1 and head in _LOGGED_ACTIONS:
        text = "Swap deployment slots of" if head == "slotsswap" else (
            "Reset publish profile of" if head == "resetpublishxml" else head.capitalize())
        _record_event(state, rec["_sub"], rec["_rg"], rec["id"], f"{SITES_TYPE}/{head}/action", f"{text} {label} '{name}'")
        return
    if tail in _READ_ACTIONS or len(rest) == 1:
        return
    if head == "config":
        if method == "POST":   # POST config/{x}[/list] is a read
            return
        kind = rest[1].lower()
        _record_event(state, rec["_sub"], rec["_rg"], rec["id"], f"{SITES_TYPE}/config/{kind}/write",
                      f"Update {_CONFIG_LABELS.get(kind, kind)} for {label} '{name}'")
        return
    if head == "slots" and len(rest) == 3:  # slots/{n}/{start|stop|restart}
        _record_event(state, rec["_sub"], rec["_rg"], rec["id"], f"{SITES_TYPE}/slots/{rest[2].lower()}/action",
                      f"{rest[2].capitalize()} deployment slot '{rest[1]}' on {label} '{name}'")
        return
    verb = "delete" if method == "DELETE" else "write"
    what = "Delete" if method == "DELETE" else ("Create" if resp["status"] == 201 else "Update")
    sub_label = _SUB_LABELS.get(rest[-2].lower(), _SUB_LABELS.get(head, head))
    _record_event(state, rec["_sub"], rec["_rg"], rec["id"], f"{SITES_TYPE}/{'/'.join(rest)}/{verb}",
                  f"{what} {sub_label} '{rest[-1]}' on {label} '{name}'")


# ── App Service plans (Microsoft.Web/serverfarms) ────────────────────────────
def _plan_defaults(sub, rg, name, payload):
    sku_name = (payload.get("sku") or {}).get("name") or "B1"
    tier, cap = PLAN_SKUS.get(sku_name, ("Basic", 1))
    is_linux = _to_bool((payload.get("properties") or {}).get("reserved"))
    rid = _canon(sub, rg, ["serverfarms"], [name])
    return {
        "id": rid, "name": name, "type": PLANS_TYPE,
        "location": payload.get("location") or DEFAULT_LOCATION,
        "kind": payload.get("kind") or ("linux" if is_linux else "app"),
        "tags": payload.get("tags") or {},
        "sku": {"name": sku_name, "tier": tier, "size": sku_name, "family": sku_name[0], "capacity": cap},
        "properties": {"reserved": is_linux, "maximumNumberOfWorkers": 30 if tier != "Free" else 1,
                       "zoneRedundant": _to_bool((payload.get("properties") or {}).get("zoneRedundant")),
                       "provisioningState": "Succeeded", "status": "Ready"},
        "_type": PLANS_TYPE, "_sub": sub, "_rg": rg, "_created": _now(),
    }


def _sites_on(state, plan_id):
    return [r for r in state.values() if _is_type(r, SITES_TYPE)
            and str((r.get("properties") or {}).get("serverFarmId", "")).lower() == plan_id.lower()]


def _plan_view(state, rec):
    v = _view(rec)
    v["properties"] = dict(v["properties"], numberOfSites=len(_sites_on(state, rec["id"])))
    return v


def _plan_ops(state, sub, rg, chain, method, payload):
    if len(chain) == 1:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        items = [_plan_view(state, r) for r in state.values()
                 if _is_type(r, PLANS_TYPE) and r.get("_sub") == sub
                 and (rg is None or (r.get("_rg") or "").lower() == rg.lower())]
        return _ok({"value": items})
    name = chain[1]
    rid = _canon(sub, rg, ["serverfarms"], [name])
    rec = state.get(rid.lower())
    if len(chain) > 2:
        if rec is None:
            raise _not_found("serverfarms", name, rg)
        if chain[2].lower() == "sites" and method == "GET":
            return _ok({"value": [_view(s) for s in _sites_on(state, rid)]})
        return _err(404, "ResourceTypeNotSupported", f"'{'/'.join(chain[2:])}' is not supported on serverfarms.")
    if method == "GET":
        if not rec:
            raise _not_found("serverfarms", name, rg)
        return _ok(_plan_view(state, rec))
    if method in ("PUT", "PATCH"):
        if rg is None:
            return _err(400, "InvalidResourceId", "App Service plans must be created in a resource group.")
        _validate_name(name, "App Service plan")
        existed = rec is not None
        if method == "PATCH" and rec:
            if isinstance(payload.get("tags"), dict):
                rec["tags"] = payload["tags"]
            sku = (payload.get("sku") or {}).get("name")
            if sku:
                tier, cap = PLAN_SKUS.get(sku, (rec["sku"]["tier"], rec["sku"]["capacity"]))
                rec["sku"] = {"name": sku, "tier": tier, "size": sku, "family": sku[0], "capacity": cap}
            resp = _ok(_plan_view(state, rec), 200)
        else:
            rec = _plan_defaults(sub, rg, name, payload)
            state[rid.lower()] = rec
            resp = _ok(_plan_view(state, rec), 200 if existed else 201, lro=True, rid=rid, verb=method.lower())
        _record_event(state, sub, rg, rid, f"{PLANS_TYPE}/write",
                      f"{'Update' if existed else 'Create'} App Service plan '{name}'")
        return resp
    if method == "DELETE":
        if rec:
            in_use = _sites_on(state, rid)
            if in_use:
                raise _E(409, "ServerFarmInUse", f"App Service plan '{name}' still has {len(in_use)} app(s). Delete them first.")
            _record_event(state, sub, rg, rid, f"{PLANS_TYPE}/delete", f"Delete App Service plan '{name}'")
        state.pop(rid.lower(), None)
        return _ok(None, 200 if rec else 204, rid=rid, verb="delete")
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


def _ensure_plan(state, sub, rg, site_name, payload, fn):
    """The plan a new site lands on. An explicit ``serverFarmId`` must exist; without one a plan is
    auto-provisioned, like the portal wizards do (web apps: ``{site}-plan``; function apps: the
    resource group's shared Flex Consumption / Consumption plan)."""
    pay = payload.get("properties") or {}
    sf = pay.get("serverFarmId")
    if sf:
        rec = state.get(sf.lower())
        if not rec or not _is_type(rec, PLANS_TYPE):
            raise _E(400, "ServerFarmNotFound", f"App Service plan '{sf}' was not found.")
        return rec["id"]
    is_linux = "linux" in (payload.get("kind") or "").lower() or _to_bool(pay.get("reserved"))
    if fn:
        flex = bool(pay.get("functionAppConfig"))
        plan_name, sku = (f"FLEX-{rg}", "FC1") if flex else (f"ASP-{rg}-consumption", "Y1")
    else:
        plan_name, sku = f"{site_name}-plan", "B1"
    rid = _canon(sub, rg, ["serverfarms"], [plan_name])
    if rid.lower() not in state:
        state[rid.lower()] = _plan_defaults(sub, rg, plan_name, {
            "location": payload.get("location"), "sku": {"name": sku},
            "kind": "functionapp" if fn else None, "properties": {"reserved": is_linux}})
    return state[rid.lower()]["id"]


# ── sites (Microsoft.Web/sites, both kinds) ───────────────────────────────────
def _default_site_config(is_linux):
    return {
        "numberOfWorkers": 1, "defaultDocuments": ["Default.htm", "Default.html", "Default.asp", "index.htm", "index.html", "iisstart.htm"],
        "netFrameworkVersion": "v4.0", "phpVersion": "", "pythonVersion": "", "linuxFxVersion": "", "windowsFxVersion": "",
        "requestTracingEnabled": False, "remoteDebuggingEnabled": False, "httpLoggingEnabled": False,
        "alwaysOn": False, "use32BitWorkerProcess": not is_linux, "webSocketsEnabled": False,
        "managedPipelineMode": "Integrated", "ftpsState": "AllAllowed", "http20Enabled": False,
        "minTlsVersion": "1.2", "scmMinTlsVersion": "1.2", "clientCertEnabled": False, "clientCertMode": "Required",
        "healthCheckPath": "", "scmType": "None", "appCommandLine": "",
        "scmBasicAuthEnabled": True, "ftpBasicAuthEnabled": True, "sessionAffinityEnabled": True,
        "continuousDeploymentEnabled": False, "basicAuthEnabled": False,
    }


def _fx_version(runtime, version):
    tag = {"Python": "PYTHON", "Node.js": "NODE", ".NET": "DOTNET-ISOLATED", "Java": "JAVA",
           "PowerShell Core": "POWERSHELL", "Custom Handler": "CUSTOM"}.get(runtime, "PYTHON")
    v = (version or "").split(" ")[0]
    return f"{tag}|{v}" if v and v != "-" else tag


def _absorb_site_config(rec, cfg):
    """Merge a client ``siteConfig`` into the site: ``appSettings`` / ``connectionStrings`` arrays go
    to their sub-resource stores (never onto the record), console-only ``_runtime`` hints are dropped."""
    cfg = dict(cfg or {})
    for k in ("_runtime", "_version"):
        cfg.pop(k, None)
    for s in cfg.pop("appSettings", None) or []:
        if isinstance(s, dict) and s.get("name"):
            rec["_appsettings"][s["name"]] = s.get("value", "")
    for c in cfg.pop("connectionStrings", None) or []:
        if isinstance(c, dict) and c.get("name"):
            rec["_connectionstrings"][c["name"]] = {"value": c.get("connectionString", c.get("value", "")),
                                                    "type": c.get("type", "Custom")}
    rec["properties"]["siteConfig"] = _merge(rec["properties"].get("siteConfig"), cfg)


_NO_IDENTITY = {"type": "None", "principalId": None, "tenantId": None, "userAssignedIdentities": None}


def _apply_identity(rec, ident):
    """``identity`` is a top-level sibling of ``properties`` (real ARM shape). System-assigned
    identity gets a stable, deterministic principal/tenant id (minted once, kept across PUT/PATCH
    like the real RP does); switching back to "None" clears it. User-assigned identities are
    stored by resource id but not resolved (Vyomi has no Managed Identity resource of its own)."""
    if ident is None:
        return
    itype = str(ident.get("type") or "None")
    cur = rec.get("identity") or _NO_IDENTITY
    out = {"type": itype, "principalId": None, "tenantId": None,
           "userAssignedIdentities": ident.get("userAssignedIdentities") or {}}
    if "systemassigned" in itype.lower():
        out["principalId"] = cur.get("principalId") or _guid(rec["id"], "principal")
        out["tenantId"] = _guid(rec["_sub"], "tenant")
    rec["identity"] = out


def _ensure(rec):
    """Every site carries every store (records written by older builds are upgraded in place)."""
    if "_connstrings" in rec and "_connectionstrings" not in rec:
        rec["_connectionstrings"] = rec.pop("_connstrings")
    for k, v in (("_appsettings", {}), ("_connectionstrings", {}), ("_logs", None),
                 ("_slots", {}), ("_hostnamebindings", {}), ("_functions", {}), ("_host", None)):
        if k not in rec:
            rec[k] = dict(DEFAULT_LOGS) if k == "_logs" else (
                {"masterKey": _h(rec["id"], "master", n=40), "functionKeys": {"default": _h(rec["id"], "default", n=40)},
                 "systemKeys": {}} if k == "_host" else dict(v))
    rec.setdefault("identity", dict(_NO_IDENTITY))
    rec.setdefault("_backups", {})
    rec.setdefault("_backupconfig", None)
    return rec


def _new_site(state, sub, rg, name, payload):
    fn = _is_fn(payload.get("kind"))
    pay = payload.get("properties") or {}
    rid = _canon(sub, rg, ["sites"], [name])
    host = f"{name}.{DOMAIN}"
    plan_id = _ensure_plan(state, sub, rg, name, payload, fn)
    hx = _h(rid, n=6)
    ip = "52.%d.%d.%d" % (int(hx[0:2], 16) % 200 + 1, int(hx[2:4], 16), int(hx[4:6], 16) % 250 + 1)
    if fn:
        reserved = _to_bool(pay.get("reserved"), False)
        is_linux = _to_bool(pay.get("reserved"), True)
        kind = payload.get("kind") or "functionapp"
    else:
        is_linux = "linux" in (payload.get("kind") or "").lower() or _to_bool(pay.get("reserved"))
        reserved = is_linux
        kind = payload.get("kind") or ("app,linux" if is_linux else "app")
    rec = {
        "id": rid, "name": name, "type": SITES_TYPE, "kind": kind,
        "location": payload.get("location") or DEFAULT_LOCATION, "tags": payload.get("tags") or {},
        "_type": SITES_TYPE, "_sub": sub, "_rg": rg, "_created": _now(),
        "properties": {
            "serverFarmId": plan_id, "state": "Running", "enabled": True,
            "defaultHostName": host, "hostNames": [host], "enabledHostNames": [host, f"{name}.scm.{DOMAIN}"],
            "repositorySiteName": name, "usageState": "Normal", "availabilityState": "Normal",
            "reserved": reserved, "isXenon": False, "hyperV": False,
            "httpsOnly": _to_bool(pay.get("httpsOnly"), fn),
            "clientAffinityEnabled": _to_bool(pay.get("clientAffinityEnabled"), not fn),
            "publicNetworkAccess": pay.get("publicNetworkAccess") or "Enabled",
            "siteConfig": _default_site_config(is_linux),
            "outboundIpAddresses": ip, "possibleOutboundIpAddresses": ",".join([ip, ip.rsplit(".", 1)[0] + ".200"]),
            "defaultHostNameSslState": {"name": host, "sslState": "Disabled", "hostType": "Standard"},
            "provisioningState": "Succeeded",
        },
    }
    _ensure(rec)
    for k, v in pay.items():
        if k not in _READONLY_PROPS and k not in rec["properties"]:
            rec["properties"][k] = v
    cfg = dict(pay.get("siteConfig") or {})
    if fn:
        runtime, version = cfg.get("_runtime", "Python"), cfg.get("_version", "3.12")
        cfg.setdefault("functionAppScaleLimit", 0)
        cfg.setdefault("minimumElasticInstanceCount", 0)
        cfg["linuxFxVersion"] = _fx_version(runtime, version) if is_linux else ""
        cfg["windowsFxVersion"] = "" if is_linux else _fx_version(runtime, version)
        worker = runtime.lower().replace(".net", "dotnet-isolated").replace(" core", "").replace(".js", "")
        rec["_appsettings"].update({"FUNCTIONS_EXTENSION_VERSION": "~4", "FUNCTIONS_WORKER_RUNTIME": worker,
                                    "AzureWebJobsStorage": f"DefaultEndpointsProtocol=https;AccountName=vyomi{_h(name, n=10)};AccountKey=sim;",
                                    "APPINSIGHTS_INSTRUMENTATIONKEY": _h(rid, "aik", n=32)})
        scale = (pay.get("functionAppConfig") or {}).get("scaleAndConcurrency") or {}
        rec["properties"]["sku"] = "FlexConsumption" if pay.get("functionAppConfig") else "Dynamic"
        rec["properties"]["functionAppConfig"] = pay.get("functionAppConfig") or {
            "runtime": {"name": worker, "version": version},
            "scaleAndConcurrency": {"instanceMemoryMB": scale.get("instanceMemoryMB", 2048),
                                    "maximumInstanceCount": scale.get("maximumInstanceCount", 100),
                                    "triggers": scale.get("triggers") or {"http": {"perInstanceConcurrency": 16}}}}
    _absorb_site_config(rec, cfg)
    if not fn:
        rec["properties"]["runtime"] = rec["properties"]["siteConfig"].get("linuxFxVersion") or ""
    rec["identity"] = dict(_NO_IDENTITY)
    _apply_identity(rec, payload.get("identity"))
    return rec


def _update_site(state, rec, payload, method):
    """PUT on an existing site / PATCH: merge the client-settable parts; kind never changes."""
    if method == "PUT" and payload.get("location"):
        rec["location"] = payload["location"]
    if isinstance(payload.get("tags"), dict):
        rec["tags"] = payload["tags"]
    _apply_identity(rec, payload.get("identity"))
    pay = payload.get("properties") or {}
    if pay.get("serverFarmId"):
        rec["properties"]["serverFarmId"] = _ensure_plan(state, rec["_sub"], rec["_rg"], rec["name"], payload, _is_fn(rec))
    if "siteConfig" in pay:
        _absorb_site_config(rec, pay["siteConfig"])
    if "functionAppConfig" in pay:
        rec["properties"]["functionAppConfig"] = _merge(rec["properties"].get("functionAppConfig"), pay["functionAppConfig"])
    for k, v in pay.items():
        if k in _READONLY_PROPS:
            continue
        rec["properties"][k] = _to_bool(v) if k in _BOOL_PROPS else v


def _site_ops(state, sub, rg, chain, method, payload):
    if len(chain) == 1:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        items = [_view(r) for r in state.values() if _is_type(r, SITES_TYPE) and r.get("_sub") == sub
                 and (rg is None or (r.get("_rg") or "").lower() == rg.lower())]
        return _ok({"value": items})
    name = chain[1]
    rid = _canon(sub, rg, ["sites"], [name])
    rec = state.get(rid.lower())
    rest = chain[2:]
    if rest:
        if rec is None:
            raise _not_found("sites", name, rg)
        _ensure(rec)
        _migrate_locks(state, rec)
        resp = _site_subresource(state, rec, rest, method, payload)
        _log_site_call(state, rec, rest, method, resp, True)
        return resp
    if method == "GET":
        if rec is None:
            raise _not_found("sites", name, rg)
        return _ok(_view(rec))
    if method in ("PUT", "PATCH"):
        if rg is None:
            return _err(400, "InvalidResourceId", "Web sites must be created in a resource group.")
        existed = rec is not None
        if method == "PATCH" and not existed:
            raise _not_found("sites", name, rg)
        if existed:
            _migrate_locks(state, rec)
            blocked = _lock_block(state, rec, for_delete=False)
            if blocked:
                return blocked
            _ensure(rec)
            _update_site(state, rec, payload, method)
        else:
            _validate_name(name, "Web app", fn=_is_fn(payload.get("kind")))
            rec = _new_site(state, sub, rg, name, payload)
            state[rid.lower()] = rec
        resp = _ok(_view(rec), 200 if existed else 201, lro=True, rid=rid, verb=method.lower())
        _log_site_call(state, rec, [], method, resp, existed)
        return resp
    if method == "DELETE":
        if rec is not None:
            _migrate_locks(state, rec)
            blocked = _lock_block(state, rec, for_delete=True)
            if blocked:
                return blocked
        state.pop(rid.lower(), None)
        resp = _ok(None, 200 if rec is not None else 204, rid=rid, verb="delete")
        if rec is not None:
            _log_site_call(state, rec, [], method, resp, True)
        return resp
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


_WEB_ONLY = ("slots", "slotsswap", "hostnamebindings")
_FN_ONLY = ("functions", "host")


def _site_subresource(state, rec, rest, method, payload):
    r0 = rest[0].lower()
    fn = _is_fn(rec)
    if (r0 in _WEB_ONLY and fn) or (r0 in _FN_ONLY and not fn):
        return _err(404, "ResourceTypeNotSupported",
                    f"'{rest[0]}' is not supported on a {_label(rec)} (kind '{rec.get('kind')}').")
    if r0 == "config":
        return _config_ops(rec, rest[1:], method, payload)
    if r0 == "locks":
        return _lock_ops(state, rec, rest[1:], method, payload)
    if r0 == "providers" and len(rest) >= 3 and rest[1].lower() == "microsoft.authorization" and rest[2].lower() == "locks":
        return _lock_ops(state, rec, rest[3:], method, payload)
    if r0 == "functions":
        return _functions_ops(rec, rest[1:], method, payload)
    if r0 == "host":
        return _host_ops(rec, rest[1:], method, payload)
    if r0 == "slots":
        return _slot_ops(rec, rest[1:], method, payload)
    if r0 == "hostnamebindings":
        return _hostname_ops(rec, rest[1:], method, payload)
    if r0 == "backups":
        return _backup_ops(rec, rest[1:], method, payload)
    if len(rest) == 1:
        return _site_action(rec, r0, method, payload)
    return _err(404, "ResourceTypeNotSupported", f"'{'/'.join(rest)}' is not supported on sites.")


def _site_action(rec, action, method, payload):
    if method != "POST":
        return _err(405, "MethodNotAllowed", f"{method} not allowed on '{action}'.")
    if action in ("start", "stop", "restart"):
        rec["properties"]["state"] = "Stopped" if action == "stop" else "Running"
        return _ok(None, 200, lro=True, rid=rec["id"], verb=action)
    if action == "slotsswap":
        _swap(rec, (payload or {}).get("targetSlot") or "production")
        return _ok(None, 200, lro=True, rid=rec["id"], verb="slotsswap")
    if action in ("publishxml", "resetpublishxml"):
        token = _h(rec["id"], "publish", _now() if action == "resetpublishxml" else "", n=24)
        prof = (f'<publishData><publishProfile profileName="{rec["name"]} - Web Deploy" '
                f'publishUrl="{rec["name"]}.scm.{DOMAIN}:443" userName="${rec["name"]}" '
                f'userPWD="{token}" destinationAppUrl="https://{rec["properties"]["defaultHostName"]}" '
                f'/></publishData>')
        return _ok({"value": prof})
    return _err(404, "ResourceTypeNotSupported", f"Action '{action}' is not supported on sites.")


# ── shared: config ────────────────────────────────────────────────────────────
def _config_ops(rec, rest, method, payload):
    if not rest:
        return _err(404, "NotFound", "Missing config name.")
    kind = rest[0].lower()
    if kind not in _CONFIG_LABELS:
        return _err(404, "ResourceTypeNotSupported", f"config/{kind} is not supported.")
    tail = [t.lower() for t in rest[1:]]
    if tail not in ([], ["list"]):
        return _err(404, "ResourceTypeNotSupported", f"config/{'/'.join(rest)} is not supported.")
    # GET, or POST (real ARM: POST config/{x}/list — the short POST form is accepted too) reads.
    read = method == "GET" or method == "POST"
    if kind == "web":
        if read:
            return _ok({"properties": rec["properties"]["siteConfig"]})
        if method in ("PUT", "PATCH"):
            _absorb_site_config(rec, _props(payload))
            return _ok({"properties": rec["properties"]["siteConfig"]})
    elif kind in ("appsettings", "connectionstrings"):
        key = "_" + kind
        if read:
            return _ok({"properties": dict(rec[key])})
        if method == "PUT":
            rec[key] = dict(_props(payload))
            return _ok({"properties": dict(rec[key])})
        if method == "PATCH":
            rec[key].update(_props(payload))
            return _ok({"properties": dict(rec[key])})
    elif kind == "logs":
        if read:
            return _ok({"properties": rec["_logs"]})
        if method in ("PUT", "PATCH"):
            rec["_logs"] = _merge(rec["_logs"], _props(payload))
            return _ok({"properties": rec["_logs"]})
    elif kind == "backup":
        if read:
            return _ok({"properties": rec["_backupconfig"] or DEFAULT_BACKUP_CONFIG})
        if method in ("PUT", "PATCH"):
            rec["_backupconfig"] = _merge(rec["_backupconfig"] or DEFAULT_BACKUP_CONFIG, _props(payload))
            return _ok({"properties": rec["_backupconfig"]})
    return _err(405, "MethodNotAllowed", f"{method} not supported on config/{kind}.")


# ── shared: resource-scoped locks (stored by the generic Microsoft.Authorization/locks engine) ──
def _locks_engine():
    try:
        from core import azure_locks_core as m
    except ImportError:
        import azure_locks_core as m      # type: ignore  (Nano: flat module path)
    return m


def _migrate_locks(state, rec):
    """Site records from older builds kept locks inside the site; move them to the locks engine."""
    old = rec.pop("_locks", None) or {}
    for name, lk in old.items():
        props = lk.get("properties", lk) if isinstance(lk, dict) else {}
        _locks_engine().upsert(state, rec["id"], name, {"properties": {"level": props.get("level"), "notes": props.get("notes", "")}})


def _lock_block(state, rec, for_delete):
    """Enforce a CanNotDelete/ReadOnly lock on this site — the same semantics and error shape
    as the generic ARM engine's Service Bus namespace lock enforcement (azure_arm_core.py's
    ``_lock_block``): blocks DELETE outright, and blocks PUT/PATCH only under a ReadOnly lock.
    Scoped to this site's own id; it does not cascade from a resource-group/subscription lock
    (those scopes are an honest 'Not simulated' gap, same as the Locks blade's scope buttons)."""
    levels = {(r.get("properties") or {}).get("level")
              for r in state.values() if r.get("_lock_scope") == rec["id"].lower()}
    if not levels:
        return None
    if for_delete or "ReadOnly" in levels:
        verb = "delete" if for_delete else "write"
        return _err(409, "ScopeLocked",
                    f"The scope '{rec['id']}' cannot perform {verb} operation because the "
                    f"following scope(s) are locked: '{rec['id']}'. Please remove the lock and try again.")
    return None


def _lock_ops(state, rec, rest, method, payload):
    """Both ``sites/{n}/locks/{lock}`` (short form the Function App blade uses) and the native
    ``sites/{n}/providers/Microsoft.Authorization/locks/{lock}`` land in ONE store: the generic
    locks engine (core/azure_locks_core.py), scoped to the site id — the same records AzureArm
    serves for Microsoft.Authorization/locks on any resource."""
    lk = _locks_engine()
    if not rest:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        r = lk.list_for(state, rec["id"])
    else:
        name = rest[0]
        if method == "GET":
            r = lk.get(state, rec["id"], name)
        elif method in ("PUT", "PATCH"):
            level = _props(payload).get("level") or "CanNotDelete"
            if level not in LOCK_LEVELS:
                return _err(400, "InvalidLockLevel", f"Invalid lock level '{level}'; use one of {', '.join(LOCK_LEVELS)}.")
            r = lk.upsert(state, rec["id"], name, {"properties": {"level": level, "notes": _props(payload).get("notes", "")}})
        elif method == "DELETE":
            r = lk.remove(state, rec["id"], name)
        else:
            return _err(405, "MethodNotAllowed", f"{method} not allowed.")
    return _ok(r["body"], r["status"]) if r["status"] < 300 else _err(r["status"], r["body"]["error"]["code"], r["body"]["error"]["message"])


# ── web apps: deployment slots + swap, custom domains ─────────────────────────
def _slot_view(site, slot_name, slot):
    host = f"{site['name']}-{slot_name}.{DOMAIN}"
    return {
        "id": f"{site['id']}/slots/{slot_name}", "name": f"{site['name']}/{slot_name}",
        "type": f"{SITES_TYPE}/slots", "location": site["location"], "kind": site["kind"], "tags": {},
        "properties": {
            "serverFarmId": site["properties"]["serverFarmId"], "state": slot.get("state", "Running"),
            "enabled": True, "defaultHostName": host, "hostNames": [host],
            "siteConfig": slot.get("siteConfig") or _default_site_config("linux" in site["kind"]),
            "targetSwapSlot": None, "provisioningState": "Succeeded",
        },
    }


def _swap(rec, target):
    if target == "production":
        return
    slot = rec["_slots"].get(target)
    if slot is None:
        raise _E(404, "SlotNotFound", f"Deployment slot '{target}' was not found.")
    prod = (rec["properties"]["siteConfig"], rec["_appsettings"], rec["_connectionstrings"])
    rec["properties"]["siteConfig"] = slot.get("siteConfig") or _default_site_config("linux" in rec["kind"])
    rec["_appsettings"] = slot.get("appsettings") or {}
    rec["_connectionstrings"] = slot.get("connectionstrings") or {}
    slot["siteConfig"], slot["appsettings"], slot["connectionstrings"] = prod


def _slot_ops(rec, rest, method, payload):
    slots = rec["_slots"]
    if not rest:
        if method == "GET":
            return _ok({"value": [_slot_view(rec, n, s) for n, s in sorted(slots.items())]})
        return _err(405, "MethodNotAllowed", "Collection supports GET only.")
    name = rest[0]
    tail = rest[1:]
    if tail:
        if name not in slots:
            raise _E(404, "SlotNotFound", f"Deployment slot '{name}' was not found.")
        if len(tail) == 1 and tail[0].lower() in ("start", "stop", "restart") and method == "POST":
            slots[name]["state"] = "Stopped" if tail[0].lower() == "stop" else "Running"
            return _ok(None, 200)
        return _err(404, "ResourceTypeNotSupported", f"slots/{'/'.join(tail)} is not supported.")
    if method == "GET":
        if name not in slots:
            raise _E(404, "SlotNotFound", f"Deployment slot '{name}' was not found.")
        return _ok(_slot_view(rec, name, slots[name]))
    if method == "PUT":
        _validate_name(name, "Deployment slot")
        existed = name in slots
        slots[name] = {"state": "Running", "siteConfig": dict(rec["properties"]["siteConfig"]),
                       "appsettings": {}, "connectionstrings": {}}
        return _ok(_slot_view(rec, name, slots[name]), 200 if existed else 201, lro=True,
                   rid=f"{rec['id']}/slots/{name}", verb="put")
    if method == "DELETE":
        had = slots.pop(name, None)
        return _ok(None, 200 if had is not None else 204)
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


def _hostname_doc(rec, host):
    b = rec["_hostnamebindings"][host]
    return {"id": f"{rec['id']}/hostNameBindings/{host}", "name": host, "type": f"{SITES_TYPE}/hostNameBindings",
            "properties": {"siteName": rec["name"], "hostNameType": "Verified", "sslState": b.get("sslState", "Disabled")}}


def _hostname_ops(rec, rest, method, payload):
    binds = rec["_hostnamebindings"]
    if not rest:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        return _ok({"value": [_hostname_doc(rec, h) for h in binds]})
    host = rest[0]
    if method == "GET":
        if host not in binds:
            raise _E(404, "HostNameBindingNotFound", f"Custom domain '{host}' was not found.")
        return _ok(_hostname_doc(rec, host))
    if method == "PUT":
        existed = host in binds
        binds[host] = {"sslState": _props(payload).get("sslState", "Disabled")}
        rec["properties"]["hostNames"] = sorted(set(rec["properties"]["hostNames"]) | {host})
        return _ok(_hostname_doc(rec, host), 200 if existed else 201)
    if method == "DELETE":
        had = binds.pop(host, None)
        if had is not None:
            rec["properties"]["hostNames"] = [h for h in rec["properties"]["hostNames"] if h != host]
        return _ok(None, 200 if had is not None else 204)
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


# ── backups (modelled as snapshots: metadata + a restore acknowledgement, no real site
#    content to archive) ─────────────────────────────────────────────────────────────────
def _backup_view(rec_id, b):
    return {"id": f"{rec_id}/backups/{b['id']}", "name": b["name"],
            "properties": {"id": b["id"], "backupId": b["id"], "status": b["status"], "created": b["created"],
                           "sizeInBytes": b["sizeInBytes"], "log": "", "databases": [],
                           "storageAccountUrl": b.get("storageAccountUrl", ""), "scheduled": b.get("scheduled", False),
                           "correlationId": b["id"]}}


def _new_backup(rec, scheduled=False):
    bid = _h(rec["id"], len(rec["_backups"]), _now(), "scheduled" if scheduled else "manual", n=12)
    b = {"id": bid, "name": f"{rec['name']}_{bid}", "status": "Succeeded", "created": _now(),
         "sizeInBytes": int(_h(rec["id"], bid, "size", n=6), 16) % 50_000_000 + 1_000_000,
         "storageAccountUrl": (rec["_backupconfig"] or DEFAULT_BACKUP_CONFIG).get("storageAccountUrl", ""), "scheduled": scheduled}
    rec["_backups"][bid] = b
    return b


def _backup_ops(rec, rest, method, payload):
    backups = rec["_backups"]
    if not rest:
        if method == "GET":
            items = list(reversed(list(backups.values())))  # dict preserves insertion order: newest last in, first out
            return _ok({"value": [_backup_view(rec["id"], b) for b in items]})
        if method == "POST":
            return _ok(_backup_view(rec["id"], _new_backup(rec)), 200)
        return _err(405, "MethodNotAllowed", "Collection supports GET/POST only.")
    bid, tail = rest[0], rest[1:]
    b = backups.get(bid)
    if b is None:
        raise _E(404, "NotFound", f"Backup '{bid}' was not found.")
    if not tail:
        if method == "GET":
            return _ok(_backup_view(rec["id"], b))
        return _err(405, "MethodNotAllowed", f"{method} not allowed.")
    if len(tail) == 1 and tail[0].lower() == "restore" and method == "POST":
        return _ok({"status": "Succeeded"}, 200)
    return _err(404, "ResourceTypeNotSupported", f"backups/{'/'.join(rest)} is not supported.")


# ── function apps: functions, host keys, invoke ────────────────────────────────
_FN_NAME_RE = re.compile(r"^[A-Za-z][-A-Za-z0-9_]{0,127}$")


def _new_function(site_rid, name, payload):
    props = (payload if isinstance(payload, dict) else {}).get("properties") or {}
    cfg = props.get("config") or {"bindings": [{"authLevel": "function", "type": "httpTrigger", "direction": "in", "name": "req",
                                                "methods": ["get", "post"]}, {"type": "http", "direction": "out", "name": "$return"}]}
    code = props.get("files", {}).get("__init__.py") if isinstance(props.get("files"), dict) else None
    trigger = next((b.get("type") for b in cfg.get("bindings", []) if b.get("direction") == "in"), "httpTrigger")
    return {"id": f"{site_rid}/functions/{name}", "name": name, "type": f"{SITES_TYPE}/functions",
            "properties": {"config": cfg, "language": props.get("language", "python"), "isDisabled": _to_bool(props.get("isDisabled"), False),
                           "invoke_url_template": f"https://{{host}}/api/{name}" if trigger == "httpTrigger" else "",
                           "trigger": trigger},
            "_code": code or DEFAULT_CODE, "_entry": props.get("entryPoint", "main"), "_invocations": 0,
            "_keys": {"default": _h(site_rid, name, n=40)}}


def _fn_view(fn):
    out = _view(fn)
    out["properties"] = dict(fn["properties"], files={"__init__.py": fn["_code"]})
    return out


def _invoke_function(fn, req):
    sandbox = {"__builtins__": dict(_SAFE_BUILTINS), "json": json}
    try:
        exec(compile(fn["_code"], f"<function:{fn['name']}>", "exec"), sandbox)
        handler = sandbox.get(fn.get("_entry", "main"))
        if not callable(handler):
            raise RuntimeError(f"entry point '{fn.get('_entry', 'main')}' is not defined")
        result = handler(req)
        fn["_invocations"] = fn.get("_invocations", 0) + 1
        return {"ok": True, "status": 200, "body": result, "error": None}
    except Exception as e:
        return {"ok": False, "status": 500, "body": None, "error": f"{type(e).__name__}: {e}"}


def _put_key(bucket, owner_id, name, payload):
    existed = name in bucket
    bucket[name] = (payload or {}).get("properties", {}).get("value") or _h(owner_id, name, n=40)
    return _ok({"properties": {"name": name, "value": bucket[name]}}, 200 if existed else 201)


def _functions_ops(rec, rest, method, payload):
    fns = rec["_functions"]
    if not rest:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        return _ok({"value": [_fn_view(f) for f in fns.values()]})
    name = rest[0]
    if len(rest) == 1:
        if method == "GET":
            if name not in fns:
                raise _E(404, "NotFound", f"Function '{name}' was not found.")
            return _ok(_fn_view(fns[name]))
        if method in ("PUT", "PATCH"):
            if not _FN_NAME_RE.match(name):
                raise _E(400, "BadRequest", f"Function name '{name}' is invalid.")
            existed = fns.get(name)
            fn = _new_function(rec["id"], name, payload)
            if existed:
                fn["_invocations"], fn["_keys"] = existed["_invocations"], existed["_keys"]
            fns[name] = fn
            return _ok(_fn_view(fn), 200 if existed else 201)
        if method == "DELETE":
            had = fns.pop(name, None)
            return _ok(None, 200 if had else 204)
        return _err(405, "MethodNotAllowed", f"{method} not allowed.")
    fn = fns.get(name)
    if fn is None:
        raise _E(404, "NotFound", f"Function '{name}' was not found.")
    action = rest[1].lower()
    if action == "listkeys" and method == "POST":
        return _ok({"default": fn["_keys"].get("default", "")})
    if action == "keys" and len(rest) == 3:
        if method in ("PUT", "POST"):
            return _put_key(fn["_keys"], fn["id"], rest[2], payload)
        if method == "DELETE":
            had = fn["_keys"].pop(rest[2], None)
            return _ok(None, 200 if had else 204)
    if action == "invoke" and method == "POST":
        p = payload or {}
        req = {"method": p.get("method", "GET"), "query": p.get("query", {}), "headers": p.get("headers", {}), "body": p.get("body")}
        return _ok(_invoke_function(fn, req))
    return _err(404, "ResourceTypeNotSupported", f"Action '{action}' is not supported on functions.")


def _host_ops(rec, rest, method, payload):
    # rest: ["default", "listKeys"] | ["default", "functionKeys"|"systemKeys", name]
    if not rest or rest[0].lower() != "default":
        return _err(404, "ResourceNotFound", "Only the 'default' host is simulated.")
    host = rec["_host"]
    if len(rest) == 2 and rest[1].lower() == "listkeys" and method == "POST":
        return _ok({"masterKey": host["masterKey"], "functionKeys": dict(host["functionKeys"]), "systemKeys": dict(host["systemKeys"])})
    if len(rest) == 3 and rest[1].lower() in ("functionkeys", "systemkeys"):
        bucket = host["functionKeys"] if rest[1].lower() == "functionkeys" else host["systemKeys"]
        if method in ("PUT", "POST"):
            return _put_key(bucket, rec["id"], rest[2], payload)
        if method == "DELETE":
            had = bucket.pop(rest[2], None)
            return _ok(None, 200 if had else 204)
    return _err(404, "ResourceTypeNotSupported", f"'{'/'.join(rest)}' is not supported on host.")


# ── dispatch ─────────────────────────────────────────────────────────────────
def dispatch(state, method, sub, rg, chain, names, payload=None, query=None):
    """Handle one ``Microsoft.Web`` ARM request.

    ``chain`` = path tokens after the namespace, e.g. ``["sites", "my-app", "config", "web"]``
    ``state`` = the ARM resource map (lower-cased id → record), shared with the rest of ARM.
    """
    method = (method or "GET").upper()
    # Own copy: records keep parts of the body, and callers may reuse theirs.
    payload = json.loads(json.dumps(payload)) if isinstance(payload, dict) else {}
    chain = list(chain or [])
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
    return bool(chain) and chain[0].lower() in TYPES


def resource_types():
    return [(t, API_VERSION) for t in TYPES]
