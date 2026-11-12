"""Front Door / CDN edge: a REAL caching reverse proxy in front of Blob storage (pure Python, Nano + offline).

Control plane (core/azure_netcfg_core.py) already stores profiles, afdEndpoints, origin groups, origins, routes, rule sets
(and classic CDN endpoints).  This module is the data plane those records configure:

    GET|HEAD /_edge/{endpoint hostname}/{path}      (offline: /azure-data/blob/_edge/{hostname}/{path})

  1. the endpoint is found by its hostname (``*.z01.azurefd.net`` / ``*.azureedge.net``); a Disabled endpoint -> 404;
  2. an AFD route is chosen by patternsToMatch (longest pattern wins; disabled routes skipped); a classic CDN endpoint uses
     its own origins;
  3. the origin is the best enabled origin (lowest priority, highest weight) of the route's origin group; origins whose host
     is ``{account}.blob.core.windows.net`` are fetched from the Blob data plane (``fetch`` callback) with originPath applied;
  4. responses are CACHED per (endpoint, path[, query per queryStringCachingBehavior]) with a TTL from the rule set's
     CacheExpiration action, else the origin's Cache-Control max-age, else 2 days (the Front Door default for cacheable
     content); only 200 GET/HEAD responses are cached; BypassCache disables caching;
  5. ``x-cache: TCP_HIT`` / ``TCP_MISS`` (+ ``age``) on every response; conditional requests (If-None-Match) are answered 304
     from the edge; ModifyResponseHeader actions are applied; a purge (``POST /_edge/{host}/__purge`` {"contentPaths":["/a/*"]})
     really evicts entries; ``GET /_edge/{host}/__stats`` returns hit/miss/origin-request counters.

Not modelled: WAF, TLS termination, custom domains (stay Pending), health probes, multiple PoPs, compression and range requests
beyond what the Blob origin itself answers.  Only Blob (storage) origins are reachable; other origin hosts return 502.
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import re
import time
from urllib.parse import quote

AFD_EP, AFD_ROUTE, AFD_OG, AFD_ORIGIN, AFD_RS, AFD_RULE, CDN_EP = (
    "microsoft.cdn/profiles/afdendpoints", "microsoft.cdn/profiles/afdendpoints/routes", "microsoft.cdn/profiles/origingroups",
    "microsoft.cdn/profiles/origingroups/origins", "microsoft.cdn/profiles/rulesets", "microsoft.cdn/profiles/rulesets/rules",
    "microsoft.cdn/profiles/endpoints")
DEFAULT_TTL = 2 * 24 * 3600
_BLOB_HOST = re.compile(r"^([a-z0-9]{3,24})\.blob\.core\.windows\.net$", re.I)


def _ref(x):
    return (x.get("id") if isinstance(x, dict) else x) or ""


def _recs(state, prefix):
    pre = prefix.lower() + "/"
    return [r for r in state.values() if isinstance(r, dict) and r.get("_type") and "properties" in r and str(r.get("id", "")).lower().startswith(pre)]


def find_endpoint(state, host):
    host = (host or "").lower().split(":")[0]
    for r in state.values():
        if isinstance(r, dict) and (r.get("_type") or "").lower() in (AFD_EP, CDN_EP) and str((r.get("properties") or {}).get("hostName", "")).lower() == host:
            return r
    return None


def _dur(s):
    """'d.hh:mm:ss' / 'hh:mm:ss' -> seconds."""
    m = re.match(r"^(?:(\d+)\.)?(\d+):(\d+):(\d+)$", str(s or ""))
    if not m:
        return None
    d, h, mi, se = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + se


def _match_pattern(pat, path):
    pat = pat if pat.startswith("/") else "/" + pat
    return fnmatch.fnmatchcase(path, pat) or (pat.endswith("/*") and path == pat[:-2])


def _pick_route(state, ep, path):
    best = None
    for r in _recs(state, ep["id"] + "/routes"):
        p = r.get("properties") or {}
        if p.get("enabledState", "Enabled") == "Disabled":
            continue
        for pat in p.get("patternsToMatch") or ["/*"]:
            if _match_pattern(pat, path) and (best is None or len(pat) > best[0]):
                best = (len(pat), r)
    return best[1] if best else None


def _pick_origin(state, og_id):
    cands = [o for o in _recs(state, og_id + "/origins") if (o.get("properties") or {}).get("enabledState", "Enabled") != "Disabled"]
    cands.sort(key=lambda o: ((o["properties"].get("priority", 1)), -(o["properties"].get("weight", 1000))))
    return cands[0] if cands else None


def _rules(state, route):
    out = []
    for rs in (route.get("properties") or {}).get("ruleSets") or []:
        rules = sorted(_recs(state, _ref(rs) + "/rules"), key=lambda r: (r.get("properties") or {}).get("order", 0))
        out.extend(rules)
    return out


def _cond_ok(c, path, query):
    prm = c.get("parameters") or {}
    vals = [str(v) for v in prm.get("matchValues") or []]
    op = (prm.get("operator") or "Equal")
    neg = bool(prm.get("negateCondition"))
    if c.get("name") == "UrlPath":
        subject = path
    elif c.get("name") == "UrlFileExtension":
        subject = path.rsplit(".", 1)[-1] if "." in path.rsplit("/", 1)[-1] else ""
    elif c.get("name") == "UrlFileName":
        subject = path.rsplit("/", 1)[-1]
    elif c.get("name") == "QueryString":
        subject = query
    else:
        return True                                    # conditions the edge cannot observe do not restrict
    low = prm.get("transforms") and "Lowercase" in prm["transforms"]
    if low:
        subject = subject.lower()
        vals = [v.lower() for v in vals]
    ok = {"Equal": lambda v: subject == v, "Contains": lambda v: v in subject, "BeginsWith": lambda v: subject.startswith(v),
          "EndsWith": lambda v: subject.endswith(v), "Any": lambda v: True}.get(op, lambda v: subject == v)
    res = any(ok(v) for v in vals) if vals else op == "Any"
    return res != neg


def _apply_rules(state, route, path, query):
    ttl, cache_mode, resp_hdrs = None, None, []
    for rule in _rules(state, route):
        p = rule.get("properties") or {}
        if all(_cond_ok(c, path, query) for c in p.get("conditions") or []):
            for a in p.get("actions") or []:
                prm = a.get("parameters") or {}
                if a.get("name") == "CacheExpiration":
                    b = prm.get("cacheBehavior")
                    if b == "BypassCache":
                        cache_mode = "bypass"
                    elif b == "Override" or (b == "SetIfMissing" and ttl is None):
                        ttl = _dur(prm.get("cacheDuration")) if _dur(prm.get("cacheDuration")) is not None else ttl
                        cache_mode = cache_mode or "cache"
                elif a.get("name") == "ModifyResponseHeader":
                    resp_hdrs.append((prm.get("headerAction"), prm.get("headerName"), prm.get("value")))
    return ttl, cache_mode, resp_hdrs


def _cache(store):
    c = getattr(store, "_edge_cache", None)
    if c is None:
        c = store._edge_cache = {"entries": {}, "stats": {}}
    return c


def _stats(cache, ep_id):
    return cache["stats"].setdefault(ep_id.lower(), {"requests": 0, "hits": 0, "misses": 0, "bypass": 0, "originRequests": 0, "bytesFromOrigin": 0, "bytesServed": 0})


def _resp(status, body=b"", headers=None):
    return {"status": status, "headers": headers or {}, "body": body}


def _err(status, code, msg):
    return _resp(status, json.dumps({"error": {"code": code, "message": msg}}).encode(), {"content-type": "application/json"})


def serve(state, store, method, host, path, query, headers, body, fetch, now=None):
    """-> {status, headers, body}.  `fetch(account, method, blob_path, query, headers)` -> {status, headers, body} from Blob."""
    now = now if now is not None else time.time()
    method = method.upper()
    headers = {(k or "").lower(): v for k, v in (headers or {}).items()}
    ep = find_endpoint(state, host)
    if ep is None:
        return _err(404, "EndpointNotFound", f"No Front Door / CDN endpoint has the host name '{host}'.")
    cache = _cache(store)
    if path == "/__stats" and method == "GET":
        return _resp(200, json.dumps({"endpoint": ep["name"], **_stats(cache, ep["id"]), "cachedObjects": sum(1 for k in cache["entries"] if k[0] == ep["id"].lower())}).encode(), {"content-type": "application/json"})
    if path == "/__purge" and method == "POST":
        try:
            paths = json.loads(body or b"{}").get("contentPaths") or []
        except ValueError:
            return _err(400, "BadRequest", "Purge body must be JSON.")
        n = 0
        for k in list(cache["entries"]):
            if k[0] == ep["id"].lower() and any(_match_pattern(p, k[1]) for p in paths):
                cache["entries"].pop(k)
                n += 1
        return _resp(200, json.dumps({"purged": n, "contentPaths": paths}).encode(), {"content-type": "application/json"})
    if (ep.get("properties") or {}).get("enabledState", "Enabled") == "Disabled" or (ep.get("properties") or {}).get("resourceState") == "Stopped":
        return _err(404, "EndpointDisabled", "The endpoint is disabled.")
    if method not in ("GET", "HEAD"):
        return _err(405, "MethodNotAllowed", "The edge serves GET and HEAD only.")
    st = _stats(cache, ep["id"])
    st["requests"] += 1
    typ = (ep.get("_type") or "").lower()
    ttl_rule, mode, extra = None, None, []
    if typ == AFD_EP:
        route = _pick_route(state, ep, path)
        if route is None:
            return _err(404, "RouteNotFound", f"No enabled route on endpoint '{ep['name']}' matches '{path}'.")
        rp = route.get("properties") or {}
        og = state.get(_ref(rp.get("originGroup")).lower())
        origin = _pick_origin(state, og["id"]) if og else None
        if origin is None:
            return _err(503, "NoOrigin", "The route's origin group has no enabled origin.")
        ohost = str(origin["properties"].get("hostName", ""))
        opath = rp.get("originPath") or ""
        ttl_rule, mode, extra = _apply_rules(state, route, path, query or "")
        qs_mode = ((rp.get("cacheConfiguration") or {}).get("queryStringCachingBehavior")) or "IgnoreQueryString"
        if not rp.get("cacheConfiguration"):
            mode = mode or "bypass"          # no cacheConfiguration on the route -> Front Door does not cache
    else:
        origins = (ep.get("properties") or {}).get("origins") or []
        if not origins:
            return _err(503, "NoOrigin", "The endpoint has no origin.")
        ohost = str((origins[0].get("properties") or origins[0]).get("hostName", ""))
        opath = (ep.get("properties") or {}).get("originPath") or ""
        qs_mode = (ep.get("properties") or {}).get("queryStringCachingBehavior") or "IgnoreQueryString"
        if qs_mode == "NotSet":
            qs_mode = "IgnoreQueryString"
    m = _BLOB_HOST.match(ohost)
    if not m:
        return _err(502, "OriginNotReachable", f"Origin host '{ohost}' is not a storage account blob endpoint; the simulator edge can only reach Blob origins.")
    account = m.group(1).lower()
    qkey = {"IgnoreQueryString": "", "BypassCaching": None, "UseQueryString": query or "", "IgnoreSpecifiedQueryStrings": "", "IncludeSpecifiedQueryStrings": query or ""}.get(qs_mode, "")
    if qs_mode == "BypassCaching":
        mode = "bypass"
    key = (ep["id"].lower(), path, qkey or "")
    ent = cache["entries"].get(key)
    inm = headers.get("if-none-match")
    if mode != "bypass" and ent and ent["expires"] > now:
        st["hits"] += 1
        h = dict(ent["headers"])
        h.update({"x-cache": "TCP_HIT", "age": str(int(now - ent["stored"]))})
        for act, name, val in extra:
            _mod_header(h, act, name, val)
        if inm and h.get("etag") and inm.strip() == h["etag"]:
            st["bytesServed"] += 0
            return _resp(304, b"", {k: v for k, v in h.items() if k in ("etag", "x-cache", "age", "cache-control")})
        st["bytesServed"] += len(ent["body"])
        return _resp(200, b"" if method == "HEAD" else ent["body"], h)
    # origin fetch
    blob_path = (opath.rstrip("/") + path) if opath else path
    st["originRequests"] += 1
    o = fetch(account, "GET" if method == "HEAD" else method, blob_path + (("?" + query) if query else ""), {})
    if mode == "bypass":
        st["bypass"] += 1
    else:
        st["misses"] += 1
    obody = o.get("body") or b""
    st["bytesFromOrigin"] += len(obody)
    oh = {k.lower(): v for k, v in (o.get("headers") or {}).items()}
    h = {k: oh[k] for k in ("content-type", "etag", "last-modified", "content-md5") if k in oh}
    h["x-cache"] = "CONFIG_NOCACHE" if mode == "bypass" else "TCP_MISS"
    h["x-azure-ref"] = hashlib.sha1(f"{ep['id']}{path}{now}".encode()).hexdigest()[:24]
    if o.get("status") == 200 and mode != "bypass" and "no-store" not in oh.get("cache-control", "") and "private" not in oh.get("cache-control", ""):
        ttl = ttl_rule
        if ttl is None:
            mm = re.search(r"max-age=(\d+)", oh.get("cache-control", ""))
            ttl = int(mm.group(1)) if mm else DEFAULT_TTL
        if ttl > 0:
            cache["entries"][key] = {"stored": now, "expires": now + ttl, "headers": dict(h, **({"cache-control": oh["cache-control"]} if "cache-control" in oh else {})), "body": obody}
            h["cache-control"] = oh.get("cache-control") or f"max-age={ttl}"
    elif "cache-control" in oh:
        h["cache-control"] = oh["cache-control"]
    for act, name, val in extra:
        _mod_header(h, act, name, val)
    return _resp(o.get("status", 502), b"" if method == "HEAD" else obody, h)


def _mod_header(h, act, name, val):
    if not name:
        return
    n = name.lower()
    if act in ("Overwrite", "Append"):
        h[n] = (h[n] + ", " + val) if act == "Append" and n in h else val
    elif act == "Delete":
        h.pop(n, None)
