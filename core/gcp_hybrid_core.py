"""GCP hybrid-connectivity + BYOIP control plane (Compute Engine v1/beta REST).

Substrate-independent (stdlib only; Pyodide-loadable). Hooked from core/gcp_compute_instances_core._dispatch, so every
client that reaches the VM core (google-cloud-compute, gcloud, the console) reaches this. State: store.ext[...] on the
Compute store (persisted with it).

  global/publicAdvertisedPrefixes        (+ :announce / :withdraw)           BYOIP
  regions/{r}/publicDelegatedPrefixes    (+ :announce / :withdraw, sub-prefix delegation)  (+ aggregated)
  global/interconnects                   (+ getDiagnostics)  global/interconnectLocations
  regions/{r}/interconnectAttachments    VLAN attachments (+ aggregated) — the Cloud Router is cross-checked against the VPC core

Honesty (also in core/capabilities/gcp/networking.json): this is the control plane only. There is no physical circuit,
no BGP session and no packet forwarding: an enabled attachment reports ACTIVE/OS_ACTIVE because the admin state says so,
not because traffic flows; BYOIP ownership (DNS TXT / RDAP) is not verified, so a prefix goes straight to VALIDATED and an
announced prefix is not actually advertised to the internet.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import uuid
from datetime import datetime, timezone

from core import gcp_compute_instances_core as G
from core.gcp_compute_instances_core import _E, _json

NAME_RE = re.compile(r"^[a-z]([-a-z0-9]{0,61}[a-z0-9])?$")
BANDWIDTHS = ("BPS_50M", "BPS_100M", "BPS_200M", "BPS_300M", "BPS_400M", "BPS_500M", "BPS_1G", "BPS_2G", "BPS_5G", "BPS_10G", "BPS_20G", "BPS_50G", "BPS_100G")
ATTACH_TYPES = ("DEDICATED", "PARTNER", "PARTNER_PROVIDER", "L2_DEDICATED")
LINK_TYPES = ("LINK_TYPE_ETHERNET_10G_LR", "LINK_TYPE_ETHERNET_100G_LR", "LINK_TYPE_ETHERNET_400G_LR4")
LINK_GBPS = {"LINK_TYPE_ETHERNET_10G_LR": 10, "LINK_TYPE_ETHERNET_100G_LR": 100, "LINK_TYPE_ETHERNET_400G_LR4": 400}
IC_TYPES = ("DEDICATED", "PARTNER", "IT_PRIVATE")
MAX_LINKS = {"LINK_TYPE_ETHERNET_10G_LR": 8, "LINK_TYPE_ETHERNET_100G_LR": 2, "LINK_TYPE_ETHERNET_400G_LR4": 1}
PDP_MODES = ("DELEGATION", "EXTERNAL_IPV6_FORWARDING_RULE_CREATION", "EXTERNAL_IPV6_SUBNETWORK_CREATION")
MTUS = (1440, 1460, 8896)
AVAILABILITY = ("AVAILABILITY_DOMAIN_ANY", "AVAILABILITY_DOMAIN_1", "AVAILABILITY_DOMAIN_2")

# Ranges that can never be advertised (documentation/test ranges are allowed so tutorials work).
_NON_PUBLIC = [ipaddress.ip_network(c) for c in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8", "169.254.0.0/16", "100.64.0.0/10",
                                                 "224.0.0.0/4", "0.0.0.0/8", "fc00::/7", "fe80::/10", "::1/128", "ff00::/8")]

# A small fixed catalog of real colocation facilities (name, city, region, facility provider).
LOCATIONS = [
    ("iad-zone1-1", "Ashburn, Virginia", "us-east4", "Equinix DC2"), ("ord-zone1-1", "Chicago, Illinois", "us-central1", "Equinix CH1"),
    ("lax-zone1-403", "Los Angeles, California", "us-west2", "CoreSite LA1"), ("sjc-zone1-6", "San Jose, California", "us-west1", "Equinix SV5"),
    ("lhr-zone1-1", "London, United Kingdom", "europe-west2", "Equinix LD5"), ("fra-zone1-5", "Frankfurt, Germany", "europe-west3", "Equinix FR5"),
    ("ams-zone1-5", "Amsterdam, Netherlands", "europe-west4", "Equinix AM3"), ("sin-zone1-1", "Singapore", "asia-southeast1", "Equinix SG1"),
    ("nrt-zone1-1", "Tokyo, Japan", "asia-northeast1", "Equinix TY2"), ("bom-zone1-2", "Mumbai, India", "asia-south1", "Equinix MB1"),
]
LOC_BY_NAME = {n: (c, r, f) for n, c, r, f in LOCATIONS}


def _x(store, coll):
    if getattr(store, "ext", None) is None:
        store.ext = {}
    return store.ext.setdefault(coll, {})


def _ts():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _bad(msg):
    return _E(400, "INVALID_ARGUMENT", msg)


def _name(payload, what):
    n = str(payload.get("name", ""))
    if not NAME_RE.match(n):
        raise _bad("Invalid value for field 'resource.name': '%s'. Must be a match of regex '[a-z]([-a-z0-9]*[a-z0-9])?' (%s)." % (n, what))
    return n


def _link(tail):
    return G._selflink(tail)


def _nf(full):
    return _E(404, "NOT_FOUND", "The resource '%s' was not found" % _link(full))


def _dup(full):
    return _E(409, "ALREADY_EXISTS", "The resource '%s' already exists" % _link(full))


def _in_use(msg):
    return _E(400, "RESOURCE_IN_USE_BY_ANOTHER_RESOURCE", msg)


def _last(v):
    return str(v or "").rstrip("/").split("/")[-1]


def _op(store, project, scope, op_type, name, full):
    return G._operation(store, project, scope, op_type, name, _link(full))


def _list(kind, items, project, tail):
    return {"kind": kind, "id": "projects/%s/%s" % (project, tail), "items": items, "selfLink": _link("projects/%s/%s" % (project, tail))}


def _agg(store, coll, project, key, kind):
    out = {}
    pre = "projects/%s/" % project
    for full, rec in sorted(_x(store, coll).items()):
        if full.startswith(pre):
            scope = "global" if full.split("/")[2] == "global" else "regions/%s" % full.split("/")[3]
            out.setdefault(scope, {key: []})[key].append(rec)
    return {"kind": kind, "id": "projects/%s/aggregated/%s" % (project, key), "items": out}


def _region(r):
    if r not in G.REGIONS:
        raise _bad("Invalid value for field 'region': '%s'. Unknown region." % r)


def _cidr(v, field, ver=None):
    try:
        n = ipaddress.ip_network(str(v), strict=True)
    except Exception:
        raise _bad("Invalid value for field '%s': '%s'. Must be a valid CIDR range (host bits must be zero)." % (field, v))
    if ver and n.version != ver:
        raise _bad("Invalid value for field '%s': '%s'. Must be IPv%d." % (field, v, ver))
    return n


# ── BYOIP: public advertised prefixes ─────────────────────────────────────────
def pap_insert(store, project, payload):
    coll = _x(store, "pap")
    name = _name(payload, "public advertised prefix")
    full = "projects/%s/global/publicAdvertisedPrefixes/%s" % (project, name)
    if full in coll:
        raise _dup(full)
    net = _cidr(payload.get("ipCidrRange"), "resource.ipCidrRange")
    if any(net.version == r.version and net.overlaps(r) for r in _NON_PUBLIC):
        raise _bad("Invalid value for field 'resource.ipCidrRange': '%s'. A public advertised prefix must be a public (globally routable) range." % net)
    if net.version == 4 and net.prefixlen > 24:
        raise _bad("Invalid value for field 'resource.ipCidrRange': IPv4 prefixes must be /24 or larger.")
    if net.version == 6 and net.prefixlen > 48:
        raise _bad("Invalid value for field 'resource.ipCidrRange': IPv6 prefixes must be /48 or larger.")
    if payload.get("pdpScope") not in (None, "GLOBAL_PDP", "REGIONAL_PDP"):
        raise _bad("Invalid value for field 'resource.pdpScope'.")
    try:
        ipaddress.ip_address(str(payload.get("dnsVerificationIp")))
    except Exception:
        raise _bad("Invalid value for field 'resource.dnsVerificationIp': a valid IP address inside the prefix is required.")
    if ipaddress.ip_address(payload["dnsVerificationIp"]) not in net:
        raise _bad("Invalid value for field 'resource.dnsVerificationIp': '%s' is not within %s." % (payload["dnsVerificationIp"], net))
    for k, v in coll.items():
        if k.startswith("projects/%s/" % project) and ipaddress.ip_network(v["ipCidrRange"]).overlaps(net):
            raise _E(400, "INVALID_ARGUMENT", "Invalid value for field 'resource.ipCidrRange': '%s' overlaps with existing public advertised prefix '%s'." % (net, v["name"]))
    rec = {"kind": "compute#publicAdvertisedPrefix", "id": str(G._next_id(store)), "creationTimestamp": _ts(), "name": name,
           "description": payload.get("description", ""), "selfLink": _link(full), "ipCidrRange": str(net),
           "dnsVerificationIp": payload["dnsVerificationIp"], "sharedSecret": uuid.uuid4().hex[:28],
           "status": "VALIDATED", "pdpScope": payload.get("pdpScope", "GLOBAL_PDP"), "publicDelegatedPrefixs": [],
           "fingerprint": hashlib.sha1(name.encode()).hexdigest()[:12]}
    coll[full] = rec
    return _op(store, project, None, "insert", name, full)


def pap_verb(store, project, name, verb):
    coll = _x(store, "pap")
    full = "projects/%s/global/publicAdvertisedPrefixes/%s" % (project, name)
    rec = coll.get(full)
    if rec is None:
        raise _nf(full)
    if verb == "announce":
        if rec["status"] == "ANNOUNCED_TO_INTERNET":
            raise _bad("The prefix is already announced.")
        rec["status"] = "ANNOUNCED_TO_INTERNET"
    elif verb == "withdraw":
        if rec["status"] != "ANNOUNCED_TO_INTERNET":
            raise _bad("The prefix is not announced, so it cannot be withdrawn.")
        if any(v.get("status") == "ANNOUNCED" for v in _x(store, "pdp").values() if _last(v.get("parentPrefix")) == name):
            raise _in_use("Cannot withdraw '%s' while a delegated prefix of it is announced." % name)
        rec["status"] = "VALIDATED"
    else:
        raise _E(404, "NOT_FOUND", "Unknown method %s." % verb)
    return _op(store, project, None, verb, name, full)


def pap_delete(store, project, name):
    coll = _x(store, "pap")
    full = "projects/%s/global/publicAdvertisedPrefixes/%s" % (project, name)
    if full not in coll:
        raise _nf(full)
    if any(_last(v.get("parentPrefix")) == name for v in _x(store, "pdp").values()):
        raise _in_use("The public advertised prefix '%s' is in use by a public delegated prefix." % name)
    del coll[full]
    return _op(store, project, None, "delete", name, full)


# ── BYOIP: public delegated prefixes ──────────────────────────────────────────
def _pdp_sub(store, project, parent_full, parent, payload):
    """Validate a (sub)prefix inside `parent` (a PDP or PAP record with ipCidrRange)."""
    net = _cidr(payload.get("ipCidrRange"), "resource.ipCidrRange")
    pn = ipaddress.ip_network(parent["ipCidrRange"])
    if net.version != pn.version or not net.subnet_of(pn) or net.prefixlen < pn.prefixlen:
        raise _bad("Invalid value for field 'resource.ipCidrRange': '%s' is not a sub-range of the parent prefix %s." % (net, pn))
    return net


def pdp_insert(store, project, region, payload):
    _region(region)
    coll = _x(store, "pdp")
    name = _name(payload, "public delegated prefix")
    full = "projects/%s/regions/%s/publicDelegatedPrefixes/%s" % (project, region, name)
    if full in coll:
        raise _dup(full)
    parent_ref = payload.get("parentPrefix")
    if not parent_ref:
        raise _bad("Invalid value for field 'resource.parentPrefix': a parent public advertised prefix is required.")
    pname = _last(parent_ref)
    parent = _x(store, "pap").get("projects/%s/global/publicAdvertisedPrefixes/%s" % (project, pname))
    if parent is None:
        raise _E(404, "NOT_FOUND", "The resource '%s' was not found" % _link("projects/%s/global/publicAdvertisedPrefixes/%s" % (project, pname)))
    if parent.get("pdpScope") == "GLOBAL_PDP":
        raise _bad("Invalid value for field 'resource.parentPrefix': prefix '%s' has pdpScope GLOBAL_PDP and cannot have regional delegated prefixes." % pname)
    net = _pdp_sub(store, project, None, parent, payload)
    if payload.get("mode") not in (None,) + PDP_MODES:
        raise _bad("Invalid value for field 'resource.mode': must be one of %s." % ", ".join(PDP_MODES))
    for v in coll.values():
        if _last(v.get("parentPrefix")) == pname and ipaddress.ip_network(v["ipCidrRange"]).overlaps(net):
            raise _bad("Invalid value for field 'resource.ipCidrRange': '%s' overlaps with delegated prefix '%s'." % (net, v["name"]))
    rec = {"kind": "compute#publicDelegatedPrefix", "id": str(G._next_id(store)), "creationTimestamp": _ts(), "name": name,
           "description": payload.get("description", ""), "selfLink": _link(full), "region": _link("projects/%s/regions/%s" % (project, region)),
           "parentPrefix": _link("projects/%s/global/publicAdvertisedPrefixes/%s" % (project, pname)), "ipCidrRange": str(net),
           "status": "READY_TO_ANNOUNCE", "isLiveMigration": bool(payload.get("isLiveMigration")),
           "mode": payload.get("mode", "DELEGATION"), "publicDelegatedSubPrefixs": [], "fingerprint": hashlib.sha1(name.encode()).hexdigest()[:12]}
    coll[full] = rec
    parent["publicDelegatedPrefixs"].append({"name": name, "region": region, "project": project, "status": rec["status"],
                                              "ipRange": str(net), "isAddress": False, "type": "DELEGATED"})
    return _op(store, project, region, "insert", name, full)


def _sync_parent_status(store, project, rec):
    parent = _x(store, "pap").get("projects/%s/global/publicAdvertisedPrefixes/%s" % (project, _last(rec["parentPrefix"])))
    if parent:
        for d in parent["publicDelegatedPrefixs"]:
            if d["name"] == rec["name"]:
                d["status"] = rec["status"]


def pdp_verb(store, project, region, name, verb, payload):
    full = "projects/%s/regions/%s/publicDelegatedPrefixes/%s" % (project, region, name)
    rec = _x(store, "pdp").get(full)
    if rec is None:
        raise _nf(full)
    if verb == "announce":
        parent = _x(store, "pap").get("projects/%s/global/publicAdvertisedPrefixes/%s" % (project, _last(rec["parentPrefix"])))
        if parent and parent["status"] != "ANNOUNCED_TO_INTERNET":
            raise _bad("The parent public advertised prefix '%s' must be announced before its delegated prefix." % parent["name"])
        if rec["status"] == "ANNOUNCED":
            raise _bad("The delegated prefix is already announced.")
        rec["status"] = "ANNOUNCED"
    elif verb == "withdraw":
        if rec["status"] != "ANNOUNCED":
            raise _bad("The delegated prefix is not announced.")
        rec["status"] = "READY_TO_ANNOUNCE"
    else:
        raise _E(404, "NOT_FOUND", "Unknown method %s." % verb)
    _sync_parent_status(store, project, rec)
    return _op(store, project, region, verb, name, full)


def pdp_patch(store, project, region, name, payload):
    full = "projects/%s/regions/%s/publicDelegatedPrefixes/%s" % (project, region, name)
    rec = _x(store, "pdp").get(full)
    if rec is None:
        raise _nf(full)
    if "description" in payload:
        rec["description"] = payload["description"]
    if "publicDelegatedSubPrefixs" in payload:
        subs = []
        for sp in payload["publicDelegatedSubPrefixs"] or []:
            sn = _name(sp, "delegated sub prefix")
            net = _pdp_sub(store, project, full, rec, sp)
            if sp.get("mode") not in (None,) + PDP_MODES:
                raise _bad("Invalid value for publicDelegatedSubPrefixs.mode.")
            for o in subs:
                if ipaddress.ip_network(o["ipCidrRange"]).overlaps(net):
                    raise _bad("Sub prefix '%s' overlaps '%s'." % (sn, o["name"]))
            subs.append({"name": sn, "description": sp.get("description", ""), "ipCidrRange": str(net), "region": region,
                         "status": "ACTIVE", "mode": sp.get("mode", "DELEGATION"), "isAddress": bool(sp.get("isAddress"))})
        rec["publicDelegatedSubPrefixs"] = subs
    return _op(store, project, region, "patch", name, full)


def pdp_delete(store, project, region, name):
    coll = _x(store, "pdp")
    full = "projects/%s/regions/%s/publicDelegatedPrefixes/%s" % (project, region, name)
    rec = coll.get(full)
    if rec is None:
        raise _nf(full)
    if rec["status"] == "ANNOUNCED":
        raise _in_use("The public delegated prefix '%s' is announced; withdraw it first." % name)
    if rec["publicDelegatedSubPrefixs"]:
        raise _in_use("The public delegated prefix '%s' still has delegated sub prefixes." % name)
    del coll[full]
    parent = _x(store, "pap").get("projects/%s/global/publicAdvertisedPrefixes/%s" % (project, _last(rec["parentPrefix"])))
    if parent:
        parent["publicDelegatedPrefixs"] = [d for d in parent["publicDelegatedPrefixs"] if d["name"] != name]
    return _op(store, project, region, "delete", name, full)


# ── Interconnect ──────────────────────────────────────────────────────────────
def _ic_refresh(rec):
    on = rec.get("adminEnabled")
    rec["state"] = "ACTIVE" if on else "UNPROVISIONED"
    rec["operationalStatus"] = "OS_ACTIVE" if on else "OS_UNPROVISIONED"
    rec["provisionedLinkCount"] = rec["requestedLinkCount"] if on else 0
    rec["circuitInfos"] = [{"googleCircuitId": "%s-%d" % (rec["name"].upper()[:12], i + 1), "googleDemarcId": "demarc-%s-%d" % (rec["id"][-4:], i + 1),
                            "customerDemarcId": ""} for i in range(rec["provisionedLinkCount"])]


def ic_insert(store, project, payload):
    coll = _x(store, "interconnects")
    name = _name(payload, "interconnect")
    full = "projects/%s/global/interconnects/%s" % (project, name)
    if full in coll:
        raise _dup(full)
    itype = payload.get("interconnectType")
    if itype not in IC_TYPES:
        raise _bad("Invalid value for field 'resource.interconnectType': '%s'. Must be one of %s." % (itype, ", ".join(IC_TYPES)))
    lt = payload.get("linkType")
    if lt not in LINK_TYPES:
        raise _bad("Invalid value for field 'resource.linkType': '%s'. Must be one of %s." % (lt, ", ".join(LINK_TYPES)))
    n = payload.get("requestedLinkCount")
    if not isinstance(n, int) or not (1 <= n <= MAX_LINKS[lt]):
        raise _bad("Invalid value for field 'resource.requestedLinkCount': must be between 1 and %d for %s." % (MAX_LINKS[lt], lt))
    loc = _last(payload.get("location"))
    if loc not in LOC_BY_NAME:
        raise _E(404, "NOT_FOUND", "The resource '%s' was not found" % _link("projects/%s/global/interconnectLocations/%s" % (project, loc)))
    email = str(payload.get("nocContactEmail", ""))
    if email and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise _bad("Invalid value for field 'resource.nocContactEmail': '%s'." % email)
    if itype == "DEDICATED" and not payload.get("customerName"):
        raise _bad("Invalid value for field 'resource.customerName': required for DEDICATED interconnects.")
    rec = {"kind": "compute#interconnect", "id": str(G._next_id(store)), "creationTimestamp": _ts(), "name": name,
           "description": payload.get("description", ""), "selfLink": _link(full), "interconnectType": itype, "linkType": lt,
           "requestedLinkCount": n, "location": _link("projects/%s/global/interconnectLocations/%s" % (project, loc)),
           "customerName": payload.get("customerName", ""), "nocContactEmail": email, "adminEnabled": bool(payload.get("adminEnabled")),
           "labels": payload.get("labels") or {}, "interconnectAttachments": [], "expectedOutages": [],
           "remoteLocation": payload.get("remoteLocation", ""), "requestedFeatures": payload.get("requestedFeatures") or [],
           "availableFeatures": ["IF_MACSEC"] if lt != "LINK_TYPE_ETHERNET_10G_LR" else [],
           "peerIpAddress": "", "googleIpAddress": "", "googleReferenceId": uuid.uuid4().hex[:16]}
    _ic_refresh(rec)
    coll[full] = rec
    return _op(store, project, None, "insert", name, full)


def ic_patch(store, project, name, payload):
    full = "projects/%s/global/interconnects/%s" % (project, name)
    rec = _x(store, "interconnects").get(full)
    if rec is None:
        raise _nf(full)
    for k in ("description", "nocContactEmail", "labels", "adminEnabled", "requestedLinkCount"):
        if k in payload:
            if k == "requestedLinkCount":
                if not isinstance(payload[k], int) or not (1 <= payload[k] <= MAX_LINKS[rec["linkType"]]):
                    raise _bad("Invalid value for field 'resource.requestedLinkCount'.")
                if payload[k] < rec["requestedLinkCount"] and rec["adminEnabled"]:
                    raise _bad("Cannot reduce requestedLinkCount of an enabled interconnect.")
            rec[k] = payload[k]
    _ic_refresh(rec)
    for a in _x(store, "attachments").values():     # attachments follow the interconnect's admin state
        if _last(a.get("interconnect")) == name:
            _att_refresh(store, a)
    return _op(store, project, None, "patch", name, full)


def ic_delete(store, project, name):
    coll = _x(store, "interconnects")
    full = "projects/%s/global/interconnects/%s" % (project, name)
    if full not in coll:
        raise _nf(full)
    users = [a["name"] for a in _x(store, "attachments").values() if _last(a.get("interconnect")) == name]
    if users:
        raise _in_use("The interconnect '%s' is in use by interconnect attachment(s): %s." % (name, ", ".join(sorted(users))))
    del coll[full]
    return _op(store, project, None, "delete", name, full)


def ic_diagnostics(store, project, name):
    full = "projects/%s/global/interconnects/%s" % (project, name)
    rec = _x(store, "interconnects").get(full)
    if rec is None:
        raise _nf(full)
    up = rec["adminEnabled"]
    links = [{"circuitId": c["googleCircuitId"], "googleDemarcId": c["googleDemarcId"],
              "operationalStatus": "LINK_OPERATIONAL_STATUS_UP" if up else "LINK_OPERATIONAL_STATUS_DOWN",
              "lacpStatus": {"state": "ACTIVE" if up else "MISSING", "googleSystemId": "", "neighborSystemId": ""},
              "receivingOpticalPower": {}, "transmittingOpticalPower": {}, "arpCaches": []} for c in rec["circuitInfos"]]
    return {"result": {"macAddress": "02:%s" % ":".join(hashlib.md5(name.encode()).hexdigest()[i:i + 2] for i in (0, 2, 4, 6, 8)),
                       "arpCaches": [], "links": links, "bundleOperationalStatus": "BUNDLE_OPERATIONAL_STATUS_UP" if up else "BUNDLE_OPERATIONAL_STATUS_DOWN"}}


def location_view(project, n):
    city, region, fac = LOC_BY_NAME[n]
    return {"kind": "compute#interconnectLocation", "id": str(int(hashlib.sha1(n.encode()).hexdigest()[:8], 16)), "name": n,
            "description": "%s - %s" % (fac, city), "selfLink": _link("projects/%s/global/interconnectLocations/%s" % (project, n)),
            "peeringdbFacilityId": str(int(hashlib.md5(n.encode()).hexdigest()[:4], 16) % 9000 + 100),
            "address": fac, "facilityProvider": fac.split()[0], "facilityProviderFacilityId": fac.split()[-1], "city": city,
            "continent": "C_" + ("EUROPE" if region.startswith("europe") else "ASIA_PAC" if region.startswith("asia") else "NORTH_AMERICA"),
            "status": "AVAILABLE", "availabilityZone": "zone1", "regionInfos": [{"region": _link("projects/%s/regions/%s" % (project, region)), "expectedRttMs": "2", "locationPresence": "GLOBAL"}],
            "supportsPzs": False}


# ── VLAN attachments ──────────────────────────────────────────────────────────
def _vpc_routers(vpc_store):
    return getattr(vpc_store, "routers", None) or {}


def _alloc_pair(store, project, candidates):
    used = {ipaddress.ip_network(a["_subnet"]) for a in _x(store, "attachments").values() if a.get("_subnet")}
    if candidates:
        for c in candidates:
            n = _cidr(c, "resource.candidateSubnets")
            if n.version != 4 or n.prefixlen != 29 or not n.subnet_of(ipaddress.ip_network("169.254.0.0/16")):
                raise _bad("Invalid value for field 'resource.candidateSubnets': '%s'. Must be a /29 within 169.254.0.0/16." % c)
            if n not in used and not any(n.overlaps(u) for u in used):
                return n
        raise _bad("None of the candidate subnets is available.")
    for third in range(1, 255):
        if third == 169:
            continue
        for fourth in range(0, 256, 8):
            n = ipaddress.ip_network("169.254.%d.%d/29" % (third, fourth))
            if n not in used:
                return n
    raise _E(400, "RESOURCE_EXHAUSTED", "No link-local /29 subnets are available.")


def _att_refresh(store, rec):
    ic = _x(store, "interconnects").get("projects/%s/global/interconnects/%s" % (rec["_project"], _last(rec.get("interconnect")))) if rec.get("interconnect") else None
    if rec["type"] in ("DEDICATED", "L2_DEDICATED"):
        up = rec["adminEnabled"] and ic is not None and ic["adminEnabled"]
        rec["state"], rec["operationalStatus"] = ("ACTIVE", "OS_ACTIVE") if up else ("UNPROVISIONED", "OS_UNPROVISIONED")
    else:      # PARTNER: needs the service provider to configure its side, which never happens here
        rec["state"] = "PENDING_PARTNER" if rec["adminEnabled"] else "UNPROVISIONED"
        rec["operationalStatus"] = "OS_UNPROVISIONED"


def att_insert(store, project, region, payload, vpc_store):
    _region(region)
    coll = _x(store, "attachments")
    name = _name(payload, "interconnect attachment")
    full = "projects/%s/regions/%s/interconnectAttachments/%s" % (project, region, name)
    if full in coll:
        raise _dup(full)
    atype = payload.get("type", "DEDICATED")
    if atype not in ATTACH_TYPES:
        raise _bad("Invalid value for field 'resource.type': '%s'. Must be one of %s." % (atype, ", ".join(ATTACH_TYPES)))
    if payload.get("mtu") is not None and payload["mtu"] not in MTUS:
        raise _bad("Invalid value for field 'resource.mtu': must be one of 1440, 1460, 8896.")
    if payload.get("edgeAvailabilityDomain", "AVAILABILITY_DOMAIN_ANY") not in AVAILABILITY:
        raise _bad("Invalid value for field 'resource.edgeAvailabilityDomain'.")
    if payload.get("encryption") not in (None, "NONE", "IPSEC"):
        raise _bad("Invalid value for field 'resource.encryption': must be NONE or IPSEC.")
    router = payload.get("router")
    if atype != "L2_DEDICATED":
        if not router:
            raise _bad("Invalid value for field 'resource.router': a Cloud Router is required.")
        rname = _last(router)
        rr = _vpc_routers(vpc_store).get("%s/%s/%s" % (project, region, rname)) if vpc_store is not None else None
        if vpc_store is not None and rr is None:
            raise _E(404, "NOT_FOUND", "The resource '%s' was not found" % _link("projects/%s/regions/%s/routers/%s" % (project, region, rname)))
    if payload.get("encryption") == "IPSEC" and not payload.get("ipsecInternalAddresses"):
        raise _bad("Invalid value for field 'resource.ipsecInternalAddresses': required when encryption is IPSEC.")
    ic = None
    if atype in ("DEDICATED", "L2_DEDICATED"):
        if not payload.get("interconnect"):
            raise _bad("Invalid value for field 'resource.interconnect': a Dedicated Interconnect is required for %s attachments." % atype)
        icfull = "projects/%s/global/interconnects/%s" % (project, _last(payload["interconnect"]))
        ic = _x(store, "interconnects").get(icfull)
        if ic is None:
            raise _E(404, "NOT_FOUND", "The resource '%s' was not found" % _link(icfull))
        loc_region = LOC_BY_NAME[_last(ic["location"])][1]
        if payload.get("bandwidth") is None:
            raise _bad("Invalid value for field 'resource.bandwidth': required.")
        vlan = payload.get("vlanTag8021q")
        if vlan is not None:
            if not isinstance(vlan, int) or not (2 <= vlan <= 4094):
                raise _bad("Invalid value for field 'resource.vlanTag8021q': must be between 2 and 4094.")
            if any(a.get("vlanTag8021q") == vlan and _last(a.get("interconnect")) == ic["name"] for a in coll.values()):
                raise _bad("Invalid value for field 'resource.vlanTag8021q': VLAN %d is already in use on interconnect '%s'." % (vlan, ic["name"]))
        else:
            used = {a.get("vlanTag8021q") for a in coll.values() if _last(a.get("interconnect")) == ic["name"]}
            vlan = next(v for v in range(2, 4095) if v not in used)
        cap = LINK_GBPS[ic["linkType"]] * ic["requestedLinkCount"] * 1000
        mbps = {"BPS_50M": 50, "BPS_100M": 100, "BPS_200M": 200, "BPS_300M": 300, "BPS_400M": 400, "BPS_500M": 500, "BPS_1G": 1000, "BPS_2G": 2000,
                "BPS_5G": 5000, "BPS_10G": 10000, "BPS_20G": 20000, "BPS_50G": 50000, "BPS_100G": 100000}
        if payload["bandwidth"] not in mbps:
            raise _bad("Invalid value for field 'resource.bandwidth': must be one of %s." % ", ".join(BANDWIDTHS))
        if mbps[payload["bandwidth"]] > cap:
            raise _bad("Invalid value for field 'resource.bandwidth': %s exceeds the interconnect's capacity of %d Mbps." % (payload["bandwidth"], cap))
    else:
        vlan = None
        if payload.get("bandwidth") is not None and payload["bandwidth"] not in BANDWIDTHS:
            raise _bad("Invalid value for field 'resource.bandwidth': must be one of %s." % ", ".join(BANDWIDTHS))
    n = _alloc_pair(store, project, payload.get("candidateSubnets"))
    hosts = list(n.hosts())
    rec = {"kind": "compute#interconnectAttachment", "id": str(G._next_id(store)), "creationTimestamp": _ts(), "name": name,
           "description": payload.get("description", ""), "selfLink": _link(full), "type": atype,
           "region": _link("projects/%s/regions/%s" % (project, region)), "adminEnabled": bool(payload.get("adminEnabled", True)),
           "bandwidth": payload.get("bandwidth"), "edgeAvailabilityDomain": payload.get("edgeAvailabilityDomain", "AVAILABILITY_DOMAIN_ANY"),
           "encryption": payload.get("encryption", "NONE"), "mtu": payload.get("mtu", 1440),
           "cloudRouterIpAddress": "%s/29" % hosts[0], "customerRouterIpAddress": "%s/29" % hosts[1],
           "googleReferenceId": uuid.uuid4().hex[:16], "labels": payload.get("labels") or {}, "stackType": payload.get("stackType", "IPV4_ONLY"),
           "_project": project, "_subnet": str(n)}
    if router:
        rec["router"] = _link("projects/%s/regions/%s/routers/%s" % (project, region, _last(router)))
    if ic is not None:
        rec["interconnect"] = ic["selfLink"]
        rec["vlanTag8021q"] = vlan
        rec["candidateSubnets"] = payload.get("candidateSubnets") or []
        ic["interconnectAttachments"].append(rec["selfLink"])
    else:
        rec["pairingKey"] = "%s/%s/%d" % (uuid.uuid4(), region, 1)
        rec["partnerMetadata"] = {}
    _att_refresh(store, rec)
    coll[full] = rec
    return _op(store, project, region, "insert", name, full)


def att_patch(store, project, region, name, payload):
    full = "projects/%s/regions/%s/interconnectAttachments/%s" % (project, region, name)
    rec = _x(store, "attachments").get(full)
    if rec is None:
        raise _nf(full)
    for k in ("description", "adminEnabled", "bandwidth", "mtu", "labels"):
        if k in payload:
            if k == "bandwidth" and payload[k] not in BANDWIDTHS:
                raise _bad("Invalid value for field 'resource.bandwidth'.")
            if k == "mtu" and payload[k] not in MTUS:
                raise _bad("Invalid value for field 'resource.mtu': must be one of 1440, 1460, 8896.")
            rec[k] = payload[k]
    _att_refresh(store, rec)
    return _op(store, project, region, "patch", name, full)


def att_delete(store, project, region, name):
    coll = _x(store, "attachments")
    full = "projects/%s/regions/%s/interconnectAttachments/%s" % (project, region, name)
    rec = coll.get(full)
    if rec is None:
        raise _nf(full)
    ic = _x(store, "interconnects").get("projects/%s/global/interconnects/%s" % (project, _last(rec.get("interconnect")))) if rec.get("interconnect") else None
    if ic:
        ic["interconnectAttachments"] = [a for a in ic["interconnectAttachments"] if not a.endswith("/" + name)]
    del coll[full]
    return _op(store, project, region, "delete", name, full)


# ── dispatch ──────────────────────────────────────────────────────────────────
def _pub(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


GLOBAL_COLLS = {"publicAdvertisedPrefixes": "pap", "interconnects": "interconnects"}
REGIONAL_COLLS = {"publicDelegatedPrefixes": "pdp", "interconnectAttachments": "attachments"}


def handle(store, method, project, rest, verb, payload, query, vpc_store=None):
    """ComputeResponse for a path this core owns, else None."""
    if not rest:
        return None
    if rest[0] == "aggregated" and len(rest) == 2 and rest[1] in ("publicDelegatedPrefixes", "interconnectAttachments") and method == "GET":
        key = rest[1]
        coll = REGIONAL_COLLS[key]
        out = _agg(store, coll, project, key, "compute#%sAggregatedList" % key[:-1])
        for sc in out["items"].values():
            sc[key] = [_pub(v) for v in sc[key]]
        return _json(200, out)
    if len(rest) < 2 or rest[0] not in ("global", "regions"):
        return None
    if rest[0] == "global":
        coll_name, tail, scope = rest[1], rest[2:], None
        if coll_name == "interconnectLocations":
            if method != "GET":
                raise _E(405, "UNIMPLEMENTED", "Method %s not supported." % method)
            if not tail:
                return _json(200, _list("compute#interconnectLocationList", [location_view(project, n) for n, *_ in LOCATIONS], project, "global/interconnectLocations"))
            if tail[0] not in LOC_BY_NAME:
                raise _nf("projects/%s/global/interconnectLocations/%s" % (project, tail[0]))
            return _json(200, location_view(project, tail[0]))
        if coll_name not in GLOBAL_COLLS:
            return None
    else:
        if len(rest) < 3 or rest[2] not in REGIONAL_COLLS:
            return None
        scope, coll_name, tail = rest[1], rest[2], rest[3:]
    if ":" in (tail[-1] if tail else ""):
        tail[-1], verb = tail[-1].rsplit(":", 1)
    if not verb and len(tail) == 2 and tail[1] in ("announce", "withdraw", "getDiagnostics"):
        tail, verb = tail[:1], tail[1]
    coll = (GLOBAL_COLLS if scope is None else REGIONAL_COLLS)[coll_name]
    pre = "projects/%s/%s/%s/" % (project, "global" if scope is None else "regions/" + scope, coll_name)
    if not tail:
        if method == "GET":
            if scope is not None:
                _region(scope)
            return _json(200, _list("compute#%sList" % coll_name[:-1], [_pub(v) for k, v in sorted(_x(store, coll).items()) if k.startswith(pre)],
                                    project, pre[len("projects/%s/" % project):-1]))
        if method == "POST":
            if coll_name == "publicAdvertisedPrefixes":
                return _json(200, pap_insert(store, project, payload))
            if coll_name == "interconnects":
                return _json(200, ic_insert(store, project, payload))
            if coll_name == "publicDelegatedPrefixes":
                return _json(200, pdp_insert(store, project, scope, payload))
            return _json(200, att_insert(store, project, scope, payload, vpc_store))
        raise _E(405, "UNIMPLEMENTED", "Method %s not supported." % method)
    name = tail[0]
    rec = _x(store, coll).get(pre + name)
    if rec is None:
        raise _nf(pre + name)
    if method == "GET" and not verb:
        return _json(200, _pub(rec))
    if method == "GET" and verb == "getDiagnostics" and coll_name == "interconnects":
        return _json(200, ic_diagnostics(store, project, name))
    if method == "POST" and verb in ("announce", "withdraw"):
        if coll_name == "publicAdvertisedPrefixes":
            return _json(200, pap_verb(store, project, name, verb))
        if coll_name == "publicDelegatedPrefixes":
            return _json(200, pdp_verb(store, project, scope, name, verb, payload))
    if method == "DELETE":
        fn = {"publicAdvertisedPrefixes": lambda: pap_delete(store, project, name), "interconnects": lambda: ic_delete(store, project, name),
              "publicDelegatedPrefixes": lambda: pdp_delete(store, project, scope, name),
              "interconnectAttachments": lambda: att_delete(store, project, scope, name)}[coll_name]
        return _json(200, fn())
    if method in ("PATCH", "PUT"):
        if coll_name == "interconnects":
            return _json(200, ic_patch(store, project, name, payload))
        if coll_name == "interconnectAttachments":
            return _json(200, att_patch(store, project, scope, name, payload))
        if coll_name == "publicDelegatedPrefixes":
            return _json(200, pdp_patch(store, project, scope, name, payload))
        if coll_name == "publicAdvertisedPrefixes":
            if "description" in payload:
                rec["description"] = payload["description"]
            return _json(200, _op(store, project, None, "patch", name, pre + name))
    raise _E(405, "UNIMPLEMENTED", "Method %s not supported." % method)
