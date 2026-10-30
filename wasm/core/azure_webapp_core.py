# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Azure Web Apps core (``Microsoft.Web``) — substrate-independent, Function Apps slice.

Speaks the ARM control-plane REST API of the ``web`` resource provider
(azure-rest-api-specs ``specification/web``, api-version 2023-12-01) for the ``sites``
resource (``kind=functionapp``) and its sub-resources, so the native
``azure-mgmt-web`` / ``armappservice`` SDKs and ``az functionapp`` / ``az rest`` work
unchanged against it.

NO fastapi / azure-sdk / socket / subprocess imports → loads under Pyodide, so the SAME
file runs offline and in Nano. It does not own a store: it mutates the ARM resource map
the dispatchers already keep (``{lower-cased resource id: record}``), which is
space-scoped and persisted by the existing seams (offline ``azure_arm_state``; Nano
``az_arm`` via core/nano_persist). Functions, app settings, connection strings and host
keys live INSIDE the site record (underscore keys, never serialised to clients).

Resource types
    Microsoft.Web/sites                (kind=functionapp) + start/stop/restart,
                                        config/appsettings, config/connectionstrings,
                                        config/web, host/default/listkeys,
                                        host/default/functionkeys|systemkeys/{name},
                                        publishxml, resetpublishxml
    Microsoft.Web/sites/functions      + listkeys, keys/{name}, invoke (console Test/Run)
    Microsoft.Web/sites/locks          a pragmatic resource-scoped lock list (the real
                                        ``Microsoft.Authorization/locks`` extension resource
                                        nests a second ``providers`` segment that the shared
                                        ARM path parser does not split; modelled as a site
                                        sub-resource instead so the console's Locks page is
                                        still backed by a real create/list/delete round-trip).
Errors use the ARM shape ``{"error":{"code","message"}}``.

Function invoke is a REAL, sandboxed Python execution (no process/filesystem/network
access) — the same restricted-exec technique as core/lambda_core.py's Invoke, so the
Code + Test "Run" panel and `az functionapp function invoke`-style calls actually run
the user's code against the request payload.

``dispatch`` returns ``{"status","headers","body","lro","rid","verb"}``; the caller adds
the Azure-AsyncOperation headers when ``lro`` is true.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone

NAMESPACE = "Microsoft.Web"
API_VERSION = "2023-12-01"
DEFAULT_LOCATION = "eastus"
TYPES = ("sites",)
RUNTIME_VERSIONS = {
    ".NET": ["8.0", "6.0"], "Java": ["21", "17", "11"], "Node.js": ["20 LTS", "18 LTS"],
    "PowerShell Core": ["7.4", "7.2"], "Python": ["3.12", "3.11", "3.10", "3.9"], "Custom Handler": ["-"],
}
LOCK_TYPES = ("ReadOnly", "CanNotDelete")

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


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _h(*parts, n=8):
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:n]


def _view(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def _ok(body=None, status=200, headers=None, lro=False, rid="", verb=""):
    return {"status": status, "headers": headers or {}, "body": body, "lro": lro, "rid": rid, "verb": verb}


def _err(status, code, message):
    return {"status": status, "headers": {}, "body": {"error": {"code": code, "message": message}},
            "lro": False, "rid": "", "verb": ""}


def _canon(sub, rg, chain, names):
    seg = ["/subscriptions/" + sub] + (["resourceGroups/" + rg] if rg else []) + ["providers", NAMESPACE]
    for i, t in enumerate(chain):
        seg.append(t)
        if i < len(names):
            seg.append(names[i])
    return "/".join(seg)


def _not_found(name, rg):
    return _E(404, "ResourceNotFound",
              f"The Resource '{NAMESPACE}/sites/{name}' under resource group '{rg}' was not found. "
              "For more details please go to https://aka.ms/ARMResourceNotFoundFix")


def _sysdata():
    n = _now()
    return {"createdBy": "vyomi@example.com", "createdByType": "User", "createdAt": n,
            "lastModifiedBy": "vyomi@example.com", "lastModifiedByType": "User", "lastModifiedAt": n}


def _to_bool(v, default=False):
    if isinstance(v, bool):
        return v
    if v is None:
        return default
    return str(v).strip().lower() in ("true", "1", "yes", "on")


def _to_int(v, default=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


# ── sites ─────────────────────────────────────────────────────────────────
def _fx_version(runtime, version):
    tag = {"Python": "PYTHON", "Node.js": "NODE", ".NET": "DOTNET-ISOLATED", "Java": "JAVA",
           "PowerShell Core": "POWERSHELL", "Custom Handler": "CUSTOM"}.get(runtime, "PYTHON")
    v = (version or "").split(" ")[0]
    return f"{tag}|{v}" if v and v != "-" else tag


def _new_site(rid, name, sub, rg, payload):
    loc = payload.get("location") or DEFAULT_LOCATION
    pay = payload.get("properties") or {}
    host = f"{name}.azurewebsites.net"
    cfg = dict(pay.get("siteConfig") or {})
    runtime = cfg.pop("_runtime", "Python")
    version = cfg.pop("_version", "3.12")
    cfg.setdefault("functionAppScaleLimit", 0)
    cfg.setdefault("minimumElasticInstanceCount", 0)
    app_settings = {s["name"]: s.get("value", "") for s in cfg.pop("appSettings", []) if s.get("name")}
    app_settings.setdefault("FUNCTIONS_EXTENSION_VERSION", "~4")
    app_settings.setdefault("FUNCTIONS_WORKER_RUNTIME", runtime.lower().replace(".net", "dotnet-isolated").replace(" core", "").replace(".js", ""))
    app_settings.setdefault("AzureWebJobsStorage", f"DefaultEndpointsProtocol=https;AccountName=vyomi{_h(name, n=10)};AccountKey=sim;")
    app_settings.setdefault("APPINSIGHTS_INSTRUMENTATIONKEY", _h(rid, "aik", n=32))
    conn_strings = {c["name"]: {"value": c.get("value", ""), "type": c.get("type", "Custom")} for c in cfg.pop("connectionStrings", []) if c.get("name")}
    scale_cfg = pay.get("functionAppConfig", {}).get("scaleAndConcurrency") or {}
    rec = {
        "id": rid, "name": name, "type": f"{NAMESPACE}/sites", "kind": "functionapp",
        "location": loc, "tags": payload.get("tags") or {}, "systemData": _sysdata(),
        "_type": f"{NAMESPACE}/sites", "_sub": sub, "_rg": rg, "_created": _now(),
        "_functions": {}, "_appsettings": app_settings, "_connstrings": conn_strings,
        "_host": {"masterKey": _h(rid, "master", n=40), "functionKeys": {"default": _h(rid, "default", n=40)}, "systemKeys": {}},
        "_locks": {},
        "properties": {
            "state": "Running", "enabled": True, "hostNames": [host], "defaultHostName": host,
            "reserved": _to_bool(pay.get("reserved"), False), "isXenon": False, "hyperV": False,
            "usageState": "Normal", "availabilityState": "Normal", "httpsOnly": _to_bool(pay.get("httpsOnly"), True),
            "serverFarmId": pay.get("serverFarmId") or f"/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Web/serverfarms/FLEX-{rg}",
            "sku": "FlexConsumption" if pay.get("functionAppConfig") else "Dynamic",
            "functionAppConfig": pay.get("functionAppConfig") or {"runtime": {"name": runtime.lower(), "version": version},
                                                                   "scaleAndConcurrency": {"instanceMemoryMB": scale_cfg.get("instanceMemoryMB", 2048),
                                                                                           "maximumInstanceCount": scale_cfg.get("maximumInstanceCount", 100),
                                                                                           "triggers": scale_cfg.get("triggers") or {"http": {"perInstanceConcurrency": 16}}}},
            "siteConfig": dict(cfg, linuxFxVersion=_fx_version(runtime, version) if _to_bool(pay.get("reserved"), True) else "",
                               windowsFxVersion="" if _to_bool(pay.get("reserved"), True) else _fx_version(runtime, version)),
            "outboundIpAddresses": "52.%d.%d.%d" % (int(_h(rid, n=6)[0:2], 16) % 200 + 1, int(_h(rid, n=6)[2:4], 16), int(_h(rid, n=6)[4:6], 16) % 250 + 1),
            "defaultHostNameSslState": {"name": host, "sslState": "Disabled", "hostType": "Standard"},
        },
    }
    return rec


def _site_view(rec):
    out = _view(rec)
    out["properties"] = dict(out["properties"])
    return out


def _put_site(state, sub, rg, rid, name, payload, method):
    existed = state.get(rid.lower())
    if method == "PATCH":
        if not existed:
            raise _not_found(name, rg)
        if isinstance(payload.get("tags"), dict):
            existed["tags"] = payload["tags"]
        pr = payload.get("properties") or {}
        existed["properties"].update({k: v for k, v in pr.items() if k not in ("siteConfig", "functionAppConfig")})
        if "siteConfig" in pr:
            existed["properties"]["siteConfig"].update(pr["siteConfig"])
        if "functionAppConfig" in pr:
            existed["properties"]["functionAppConfig"] = {**existed["properties"].get("functionAppConfig", {}), **pr["functionAppConfig"]}
        return existed
    if not re.fullmatch(r"[A-Za-z0-9][-A-Za-z0-9]{0,58}[A-Za-z0-9]", name) and not re.fullmatch(r"[A-Za-z0-9]", name):
        raise _E(400, "BadRequest", f"Site name '{name}' is invalid. Site names must consist of alphanumeric characters and hyphens only, "
                  "cannot start or end in a hyphen and must be <= 60 characters.")
    if existed is None:
        rec = _new_site(rid, name, sub, rg, payload)
        state[rid.lower()] = rec
    else:
        rec = existed
        rec["location"] = payload.get("location") or rec["location"]
        if isinstance(payload.get("tags"), dict):
            rec["tags"] = payload["tags"]
        pr = payload.get("properties") or {}
        if "siteConfig" in pr:
            rec["properties"]["siteConfig"].update(pr["siteConfig"])
        if "functionAppConfig" in pr:
            rec["properties"]["functionAppConfig"] = {**rec["properties"].get("functionAppConfig", {}), **pr["functionAppConfig"]}
    return rec


# ── functions ────────────────────────────────────────────────────────────────
_FN_NAME_RE = re.compile(r"^[A-Za-z][-A-Za-z0-9_]{0,127}$")


def _new_function(site_rid, name, payload):
    pay = payload if isinstance(payload, dict) else {}
    props = pay.get("properties") or {}
    cfg = props.get("config") or {"bindings": [{"authLevel": "function", "type": "httpTrigger", "direction": "in", "name": "req",
                                                "methods": ["get", "post"]}, {"type": "http", "direction": "out", "name": "$return"}]}
    code = props.get("files", {}).get("__init__.py") if isinstance(props.get("files"), dict) else None
    trigger = next((b.get("type") for b in cfg.get("bindings", []) if b.get("direction") == "in"), "httpTrigger")
    return {"id": f"{site_rid}/functions/{name}", "name": name, "type": f"{NAMESPACE}/sites/functions",
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


def _functions_ops(state, rec, rest, method, payload):
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
        kname = rest[2]
        if method in ("PUT", "POST"):
            fn["_keys"][kname] = (payload or {}).get("properties", {}).get("value") or _h(fn["id"], kname, n=40)
            return _ok({"properties": {"name": kname, "value": fn["_keys"][kname]}})
        if method == "DELETE":
            had = fn["_keys"].pop(kname, None)
            return _ok(None, 200 if had else 204)
    if action == "invoke" and method == "POST":
        req = {"method": (payload or {}).get("method", "GET"), "query": (payload or {}).get("query", {}),
               "headers": (payload or {}).get("headers", {}), "body": (payload or {}).get("body")}
        return _ok(_invoke_function(fn, req))
    return _err(404, "ResourceTypeNotSupported", f"Action '{action}' is not supported on functions.")


# ── config / host keys / locks ──────────────────────────────────────────────
def _config_ops(rec, rest, method, payload):
    kind = rest[0].lower()
    if kind == "appsettings":
        store = rec["_appsettings"]
        if method in ("GET", "POST"):
            return _ok({"properties": dict(store)})
        if method == "PUT":
            rec["_appsettings"] = dict((payload or {}).get("properties") or {})
            return _ok({"properties": dict(rec["_appsettings"])})
    elif kind == "connectionstrings":
        store = rec["_connstrings"]
        if method in ("GET", "POST"):
            return _ok({"properties": dict(store)})
        if method == "PUT":
            rec["_connstrings"] = dict((payload or {}).get("properties") or {})
            return _ok({"properties": dict(rec["_connstrings"])})
    elif kind == "web":
        if method == "GET":
            return _ok({"properties": rec["properties"]["siteConfig"]})
        if method in ("PUT", "PATCH"):
            rec["properties"]["siteConfig"].update((payload or {}).get("properties") or {})
            return _ok({"properties": rec["properties"]["siteConfig"]})
    return _err(405, "MethodNotAllowed", f"{method} not supported on config/{kind}.")


def _host_ops(rec, rest, method, payload):
    # rest: ["default", "listKeys"] | ["default", "functionKeys"|"systemKeys", name]
    if rest[0].lower() != "default":
        return _err(404, "ResourceNotFound", "Only the 'default' host is simulated.")
    host = rec["_host"]
    if len(rest) == 2 and rest[1].lower() == "listkeys" and method == "POST":
        return _ok({"masterKey": host["masterKey"], "functionKeys": dict(host["functionKeys"]), "systemKeys": dict(host["systemKeys"])})
    if len(rest) == 3 and rest[1].lower() in ("functionkeys", "systemkeys"):
        bucket = host["functionKeys"] if rest[1].lower() == "functionkeys" else host["systemKeys"]
        name = rest[2]
        if method in ("PUT", "POST"):
            bucket[name] = (payload or {}).get("properties", {}).get("value") or _h(rec["id"], name, n=40)
            return _ok({"properties": {"name": name, "value": bucket[name]}})
        if method == "DELETE":
            had = bucket.pop(name, None)
            return _ok(None, 200 if had else 204)
    return _err(404, "ResourceTypeNotSupported", f"'{'/'.join(rest)}' is not supported on host.")


def _locks_ops(rec, rest, method, payload):
    locks = rec["_locks"]
    if not rest:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        return _ok({"value": list(locks.values())})
    name = rest[0]
    if method in ("PUT",):
        pr = (payload or {}).get("properties") or {}
        lt = pr.get("level", "ReadOnly")
        if lt not in LOCK_TYPES:
            raise _E(400, "InvalidLockType", f"Invalid lock level '{lt}'; use one of {', '.join(LOCK_TYPES)}.")
        locks[name] = {"id": f"{rec['id']}/locks/{name}", "name": name, "type": f"{NAMESPACE}/sites/locks",
                       "properties": {"level": lt, "notes": pr.get("notes", "")}}
        return _ok(locks[name])
    if method == "GET":
        if name not in locks:
            raise _E(404, "ResourceNotFound", f"Lock '{name}' was not found.")
        return _ok(locks[name])
    if method == "DELETE":
        had = locks.pop(name, None)
        return _ok(None, 200 if had else 204)
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


def _site_action(rec, action, method):
    if action in ("start", "stop", "restart") and method == "POST":
        rec["properties"]["state"] = "Stopped" if action == "stop" else "Running"
        return _ok(None, 200, lro=True, rid=rec["id"], verb=action)
    if action in ("publishxml", "resetpublishxml") and method == "POST":
        token = _h(rec["id"], "publish", _now() if action == "resetpublishxml" else "", n=24)
        prof = (f'<publishData><publishProfile profileName="{rec["name"]} - Web Deploy" '
               f'publishUrl="{rec["name"]}.scm.azurewebsites.net:443" userName="${rec["name"]}" '
               f'userPWD="{token}" destinationAppUrl="https://{rec["properties"]["defaultHostName"]}" '
               f'/></publishData>')
        return _ok({"value": prof})
    return _err(404, "ResourceTypeNotSupported", f"Action '{action}' is not supported on sites.")


# ── dispatch ────────────────────────────────────────────────────────────────
def _list(state, sub, rg):
    items = []
    for rec in state.values():
        if str(rec.get("_type", "")).lower() != f"{NAMESPACE}/sites".lower() or rec.get("_sub") != sub:
            continue
        if rg is not None and (rec.get("_rg") or "").lower() != rg.lower():
            continue
        items.append(_site_view(rec))
    return _ok({"value": items})


def dispatch(state, method, sub, rg, chain, names, payload=None, query=None):
    """Handle one ``Microsoft.Web/sites`` ARM request.

    ``chain``  = path tokens after the namespace, e.g. ``["sites", "fn1", "functions", "f1"]``
    ``state``  = the ARM resource map (lower-cased id → record).
    """
    method = (method or "GET").upper()
    payload = payload if isinstance(payload, dict) else {}
    try:
        return _dispatch(state, method, sub, rg, list(chain), payload)
    except _E as e:
        return _err(e.status, e.code, e.message)


def _dispatch(state, method, sub, rg, chain, payload):
    if not chain or chain[0].lower() not in TYPES:
        return _err(404, "ResourceTypeNotSupported", f"The resource type '{NAMESPACE}/{chain[0] if chain else ''}' is not supported.")
    if len(chain) == 1:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        return _list(state, sub, rg)
    name = chain[1]
    rid = _canon(sub, rg, ["sites"], [name])
    rec = state.get(rid.lower())
    rest = chain[2:]
    if rest:
        if rec is None:
            raise _not_found(name, rg)
        r0 = rest[0].lower()
        if r0 == "functions":
            return _functions_ops(state, rec, rest[1:], method, payload)
        if r0 == "config":
            return _config_ops(rec, rest[1:], method, payload)
        if r0 == "host":
            return _host_ops(rec, rest[1:], method, payload)
        if r0 == "locks":
            return _locks_ops(rec, rest[1:], method, payload)
        return _site_action(rec, r0, method)
    if method == "GET":
        if rec is None:
            raise _not_found(name, rg)
        return _ok(_site_view(rec))
    if method in ("PUT", "PATCH"):
        if rg is None:
            return _err(400, "InvalidResourceId", "Web sites must be created in a resource group.")
        existed = rec is not None
        rec = _put_site(state, sub, rg, rid, name, payload, method)
        return _ok(_site_view(rec), 200 if existed else 201, lro=True, rid=rid, verb=method.lower())
    if method == "DELETE":
        state.pop(rid.lower(), None)
        return _ok(None, 200 if rec is not None else 204, rid=rid, verb="delete")
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


def resource_types():
    return [("sites", API_VERSION)]
