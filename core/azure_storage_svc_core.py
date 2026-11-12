"""Azure Storage Queue / Table SERVICE properties, enforced by the data plane (Set/Get Queue|Table Service Properties,
Get Service Stats, CORS preflight, request logging, metrics, retention).  Substrate-free (stdlib only).

  GET/PUT  /?restype=service&comp=properties   StorageServiceProperties XML (Logging, HourMetrics, MinuteMetrics, Cors)
  GET      /?restype=service&comp=stats        GeoReplication (primary only)
  OPTIONS  any path with Origin + Access-Control-Request-Method    CORS preflight evaluated against the rules (200 + ACAO headers or 403)
  any      request carrying Origin                                  gets Access-Control-Allow-Origin/Expose-Headers when a rule matches
  GET      /?restype=service&comp=vyomi-logs | vyomi-metrics        the recorded request log / metrics ring (Vyomi extension: real Azure
                                                                    writes these to the $logs blob container / $Metrics tables)

The properties live in the ARM storage-account record (`_queueServices` / `_tableServices`, the same place the ARM
queueServices/default | tableServices/default CORS PUT writes), so ARM and data plane share one source of truth.  Every request
through the wrapped data plane is counted (HourMetrics/MinuteMetrics, API-level when `includeAPIs`) and, per the Logging
flags, logged (read / write / delete by operation class); entries older than the RetentionPolicy days are purged.

HONEST LIMITS: the account is resolved from a leading `/{account}` path segment, `x-vyomi-account`, the
`<account>.queue|table.core.windows.net` host, or the only storage account.  Queue vs Table vs Blob service-root requests are
indistinguishable on the wire without a distinct host, so the router needs the host or `x-vyomi-service: queue|table`.
Metrics/logs are kept in a bounded in-memory ring on the account record, not as blobs/tables.  Offline (wire_ingress) wiring of
this wrapper is not done: the enforcement is on the Nano router.
"""
from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

RING = 2000
KINDS = {"queue": "_queueServices", "table": "_tableServices"}


@dataclass
class Resp:
    status: int = 200
    headers: dict = field(default_factory=dict)
    body: bytes = b""
    media_type: str | None = "application/xml"


def default_props():
    return {"cors": {"corsRules": []},
            "logging": {"version": "1.0", "read": False, "write": False, "delete": False, "retentionDays": None},
            "hourMetrics": {"version": "1.0", "enabled": False, "includeAPIs": False, "retentionDays": None},
            "minuteMetrics": {"version": "1.0", "enabled": False, "includeAPIs": False, "retentionDays": None}}


def _accounts(arm_state):
    return [r for r in (arm_state or {}).values() if str(r.get("_type") or "").lower() == "microsoft.storage/storageaccounts"]


def resolve_account(arm_state, path, headers):
    accts = _accounts(arm_state)
    hd = {(k or "").lower(): v for k, v in (headers or {}).items()}
    want = str(hd.get("x-vyomi-account") or "").lower()
    if not want:
        host = str(hd.get("host") or "").split(":")[0].lower()
        m = re.match(r"^([a-z0-9]+)\.(queue|table)\.core\.windows\.net$", host)
        if m:
            want = m.group(1)
    if not want:
        segs = [s for s in path.split("?", 1)[0].split("/") if s]
        if segs:
            want = segs[0].lower()
    for a in accts:
        if (a.get("name") or "").lower() == want:
            return a
    return accts[0] if len(accts) == 1 and not want else None


def props_of(acct, kind, fallback_store=None):
    holder = acct if acct is not None else (fallback_store.__dict__ if fallback_store is not None else {})
    slot = holder.setdefault(KINDS[kind], {})
    base = default_props()
    for k, v in base.items():
        slot.setdefault(k, v)
    slot.setdefault("_log", [])
    slot.setdefault("_metrics", [])
    return slot


# ── XML ──
def _b(v):
    return "true" if v else "false"


def to_xml(p):
    def pol(d):
        return (f"<RetentionPolicy><Enabled>{_b(d.get('retentionDays'))}</Enabled>" + (f"<Days>{d['retentionDays']}</Days>" if d.get("retentionDays") else "") + "</RetentionPolicy>")

    def met(tag, d):
        return (f"<{tag}><Version>{d['version']}</Version><Enabled>{_b(d['enabled'])}</Enabled>"
                + (f"<IncludeAPIs>{_b(d['includeAPIs'])}</IncludeAPIs>" if d["enabled"] else "") + pol(d) + f"</{tag}>")
    lg = p["logging"]
    cors = "".join("<CorsRule><AllowedOrigins>{}</AllowedOrigins><AllowedMethods>{}</AllowedMethods><MaxAgeInSeconds>{}</MaxAgeInSeconds>"
                   "<ExposedHeaders>{}</ExposedHeaders><AllowedHeaders>{}</AllowedHeaders></CorsRule>".format(
                       ",".join(r.get("allowedOrigins", [])), ",".join(r.get("allowedMethods", [])), r.get("maxAgeInSeconds", 0),
                       ",".join(r.get("exposedHeaders", [])), ",".join(r.get("allowedHeaders", []))) for r in p["cors"]["corsRules"])
    return ('<?xml version="1.0" encoding="utf-8"?><StorageServiceProperties>'
            f"<Logging><Version>{lg['version']}</Version><Read>{_b(lg['read'])}</Read><Write>{_b(lg['write'])}</Write><Delete>{_b(lg['delete'])}</Delete>"
            + pol(lg) + "</Logging>" + met("HourMetrics", p["hourMetrics"]) + met("MinuteMetrics", p["minuteMetrics"])
            + f"<Cors>{cors}</Cors></StorageServiceProperties>").encode()


def from_xml(body, p):
    """Apply a StorageServiceProperties document onto `p` (elements that are absent are left unchanged, as in Azure)."""
    root = ET.fromstring(body)
    ns = lambda e: e.tag.split("}")[-1]
    kids = {ns(c): c for c in root}
    txt = lambda e, t: next((c.text for c in e if ns(c) == t), None)
    boolv = lambda s: str(s).strip().lower() == "true"

    def days(e):
        pol = next((c for c in e if ns(c) == "RetentionPolicy"), None)
        if pol is None:
            return None
        if boolv(txt(pol, "Enabled")):
            d = txt(pol, "Days")
            if d is None or not d.isdigit() or not 1 <= int(d) <= 365:
                raise ValueError("RetentionPolicy Days must be between 1 and 365 when the policy is enabled.")
            return int(d)
        return None
    if "Logging" in kids:
        e = kids["Logging"]
        p["logging"] = {"version": txt(e, "Version") or "1.0", "read": boolv(txt(e, "Read")), "write": boolv(txt(e, "Write")),
                        "delete": boolv(txt(e, "Delete")), "retentionDays": days(e)}
    for tag, key in (("HourMetrics", "hourMetrics"), ("MinuteMetrics", "minuteMetrics")):
        if tag in kids:
            e = kids[tag]
            en = boolv(txt(e, "Enabled"))
            if en and txt(e, "IncludeAPIs") is None:
                raise ValueError(f"{tag}: IncludeAPIs is required when Enabled is true.")
            p[key] = {"version": txt(e, "Version") or "1.0", "enabled": en, "includeAPIs": boolv(txt(e, "IncludeAPIs")), "retentionDays": days(e)}
    if "Cors" in kids:
        rules = []
        for r in kids["Cors"]:
            sp = lambda t: [x.strip() for x in (txt(r, t) or "").split(",") if x.strip()]
            rules.append({"allowedOrigins": sp("AllowedOrigins"), "allowedMethods": sp("AllowedMethods"), "maxAgeInSeconds": int(txt(r, "MaxAgeInSeconds") or 0),
                          "exposedHeaders": sp("ExposedHeaders"), "allowedHeaders": sp("AllowedHeaders")})
        if len(rules) > 5:
            raise ValueError("A maximum of 5 CORS rules can be specified.")
        for r in rules:
            if not r["allowedOrigins"] or not r["allowedMethods"]:
                raise ValueError("A CORS rule needs AllowedOrigins and AllowedMethods.")
        p["cors"] = {"corsRules": rules}


# ── CORS ──
def _match(patterns, value):
    return any(p == "*" or p.lower() == value.lower() or (p.endswith("*") and value.lower().startswith(p[:-1].lower())) for p in patterns)


def cors_rule(p, origin, method, req_headers=()):
    for r in p["cors"]["corsRules"]:
        if _match(r["allowedOrigins"], origin) and method.upper() in [m.upper() for m in r["allowedMethods"]] \
                and all(_match(r["allowedHeaders"], h) for h in req_headers if h):
            return r
    return None


def cors_headers(rule, origin):
    h = {"Access-Control-Allow-Origin": "*" if "*" in rule["allowedOrigins"] else origin, "Vary": "Origin"}
    if rule.get("exposedHeaders"):
        h["Access-Control-Expose-Headers"] = ",".join(rule["exposedHeaders"])
    return h


# ── metrics / logging ──
def _op_class(method):
    m = method.upper()
    return "delete" if m == "DELETE" else "read" if m in ("GET", "HEAD") else "write"


def record(p, kind, method, path, status, now=None):
    now = now if now is not None else time.time()
    cls = _op_class(method)
    api = f"{method.upper()} {re.sub(r'/[^/]+$', '/{id}', path.split('?')[0]) if path.count('/') > 2 else path.split('?')[0]}"
    lg = p["logging"]
    if lg.get(cls):
        p["_log"].append({"ts": now, "operation": cls, "request": f"{method.upper()} {path.split('?')[0]}", "status": status})
        del p["_log"][:-RING]
    for key, bucket in (("hourMetrics", 3600), ("minuteMetrics", 60)):
        m = p[key]
        if not m["enabled"]:
            continue
        start = int(now // bucket) * bucket
        row = next((r for r in p["_metrics"] if r["interval"] == key and r["start"] == start and r.get("api") is None), None)
        if row is None:
            row = {"interval": key, "start": start, "api": None, "TotalRequests": 0, "Success": 0, "ClientErrors": 0, "ServerErrors": 0}
            p["_metrics"].append(row)
        _bump(row, status)
        if m["includeAPIs"]:
            ar = next((r for r in p["_metrics"] if r["interval"] == key and r["start"] == start and r.get("api") == api), None)
            if ar is None:
                ar = {"interval": key, "start": start, "api": api, "TotalRequests": 0, "Success": 0, "ClientErrors": 0, "ServerErrors": 0}
                p["_metrics"].append(ar)
            _bump(ar, status)
    del p["_metrics"][:-RING]
    purge(p, now)


def _bump(row, status):
    row["TotalRequests"] += 1
    row["Success" if status < 400 else "ClientErrors" if status < 500 else "ServerErrors"] += 1


def purge(p, now=None):
    now = now if now is not None else time.time()
    d = p["logging"].get("retentionDays")
    if d:
        p["_log"][:] = [e for e in p["_log"] if e["ts"] >= now - d * 86400]
    for key in ("hourMetrics", "minuteMetrics"):
        d = p[key].get("retentionDays")
        if d:
            p["_metrics"][:] = [r for r in p["_metrics"] if r["interval"] != key or r["start"] >= now - d * 86400]


# ── wrapper ──
def serve(kind, mod, store, method, path, query, headers, body, arm_state=None, now=None):
    """Wrap a Queue/Table data-plane dispatch with service properties, CORS, logging and metrics."""
    query = query or {}
    hd = {(k or "").lower(): v for k, v in (headers or {}).items()}
    acct = resolve_account(arm_state, path, hd)
    p = props_of(acct, kind, store)
    method_u = method.upper()
    origin = hd.get("origin")
    if query.get("restype") == "service" and not [s for s in path.split("?")[0].split("/") if s][1:]:
        comp = query.get("comp")
        if comp == "properties" and method_u == "GET":
            return Resp(200, {"x-ms-version": "2021-08-06"}, to_xml(p))
        if comp == "properties" and method_u == "PUT":
            try:
                from_xml(body, p)
            except (ET.ParseError, ValueError) as e:
                return Resp(400, {"x-ms-error-code": "InvalidXmlDocument"}, f'<?xml version="1.0"?><Error><Code>InvalidXmlDocument</Code><Message>{e}</Message></Error>'.encode())
            purge(p, now)
            return Resp(202, {"x-ms-version": "2021-08-06"}, b"", None)
        if comp == "stats" and method_u == "GET":
            return Resp(200, {}, b'<?xml version="1.0"?><StorageServiceStats><GeoReplication><Status>unavailable</Status><LastSyncTime /></GeoReplication></StorageServiceStats>')
        if comp in ("vyomi-logs", "vyomi-metrics") and method_u == "GET":
            import json
            data = p["_log"] if comp == "vyomi-logs" else p["_metrics"]
            return Resp(200, {}, json.dumps({"value": data}).encode(), "application/json")
    if method_u == "OPTIONS":
        rm = hd.get("access-control-request-method")
        if not origin or not rm:
            r = Resp(400, {"x-ms-error-code": "MissingRequiredHeader"}, b"", None)
        else:
            rule = cors_rule(p, origin, rm, [h.strip() for h in (hd.get("access-control-request-headers") or "").split(",")])
            if rule is None:
                r = Resp(403, {"x-ms-error-code": "CorsPreflightFailure"},
                         b'<?xml version="1.0"?><Error><Code>CorsPreflightFailure</Code><Message>CORS not enabled or no matching rule found for this request.</Message></Error>')
            else:
                h = cors_headers(rule, origin)
                h["Access-Control-Allow-Methods"] = ",".join(rule["allowedMethods"])
                h["Access-Control-Max-Age"] = str(rule["maxAgeInSeconds"])
                if hd.get("access-control-request-headers"):
                    h["Access-Control-Allow-Headers"] = hd["access-control-request-headers"]
                r = Resp(200, h, b"", None)
        record(p, kind, method, path, r.status, now)
        return r
    r = mod.dispatch(store, method, path, query, headers or {}, body)
    if origin:
        rule = cors_rule(p, origin, method_u)
        if rule is not None:
            r.headers = {**(r.headers or {}), **cors_headers(rule, origin)}
    record(p, kind, method, path, r.status, now)
    return r
