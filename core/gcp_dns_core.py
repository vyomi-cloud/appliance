"""GCP Cloud DNS core — substrate-independent. Speaks the native **Cloud DNS REST API
v1** (`/dns/v1/projects/{p}/managedZones...`) so the official `google-cloud-dns` /
`google.golang.org/api/dns/v1` clients and `gcloud dns` work unchanged against it
(point them at the endpoint via the root URL / api_endpoint_overrides).

NO fastapi / google-cloud / socket / subprocess imports → loads under Pyodide, so the
SAME file runs offline and in Nano.

Resources (Discovery doc `dns/v1`):
    projects.get
    managedZones            create / get / list / patch / update / delete
    managedZones/{z}/rrsets list / get / create / patch / delete
    managedZones/{z}/changes create / get / list     (atomic additions + deletions)
    managedZones/{z}/dnsKeys list / get              (populated when DNSSEC is on)
    policies                create / get / list / patch / update / delete

A new zone gets the default apex `NS` + `SOA` record sets and the four
`ns-cloud-*.googledomains.com.` name servers (public zones), exactly like the real
service. Every record-set mutation is a Change (the rrsets.* shortcuts record one too),
the SOA serial is bumped by each change, and changes complete immediately (`done`).
Errors use the Google shape `{"error":{"code","message","errors":[{message,domain,reason}],"status"}}`
(alreadyExists, notFound, invalid, conditionNotMet, containerNotEmpty).
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

API_VERSIONS = ("v1", "v1beta2", "v2")
RR_TYPES = ("A", "AAAA", "CAA", "CNAME", "DNSKEY", "DS", "HTTPS", "IPSECKEY", "MX", "NAPTR",
            "NS", "PTR", "SOA", "SPF", "SRV", "SSHFP", "SVCB", "TLSA", "TXT")
QUOTA = {"kind": "dns#quota", "managedZones": 10000, "rrsetsPerManagedZone": 10000,
         "rrsetAdditionsPerChange": 1000, "rrsetDeletionsPerChange": 1000,
         "totalRrdataSizePerChange": 100000, "resourceRecordsPerRrset": 100,
         "managedZonesPerNetwork": 100, "networksPerManagedZone": 100, "networksPerPolicy": 100,
         "policies": 1000, "targetNameServersPerManagedZone": 100,
         "targetNameServersPerPolicy": 100, "whitelistedKeySpecs": []}
DEFAULT_TTL = 300
NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,61}[a-z0-9]$")
_NS_SETS = "abcd"


# ── store ──────────────────────────────────────────────────────────────────
class CloudDnsStore:
    """Public dict attrs only → persisted/synced by core/nano_persist."""

    def __init__(self):
        # "project/zone" -> {"zone": managedZone resource, "rrsets": [..], "changes": [..]}
        self.zones: dict = {}
        self.policies: dict = {}      # "project/policy" -> policy resource


_SHARED: CloudDnsStore | None = None


def shared_store() -> CloudDnsStore:
    """The appliance-wide store: the native wire and the console REST share it."""
    global _SHARED
    if _SHARED is None:
        _SHARED = CloudDnsStore()
    return _SHARED


@dataclass
class DnsResponse:
    status: int = 200
    headers: dict = field(default_factory=dict)
    body: bytes = b""
    media_type: str | None = "application/json"


class _E(Exception):
    def __init__(self, status, gcp_status, reason, message):
        super().__init__(message)
        self.status, self.gcp_status, self.reason, self.message = status, gcp_status, reason, message


def _err(status, gcp_status, reason, message):
    body = {"error": {"code": status, "message": message,
                      "errors": [{"message": message, "domain": "global", "reason": reason}],
                      "status": gcp_status}}
    return DnsResponse(status=status, body=json.dumps(body).encode())


def _json(status, obj):
    return DnsResponse(status=status, body=json.dumps(obj).encode())


def _empty(status=204):
    return DnsResponse(status=status, body=b"", media_type=None)


def _ts():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _num_id(*parts):
    """Stable 64-bit-ish numeric id (the real API returns uint64 as a string)."""
    h = hashlib.sha1("/".join(parts).encode()).hexdigest()
    return str(int(h[:15], 16))


def _bad(msg, field_name):
    return _E(400, "INVALID_ARGUMENT", "invalid", "Invalid value for '%s': '%s'" % (field_name, msg))


# ── validation ─────────────────────────────────────────────────────────────
def _fqdn_ok(s):
    return isinstance(s, str) and s.endswith(".") and len(s) > 1 and len(s) <= 254 and ".." not in s \
        and all(0 < len(lbl) <= 63 for lbl in s[:-1].split("."))


def _validate_rrdata(rtype, data, where):
    for i, d in enumerate(data):
        w = "%s.rrdata[%d]" % (where, i)
        if not isinstance(d, str) or not d.strip():
            raise _bad(str(d), w)
        try:
            if rtype == "A":
                ipaddress.IPv4Address(d)
            elif rtype == "AAAA":
                ipaddress.IPv6Address(d)
            elif rtype in ("CNAME", "NS", "PTR"):
                if not _fqdn_ok(d):
                    raise ValueError
            elif rtype == "MX":
                pri, host = d.split(None, 1)
                if not pri.isdigit() or not _fqdn_ok(host.strip()):
                    raise ValueError
            elif rtype == "SRV":
                pr, wt, pt, host = d.split(None, 3)
                if not (pr.isdigit() and wt.isdigit() and pt.isdigit() and _fqdn_ok(host.strip())):
                    raise ValueError
            elif rtype == "SOA" and len(d.split()) != 7:
                raise ValueError
        except ValueError:
            raise _bad(d, w)
    if rtype in ("CNAME", "SOA") and len(data) != 1:
        raise _bad(",".join(data), "%s.rrdata" % where)


def _norm_rrset(rr, zone_dns, where):
    """Validate + canonicalise one resource record set from a request."""
    if not isinstance(rr, dict):
        raise _bad(str(rr), where)
    name, rtype = rr.get("name"), str(rr.get("type") or "").upper()
    if not _fqdn_ok(name):
        raise _bad(str(name), where + ".name")
    if not (name.lower() == zone_dns.lower() or name.lower().endswith("." + zone_dns.lower())):
        raise _bad(name, where + ".name")
    if rtype not in RR_TYPES:
        raise _bad(str(rr.get("type")), where + ".type")
    data = rr.get("rrdatas")
    if not isinstance(data, list) or not data:
        raise _bad("", where + ".rrdata")
    ttl = rr.get("ttl", DEFAULT_TTL)
    if not isinstance(ttl, int) or isinstance(ttl, bool) or ttl < 0:
        raise _bad(str(ttl), where + ".ttl")
    _validate_rrdata(rtype, data, where)
    out = {"name": name, "type": rtype, "ttl": ttl, "rrdatas": list(data), "kind": "dns#resourceRecordSet"}
    if rr.get("signatureRrdatas"):
        out["signatureRrdatas"] = list(rr["signatureRrdatas"])
    return out


def _key(name, rtype):
    return (name.lower(), rtype)


def _sort_key(rr):
    return (list(reversed(rr["name"].lower().rstrip(".").split("."))), rr["type"])


def _same(a, b):
    return (a["name"].lower() == b["name"].lower() and a["type"] == b["type"] and a.get("ttl") == b.get("ttl")
            and sorted(a.get("rrdatas") or []) == sorted(b.get("rrdatas") or []))


# ── zones ──────────────────────────────────────────────────────────────────
def _nameservers(project, name):
    set_letter = _NS_SETS[int(_num_id(project, name)) % 4]
    return ["ns-cloud-%s%d.googledomains.com." % (set_letter, i) for i in range(1, 5)]


def _soa_data(project, name, serial=1):
    ns = _nameservers(project, name)[0]
    return "%s cloud-dns-hostmaster.google.com. %d 21600 3600 259200 300" % (ns, serial)


def _zkey(project, name):
    return "%s/%s" % (project, name)


def _zone_rec(store, project, name):
    rec = store.zones.get(_zkey(project, name))
    if rec is None:
        raise _E(404, "NOT_FOUND", "notFound",
                 "The 'parameters.managedZone' resource named '%s' does not exist." % name)
    return rec


def _zone_view(rec):
    return json.loads(json.dumps(rec["zone"]))


def create_zone(store, project, payload):
    name = payload.get("name")
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise _bad(str(name), "entity.managedZone.name")
    dns_name = payload.get("dnsName")
    if not _fqdn_ok(dns_name):
        raise _bad(str(dns_name), "entity.managedZone.dnsName")
    vis = payload.get("visibility") or "public"
    if vis not in ("public", "private"):
        raise _bad(str(vis), "entity.managedZone.visibility")
    if _zkey(project, name) in store.zones:
        raise _E(409, "ALREADY_EXISTS", "alreadyExists",
                 "The resource 'entity.managedZone' named '%s' already exists" % name)
    desc = payload.get("description")
    if desc is not None and (not isinstance(desc, str) or len(desc) > 1024):
        raise _bad(str(desc)[:30], "entity.managedZone.description")
    zone = {"kind": "dns#managedZone", "id": _num_id(project, name), "name": name,
            "dnsName": dns_name, "description": desc or "", "creationTime": _ts(), "visibility": vis}
    if vis == "public":
        zone["nameServers"] = _nameservers(project, name)
        zone["dnssecConfig"] = dict(payload.get("dnssecConfig") or {}, kind="dns#managedZoneDnsSecConfig")
        zone["dnssecConfig"].setdefault("state", "off")
        if payload.get("nameServerSet"):
            zone["nameServerSet"] = payload["nameServerSet"]
    else:
        pvc = payload.get("privateVisibilityConfig") or {}
        zone["privateVisibilityConfig"] = dict(pvc, kind="dns#managedZonePrivateVisibilityConfig")
        if payload.get("forwardingConfig"):
            zone["forwardingConfig"] = dict(payload["forwardingConfig"], kind="dns#managedZoneForwardingConfig")
    if payload.get("labels"):
        zone["labels"] = dict(payload["labels"])
    zone["cloudLoggingConfig"] = dict(payload.get("cloudLoggingConfig") or {}, kind="dns#managedZoneCloudLoggingConfig")
    rrsets = [
        {"name": dns_name, "type": "NS", "ttl": 21600, "kind": "dns#resourceRecordSet",
         "rrdatas": _nameservers(project, name)},
        {"name": dns_name, "type": "SOA", "ttl": 21600, "kind": "dns#resourceRecordSet",
         "rrdatas": [_soa_data(project, name)]},
    ]
    store.zones[_zkey(project, name)] = {"zone": zone, "rrsets": rrsets, "changes": [], "next_change": 1}
    return zone


_MUTABLE_ZONE = ("description", "labels", "dnssecConfig", "privateVisibilityConfig", "forwardingConfig",
                 "cloudLoggingConfig", "nameServerSet", "peeringConfig", "reverseLookupConfig")


def patch_zone(store, project, name, payload, replace=False):
    rec = _zone_rec(store, project, name)
    old = _zone_view(rec)
    z = rec["zone"]
    if payload.get("dnsName") and payload["dnsName"] != z["dnsName"]:
        raise _bad(payload["dnsName"], "entity.managedZone.dnsName")
    for k in _MUTABLE_ZONE:
        if k in payload:
            v = payload[k]
            if isinstance(v, dict) and k.endswith("Config"):
                v = dict(v, kind=z.get(k, {}).get("kind") or "dns#managedZone" + k[0].upper() + k[1:])
            z[k] = v
        elif replace and k in ("description", "labels"):
            z.pop(k, None)
    z.setdefault("description", "")
    return {"kind": "dns#operation", "id": _num_id(project, name, _ts()), "startTime": _ts(), "status": "DONE",
            "type": "update", "user": "", "zoneContext": {"oldValue": old, "newValue": _zone_view(rec)}}


def delete_zone(store, project, name):
    rec = _zone_rec(store, project, name)
    non_default = [r for r in rec["rrsets"] if not (r["name"] == rec["zone"]["dnsName"] and r["type"] in ("NS", "SOA"))]
    if non_default:
        raise _E(400, "FAILED_PRECONDITION", "containerNotEmpty",
                 "The resource named 'projects/%s/managedZones/%s' cannot be deleted because it is not empty"
                 % (project, name))
    del store.zones[_zkey(project, name)]


def delete_zone_with_records(store, project, name):
    """Console "Delete zone": clear every non-default record set (as separate changes would),
    then delete the zone. Shared by the offline console REST and the Nano adapter."""
    rec = _zone_rec(store, project, name)
    apex = rec["zone"]["dnsName"]
    extra = [r for r in rec["rrsets"] if not (r["name"] == apex and r["type"] in ("NS", "SOA"))]
    if extra:
        apply_change(store, project, name, {"deletions": extra})
    delete_zone(store, project, name)


def _page(items, query, key):
    try:
        size = int(query.get("maxResults") or 0)
    except ValueError:
        raise _bad(str(query.get("maxResults")), "parameters.maxResults")
    try:
        start = int(query.get("pageToken") or 0)
    except ValueError:
        raise _bad(str(query.get("pageToken")), "parameters.pageToken")
    out = {}
    if size > 0 and start + size < len(items):
        out["nextPageToken"] = str(start + size)
        items = items[start:start + size]
    else:
        items = items[start:]
    out[key] = items
    return out


def list_zones(store, project, query):
    zs = sorted((r for k, r in store.zones.items() if k.startswith(project + "/")), key=lambda r: r["zone"]["name"])
    if query.get("dnsName"):
        zs = [r for r in zs if r["zone"]["dnsName"] == query["dnsName"]]
    out = _page([_zone_view(r) for r in zs], query, "managedZones")
    return dict(kind="dns#managedZonesListResponse", header={"operationId": ""}, **out)


# ── record sets + changes ──────────────────────────────────────────────────
def _bump_soa(rrsets):
    for r in rrsets:
        if r["type"] == "SOA":
            f = r["rrdatas"][0].split()
            if len(f) == 7 and f[2].isdigit():
                f[2] = str(int(f[2]) + 1)
                r["rrdatas"] = [" ".join(f)]


def apply_change(store, project, zone_name, payload):
    """Atomic change: validate everything, then apply deletions followed by additions."""
    rec = _zone_rec(store, project, zone_name)
    dns_name = rec["zone"]["dnsName"]
    adds_in, dels_in = payload.get("additions") or [], payload.get("deletions") or []
    if not adds_in and not dels_in:
        raise _bad("", "entity.change")
    if len(adds_in) > QUOTA["rrsetAdditionsPerChange"] or len(dels_in) > QUOTA["rrsetDeletionsPerChange"]:
        raise _E(403, "PERMISSION_DENIED", "quotaExceeded", "Quota exceeded for rrset changes.")
    adds = [_norm_rrset(r, dns_name, "entity.change.additions[%d]" % i) for i, r in enumerate(adds_in)]
    dels = [_norm_rrset(r, dns_name, "entity.change.deletions[%d]" % i) for i, r in enumerate(dels_in)]
    cur = {_key(r["name"], r["type"]): r for r in rec["rrsets"]}
    for i, d in enumerate(dels):
        have = cur.get(_key(d["name"], d["type"]))
        if have is None:
            raise _E(404, "NOT_FOUND", "notFound",
                     "The 'entity.change.deletions[%d]' resource named '%s (%s)' does not exist."
                     % (i, d["name"], d["type"]))
        if not _same(have, d):
            raise _E(412, "FAILED_PRECONDITION", "conditionNotMet",
                     "Precondition not met for 'entity.change.deletions[%d]'" % i)
        del cur[_key(d["name"], d["type"])]
    for i, a in enumerate(adds):
        k = _key(a["name"], a["type"])
        if k in cur:
            raise _E(409, "ALREADY_EXISTS", "alreadyExists",
                     "The resource record set 'entity.change.additions[%d]' named '%s (%s)' already exists"
                     % (i, a["name"], a["type"]))
        if a["type"] == "CNAME" and any(c[0] == k[0] for c in cur):
            raise _E(409, "ALREADY_EXISTS", "alreadyExists",
                     "The 'entity.change.additions[%d]' CNAME at '%s' conflicts with other record sets." % (i, a["name"]))
        if a["type"] != "CNAME" and (k[0], "CNAME") in cur:
            raise _E(409, "ALREADY_EXISTS", "alreadyExists",
                     "The 'entity.change.additions[%d]' at '%s' conflicts with an existing CNAME." % (i, a["name"]))
        cur[k] = a
    for t in ("NS", "SOA"):
        if (dns_name.lower(), t) not in cur:
            raise _bad(dns_name, "entity.change.deletions: the apex %s record set must remain" % t)
    touched_soa = any(r["type"] == "SOA" for r in adds + dels)
    rec["rrsets"] = list(cur.values())
    if not touched_soa:
        _bump_soa(rec["rrsets"])
    cid = str(rec["next_change"])
    rec["next_change"] += 1
    change = {"kind": "dns#change", "id": cid, "startTime": _ts(), "status": "done", "isServing": True}
    if adds:
        change["additions"] = adds
    if dels:
        change["deletions"] = dels
    rec["changes"].append(change)
    return change


def _find_rrset(rec, name, rtype):
    for r in rec["rrsets"]:
        if r["name"].lower() == name.lower() and r["type"] == rtype:
            return r
    raise _E(404, "NOT_FOUND", "notFound",
             "The 'parameters.name' resource named '%s (%s)' does not exist." % (name, rtype))


def list_rrsets(store, project, zone_name, query):
    rec = _zone_rec(store, project, zone_name)
    rr = sorted(rec["rrsets"], key=_sort_key)
    name, rtype = query.get("name"), query.get("type")
    if rtype and not name:
        raise _bad("", "parameters.name")
    if name:
        rr = [r for r in rr if r["name"].lower() == name.lower()]
    if rtype:
        rr = [r for r in rr if r["type"] == rtype]
    out = _page(json.loads(json.dumps(rr)), query, "rrsets")
    return dict(kind="dns#resourceRecordSetsListResponse", header={"operationId": ""}, **out)


def list_changes(store, project, zone_name, query):
    rec = _zone_rec(store, project, zone_name)
    ch = sorted(rec["changes"], key=lambda c: int(c["id"]), reverse=query.get("sortOrder") == "descending")
    out = _page(json.loads(json.dumps(ch)), query, "changes")
    return dict(kind="dns#changesListResponse", header={"operationId": ""}, **out)


def rrset_op(store, project, zone_name, method, name, rtype, payload):
    """rrsets.create / get / patch / delete — each mutation is recorded as a Change."""
    rec = _zone_rec(store, project, zone_name)
    if method == "POST":
        apply_change(store, project, zone_name, {"additions": [payload]})
        return _find_rrset(rec, payload["name"], str(payload["type"]).upper())
    rtype = (rtype or "").upper()
    cur = _find_rrset(rec, name, rtype)
    if method == "GET":
        return json.loads(json.dumps(cur))
    if method == "DELETE":
        apply_change(store, project, zone_name, {"deletions": [cur]})
        return {}
    if method == "PATCH":
        new = dict(cur, **{k: v for k, v in payload.items() if k in ("ttl", "rrdatas", "signatureRrdatas")})
        apply_change(store, project, zone_name, {"deletions": [cur], "additions": [new]})
        return _find_rrset(rec, name, rtype)
    raise _E(405, "UNIMPLEMENTED", "methodNotAllowed", "Method %s not allowed on rrset." % method)


# ── dnsKeys (DNSSEC) ───────────────────────────────────────────────────────
def dns_keys(store, project, zone_name):
    rec = _zone_rec(store, project, zone_name)
    z = rec["zone"]
    if (z.get("dnssecConfig") or {}).get("state") != "on":
        return []
    keys = []
    for kind, tag in (("keySigning", 2371), ("zoneSigning", 38207)):
        kid = _num_id(project, zone_name, kind)
        keys.append({"kind": "dns#dnsKey", "id": str(int(kid) % 100000), "type": kind, "algorithm": "rsasha256",
                     "keyLength": 2048 if kind == "keySigning" else 1024, "isActive": True,
                     "creationTime": z["creationTime"], "keyTag": tag + int(kid) % 1000,
                     "publicKey": "AwEAAa" + hashlib.sha256(kid.encode()).hexdigest()[:40]})
    return keys


# ── policies ───────────────────────────────────────────────────────────────
def _pkey(project, name):
    return "%s/%s" % (project, name)


def _policy(store, project, name):
    p = store.policies.get(_pkey(project, name))
    if p is None:
        raise _E(404, "NOT_FOUND", "notFound", "The 'parameters.policy' resource named '%s' does not exist." % name)
    return p


_POLICY_FIELDS = ("description", "enableInboundForwarding", "enableLogging", "networks", "alternativeNameServerConfig")


def create_policy(store, project, payload):
    name = payload.get("name")
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise _bad(str(name), "entity.policy.name")
    if _pkey(project, name) in store.policies:
        raise _E(409, "ALREADY_EXISTS", "alreadyExists", "The resource 'entity.policy' named '%s' already exists" % name)
    p = {"kind": "dns#policy", "id": _num_id(project, "policy", name), "name": name,
         "description": payload.get("description") or "",
         "enableInboundForwarding": bool(payload.get("enableInboundForwarding")),
         "enableLogging": bool(payload.get("enableLogging")),
         "networks": [dict(n, kind="dns#policyNetwork") for n in payload.get("networks") or []]}
    if payload.get("alternativeNameServerConfig"):
        p["alternativeNameServerConfig"] = payload["alternativeNameServerConfig"]
    store.policies[_pkey(project, name)] = p
    return p


def patch_policy(store, project, name, payload):
    p = _policy(store, project, name)
    for k in _POLICY_FIELDS:
        if k in payload:
            p[k] = [dict(n, kind="dns#policyNetwork") for n in payload[k]] if k == "networks" else payload[k]
    return p


def delete_policy(store, project, name):
    p = _policy(store, project, name)
    if p.get("networks"):
        raise _E(400, "FAILED_PRECONDITION", "containerNotEmpty",
                 "Policy '%s' is attached to one or more networks and cannot be deleted." % name)
    del store.policies[_pkey(project, name)]


# ── console views ──────────────────────────────────────────────────────────
def console_view(rec):
    """Flat row for the console grid / detail: every column filled."""
    z = rec["zone"]
    v = json.loads(json.dumps(z))
    public = z.get("visibility", "public") == "public"
    dnssec = (z.get("dnssecConfig") or {}).get("state", "off")
    v.update({
        "id": z["name"], "dns_name": z["dnsName"],
        "zone_type": "Public" if public else "Private",
        "description_text": z.get("description") or "No description",
        "record_count": len(rec["rrsets"]),
        "name_servers_text": ", ".join(z.get("nameServers") or []) or "Not applicable (private zone)",
        "dnssec_state": {"on": "On", "off": "Off", "transfer": "Transfer"}.get(dnssec, dnssec),
        "created": z["creationTime"],
        "records": [{"name": r["name"], "type": r["type"], "ttl": r.get("ttl", DEFAULT_TTL),
                     "data": "\n".join(r.get("rrdatas") or [])} for r in sorted(rec["rrsets"], key=_sort_key)],
    })
    return v


def list_all(store, project=None):
    return [console_view(r) for k, r in sorted(store.zones.items())
            if project is None or k.startswith(project + "/")]


def zone_from_form(b):
    """Console create form (catalog createFields) → REST ManagedZone, shared by the
    offline console REST and the Nano adapter so both consoles create identical zones."""
    dns = str(b.get("dnsName") or "").strip()
    if dns and not dns.endswith("."):
        dns += "."
    z = {"name": str(b.get("name") or "").strip(), "dnsName": dns,
         "description": str(b.get("description") or ""),
         "visibility": str(b.get("visibility") or "public").lower()}
    if z["visibility"] == "private":
        net = str(b.get("network") or "").strip()
        z["privateVisibilityConfig"] = {"networks": [{"networkUrl": net}] if net else []}
    elif str(b.get("dnssec") or "").lower() in ("on", "true", "yes"):
        z["dnssecConfig"] = {"state": "on"}
    if isinstance(b.get("labels"), dict) and b["labels"]:
        z["labels"] = b["labels"]
    return z


# ── dispatch ───────────────────────────────────────────────────────────────
def dispatch(store, method, path, query=None, headers=None, body=b""):
    return _dispatch(store, method, path, query or {}, headers or {}, body)


def _dispatch(store, method, path, query, headers, body):
    method = method.upper()
    for k, v in headers.items():   # REST clients without PATCH tunnel it over POST
        if k.lower() == "x-http-method-override" and method == "POST" and v:
            method = str(v).upper()
    try:
        payload = json.loads(body.decode("utf-8")) if body else {}
    except Exception:
        return _err(400, "INVALID_ARGUMENT", "parseError", "Invalid JSON payload received.")
    if not isinstance(payload, dict):
        payload = {}
    p = path.split("?", 1)[0].strip("/")
    segs = [s for s in p.split("/") if s]
    if len(segs) >= 2 and segs[0] == "dns" and segs[1] in API_VERSIONS:
        segs = segs[2:]
    if len(segs) < 2 or segs[0] != "projects":
        return _err(404, "NOT_FOUND", "notFound", "Unknown path: %s" % path)
    project, rest = segs[1], segs[2:]
    try:
        if not rest:
            if method != "GET":
                return _err(405, "UNIMPLEMENTED", "methodNotAllowed", "Method %s not allowed." % method)
            return _json(200, {"kind": "dns#project", "id": project, "number": _num_id("project", project)[:12],
                               "quota": QUOTA})
        coll = rest[0]
        if coll == "managedZones":
            return _zones(store, method, project, rest[1:], query, payload)
        if coll == "policies":
            return _policies(store, method, project, rest[1:], payload, query)
        return _err(404, "NOT_FOUND", "notFound", "Unknown path: %s" % path)
    except _E as e:
        return _err(e.status, e.gcp_status, e.reason, e.message)


def _zones(store, method, project, rest, query, payload):
    if not rest:
        if method == "POST":
            return _json(200, create_zone(store, project, payload))
        if method == "GET":
            return _json(200, list_zones(store, project, query))
        raise _E(405, "UNIMPLEMENTED", "methodNotAllowed", "Method %s not allowed on managedZones." % method)
    zname = rest[0]
    if len(rest) == 1:
        if method == "GET":
            return _json(200, _zone_view(_zone_rec(store, project, zname)))
        if method in ("PATCH", "PUT"):
            return _json(200, patch_zone(store, project, zname, payload, replace=method == "PUT"))
        if method == "DELETE":
            delete_zone(store, project, zname)
            return _empty()
        raise _E(405, "UNIMPLEMENTED", "methodNotAllowed", "Method %s not allowed on managedZone." % method)
    sub = rest[1]
    if sub == "rrsets":
        if len(rest) == 2:
            if method == "GET":
                return _json(200, list_rrsets(store, project, zname, query))
            if method == "POST":
                return _json(200, rrset_op(store, project, zname, "POST", None, None, payload))
        elif len(rest) == 4 and method in ("GET", "PATCH", "DELETE"):
            return _json(200, rrset_op(store, project, zname, method, rest[2], rest[3], payload))
    elif sub == "changes":
        if len(rest) == 2:
            if method == "POST":
                return _json(200, apply_change(store, project, zname, payload))
            if method == "GET":
                return _json(200, list_changes(store, project, zname, query))
        elif len(rest) == 3 and method == "GET":
            for c in _zone_rec(store, project, zname)["changes"]:
                if c["id"] == rest[2]:
                    return _json(200, c)
            raise _E(404, "NOT_FOUND", "notFound",
                     "The 'parameters.changeId' resource named '%s' does not exist." % rest[2])
    elif sub == "dnsKeys" and method == "GET":
        keys = dns_keys(store, project, zname)
        if len(rest) == 2:
            return _json(200, {"kind": "dns#dnsKeysListResponse", "header": {"operationId": ""}, "dnsKeys": keys})
        for k in keys:
            if k["id"] == rest[2]:
                return _json(200, k)
        raise _E(404, "NOT_FOUND", "notFound", "The 'parameters.dnsKeyId' resource named '%s' does not exist." % rest[2])
    return _err(404, "NOT_FOUND", "notFound", "Unknown path: /%s" % "/".join(["projects", project, "managedZones"] + rest))


def _policies(store, method, project, rest, payload, query):
    if not rest:
        if method == "POST":
            return _json(200, create_policy(store, project, payload))
        if method == "GET":
            ps = sorted((p for k, p in store.policies.items() if k.startswith(project + "/")), key=lambda p: p["name"])
            out = _page(json.loads(json.dumps(ps)), query, "policies")
            return _json(200, dict(kind="dns#policiesListResponse", header={"operationId": ""}, **out))
        raise _E(405, "UNIMPLEMENTED", "methodNotAllowed", "Method %s not allowed on policies." % method)
    name = rest[0]
    if method == "GET":
        return _json(200, _policy(store, project, name))
    if method == "PATCH":
        return _json(200, {"kind": "dns#policiesPatchResponse", "header": {"operationId": ""},
                           "policy": patch_policy(store, project, name, payload)})
    if method == "PUT":
        return _json(200, {"kind": "dns#policiesUpdateResponse", "header": {"operationId": ""},
                           "policy": patch_policy(store, project, name, payload)})
    if method == "DELETE":
        delete_policy(store, project, name)
        return _empty()
    raise _E(405, "UNIMPLEMENTED", "methodNotAllowed", "Method %s not allowed on policy." % method)
