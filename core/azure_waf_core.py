"""Azure WAF policy CUSTOM-RULE evaluation (substrate-free, pure Python; Pyodide-loadable).

The WAF policy resources themselves are plain ARM CRUD (``Microsoft.Network/FrontDoorWebApplicationFirewallPolicies``,
``Microsoft.Network/ApplicationGatewayWebApplicationFirewallPolicies``, ``Microsoft.Cdn/cdnWebApplicationFirewallPolicies``; see
core/azure_arm_data.py). This module evaluates the policy's ``customRules`` against one request on the gateway path the simulator serves
(the APIM gateway, core/azure_apim_gateway_core.py), in priority order, with the real semantics:

* Front Door shape ``properties.customRules.rules[]`` (``matchConditions[].matchVariable/selector/operator/negateCondition/matchValue``) and the Application Gateway
  shape ``properties.customRules[]`` (``matchConditions[].matchVariables[]/operator/negationConditon/matchValues``) are both read;
* ``ruleType`` MatchRule (all conditions must match) and RateLimitRule (``rateLimitThreshold`` per ``rateLimitDurationInMinutes`` per client IP);
* variables RemoteAddr, SocketAddr, RequestMethod, QueryString, RequestUri, RequestHeader(s), RequestBody, PostArgs, Cookies;
  operators Any, IPMatch (address / CIDR), Equal, Contains, BeginsWith, EndsWith, RegEx, LessThan, GreaterThan, LessThanOrEqual, GreaterThanOrEqual, Wildcard;
  transforms Lowercase, Uppercase, Trim, UrlDecode;
* actions Allow (stop, request passes), Block (403 or the policy's customBlockResponseStatusCode/Body), Log (continue, recorded), Redirect (302);
  AnomalyScoring/JSChallenge/CAPTCHA are treated as Log (no managed-rule scoring or challenge engine);
* mode Detection records a would-be block as ``logged`` and lets the request through; ``enabledState/state`` Disabled skips the policy.

Managed rule sets (OWASP / Microsoft_DefaultRuleSet / bot manager) are stored only: there is no managed-rule engine.
"""
from __future__ import annotations

import base64
import ipaddress
import re
from urllib.parse import unquote


def _settings(props):
    ps = props.get("policySettings") or {}
    state = str(ps.get("enabledState") or ps.get("state") or "Enabled").lower()
    return state == "enabled", str(ps.get("mode") or "Prevention").lower(), ps


def _rules(props):
    cr = props.get("customRules") or []
    if isinstance(cr, dict):
        cr = cr.get("rules") or []
    out = []
    for r in cr:
        if str(r.get("enabledState") or r.get("state") or "Enabled").lower() != "enabled":
            continue
        out.append(r)
    return sorted(out, key=lambda r: int(r.get("priority", 100)))


def _values(var, sel, ctx):
    v = str(var or "").lower()
    q = ctx["query"]
    if v == "remoteaddr" or v == "socketaddr":
        return [ctx["ip"]]
    if v == "requestmethod":
        return [ctx["method"]]
    if v == "querystring":
        return ["&".join(f"{k}={x}" for k, x in q.items())]
    if v == "requesturi":
        return [ctx["path"] + (("?" + "&".join(f"{k}={x}" for k, x in q.items())) if q else "")]
    if v in ("requestheader", "requestheaders"):
        h = ctx["headers"]
        return [h[sel.lower()]] if sel and sel.lower() in h else ([] if sel else list(h.values()))
    if v == "requestbody":
        return [ctx["body"].decode("utf-8", "replace")]
    if v == "postargs":
        from urllib.parse import parse_qs
        pa = {k: x[0] for k, x in parse_qs(ctx["body"].decode("utf-8", "replace")).items()}
        return [pa[sel]] if sel and sel in pa else ([] if sel else list(pa.values()))
    if v == "cookies":
        ck = {}
        for part in ctx["headers"].get("cookie", "").split(";"):
            if "=" in part:
                a, _, b = part.strip().partition("=")
                ck[a] = b
        return [ck[sel]] if sel and sel in ck else ([] if sel else list(ck.values()))
    return []


def _tx(val, transforms):
    for t in transforms or []:
        t = str(t).lower()
        val = val.lower() if t == "lowercase" else val.upper() if t == "uppercase" else val.strip() if t == "trim" else unquote(val) if t == "urldecode" else val
    return val


def _op(op, val, matches):
    op = str(op or "").lower()
    if op == "any":
        return True
    for m in matches:
        m = str(m)
        if op == "ipmatch":
            try:
                if ipaddress.ip_address(val) in ipaddress.ip_network(m, strict=False):
                    return True
            except ValueError:
                pass
        elif op == "equal" and val == m:
            return True
        elif op == "contains" and m in val:
            return True
        elif op == "beginswith" and val.startswith(m):
            return True
        elif op == "endswith" and val.endswith(m):
            return True
        elif op == "regex":
            try:
                if re.search(m, val):
                    return True
            except re.error:
                pass
        elif op == "wildcard" and re.fullmatch(".*".join(re.escape(p) for p in m.split("*")), val):
            return True
        elif op in ("lessthan", "greaterthan", "lessthanorequal", "greaterthanorequal"):
            try:
                a, b = float(val), float(m)
                if {"lessthan": a < b, "greaterthan": a > b, "lessthanorequal": a <= b, "greaterthanorequal": a >= b}[op]:
                    return True
            except ValueError:
                pass
    return False


def _cond(c, ctx):
    neg = bool(c.get("negateCondition") or c.get("negationConditon") or c.get("negationCondition"))
    matches = c.get("matchValue") or c.get("matchValues") or []
    vars_ = c.get("matchVariables") or [{"variableName": c.get("matchVariable"), "selector": c.get("selector")}]
    hit = False
    for mv in vars_:
        name = mv.get("variableName") or mv.get("matchVariable")
        for val in _values(name, mv.get("selector"), ctx) or ([] if str(c.get("operator", "")).lower() != "any" else [""]):
            if _op(c.get("operator"), _tx(val, c.get("transforms")), matches):
                hit = True
    return hit != neg


def evaluate(policy, method, path, query, headers, body, ip, now, bag):
    """-> None (no policy effect) or a dict {"action": "allow"|"block"|"log"|"redirect", "rule": name, "status": int, "body": str, "logged": bool}.
    ``policy`` is the ARM record; ``bag`` a dict that keeps the rate-limit windows."""
    props = (policy or {}).get("properties") or {}
    enabled, mode, ps = _settings(props)
    if not enabled:
        return None
    ctx = {"method": method.upper(), "path": path, "query": query or {}, "headers": {str(k).lower(): str(v) for k, v in (headers or {}).items()},
           "body": body or b"", "ip": ip}
    for r in _rules(props):
        conds = r.get("matchConditions") or []
        if not conds or not all(_cond(c, ctx) for c in conds):
            continue
        if str(r.get("ruleType", "MatchRule")).lower() == "ratelimitrule":
            win = max(1, int(r.get("rateLimitDurationInMinutes") or 1)) * 60
            thr = int(r.get("rateLimitThreshold") or 0)
            k = f"{policy.get('name','')}/{r.get('name','')}/{ip}"
            hits = [t for t in bag.get(k, []) if now - t < win]
            hits.append(now)
            bag[k] = hits
            if len(hits) <= thr:
                continue
        act = str(r.get("action") or "Block").lower()
        if act == "allow":
            return {"action": "allow", "rule": r.get("name"), "status": 200, "body": "", "logged": False}
        if act in ("log", "anomalyscoring", "jschallenge", "captcha"):
            ctx.setdefault("_log", []).append(r.get("name"))
            continue
        status = 302 if act == "redirect" else int(ps.get("customBlockResponseStatusCode") or 403)
        body_ = ps.get("customBlockResponseBody")
        try:
            body_ = base64.b64decode(body_).decode() if body_ else ""
        except Exception:
            body_ = str(body_ or "")
        if mode == "detection":
            return {"action": "log", "rule": r.get("name"), "status": status, "body": "", "logged": True}
        return {"action": "redirect" if act == "redirect" else "block", "rule": r.get("name"), "status": status,
                "body": body_ or "The request is blocked.", "logged": False, "redirect": (r.get("redirectUrl") or "")}
    return None
