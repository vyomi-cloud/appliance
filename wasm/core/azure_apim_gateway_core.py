# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Azure API Management gateway DATA PLANE (substrate-free, pure Python; Pyodide-loadable).

``handle(state, svc_id, method, path, query, headers, body, fetch=None, now=None)`` serves one request the way the
APIM gateway does, over the service's own ARM records (``Microsoft.ApiManagement/service`` + ``apis`` + ``operations`` +
``policies`` + ``products`` + ``subscriptions`` + ``backends``) kept in the shared ARM state:

* routing -- longest matching API ``path`` prefix, then operation by method + ``urlTemplate`` ({param} segments);
  unknown API/operation -> 404 ``Resource not found`` exactly like the gateway;
* subscription keys -- ``Ocp-Apim-Subscription-Key`` header or ``subscription-key`` query; missing / invalid / suspended /
  out-of-scope (all APIs, one API, one product) -> 401 with the real messages; ``subscriptionRequired=false`` APIs skip it;
* policies -- global, API and operation scopes composed through ``<base />`` into inbound / backend / outbound /
  on-error pipelines. Implemented elements: rate-limit, rate-limit-by-key, quota, quota-by-key, set-header, set-query-parameter,
  rewrite-uri, mock-response, return-response (set-status/set-header/set-body), set-backend-service (base-url |
  backend-id), validate-jwt, check-header, set-body (literal), cors (headers only), choose/when (simple
  ``@(...)`` conditions are NOT evaluated: reported), plus a small ``@(...)`` expression subset (context.Request.IpAddress /
  Method / Url.Path / Headers.GetValueOrDefault("h","d"), context.Subscription.Id|Name, context.Api.Name,
  context.Operation.Name). Any other element is skipped and listed in the ``x-vyomi-apim-skipped-policies`` response header
  and the request log -- never silently "passed";
* backends -- the API ``serviceUrl`` or ``set-backend-service``; the request is forwarded through the host-supplied
  ``fetch(method, url, headers, body) -> (status, headers, bytes)``. A runtime with no outbound network (Nano in a browser tab)
  passes ``fetch=None`` and a forwarded call answers 502 -- ``mock-response`` / ``return-response`` / policy rejections
  still work everywhere;
* analytics -- every request is appended to a bounded log in the service record (``_gw``); ``analytics()`` derives request
  counts, status classes, per-API/operation/subscription breakdowns, latency and the *capacity* gauge from those real
  requests (nominal requests/second per SKU unit -- the real gauge is CPU/memory, which a simulator has not; see the
  capability text).

Honest limits: validate-jwt verifies HS256 signatures against ``issuer-signing-keys`` only; for RS*/ES* tokens the claims
(``exp``/``nbf``/issuer/audience/required-claims) are checked but the signature is NOT verified (flagged with
``x-vyomi-apim-warning``). No response caching, no XML/JSON schema validation, no WebSocket/gRPC/GraphQL pass-through.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import time
import xml.etree.ElementTree as ET

APIM = "microsoft.apimanagement/service"
LOG_MAX = 1000
# nominal sustained requests/second one unit of each SKU is rated at (used only for the simulated capacity gauge)
NOMINAL_RPS = {"developer": 50, "basic": 100, "basicv2": 150, "standard": 250, "standardv2": 300, "premium": 1000,
               "premiumv2": 1000, "consumption": 1000, "isolated": 1000}


class PolicyError(Exception):
    def __init__(self, status, message, headers=None):
        super().__init__(message)
        self.status, self.message, self.headers = status, message, headers or {}


def _body(status, message, headers=None):
    h = {"content-type": "application/json"}
    h.update(headers or {})
    return {"status": status, "headers": h, "body": json.dumps({"statusCode": status, "message": message}).encode()}


def _recs(state, prefix, rtype=None):
    pre = prefix.lower() + "/"
    for k, r in list(state.items()):
        if isinstance(r, dict) and str(k).startswith(pre) and (rtype is None or str(r.get("type", "")).lower() == rtype):
            yield r


def _props(r):
    return (r or {}).get("properties") or {}


def find_service(state, name, rg=None):
    for r in state.values():
        if isinstance(r, dict) and str(r.get("type", "")).lower() == APIM and str(r.get("name", "")).lower() == name.lower() \
                and (not rg or str(r.get("_rg", "")).lower() == rg.lower()):
            return r
    return None


# ── policies ──────────────────────────────────────────────────────────────────
def _parse(xml_text):
    try:
        root = ET.fromstring(xml_text or "<policies/>")
    except ET.ParseError:
        return None
    return {sec: list(root.find(sec)) if root.find(sec) is not None else None for sec in ("inbound", "backend", "outbound", "on-error")}


def _compose(levels, section):
    """Expand <base /> through the scopes (outermost first). A scope that omits a section contributes nothing of its own."""
    out = []
    for lv in levels:
        els = lv.get(section) if lv else None
        if els is None:
            continue
        merged = []
        for e in els:
            if e.tag == "base":
                merged.extend(out)
            else:
                merged.append(e)
        out = merged
    return out


def _policy_xml(state, rid):
    r = state.get((rid + "/policies/policy").lower())
    return _props(r).get("value") if r else None


class _Ctx:
    def __init__(self, svc, api, op, sub, method, path, query, headers, body, ip):
        self.svc, self.api, self.op, self.sub = svc, api, op, sub
        self.method, self.path, self.query, self.headers, self.body, self.ip = method, path, query, headers, body, ip
        self.backend_url = None
        self.rewrite = None
        self.resp = None          # a short-circuit response
        self.warnings, self.skipped = [], []
        self.cors = None

    def expr(self, s):
        s = (s or "").strip()
        m = re.fullmatch(r"@\((.*)\)", s, re.S)
        if not m:
            return s
        e = m.group(1).strip()
        if re.fullmatch(r'"[^"]*"', e):
            return e[1:-1]
        table = {"context.Request.IpAddress": self.ip, "context.Request.Method": self.method, "context.Request.Url.Path": self.path,
                 "context.Subscription.Id": (self.sub or {}).get("name", ""), "context.Subscription.Name": _props(self.sub).get("displayName", ""),
                 "context.Api.Name": _props(self.api).get("displayName", ""), "context.Operation.Name": _props(self.op).get("displayName", "")}
        if e in table:
            return str(table[e])
        m = re.fullmatch(r'context\.Request\.Headers\.GetValueOrDefault\("([^"]+)"\s*,\s*"([^"]*)"\)', e)
        if m:
            return self.headers.get(m.group(1).lower(), m.group(2))
        raise PolicyError(500, f"Expression '{s}' is outside the supported subset.")


def _a(e, name, default=None):
    return e.get(name, default)


def _period(e):
    n = int(_a(e, "renewal-period", "60"))
    return max(1, n)


def _limit(ctx, e, key_extra, bag, now, kind):
    calls = int(_a(e, "calls", "0"))
    period = _period(e)
    key = "|".join([kind, _a(e, "counter-key", "") and ctx.expr(_a(e, "counter-key")) or "", key_extra, str(calls), str(period)])
    w = bag.get(key)
    if not w or now - w[0] >= period:
        w = [now, 0]
    w[1] += 1
    bag[key] = w
    if w[1] > calls:
        wait = max(1, int(period - (now - w[0])))
        if kind == "quota":
            raise PolicyError(403, f"Out of call volume quota. Quota will be replenished in {wait} seconds.", {"Retry-After": str(wait)})
        raise PolicyError(429, f"Rate limit is exceeded. Try again in {wait} seconds.", {"Retry-After": str(wait)})


def _b64d(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _jwt(ctx, e, now):
    hn = _a(e, "header-name")
    tok = ctx.headers.get((hn or "authorization").lower(), "")
    if not hn or hn.lower() == "authorization":
        tok = tok[7:] if tok.lower().startswith("bearer ") else ""
    fail = lambda msg="Unauthorized. Access token is missing or invalid.": PolicyError(  # noqa: E731
        int(_a(e, "failed-validation-httpcode", "401")), _a(e, "failed-validation-error-message") or msg,
        {"WWW-Authenticate": 'Bearer error="invalid_token"'})
    if not tok:
        raise fail()
    try:
        h_b, p_b, s_b = tok.split(".")
        hdr, claims = json.loads(_b64d(h_b)), json.loads(_b64d(p_b))
    except Exception:
        raise fail()
    keys = [k.text.strip() for k in e.findall("issuer-signing-keys/key") if (k.text or "").strip()]
    alg = str(hdr.get("alg", ""))
    if alg == "HS256" and keys:
        ok = False
        for k in keys:
            try:
                kb = base64.b64decode(k)
            except Exception:
                kb = k.encode()
            sig = hmac.new(kb, f"{h_b}.{p_b}".encode(), hashlib.sha256).digest()
            ok = ok or hmac.compare_digest(sig, _b64d(s_b))
        if not ok:
            raise fail("Unauthorized. Access token signature is invalid.")
    elif alg.startswith(("RS", "ES", "PS")) or not keys:
        if alg.lower() == "none":
            raise fail()
        ctx.warnings.append("jwt-signature-unverified")
    skew = int(_a(e, "clock-skew", "0"))
    if "exp" in claims and now > float(claims["exp"]) + skew:
        raise fail("Unauthorized. Access token is expired.")
    if "nbf" in claims and now < float(claims["nbf"]) - skew:
        raise fail()
    iss = [(i.text or "").strip() for i in e.findall("issuers/issuer")]
    if iss and claims.get("iss") not in iss:
        raise fail("Unauthorized. Access token issuer is invalid.")
    aud = [(i.text or "").strip() for i in e.findall("audiences/audience")]
    if aud:
        ca = claims.get("aud")
        if not (set(ca if isinstance(ca, list) else [ca]) & set(aud)):
            raise fail("Unauthorized. Access token audience is invalid.")
    for c in e.findall("required-claims/claim"):
        have = claims.get(c.get("name"))
        have = have if isinstance(have, list) else ([] if have is None else str(have).split(" ") if c.get("separator") == " " else [have])
        want = [(v.text or "").strip() for v in c.findall("value")]
        if (want and not ((set(map(str, have)) & set(want)) if c.get("match", "all") == "any" else set(want) <= set(map(str, have)))) \
                or (not want and not have):
            raise fail("Unauthorized. Required claim is missing or does not match.")


def _run(ctx, els, state, bag, now, phase):
    for e in els:
        t = e.tag
        if t == "rate-limit":
            _limit(ctx, e, (ctx.sub or {}).get("name", ctx.ip), bag, now, "rate")
        elif t == "rate-limit-by-key":
            _limit(ctx, e, "", bag, now, "rate")
        elif t in ("quota", "quota-by-key"):
            _limit(ctx, e, (ctx.sub or {}).get("name", ctx.ip) if t == "quota" else "", bag, now, "quota")
        elif t == "set-header":
            name, act = _a(e, "name", ""), _a(e, "exists-action", "override")
            vals = [ctx.expr(v.text or "") for v in e.findall("value")]
            tgt = ctx.resp_headers if phase == "outbound" else ctx.headers
            low = name.lower()
            if act == "delete":
                for k in [k for k in tgt if k.lower() == low]:
                    tgt.pop(k)
            elif act == "skip" and low in {k.lower() for k in tgt}:
                pass
            elif act == "append" and low in {k.lower() for k in tgt}:
                k0 = next(k for k in tgt if k.lower() == low)
                tgt[k0] = ", ".join([tgt[k0]] + vals)
            else:
                for k in [k for k in tgt if k.lower() == low]:
                    tgt.pop(k)
                tgt[name if phase == "outbound" else low] = ", ".join(vals)
        elif t == "set-query-parameter":
            n, act = _a(e, "name", ""), _a(e, "exists-action", "override")
            vals = [ctx.expr(v.text or "") for v in e.findall("value")]
            if act == "delete":
                ctx.query.pop(n, None)
            elif not (act == "skip" and n in ctx.query):
                ctx.query[n] = ",".join(vals) if act != "append" or n not in ctx.query else ctx.query[n] + "," + ",".join(vals)
        elif t == "rewrite-uri":
            ctx.rewrite = ctx.expr(_a(e, "template", ""))
            if not ctx.rewrite.startswith("/"):
                raise PolicyError(500, "rewrite-uri template must start with '/'.")
        elif t == "mock-response":
            ctx.resp = _mock(ctx, e)
        elif t == "return-response":
            st = e.find("set-status")
            hdrs = {}
            for h in e.findall("set-header"):
                hdrs[_a(h, "name", "")] = ", ".join(ctx.expr(v.text or "") for v in h.findall("value"))
            b = e.find("set-body")
            data = ctx.expr(b.text or "").encode() if b is not None else b""
            hdrs.setdefault("content-type", "application/json" if data[:1] in (b"{", b"[") else "text/plain")
            ctx.resp = {"status": int(_a(st, "code", "200")) if st is not None else 200, "headers": hdrs, "body": data}
        elif t == "set-backend-service":
            if _a(e, "base-url"):
                ctx.backend_url = ctx.expr(_a(e, "base-url"))
            elif _a(e, "backend-id"):
                bk = state.get((ctx.svc["id"] + "/backends/" + ctx.expr(_a(e, "backend-id"))).lower())
                if not bk:
                    raise PolicyError(500, f"Backend '{_a(e, 'backend-id')}' was not found.")
                ctx.backend_url = _props(bk).get("url")
            else:
                raise PolicyError(500, "set-backend-service needs base-url or backend-id.")
        elif t == "validate-jwt":
            _jwt(ctx, e, now)
        elif t == "check-header":
            n = _a(e, "name", "")
            have = ctx.headers.get(n.lower())
            vals = [(v.text or "").strip() for v in e.findall("value")]
            ign = _a(e, "ignore-case", "false").lower() == "true"
            ok = have is not None and (not vals or any((have.lower() == v.lower()) if ign else have == v for v in vals))
            if not ok:
                raise PolicyError(int(_a(e, "failed-check-httpcode", "401")), _a(e, "failed-check-error-message") or f"Header '{n}' is missing or has an invalid value.")
        elif t == "set-body":
            ctx.set_body = ctx.expr(e.text or "")
        elif t == "cors":
            ctx.cors = [(o.text or "").strip() for o in e.findall("allowed-origins/origin")]
        elif t == "forward-request":
            pass
        else:
            ctx.skipped.append(t)


def _mock(ctx, e):
    code = int(_a(e, "status-code", "200"))
    ct = _a(e, "content-type")
    reps = []
    for resp in (_props(ctx.op).get("responses") or []):
        if int(resp.get("statusCode", 0)) == code:
            reps = resp.get("representations") or []
    rep = next((r for r in reps if not ct or r.get("contentType") == ct), None)
    if rep:
        ct = ct or rep.get("contentType")
        ex = rep.get("examples") or {}
        sample = rep.get("sample") or (next(iter(ex.values()), {}) or {}).get("value")
        data = (sample if isinstance(sample, str) else json.dumps(sample)).encode() if sample is not None else b""
    elif ct or not reps:
        data = b""
    else:
        data = b""
    h = {"content-type": ct} if ct else {}
    return {"status": code, "headers": h, "body": data}


# ── routing ──────────────────────────────────────────────────────────────────
def _match_template(tpl, path):
    tpl = tpl.split("?", 1)[0]
    if tpl.endswith("/*"):                              # wildcard operation (``/*`` matches any tail, as APIM wildcard operations do)
        pre = tpl[:-2]
        if path == pre or path.startswith(pre + "/") or not pre:
            return re.match(r"(?P<_tail>.*)", path)
        return None
    rx = "^" + re.sub(r"\\\{([^/}]+)\\\}", r"(?P<\1>[^/]+)", re.escape(tpl.rstrip("/") or "/")) + "/?$"
    try:
        return re.match(rx, path)
    except re.error:
        return None


def _api_in_product(state, svc_id, api_name, product):
    return (f"{svc_id}/products/{product}/apis/{api_name}").lower() in state


def _auth(state, svc, api, key):
    """-> (sub_record|None, error_message|None)."""
    try:
        from core import azure_arm_ext_core as ext
    except ImportError:
        import azure_arm_ext_core as ext   # type: ignore
    sid = svc["id"]
    if not key:
        return None, "Access denied due to missing subscription key. Make sure to include subscription key when making requests to an API."
    cands = [(None, "master")] + [(r, r.get("name", "")) for r in _recs(state, sid + "/subscriptions", APIM + "/subscriptions")]
    for rec, name in cands:
        if key not in ext.apim_sub_keys(sid, name, rec):
            continue
        p = _props(rec)
        if str(p.get("state", "active")).lower() in ("suspended", "cancelled", "expired", "rejected", "submitted"):
            return None, "Access denied due to invalid subscription key. Make sure to provide a valid key for an active subscription."
        scope = str(p.get("scope", "")).lower().rstrip("/")
        base = sid.lower()
        rest = scope[len(base):] if scope.startswith(base) else scope
        an = api.get("name", "")
        if rest in ("", "/apis") or rec is None:
            return rec or {"name": "master", "properties": {}}, None
        if rest == f"/apis/{an.lower()}" or (rest.startswith("/products/") and _api_in_product(state, sid, an, rest.split("/")[2])):
            return rec, None
        return None, "Access denied due to invalid subscription key. Make sure to provide a valid key for an active subscription."
    return None, "Access denied due to invalid subscription key. Make sure to provide a valid key for an active subscription."


def handle(state, svc, method, path, query, headers, body, fetch=None, now=None, ip="127.0.0.1", gateway=None):
    """Serve one gateway request. ``svc`` is the APIM service record; ``path`` is the gateway path (no query)."""
    now = time.time() if now is None else now
    t0 = time.time()
    method = method.upper()
    path = "/" + path.strip("/") if path.strip("/") else "/"
    qd = {k: (v[0] if isinstance(v, list) else v) for k, v in (query or {}).items()}
    hd = {k.lower(): v for k, v in (headers or {}).items()}
    gw = svc.setdefault("_gw", {"log": [], "rl": {}})
    sid = svc["id"]
    api = op = sub = None
    skipped, warns = [], []

    def done(res, **kw):
        res["headers"].setdefault("x-vyomi-apim-request-id", hashlib.sha1(f"{sid}{now}{path}".encode()).hexdigest()[:16])
        if skipped:
            res["headers"]["x-vyomi-apim-skipped-policies"] = ",".join(sorted(set(skipped)))
        if warns:
            res["headers"]["x-vyomi-apim-warning"] = ",".join(sorted(set(warns)))
        gw["log"].append({"t": now, "method": method, "path": path, "status": res["status"], "ms": round((time.time() - t0) * 1000, 2),
                          "api": (api or {}).get("name"), "op": (op or {}).get("name"), "sub": (sub or {}).get("name"), "ip": ip,
                          "skipped": sorted(set(skipped)), **kw})
        del gw["log"][:-LOG_MAX]
        return res

    # route: longest API path prefix
    apis = [a for a in _recs(state, sid + "/apis", APIM + "/apis") if "/" not in a["id"][len(sid) + 6:]]
    if gateway:   # a SELF-HOSTED gateway serves only the APIs associated with it (service/gateways/{gw}/apis/{api}); the managed gateway serves all
        if f"{sid}/gateways/{gateway}".lower() not in state:
            return done(_body(404, f"Gateway '{gateway}' not found."))
        apis = [a for a in apis if f"{sid}/gateways/{gateway}/apis/{a['name']}".lower() in state]
    best, rem = None, None
    for a in apis:
        pre = "/" + str(_props(a).get("path", "")).strip("/")
        pre = "" if pre == "/" else pre
        if (path == pre or path.startswith(pre + "/") or pre == "") and (best is None or len(pre) > len(best[0])):
            best, rem = (pre, a), (path[len(pre):] or "/")
    if best is None:
        return done(_body(404, "Resource not found"))
    api = best[1]
    ap = _props(api)
    ops = list(_recs(state, api["id"] + "/operations", APIM + "/apis/operations"))
    mt = None
    for o in ops:
        op_p = _props(o)
        if str(op_p.get("method", "")).upper() == method:
            mm = _match_template(str(op_p.get("urlTemplate", "")), rem)
            if mm:
                op, mt = o, mm.groupdict()
                break
    if op is None:
        return done(_body(404, "Resource not found"))
    # subscription key
    if ap.get("subscriptionRequired", True) is not False:
        key = hd.get("ocp-apim-subscription-key") or qd.get("subscription-key") or ""
        sub, err = _auth(state, svc, api, key)
        if err:
            return done(_body(401, err))
    ctx = _Ctx(svc, api, op, sub, method, path, {k: v for k, v in qd.items() if k != "subscription-key"}, dict(hd), body or b"", ip)
    ctx.resp_headers = {}
    ctx.set_body = None
    lv = [_parse(_policy_xml(state, sid)), _parse(_policy_xml(state, api["id"])), _parse(_policy_xml(state, op["id"]))]
    bag = gw["rl"]
    resp = None
    try:
        _run(ctx, _compose(lv, "inbound"), state, bag, now, "inbound")
        if ctx.resp is None:
            _run(ctx, _compose(lv, "backend"), state, bag, now, "backend")
        if ctx.resp is not None:
            resp = {"status": ctx.resp["status"], "headers": dict(ctx.resp["headers"]), "body": ctx.resp["body"]}
        else:
            base = (ctx.backend_url or ap.get("serviceUrl") or "").rstrip("/")
            if not base:
                raise PolicyError(500, "The API has no backend: set serviceUrl or a set-backend-service policy.")
            tail = ctx.rewrite if ctx.rewrite is not None else rem
            if ctx.rewrite is not None:
                tail = re.sub(r"\{([^}]+)\}", lambda m: (mt or {}).get(m.group(1), m.group(0)), tail)
            url = base + (tail if tail.startswith("/") else "/" + tail)
            if ctx.query:
                from urllib.parse import urlencode
                url += "?" + urlencode(ctx.query)
            fh = {k: v for k, v in ctx.headers.items() if k not in ("host", "content-length", "ocp-apim-subscription-key", "connection")}
            data = ctx.set_body.encode() if ctx.set_body is not None else ctx.body
            if fetch is None:
                resp = _body(502, "Bad Gateway: the backend cannot be reached from this runtime (no outbound network).")
            else:
                try:
                    st, rh, rb = fetch(method, url, fh, data)
                    resp = {"status": st, "headers": {k: v for k, v in (rh or {}).items() if k.lower() not in ("transfer-encoding", "content-length", "connection")}, "body": rb or b""}
                except Exception as e:  # noqa: BLE001
                    resp = _body(502, f"Bad Gateway: {type(e).__name__}: {e}")
        ctx.resp_headers = resp["headers"]
        _run(ctx, _compose(lv, "outbound"), state, bag, now, "outbound")
        if ctx.cors is not None:
            origin = hd.get("origin")
            if origin and ("*" in ctx.cors or origin in ctx.cors):
                resp["headers"]["Access-Control-Allow-Origin"] = origin
    except PolicyError as pe:
        resp = _body(pe.status, pe.message, pe.headers)
    skipped.extend(ctx.skipped)
    warns.extend(ctx.warnings)
    return done(resp)


# ── analytics ────────────────────────────────────────────────────────────────
def analytics(svc, now=None, window=3600.0):
    now = time.time() if now is None else now
    log = [x for x in (svc.get("_gw") or {}).get("log", []) if now - x["t"] <= window]
    total = len(log)

    def grp(k):
        d = {}
        for x in log:
            d[x.get(k) or "-"] = d.get(x.get(k) or "-", 0) + 1
        return d
    classes = {"2xx": 0, "3xx": 0, "4xx": 0, "5xx": 0}
    for x in log:
        classes[f"{x['status'] // 100}xx"] = classes.get(f"{x['status'] // 100}xx", 0) + 1
    units = int((svc.get("sku") or {}).get("capacity") or 1)
    sku = str((svc.get("sku") or {}).get("name", "Developer")).lower()
    rps = len([x for x in log if now - x["t"] <= 60]) / 60.0
    nominal = NOMINAL_RPS.get(sku, 50) * max(1, units)
    lat = sorted(x["ms"] for x in log)
    return {"windowSeconds": int(window), "totalRequests": total, "statusClasses": classes,
            "failedRequests": classes.get("4xx", 0) + classes.get("5xx", 0), "byApi": grp("api"), "byOperation": grp("op"),
            "bySubscription": grp("sub"), "avgLatencyMs": round(sum(lat) / total, 2) if total else 0,
            "p95LatencyMs": lat[int(0.95 * (total - 1))] if total else 0, "requestsPerSecond60s": round(rps, 3),
            "capacity": {"percent": min(100, round(100 * rps / nominal, 2)), "unit": "%", "units": max(1, units), "sku": sku,
                         "basis": f"{rps:.3f} req/s over the last 60 s against a nominal {nominal} req/s ({NOMINAL_RPS.get(sku, 50)} per {sku} unit); "
                                  "derived from real simulator gateway requests, not CPU/memory"},
            "recent": list(reversed(log[-50:]))}
