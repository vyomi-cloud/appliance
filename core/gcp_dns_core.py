"""Google Cloud DNS REST API (dns.googleapis.com/dns/v1, v1beta2) -- substrate-independent, pure Python.

Real semantics, not echoes:
  managedZones      create / get / list / patch / update / delete (a zone with record sets refuses delete, like Google);
                    every zone gets the NS + SOA record sets Google creates, with a stable name-server set
  resourceRecordSets  list (name / type filters, paging), get, create, patch, delete
  changes           create applies additions/deletions ATOMICALLY (validates the whole change first: deleting a record that
                    does not match exactly, adding a duplicate, touching the apex NS/SOA illegally all fail with 4xx and
                    change nothing), bumps the SOA serial, records the change with a monotonically increasing id; get / list
  policies          create / get / list / patch / update / delete (a policy attached to a network cannot be deleted blindly)
  responsePolicies  + responsePolicyRules  create / get / list / patch / update / delete
  dnsKeys           DNSSEC-enabled zones expose KSK + ZSK keys (generated deterministically per zone)
  managedZoneOperations  zone operations produced by zone changes (list / get)
  projects.get      the project's DNS quota
State lives in `bag` (the persisted account dict), keyed by project.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime, timezone

_ZONE_RE = re.compile(r"^[a-z]([-a-z0-9]{0,61}[a-z0-9])?$")
_TYPES = ("A", "AAAA", "CAA", "CNAME", "DNSKEY", "DS", "HTTPS", "IPSECKEY", "MX", "NAPTR", "NS", "PTR", "SOA", "SPF", "SRV", "SSHFP", "SVCB", "TLSA", "TXT")


class Resp:
    def __init__(self, status, obj):
        self.status, self.headers, self.media_type = status, {}, "application/json"
        self.body = json.dumps(obj).encode()


class _E(Exception):
    def __init__(self, status, code, msg, reason=None):
        self.status, self.code, self.msg, self.reason = status, code, msg, reason or code.lower()


def _err(status, code, msg, reason=None):
    return Resp(status, {"error": {"code": status, "message": msg, "status": code,
                                    "errors": [{"message": msg, "domain": "global", "reason": reason or code.lower()}]}})


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _st(bag):
    s = bag.setdefault("gcp_dns", {})
    for k in ("zones", "rrsets", "changes", "policies", "rpolicies", "rrules", "ops"):
        s.setdefault(k, {})
    s.setdefault("seq", 0)
    return s


def _next(s):
    s["seq"] += 1
    return s["seq"]


def _num(*parts):
    return str(int(hashlib.sha1("|".join(parts).encode()).hexdigest()[:12], 16) % 10 ** 18)


def _fqdn(n):
    n = (n or "").lower()
    return n if n.endswith(".") else n + "."


def _nameservers(zone_id):
    c = "abcd"[int(hashlib.sha1(zone_id.encode()).hexdigest()[:4], 16) % 4]
    return ["ns-cloud-%s%d.googledomains.com." % (c, i) for i in (1, 2, 3, 4)]


def _soa(zone, serial=1):
    ns = zone["nameServers"][0]
    return "%s cloud-dns-hostmaster.google.com. %d 21600 3600 259200 300" % (ns, serial)


# ── helpers over the stores ─────────────────────────────────────────────────────────────
def _zone(s, project, zid):
    z = s["zones"].get("%s/%s" % (project, zid))
    if z is None:
        for k, v in s["zones"].items():   # a zone is addressable by its unique numeric id too
            if k.startswith(project + "/") and v["id"] == zid:
                return v
        raise _E(404, "NOT_FOUND", "The 'parameters.managedZone' resource named '%s' does not exist." % zid, "notFound")
    return z


def _rrs(s, zone):
    return s["rrsets"].setdefault("%s/%s" % (zone["_project"], zone["name"]), [])


def _view(o):
    return {k: v for k, v in o.items() if not k.startswith("_")}


def _page(items, q, key, default=100):
    try:
        size = int(q.get("maxResults") or default)
        start = int(q.get("pageToken") or 0)
    except ValueError:
        raise _E(400, "INVALID_ARGUMENT", "Invalid maxResults/pageToken", "invalid")
    chunk = items[start:start + size]
    out = {key: chunk}
    if start + size < len(items):
        out["nextPageToken"] = str(start + size)
    return out


def _check_dns_name(dn):
    if not dn or not re.match(r"^([a-zA-Z0-9_]([-a-zA-Z0-9_]{0,61}[a-zA-Z0-9_])?\.)+$", _fqdn(dn)) or len(dn) > 253:
        raise _E(400, "INVALID_ARGUMENT", "Invalid value for 'entity.managedZone.dnsName': '%s'" % dn, "invalid")


def _op(s, project, zone, kind, change=None):
    n = _next(s)
    op = {"kind": "dns#operation", "id": str(n), "startTime": _now(), "status": "DONE", "type": kind, "user": "admin@vyomi.cloud",
          "zoneContext": {"oldValue": {"kind": "dns#operationManagedZoneContext"}, "newValue": {"kind": "dns#operationManagedZoneContext"}}}
    s["ops"].setdefault("%s/%s" % (project, zone["name"]), []).append(op)
    return op


# ── zones ───────────────────────────────────────────────────────────────────────────────
def _create_zone(s, project, q, p):
    name, dn = p.get("name") or "", p.get("dnsName") or ""
    if not _ZONE_RE.match(name):
        raise _E(400, "INVALID_ARGUMENT", "Invalid value for 'entity.managedZone.name': '%s'" % name, "invalid")
    _check_dns_name(dn)
    if "%s/%s" % (project, name) in s["zones"]:
        raise _E(409, "ALREADY_EXISTS", "The resource 'entity.managedZone: %s' already exists" % name, "alreadyExists")
    vis = (p.get("visibility") or "public")
    if vis not in ("public", "private"):
        raise _E(400, "INVALID_ARGUMENT", "Invalid value for 'entity.managedZone.visibility': '%s'" % vis, "invalid")
    if vis == "private" and not (p.get("privateVisibilityConfig") or {}).get("networks") and not (p.get("privateVisibilityConfig") or {}).get("gkeClusters"):
        raise _E(400, "INVALID_ARGUMENT", "Private zones require privateVisibilityConfig.networks", "invalid")
    zid = _num(project, name)
    z = {"kind": "dns#managedZone", "id": zid, "name": name, "dnsName": _fqdn(dn), "description": p.get("description", ""),
         "nameServers": [] if vis == "private" else _nameservers(zid), "creationTime": _now(), "visibility": vis,
         "labels": p.get("labels") or {}, "cloudLoggingConfig": p.get("cloudLoggingConfig") or {"kind": "dns#managedZoneCloudLoggingConfig"},
         "_project": project, "_serial": 1}
    for k in ("dnssecConfig", "forwardingConfig", "privateVisibilityConfig", "peeringConfig", "serviceDirectoryConfig", "reverseLookupConfig", "nameServerSet"):
        if k in p:
            z[k] = p[k]
    if vis == "public":
        z.setdefault("dnssecConfig", {"kind": "dns#managedZoneDnsSecConfig", "state": "off", "nonExistence": "nsec3"})
    s["zones"]["%s/%s" % (project, name)] = z
    base = [{"name": z["dnsName"], "type": "NS", "ttl": 21600, "rrdatas": z["nameServers"] or ["ns-cloud-private.googledomains.com."]},
            {"name": z["dnsName"], "type": "SOA", "ttl": 21600, "rrdatas": [_soa(z if z["nameServers"] else dict(z, nameServers=["ns-cloud-private.googledomains.com."]))]}]
    s["rrsets"]["%s/%s" % (project, name)] = [dict(r, kind="dns#resourceRecordSet") for r in base]
    s["changes"]["%s/%s" % (project, name)] = []
    return _view(z)


def _patch_zone(s, z, p, replace):
    for k in ("description", "labels", "dnssecConfig", "forwardingConfig", "privateVisibilityConfig", "peeringConfig", "cloudLoggingConfig",
              "serviceDirectoryConfig", "reverseLookupConfig"):
        if k in p:
            z[k] = p[k]
        elif replace and k in z and k not in ("cloudLoggingConfig",):
            z.pop(k)
    if "dnsName" in p and _fqdn(p["dnsName"]) != z["dnsName"]:
        raise _E(400, "INVALID_ARGUMENT", "dnsName of a managed zone is immutable.", "invalid")
    return _view(z)


def _dnskeys(z):
    cfg = z.get("dnssecConfig") or {}
    if cfg.get("state") not in ("on", "transfer"):
        return []
    out = []
    for kt, flags in (("keySigning", 257), ("zoneSigning", 256)):
        kid = _num(z["id"], kt)[:10]
        out.append({"kind": "dns#dnsKey", "id": kid, "type": kt, "algorithm": "rsasha256" if kt == "keySigning" else "rsasha256", "keyLength": 2048 if kt == "keySigning" else 1024,
                    "creationTime": z["creationTime"], "isActive": True,
                    "publicKey": hashlib.sha256((z["id"] + kt).encode()).hexdigest(),
                    "digests": [{"type": "sha256", "digest": hashlib.sha256((z["id"] + kt + "d").encode()).hexdigest()}] if kt == "keySigning" else []})
    return out


# ── record sets / changes ───────────────────────────────────────────────────────────────
def _norm_rr(z, r):
    if not r.get("name") or not r.get("type"):
        raise _E(400, "INVALID_ARGUMENT", "Invalid value for 'entity.change.additions[0]': name and type are required", "invalid")
    name = _fqdn(r["name"])
    if not (name == z["dnsName"] or name.endswith("." + z["dnsName"])):
        raise _E(400, "INVALID_ARGUMENT", "Invalid value for 'entity.change.additions[0].name': '%s' is not within the zone '%s'" % (name, z["dnsName"]), "invalid")
    t = r["type"].upper()
    if t not in _TYPES:
        raise _E(400, "INVALID_ARGUMENT", "Invalid value for 'entity.change.additions[0].type': '%s'" % r["type"], "invalid")
    data = r.get("rrdatas") or []
    if not data and not r.get("routingPolicy"):
        raise _E(400, "INVALID_ARGUMENT", "Invalid value for 'entity.change.additions[0].rrdata': at least one rrdata is required", "invalid")
    try:
        ttl = int(r.get("ttl", 300))
    except (TypeError, ValueError):
        raise _E(400, "INVALID_ARGUMENT", "ttl must be an integer", "invalid")
    if ttl < 0:
        raise _E(400, "INVALID_ARGUMENT", "ttl must be non-negative", "invalid")
    out = {"kind": "dns#resourceRecordSet", "name": name, "type": t, "ttl": ttl, "rrdatas": [str(d) for d in data]}
    if t == "CNAME" and len(out["rrdatas"]) != 1:
        raise _E(400, "INVALID_ARGUMENT", "CNAME records must have exactly one rrdata", "invalid")
    if t == "A":
        for d in out["rrdatas"]:
            if not re.match(r"^(\d{1,3}\.){3}\d{1,3}$", d) or any(int(x) > 255 for x in d.split(".")):
                raise _E(400, "INVALID_ARGUMENT", "Invalid value for 'entity.change.additions[0].rrdata[0]': '%s'" % d, "invalid")
    if r.get("routingPolicy"):
        out["routingPolicy"] = r["routingPolicy"]
    return out


def _apply_change(s, z, p):
    rr = list(_rrs(s, z))
    adds = [_norm_rr(z, r) for r in (p.get("additions") or [])]
    dels = list(p.get("deletions") or [])
    if not adds and not dels:
        raise _E(400, "INVALID_ARGUMENT", "A change must include additions or deletions", "invalid")
    for d in dels:
        key = (_fqdn(d.get("name")), (d.get("type") or "").upper())
        match = [r for r in rr if (r["name"], r["type"]) == key]
        if not match:
            raise _E(404, "NOT_FOUND", "The 'entity.change.deletions[0]' resource named '%s (%s)' does not exist." % key, "notFound")
        cur = match[0]
        if sorted(cur["rrdatas"]) != sorted(d.get("rrdatas") or []) or int(cur["ttl"]) != int(d.get("ttl", cur["ttl"])):
            raise _E(412, "FAILED_PRECONDITION", "Precondition not met for 'entity.change.deletions[0]': the record to delete does not match the existing record set", "conditionNotMet")
        rr.remove(cur)
    deleted_keys = {(_fqdn(d["name"]), d["type"].upper()) for d in (p.get("deletions") or [])}
    for a in adds:
        key = (a["name"], a["type"])
        if any((r["name"], r["type"]) == key for r in rr):
            raise _E(409, "ALREADY_EXISTS", "The resource 'entity.change.additions[0]' named '%s (%s)' already exists" % key, "alreadyExists")
        if a["type"] == "CNAME" and any(r["name"] == a["name"] and r["type"] != "CNAME" for r in rr):
            raise _E(400, "INVALID_ARGUMENT", "CNAME at '%s' conflicts with other record sets" % a["name"], "invalid")
        if a["type"] != "CNAME" and any(r["name"] == a["name"] and r["type"] == "CNAME" for r in rr):
            raise _E(400, "INVALID_ARGUMENT", "'%s' already has a CNAME record" % a["name"], "invalid")
        rr.append(a)
    apex = z["dnsName"]
    if not any(r["name"] == apex and r["type"] == "SOA" for r in rr) or not any(r["name"] == apex and r["type"] == "NS" for r in rr):
        raise _E(400, "INVALID_ARGUMENT", "The apex NS and SOA record sets cannot be removed", "invalid")
    z["_serial"] += 1
    for r in rr:   # every applied change bumps the SOA serial, as Google does
        if r["name"] == apex and r["type"] == "SOA":
            parts = r["rrdatas"][0].split()
            parts[2] = str(z["_serial"])
            r["rrdatas"] = [" ".join(parts)]
    s["rrsets"]["%s/%s" % (z["_project"], z["name"])] = rr
    cid = str(len(s["changes"]["%s/%s" % (z["_project"], z["name"])]) + 1)
    ch = {"kind": "dns#change", "id": cid, "startTime": _now(), "status": "done", "isServing": True,
          "additions": [dict(a) for a in adds], "deletions": [dict(d, kind="dns#resourceRecordSet") for d in (p.get("deletions") or [])]}
    s["changes"]["%s/%s" % (z["_project"], z["name"])].append(ch)
    _op(s, z["_project"], z, "update")
    return ch


# ── routing ─────────────────────────────────────────────────────────────────────────────
_ROOT = re.compile(r"^/dns/(v1|v1beta2)/projects/([^/]+)(?:/(.*))?$")


def handles(path):
    return bool(_ROOT.match(path.split("?", 1)[0]))


def dispatch(bag, method, path, query, body):
    method = method.upper()
    q = query or {}
    try:
        p = json.loads(body.decode() or "{}") if body else {}
    except ValueError:
        return _err(400, "INVALID_ARGUMENT", "Invalid JSON payload received.", "parseError")
    if not isinstance(p, dict):
        p = {}
    m = _ROOT.match(path.split("?", 1)[0])
    if not m:
        return _err(404, "NOT_FOUND", "Unknown path: %s" % path)
    project, rest = m.group(2), [x for x in (m.group(3) or "").split("/") if x]
    s = _st(bag)
    try:
        return Resp(200, _route(s, method, project, rest, q, p))
    except _E as e:
        return _err(e.status, e.code, e.msg, e.reason)


def _route(s, method, project, rest, q, p):
    if not rest:
        if method == "GET":
            return {"kind": "dns#project", "id": project, "number": _num(project)[:12],
                    "quota": {"kind": "dns#quota", "managedZones": 10000, "rrsetsPerManagedZone": 10000, "rrsetAdditionsPerChange": 1000,
                              "rrsetDeletionsPerChange": 1000, "totalRrdataSizePerChange": 10000000, "resourceRecordsPerRrset": 100, "policies": 500,
                              "networksPerPolicy": 100, "networksPerManagedZone": 100, "responsePolicies": 100, "responsePolicyRules": 100000}}
        raise _E(405, "UNIMPLEMENTED", "Method not allowed")
    head = rest[0]
    if head == "managedZones":
        return _zones(s, method, project, rest[1:], q, p)
    if head == "policies":
        return _simple(s, "policies", "dns#policy", "policies", method, project, rest[1:], q, p, ("enableInboundForwarding", "enableLogging", "alternativeNameServerConfig", "networks", "description"))
    if head == "responsePolicies":
        if len(rest) >= 3 and rest[2] == "rules":
            return _rules(s, method, project, rest[1], rest[3:], q, p)
        return _simple(s, "rpolicies", "dns#responsePolicy", "responsePolicies", method, project, rest[1:], q, p, ("description", "networks", "gkeClusters", "labels"),
                       name_key="responsePolicyName", delete_guard=lambda k: any(r for r in s["rrules"].values() if r["_policy"] == k))
    raise _E(404, "NOT_FOUND", "Unknown path: /%s" % "/".join(rest))


def _zones(s, method, project, rest, q, p):
    if not rest:
        if method == "POST":
            return _create_zone(s, project, q, p)
        if method == "GET":
            zs = sorted((z for k, z in s["zones"].items() if k.startswith(project + "/")), key=lambda z: z["name"])
            if q.get("dnsName"):
                zs = [z for z in zs if z["dnsName"] == _fqdn(q["dnsName"])]
            return dict(_page([_view(z) for z in zs], q, "managedZones"), kind="dns#managedZonesListResponse")
        raise _E(405, "UNIMPLEMENTED", "Method not allowed")
    z = _zone(s, project, rest[0])
    sub = rest[1:]
    if not sub:
        if method == "GET":
            return _view(z)
        if method in ("PATCH", "PUT"):
            return _patch_zone(s, z, p, replace=method == "PUT")
        if method == "DELETE":
            if len([r for r in _rrs(s, z) if r["type"] not in ("NS", "SOA") or r["name"] != z["dnsName"]]):
                raise _E(400, "FAILED_PRECONDITION", "The resource 'entity.managedZone: %s' is not empty (it has non-default record sets)." % z["name"], "containerNotEmpty")
            for k in ("zones", "rrsets", "changes"):
                s[k].pop("%s/%s" % (project, z["name"]), None)
            s["zones"].pop("%s/%s" % (project, z["name"]), None)
            return {}
        raise _E(405, "UNIMPLEMENTED", "Method not allowed")
    if sub[0] == "rrsets":
        return _rrsets(s, method, z, sub[1:], q, p)
    if sub[0] == "changes":
        key = "%s/%s" % (project, z["name"])
        if len(sub) == 1:
            if method == "POST":
                return _apply_change(s, z, p)
            if method == "GET":
                chs = list(s["changes"][key])
                if q.get("sortOrder") == "descending":
                    chs.reverse()
                return dict(_page(chs, q, "changes"), kind="dns#changesListResponse")
        elif len(sub) == 2 and method == "GET":
            for c in s["changes"][key]:
                if c["id"] == sub[1]:
                    return c
            raise _E(404, "NOT_FOUND", "The 'parameters.changeId' resource named '%s' does not exist." % sub[1], "notFound")
    if sub[0] == "dnsKeys":
        keys = _dnskeys(z)
        if len(sub) == 1 and method == "GET":
            return dict(_page(keys, q, "dnsKeys"), kind="dns#dnsKeysListResponse")
        if len(sub) == 2 and method == "GET":
            for k in keys:
                if k["id"] == sub[1]:
                    return k
            raise _E(404, "NOT_FOUND", "The 'parameters.dnsKeyId' resource named '%s' does not exist." % sub[1], "notFound")
    if sub[0] == "operations":
        ops = s["ops"].get("%s/%s" % (project, z["name"]), [])
        if len(sub) == 1 and method == "GET":
            return dict(_page(ops, q, "operations"), kind="dns#managedZoneOperationsListResponse")
        if len(sub) == 2 and method == "GET":
            for o in ops:
                if o["id"] == sub[1]:
                    return o
            raise _E(404, "NOT_FOUND", "The 'parameters.operation' resource named '%s' does not exist." % sub[1], "notFound")
    raise _E(404, "NOT_FOUND", "Unknown path: /%s" % "/".join(sub))


def _rrsets(s, method, z, rest, q, p):
    rr = _rrs(s, z)
    if not rest:
        if method == "GET":
            items = sorted(rr, key=lambda r: (r["name"], r["type"]))
            if q.get("name"):
                items = [r for r in items if r["name"] == _fqdn(q["name"])]
            if q.get("type"):
                items = [r for r in items if r["type"] == q["type"].upper()]
            return dict(_page(items, q, "rrsets"), kind="dns#resourceRecordSetsListResponse")
        if method == "POST":
            ch = _apply_change(s, z, {"additions": [p]})
            return ch["additions"][0]
        raise _E(405, "UNIMPLEMENTED", "Method not allowed")
    if len(rest) == 2:
        return _rrset_item(s, method, z, rest[0], rest[1], p)
    raise _E(404, "NOT_FOUND", "Unknown rrsets path")


def _rrset_item(s, method, z, name, rtype, p):
    rr = _rrs(s, z)
    name, rtype = _fqdn(name), rtype.upper()
    cur = next((r for r in rr if r["name"] == name and r["type"] == rtype), None)
    if cur is None:
        raise _E(404, "NOT_FOUND", "The 'entity.rrset' resource named '%s (%s)' does not exist." % (name, rtype), "notFound")
    if method == "GET":
        return cur
    if method == "DELETE":
        _apply_change(s, z, {"deletions": [cur]})
        return {}
    if method == "PATCH":
        new = dict(cur, **{k: v for k, v in p.items() if k in ("ttl", "rrdatas", "routingPolicy")})
        _apply_change(s, z, {"deletions": [cur], "additions": [new]})
        return next(r for r in _rrs(s, z) if r["name"] == name and r["type"] == rtype)
    raise _E(405, "UNIMPLEMENTED", "Method not allowed")


def _simple(s, store, kind, listkey, method, project, rest, q, p, fields, name_key="name", delete_guard=None):
    items = s[store]
    if not rest:
        if method == "POST":
            nm = p.get(name_key) or p.get("name") or p.get("policyName") or ""
            if not _ZONE_RE.match(nm):
                raise _E(400, "INVALID_ARGUMENT", "Invalid value for '%s': '%s'" % (name_key, nm), "invalid")
            key = "%s/%s" % (project, nm)
            if key in items:
                raise _E(409, "ALREADY_EXISTS", "The resource '%s' already exists" % nm, "alreadyExists")
            o = {"kind": kind, "id": _num(project, kind, nm), name_key if store == "rpolicies" else "name": nm, "_project": project}
            if store == "rpolicies":
                o["id"] = _num(project, kind, nm)
            for f in fields:
                if f in p:
                    o[f] = p[f]
            items[key] = o
            return _view(o)
        if method == "GET":
            os_ = sorted((o for k, o in items.items() if k.startswith(project + "/")), key=lambda o: o.get("name") or o.get(name_key))
            return dict(_page([_view(o) for o in os_], q, listkey), kind=kind + "sListResponse")
        raise _E(405, "UNIMPLEMENTED", "Method not allowed")
    key = "%s/%s" % (project, rest[0])
    o = items.get(key)
    if o is None:
        raise _E(404, "NOT_FOUND", "The '%s' resource named '%s' does not exist." % (kind, rest[0]), "notFound")
    if method == "GET":
        return _view(o)
    if method in ("PATCH", "PUT"):
        for f in fields:
            if f in p:
                o[f] = p[f]
            elif method == "PUT":
                o.pop(f, None)
        if method == "PUT":
            return {"kind": kind + "sUpdateResponse", ("policy" if store == "policies" else "responsePolicy"): _view(o)}
        return _view(o)
    if method == "DELETE":
        if store == "policies" and o.get("networks"):
            raise _E(400, "FAILED_PRECONDITION", "Policy '%s' is still attached to networks; detach them first." % rest[0], "resourceInUseByAnotherResource")
        if delete_guard and delete_guard(key):
            raise _E(400, "FAILED_PRECONDITION", "Response policy '%s' still has rules." % rest[0], "containerNotEmpty")
        items.pop(key)
        return {}
    raise _E(405, "UNIMPLEMENTED", "Method not allowed")


def _rules(s, method, project, rp, rest, q, p):
    pkey = "%s/%s" % (project, rp)
    if pkey not in s["rpolicies"]:
        raise _E(404, "NOT_FOUND", "The 'responsePolicy' resource named '%s' does not exist." % rp, "notFound")
    rules = s["rrules"]
    if not rest:
        if method == "POST":
            nm = p.get("ruleName") or ""
            if not nm or not p.get("dnsName"):
                raise _E(400, "INVALID_ARGUMENT", "ruleName and dnsName are required", "invalid")
            key = "%s/%s" % (pkey, nm)
            if key in rules:
                raise _E(409, "ALREADY_EXISTS", "The resource '%s' already exists" % nm, "alreadyExists")
            o = {"kind": "dns#responsePolicyRule", "ruleName": nm, "dnsName": _fqdn(p["dnsName"]), "_policy": pkey}
            for f in ("localData", "behavior"):
                if f in p:
                    o[f] = p[f]
            if "localData" not in o and "behavior" not in o:
                raise _E(400, "INVALID_ARGUMENT", "A rule needs localData or behavior", "invalid")
            rules[key] = o
            return _view(o)
        if method == "GET":
            return dict(_page([_view(r) for k, r in sorted(rules.items()) if r["_policy"] == pkey], q, "responsePolicyRules"), kind="dns#responsePolicyRulesListResponse")
        raise _E(405, "UNIMPLEMENTED", "Method not allowed")
    key = "%s/%s" % (pkey, rest[0])
    o = rules.get(key)
    if o is None:
        raise _E(404, "NOT_FOUND", "The 'responsePolicyRule' resource named '%s' does not exist." % rest[0], "notFound")
    if method == "GET":
        return _view(o)
    if method in ("PATCH", "PUT"):
        for f in ("dnsName", "localData", "behavior"):
            if f in p:
                o[f] = _fqdn(p[f]) if f == "dnsName" else p[f]
        return {"kind": "dns#responsePolicyRulesUpdateResponse", "responsePolicyRule": _view(o)} if method == "PUT" else _view(o)
    if method == "DELETE":
        rules.pop(key)
        return {}
    raise _E(405, "UNIMPLEMENTED", "Method not allowed")
