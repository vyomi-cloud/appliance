# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""AWS Network Manager (service `networkmanager`, SigV4 signing name `networkmanager`, rest-json) - substrate-independent.

The control-plane inventory of the real service: global networks, sites, devices, links, link associations (device <-> link) and
transit gateway registrations, with the real paths (POST /global-networks, GET/POST /global-networks/{id}/sites ...), ID formats
(global-network-/site-/device-/link- + 17 hex), ARNs, state fields, tags and the real dependency errors (a global network with
sites, devices, links or registered transit gateways cannot be deleted; a site with devices or links cannot be deleted; a device
or link with associations cannot be deleted; a transit gateway can be registered to ONE global network and must exist in the
account's EC2/VPC model). State lives in ``s3_store.account["networkmanager"]``.

Honest limits: this is the inventory/registration control plane. No topology telemetry, events, route analysis, Connect
attachments, customer-gateway / Direct Connect associations or network-routing analysis are modelled.
"""
from __future__ import annotations

import json
import re
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import unquote

ACCT = "123456789012"
REGION = "us-west-2"          # Network Manager's home Region
TGW_ARN = re.compile(r"^arn:aws:ec2:([a-z0-9-]+):(\d{12}):transit-gateway/(tgw-[0-9a-f]{8,17})$")


class _Err(Exception):
    def __init__(self, code, message, status=400):
        self.code, self.message, self.status = code, message, status


def _bad(msg):
    return _Err("ValidationException", msg, 400)


def _nf(kind, rid):
    return _Err("ResourceNotFoundException", f"{kind} {rid} not found.", 404)


def _conflict(msg):
    return _Err("ConflictException", msg, 409)


def _ts():
    return time.time()


def _state(s3_store) -> dict:
    st = s3_store.account.setdefault("networkmanager", {})
    st.setdefault("gn", {})
    return st


def _rid(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:17]}"


def _gn(st, gid):
    g = st["gn"].get(gid)
    if not g:
        raise _nf("Global network", gid)
    return g


def _arn(kind, gid, rid=None):
    return f"arn:aws:networkmanager::{ACCT}:{kind}/{gid}" + (f"/{rid}" if rid else "")


def _tags(p):
    t = p.get("Tags") or []
    if not isinstance(t, list) or len(t) > 50:
        raise _bad("Tags must be a list of at most 50 Key/Value entries.")
    out = []
    for x in t:
        if not isinstance(x, dict) or not x.get("Key") or len(str(x["Key"])) > 128 or len(str(x.get("Value", ""))) > 256:
            raise _bad("Each tag needs a Key (max 128) and a Value (max 256).")
        if str(x["Key"]).lower().startswith("aws:"):
            raise _bad("Tag keys starting with aws: are reserved.")
        out.append({"Key": str(x["Key"]), "Value": str(x.get("Value", ""))})
    return out


def _desc(p):
    d = p.get("Description", "")
    if len(str(d)) > 256:
        raise _bad("Description must be at most 256 characters.")
    return str(d)


def _location(p):
    loc = p.get("Location")
    if loc is None:
        return None
    if not isinstance(loc, dict):
        raise _bad("Location must be an object.")
    for k, lo, hi in (("Latitude", -90, 90), ("Longitude", -180, 180)):
        if loc.get(k) not in (None, ""):
            try:
                v = float(loc[k])
            except (TypeError, ValueError):
                raise _bad(f"Location.{k} must be a number.")
            if not lo <= v <= hi:
                raise _bad(f"Location.{k} must be between {lo} and {hi}.")
    return {k: str(v) for k, v in loc.items() if k in ("Address", "Latitude", "Longitude") and v not in (None, "")}


def _iso(t):
    return round(t, 3)


# ── views ─────────────────────────────────────────────────────────────────────────────────────
def _gn_view(g):
    return {"GlobalNetworkId": g["id"], "GlobalNetworkArn": _arn("global-network", g["id"]), "Description": g["description"], "CreatedAt": _iso(g["created"]),
            "State": "AVAILABLE", "Tags": g["tags"]}


def _site_view(g, s):
    return {"SiteId": s["id"], "SiteArn": _arn("site", g["id"], s["id"]), "GlobalNetworkId": g["id"], "Description": s["description"], "Location": s["location"],
            "CreatedAt": _iso(s["created"]), "State": "AVAILABLE", "Tags": s["tags"]}


def _dev_view(g, d):
    return {"DeviceId": d["id"], "DeviceArn": _arn("device", g["id"], d["id"]), "GlobalNetworkId": g["id"], "Description": d["description"], "Type": d.get("type"),
            "Vendor": d.get("vendor"), "Model": d.get("model"), "SerialNumber": d.get("serial"), "Location": d["location"], "SiteId": d.get("site"),
            "CreatedAt": _iso(d["created"]), "State": "AVAILABLE", "Tags": d["tags"]}


def _link_view(g, l):
    return {"LinkId": l["id"], "LinkArn": _arn("link", g["id"], l["id"]), "GlobalNetworkId": g["id"], "SiteId": l["site"], "Description": l["description"],
            "Type": l.get("type"), "Bandwidth": l["bandwidth"], "Provider": l.get("provider"), "CreatedAt": _iso(l["created"]), "State": "AVAILABLE", "Tags": l["tags"]}


def _tgw_in_model(vpc_store, arn):
    m = TGW_ARN.match(arn or "")
    if not m:
        raise _bad(f"Invalid transit gateway ARN: {arn}")
    try:
        from core import vpc_core
    except ImportError:
        import vpc_core  # type: ignore
    tgws = vpc_core._model(vpc_store).get("tgws", {})
    t = tgws.get(m.group(3))
    if not t or t.get("state") in ("deleted", "deleting"):
        raise _nf("Transit gateway", arn)
    return t


def _tg_registration_view(g, r, vpc_store):
    return {"GlobalNetworkId": g["id"], "TransitGatewayArn": r["arn"], "State": {"Code": "AVAILABLE"}}


# ── operations ────────────────────────────────────────────────────────────────────────────────
def create_global_network(st, vp, p, q, gid=None):
    rid = _rid("global-network")
    st["gn"][rid] = {"id": rid, "description": _desc(p), "created": _ts(), "tags": _tags(p), "sites": {}, "devices": {}, "links": {}, "assoc": [], "tgw": {}}
    return {"GlobalNetwork": _gn_view(st["gn"][rid])}


def describe_global_networks(st, vp, p, q, gid=None):
    ids = q.get("globalNetworkIds")
    ids = [ids] if isinstance(ids, str) else (ids or [])
    rows = [_gn_view(g) for g in st["gn"].values() if not ids or g["id"] in ids]
    return {"GlobalNetworks": rows}


def delete_global_network(st, vp, p, q, gid=None):
    g = _gn(st, gid)
    for kind, key in (("sites", "sites"), ("devices", "devices"), ("links", "links")):
        if g[key]:
            raise _conflict(f"The global network still has {kind}; delete them first.")
    if g["tgw"]:
        raise _conflict("The global network still has registered transit gateways; deregister them first.")
    del st["gn"][gid]
    return {"GlobalNetwork": {**_gn_view(g), "State": "DELETING"}}


def update_global_network(st, vp, p, q, gid=None):
    g = _gn(st, gid)
    if "Description" in p:
        g["description"] = _desc(p)
    return {"GlobalNetwork": _gn_view(g)}


def create_site(st, vp, p, q, gid=None):
    g = _gn(st, gid)
    sid = _rid("site")
    g["sites"][sid] = {"id": sid, "description": _desc(p), "location": _location(p), "created": _ts(), "tags": _tags(p)}
    return {"Site": _site_view(g, g["sites"][sid])}


def get_sites(st, vp, p, q, gid=None):
    g = _gn(st, gid)
    ids = q.get("siteIds")
    ids = [ids] if isinstance(ids, str) else (ids or [])
    return {"Sites": [_site_view(g, s) for s in g["sites"].values() if not ids or s["id"] in ids]}


def delete_site(st, vp, p, q, gid=None, rid=None):
    g = _gn(st, gid)
    s = g["sites"].get(rid)
    if not s:
        raise _nf("Site", rid)
    if any(d.get("site") == rid for d in g["devices"].values()) or any(l["site"] == rid for l in g["links"].values()):
        raise _conflict("The site still has devices or links; delete them first.")
    del g["sites"][rid]
    return {"Site": {**_site_view(g, s), "State": "DELETING"}}


def create_device(st, vp, p, q, gid=None):
    g = _gn(st, gid)
    if p.get("SiteId") and p["SiteId"] not in g["sites"]:
        raise _nf("Site", p["SiteId"])
    for k in ("Type", "Vendor", "Model", "SerialNumber"):
        if p.get(k) is not None and len(str(p[k])) > 128:
            raise _bad(f"{k} must be at most 128 characters.")
    aws = p.get("AWSLocation")
    if aws is not None and not (isinstance(aws, dict) and (aws.get("Zone") or aws.get("SubnetArn"))):
        raise _bad("AWSLocation needs a Zone or a SubnetArn.")
    did = _rid("device")
    g["devices"][did] = {"id": did, "description": _desc(p), "site": p.get("SiteId"), "type": p.get("Type"), "vendor": p.get("Vendor"), "model": p.get("Model"),
                         "serial": p.get("SerialNumber"), "location": _location(p) or (aws and {"Address": ""}) or None, "created": _ts(), "tags": _tags(p), "aws": aws}
    return {"Device": _dev_view(g, g["devices"][did])}


def get_devices(st, vp, p, q, gid=None):
    g = _gn(st, gid)
    ids = q.get("deviceIds")
    ids = [ids] if isinstance(ids, str) else (ids or [])
    return {"Devices": [_dev_view(g, d) for d in g["devices"].values() if (not ids or d["id"] in ids) and (not q.get("siteId") or d.get("site") == q["siteId"])]}


def delete_device(st, vp, p, q, gid=None, rid=None):
    g = _gn(st, gid)
    d = g["devices"].get(rid)
    if not d:
        raise _nf("Device", rid)
    if any(a["DeviceId"] == rid for a in g["assoc"]):
        raise _conflict("The device still has link associations; disassociate them first.")
    del g["devices"][rid]
    return {"Device": {**_dev_view(g, d), "State": "DELETING"}}


def create_link(st, vp, p, q, gid=None):
    g = _gn(st, gid)
    if not p.get("SiteId"):
        raise _bad("SiteId is required.")
    if p["SiteId"] not in g["sites"]:
        raise _nf("Site", p["SiteId"])
    bw = p.get("Bandwidth")
    if not isinstance(bw, dict) or not (bw.get("UploadSpeed") or bw.get("DownloadSpeed")):
        raise _bad("Bandwidth needs an UploadSpeed and/or a DownloadSpeed (Mbps).")
    for k in ("UploadSpeed", "DownloadSpeed"):
        if bw.get(k) is not None and (not isinstance(bw[k], int) or isinstance(bw[k], bool) or bw[k] < 1):
            raise _bad(f"Bandwidth.{k} must be a positive integer (Mbps).")
    lid = _rid("link")
    g["links"][lid] = {"id": lid, "site": p["SiteId"], "description": _desc(p), "type": p.get("Type"), "bandwidth": {k: bw[k] for k in ("UploadSpeed", "DownloadSpeed") if bw.get(k) is not None},
                       "provider": p.get("Provider"), "created": _ts(), "tags": _tags(p)}
    return {"Link": _link_view(g, g["links"][lid])}


def get_links(st, vp, p, q, gid=None):
    g = _gn(st, gid)
    ids = q.get("linkIds")
    ids = [ids] if isinstance(ids, str) else (ids or [])
    return {"Links": [_link_view(g, l) for l in g["links"].values() if (not ids or l["id"] in ids) and (not q.get("siteId") or l["site"] == q["siteId"])]}


def delete_link(st, vp, p, q, gid=None, rid=None):
    g = _gn(st, gid)
    l = g["links"].get(rid)
    if not l:
        raise _nf("Link", rid)
    if any(a["LinkId"] == rid for a in g["assoc"]):
        raise _conflict("The link still has device associations; disassociate them first.")
    del g["links"][rid]
    return {"Link": {**_link_view(g, l), "State": "DELETING"}}


def associate_link(st, vp, p, q, gid=None):
    g = _gn(st, gid)
    did, lid = p.get("DeviceId"), p.get("LinkId")
    if did not in g["devices"]:
        raise _nf("Device", did)
    if lid not in g["links"]:
        raise _nf("Link", lid)
    if g["devices"][did].get("site") != g["links"][lid]["site"]:
        raise _bad("The device and the link must belong to the same site.")
    if any(a["DeviceId"] == did and a["LinkId"] == lid for a in g["assoc"]):
        raise _conflict("The link is already associated with the device.")
    a = {"GlobalNetworkId": gid, "DeviceId": did, "LinkId": lid, "LinkAssociationState": "AVAILABLE"}
    g["assoc"].append(a)
    return {"LinkAssociation": a}


def get_link_associations(st, vp, p, q, gid=None):
    g = _gn(st, gid)
    return {"LinkAssociations": [a for a in g["assoc"] if (not q.get("deviceId") or a["DeviceId"] == q["deviceId"]) and (not q.get("linkId") or a["LinkId"] == q["linkId"])]}


def disassociate_link(st, vp, p, q, gid=None):
    g = _gn(st, gid)
    for a in g["assoc"]:
        if a["DeviceId"] == q.get("deviceId") and a["LinkId"] == q.get("linkId"):
            g["assoc"].remove(a)
            return {"LinkAssociation": {**a, "LinkAssociationState": "DELETING"}}
    raise _nf("Link association", f"{q.get('deviceId')}/{q.get('linkId')}")


def register_tgw(st, vp, p, q, gid=None):
    g = _gn(st, gid)
    arn = p.get("TransitGatewayArn")
    _tgw_in_model(vp, arn)
    for og in st["gn"].values():
        if arn in og["tgw"]:
            raise _conflict(f"The transit gateway is already registered to global network {og['id']}." if og is not g else "The transit gateway is already registered to this global network.")
    g["tgw"][arn] = {"arn": arn, "created": _ts()}
    return {"TransitGatewayRegistration": _tg_registration_view(g, g["tgw"][arn], vp)}


def get_tgw_registrations(st, vp, p, q, gid=None):
    g = _gn(st, gid)
    arns = q.get("transitGatewayArns")
    arns = [arns] if isinstance(arns, str) else (arns or [])
    return {"TransitGatewayRegistrations": [_tg_registration_view(g, r, vp) for r in g["tgw"].values() if not arns or r["arn"] in arns]}


def deregister_tgw(st, vp, p, q, gid=None, rid=None):
    g = _gn(st, gid)
    arn = unquote(rid or "")
    r = g["tgw"].get(arn)
    if not r:
        raise _nf("Transit gateway registration", arn)
    del g["tgw"][arn]
    return {"TransitGatewayRegistration": {**_tg_registration_view(g, r, vp), "State": {"Code": "DELETING"}}}


def _resource_by_arn(st, arn):
    m = re.match(r"^arn:aws:networkmanager::\d{12}:([a-z-]+)/(global-network-[0-9a-f]+)(?:/([a-z]+-[0-9a-f]+))?$", arn or "")
    if not m:
        raise _bad(f"Invalid resource ARN: {arn}")
    kind, gid, rid = m.groups()
    g = _gn(st, gid)
    tbl = {"global-network": None, "site": "sites", "device": "devices", "link": "links"}.get(kind)
    if kind == "global-network":
        return g
    if tbl is None or rid not in g[tbl]:
        raise _nf(kind, rid)
    return g[tbl][rid]


def tag_ops(st, method, arn, p, q):
    r = _resource_by_arn(st, arn)
    if method == "GET":
        return {"TagList": r["tags"]}
    if method == "POST":
        new = _tags(p)
        cur = {t["Key"]: t for t in r["tags"]}
        for t in new:
            cur[t["Key"]] = t
        if len(cur) > 50:
            raise _bad("A resource can have at most 50 tags.")
        r["tags"] = list(cur.values())
        return {}
    keys = q.get("tagKeys")
    keys = [keys] if isinstance(keys, str) else (keys or [])
    r["tags"] = [t for t in r["tags"] if t["Key"] not in keys]
    return {}


_ROUTES = [  # (method, path regex, handler)
    ("POST", r"^/global-networks$", create_global_network), ("GET", r"^/global-networks$", describe_global_networks),
    ("PATCH", r"^/global-networks/(?P<gid>[^/]+)$", update_global_network), ("DELETE", r"^/global-networks/(?P<gid>[^/]+)$", delete_global_network),
    ("POST", r"^/global-networks/(?P<gid>[^/]+)/sites$", create_site), ("GET", r"^/global-networks/(?P<gid>[^/]+)/sites$", get_sites),
    ("DELETE", r"^/global-networks/(?P<gid>[^/]+)/sites/(?P<rid>[^/]+)$", delete_site),
    ("POST", r"^/global-networks/(?P<gid>[^/]+)/devices$", create_device), ("GET", r"^/global-networks/(?P<gid>[^/]+)/devices$", get_devices),
    ("DELETE", r"^/global-networks/(?P<gid>[^/]+)/devices/(?P<rid>[^/]+)$", delete_device),
    ("POST", r"^/global-networks/(?P<gid>[^/]+)/links$", create_link), ("GET", r"^/global-networks/(?P<gid>[^/]+)/links$", get_links),
    ("DELETE", r"^/global-networks/(?P<gid>[^/]+)/links/(?P<rid>[^/]+)$", delete_link),
    ("POST", r"^/global-networks/(?P<gid>[^/]+)/link-associations$", associate_link), ("GET", r"^/global-networks/(?P<gid>[^/]+)/link-associations$", get_link_associations),
    ("DELETE", r"^/global-networks/(?P<gid>[^/]+)/link-associations$", disassociate_link),
    ("POST", r"^/global-networks/(?P<gid>[^/]+)/transit-gateway-registrations$", register_tgw),
    ("GET", r"^/global-networks/(?P<gid>[^/]+)/transit-gateway-registrations$", get_tgw_registrations),
    ("DELETE", r"^/global-networks/(?P<gid>[^/]+)/transit-gateway-registrations/(?P<rid>.+)$", deregister_tgw),
]
_COMPILED = [(m, re.compile(rx), fn) for m, rx, fn in _ROUTES]


def dispatch(s3_store, vpc_store, method, path, query, body):
    method = method.upper()
    path = "/" + (path or "").strip("/")
    q = {k: (v[0] if isinstance(v, list) and len(v) == 1 else v) for k, v in (query or {}).items()}

    def resp(status, doc, err=None):
        h = {"content-type": "application/json"}
        if err:
            h["x-amzn-errortype"] = err
        return {"status": status, "headers": h, "body": json.dumps(doc).encode()}
    try:
        p = json.loads(body) if body else {}
        if not isinstance(p, dict):
            raise ValueError
    except ValueError:
        return resp(400, {"__type": "ValidationException", "message": "The request body must be a JSON object."}, "ValidationException")
    st = _state(s3_store)
    try:
        if path.startswith("/tags/"):
            out = tag_ops(st, method, unquote(path[6:]), p, q)
        else:
            for m, rx, fn in _COMPILED:
                mt = rx.match(path) if m == method else None
                if mt:
                    out = fn(st, vpc_store, p, q, **mt.groupdict())
                    break
            else:
                return resp(404, {"__type": "UnknownOperationException", "message": f"Unknown operation {method} {path}"}, "UnknownOperationException")
        if method != "GET":
            try:
                s3_store.persist()
            except Exception:
                pass
        return resp(200, out)
    except _Err as e:
        return resp(e.status, {"__type": e.code, "message": e.message, "Message": e.message}, e.code)


def tgw_registrations_for(s3_store):
    """{tgw arn: global network id} - lets the VPC console show which transit gateways are registered."""
    return {arn: g["id"] for g in _state(s3_store)["gn"].values() for arn in g["tgw"]}
