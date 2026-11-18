"""Azure Functions host (offline appliance / Mesh): what sits between `zipdeploy` / the HTTPS front door and the sandboxed worker.

* zip deploy -> the app's REAL functions: v1 (`<fn>/function.json` + `__init__.py`) and v2 (decorators in `function_app.py`, discovered by
  importing it in the sandbox with the real `azure.functions`). They become the ARM `Microsoft.Web/sites/functions` children, so
  `WebSiteManagementClient.web_apps.list_functions / get_function / list_function_keys` see them (state lives in the site record:
  `_functions`, `_host`, `_zipfiles`).
* HTTP front door `https://<app>.azurewebsites.net/api/<route>` (also `/azure-data/functions/<app>/api/<route>`): route templates, methods, and
  function-key authentication (`x-functions-key` header or `?code=`; authLevel anonymous / function / admin, master key opens everything).
* Admin API `/admin/host/keys`, `/admin/host/systemkeys`, `/admin/functions/<fn>/keys`, `/admin/host/status`, `/admin/functions`
  and `POST /admin/functions/<fn>` (manual invocation of any trigger, the real way to run a timer function).
* The trigger invocation seam used by Event Grid delivery and (lane az-ref-messaging) Service Bus delivery: `invoke_trigger()` / `functions_with_trigger()`.

Execution is `core/gcp_function_runtime.azure_invoke` (subprocess per call, scrubbed env, egress limited to loopback + the simulator).
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import re
import secrets
import time
import zipfile

from fastapi import Request
from fastapi.responses import JSONResponse, Response

from core import gcp_function_runtime as gfr

MAX_ZIP = 64 * 1024 * 1024
HTTP_BINDINGS = ("httptrigger",)
SELF = {"base": ""}          # where the simulator is reachable from the worker (last base URL seen on a data-plane request)

_SKIP = ("__pycache__/", ".git/", ".venv/", "node_modules/")


# ── helpers ───────────────────────────────────────────────────────────────────────────────────────────────
def _web():
    from core import azure_webapp_core as w
    return w


def _ext():
    from core import azure_arm_ext_core as e
    return e


def note_base(request) -> None:
    try:
        SELF["base"] = str(request.base_url).rstrip("/")
    except Exception:
        pass


def _enc(data: bytes):
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return {"b64": base64.b64encode(data).decode()}


def _dec(v):
    return base64.b64decode(v["b64"]) if isinstance(v, dict) else v


def files_of(rec) -> dict:
    return {k: _dec(v) for k, v in (rec.get("_zipfiles") or {}).items()}


def _low_binding(b: dict) -> dict:
    d = dict(b)
    d["direction"] = str(d.get("direction", "in")).lower()
    if "authLevel" in d:
        d["authLevel"] = str(d["authLevel"]).lower()
    if "methods" in d:
        d["methods"] = [str(m).lower() for m in d["methods"]]
    return d


def trigger_of(fn):
    for b in (fn.get("properties") or {}).get("config", {}).get("bindings", []):
        if str(b.get("direction", "in")).lower() == "in" and str(b.get("type", "")).lower().endswith("trigger"):
            return b
    return None


def is_http(fn) -> bool:
    t = trigger_of(fn)
    return bool(t) and str(t.get("type", "")).lower() in HTTP_BINDINGS


def _fn_record(rec, name, cfg, *, code, entry, v2, dirname, script, prior):
    bindings = [_low_binding(b) for b in cfg.get("bindings", [])]
    cfg = dict(cfg, bindings=bindings)
    cfg.setdefault("scriptFile", script)
    trig = next((b for b in bindings if b["direction"] == "in" and str(b.get("type", "")).lower().endswith("trigger")), None)
    app = rec["name"]
    base = f"https://{app}.scm.azurewebsites.net"
    folder = (dirname + "/") if dirname else ""
    props = {"name": name, "function_app_id": rec["id"], "script_root_path_href": f"{base}/api/vfs/site/wwwroot/{folder}",
             "script_href": f"{base}/api/vfs/site/wwwroot/{folder}{script}", "config_href": f"{base}/api/vfs/site/wwwroot/{folder}function.json",
             "href": f"https://{app}.azurewebsites.net/admin/functions/{name}", "config": cfg, "language": "python",
             "isDisabled": bool(cfg.get("disabled", False)), "test_data_href": None, "test_data": ""}
    if trig and str(trig.get("type", "")).lower() in HTTP_BINDINGS:
        props["invoke_url_template"] = f"https://{app}.azurewebsites.net/api/{trig.get('route') or name}"
    else:
        props["invoke_url_template"] = None
    keys = (prior or {}).get("_keys") or {"default": _web()._h(rec["id"], name, "fnkey", n=40) + "=="}
    return {"id": f"{rec['id']}/functions/{name}", "name": name, "type": "Microsoft.Web/sites/functions", "properties": props,
            "_code": code, "_entry": entry, "_invocations": (prior or {}).get("_invocations", 0), "_keys": keys,
            "_zip": True, "_v2": v2, "_dir": dirname, "_script": script}


# ── zip deploy ────────────────────────────────────────────────────────────────────────────────────────────
def _read_zip(data: bytes) -> dict:
    z = zipfile.ZipFile(io.BytesIO(data))
    total, out = 0, {}
    for info in z.infolist():
        n = info.filename.replace("\\", "/")
        if info.is_dir() or n.startswith("/") or ".." in n.split("/") or any(s in n + "/" for s in _SKIP) or n.endswith(".pyc"):
            continue
        total += info.file_size
        if total > MAX_ZIP * 2:
            raise ValueError("the package expands past the size limit")
        out[n] = z.read(info)
    return out


def _env(rec, base: str = "") -> dict:
    return gfr.azure_function_env(app=rec["name"], resource_group=rec.get("_rg") or "", region=rec.get("location") or "eastus",
                                  subscription=rec.get("_sub") or "", runtime="python", endpoint=gfr.self_url(base or SELF["base"]),
                                  settings=rec.get("_appsettings"), conn_strings=rec.get("_connectionstrings"))


def deploy(rec, data: bytes, base: str = "") -> tuple:
    """Unpack + discover + register. -> (status, message). 200 'Deployment successful.' even when the host can load zero functions
    (like the real service: the host reports it in its log), 400 for a bad zip or an unsatisfiable requirements.txt."""
    web = _web()
    web._ensure(rec)
    try:
        raw = _read_zip(data)
    except zipfile.BadZipFile:
        return 400, "Body is not a zip archive"
    except ValueError as e:
        return 400, str(e)
    reqs = raw.get("requirements.txt")
    if reqs:
        missing = gfr.check_requirements(reqs.decode("utf-8", "replace"))
        if missing:
            return 400, ("Build failed: requirements.txt cannot be satisfied offline (no internet to pip install): " + "; ".join(missing)
                         + ". Available libraries: " + ", ".join("%s==%s" % kv for kv in sorted(gfr.azure_libraries().items())))
    rec["_zipfiles"] = {k: _enc(v) for k, v in raw.items()}
    ext = _ext()
    prior = {n: f for n, f in rec["_functions"].items() if f.get("_zip")}
    for n in list(prior):
        rec["_functions"].pop(n, None)
    found = []
    # v1: <dir>/function.json
    for path, b in raw.items():
        if path.endswith("/function.json") and path.count("/") == 1:
            d = path.split("/")[0]
            try:
                cfg = json.loads(b.decode("utf-8"))
            except ValueError:
                ext.site_log(rec, f"Function '{d}': function.json is not valid JSON.", "Error")
                continue
            script = cfg.get("scriptFile") or "__init__.py"
            code = raw.get(f"{d}/{script}", b"").decode("utf-8", "replace")
            found.append(_fn_record(rec, d, cfg, code=code, entry=cfg.get("entryPoint") or "main", v2=False, dirname=d, script=script, prior=prior.get(d)))
    # v2: decorators in function_app.py (imported in the sandbox with the real azure.functions)
    if "function_app.py" in raw:
        d = gfr.azure_discover(dict(raw), "function_app.py", _env(rec, base))
        if not d["ok"]:
            ext.site_log(rec, "Host started but function_app.py could not be indexed: " + str(d["error"])[-600:], "Error")
        for f in d["functions"]:
            found.append(_fn_record(rec, f["name"], {"bindings": f["bindings"], "scriptFile": f["scriptFile"]}, code=raw["function_app.py"].decode("utf-8", "replace"),
                                    entry=f["name"], v2=True, dirname="", script="function_app.py", prior=prior.get(f["name"])))
    # legacy layout (no function.json): <dir>/__init__.py with main(), served as an anonymous HTTP function named like the folder
    if not found:
        for path, b in raw.items():
            if path.endswith("/__init__.py") and path.count("/") == 1 and b"def main" in b:
                d = path.split("/")[0]
                cfg = {"bindings": [{"type": "httpTrigger", "direction": "in", "name": "req", "authLevel": "anonymous", "methods": ["get", "post"]},
                                    {"type": "http", "direction": "out", "name": "$return"}], "scriptFile": "__init__.py"}
                found.append(_fn_record(rec, d, cfg, code=b.decode("utf-8", "replace"), entry="main", v2=False, dirname=d, script="__init__.py", prior=prior.get(d)))
    for f in found:
        rec["_functions"][f["name"]] = f
    rec["_routeprefix"] = "api"
    if raw.get("host.json"):
        try:
            rec["_routeprefix"] = (json.loads(raw["host.json"].decode("utf-8")).get("extensions", {}).get("http", {}) or {}).get("routePrefix", "api")
        except ValueError:
            pass
    ext.site_log(rec, f"Deployment successful: {len(found)} function(s) loaded: " + ", ".join(sorted(f['name'] for f in found)))
    for f in found:
        t = trigger_of(f)
        ext.site_log(rec, f"Found the following functions: Host.Functions.{f['name']} ({(t or {}).get('type', 'no trigger')})")
    ext.mark_changed(rec)
    return 200, "Deployment successful."


# ── keys + auth ───────────────────────────────────────────────────────────────────────────────────────────
def key_ok(rec, fn, key: str, level: str) -> bool:
    if not key:
        return False
    host = rec["_host"]
    if key == host["masterKey"]:
        return True
    if level == "admin":
        return False
    if fn and key in (fn.get("_keys") or {}).values():
        return True
    return key in host["functionKeys"].values()


def _presented_key(request) -> str:
    return request.headers.get("x-functions-key") or request.query_params.get("code") or ""


# ── HTTP front door ───────────────────────────────────────────────────────────────────────────────────────
def _route_regex(tpl: str):
    pat = ""
    for part in re.split(r"(\{[^}]+\})", tpl):
        m = re.fullmatch(r"\{([A-Za-z_]\w*)(?::[^}?]+)?(\?)?\}", part or "")
        pat += (("(?P<%s>[^/]+)" % m.group(1)) + ("?" if m.group(2) else "")) if m else re.escape(part)
    return re.compile("^" + pat + "$", re.I)


def resolve(rec, route: str):
    """-> (function record, route params) for an http route (no prefix)."""
    route = route.strip("/")
    best = None
    for fn in rec["_functions"].values():
        t = trigger_of(fn)
        if not (fn.get("_zip") and t and str(t.get("type", "")).lower() in HTTP_BINDINGS):
            continue
        tpl = (t.get("route") if t.get("route") is not None else fn["name"]).strip("/")
        m = _route_regex(tpl).match(route)
        if m:
            score = len(tpl) - tpl.count("{") * 8
            if best is None or score > best[0]:
                best = (score, fn, {k: v for k, v in m.groupdict().items() if v is not None})
    return (best[1], best[2]) if best else (None, {})


def _strip_prefix(rec, rest: str) -> str:
    rest = rest.strip("/")
    prefix = rec.get("_routeprefix", "api")
    if prefix and (rest == prefix or rest.startswith(prefix + "/")):
        return rest[len(prefix):].lstrip("/")
    if rest == "api" or rest.startswith("api/"):          # the simulator path form always accepted /api/
        return rest[3:].lstrip("/")
    return rest


def has_deployed(rec) -> bool:
    return any(f.get("_zip") for f in (rec.get("_functions") or {}).values())


def _identity(rec) -> dict:
    web = _web()
    ident = rec.get("identity") or {}
    return {"header": secrets.token_hex(16), "principal": ident.get("principalId") or web._guid(rec["id"], "principal"),
            "tenant": ident.get("tenantId") or web._guid(rec.get("_sub", ""), "tenant"), "client_id": web._guid(rec["id"], "client"), "resource_id": rec["id"]}


def _fn_spec(fn) -> dict:
    return {"name": fn["name"], "v2": fn.get("_v2", False), "dir": fn.get("_dir", ""), "scriptFile": fn.get("_script") or "__init__.py",
            "entryPoint": fn.get("_entry") or "main", "bindings": [_low_binding(b) for b in fn["properties"]["config"].get("bindings", [])]}


def _timeout(rec) -> int:
    try:
        h = json.loads(_dec((rec.get("_zipfiles") or {}).get("host.json", "{}")) or "{}").get("functionTimeout")
        if h:
            hh, mm, ss = (int(x) for x in str(h).split(":")[:3])
            return max(5, min(hh * 3600 + mm * 60 + ss, 230))
    except Exception:
        pass
    return 60


def execute(rec, fn, payload, base: str = "") -> dict:
    """Run one function of a deployed app in the sandbox; log to the site's log stream + invocation log. Blocking."""
    web = _web()
    ext = _ext()
    t0 = time.perf_counter()
    out = gfr.azure_invoke(files_of(rec), _fn_spec(fn), payload, _env(rec, base), _identity(rec), timeout=_timeout(rec))
    ms = round((time.perf_counter() - t0) * 1000, 2)
    fn["_invocations"] = fn.get("_invocations", 0) + 1
    name = fn["name"]
    ext.site_log(rec, f"Executing 'Functions.{name}' (Reason='{'This function was programmatically called via the host APIs.' if out.get('kind') != 'http' else 'New HTTP request'}')")
    for line in (out.get("logs") or "").splitlines() + (out.get("stderr") or "").splitlines():
        if line.strip():
            ext.site_log(rec, f"[{name}] {line[:400]}", "Error" if line.startswith(("ERROR", "CRITICAL", "Traceback")) else "Information")
    ok = out["ok"] and (out.get("status", 200) < 500)
    ext.site_log(rec, f"Executed 'Functions.{name}' ({'Succeeded' if ok else 'Failed'}, Duration={int(ms)}ms)", "Information" if ok else "Error")
    log = rec.setdefault("_invocationlog", [])
    log.append({"timestamp": web._now(), "function": name, "status": out.get("status", 500), "ok": ok, "durationMs": ms, "error": out.get("error")})
    del log[:-getattr(web, "INVOCATIONLOG_CAP", 500)]
    out["durationMs"] = ms
    return out


async def serve_http(rec, app_name: str, rest: str, request: Request):
    """The HTTP front door for a zip-deployed app, or None when the app has no deployed functions (legacy single-code path)."""
    if not has_deployed(rec):
        return None
    note_base(request)
    if (rec.get("properties") or {}).get("state") == "Stopped":
        return Response(content="Error 403 - This web app is stopped.", status_code=403, media_type="text/html")
    route = _strip_prefix(rec, rest)
    fn, rparams = resolve(rec, route)
    if fn is None:
        return Response(status_code=404)
    t = trigger_of(fn)
    methods = [m.lower() for m in (t.get("methods") or [])]
    if methods and request.method.lower() not in methods and request.method != "OPTIONS":
        return Response(status_code=404)
    if fn["properties"].get("isDisabled") or str((rec.get("_appsettings") or {}).get(f"AzureWebJobs.{fn['name']}.Disabled", "")).lower() == "true":
        return Response(status_code=404)
    level = str(t.get("authLevel", "function")).lower()
    if level != "anonymous" and not key_ok(rec, fn, _presented_key(request), level):
        return Response(status_code=401)
    body = await request.body()
    url = str(request.url)
    host = request.headers.get("host", "")
    if ".azurewebsites." in host:          # the app's own hostname: the function sees the URL a real host would
        pre = rec.get("_routeprefix", "api")
        url = f"{request.url.scheme}://{host}/{(pre + '/') if pre else ''}{route}" + (("?" + request.url.query) if request.url.query else "")
    payload = {"method": request.method, "url": url, "query": request.url.query, "headers": {k: v for k, v in request.headers.items()},
               "body_b64": base64.b64encode(body).decode(), "route_params": rparams}
    loop = asyncio.get_running_loop()
    out = await loop.run_in_executor(None, lambda: execute(rec, fn, payload, str(request.base_url)))
    if not out["ok"]:
        return Response(content=("Exception while executing function: Functions.%s\n%s" % (fn["name"], out.get("error", ""))).encode(), status_code=500,
                        media_type="text/plain")
    hdrs = {k: str(v) for k, v in (out.get("headers") or {}).items() if k.lower() not in ("content-length", "content-type")}
    ct = next((v for k, v in (out.get("headers") or {}).items() if k.lower() == "content-type"), None)
    return Response(content=out.get("body", b""), status_code=int(out.get("status", 200)), headers=hdrs, media_type=ct)


# ── trigger invocation seam (Event Grid / Service Bus delivery, admin API) ────────────────────────────────
def functions_with_trigger(rec, trigger_type: str, **match) -> list:
    """Deployed functions whose trigger is `trigger_type` (e.g. 'serviceBusTrigger', 'eventGridTrigger', 'blobTrigger') and whose binding
    contains every key/value in `match` (case-insensitive), e.g. functions_with_trigger(rec, 'serviceBusTrigger', topicName='work-order-approval',
    subscriptionName='approver-inbox') or queueName='approver-inbox'."""
    out = []
    for fn in rec.get("_functions", {}).values():
        t = trigger_of(fn)
        if fn.get("_zip") and t and str(t.get("type", "")).lower() == trigger_type.lower() and all(
                str(t.get(k, "")).lower() == str(v).lower() for k, v in match.items()):
            out.append(fn)
    return out


def invoke_trigger(rec, fn, payload, base: str = "") -> dict:
    """THE seam: run a deployed function with a trigger event. `payload` is, per trigger type:
    eventGridTrigger -> one Event Grid event dict (id, topic, subject, eventType, eventTime, dataVersion, data);
    serviceBusTrigger -> {"body": str|dict, "content_type", "correlation_id", "message_id"};  queueTrigger -> {"id", "body"};
    blobTrigger -> {"name", "uri", "length"};  timerTrigger -> {"past_due": bool};  httpTrigger -> the request dict
    {method, url, query, headers, body_b64, route_params}. Blocking. Returns {ok, kind, status, result, logs, error}."""
    return execute(rec, fn, payload, base)


def invoke_by_name(rec, name: str, method: str, payload, base: str = "") -> dict:
    """Event Grid `AzureFunction` / WebHook-to-function destination: `payload` is the delivered batch (list) or one event."""
    fn = next((f for f in rec["_functions"].values() if f["name"].lower() == name.lower() and f.get("_zip")), None)
    if fn is None:
        return {"ok": False, "error": f"function '{name}' is not deployed"}
    if is_http(fn):
        body = json.dumps(payload).encode()
        return execute(rec, fn, {"method": method or "POST", "url": f"https://{rec['name']}.azurewebsites.net/api/{name}", "query": "",
                                 "headers": {"content-type": "application/json"}, "body_b64": base64.b64encode(body).decode(), "route_params": {}}, base)
    events = payload if isinstance(payload, list) else [payload]
    outs = [execute(rec, fn, e, base) for e in events]
    return {"ok": all(o["ok"] for o in outs), "results": outs, "kind": "event", "status": 200}


# ── admin API ─────────────────────────────────────────────────────────────────────────────────────────────
def _keys_doc(bucket: dict) -> dict:
    return {"keys": [{"name": k, "value": v} for k, v in bucket.items()], "links": []}


async def serve_admin(rec, app_name: str, rest: str, request: Request):
    note_base(request)
    web = _web()
    web._ensure(rec)
    if not key_ok(rec, None, _presented_key(request), "admin"):
        return Response(status_code=401)
    parts = [p for p in rest.strip("/").split("/") if p]
    host = rec["_host"]
    m = request.method
    try:
        body = await request.json() if m in ("POST", "PUT") else {}
    except Exception:
        body = {}
    if parts[:2] in (["host", "status"], ["host", "ping"]):
        return JSONResponse({"id": rec["name"].lower(), "state": "Running", "version": "4.34.2.0", "versionDetails": "4.34.2.0",
                             "platformVersion": "99.0.0.0", "instanceId": "vyomi-" + rec["name"], "computerName": "vyomi", "processUptime": 100000,
                             "functionAppContentEditingState": "Unknown", "extensionBundle": {"id": "Microsoft.Azure.Functions.ExtensionBundle", "version": "4.20.0"}})
    if parts[:2] in (["host", "keys"], ["host", "systemkeys"]):
        bucket = host["functionKeys"] if parts[1] == "keys" else host["systemKeys"]
        if len(parts) == 2 and m == "GET":
            doc = _keys_doc(bucket)
            if parts[1] == "keys":
                doc["keys"].insert(0, {"name": "_master", "value": host["masterKey"]})
            return JSONResponse(doc)
        if len(parts) == 3:
            name = parts[2]
            if m in ("PUT", "POST"):
                bucket[name] = (body or {}).get("value") or web._h(rec["id"], name, secrets.token_hex(4), n=40) + "=="
                return JSONResponse({"name": name, "value": bucket[name]}, status_code=201 if m == "POST" else 200)
            if m == "GET":
                return JSONResponse({"name": name, "value": bucket[name]}) if name in bucket else Response(status_code=404)
            if m == "DELETE":
                return Response(status_code=204 if bucket.pop(name, None) is not None else 404)
    if parts[:1] == ["functions"]:
        if len(parts) == 1 and m == "GET":
            return JSONResponse([{"name": f["name"], "script_href": f["properties"]["script_href"], "config": f["properties"]["config"], "href": f["properties"]["href"],
                                  "invoke_url_template": f["properties"]["invoke_url_template"], "language": "python", "isDisabled": f["properties"]["isDisabled"]}
                                 for f in rec["_functions"].values() if f.get("_zip")])
        fn = next((f for f in rec["_functions"].values() if f["name"].lower() == (parts[1] if len(parts) > 1 else "").lower()), None)
        if fn is None:
            return Response(status_code=404)
        if len(parts) == 2 and m == "GET":
            return JSONResponse({"name": fn["name"], "config": fn["properties"]["config"], "invoke_url_template": fn["properties"]["invoke_url_template"],
                                 "isDisabled": fn["properties"]["isDisabled"], "language": "python"})
        if len(parts) == 2 and m == "POST":      # manual invoke: {"input": ...}; 202 like the real admin endpoint
            inp = (body or {}).get("input")
            try:
                inp = json.loads(inp) if isinstance(inp, str) else inp
            except ValueError:
                pass
            payload = inp if isinstance(inp, dict) else {"body": inp}
            loop = asyncio.get_running_loop()
            out = await loop.run_in_executor(None, lambda: invoke_trigger(rec, fn, payload, str(request.base_url)))
            return Response(status_code=202 if out["ok"] else 500)
        if parts[2:3] == ["keys"]:
            bucket = fn["_keys"]
            if len(parts) == 3 and m == "GET":
                return JSONResponse(_keys_doc(bucket))
            if len(parts) == 4:
                name = parts[3]
                if m in ("PUT", "POST"):
                    bucket[name] = (body or {}).get("value") or web._h(fn["id"], name, secrets.token_hex(4), n=40) + "=="
                    return JSONResponse({"name": name, "value": bucket[name]}, status_code=201 if m == "POST" else 200)
                if m == "GET":
                    return JSONResponse({"name": name, "value": bucket[name]}) if name in bucket else Response(status_code=404)
                if m == "DELETE":
                    return Response(status_code=204 if bucket.pop(name, None) is not None else 404)
    return Response(status_code=404)
