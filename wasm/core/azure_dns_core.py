"""Azure DNS core (``Microsoft.Network/dnsZones`` — public and private-typed zones, record sets).

Substrate-free (no fastapi / sockets / subprocess) so the SAME file runs offline and in Nano.

ARM REST of the ``dns`` resource provider (azure-rest-api-specs ``specification/dns/resource-manager``,
api-version 2018-05-01), so ``azure-mgmt-dns`` / ``armdns`` / ``com.azure.resourcemanager.dns`` and
``az network dns zone|record-set|record-set a|aaaa|cname|mx|ns|ptr|srv|txt|caa …`` work unchanged:

    Microsoft.Network/dnsZones                       (CreateOrUpdate / Update / Delete / Get / List*)
    Microsoft.Network/dnsZones/{A|AAAA|CAA|CNAME|DS|MX|NAPTR|NS|PTR|SOA|SRV|TLSA|TXT}/{relativeName}
    Microsoft.Network/dnsZones/{type}                (ListByType)     .../recordsets  .../all
    Microsoft.Network/getDnsResourceReference        (POST, subscription scope)

Record sets live INSIDE the zone's ARM record (underscore key ``_rs``, never serialised to ARM clients),
so they are space-scoped and persisted by the same seams as the rest of ARM (offline
``azure_arm_state``; Nano ``az_arm``). ``resolve`` answers a DNS question from those record sets
(the offline appliance exposes it as ``/azure-data/dns/query`` and the console's Test query).

``dispatch`` returns ``{"status","headers","body","lro","rid","verb"}`` (``body`` is a JSON-able object
or ``None``). Conditional headers (If-Match / If-None-Match) are not modelled.
"""
from __future__ import annotations

import hashlib
import ipaddress
import re
import uuid
from datetime import datetime, timezone
from urllib.parse import quote

NAMESPACE = "Microsoft.Network"
ZONE_TYPE = "dnszones"                       # ARM reports the type lower-cased: Microsoft.Network/dnszones
API_VERSION = "2018-05-01"
DEFAULT_LOCATION = "global"
RECORD_TYPES = ("A", "AAAA", "CAA", "CNAME", "DS", "MX", "NAPTR", "NS", "PTR", "SOA", "SRV", "TLSA", "TXT")
# record type → ARM property holding its records
FIELDS = {"A": "ARecords", "AAAA": "AAAARecords", "CAA": "caaRecords", "CNAME": "CNAMERecord", "DS": "DSRecords",
          "MX": "MXRecords", "NAPTR": "NAPTRRecords", "NS": "NSRecords", "PTR": "PTRRecords", "SOA": "SOARecord",
          "SRV": "SRVRecords", "TLSA": "TLSARecords", "TXT": "TXTRecords"}
MAX_RECORD_SETS = 10000
MAX_RECORDS_PER_SET = 20
DEFAULT_TTL = 3600
NS_TTL = 172800
SOA_DEFAULTS = {"email": "azuredns-hostmaster.microsoft.com", "serialNumber": 1, "refreshTime": 3600,
                "retryTime": 300, "expireTime": 2419200, "minimumTTL": 300}


class _E(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _ok(body=None, status=200, headers=None, lro=False, rid="", verb=""):
    return {"status": status, "headers": headers or {}, "body": body, "lro": lro, "rid": rid, "verb": verb}


def _err(status, code, message):
    return {"status": status, "headers": {}, "body": {"error": {"code": code, "message": message}},
            "lro": False, "rid": "", "verb": ""}


def _etag():
    return str(uuid.uuid4())


def _view(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def _to_int(v, default=None):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _zone_rid(sub, rg, name):
    return f"/subscriptions/{sub}/resourceGroups/{rg}/providers/{NAMESPACE}/{ZONE_TYPE}/{name}"


def _not_found(name, rg):
    return _E(404, "ResourceNotFound",
              f"The Resource '{NAMESPACE}/dnszones/{name}' under resource group '{rg}' was not found. "
              "For more details please go to https://aka.ms/ARMResourceNotFoundFix")


def _zones(state):
    return [r for r in state.values() if str(r.get("_type", "")).lower() == f"{NAMESPACE}/{ZONE_TYPE}".lower()]


# ═══════════════════════════ names ═══════════════════════════════════════════════
_LABEL = re.compile(r"^[a-z0-9_]([a-z0-9_-]{0,61}[a-z0-9_])?$|^\*$")


def _zone_name_problem(name):
    n = (name or "").rstrip(".").lower()
    labels = n.split(".")
    if not n or len(n) > 253 or not 2 <= len(labels) <= 34 or any(not re.fullmatch(r"[a-z0-9_]([a-z0-9_-]{0,61}[a-z0-9_])?", l) for l in labels):
        return (f"The zone name '{name}' is invalid. A zone name must have 2 to 34 labels of letters, digits, "
                "underscores and hyphens, each at most 63 characters, and at most 253 characters in total.")
    return None


def _rel_name_problem(rel, zone):
    if rel == "@":
        return None
    labels = rel.rstrip(".").split(".")
    if not rel or any(not _LABEL.match(l.lower()) for l in labels):
        return f"The record set name '{rel}' is invalid."
    if len(rel) + 1 + len(zone) > 253:
        return f"The record set name '{rel}' is too long for zone '{zone}'."
    return None


def _fqdn(rel, zone):
    return (zone if rel == "@" else f"{rel}.{zone}").lower().rstrip(".") + "."


def _name_servers(rid):
    n = int(hashlib.sha1(rid.lower().encode()).hexdigest()[:4], 16) % 9 + 1
    return [f"ns1-0{n}.azure-dns.com.", f"ns2-0{n}.azure-dns.net.", f"ns3-0{n}.azure-dns.org.", f"ns4-0{n}.azure-dns.info."]


# ═══════════════════════════ records ═════════════════════════════════════════════
def _need(d, field, what):
    v = d.get(field) if isinstance(d, dict) else None
    if v is None or v == "":
        raise _E(400, "BadRequest", f"The {what} record is missing the required property '{field}'.")
    return v


def _rec_int(d, field, what, lo, hi):
    v = _to_int(_need(d, field, what))
    if v is None or not lo <= v <= hi:
        raise _E(400, "BadRequest", f"The {what} record property '{field}' must be an integer between {lo} and {hi}.")
    return v


def _host(v, what, field):
    s = str(v).strip()
    if not s or len(s.rstrip(".")) > 253:
        raise _E(400, "BadRequest", f"The {what} record property '{field}' is not a valid domain name.")
    return s


def _norm_record(rtype, rec):
    """Validate one record of ``rtype`` and return its canonical ARM shape."""
    if not isinstance(rec, dict):
        raise _E(400, "BadRequest", f"Invalid {rtype} record.")
    if rtype == "A":
        ip = str(_need(rec, "ipv4Address", "A")).strip()
        try:
            ipaddress.IPv4Address(ip)
        except ValueError:
            raise _E(400, "BadRequest", f"'{ip}' is not a valid IPv4 address.") from None
        return {"ipv4Address": ip}
    if rtype == "AAAA":
        ip = str(_need(rec, "ipv6Address", "AAAA")).strip()
        try:
            ip = str(ipaddress.IPv6Address(ip))
        except ValueError:
            raise _E(400, "BadRequest", f"'{ip}' is not a valid IPv6 address.") from None
        return {"ipv6Address": ip}
    if rtype == "CNAME":
        return {"cname": _host(_need(rec, "cname", "CNAME"), "CNAME", "cname")}
    if rtype == "NS":
        return {"nsdname": _host(_need(rec, "nsdname", "NS"), "NS", "nsdname")}
    if rtype == "PTR":
        return {"ptrdname": _host(_need(rec, "ptrdname", "PTR"), "PTR", "ptrdname")}
    if rtype == "MX":
        return {"preference": _rec_int(rec, "preference", "MX", 0, 65535), "exchange": _host(_need(rec, "exchange", "MX"), "MX", "exchange")}
    if rtype == "SRV":
        return {"priority": _rec_int(rec, "priority", "SRV", 0, 65535), "weight": _rec_int(rec, "weight", "SRV", 0, 65535),
                "port": _rec_int(rec, "port", "SRV", 0, 65535), "target": _host(_need(rec, "target", "SRV"), "SRV", "target")}
    if rtype == "TXT":
        vals = rec.get("value")
        if isinstance(vals, str):
            vals = [vals]
        if not isinstance(vals, list) or not vals or any(not isinstance(x, str) for x in vals):
            raise _E(400, "BadRequest", "The TXT record property 'value' must be a non-empty list of strings.")
        if any(len(x) > 255 for x in vals):
            raise _E(400, "BadRequest", "Each string of a TXT record can be at most 255 characters; split longer values into several strings.")
        return {"value": list(vals)}
    if rtype == "CAA":
        tag = str(_need(rec, "tag", "CAA"))
        if tag.lower() not in ("issue", "issuewild", "iodef"):
            raise _E(400, "BadRequest", "The CAA record property 'tag' must be one of issue, issuewild, iodef.")
        return {"flags": _rec_int(rec, "flags", "CAA", 0, 255), "tag": tag, "value": str(_need(rec, "value", "CAA"))}
    if rtype == "SOA":
        out = {"host": _host(_need(rec, "host", "SOA"), "SOA", "host"), "email": str(rec.get("email") or SOA_DEFAULTS["email"])}
        for f in ("serialNumber", "refreshTime", "retryTime", "expireTime", "minimumTTL"):
            out[f] = _rec_int({f: rec.get(f, SOA_DEFAULTS[f])}, f, "SOA", 0, 4294967295)
        return out
    if rtype == "DS":
        return {"keyTag": _rec_int(rec, "keyTag", "DS", 0, 65535), "algorithm": _rec_int(rec, "algorithm", "DS", 0, 255),
                "digest": {"algorithmType": _rec_int(rec.get("digest") or {}, "algorithmType", "DS digest", 0, 255),
                           "value": str(_need(rec.get("digest") or {}, "value", "DS digest"))}}
    if rtype == "TLSA":
        return {"usage": _rec_int(rec, "usage", "TLSA", 0, 255), "selector": _rec_int(rec, "selector", "TLSA", 0, 255),
                "matchingType": _rec_int(rec, "matchingType", "TLSA", 0, 255), "certAssociationData": str(_need(rec, "certAssociationData", "TLSA"))}
    if rtype == "NAPTR":
        return {"order": _rec_int(rec, "order", "NAPTR", 0, 65535), "preference": _rec_int(rec, "preference", "NAPTR", 0, 65535),
                "flags": str(rec.get("flags") or ""), "services": str(rec.get("services") or ""),
                "regexp": str(rec.get("regexp") or ""), "replacement": str(rec.get("replacement") or ".")}
    raise _E(404, "ResourceTypeNotSupported", f"The record type '{rtype}' is not supported.")


def _canon_type(t):
    up = str(t or "").upper()
    return up if up in RECORD_TYPES else None


def _records_from(rtype, props):
    """The (normalised) records a request's ``properties`` carries for ``rtype`` (``None`` = not supplied)."""
    field = FIELDS[rtype]
    wrong = [FIELDS[t] for t in RECORD_TYPES if t != rtype and props.get(FIELDS[t]) not in (None, [], {})]
    if wrong:
        raise _E(400, "BadRequest", f"The record set type '{rtype}' does not match the supplied records ({', '.join(wrong)}).")
    val = props.get(field)
    if val is None:
        return None
    if rtype in ("CNAME", "SOA"):
        return _norm_record(rtype, val)
    if not isinstance(val, list):
        raise _E(400, "BadRequest", f"'{field}' must be an array.")
    out: list = []
    for r in val:
        n = _norm_record(rtype, r)
        if n not in out:                                   # identical records collapse (as in Azure)
            out.append(n)
    if len(out) > MAX_RECORDS_PER_SET:
        raise _E(400, "BadRequest", f"A record set can have at most {MAX_RECORDS_PER_SET} records.")
    return out


def _rs_view(zone, rs):
    rtype = rs["_rtype"]
    props = {"fqdn": _fqdn(rs["name"], zone["name"]), "TTL": rs["ttl"], "provisioningState": "Succeeded",
             "targetResource": dict(rs.get("target") or {})}
    if rs.get("metadata"):
        props["metadata"] = dict(rs["metadata"])
    if rs["records"] is not None and not rs.get("target"):
        props[FIELDS[rtype]] = rs["records"]
    return {"id": f"{zone['id']}/{rtype}/{rs['name']}", "name": rs["name"], "type": f"{NAMESPACE}/{ZONE_TYPE}/{rtype}",
            "etag": rs["etag"], "properties": props}


def _rs_key(rtype, name):
    return f"{rtype}|{name.lower()}"


def _seed_zone(zone):
    name = zone["name"]
    ns = [{"nsdname": n} for n in zone["properties"]["nameServers"]]
    zone["_rs"][_rs_key("NS", "@")] = {"name": "@", "_rtype": "NS", "ttl": NS_TTL, "records": ns, "etag": _etag(), "metadata": {}}
    soa = dict(SOA_DEFAULTS, host=zone["properties"]["nameServers"][0])
    zone["_rs"][_rs_key("SOA", "@")] = {"name": "@", "_rtype": "SOA", "ttl": 3600, "records": soa, "etag": _etag(), "metadata": {}}


def _sync_count(zone):
    zone["properties"]["numberOfRecordSets"] = len(zone["_rs"])


# ═══════════════════════════ zones ═══════════════════════════════════════════════
def _zone_view(rec):
    out = _view(rec)
    out["properties"] = dict(rec["properties"])
    return out


def _vnet_refs(v):
    if v is None:
        return None
    if not isinstance(v, list):
        raise _E(400, "BadRequest", "Virtual network references must be an array of {id}.")
    return [{"id": str(x.get("id"))} for x in v if isinstance(x, dict) and x.get("id")]


def _put_zone(state, sub, rg, rid, name, payload, method):
    prob = _zone_name_problem(name)
    if prob:
        raise _E(400, "BadRequest", prob)
    pay = payload.get("properties") or {}
    rec = state.get(rid.lower())
    if rec is None:
        if method == "PATCH":
            raise _not_found(name, rg)
        ztype = str(pay.get("zoneType") or "Public").capitalize()
        if ztype not in ("Public", "Private"):
            raise _E(400, "BadRequest", "zoneType must be Public or Private.")
        props = {"maxNumberOfRecordSets": MAX_RECORD_SETS, "maxNumberOfRecordsPerRecordSet": MAX_RECORDS_PER_SET,
                 "numberOfRecordSets": 0, "nameServers": _name_servers(rid), "zoneType": ztype}
        if ztype == "Private":
            props["nameServers"] = []
        for f in ("registrationVirtualNetworks", "resolutionVirtualNetworks"):
            refs = _vnet_refs(pay.get(f))
            if refs is not None:
                props[f] = refs
        rec = {"id": rid, "name": name, "type": f"{NAMESPACE}/{ZONE_TYPE}", "etag": _etag(),
               "location": payload.get("location") or DEFAULT_LOCATION, "tags": dict(payload.get("tags") or {}),
               "properties": props, "_type": f"{NAMESPACE}/{ZONE_TYPE}", "_sub": sub, "_rg": rg, "_rs": {}}
        if props["zoneType"] == "Public":
            _seed_zone(rec)
        _sync_count(rec)
        state[rid.lower()] = rec
        return rec, True
    if isinstance(payload.get("tags"), dict):
        rec["tags"] = dict(payload["tags"])
    for f in ("registrationVirtualNetworks", "resolutionVirtualNetworks"):
        if f in pay:
            refs = _vnet_refs(pay[f])
            if refs is None:
                rec["properties"].pop(f, None)
            else:
                rec["properties"][f] = refs
    rec["etag"] = _etag()
    return rec, False


def _page(items, query, base, path, extra=""):
    top = _to_int(query.get("$top"))
    skip = _to_int(query.get("$skiptoken"), 0) or 0
    rest = items[skip:]
    if top is None or top <= 0 or len(rest) <= top:
        return {"value": rest}
    q = f"api-version={query.get('api-version') or API_VERSION}&$top={top}&$skiptoken={skip + top}{extra}"
    return {"value": rest[:top], "nextLink": f"{base}{quote(path)}?{q}"}


def _list_zones(state, sub, rg, query, base):
    zs = [r for r in _zones(state) if r.get("_sub") == sub and (rg is None or (r.get("_rg") or "").lower() == rg.lower())]
    zs.sort(key=lambda r: (r["name"].lower(), r["id"].lower()))
    path = f"/subscriptions/{sub}" + (f"/resourceGroups/{rg}" if rg else "") + f"/providers/{NAMESPACE}/dnsZones"
    return _ok(_page([_zone_view(r) for r in zs], query, base, path))


def _delete_zone(state, rec):
    state.pop(rec["id"].lower(), None)


# ═══════════════════════════ record sets ═════════════════════════════════════════
def _put_rs(zone, rtype, rel, payload, method):
    prob = _rel_name_problem(rel, zone["name"])
    if prob:
        raise _E(400, "BadRequest", prob)
    props = payload.get("properties") or {}
    key = _rs_key(rtype, rel)
    cur = zone["_rs"].get(key)
    if cur is None and method == "PATCH":
        raise _E(404, "NotFound", f"The Resource '{NAMESPACE}/dnszones/{zone['name']}/{rtype}/{rel}' was not found.")
    recs = _records_from(rtype, props)
    target = props.get("targetResource") if isinstance(props.get("targetResource"), dict) else None
    if target is not None and not target.get("id"):
        target = None
    if rtype == "SOA":
        if rel != "@":
            raise _E(400, "BadRequest", "The SOA record set must be named '@'.")
        if cur is None:
            raise _E(400, "BadRequest", "A zone has exactly one SOA record set; it cannot be created.")
    if rtype == "CNAME" and rel == "@":
        raise _E(400, "BadRequest", "A CNAME record set cannot be created at the zone apex ('@').")
    if rtype == "NS" and rel == "@" and cur is not None and recs is not None and recs != cur["records"]:
        raise _E(400, "BadRequest", "The NS records at the zone apex are managed by Azure DNS and cannot be modified.")
    if method == "PUT" and recs is None and target is None:
        raise _E(400, "BadRequest", f"The {rtype} record set must contain at least one record or an alias target resource.")
    if recs is not None and not isinstance(recs, dict) and not recs and target is None:
        raise _E(400, "BadRequest", f"The {rtype} record set must contain at least one record.")
    if cur is None:
        if len(zone["_rs"]) >= MAX_RECORD_SETS:
            raise _E(400, "BadRequest", f"The zone already has the maximum of {MAX_RECORD_SETS} record sets.")
        others = [k for k, v in zone["_rs"].items() if v["name"].lower() == rel.lower()]
        if rtype == "CNAME" and others:
            raise _E(409, "Conflict", f"A CNAME record set named '{rel}' cannot be created because another record set with that name exists.")
        if rtype != "CNAME" and _rs_key("CNAME", rel) in zone["_rs"]:
            raise _E(409, "Conflict", f"A record set named '{rel}' cannot be created because a CNAME record set with that name exists.")
    ttl = props.get("TTL", props.get("ttl"))
    ttl = _to_int(ttl) if ttl is not None else None
    if ttl is not None and not 0 <= ttl <= 2147483647:
        raise _E(400, "BadRequest", "TTL must be between 0 and 2147483647.")
    if method == "PATCH":
        rs = cur
        if ttl is not None:
            rs["ttl"] = ttl
        if recs is not None:
            rs["records"] = recs
        if target is not None:
            rs["target"] = target
        if "metadata" in props:
            rs["metadata"] = dict(props.get("metadata") or {})
        created = False
    else:
        rs = {"name": rel, "_rtype": rtype,
              "ttl": ttl if ttl is not None else (cur["ttl"] if cur else DEFAULT_TTL),
              "records": recs if recs is not None else ({} if rtype in ("CNAME", "SOA") else []),
              "metadata": dict(props.get("metadata") or {}), "target": target or {}, "etag": _etag()}
        if cur is not None and recs is None and target is not None:
            rs["records"] = None
        created = cur is None
        zone["_rs"][key] = rs
    rs["etag"] = _etag()
    _sync_count(zone)
    return rs, created


def _rs_sorted(zone, rtype=None, suffix=None):
    items = [r for r in zone["_rs"].values() if (rtype is None or r["_rtype"] == rtype)
             and (not suffix or r["name"].lower().endswith(suffix.lower()))]
    order = {t: i for i, t in enumerate(RECORD_TYPES)}
    items.sort(key=lambda r: (r["name"] != "@", r["name"].lower(), order[r["_rtype"]]))
    return items


def _rs_ops(state, zone, rest, method, payload, query, base):
    """``rest`` = path tokens after the zone name."""
    first = rest[0]
    low = first.lower()
    zpath = zone["id"]
    if low == "resolve" and len(rest) == 1:                  # console "Test query" (not part of the Azure API)
        if method != "GET":
            return _err(405, "MethodNotAllowed", "GET required.")
        return _ok(_resolution(resolve(state, query.get("name") or zone["name"], query.get("type") or "A", zone_id=zone["id"]),
                               query.get("name") or zone["name"], query.get("type") or "A"))
    if low in ("recordsets", "all") and len(rest) == 1:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        items = [_rs_view(zone, r) for r in _rs_sorted(zone, None, query.get("$recordsetnamesuffix"))]
        suf = f"&$recordsetnamesuffix={quote(query['$recordsetnamesuffix'])}" if query.get("$recordsetnamesuffix") else ""
        return _ok(_page(items, query, base, f"{zpath}/{first}", suf))
    rtype = _canon_type(first)
    if rtype is None:
        return _err(404, "ResourceTypeNotSupported", f"The resource type '{NAMESPACE}/dnszones/{first}' is not supported.")
    if len(rest) == 1:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        items = [_rs_view(zone, r) for r in _rs_sorted(zone, rtype, query.get("$recordsetnamesuffix"))]
        suf = f"&$recordsetnamesuffix={quote(query['$recordsetnamesuffix'])}" if query.get("$recordsetnamesuffix") else ""
        return _ok(_page(items, query, base, f"{zpath}/{rtype}", suf))
    if len(rest) != 2:
        return _err(404, "ResourceTypeNotSupported", f"The resource type '{NAMESPACE}/dnszones/{'/'.join(rest)}' is not supported.")
    rel = rest[1]
    cur = zone["_rs"].get(_rs_key(rtype, rel))
    if method == "GET":
        if cur is None:
            raise _E(404, "NotFound", f"The Resource '{NAMESPACE}/dnszones/{zone['name']}/{rtype}/{rel}' under resource group "
                                      f"'{zone['_rg']}' was not found.")
        return _ok(_rs_view(zone, cur))
    if method in ("PUT", "PATCH"):
        rs, created = _put_rs(zone, rtype, rel, payload, method)
        return _ok(_rs_view(zone, rs), 201 if created else 200)
    if method == "DELETE":
        if cur is None:
            return _ok(None, 204)
        if rtype == "SOA" or (rtype == "NS" and rel == "@"):
            raise _E(400, "BadRequest", f"The {rtype} record set at the zone apex cannot be deleted.")
        zone["_rs"].pop(_rs_key(rtype, rel), None)
        _sync_count(zone)
        return _ok(None, 200)
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


# ═══════════════════════════ resolution (data plane) ═════════════════════════════
def resolve(state, qname, qtype="A", sub=None, zone_id=None):
    """Answer a DNS question from the public zones' record sets (longest-suffix zone match, CNAME
    chasing, wildcards). Returns ``{"status": NOERROR|NXDOMAIN|REFUSED, "answer": [...], "zone": name}``."""
    name = str(qname or "").strip().lower().rstrip(".")
    qtype = (qtype or "A").upper()
    best = None
    for z in _zones(state):
        if (sub and z.get("_sub") != sub) or (zone_id and z["id"].lower() != zone_id.lower()):
            continue
        if z["properties"].get("zoneType") != "Public":
            continue
        zn = z["name"].lower()
        if (name == zn or name.endswith("." + zn)) and (best is None or len(zn) > len(best["name"])):
            best = z
    if best is None:
        return {"status": "REFUSED", "answer": [], "zone": None}
    zn = best["name"].lower()
    answer: list = []
    cur = name
    for _ in range(8):                                     # CNAME chain limit
        rel = "@" if cur == zn else cur[: -len(zn) - 1]
        cand = [rel]
        parts = rel.split(".")
        if rel != "@":
            cand += ["*." + ".".join(parts[i:]) for i in range(1, len(parts))] + ["*"]
        hit = None
        for c in cand:
            sets = [r for r in best["_rs"].values() if r["name"].lower() == c]
            if sets:
                hit = sets
                break
        if hit is None:
            break
        want = [r for r in hit if r["_rtype"] == qtype] if qtype != "ANY" else hit
        if want:
            for r in want:
                answer += _answers(cur, r)
            return {"status": "NOERROR", "answer": answer, "zone": best["name"]}
        cn = next((r for r in hit if r["_rtype"] == "CNAME"), None)
        if cn is None:
            break
        answer += _answers(cur, cn)
        cur = cn["records"]["cname"].lower().rstrip(".")
        if not (cur == zn or cur.endswith("." + zn)):
            return {"status": "NOERROR", "answer": answer, "zone": best["name"]}
    if answer:
        return {"status": "NOERROR", "answer": answer, "zone": best["name"]}
    exists = any(r["name"].lower() == ("@" if name == zn else name[: -len(zn) - 1]) for r in best["_rs"].values())
    return {"status": "NOERROR" if exists else "NXDOMAIN", "answer": [], "zone": best["name"]}


def _answers(owner, rs):
    t, ttl, recs = rs["_rtype"], rs["ttl"], rs["records"]
    out = []
    for r in ([recs] if isinstance(recs, dict) else (recs or [])):
        if t == "A":
            data = r["ipv4Address"]
        elif t == "AAAA":
            data = r["ipv6Address"]
        elif t == "CNAME":
            data = r["cname"]
        elif t == "NS":
            data = r["nsdname"]
        elif t == "PTR":
            data = r["ptrdname"]
        elif t == "MX":
            data = f"{r['preference']} {r['exchange']}"
        elif t == "SRV":
            data = f"{r['priority']} {r['weight']} {r['port']} {r['target']}"
        elif t == "TXT":
            data = " ".join('"%s"' % v for v in r["value"])
        elif t == "CAA":
            data = f'{r["flags"]} {r["tag"]} "{r["value"]}"'
        elif t == "SOA":
            data = (f"{r['host']} {r['email']} {r['serialNumber']} {r['refreshTime']} {r['retryTime']} "
                    f"{r['expireTime']} {r['minimumTTL']}")
        else:
            data = str(r)
        out.append({"name": owner.rstrip(".") + ".", "type": t, "TTL": ttl, "data": data})
    return out


def _resolution(r, name, rtype):
    code = {"NOERROR": 0, "NXDOMAIN": 3, "REFUSED": 5}[r["status"]]
    return {"Status": code, "Question": [{"name": name.rstrip(".") + ".", "type": (rtype or "A").upper()}],
            "Answer": [{"name": a["name"], "type": a["type"], "TTL": a["TTL"], "data": a["data"]} for a in r["answer"]],
            "Zone": r["zone"]}


def data_dispatch(state, method, query=None):
    """Offline ``/azure-data/dns/query?name=&type=`` (DNS-over-HTTPS-style JSON answer)."""
    q = query or {}
    if (method or "GET").upper() != "GET":
        return {"status": 405, "body": {"error": "GET only"}}
    if not q.get("name"):
        return {"status": 400, "body": {"error": "missing 'name'"}}
    return {"status": 200, "body": _resolution(resolve(state, q["name"], q.get("type") or "A"), q["name"], q.get("type") or "A")}


# ═══════════════════════════ dispatch ════════════════════════════════════════════
def dispatch(state, method, sub, rg, chain, names, payload=None, query=None, base=""):
    """Handle one ``Microsoft.Network`` DNS ARM request (``chain`` = tokens after the namespace)."""
    method = (method or "GET").upper()
    payload = payload if isinstance(payload, dict) else {}
    try:
        return _dispatch(state, method, sub, rg, list(chain), payload, query or {}, base)
    except _E as e:
        return _err(e.status, e.code, e.message)


def handles(chain):
    return bool(chain) and chain[0].lower() in (ZONE_TYPE, "getdnsresourcereference")


def _dispatch(state, method, sub, rg, chain, payload, query, base=""):
    low = chain[0].lower()
    if low == "getdnsresourcereference":
        if method != "POST" or len(chain) != 1:
            return _err(405, "MethodNotAllowed", "POST required.")
        refs = []
        for t in payload.get("properties", {}).get("targetResources") or payload.get("targetResources") or []:
            tid = (t or {}).get("id", "")
            hits = []
            for z in _zones(state):
                if z.get("_sub") != sub:
                    continue
                for rs in z["_rs"].values():
                    if (rs.get("target") or {}).get("id", "").lower() == tid.lower():
                        hits.append({"id": f"{z['id']}/{rs['_rtype']}/{rs['name']}"})
            refs.append({"dnsResources": hits, "targetResource": {"id": tid}})
        return _ok({"properties": {"dnsResourceReferences": refs}})
    if len(chain) == 1:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        return _list_zones(state, sub, rg, query, base)
    name = chain[1]
    if rg is None:
        return _err(400, "InvalidResourceId", "DNS zones must be addressed within a resource group.")
    rid = _zone_rid(sub, rg, name)
    rec = state.get(rid.lower())
    rest = chain[2:]
    if rest:
        if rec is None:
            raise _not_found(name, rg)
        return _rs_ops(state, rec, rest, method, payload, query, base)
    if method == "GET":
        if rec is None:
            raise _not_found(name, rg)
        return _ok(_zone_view(rec))
    if method in ("PUT", "PATCH"):
        rec, created = _put_zone(state, sub, rg, rid, name, payload, method)
        return _ok(_zone_view(rec), 201 if created else 200, rid=rid, verb=method.lower())
    if method == "DELETE":
        if rec is None:
            return _ok(None, 204)
        _delete_zone(state, rec)
        return _ok(None, 200, lro=True, rid=rid, verb="delete")
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


def resource_types():
    return [("dnsZones", API_VERSION)]


def record_set_count(zone):
    return len(zone.get("_rs") or {})
