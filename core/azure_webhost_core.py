"""App Service front door + app host (Microsoft.Web/sites data plane), substrate-free (Nano + offline).

``serve(state, site, method, path, query, headers, body, now=None)`` answers one HTTP request to ``https://{site}.azurewebsites.net``
the way the App Service front end + worker does, over the site's REAL stored configuration and content, and APPLIES the site
configuration panels while doing it:

* state                      -- a Stopped app answers 403 "Web App - Stopped" (the real site-disabled page)
* publicNetworkAccess        -- Disabled -> 403
* ipSecurityRestrictions     -- priority-ordered Allow/Deny (core/azure_webnet_core.evaluate_access) -> 403 Ip Forbidden
* httpsOnly                  -- plain HTTP (``x-forwarded-proto: http``) -> 301 to https
* minTlsVersion              -- a caller that declares ``x-vyomi-tls-version`` below the minimum is refused (421), as the TLS
                                 handshake would fail; clientCertEnabled + clientCertMode=Required without ``x-arr-clientcert`` -> 403
* virtualApplications        -- "Path mappings": a virtual path serves its own physical directory of the app's file system
* defaultDocuments           -- a directory request serves the first configured document that exists (in order)
* errorPages                 -- the HTML configured for 403/404/500 replaces the platform default body
* handlerMappings            -- not executed (reported via the ``x-vyomi-skipped`` header)
* healthCheckPath            -- probes the path (a function or a file) every request window; the result is recorded on the site
                                 (``_webhost.health``) and reflected in ``x-vyomi-health`` -- with one instance the app keeps serving
* alwaysOn                   -- a non-Always-On app unloads after 20 idle minutes; the next request is a COLD START (extra
                                 latency recorded, ``x-vyomi-cold-start: true``) -- an Always-On app never does
* app settings               -- function code runs with them as its environment (``os.environ``) via core/azure_webapp_core
* Function Apps              -- ``/api/{function}`` runs the deployed function in the sandbox (the real invoke path)
* Web Apps                   -- the site's file system (Kudu VFS wwwroot: deployed package + edits) is served as static content

Every request is appended to a bounded per-site log (``_webhost.log``): the REAL series behind the ``Requests`` / ``Http5xx`` /
``AverageResponseTime`` site metrics and the plan ``CpuPercentage`` load gauge that autoscale (core/azure_autoscale_core.py) reads.
Honest limits: no language runtime executes a Web App's server-side code (only static content and Python Functions run); the
handler mappings are stored, not executed; TLS version is evaluated from a declared header (no real TLS terminates here).
"""
from __future__ import annotations

import json
import mimetypes
import time
from datetime import datetime, timezone

try:
    from core import azure_kudu_core as kudu
    from core import azure_webnet_core as webnet
except ImportError:                                    # Pyodide flat layout
    import azure_kudu_core as kudu                     # type: ignore
    import azure_webnet_core as webnet                 # type: ignore

LOG_MAX = 5000
IDLE_UNLOAD_S = 20 * 60
COLD_START_MS = 1500.0
TLS_ORDER = {"1.0": 0, "1.1": 1, "1.2": 2, "1.3": 3}
#: nominal requests/second one instance of each plan size absorbs before reporting 100 % CPU (the load gauge, see capability text)
NOMINAL_RPS = 20.0

_DEFAULT_PAGES = {
    403: "<html><head><title>403 - Forbidden</title></head><body><h2>403 - Forbidden: Access is denied.</h2>%s</body></html>",
    404: "<html><head><title>404 Not Found</title></head><body><h2>404 Web Site not found.</h2><p>%s</p></body></html>",
    500: "<html><head><title>500 - Internal server error</title></head><body><h2>500 - Internal server error.</h2><p>%s</p></body></html>",
}


def _cfg(site):
    return (site.get("properties") or {}).get("siteConfig") or {}


def _host(site):
    return site.setdefault("_webhost", {"log": [], "last": None, "health": None})


def _resp(status, body=b"", ctype="text/html", headers=None):
    if isinstance(body, str):
        body = body.encode()
    h = {"content-type": ctype}
    h.update(headers or {})
    return {"status": status, "headers": h, "body": body}


def _error_page(site, status, detail=""):
    pages = _cfg(site).get("errorPages") or {}
    custom = pages.get(str(status))
    if custom and str(custom).strip():
        return str(custom)
    return _DEFAULT_PAGES.get(status, "<html><body>%s</body></html>") % detail


def _physical(site, vpath):
    """Longest matching virtual application -> (physical /home/... dir, remaining path)."""
    apps = _cfg(site).get("virtualApplications") or [{"virtualPath": "/", "physicalPath": "site\\wwwroot"}]
    best, rest = None, vpath
    for a in apps:
        vp = "/" + str(a.get("virtualPath") or "/").strip("/")
        vp = "" if vp == "/" else vp
        if vpath == vp or vpath.startswith(vp + "/") or vp == "":
            if best is None or len(vp) > len(best[0]):
                best, rest = (vp, a), (vpath[len(vp):] or "/")
    if best is None:
        return kudu.WWW, vpath
    phys = str(best[1].get("physicalPath") or "site\\wwwroot").replace("\\", "/").strip("/")
    return kudu.ROOT + "/" + phys, rest


def _probe(site, fnmod, now):
    """Run the configured health check path through the same serving code (without front-end filters)."""
    path = (_cfg(site).get("healthCheckPath") or "").strip()
    if not path:
        return None
    r = _serve_content(site, "GET", path, {}, {}, b"", fnmod)
    h = {"path": path, "status": r["status"], "healthy": r["status"] < 400, "checkedAt": now}
    _host(site)["health"] = h
    return h


def _serve_content(site, method, path, query, headers, body, fnmod):
    fx = site.get("kind", "") or ""
    # Function App: /api/{function}
    if "functionapp" in fx.lower() and path.lower().startswith("/api/"):
        fname = path[5:].split("/")[0]
        fn = (site.get("_functions") or {}).get(fname)
        if fn is None:
            return _resp(404, _error_page(site, 404, f"Function '{fname}' does not exist on {site['name']}."))
        res = fnmod._invoke_function(site, fn, {"method": method, "query": query, "headers": headers, "body": body, "path": path})
        if not res["ok"]:
            st = res.get("status") or 500
            return _resp(st, json.dumps({"error": res.get("error")}), "application/json", res.get("headers"))
        b = res["body"]
        if isinstance(b, (bytes, bytearray)):
            return _resp(res.get("status", 200), bytes(b), "application/octet-stream")
        if isinstance(b, str):
            return _resp(res.get("status", 200), b, "text/plain")
        return _resp(res.get("status", 200), json.dumps(b), "application/json")
    files = kudu._view(site)
    base, rest = _physical(site, "/" + path.strip("/") if path.strip("/") else "/")
    full = (base.rstrip("/") + "/" + rest.strip("/")).rstrip("/") if rest.strip("/") else base
    if full in files:
        ct = mimetypes.guess_type(full)[0] or "application/octet-stream"
        return _resp(200, files[full], ct)
    if any(p.startswith(full + "/") for p in files):
        for doc in _cfg(site).get("defaultDocuments") or []:
            cand = full + "/" + doc
            if cand in files:
                return _resp(200, files[cand], mimetypes.guess_type(cand)[0] or "text/html")
        return _resp(403, _error_page(site, 403, "The Web server is configured to not list the contents of this directory."))
    return _resp(404, _error_page(site, 404, "The resource you are looking for has been removed, had its name changed, or is temporarily unavailable."))


def serve(state, site, method, path, query=None, headers=None, body=b"", now=None, fnmod=None):
    t0 = time.perf_counter()
    now = time.time() if now is None else now
    h = {str(k).lower(): str(v) for k, v in (headers or {}).items()}
    method = method.upper()
    path = "/" + path.strip("/") if path.strip("/") else "/"
    host = _host(site)
    if fnmod is None:
        try:
            from core import azure_webapp_core as fnmod
        except ImportError:
            import azure_webapp_core as fnmod      # type: ignore
    props = site.get("properties") or {}
    cfg = _cfg(site)
    extra = {}

    def done(r):
        r["headers"].update(extra)
        ms = (time.perf_counter() - t0) * 1000 + (COLD_START_MS if extra.get("x-vyomi-cold-start") else 0)
        host["log"].append({"t": now, "method": method, "path": path, "status": r["status"], "ms": round(ms, 2)})
        del host["log"][:-LOG_MAX]
        host["last"] = now
        return r

    # front-end filters, in the order App Service applies them
    if props.get("state") == "Stopped" or props.get("enabled") is False:
        return done(_resp(403, "<html><body><h2>Error 403 - This web app is stopped.</h2></body></html>"))
    if str(props.get("publicNetworkAccess", "Enabled")) == "Disabled":
        return done(_resp(403, _error_page(site, 403, "Public network access is disabled for this app.")))
    if props.get("httpsOnly") and h.get("x-forwarded-proto", "https").lower() == "http":
        host_name = h.get("host") or f"{site['name']}.azurewebsites.net"
        return done(_resp(301, "", headers={"location": f"https://{host_name}{path}"}))
    declared = h.get("x-vyomi-tls-version")
    minv = str(cfg.get("minTlsVersion") or "1.2")
    if declared and TLS_ORDER.get(declared, 99) < TLS_ORDER.get(minv, 2):
        return done(_resp(421, f"TLS {declared} is below this app's minimum TLS version {minv}.", "text/plain",
                          {"x-vyomi-reason": "minTlsVersion"}))
    if cfg.get("clientCertEnabled") and str(cfg.get("clientCertMode", "Required")) == "Required" and not h.get("x-arr-clientcert"):
        return done(_resp(403, _error_page(site, 403, "A client certificate is required (clientCertMode=Required).")))
    den = webnet.evaluate_access(state, site, headers)
    if den:
        return done(_resp(den[0], _error_page(site, den[0], den[2])))
    # instance lifecycle: cold start unless Always On
    last = host.get("last")
    if not cfg.get("alwaysOn") and (last is None or now - last > IDLE_UNLOAD_S):
        extra["x-vyomi-cold-start"] = "true"
    # health check
    stamp = datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    hc = _probe(site, fnmod, stamp) if cfg.get("healthCheckPath") else None
    if hc:
        extra["x-vyomi-health"] = "healthy" if hc["healthy"] else "unhealthy"
    if cfg.get("handlerMappings"):
        extra["x-vyomi-skipped"] = "handlerMappings"
    r = _serve_content(site, method, path, query or {}, h, body or b"", fnmod)
    if r["status"] >= 400 and r["status"] in (403, 404, 500) and not r["body"]:
        r["body"] = _error_page(site, r["status"]).encode()
    return done(r)


# ── metrics derived from the real request log (consumed by autoscale + Monitor) ────────────────────────
def window(site, now, seconds):
    return [x for x in (site.get("_webhost") or {}).get("log", []) if now - seconds <= x["t"] <= now]


def metric(site, name, now, seconds, instances=1):
    """-> (value|None, unit). Site metrics from real requests; ``CpuPercentage`` is a LOAD GAUGE (requests/s per instance against
    a nominal capacity), not a measured CPU (no CPU exists to measure)."""
    log = window(site, now, seconds)
    n = name.lower()
    if n in ("requests", "http2xx", "http4xx", "http5xx"):
        if n == "requests":
            return float(len(log)), "Count"
        cls = int(n[4])
        return float(len([x for x in log if x["status"] // 100 == cls])), "Count"
    if n in ("averageresponsetime", "httpresponsetime"):
        return (sum(x["ms"] for x in log) / len(log) / 1000.0) if log else 0.0, "Seconds"
    if n in ("cpupercentage", "memorypercentage"):
        rps = len(log) / float(seconds)
        return min(100.0, 100.0 * rps / (NOMINAL_RPS * max(1, instances))), "Percent"
    return None, ""


# ── API Management link (siteConfig.apiManagementConfig) ──────────────────────────────────────────────
SITE_SCHEME = "vyomi-site://"          # backend URL scheme the APIM gateway's fetch resolves IN-PROCESS to serve() (no socket needed)


def apim_link(state, site):
    """Import the app's API into the linked API Management instance (Function App: one operation per function, Web App: every
    method on ``/*``). ``apiManagementConfig.id`` may be the service id or ``.../service/{svc}/apis/{api}``. Returns an error
    string or None. Removing the link (null) deletes the imported API + its operations."""
    cfg = _cfg(site).get("apiManagementConfig")
    imported = site.get("_apim_import")
    if not cfg or not cfg.get("id"):
        if imported:
            for k in [k for k in list(state) if k == imported or k.startswith(imported + "/")]:
                state.pop(k, None)
            site.pop("_apim_import", None)
        return None
    rid = str(cfg["id"])
    low = rid.lower()
    if "/apis/" in low:
        svc_id, api_name = rid[: low.index("/apis/")], rid.rsplit("/", 1)[-1]
    else:
        svc_id, api_name = rid.rstrip("/"), site["name"]
    svc = state.get(svc_id.lower())
    if svc is None or str(svc.get("type", "")).lower() != "microsoft.apimanagement/service":
        return f"API Management service '{svc_id.rsplit('/', 1)[-1]}' was not found."
    api_id = f"{svc['id']}/apis/{api_name}"
    if imported and imported != api_id.lower():
        for k in [k for k in list(state) if k == imported or k.startswith(imported + "/")]:
            state.pop(k, None)
    base = {"location": svc.get("location"), "tags": {}, "_sub": svc.get("_sub"), "_rg": svc.get("_rg")}
    for k in [k for k in list(state) if k.startswith(api_id.lower() + "/operations/")]:
        state.pop(k, None)
    is_fn = "functionapp" in (site.get("kind") or "").lower()
    state[api_id.lower()] = dict(base, id=api_id, name=api_name, type="Microsoft.ApiManagement/service/apis",
                                 _type="Microsoft.ApiManagement/service/apis", properties={
        "displayName": site["name"], "path": site["name"], "protocols": ["https"], "subscriptionRequired": True, "apiRevision": "1",
        "isCurrent": True, "serviceUrl": SITE_SCHEME + site["name"] + ("/api" if is_fn else ""),
        "description": f"Imported from {'Function App' if is_fn else 'App Service'} '{site['name']}'", "vyomiImportedFrom": site["id"]})
    ops = ([(m, f"/{fn}", f"{m.lower()}-{fn}") for fn in (site.get("_functions") or {}) for m in ("GET", "POST")] if is_fn else
           [(m, "/*", f"{m.lower()}-all") for m in ("GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS")])
    for m, tpl, nm in ops:
        oid = f"{api_id}/operations/{nm}"
        state[oid.lower()] = dict(base, id=oid, name=nm, type="Microsoft.ApiManagement/service/apis/operations",
                                  _type="Microsoft.ApiManagement/service/apis/operations",
                                  properties={"displayName": nm, "method": m, "urlTemplate": tpl, "templateParameters": [], "responses": []})
    site["_apim_import"] = api_id.lower()
    return None


def make_fetch(state, outer=None):
    """APIM gateway ``fetch`` that answers ``vyomi-site://{app}/...`` backends by calling serve() in-process; everything else goes to ``outer``."""
    def fetch(method, url, headers, data):
        if url.startswith(SITE_SCHEME):
            rest = url[len(SITE_SCHEME):]
            name, _, tail = rest.partition("/")
            path, _, qs = ("/" + tail).partition("?")
            site = next((r for r in state.values() if isinstance(r, dict) and str(r.get("type", "")).lower() == "microsoft.web/sites"
                         and str(r.get("name", "")).lower() == name.lower()), None)
            if site is None:
                return 502, {}, b"backend app not found"
            from urllib.parse import parse_qs
            r = serve(state, site, method, path, {k: v[0] for k, v in parse_qs(qs).items()}, dict(headers or {}, **{"x-forwarded-proto": "https"}), data or b"")
            return r["status"], r["headers"], r["body"]
        if outer is None:
            return 502, {}, b"Bad Gateway: no outbound network in this runtime"
        return outer(method, url, headers, data)
    return fetch
