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

try:
    from core import gateway_common as gc
    from core import azure_apim_expr_core as ex
except ImportError:  # pragma: no cover - Pyodide flat layout
    import gateway_common as gc  # type: ignore
    import azure_apim_expr_core as ex  # type: ignore

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
        self.vars, self.matched, self.out, self.last_error, self.now = {}, None, None, None, time.time()
        self.request_id = hashlib.sha1(f"{path}{time.time()}".encode()).hexdigest()

    def env(self):
        """The ``context`` object the policy expressions see (rebuilt per evaluation so header/variable mutations are visible)."""
        sp, ap, op = _props(self.sub), _props(self.api), _props(self.op)
        q = dict(self.query)
        surl = ap.get("serviceUrl") or ""
        host = (self.headers.get("host") or "").split(":")[0]
        qobj = ex.dict_obj({k: [v] for k, v in q.items()}, "Query")
        qobj.methods["GetValueOrDefault"] = lambda a: q.get(a[0], a[1] if len(a) > 1 else None)
        url = ex.Obj({"Path": self.path, "Host": host, "Port": 443, "Scheme": "https", "Query": qobj,
                      "QueryString": ("?" + "&".join(f"{k}={v}" for k, v in q.items())) if q else ""}, {}, "Url")
        req = ex.Obj({"Method": self.method, "Url": url, "OriginalUrl": url, "Headers": ex.headers_obj(self.headers), "Body": ex.body_obj(self.body),
                      "IpAddress": self.ip, "MatchedParameters": ex.dict_obj(dict(self.matched or {}), "MatchedParameters"), "Certificate": None}, {}, "Request")
        vars_ = self.vars
        vobj = ex.Obj({"Count": len(vars_)}, {"GetValueOrDefault": lambda a: vars_.get(a[0], a[1] if len(a) > 1 else None),
                                              "ContainsKey": lambda a: a[0] in vars_}, "Variables")

        def vidx(k):
            if k not in vars_:
                raise ex.ExprError(f"The given key '{k}' was not present in the dictionary.")
            return vars_[k]
        vobj.index = vidx
        user = None
        if self.sub and sp.get("ownerId"):
            user = ex.Obj({"Id": str(sp["ownerId"]).rsplit("/", 1)[-1], "Email": "", "FirstName": "", "LastName": "", "Groups": []}, {}, "User")
        sub = None if not self.sub else ex.Obj({"Id": self.sub.get("name", ""), "Name": sp.get("displayName", ""), "Key": "", "CreatedDate": ex.CsDate(0)}, {}, "Subscription")
        ctxo = {"Request": req, "Subscription": sub, "User": user,
                "Api": ex.Obj({"Id": (self.api or {}).get("name", ""), "Name": ap.get("displayName", ""), "Path": ap.get("path", ""),
                               "ServiceUrl": ex.Obj({"Host": surl.split("//")[-1].split("/")[0], "Path": "/" + surl.split("//")[-1].partition("/")[2],
                                                     "Scheme": surl.split("://")[0] if "://" in surl else "", "Port": 0}, {}, "ServiceUrl"),
                               "Version": ap.get("apiVersion"), "Revision": ap.get("apiRevision", "1"), "IsCurrentRevision": True}, {}, "Api"),
                "Operation": ex.Obj({"Id": (self.op or {}).get("name", ""), "Name": op.get("displayName", ""), "Method": op.get("method", ""),
                                     "UrlTemplate": op.get("urlTemplate", "")}, {}, "Operation"),
                "Product": None, "Variables": vobj,
                "Deployment": ex.Obj({"ServiceName": self.svc.get("name", ""), "Region": self.svc.get("location", ""), "ServiceId": self.svc.get("id", ""),
                                      "Certificates": []}, {}, "Deployment"),
                "RequestId": self.request_id, "Timestamp": ex.CsDate(self.now), "LastError": self.last_error}
        if self.out is not None:
            ctxo["Response"] = ex.Obj({"StatusCode": self.out["status"], "StatusReason": "", "Headers": ex.headers_obj(self.out.get("headers", {})),
                                       "Body": ex.body_obj(self.out.get("body") or b"")}, {}, "Response")
        else:
            ctxo["Response"] = None
        return {"context": ex.Obj(ctxo, {}, "context")}

    def expr(self, s):
        """One policy attribute/text: a literal as-is, ``@(expr)`` / ``@{ statements }`` evaluated by core/azure_apim_expr_core and stringified like C#."""
        if not ex.is_expression(s):
            return (s or "").strip() if s is not None else ""
        try:
            return ex.cs_str(ex.evaluate(s, self.env()))
        except ex.ExprError as e:
            raise PolicyError(500, f"Expression evaluation failed: {e}")

    def value(self, s):
        """Like expr() but keeps the C# type (bool / number / list): what conditions need."""
        if not ex.is_expression(s):
            return s
        try:
            return ex.evaluate(s, self.env())
        except ex.ExprError as e:
            raise PolicyError(500, f"Expression evaluation failed: {e}")


def _a(e, name, default=None):
    return e.get(name, default)


def _period(e):
    n = int(_a(e, "renewal-period", "60"))
    return max(1, n)


def _limit(ctx, e, key_extra, bag, now, kind):
    calls = int(_a(e, "calls", "0"))
    period = _period(e)
    key = "|".join([kind, _a(e, "counter-key", "") and ctx.expr(_a(e, "counter-key")) or "", key_extra, str(calls), str(period)])
    ok, wait = gc.window_take(bag, key, now, period, 1, calls, count_rejected=True)
    if not ok:
        if kind == "quota":
            raise PolicyError(403, f"Out of call volume quota. Quota will be replenished in {wait} seconds.", {"Retry-After": str(wait)})
        raise PolicyError(429, f"Rate limit is exceeded. Try again in {wait} seconds.", {"Retry-After": str(wait)})


def _b64d(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _rs256_verifier():
    """The shared RS256/JWKS verifier (None on Nano / without `cryptography`); module-level so tests can substitute it."""
    return gc.make_rs256_verifier()


def _entra():
    try:
        from core import azure_entra_tokens_core as m
    except ImportError:
        try:
            import azure_entra_tokens_core as m  # type: ignore
        except ImportError:
            return None
    return m


def _entra_issuer_ok(oc_url, claims, fail):
    """The openid-config URL names the tenant + endpoint version a token must come from (real APIM compares ``iss`` with the issuer in that document)."""
    m = re.match(r"^https?://[^/]+/([^/]+?)(/v2\.0)?/\.well-known/openid-configuration/?$", oc_url or "")
    if not m:
        return
    tenant, v2 = m.group(1), bool(m.group(2))
    tid = str(claims.get("tid", ""))
    if re.fullmatch(r"[0-9a-fA-F]{8}-[0-9a-zA-Z]{4}-[0-9a-zA-Z]{4}-[0-9a-zA-Z]{4}-[0-9a-zA-Z]{12}", tenant) and tenant.lower() != tid.lower():
        raise fail("Unauthorized. Access token issuer is invalid.")
    want = ("https://login.microsoftonline.com/%s/v2.0" if v2 else "https://sts.windows.net/%s/") % tid
    if claims.get("iss") != want:
        raise fail("Unauthorized. Access token issuer is invalid.")


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
        # RS256 against the issuer's JWKS through the shared verifier (core/gateway_common): needs a discoverable issuer
        # (openid-config url, else the first <issuer>) and a runtime that can verify (not Nano). Otherwise claims-only + warning.
        oc = e.find("openid-config")
        oc_url = (oc.get("url") or "").strip() if oc is not None else ""
        iss0 = oc_url.split("/.well-known/")[0] if oc_url else next(((i.text or "").strip() for i in e.findall("issuers/issuer") if (i.text or "").strip()), "")
        T = _entra()
        if alg == "RS256" and T is not None and hdr.get("kid") == T.kid():
            # a token this simulator's Entra endpoint issued: verified in pure Python against its own key, no network hop to the openid-config URL
            if not T.verify(tok):
                raise fail("Unauthorized. Access token signature is invalid.")
            _entra_issuer_ok(oc_url, claims, fail)
        else:
            verify = _rs256_verifier() if (alg == "RS256" and iss0) else None
            if verify is None:
                ctx.warnings.append("jwt-signature-unverified")
            elif not verify(tok, hdr, {"issuer": iss0}):
                raise fail("Unauthorized. Access token signature is invalid.")
    _check_claims(e, claims, now, fail)


def _check_claims(e, claims, now, fail):
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


def _cond(ctx, text) -> bool:
    v = ctx.value(text)
    if isinstance(v, bool):
        return v
    if isinstance(v, str) and v.strip().lower() in ("true", "false"):
        return v.strip().lower() == "true"
    raise PolicyError(500, f"Condition '{text}' did not evaluate to a boolean.")


def _ip_filter(ctx, e):
    import ipaddress
    try:
        ip = ipaddress.ip_address(ctx.ip)
    except ValueError:
        raise PolicyError(403, "Client IP address is not allowed.")
    hit = False
    for a in e.findall("address"):
        try:
            hit = hit or (ip in ipaddress.ip_network((a.text or "").strip(), strict=False))
        except ValueError:
            pass
    for r in e.findall("address-range"):
        try:
            hit = hit or (ipaddress.ip_address(r.get("from", "")) <= ip <= ipaddress.ip_address(r.get("to", "")))
        except ValueError:
            pass
    if hit != (_a(e, "action", "allow").lower() == "allow"):
        raise PolicyError(403, "Client IP address is not allowed.")


def _aad(ctx, e, now):
    """validate-azure-ad-token: signature (the simulator's Entra key), tenant, client application ids, audiences, required claims."""
    hn = _a(e, "header-name", "Authorization")
    tok = ctx.headers.get(hn.lower(), "")
    if hn.lower() == "authorization":
        tok = tok[7:] if tok.lower().startswith("bearer ") else ""
    fail = lambda msg="Unauthorized. Access token is missing or invalid.": PolicyError(  # noqa: E731
        int(_a(e, "failed-validation-httpcode", "401")), _a(e, "failed-validation-error-message") or msg, {"WWW-Authenticate": 'Bearer error="invalid_token"'})
    T = _entra()
    dec = T.decode(tok) if (tok and T is not None) else None
    if dec is None:
        raise fail()
    hdr, claims = dec
    if hdr.get("alg") != "RS256" or not T.verify(tok):
        raise fail("Unauthorized. Access token signature is invalid.")
    tenant = ctx.expr(_a(e, "tenant-id", ""))
    if tenant and re.fullmatch(r"[0-9a-zA-Z-]{36}", tenant) and tenant.lower() != str(claims.get("tid", "")).lower():
        raise fail("Unauthorized. Access token tenant is invalid.")
    ids = [(i.text or "").strip() for i in e.findall("client-application-ids/application-id")]
    if ids and str(claims.get("azp") or claims.get("appid") or "") not in ids:
        raise fail("Unauthorized. Access token client application is not allowed.")
    _check_claims(e, claims, now, fail)
    if _a(e, "output-token-variable-name"):
        ctx.vars[_a(e, "output-token-variable-name")] = tok


def _mi_token(ctx, e):
    """authentication-managed-identity: attach a bearer token for ``resource`` minted for the service's managed identity (a real RS256 JWT)."""
    T = _entra()
    res = ctx.expr(_a(e, "resource", ""))
    if T is None or not res:
        raise PolicyError(500, "authentication-managed-identity needs a resource.")
    ident = ctx.svc.get("identity") or {}
    oid = ident.get("principalId") or hashlib.sha1(("mi/" + str(ctx.svc.get("id", ""))).encode()).hexdigest()[:8] + "-0000-0000-0000-000000000000"
    tok, _ = T.access_token(tid=ident.get("tenantId") or "00000000-0000-0000-0000-cloudlearn01", v2=False, aud=res, client_id=ident.get("clientId") or oid, oid=oid)
    if _a(e, "output-token-variable-name"):
        ctx.vars[_a(e, "output-token-variable-name")] = tok
    else:
        ctx.headers["authorization"] = "Bearer " + tok


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
            nb = ctx.expr(e.text or "")
            if phase == "outbound" and ctx.out is not None:
                ctx.out["body"] = nb.encode()
                ctx.out["headers"] = {k: v for k, v in ctx.out["headers"].items() if k.lower() != "content-length"}
            else:
                ctx.set_body = nb
                ctx.body = nb.encode()
        elif t == "cors":
            ctx.cors = [(o.text or "").strip() for o in e.findall("allowed-origins/origin")]
        elif t == "forward-request":
            pass
        elif t == "choose":
            for br in e:
                if br.tag == "when":
                    if _cond(ctx, _a(br, "condition", "false")):
                        _run(ctx, list(br), state, bag, now, phase)
                        break
                elif br.tag == "otherwise":
                    _run(ctx, list(br), state, bag, now, phase)
                    break
        elif t == "set-variable":
            ctx.vars[_a(e, "name", "")] = ctx.value(_a(e, "value", e.text or ""))
        elif t == "set-method":
            ctx.method = (e.text or "").strip().upper()
        elif t == "ip-filter":
            _ip_filter(ctx, e)
        elif t == "validate-azure-ad-token":
            _aad(ctx, e, now)
        elif t == "authentication-managed-identity":
            _mi_token(ctx, e)
        else:
            ctx.skipped.append(t)      # not evaluated: listed in x-vyomi-apim-skipped-policies, never silently passed
        if ctx.resp is not None and phase != "outbound":
            return                       # return-response / mock-response ends the section


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
    """Serve one gateway request. ``svc`` is the APIM service record; ``path`` is the gateway path (no query).
    Synchronous: appliance / Mesh / tests (`handle_steps` driven with ``fetch``)."""
    gen = handle_steps(state, svc, method, path, query, headers, body, can_fetch=fetch is not None, now=now, ip=ip, gateway=gateway)
    return gc.drive(gen, (lambda f: fetch(f.method, f.url, f.headers, f.body)) if fetch is not None else (lambda f: None))


async def ahandle(state, svc, method, path, query, headers, body, async_fetch=None, now=None, ip="127.0.0.1", gateway=None):
    """Nano: the same run with the backend hop awaited (``async_fetch(gc.Fetch) -> (status, headers, bytes)``, may raise
    gc.BackendUnavailable). Policies / subscription / rate-limit / quota run once, inside the run, before the hop."""
    gen = handle_steps(state, svc, method, path, query, headers, body, can_fetch=async_fetch is not None, now=now, ip=ip, gateway=gateway)
    return await gc.adrive(gen, async_fetch or (lambda f: None))


def handle_steps(state, svc, method, path, query, headers, body, can_fetch=True, now=None, ip="127.0.0.1", gateway=None):
    """The engine as a resumable run: yields ONE `gc.Fetch` for the backend call and resumes with (status, headers, body)."""
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
    if "mcp" in (str(ap.get("type", "")).lower(), str(ap.get("apiType", "")).lower()):   # ARM `type` (SDK api_type) or the console's `apiType`
        sub = None
        if ap.get("subscriptionRequired", True) is not False:
            sub, err = _auth(state, svc, api, hd.get("ocp-apim-subscription-key") or qd.get("subscription-key") or "")
            if err:
                return done(_body(401, err))
        res = yield from _mcp(state, svc, api, sub, rem, method, qd, hd, body or b"", can_fetch, now, ip, gw)
        return done(res)
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
    ctx.matched, ctx.now = mt, now
    ctx.resp_headers = {}
    ctx.set_body = None
    lv = [_parse(_policy_xml(state, sid)), _parse(_policy_xml(state, api["id"])), _parse(_policy_xml(state, op["id"]))]
    if any(lv[i] is None and _policy_xml(state, rid) for i, rid in enumerate((sid, api["id"], op["id"]))):
        return done(_body(500, "A policy document at this scope is not well-formed XML (attribute values containing quotes must use &quot;)."))
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
            fh = gc.strip_hop(ctx.headers, extra=("ocp-apim-subscription-key",))
            data = ctx.set_body.encode() if ctx.set_body is not None else ctx.body
            if not can_fetch:
                resp = _body(502, "Bad Gateway: the backend cannot be reached from this runtime (no outbound network).")
            else:
                try:
                    st, rh, rb = yield gc.Fetch(method, url, fh, data, 10.0)
                    resp = {"status": st, "headers": gc.strip_resp_hop(rh), "body": rb or b""}
                except Exception as e:  # noqa: BLE001
                    resp = _body(502, f"Bad Gateway: {type(e).__name__}: {e}")
        ctx.resp_headers = resp["headers"]
        ctx.out, ctx.resp = resp, None
        _run(ctx, _compose(lv, "outbound"), state, bag, now, "outbound")
        if ctx.resp is not None:      # return-response in the outbound section replaces the response
            resp = {"status": ctx.resp["status"], "headers": dict(ctx.resp["headers"]), "body": ctx.resp["body"]}
        if ctx.cors is not None:
            origin = hd.get("origin")
            if origin and ("*" in ctx.cors or origin in ctx.cors):
                resp["headers"]["Access-Control-Allow-Origin"] = origin
    except PolicyError as pe:
        resp = _body(pe.status, pe.message, pe.headers)
    skipped.extend(ctx.skipped)
    warns.extend(ctx.warnings)
    return done(resp)


# ── MCP servers (API type "mcp") ─────────────────────────────────────────────────────────────────────────────
MCP_PROTOCOL = "2025-03-26"


def _rpc(id_, result=None, error=None):
    o = {"jsonrpc": "2.0", "id": id_}
    if error is not None:
        o["error"] = error
    else:
        o["result"] = result
    return o


def _json_resp(obj, status=200, headers=None):
    h = {"content-type": "application/json"}
    h.update(headers or {})
    return {"status": status, "headers": h, "body": json.dumps(obj).encode()}


def _mcp_tools(state, svc, api):
    """-> [(tool name, description, source api record, operation record)] for an MCP API: its ``mcpTools`` entries (operationId = an operation resource id or
    name, resolved in the id's own /apis/{api}/ segment, else ``sourceApiId``, else this API), else every operation of ``sourceApiId`` (or of this API)."""
    sid, ap = svc["id"], _props(api)

    def api_rec(name):
        return state.get(f"{sid}/apis/{name}".lower())
    src = str(ap.get("sourceApiId") or "").rstrip("/").rsplit("/", 1)[-1]
    out = []
    if ap.get("mcpTools"):
        for t in ap["mcpTools"]:
            oid = str(t.get("operationId") or t.get("name") or "")
            m = re.search(r"/apis/([^/]+)/operations/([^/]+)$", oid)
            an, on = (m.group(1), m.group(2)) if m else (src or api["name"], oid.rsplit("/", 1)[-1])
            a = api_rec(an)
            op = state.get(f"{a['id']}/operations/{on}".lower()) if a else None
            if op is None:
                continue
            p = _props(op)
            out.append((t.get("name") or on, t.get("description") or p.get("description") or p.get("displayName") or on, a, op))
        return out
    a = api_rec(src) if src else api
    a = a or api
    for op in _recs(state, a["id"] + "/operations", APIM + "/apis/operations"):
        p = _props(op)
        out.append((re.sub(r"[^A-Za-z0-9_-]", "_", op.get("name") or p.get("displayName", "")), p.get("description") or p.get("displayName") or op.get("name"), a, op))
    return out


def _tool_schema(op):
    p = _props(op)
    props, req = {}, []
    for t in re.findall(r"\{([^/}]+)\}", str(p.get("urlTemplate", ""))):
        props[t] = {"type": "string", "description": f"path parameter {t}"}
        req.append(t)
    for tp in p.get("templateParameters") or []:
        props.setdefault(tp.get("name"), {"type": tp.get("type") or "string", "description": tp.get("description") or ""})
    for qp in ((p.get("request") or {}).get("queryParameters") or []):
        props[qp.get("name")] = {"type": qp.get("type") or "string", "description": qp.get("description") or ""}
        if qp.get("required"):
            req.append(qp.get("name"))
    if str(p.get("method", "")).upper() in ("POST", "PUT", "PATCH"):
        props["body"] = {"type": "object", "description": "JSON request body"}
    sch = {"type": "object", "properties": props}
    if req:
        sch["required"] = sorted(set(req))
    return sch


def _mcp(state, svc, api, sub, rem, method, qd, hd, body, can_fetch, now, ip, gw):
    """Serve the MCP streamable-HTTP endpoint of an API with type=mcp: JSON-RPC ``initialize`` / ``ping`` / ``tools/list`` / ``tools/call``.
    The MCP API's own (and the service-level) inbound policies run first (validate-jwt, rate-limit, ...); a ``tools/call`` is dispatched as an ordinary
    gateway request to the source operation, so that operation's API/operation policies and backend apply. An MCP API with a serviceUrl and no tools is a
    pass-through to a backend MCP server (the JSON-RPC body is forwarded unchanged)."""
    ap = _props(api)
    if rem.rstrip("/") not in ("", "/mcp", "mcp"):
        return _body(404, "Resource not found")
    ctx = _Ctx(svc, api, None, sub, method, rem, {k: v for k, v in qd.items() if k != "subscription-key"}, dict(hd), body, ip)
    ctx.now = now
    lv = [_parse(_policy_xml(state, svc["id"])), _parse(_policy_xml(state, api["id"]))]
    if any(lv[i] is None and _policy_xml(state, rid) for i, rid in enumerate((svc["id"], api["id"]))):
        return _body(500, "A policy document at this scope is not well-formed XML (attribute values containing quotes must use &quot;).")
    try:
        _run(ctx, _compose(lv, "inbound"), state, gw["rl"], now, "inbound")
    except PolicyError as pe:
        return _body(pe.status, pe.message, pe.headers)
    if ctx.resp is not None:
        return {"status": ctx.resp["status"], "headers": dict(ctx.resp["headers"]), "body": ctx.resp["body"]}
    if method == "GET":
        return _body(405, "This MCP server does not offer a server-initiated SSE stream; POST JSON-RPC to the endpoint.", {"Allow": "POST, DELETE"})
    if method == "DELETE":
        return {"status": 200, "headers": {}, "body": b""}
    if method != "POST":
        return _body(405, "Method not allowed.", {"Allow": "POST"})
    try:
        req = json.loads(body.decode("utf-8") or "null")
    except ValueError:
        return _json_resp(_rpc(None, error={"code": -32700, "message": "Parse error"}), 400)
    tools = _mcp_tools(state, svc, api)
    if not tools and ap.get("serviceUrl") and can_fetch and not ap.get("mcpTools"):
        url = ap["serviceUrl"].rstrip("/") + ("/mcp" if rem.rstrip("/") in ("/mcp", "mcp") else "")
        try:
            st, rh, rb = yield gc.Fetch("POST", url, gc.strip_hop(ctx.headers, extra=("ocp-apim-subscription-key",)), body, 15.0)
            return {"status": st, "headers": gc.strip_resp_hop(rh), "body": rb or b""}
        except Exception as e:  # noqa: BLE001
            return _body(502, f"Bad Gateway: {type(e).__name__}: {e}")
    batch = isinstance(req, list)
    outs = []
    for r in (req if batch else [req]):
        o = yield from _mcp_one(state, svc, api, tools, r, ctx, can_fetch, now, ip)
        if o is not None:
            outs.append(o)
    if not outs:
        return {"status": 202, "headers": {}, "body": b""}
    return _json_resp(outs if batch else outs[0])


def _mcp_one(state, svc, api, tools, r, ctx, can_fetch, now, ip):
    if not isinstance(r, dict) or r.get("jsonrpc") != "2.0" or "method" not in r:
        return _rpc(r.get("id") if isinstance(r, dict) else None, error={"code": -32600, "message": "Invalid Request"})
    mid, m, prm = r.get("id"), r["method"], r.get("params") or {}
    if "id" not in r:                       # a notification: no response
        return None
    if m == "initialize":
        return _rpc(mid, {"protocolVersion": prm.get("protocolVersion") or MCP_PROTOCOL, "capabilities": {"tools": {"listChanged": False}},
                          "serverInfo": {"name": _props(api).get("displayName") or api["name"], "version": "1.0.0"}})
    if m == "ping":
        return _rpc(mid, {})
    if m == "tools/list":
        return _rpc(mid, {"tools": [{"name": n, "description": d, "inputSchema": _tool_schema(op)} for n, d, a, op in tools]})
    if m == "tools/call":
        name, args = prm.get("name"), dict(prm.get("arguments") or {})
        t = next((x for x in tools if x[0] == name), None)
        if t is None:
            return _rpc(mid, error={"code": -32602, "message": f"Unknown tool: {name}"})
        sapi, op = t[2], t[3]
        p = _props(op)
        tpl = str(p.get("urlTemplate", "")).split("?", 1)[0]
        missing = [x for x in re.findall(r"\{([^/}]+)\}", tpl) if x not in args]
        if missing:
            return _rpc(mid, error={"code": -32602, "message": f"Missing required argument(s): {', '.join(missing)}"})
        path_ = re.sub(r"\{([^/}]+)\}", lambda mm: str(args.pop(mm.group(1))), tpl)
        pre = "/" + str(_props(sapi).get("path", "")).strip("/")
        mth = str(p.get("method", "GET")).upper()
        bdata = b""
        if mth in ("POST", "PUT", "PATCH"):
            b = args.pop("body", None)
            if b is None and args:
                b, args = dict(args), {}
            bdata = (b if isinstance(b, str) else json.dumps(b)).encode() if b is not None else b""
        fh = {k: v for k, v in ctx.headers.items() if k in ("ocp-apim-subscription-key", "authorization", "x-forwarded-for")}
        if bdata:
            fh["content-type"] = "application/json"
        res = yield from handle_steps(state, svc, mth, (pre if pre != "/" else "") + path_, {k: str(v) for k, v in args.items()}, fh, bdata,
                                      can_fetch=can_fetch, now=now, ip=ip)
        text = (res.get("body") or b"").decode("utf-8", "replace")
        return _rpc(mid, {"content": [{"type": "text", "text": text}], "isError": res["status"] >= 400})
    return _rpc(mid, error={"code": -32601, "message": f"Method not found: {m}"})


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
