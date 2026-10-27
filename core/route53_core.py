"""Route 53 core — substrate-independent engine for the AWS Route 53 API.

Targets the NATIVE Route 53 wire — **REST-XML** (`/2013-04-01/hostedzone`, …, XML
request and response bodies in https://route53.amazonaws.com/doc/2013-04-01/) — so an
unmodified boto3 / aws-cli / aws-sdk-java-v2 / aws-sdk-go-v2 client works with only
the endpoint overridden. Request / response field names and error codes follow the
botocore model (`route53/2013-04-01/service-2.json`).

Pure Python (stdlib only — no fastapi / boto3 / socket), so the SAME file runs on the
offline appliance and in Nano (Pyodide). State lives in a `Route53Store` (plain dicts,
a `persist()` hook) — the seam the offline appliance backs with the space-scoped state
and Nano backs with its shared store registry.

Backend: in-process engine + (offline, optional) CoreDNS. The engine is the API and
the source of truth; `zone_files()` renders every hosted zone as an RFC 1035 zone file
so the shared CoreDNS container can answer `dig` for the records you create. Alias
records are expanded to the addresses of their in-account target. `TestDNSAnswer`
resolves inside the engine, so Nano (no CoreDNS) answers it too.

Operations: Create/Get/List/ListByName/ListByVPC/Count/UpdateComment/Delete HostedZone,
Associate/Disassociate VPC, ChangeResourceRecordSets (CREATE/DELETE/UPSERT, atomic),
ListResourceRecordSets, GetChange, Create/Get/List/Update/Delete HealthCheck (+ status,
count, last failure reason), reusable delegation sets, query-logging configs, tags
(Change/List/ListForResources), GetDNSSEC, GetAccountLimit, GetHostedZoneLimit,
GetCheckerIpRanges, TestDNSAnswer.

The `console_*` helpers at the bottom are the flat REST view the web consoles use
(`/api/aws/route53/...`), shared by the offline server and Nano.
"""
from __future__ import annotations

import hashlib
import re
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import unquote
from xml.sax.saxutils import escape as _esc

NS = "https://route53.amazonaws.com/doc/2013-04-01/"
DEFAULT_ACCOUNT_ID = "123456789012"
REGION = "us-east-1"
PREFIX = "/2013-04-01"

RR_TYPES = ("SOA", "A", "TXT", "NS", "CNAME", "MX", "NAPTR", "PTR", "SRV", "SPF", "AAAA", "CAA", "DS",
            "TLSA", "SSHFP", "SVCB", "HTTPS")
HC_TYPES = ("HTTP", "HTTPS", "HTTP_STR_MATCH", "HTTPS_STR_MATCH", "TCP", "CALCULATED",
            "CLOUDWATCH_METRIC", "RECOVERY_CONTROL")
_REGIONS = ("us-east-1", "us-west-1", "us-west-2", "eu-west-1", "ap-southeast-1", "ap-southeast-2",
            "ap-northeast-1", "sa-east-1")
_NS_TLDS = ("com", "net", "org", "co.uk")
_CHECKER_IPS = ["15.177.0.0/18", "54.183.255.128/26", "54.228.16.0/26", "54.232.40.64/26",
                "54.241.32.64/26", "54.243.31.192/26", "54.244.52.192/26", "54.245.168.0/26"]
_LIMITS = {"MAX_HEALTH_CHECKS_BY_OWNER": 200, "MAX_HOSTED_ZONES_BY_OWNER": 500,
           "MAX_TRAFFIC_POLICY_INSTANCES_BY_OWNER": 5, "MAX_REUSABLE_DELEGATION_SETS_BY_OWNER": 100,
           "MAX_TRAFFIC_POLICIES_BY_OWNER": 50}
_ZONE_LIMITS = {"MAX_RRSETS_BY_ZONE": 10000, "MAX_VPCS_ASSOCIATED_BY_ZONE": 100}


@dataclass
class Route53Response:
    status: int = 200
    body: bytes = b""
    headers: dict = field(default_factory=dict)
    media_type: str = "text/xml"


class Route53Error(Exception):
    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.status = status


class Route53Store:
    """State seam: plain dicts the engine reads/writes. `persist()` is called after
    every mutation."""

    def __init__(self, account_id: str = DEFAULT_ACCOUNT_ID, region: str = REGION) -> None:
        self.account_id = account_id
        self.region = region
        self.hosted_zones: dict[str, dict] = {}      # zone id → record (incl. `records`)
        self.changes: dict[str, dict] = {}           # change id → ChangeInfo
        self.health_checks: dict[str, dict] = {}
        self.delegation_sets: dict[str, dict] = {}
        self.query_logging: dict[str, dict] = {}
        self.tags: dict[str, dict] = {}              # "hostedzone/Z…" → {key: value}

    def persist(self) -> None:
        pass


# ── helpers ────────────────────────────────────────────────────────────────
def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _req_id() -> str:
    return str(uuid.uuid4())


def _rid(prefix: str, n: int = 19) -> str:
    return prefix + uuid.uuid4().hex.upper()[:n]


def _t(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    return _esc(str(v))


def _el(tag: str, val=None) -> str:
    return f"<{tag}>{_t(val)}</{tag}>" if val is not None else ""


def norm_name(name: str) -> str:
    """Lower-case, absolute (trailing dot), `\\052` → `*`."""
    n = str(name or "").strip().lower().replace("\\052", "*")
    return n if n.endswith(".") else n + "."


def out_name(name: str) -> str:
    """Route 53 echoes `*` as the octal escape `\\052`."""
    return name.replace("*", "\\052")


def _rev(name: str) -> tuple:
    return tuple(reversed([p for p in name.strip(".").split(".") if p]))


def _short_id(raw: str, kind: str) -> str:
    raw = unquote(str(raw or ""))
    for p in (f"/{kind}/", f"{kind}/"):
        if raw.startswith(p):
            return raw[len(p):]
    return raw


def _valid_domain(name: str) -> bool:
    n = name.rstrip(".")
    if not n or len(n) > 253:
        return False
    for label in n.split("."):
        if not label or len(label) > 63:
            return False
        if not re.fullmatch(r"[a-z0-9_*\-\\0-9]+", label):
            return False
    return True


# ── XML in / out ───────────────────────────────────────────────────────────
def _parse(body: bytes) -> ET.Element:
    try:
        root = ET.fromstring(body or b"")
    except ET.ParseError as e:
        raise Route53Error("InvalidInput", f"Invalid XML in request body: {e}") from None
    for e in root.iter():
        if "}" in e.tag:
            e.tag = e.tag.split("}", 1)[1]
    return root


def _child(e, tag: str):
    return None if e is None else e.find(tag)


def _text(e, tag: str, default=None):
    c = _child(e, tag)
    return default if c is None or c.text is None else c.text.strip()


def _xml(root: str, inner: str = "", status: int = 200, headers: dict | None = None) -> Route53Response:
    head = '<?xml version="1.0"?>\n'
    body = f'{head}<{root} xmlns="{NS}">{inner}</{root}>' if inner or root else head
    return Route53Response(status, body.encode(), dict(headers or {}))


def _error(code: str, message: str, status: int = 400) -> Route53Response:
    body = ('<?xml version="1.0"?>\n'
            f'<ErrorResponse xmlns="{NS}"><Error><Type>Sender</Type><Code>{_esc(code)}</Code>'
            f'<Message>{_esc(message)}</Message></Error><RequestId>{_req_id()}</RequestId></ErrorResponse>')
    return Route53Response(status, body.encode(), {})


# ── record sets ────────────────────────────────────────────────────────────
def _rr_key(name: str, typ: str, setid: str | None) -> str:
    return f"{name}|{typ}|{setid or ''}"


def _parse_rrset(e: ET.Element) -> dict:
    name, typ = _text(e, "Name"), _text(e, "Type")
    if not name or not typ:
        raise Route53Error("InvalidInput", "ResourceRecordSet requires Name and Type")
    rr: dict = {"Name": norm_name(name), "Type": typ.upper()}
    if typ.upper() not in RR_TYPES:
        raise Route53Error("InvalidInput", f"Invalid XML ; cvc-enumeration-valid: Value '{typ}' is not facet-valid with "
                                           "respect to enumeration '[SOA, A, TXT, NS, CNAME, MX, NAPTR, PTR, SRV, SPF, AAAA, CAA, DS]'. "
                                           "It must be a value from the enumeration.")
    for tag in ("SetIdentifier", "Region", "Failover", "HealthCheckId", "TrafficPolicyInstanceId"):
        v = _text(e, tag)
        if v is not None:
            rr[tag] = v
    if _text(e, "Weight") is not None:
        rr["Weight"] = int(_text(e, "Weight"))
    if _text(e, "TTL") is not None:
        rr["TTL"] = int(_text(e, "TTL"))
    if _text(e, "MultiValueAnswer") is not None:
        rr["MultiValueAnswer"] = _text(e, "MultiValueAnswer").lower() == "true"
    g = _child(e, "GeoLocation")
    if g is not None:
        rr["GeoLocation"] = {t: _text(g, t) for t in ("ContinentCode", "CountryCode", "SubdivisionCode") if _text(g, t)}
    a = _child(e, "AliasTarget")
    if a is not None:
        rr["AliasTarget"] = {"HostedZoneId": _text(a, "HostedZoneId", ""), "DNSName": norm_name(_text(a, "DNSName", "")),
                             "EvaluateTargetHealth": (_text(a, "EvaluateTargetHealth", "false") or "false").lower() == "true"}
    recs = _child(e, "ResourceRecords")
    if recs is not None:
        rr["ResourceRecords"] = [_text(r, "Value", "") for r in recs.findall("ResourceRecord")]
    if "AliasTarget" in rr and ("ResourceRecords" in rr or "TTL" in rr):
        raise Route53Error("InvalidInput", "Invalid XML ; Alias resource record sets must not specify TTL or ResourceRecords")
    if "AliasTarget" not in rr:
        if "TTL" not in rr or not rr.get("ResourceRecords"):
            raise Route53Error("InvalidInput", f"Invalid request: Expected exactly one of [AliasTarget, all of [TTL, and ResourceRecords], "
                                               f"or TrafficPolicyInstanceId], but found none in Change with [Action=CREATE, Name={name}, Type={typ}]")
    if rr.get("SetIdentifier") is None and any(k in rr for k in ("Weight", "Region", "Failover", "GeoLocation")):
        raise Route53Error("InvalidInput", f"Invalid request: SetIdentifier is required for routing-policy record {name} ({typ})")
    return rr


def _rr_xml(rr: dict) -> str:
    x = _el("Name", out_name(rr["Name"])) + _el("Type", rr["Type"]) + _el("SetIdentifier", rr.get("SetIdentifier"))
    x += _el("Weight", rr.get("Weight")) + _el("Region", rr.get("Region"))
    g = rr.get("GeoLocation")
    if g:
        x += "<GeoLocation>" + "".join(_el(k, g[k]) for k in ("ContinentCode", "CountryCode", "SubdivisionCode") if k in g) + "</GeoLocation>"
    x += _el("Failover", rr.get("Failover"))
    if "MultiValueAnswer" in rr:
        x += _el("MultiValueAnswer", rr["MultiValueAnswer"])
    x += _el("TTL", rr.get("TTL"))
    if "ResourceRecords" in rr:
        x += "<ResourceRecords>" + "".join(f"<ResourceRecord>{_el('Value', v)}</ResourceRecord>" for v in rr["ResourceRecords"]) + "</ResourceRecords>"
    a = rr.get("AliasTarget")
    if a:
        x += ("<AliasTarget>" + _el("HostedZoneId", a["HostedZoneId"]) + _el("EvaluateTargetHealth", a["EvaluateTargetHealth"]) +
              _el("DNSName", out_name(a["DNSName"])) + "</AliasTarget>")
    x += _el("HealthCheckId", rr.get("HealthCheckId")) + _el("TrafficPolicyInstanceId", rr.get("TrafficPolicyInstanceId"))
    return f"<ResourceRecordSet>{x}</ResourceRecordSet>"


def _nameservers(zid: str, n: int = 4) -> list[str]:
    h = hashlib.sha1(zid.encode()).hexdigest()
    base = int(h[:6], 16)
    out = []
    for i in range(n):
        out.append(f"ns-{(base // (7 + i)) % 2048 + 1}.awsdns-{(base // (3 + i)) % 64:02d}.{_NS_TLDS[i % 4]}.")
    return out


def _default_records(name: str, ns: list[str]) -> dict:
    soa = {"Name": name, "Type": "SOA", "TTL": 900,
           "ResourceRecords": [f"{ns[0]} awsdns-hostmaster.amazon.com. 1 7200 900 1209600 86400"]}
    nsr = {"Name": name, "Type": "NS", "TTL": 172800, "ResourceRecords": list(ns)}
    return {_rr_key(name, "NS", None): nsr, _rr_key(name, "SOA", None): soa}


# ── hosted zones ───────────────────────────────────────────────────────────
def _zone(store, zid: str) -> dict:
    z = store.hosted_zones.get(_short_id(zid, "hostedzone"))
    if z is None:
        raise Route53Error("NoSuchHostedZone", f"No hosted zone found with ID: {_short_id(zid, 'hostedzone')}", 404)
    return z


def _change_info(store, status: str = "PENDING", comment: str | None = None) -> dict:
    cid = _rid("C", 13)
    ci = {"Id": cid, "Status": status, "SubmittedAt": _now(), "Comment": comment}
    store.changes[cid] = ci
    return ci


def _ci_xml(ci: dict, status: str | None = None) -> str:
    return ("<ChangeInfo>" + _el("Id", "/change/" + ci["Id"]) + _el("Status", status or ci["Status"]) +
            _el("SubmittedAt", ci["SubmittedAt"]) + _el("Comment", ci.get("Comment")) + "</ChangeInfo>")


def _zone_xml(z: dict) -> str:
    cfg = "<Config>" + _el("Comment", z.get("Comment")) + _el("PrivateZone", z["PrivateZone"]) + "</Config>"
    return ("<HostedZone>" + _el("Id", "/hostedzone/" + z["Id"]) + _el("Name", out_name(z["Name"])) +
            _el("CallerReference", z["CallerReference"]) + cfg + _el("ResourceRecordSetCount", len(z["records"])) + "</HostedZone>")


def _ds_xml(ds: dict) -> str:
    return ("<DelegationSet>" + _el("Id", "/delegationset/" + ds["Id"] if ds.get("Id") else None) +
            _el("CallerReference", ds.get("CallerReference")) +
            "<NameServers>" + "".join(_el("NameServer", n.rstrip(".")) for n in ds["NameServers"]) + "</NameServers></DelegationSet>")


def _vpc_xml(v: dict, tag: str = "VPC") -> str:
    return f"<{tag}>" + _el("VPCRegion", v.get("VPCRegion")) + _el("VPCId", v.get("VPCId")) + f"</{tag}>"


def _create_hosted_zone(store, m, path, q, body):
    r = _parse(body)
    name = _text(r, "Name")
    if not name:
        raise Route53Error("InvalidInput", "Invalid request: missing required field Name")
    name = norm_name(name)
    if not _valid_domain(name):
        raise Route53Error("InvalidDomainName", f"{name.rstrip('.')} is not a valid DNS domain name")
    ref = _text(r, "CallerReference")
    if not ref:
        raise Route53Error("InvalidInput", "Invalid request: missing required field CallerReference")
    cfg = _child(r, "HostedZoneConfig")
    private = (_text(cfg, "PrivateZone", "false") or "false").lower() == "true"
    vpc = _child(r, "VPC")
    if private and vpc is None:
        raise Route53Error("InvalidInput", "When creating private hosted zone, user must specify VPC information")
    for z in store.hosted_zones.values():
        if z["CallerReference"] == ref:
            raise Route53Error("HostedZoneAlreadyExists", f"A hosted zone has already been created with the specified caller reference.", 409)
    for z in store.hosted_zones.values():
        if z["Name"] == name and z["PrivateZone"] == private and not private:
            pass   # real Route 53 allows duplicate public zone names (distinct delegation sets)
    dsid = _text(r, "DelegationSetId")
    if dsid:
        ds = store.delegation_sets.get(_short_id(dsid, "delegationset"))
        if ds is None:
            raise Route53Error("NoSuchDelegationSet", f"A reusable delegation set with the specified ID does not exist.", 400)
        ns = list(ds["NameServers"])
    else:
        ns = None
    zid = _rid("Z")
    ns = ns or _nameservers(zid)
    z = {"Id": zid, "Name": name, "CallerReference": ref, "Comment": _text(cfg, "Comment"), "PrivateZone": private,
         "NameServers": ns, "DelegationSetId": _short_id(dsid, "delegationset") if dsid else None,
         "VPCs": [], "created": _now(), "records": _default_records(name, ns)}
    if vpc is not None:
        v = {"VPCRegion": _text(vpc, "VPCRegion", store.region), "VPCId": _text(vpc, "VPCId", "")}
        if not v["VPCId"]:
            raise Route53Error("InvalidVPCId", "The VPC ID is invalid or missing.")
        z["VPCs"].append(v)
    store.hosted_zones[zid] = z
    ci = _change_info(store)
    store.persist()
    inner = _zone_xml(z) + _ci_xml(ci) + _ds_xml({"NameServers": ns, "Id": z["DelegationSetId"]})
    inner += "".join(_vpc_xml(v) for v in z["VPCs"])
    return _xml("CreateHostedZoneResponse", inner, 201, {"Location": f"https://route53.amazonaws.com{PREFIX}/hostedzone/{zid}"})


def _get_hosted_zone(store, m, path, q, body):
    z = _zone(store, m.group(1))
    inner = _zone_xml(z) + _ds_xml({"NameServers": z["NameServers"], "Id": z.get("DelegationSetId")})
    if z["VPCs"]:
        inner += "<VPCs>" + "".join(_vpc_xml(v) for v in z["VPCs"]) + "</VPCs>"
    return _xml("GetHostedZoneResponse", inner)


def _page(items: list, marker_ok, maxitems: int, key):
    """Slice `items` after the marker, returning (page, truncated, next_item)."""
    start = 0
    if marker_ok is not None:
        for i, it in enumerate(items):
            if key(it) == marker_ok:
                start = i
                break
    page = items[start:start + maxitems]
    nxt = items[start + maxitems] if len(items) > start + maxitems else None
    return page, nxt is not None, nxt


def _maxitems(q, default=100) -> int:
    try:
        n = int(q.get("maxitems", default))
    except (TypeError, ValueError):
        raise Route53Error("InvalidInput", "Invalid value for maxitems") from None
    return max(1, min(n, 100 if default == 100 else n))


def _list_hosted_zones(store, m, path, q, body):
    zs = sorted(store.hosted_zones.values(), key=lambda z: z["created"] + z["Id"])
    if q.get("delegationsetid"):
        zs = [z for z in zs if z.get("DelegationSetId") == _short_id(q["delegationsetid"], "delegationset")]
    mx = _maxitems(q)
    marker = q.get("marker")
    page, trunc, nxt = _page(zs, marker, mx, lambda z: z["Id"])
    inner = "<HostedZones>" + "".join(_zone_xml(z) for z in page) + "</HostedZones>"
    inner += _el("Marker", marker) + _el("IsTruncated", trunc) + (_el("NextMarker", nxt["Id"]) if nxt else "") + _el("MaxItems", mx)
    return _xml("ListHostedZonesResponse", inner)


def _list_hosted_zones_by_name(store, m, path, q, body):
    zs = sorted(store.hosted_zones.values(), key=lambda z: (_rev(z["Name"]), z["Id"]))
    dns = norm_name(q["dnsname"]) if q.get("dnsname") else None
    if dns:
        zs = [z for z in zs if (_rev(z["Name"]), z["Id"]) >= (_rev(dns), _short_id(q.get("hostedzoneid", ""), "hostedzone"))]
    mx = _maxitems(q)
    page = zs[:mx]
    nxt = zs[mx] if len(zs) > mx else None
    inner = "<HostedZones>" + "".join(_zone_xml(z) for z in page) + "</HostedZones>"
    inner += _el("DNSName", out_name(dns) if dns else None) + _el("HostedZoneId", _short_id(q.get("hostedzoneid", ""), "hostedzone") or None)
    inner += _el("IsTruncated", nxt is not None)
    if nxt:
        inner += _el("NextDNSName", out_name(nxt["Name"])) + _el("NextHostedZoneId", nxt["Id"])
    inner += _el("MaxItems", mx)
    return _xml("ListHostedZonesByNameResponse", inner)


def _list_hosted_zones_by_vpc(store, m, path, q, body):
    vid, vreg = q.get("vpcid"), q.get("vpcregion")
    if not vid or not vreg:
        raise Route53Error("InvalidInput", "Invalid request: vpcid and vpcregion are required")
    zs = [z for z in sorted(store.hosted_zones.values(), key=lambda z: z["created"] + z["Id"])
          if any(v["VPCId"] == vid and v["VPCRegion"] == vreg for v in z["VPCs"])]
    mx = _maxitems(q)
    page = zs[:mx]
    inner = "<HostedZoneSummaries>" + "".join(
        "<HostedZoneSummary>" + _el("HostedZoneId", z["Id"]) + _el("Name", out_name(z["Name"])) +
        f"<Owner>{_el('OwningAccount', store.account_id)}</Owner></HostedZoneSummary>" for z in page) + "</HostedZoneSummaries>"
    inner += _el("MaxItems", mx) + (_el("NextToken", page[-1]["Id"]) if len(zs) > mx else "")
    return _xml("ListHostedZonesByVPCResponse", inner)


def _get_hosted_zone_count(store, m, path, q, body):
    return _xml("GetHostedZoneCountResponse", _el("HostedZoneCount", len(store.hosted_zones)))


def _update_hosted_zone_comment(store, m, path, q, body):
    z = _zone(store, m.group(1))
    r = _parse(body)
    z["Comment"] = _text(r, "Comment")
    store.persist()
    return _xml("UpdateHostedZoneCommentResponse", _zone_xml(z))


def _delete_hosted_zone(store, m, path, q, body):
    z = _zone(store, m.group(1))
    extra = [r for r in z["records"].values() if not (r["Type"] in ("NS", "SOA") and r["Name"] == z["Name"])]
    if extra:
        raise Route53Error("HostedZoneNotEmpty", "The specified hosted zone contains non-required resource record sets and so cannot be deleted.")
    del store.hosted_zones[z["Id"]]
    store.tags.pop(f"hostedzone/{z['Id']}", None)
    for lid, cfg in list(store.query_logging.items()):
        if cfg["HostedZoneId"] == z["Id"]:
            del store.query_logging[lid]
    ci = _change_info(store)
    store.persist()
    return _xml("DeleteHostedZoneResponse", _ci_xml(ci))


def _assoc_vpc(store, m, path, q, body, add: bool):
    z = _zone(store, m.group(1))
    r = _parse(body)
    vpc = _child(r, "VPC")
    v = {"VPCRegion": _text(vpc, "VPCRegion", store.region), "VPCId": _text(vpc, "VPCId", "")}
    if not v["VPCId"]:
        raise Route53Error("InvalidInput", "Invalid request: VPC is required")
    if not z["PrivateZone"]:
        raise Route53Error("InvalidInput", "The specified hosted zone is a public hosted zone, not a private one.")
    have = [x for x in z["VPCs"] if x["VPCId"] == v["VPCId"]]
    if add:
        if have:
            raise Route53Error("ConflictingDomainExists", "The VPC is already associated with the hosted zone.", 400)
        z["VPCs"].append(v)
    else:
        if not have:
            raise Route53Error("VPCAssociationNotFound", "The specified VPC and hosted zone are not currently associated.", 404)
        if len(z["VPCs"]) == 1:
            raise Route53Error("LastVPCAssociation", "The VPC that you're trying to disassociate from the private hosted zone is the last VPC that is associated with the hosted zone.")
        z["VPCs"] = [x for x in z["VPCs"] if x["VPCId"] != v["VPCId"]]
    ci = _change_info(store, comment=_text(r, "Comment"))
    store.persist()
    return _xml("AssociateVPCWithHostedZoneResponse" if add else "DisassociateVPCFromHostedZoneResponse", _ci_xml(ci))


# ── record sets: change / list ─────────────────────────────────────────────
def _msg(rr: dict, what: str) -> str:
    sid = f", SetIdentifier='{rr['SetIdentifier']}'" if rr.get("SetIdentifier") else ""
    return f"[Tried to {what} resource record set [name='{out_name(rr['Name'])}', type='{rr['Type']}'{sid}]"


def _change_rrsets(store, m, path, q, body):
    z = _zone(store, m.group(1))
    r = _parse(body)
    batch = _child(r, "ChangeBatch")
    if batch is None:
        raise Route53Error("InvalidInput", "Invalid request: ChangeBatch is required")
    comment = _text(batch, "Comment")
    changes = []
    for c in (_child(batch, "Changes") or []):
        action = (_text(c, "Action", "") or "").upper()
        if action not in ("CREATE", "DELETE", "UPSERT"):
            raise Route53Error("InvalidInput", f"Invalid XML ; cvc-enumeration-valid: Value '{action}' is not facet-valid with respect to enumeration '[CREATE, DELETE, UPSERT]'.")
        rs = _child(c, "ResourceRecordSet")
        if rs is None:
            raise Route53Error("InvalidInput", "Invalid request: ResourceRecordSet is required")
        changes.append((action, _parse_rrset(rs) if action != "DELETE" else _parse_delete(rs)))
    if not changes:
        raise Route53Error("InvalidInput", "Invalid request: ChangeBatch must contain at least one Change")
    work = {k: dict(v) for k, v in z["records"].items()}
    msgs: list[str] = []
    for action, rr in changes:
        if not (rr["Name"] == z["Name"] or rr["Name"].endswith("." + z["Name"])):
            msgs.append(f"[RRSet with DNS name {out_name(rr['Name'])} is not permitted in zone {out_name(z['Name'])}.]")
            continue
        k = _rr_key(rr["Name"], rr["Type"], rr.get("SetIdentifier"))
        cur = work.get(k)
        if action == "CREATE":
            if cur is not None:
                msgs.append(_msg(rr, "create") + " but it already exists]")
                continue
            work[k] = rr
        elif action == "UPSERT":
            work[k] = rr
        else:
            if cur is None:
                msgs.append(_msg(rr, "delete") + " but it was not found]")
                continue
            if rr["Type"] in ("SOA",) and rr["Name"] == z["Name"]:
                msgs.append(_msg(rr, "delete") + " but it is required]")
                continue
            if not _same_values(cur, rr):
                msgs.append(_msg(rr, "delete") + " but the values provided do not match the current values]")
                continue
            del work[k]
    if not msgs:   # CNAME may not coexist with other types at the same name
        by_name: dict[str, set] = {}
        for rr in work.values():
            by_name.setdefault(rr["Name"], set()).add((rr["Type"], rr.get("SetIdentifier")))
        for name, ts in by_name.items():
            if any(t == "CNAME" and not s for t, s in ts) and any(t != "CNAME" for t, _ in ts):
                msgs.append(f"[RRSet of type CNAME with DNS name {out_name(name)} is not permitted as it conflicts with other records with the same DNS name in zone {out_name(z['Name'])}.]")
                break
    if msgs:
        raise Route53Error("InvalidChangeBatch", " ".join(msgs))
    z["records"] = work
    ci = _change_info(store, comment=comment)
    store.persist()
    return _xml("ChangeResourceRecordSetsResponse", _ci_xml(ci))


def _parse_delete(e: ET.Element) -> dict:
    """DELETE carries the full existing rrset; only identity + values matter."""
    rr: dict = {"Name": norm_name(_text(e, "Name", "")), "Type": (_text(e, "Type", "") or "").upper()}
    if not rr["Name"] or not rr["Type"]:
        raise Route53Error("InvalidInput", "ResourceRecordSet requires Name and Type")
    if _text(e, "SetIdentifier"):
        rr["SetIdentifier"] = _text(e, "SetIdentifier")
    if _child(e, "ResourceRecords") is not None:
        rr["ResourceRecords"] = [_text(x, "Value", "") for x in _child(e, "ResourceRecords").findall("ResourceRecord")]
    if _text(e, "TTL") is not None:
        rr["TTL"] = int(_text(e, "TTL"))
    a = _child(e, "AliasTarget")
    if a is not None:
        rr["AliasTarget"] = {"HostedZoneId": _text(a, "HostedZoneId", ""), "DNSName": norm_name(_text(a, "DNSName", ""))}
    return rr


def _same_values(cur: dict, rr: dict) -> bool:
    if "AliasTarget" in cur or "AliasTarget" in rr:
        return (cur.get("AliasTarget") or {}).get("DNSName") == (rr.get("AliasTarget") or {}).get("DNSName")
    if rr.get("TTL") is not None and cur.get("TTL") != rr["TTL"]:
        return False
    return sorted(cur.get("ResourceRecords", [])) == sorted(rr.get("ResourceRecords", []))


def _sorted_records(z: dict) -> list[dict]:
    return sorted(z["records"].values(), key=lambda r: (_rev(r["Name"]), r["Type"], r.get("SetIdentifier") or ""))


def _list_rrsets(store, m, path, q, body):
    z = _zone(store, m.group(1))
    recs = _sorted_records(z)
    if q.get("type") and not q.get("name"):
        raise Route53Error("InvalidInput", "Invalid request: type requires name")
    if q.get("name"):
        sn = norm_name(q["name"])
        st = (q.get("type") or "").upper()
        sid = q.get("identifier") or ""
        recs = [r for r in recs if (_rev(r["Name"]), r["Type"], r.get("SetIdentifier") or "") >= (_rev(sn), st, sid)]
    mx = _maxitems(q)
    page = recs[:mx]
    nxt = recs[mx] if len(recs) > mx else None
    inner = "<ResourceRecordSets>" + "".join(_rr_xml(r) for r in page) + "</ResourceRecordSets>"
    inner += _el("IsTruncated", nxt is not None)
    if nxt:
        inner += _el("NextRecordName", out_name(nxt["Name"])) + _el("NextRecordType", nxt["Type"]) + _el("NextRecordIdentifier", nxt.get("SetIdentifier"))
    inner += _el("MaxItems", mx)
    return _xml("ListResourceRecordSetsResponse", inner)


def _get_change(store, m, path, q, body):
    cid = _short_id(m.group(1), "change")
    ci = store.changes.get(cid)
    if ci is None:
        raise Route53Error("NoSuchChange", f"Could not find change with ID {cid}", 404)
    # Changes propagate instantly: the first Get after submit already reports INSYNC.
    ci["Status"] = "INSYNC"
    return _xml("GetChangeResponse", _ci_xml(ci))


# ── health checks ──────────────────────────────────────────────────────────
_HC_ORDER = ("IPAddress", "Port", "Type", "ResourcePath", "FullyQualifiedDomainName", "SearchString", "RequestInterval",
             "FailureThreshold", "MeasureLatency", "Inverted", "Disabled", "HealthThreshold", "ChildHealthChecks",
             "EnableSNI", "Regions", "AlarmIdentifier", "InsufficientDataHealthStatus", "RoutingControlArn")
_HC_INT = ("Port", "RequestInterval", "FailureThreshold", "HealthThreshold")
_HC_BOOL = ("MeasureLatency", "Inverted", "Disabled", "EnableSNI")


def _hc_from_xml(cfg: ET.Element) -> dict:
    c: dict = {}
    for k in _HC_ORDER:
        e = _child(cfg, k)
        if e is None:
            continue
        if k == "ChildHealthChecks":
            c[k] = [(x.text or "").strip() for x in e.findall("ChildHealthCheck")]
        elif k == "Regions":
            c[k] = [(x.text or "").strip() for x in e.findall("Region")]
        elif k == "AlarmIdentifier":
            c[k] = {"Region": _text(e, "Region", ""), "Name": _text(e, "Name", "")}
        elif k in _HC_INT:
            c[k] = int(e.text)
        elif k in _HC_BOOL:
            c[k] = (e.text or "").strip().lower() == "true"
        else:
            c[k] = (e.text or "").strip()
    return c


def _hc_config_xml(c: dict) -> str:
    x = ""
    for k in _HC_ORDER:
        if k not in c:
            continue
        v = c[k]
        if k == "ChildHealthChecks":
            x += "<ChildHealthChecks>" + "".join(_el("ChildHealthCheck", i) for i in v) + "</ChildHealthChecks>"
        elif k == "Regions":
            x += "<Regions>" + "".join(_el("Region", i) for i in v) + "</Regions>"
        elif k == "AlarmIdentifier":
            x += "<AlarmIdentifier>" + _el("Region", v["Region"]) + _el("Name", v["Name"]) + "</AlarmIdentifier>"
        else:
            x += _el(k, v)
    return "<HealthCheckConfig>" + x + "</HealthCheckConfig>"


def _hc_xml(h: dict) -> str:
    return ("<HealthCheck>" + _el("Id", h["Id"]) + _el("CallerReference", h["CallerReference"]) + _hc_config_xml(h["Config"]) +
            _el("HealthCheckVersion", h["Version"]) + "</HealthCheck>")


def _hc(store, hid: str) -> dict:
    h = store.health_checks.get(unquote(hid))
    if h is None:
        raise Route53Error("NoSuchHealthCheck", f"A health check with id {hid} does not exist.", 404)
    return h


def _hc_defaults(c: dict) -> dict:
    t = c.get("Type")
    if t not in HC_TYPES:
        raise Route53Error("InvalidInput", f"Invalid XML ; cvc-enumeration-valid: Value '{t}' is not facet-valid with respect to enumeration "
                                           f"'{list(HC_TYPES)}'. It must be a value from the enumeration.")
    if t not in ("CALCULATED", "CLOUDWATCH_METRIC", "RECOVERY_CONTROL") and not (c.get("IPAddress") or c.get("FullyQualifiedDomainName")):
        raise Route53Error("InvalidInput", "Invalid request: IPAddress or FullyQualifiedDomainName must be specified for this health check type")
    out = dict(c)
    if t in ("HTTP", "HTTP_STR_MATCH"):
        out.setdefault("Port", 80)
    if t in ("HTTPS", "HTTPS_STR_MATCH"):
        out.setdefault("Port", 443)
        out.setdefault("EnableSNI", True)
    if t in ("HTTP", "HTTPS", "HTTP_STR_MATCH", "HTTPS_STR_MATCH"):
        out.setdefault("ResourcePath", "/")
    if t not in ("CALCULATED", "CLOUDWATCH_METRIC", "RECOVERY_CONTROL"):
        out.setdefault("RequestInterval", 30)
        out.setdefault("FailureThreshold", 3)
        out.setdefault("MeasureLatency", False)
    out.setdefault("Inverted", False)
    out.setdefault("Disabled", False)
    if t == "CALCULATED":
        out.setdefault("HealthThreshold", 1)
        out.setdefault("ChildHealthChecks", [])
    return out


def _create_health_check(store, m, path, q, body):
    r = _parse(body)
    ref = _text(r, "CallerReference")
    cfg = _child(r, "HealthCheckConfig")
    if not ref or cfg is None:
        raise Route53Error("InvalidInput", "Invalid request: CallerReference and HealthCheckConfig are required")
    for h in store.health_checks.values():
        if h["CallerReference"] == ref:
            raise Route53Error("HealthCheckAlreadyExists", "A health check with the specified caller reference already exists.", 409)
    if len(store.health_checks) >= _LIMITS["MAX_HEALTH_CHECKS_BY_OWNER"]:
        raise Route53Error("TooManyHealthChecks", "You have reached the maximum number of active health checks for this account.")
    h = {"Id": str(uuid.uuid4()), "CallerReference": ref, "Config": _hc_defaults(_hc_from_xml(cfg)), "Version": 1, "created": _now()}
    store.health_checks[h["Id"]] = h
    store.persist()
    return _xml("CreateHealthCheckResponse", _hc_xml(h), 201, {"Location": f"https://route53.amazonaws.com{PREFIX}/healthcheck/{h['Id']}"})


def _get_health_check(store, m, path, q, body):
    return _xml("GetHealthCheckResponse", _hc_xml(_hc(store, m.group(1))))


def _list_health_checks(store, m, path, q, body):
    hs = sorted(store.health_checks.values(), key=lambda h: h["created"] + h["Id"])
    mx = _maxitems(q)
    page, trunc, nxt = _page(hs, q.get("marker"), mx, lambda h: h["Id"])
    inner = "<HealthChecks>" + "".join(_hc_xml(h) for h in page) + "</HealthChecks>"
    inner += _el("Marker", q.get("marker")) + _el("IsTruncated", trunc) + (_el("NextMarker", nxt["Id"]) if nxt else "") + _el("MaxItems", mx)
    return _xml("ListHealthChecksResponse", inner)


def _update_health_check(store, m, path, q, body):
    h = _hc(store, m.group(1))
    r = _parse(body)
    ver = _text(r, "HealthCheckVersion")
    if ver is not None and int(ver) != h["Version"]:
        raise Route53Error("HealthCheckVersionMismatch", "The value of HealthCheckVersion in the request doesn't match the current value in the health check.", 409)
    upd = {}
    for k in _HC_ORDER:
        e = _child(r, k)
        if e is None:
            continue
        if k == "ChildHealthChecks":
            upd[k] = [(x.text or "").strip() for x in e.findall("ChildHealthCheck")]
        elif k == "Regions":
            upd[k] = [(x.text or "").strip() for x in e.findall("Region")]
        elif k == "AlarmIdentifier":
            upd[k] = {"Region": _text(e, "Region", ""), "Name": _text(e, "Name", "")}
        elif k in _HC_INT:
            upd[k] = int(e.text)
        elif k in _HC_BOOL:
            upd[k] = (e.text or "").strip().lower() == "true"
        else:
            upd[k] = (e.text or "").strip()
    for rm in (_child(r, "ResetElements") or []):
        h["Config"].pop((rm.text or "").strip(), None)
    h["Config"].update(upd)
    h["Version"] += 1
    store.persist()
    return _xml("UpdateHealthCheckResponse", _hc_xml(h))


def _delete_health_check(store, m, path, q, body):
    h = _hc(store, m.group(1))
    for z in store.hosted_zones.values():
        if any(r.get("HealthCheckId") == h["Id"] for r in z["records"].values()):
            raise Route53Error("HealthCheckInUse", "This health check is still associated with a resource record set.")
    del store.health_checks[h["Id"]]
    store.tags.pop(f"healthcheck/{h['Id']}", None)
    store.persist()
    return _xml("DeleteHealthCheckResponse")


def _get_health_check_status(store, m, path, q, body):
    h = _hc(store, m.group(1))
    ok = not h["Config"].get("Disabled")
    ok = ok != bool(h["Config"].get("Inverted")) if h["Config"].get("Inverted") else ok
    status = "Success: HTTP Status Code 200, OK" if ok else "Failure: Health check is disabled"
    obs = "".join(
        "<HealthCheckObservation>" + _el("Region", r) + _el("IPAddress", f"15.177.{i}.{10 + i}") +
        "<StatusReport>" + _el("Status", status) + _el("CheckedTime", _now()) + "</StatusReport></HealthCheckObservation>"
        for i, r in enumerate(_REGIONS[:3]))
    return _xml("GetHealthCheckStatusResponse", f"<HealthCheckObservations>{obs}</HealthCheckObservations>")


def _get_health_check_count(store, m, path, q, body):
    return _xml("GetHealthCheckCountResponse", _el("HealthCheckCount", len(store.health_checks)))


def _get_hc_last_failure(store, m, path, q, body):
    _hc(store, m.group(1))
    return _xml("GetHealthCheckLastFailureReasonResponse", "<HealthCheckObservations></HealthCheckObservations>")


# ── reusable delegation sets ───────────────────────────────────────────────
def _create_delegation_set(store, m, path, q, body):
    r = _parse(body)
    ref = _text(r, "CallerReference")
    if not ref:
        raise Route53Error("InvalidInput", "Invalid request: CallerReference is required")
    for d in store.delegation_sets.values():
        if d["CallerReference"] == ref:
            raise Route53Error("DelegationSetAlreadyCreated", "A delegation set with the same caller reference was already created.", 400)
    did = _rid("N")
    ds = {"Id": did, "CallerReference": ref, "NameServers": _nameservers(did), "HostedZoneId": _short_id(_text(r, "HostedZoneId", ""), "hostedzone") or None}
    store.delegation_sets[did] = ds
    store.persist()
    return _xml("CreateReusableDelegationSetResponse", _ds_xml(ds), 201, {"Location": f"https://route53.amazonaws.com{PREFIX}/delegationset/{did}"})


def _ds(store, did: str) -> dict:
    d = store.delegation_sets.get(_short_id(did, "delegationset"))
    if d is None:
        raise Route53Error("NoSuchDelegationSet", "A reusable delegation set with the specified ID does not exist.", 404)
    return d


def _get_delegation_set(store, m, path, q, body):
    return _xml("GetReusableDelegationSetResponse", _ds_xml(_ds(store, m.group(1))))


def _list_delegation_sets(store, m, path, q, body):
    ds = sorted(store.delegation_sets.values(), key=lambda d: d["Id"])
    mx = _maxitems(q)
    page, trunc, nxt = _page(ds, q.get("marker"), mx, lambda d: d["Id"])
    inner = "<DelegationSets>" + "".join(_ds_xml(d) for d in page) + "</DelegationSets>"
    inner += _el("Marker", q.get("marker")) + _el("IsTruncated", trunc) + (_el("NextMarker", nxt["Id"]) if nxt else "") + _el("MaxItems", mx)
    return _xml("ListReusableDelegationSetsResponse", inner)


def _delete_delegation_set(store, m, path, q, body):
    d = _ds(store, m.group(1))
    if any(z.get("DelegationSetId") == d["Id"] for z in store.hosted_zones.values()):
        raise Route53Error("DelegationSetInUse", "The specified delegation contains associated hosted zones which must be deleted before the reusable delegation set can be deleted.")
    del store.delegation_sets[d["Id"]]
    store.persist()
    return _xml("DeleteReusableDelegationSetResponse")


# ── query logging ──────────────────────────────────────────────────────────
def _ql_xml(c: dict) -> str:
    return ("<QueryLoggingConfig>" + _el("Id", c["Id"]) + _el("HostedZoneId", c["HostedZoneId"]) +
            _el("CloudWatchLogsLogGroupArn", c["CloudWatchLogsLogGroupArn"]) + "</QueryLoggingConfig>")


def _create_query_logging(store, m, path, q, body):
    r = _parse(body)
    zid = _short_id(_text(r, "HostedZoneId", ""), "hostedzone")
    arn = _text(r, "CloudWatchLogsLogGroupArn")
    z = _zone(store, zid)
    if not arn:
        raise Route53Error("InvalidInput", "Invalid request: CloudWatchLogsLogGroupArn is required")
    if z["PrivateZone"]:
        raise Route53Error("InvalidInput", "Query logging is only supported for public hosted zones.")
    if any(c["HostedZoneId"] == zid for c in store.query_logging.values()):
        raise Route53Error("QueryLoggingConfigAlreadyExists", "You can create only one query logging configuration for a hosted zone, and a query logging configuration already exists for this hosted zone.", 409)
    c = {"Id": str(uuid.uuid4()), "HostedZoneId": zid, "CloudWatchLogsLogGroupArn": arn}
    store.query_logging[c["Id"]] = c
    store.persist()
    return _xml("CreateQueryLoggingConfigResponse", _ql_xml(c), 201, {"Location": f"https://route53.amazonaws.com{PREFIX}/queryloggingconfig/{c['Id']}"})


def _ql(store, cid: str) -> dict:
    c = store.query_logging.get(unquote(cid))
    if c is None:
        raise Route53Error("NoSuchQueryLoggingConfig", "The query logging configuration does not exist.", 404)
    return c


def _get_query_logging(store, m, path, q, body):
    return _xml("GetQueryLoggingConfigResponse", _ql_xml(_ql(store, m.group(1))))


def _list_query_logging(store, m, path, q, body):
    cs = sorted(store.query_logging.values(), key=lambda c: c["Id"])
    if q.get("hostedzoneid"):
        cs = [c for c in cs if c["HostedZoneId"] == _short_id(q["hostedzoneid"], "hostedzone")]
    mx = _maxitems(q, 100)
    inner = "<QueryLoggingConfigs>" + "".join(_ql_xml(c) for c in cs[:mx]) + "</QueryLoggingConfigs>"
    if len(cs) > mx:
        inner += _el("NextToken", cs[mx]["Id"])
    return _xml("ListQueryLoggingConfigsResponse", inner)


def _delete_query_logging(store, m, path, q, body):
    c = _ql(store, m.group(1))
    del store.query_logging[c["Id"]]
    store.persist()
    return _xml("DeleteQueryLoggingConfigResponse")


# ── tags ───────────────────────────────────────────────────────────────────
def _tag_target(store, rtype: str, rid: str) -> str:
    if rtype not in ("hostedzone", "healthcheck"):
        raise Route53Error("InvalidInput", f"Invalid resource type: {rtype}")
    rid = _short_id(rid, rtype)
    if rtype == "hostedzone":
        _zone(store, rid)
    else:
        _hc(store, rid)
    return f"{rtype}/{rid}"


def _change_tags(store, m, path, q, body):
    key = _tag_target(store, m.group(1), m.group(2))
    r = _parse(body)
    tags = store.tags.setdefault(key, {})
    add = _child(r, "AddTags")
    for t in (add if add is not None else []):
        tags[_text(t, "Key", "")] = _text(t, "Value", "")
    rem = _child(r, "RemoveTagKeys")
    for k in (rem if rem is not None else []):
        tags.pop((k.text or "").strip(), None)
    if len(tags) > 50:
        raise Route53Error("InvalidInput", "Too many tags: a resource can have at most 50 tags")
    if not tags:
        store.tags.pop(key, None)
    store.persist()
    return _xml("ChangeTagsForResourceResponse")


def _tagset_xml(store, key: str) -> str:
    rtype, rid = key.split("/", 1)
    tags = store.tags.get(key, {})
    return ("<ResourceTagSet>" + _el("ResourceType", rtype) + _el("ResourceId", rid) + "<Tags>" +
            "".join(f"<Tag>{_el('Key', k)}{_el('Value', v)}</Tag>" for k, v in sorted(tags.items())) + "</Tags></ResourceTagSet>")


def _list_tags(store, m, path, q, body):
    return _xml("ListTagsForResourceResponse", _tagset_xml(store, _tag_target(store, m.group(1), m.group(2))))


def _list_tags_many(store, m, path, q, body):
    r = _parse(body)
    ids = [(i.text or "").strip() for i in (_child(r, "ResourceIds") or [])]
    sets = "".join(_tagset_xml(store, _tag_target(store, m.group(1), i)) for i in ids)
    return _xml("ListTagsForResourcesResponse", f"<ResourceTagSets>{sets}</ResourceTagSets>")


# ── misc ───────────────────────────────────────────────────────────────────
def _get_dnssec(store, m, path, q, body):
    _zone(store, m.group(1))
    return _xml("GetDNSSECResponse", "<Status>" + _el("ServeSignature", "NOT_SIGNING") + "</Status><KeySigningKeys></KeySigningKeys>")


def _get_account_limit(store, m, path, q, body):
    t = m.group(1)
    if t not in _LIMITS:
        raise Route53Error("InvalidInput", f"Invalid limit type: {t}")
    count = {"MAX_HEALTH_CHECKS_BY_OWNER": len(store.health_checks), "MAX_HOSTED_ZONES_BY_OWNER": len(store.hosted_zones),
             "MAX_REUSABLE_DELEGATION_SETS_BY_OWNER": len(store.delegation_sets)}.get(t, 0)
    return _xml("GetAccountLimitResponse", f"<Limit>{_el('Type', t)}{_el('Value', _LIMITS[t])}</Limit>" + _el("Count", count))


def _get_zone_limit(store, m, path, q, body):
    t, z = m.group(2), _zone(store, m.group(1))
    if t not in _ZONE_LIMITS:
        raise Route53Error("InvalidInput", f"Invalid limit type: {t}")
    count = len(z["records"]) if t == "MAX_RRSETS_BY_ZONE" else len(z["VPCs"])
    return _xml("GetHostedZoneLimitResponse", f"<Limit>{_el('Type', t)}{_el('Value', _ZONE_LIMITS[t])}</Limit>" + _el("Count", count))


def _checker_ips(store, m, path, q, body):
    return _xml("GetCheckerIpRangesResponse", "<CheckerIpRanges>" + "".join(_el("CheckerIpRange", i) for i in _CHECKER_IPS) + "</CheckerIpRanges>")


def resolve(z: dict, zones: dict, name: str, rtype: str, depth: int = 0) -> list[str] | None:
    """Answer `name/rtype` from zone `z` the way an authoritative server would:
    exact match, then wildcard, following alias targets inside the account.
    Returns the record data, or None for NXDOMAIN."""
    name = norm_name(name)
    recs = list(z["records"].values())

    def match(nm):
        return [r for r in recs if r["Name"] == nm and r["Type"] == rtype] or []

    cand = match(name)
    exists = any(r["Name"] == name for r in recs)
    if not cand and not exists:
        labels = name.strip(".").split(".")
        for i in range(1, len(labels)):
            wild = "*." + ".".join(labels[i:]) + "."
            if any(r["Name"] == wild for r in recs):
                cand, exists = match(wild), True
                break
    if not exists:
        return None
    out: list[str] = []
    for r in cand:
        a = r.get("AliasTarget")
        if a and depth < 4:
            for oz in zones.values():
                got = resolve(oz, zones, a["DNSName"], rtype, depth + 1)
                if got:
                    out += got
                    break
        else:
            out += r.get("ResourceRecords", [])
    return out


def _test_dns_answer(store, m, path, q, body):
    z = _zone(store, q.get("hostedzoneid", ""))
    name, rtype = q.get("recordname"), (q.get("recordtype") or "").upper()
    if not name or rtype not in RR_TYPES:
        raise Route53Error("InvalidInput", "Invalid request: recordname and recordtype are required")
    got = resolve(z, store.hosted_zones, name, rtype)
    ns = z["NameServers"][0].rstrip(".")
    inner = (_el("Nameserver", ns) + _el("RecordName", norm_name(name)) + _el("RecordType", rtype) +
             "<RecordData>" + "".join(_el("RecordDataEntry", v) for v in (got or [])) + "</RecordData>" +
             _el("ResponseCode", "NXDOMAIN" if got is None else "NOERROR") + _el("Protocol", "UDP"))
    return _xml("TestDNSAnswerResponse", inner)


# ── CoreDNS zone files ─────────────────────────────────────────────────────
def _abs(v: str) -> str:
    return v if v.endswith(".") else v + "."


def _rdata(rtype: str, v: str) -> str:
    v = v.strip()
    if rtype in ("CNAME", "NS", "PTR"):
        return _abs(v)
    if rtype == "MX":
        pr, _, host = v.partition(" ")
        return f"{pr} {_abs(host.strip())}"
    if rtype == "SRV":
        p = v.split()
        return " ".join(p[:3] + [_abs(p[3])]) if len(p) == 4 else v
    return v


def zone_files(store) -> dict[str, str]:
    """`{zone name (no trailing dot): RFC 1035 text}` for every hosted zone — what the
    shared CoreDNS `auto` plugin loads. Alias records become the addresses of their
    in-account target; private zones are included (the lab network is the VPC)."""
    out: dict[str, str] = {}
    for z in store.hosted_zones.values():
        lines = [f"$ORIGIN {z['Name']}", "$TTL 300"]
        for r in _sorted_records(z):
            nm = r["Name"]
            if "AliasTarget" in r:
                if r["Type"] not in ("A", "AAAA"):
                    continue
                for v in resolve(z, store.hosted_zones, r["Name"], r["Type"]) or []:
                    lines.append(f"{nm} 60 IN {r['Type']} {v}")
                continue
            for v in r.get("ResourceRecords", []):
                lines.append(f"{nm} {r.get('TTL', 300)} IN {r['Type']} {_rdata(r['Type'], v)}")
        out[z["Name"].rstrip(".")] = "\n".join(lines) + "\n"
    return out


# ── routing ────────────────────────────────────────────────────────────────
_R = [
    ("POST", r"/hostedzone", _create_hosted_zone, "CreateHostedZone"),
    ("GET", r"/hostedzone", _list_hosted_zones, "ListHostedZones"),
    ("GET", r"/hostedzonecount", _get_hosted_zone_count, "GetHostedZoneCount"),
    ("GET", r"/hostedzonesbyname", _list_hosted_zones_by_name, "ListHostedZonesByName"),
    ("GET", r"/hostedzonesbyvpc", _list_hosted_zones_by_vpc, "ListHostedZonesByVPC"),
    ("GET", r"/hostedzone/([^/]+)", _get_hosted_zone, "GetHostedZone"),
    ("POST", r"/hostedzone/([^/]+)", _update_hosted_zone_comment, "UpdateHostedZoneComment"),
    ("DELETE", r"/hostedzone/([^/]+)", _delete_hosted_zone, "DeleteHostedZone"),
    ("POST", r"/hostedzone/([^/]+)/rrset/?", _change_rrsets, "ChangeResourceRecordSets"),
    ("GET", r"/hostedzone/([^/]+)/rrset/?", _list_rrsets, "ListResourceRecordSets"),
    ("POST", r"/hostedzone/([^/]+)/associatevpc", lambda *a: _assoc_vpc(*a, add=True), "AssociateVPCWithHostedZone"),
    ("POST", r"/hostedzone/([^/]+)/disassociatevpc", lambda *a: _assoc_vpc(*a, add=False), "DisassociateVPCFromHostedZone"),
    ("GET", r"/hostedzone/([^/]+)/dnssec", _get_dnssec, "GetDNSSEC"),
    ("GET", r"/change/([^/]+)", _get_change, "GetChange"),
    ("POST", r"/healthcheck", _create_health_check, "CreateHealthCheck"),
    ("GET", r"/healthcheck", _list_health_checks, "ListHealthChecks"),
    ("GET", r"/healthcheckcount", _get_health_check_count, "GetHealthCheckCount"),
    ("GET", r"/healthcheck/([^/]+)", _get_health_check, "GetHealthCheck"),
    ("POST", r"/healthcheck/([^/]+)", _update_health_check, "UpdateHealthCheck"),
    ("DELETE", r"/healthcheck/([^/]+)", _delete_health_check, "DeleteHealthCheck"),
    ("GET", r"/healthcheck/([^/]+)/status", _get_health_check_status, "GetHealthCheckStatus"),
    ("GET", r"/healthcheck/([^/]+)/lastfailurereason", _get_hc_last_failure, "GetHealthCheckLastFailureReason"),
    ("POST", r"/delegationset", _create_delegation_set, "CreateReusableDelegationSet"),
    ("GET", r"/delegationset", _list_delegation_sets, "ListReusableDelegationSets"),
    ("GET", r"/delegationset/([^/]+)", _get_delegation_set, "GetReusableDelegationSet"),
    ("DELETE", r"/delegationset/([^/]+)", _delete_delegation_set, "DeleteReusableDelegationSet"),
    ("POST", r"/queryloggingconfig", _create_query_logging, "CreateQueryLoggingConfig"),
    ("GET", r"/queryloggingconfig", _list_query_logging, "ListQueryLoggingConfigs"),
    ("GET", r"/queryloggingconfig/([^/]+)", _get_query_logging, "GetQueryLoggingConfig"),
    ("DELETE", r"/queryloggingconfig/([^/]+)", _delete_query_logging, "DeleteQueryLoggingConfig"),
    ("POST", r"/tags/([^/]+)/([^/]+)", _change_tags, "ChangeTagsForResource"),
    ("GET", r"/tags/([^/]+)/([^/]+)", _list_tags, "ListTagsForResource"),
    ("POST", r"/tags/([^/]+)", _list_tags_many, "ListTagsForResources"),
    ("GET", r"/accountlimit/([^/]+)", _get_account_limit, "GetAccountLimit"),
    ("GET", r"/hostedzonelimit/([^/]+)/([^/]+)", _get_zone_limit, "GetHostedZoneLimit"),
    ("GET", r"/checkeripranges", _checker_ips, "GetCheckerIpRanges"),
    ("GET", r"/testdnsanswer", _test_dns_answer, "TestDNSAnswer"),
]
_ROUTES = [(meth, re.compile("^" + pat + "$"), fn, op) for meth, pat, fn, op in _R]
OPERATIONS = [op for *_x, op in _R]


def is_route53_path(path: str) -> bool:
    return path.startswith(PREFIX + "/") or path == PREFIX


def dispatch(store: Route53Store, method: str, path: str, query: dict | None, headers: dict | None,
             body: bytes | None) -> Route53Response:
    """Serve ONE REST-XML request. `query` is a flat {name: value} dict."""
    method = (method or "GET").upper()
    sub = path[len(PREFIX):] if path.startswith(PREFIX) else path
    sub = sub.rstrip("/") or "/"
    q = {str(k).lower(): (v[0] if isinstance(v, (list, tuple)) else v) for k, v in (query or {}).items()}
    seen_path = False
    for meth, rx, fn, _op in _ROUTES:
        m = rx.match(sub)
        if not m:
            continue
        seen_path = True
        if meth != method:
            continue
        try:
            return fn(store, m, sub, q, body or b"")
        except Route53Error as e:
            return _error(e.code, e.message, e.status)
    if seen_path:
        return _error("InvalidAction", f"The {method} method is not valid for {PREFIX}{sub}.", 405)
    return _error("InvalidAction", f"The action for {PREFIX}{sub} is not valid for this web service.", 404)


# ── console REST view (flat, shared by the offline server and Nano) ────────
def _err(r: Route53Response) -> Route53Error:
    t = r.body.decode()
    code = re.search(r"<Code>(.*?)</Code>", t)
    msg = re.search(r"<Message>(.*?)</Message>", t)
    return Route53Error(code.group(1) if code else "Error", msg.group(1) if msg else "", r.status)


def _rec_summary(r: dict) -> dict:
    if "AliasTarget" in r:
        a = r["AliasTarget"]
        value, ttl, alias = a["DNSName"], "Alias", "Yes"
    else:
        value, ttl, alias = "\n".join(r.get("ResourceRecords", [])), str(r.get("TTL", 300)), "No"
    policy = ("Weighted" if "Weight" in r else "Latency" if "Region" in r else "Failover" if "Failover" in r
              else "Geolocation" if "GeoLocation" in r else "Multivalue answer" if r.get("MultiValueAnswer") else "Simple")
    return {"name": out_name(r["Name"]), "type": r["Type"], "routing_policy": policy, "alias": alias,
            "value": value, "ttl": ttl, "set_identifier": r.get("SetIdentifier") or "None"}


def console_zone(store, z: dict) -> dict:
    return {
        "zone_id": z["Id"], "name": out_name(z["Name"]), "type": "Private hosted zone" if z["PrivateZone"] else "Public hosted zone",
        "created_by": "Route 53", "record_count": len(z["records"]), "comment": z.get("Comment") or "No description",
        "name_servers": ", ".join(n.rstrip(".") for n in z["NameServers"]), "created": z["created"],
        "vpcs": ", ".join(v["VPCId"] for v in z["VPCs"]) or "None",
        "arn": f"arn:aws:route53:::hostedzone/{z['Id']}",
        "tags": dict(store.tags.get(f"hostedzone/{z['Id']}", {})),
        "records": [_rec_summary(r) for r in _sorted_records(z)],
    }


def console_list(store) -> dict:
    zs = sorted(store.hosted_zones.values(), key=lambda z: z["created"] + z["Id"])
    return {"items": [{k: v for k, v in console_zone(store, z).items() if k != "records"} for z in zs]}


def _find_zone(store, key: str) -> dict:
    key = _short_id(key, "hostedzone")
    if key in store.hosted_zones:
        return store.hosted_zones[key]
    n = norm_name(key)
    for z in store.hosted_zones.values():
        if z["Name"] == n:
            return z
    raise Route53Error("NoSuchHostedZone", f"No hosted zone found with ID: {key}", 404)


def console_get(store, key: str) -> dict:
    return console_zone(store, _find_zone(store, key))


def console_create(store, body: dict) -> dict:
    name = str(body.get("name") or "").strip()
    private = str(body.get("private", "")).lower() in ("true", "1", "yes") or str(body.get("type", "")).lower().startswith("private")
    vpc = (f"<VPC><VPCRegion>{_esc(str(body.get('vpc_region') or store.region))}</VPCRegion>"
           f"<VPCId>{_esc(str(body.get('vpc_id') or 'vpc-0a1b2c3d4e5f60718'))}</VPCId></VPC>") if private else ""
    xml = (f'<CreateHostedZoneRequest xmlns="{NS}"><Name>{_esc(name)}</Name>{vpc}<CallerReference>{_req_id()}</CallerReference>'
           f'<HostedZoneConfig><Comment>{_esc(str(body.get("comment") or "Managed by Vyomi"))}</Comment>'
           f'<PrivateZone>{"true" if private else "false"}</PrivateZone></HostedZoneConfig></CreateHostedZoneRequest>')
    r = dispatch(store, "POST", PREFIX + "/hostedzone", {}, {}, xml.encode())
    if r.status >= 300:
        raise _err(r)
    zid = re.search(r"<Id>/hostedzone/(.*?)</Id>", r.body.decode()).group(1)
    return console_zone(store, store.hosted_zones[zid])


def console_delete(store, key: str) -> dict:
    z = _find_zone(store, key)
    # The console deletes the zone together with its records (as the AWS console's
    # "Delete records" step does), then the zone itself.
    z["records"] = {k: v for k, v in z["records"].items() if v["Type"] in ("NS", "SOA") and v["Name"] == z["Name"]}
    r = dispatch(store, "DELETE", f"{PREFIX}/hostedzone/{z['Id']}", {}, {}, b"")
    if r.status >= 300:
        raise _err(r)
    return {"ok": True}


def console_set_tags(store, key: str, tags: dict) -> dict:
    z = _find_zone(store, key)
    store.tags[f"hostedzone/{z['Id']}"] = {str(k): str(v) for k, v in (tags or {}).items()}
    if not store.tags[f"hostedzone/{z['Id']}"]:
        del store.tags[f"hostedzone/{z['Id']}"]
    store.persist()
    return console_zone(store, z)


def console_record_upsert(store, key: str, body: dict) -> dict:
    z = _find_zone(store, key)
    vals = body.get("values") or body.get("value") or ""
    if isinstance(vals, str):
        vals = [v for v in vals.replace(",", "\n").split("\n") if v.strip()]
    recs = "".join(f"<ResourceRecord><Value>{_esc(str(v).strip())}</Value></ResourceRecord>" for v in vals)
    xml = (f'<ChangeResourceRecordSetsRequest xmlns="{NS}"><ChangeBatch><Changes><Change><Action>UPSERT</Action>'
           f'<ResourceRecordSet><Name>{_esc(str(body.get("name") or ""))}</Name><Type>{_esc(str(body.get("type") or "A"))}</Type>'
           f'<TTL>{int(body.get("ttl") or 300)}</TTL><ResourceRecords>{recs}</ResourceRecords></ResourceRecordSet>'
           f'</Change></Changes></ChangeBatch></ChangeResourceRecordSetsRequest>')
    r = dispatch(store, "POST", f"{PREFIX}/hostedzone/{z['Id']}/rrset", {}, {}, xml.encode())
    if r.status >= 300:
        raise _err(r)
    return console_zone(store, z)


def console_record_delete(store, key: str, name: str, rtype: str) -> dict:
    z = _find_zone(store, key)
    n = norm_name(name)
    cur = [r for r in z["records"].values() if r["Name"] == n and r["Type"] == rtype.upper() and not r.get("SetIdentifier")]
    if not cur:
        raise Route53Error("InvalidChangeBatch", f"[Tried to delete resource record set [name='{name}', type='{rtype}'] but it was not found]")
    del z["records"][_rr_key(n, rtype.upper(), None)]
    store.persist()
    return console_zone(store, z)


def _hc_summary(store, h: dict) -> dict:
    c = h["Config"]
    target = c.get("IPAddress") or c.get("FullyQualifiedDomainName") or "Calculated"
    return {"name": h["Id"], "type": c["Type"], "target": target, "port": str(c.get("Port", "N/A")),
            "path": c.get("ResourcePath", "N/A"), "status": "Disabled" if c.get("Disabled") else "Healthy",
            "interval": f"{c['RequestInterval']}s" if "RequestInterval" in c else "N/A", "created": h["created"]}


def console_children(store, kind: str) -> dict:
    if kind == "health-checks":
        return {"items": [_hc_summary(store, h) for h in sorted(store.health_checks.values(), key=lambda h: h["created"] + h["Id"])]}
    if kind == "delegation-sets":
        return {"items": [{"name": d["Id"], "caller_reference": d["CallerReference"],
                           "name_servers": ", ".join(n.rstrip(".") for n in d["NameServers"]),
                           "zones": str(sum(1 for z in store.hosted_zones.values() if z.get("DelegationSetId") == d["Id"]))}
                          for d in sorted(store.delegation_sets.values(), key=lambda d: d["Id"])]}
    raise Route53Error("InvalidInput", f"unknown collection {kind}", 404)


def console_child_create(store, kind: str, body: dict) -> dict:
    if kind == "health-checks":
        target = str(body.get("target") or body.get("ip_address") or "example.com")
        typ = str(body.get("type") or "HTTP").upper()
        ip = re.fullmatch(r"\d+\.\d+\.\d+\.\d+", target)
        xml = (f'<CreateHealthCheckRequest xmlns="{NS}"><CallerReference>{_req_id()}</CallerReference><HealthCheckConfig>'
               f'<Type>{_esc(typ)}</Type>' + (f"<IPAddress>{_esc(target)}</IPAddress>" if ip else f"<FullyQualifiedDomainName>{_esc(target)}</FullyQualifiedDomainName>") +
               (f"<Port>{int(body['port'])}</Port>" if body.get("port") else "") +
               (f"<ResourcePath>{_esc(str(body['path']))}</ResourcePath>" if body.get("path") else "") +
               '</HealthCheckConfig></CreateHealthCheckRequest>')
        r = dispatch(store, "POST", PREFIX + "/healthcheck", {}, {}, xml.encode())
        if r.status >= 300:
            raise _err(r)
        hid = re.search(r"<Id>(.*?)</Id>", r.body.decode()).group(1)
        return _hc_summary(store, store.health_checks[hid])
    raise Route53Error("InvalidInput", f"unknown collection {kind}", 404)


def console_child_delete(store, kind: str, name: str) -> dict:
    if kind == "health-checks":
        r = dispatch(store, "DELETE", f"{PREFIX}/healthcheck/{name}", {}, {}, b"")
    elif kind == "delegation-sets":
        r = dispatch(store, "DELETE", f"{PREFIX}/delegationset/{name}", {}, {}, b"")
    else:
        raise Route53Error("InvalidInput", f"unknown collection {kind}", 404)
    if r.status >= 300:
        raise _err(r)
    return {"ok": True}
