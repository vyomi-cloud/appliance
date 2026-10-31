"""GCP Compute Engine **networking** core — substrate-independent. Speaks the native
**Compute Engine REST API v1** (`compute.googleapis.com/compute/v1`) so the native
`google-cloud-compute` SDK / `gcloud compute ...` work unchanged against it (point the
client's api_endpoint at this relay).

NO fastapi / google-cloud / socket / subprocess imports → loads under Pyodide, so the
SAME file runs offline and in Nano.

Scope: the console's "VPC network" product only — networks, subnetworks, firewalls,
routes and addresses (regional + global), plus the aggregatedList views the console
uses for its "all regions" tabs. Virtual machines, disks and the rest of Compute
Engine are a separate product/core; out of scope here.

Resources (Compute Engine v1 shapes):
    projects/{p}/global/networks/{network}
    projects/{p}/regions/{r}/subnetworks/{subnetwork}  (+ aggregated/subnetworks)
    projects/{p}/global/firewalls/{firewall}
    projects/{p}/global/routes/{route}
    projects/{p}/regions/{r}/addresses/{address}       (+ aggregated/addresses)
    projects/{p}/global/addresses/{address}
    projects/{p}/global/operations/{operation}

Every mutation returns a completed `Operation` (status DONE) like a very fast real
cloud — the same pattern core/gcp_container_core.py uses. GCP errors use the Google
JSON API shape `{"error":{"code","message","status"}}`.
"""
from __future__ import annotations

import ipaddress
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

REGIONS = [
    "us-central1", "us-east1", "us-east4", "us-west1",
    "europe-west1", "europe-west4", "asia-south1", "asia-southeast1", "asia-northeast1",
]
DEFAULT_REGION = "us-central1"
DEFAULT_MTU = 1460
DEFAULT_NETWORK_TIER = "PREMIUM"


@dataclass
class ComputeResponse:
    status: int = 200
    headers: dict = field(default_factory=dict)
    body: bytes = b""
    media_type: str | None = "application/json"


class ComputeStore:
    """Public dict attrs only → persisted/synced by core/nano_persist."""

    def __init__(self):
        self.networks: dict = {}       # "project/name" -> network resource
        self.subnetworks: dict = {}    # "project/region/name" -> subnetwork resource
        self.firewalls: dict = {}      # "project/name" -> firewall resource
        self.routes: dict = {}         # "project/name" -> route resource
        self.addresses: dict = {}      # "project/scope/name" -> address resource (scope = region or "global")
        self.routers: dict = {}        # "project/region/name" -> Cloud Router (+ Cloud NAT configs)
        self.connectivity_tests: dict = {}   # "project/name" -> Network Intelligence Center connectivity test
        self.seq: dict = {"op": 0, "ip": 0}


def _bucket(store, name: str) -> dict:
    """Stores created before an attribute existed (persisted / slot-backed) get it lazily."""
    d = getattr(store, name, None)
    if d is None:
        d = {}
        setattr(store, name, d)
    return d


class _E(Exception):
    def __init__(self, status, gcp_status, message):
        super().__init__(message)
        self.status, self.gcp_status, self.message = status, gcp_status, message


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _json(status: int, obj: dict) -> ComputeResponse:
    return ComputeResponse(status=status, body=json.dumps(obj).encode())


def _err(status: int, gcp_status: str, message: str) -> ComputeResponse:
    body = {"error": {"code": status, "message": message, "status": gcp_status,
                       "errors": [{"domain": "global", "reason": gcp_status.lower(), "message": message}]}}
    return ComputeResponse(status=status, body=json.dumps(body).encode())


def _not_found(message: str) -> ComputeResponse:
    return _err(404, "NOT_FOUND", message)


_NAME = re.compile(r"^[a-z]([-a-z0-9]{0,61}[a-z0-9])?$")


def _check_name(name, what="Name"):
    if not name or not _NAME.match(str(name)):
        raise _E(400, "INVALID_ARGUMENT",
                  f"{what} must be 1-63 characters, start with a lowercase letter, and contain only "
                  "lowercase letters, numbers and hyphens.")


def _self_link(kind: str, project: str, tail: str) -> str:
    return f"https://compute.googleapis.com/compute/v1/projects/{project}/{kind}/{tail}"


def _operation(project: str, scope_kind: str, scope: str | None, op_type: str, target_link: str, store: ComputeStore) -> dict:
    store.seq["op"] += 1
    name = f"operation-{store.seq['op']}-{uuid.uuid4().hex[:12]}"
    tail = f"global/operations/{name}" if scope_kind == "global" else f"regions/{scope}/operations/{name}"
    return {
        "kind": "compute#operation",
        "id": str(store.seq["op"]),
        "name": name,
        "operationType": op_type,
        "targetLink": target_link,
        "status": "DONE",
        "progress": 100,
        "insertTime": _ts(),
        "startTime": _ts(),
        "endTime": _ts(),
        "selfLink": _self_link(scope_kind if scope_kind == "global" else f"regions/{scope}", project, f"operations/{name}"),
        **({"region": _self_link("regions", project, scope)} if scope_kind == "regional" else {}),
    }


# ── networks ─────────────────────────────────────────────────────────────────
def _net_key(project, name):
    return f"{project}/{name}"


def _network_view(rec: dict) -> dict:
    project, name = rec["project"], rec["name"]
    out = {
        "kind": "compute#network",
        "id": rec["id"],
        "name": name,
        "description": rec.get("description", ""),
        "autoCreateSubnetworks": rec.get("autoCreateSubnetworks", False),
        "subnetworks": [_self_link("regions", project, f"{s['region']}/subnetworks/{s['name']}")
                         for s in rec.get("_subnets", [])],
        "routingConfig": {"routingMode": rec.get("routingMode", "REGIONAL")},
        "mtu": rec.get("mtu", DEFAULT_MTU),
        "creationTimestamp": rec["creationTimestamp"],
        "selfLink": _self_link("global", project, f"networks/{name}"),
    }
    if rec.get("peerings"):
        out["peerings"] = [dict(p) for p in rec["peerings"]]
    if rec.get("ulaInternalIpv6Range"):
        out["internalIpv6Range"] = rec["ulaInternalIpv6Range"]
        out["enableUlaInternalIpv6"] = True
    return out


def _insert_network(store: ComputeStore, project: str, body: dict) -> ComputeResponse:
    name = str(body.get("name", "")).strip()
    try:
        _check_name(name, "Network name")
    except _E as e:
        return _err(e.status, e.gcp_status, e.message)
    if _net_key(project, name) in store.networks:
        return _err(409, "ALREADY_EXISTS", f"The resource 'projects/{project}/global/networks/{name}' already exists")
    store.seq["ip"] += 1
    rec = {
        "id": str(10_000 + store.seq["ip"]),
        "project": project,
        "name": name,
        "description": str(body.get("description", "")),
        "autoCreateSubnetworks": bool(body.get("autoCreateSubnetworks", False)),
        "mtu": int(body.get("mtu") or DEFAULT_MTU),
        "routingMode": (body.get("routingConfig") or {}).get("routingMode", "REGIONAL"),
        "creationTimestamp": _ts(),
        "_subnets": [],
        "_hasDefaultRoute": True,
    }
    if body.get("enableUlaInternalIpv6"):
        rec["ulaInternalIpv6Range"] = body.get("internalIpv6Range") or f"fd20:{uuid.uuid4().hex[:4]}:{uuid.uuid4().hex[:4]}::/48"
    store.networks[_net_key(project, name)] = rec
    # GCP creates the default internet route with every VPC network (deletable by the user)
    store.seq["ip"] += 1
    rname = f"default-route-{uuid.uuid4().hex[:16]}"
    store.routes[_route_key(project, rname)] = {
        "id": str(40_000 + store.seq["ip"]), "project": project, "name": rname,
        "description": "Default route to the Internet.", "networkName": name, "destRange": "0.0.0.0/0",
        "priority": 1000, "tags": [], "_system": True, "creationTimestamp": _ts(),
        "nextHop": {"nextHopGateway": _self_link("global", project, "gateways/default-internet-gateway")}}
    if rec["autoCreateSubnetworks"]:
        for i, region in enumerate(REGIONS):
            _create_subnet(store, project, region, {
                "name": f"{name}-{region}", "network": name,
                "ipCidrRange": f"10.{128 + i}.0.0/20",
            }, auto=True)
    return _json(200, _operation(project, "global", None, "insert", _self_link("global", project, f"networks/{name}"), store))


def _list_networks(store: ComputeStore, project: str) -> ComputeResponse:
    items = [_network_view(r) for k, r in sorted(store.networks.items()) if k.startswith(f"{project}/")]
    out = {"kind": "compute#networkList", "id": f"projects/{project}/global/networks", "selfLink": _self_link("global", project, "networks")}
    if items:
        out["items"] = items
    return _json(200, out)


def _get_network(store: ComputeStore, project: str, name: str) -> ComputeResponse:
    rec = store.networks.get(_net_key(project, name))
    if not rec:
        return _not_found(f"The resource 'projects/{project}/global/networks/{name}' was not found")
    return _json(200, _network_view(rec))


def _delete_network(store: ComputeStore, project: str, name: str) -> ComputeResponse:
    key = _net_key(project, name)
    rec = store.networks.get(key)
    if not rec:
        return _not_found(f"The resource 'projects/{project}/global/networks/{name}' was not found")
    using = [s["name"] for s in rec.get("_subnets", [])]
    using += [f["name"] for f in store.firewalls.values() if f["project"] == project and f["networkName"] == name]
    using += [r["name"] for r in store.routes.values()
              if r["project"] == project and r["networkName"] == name and not r.get("_system")]
    using += [r["name"] for r in _bucket(store, "routers").values() if r["project"] == project and r["networkName"] == name]
    if using:
        return _err(400, "RESOURCE_IN_USE_BY_ANOTHER_RESOURCE",
                    f"The network resource '{name}' is already being used by {using[0]}")
    for rk in [k for k, r in store.routes.items() if r["project"] == project and r["networkName"] == name and r.get("_system")]:
        del store.routes[rk]
    for other in store.networks.values():     # the peer side flips to INACTIVE, like GCP
        for p in other.get("peerings", []):
            if _tail(p.get("network")) == name:
                p["state"], p["stateDetails"] = "INACTIVE", "Peer network deleted"
    del store.networks[key]
    return _json(200, _operation(project, "global", None, "delete", _self_link("global", project, f"networks/{name}"), store))


def _tail(link) -> str:
    return str(link or "").rstrip("/").split("/")[-1]


def _peer_state(store, project, a: str, b: str) -> str:
    nb = store.networks.get(_net_key(project, b))
    if nb is None:
        return "INACTIVE"
    return "ACTIVE" if any(_tail(p.get("network")) == a for p in nb.get("peerings", [])) else "INACTIVE"


def _refresh_peerings(store, project) -> None:
    for n in store.networks.values():
        if n["project"] != project:
            continue
        for p in n.get("peerings", []):
            st = _peer_state(store, project, n["name"], _tail(p["network"]))
            p["state"] = st
            p["stateDetails"] = "[2026-01-01T00:00:00Z]: Connected." if st == "ACTIVE" else "Waiting for peer network to connect."


def _add_peering(store, project, name, body) -> ComputeResponse:
    rec = store.networks.get(_net_key(project, name))
    if not rec:
        return _not_found(f"The resource 'projects/{project}/global/networks/{name}' was not found")
    nc = body.get("networkPeering") or {}
    pname = str(body.get("name") or nc.get("name") or "").strip()
    peer = nc.get("network") or body.get("peerNetwork") or ""
    if not pname or not peer:
        return _err(400, "INVALID_ARGUMENT", "networkPeering.name and networkPeering.network are required")
    if any(p["name"] == pname for p in rec.setdefault("peerings", [])):
        return _err(409, "ALREADY_EXISTS", f"There is already a peering {pname} on network {name}")
    peer_link = peer if peer.startswith("http") else _self_link("global", project, f"networks/{_tail(peer)}")
    rec["peerings"].append({"name": pname, "network": peer_link,
                            "exchangeSubnetRoutes": bool(nc.get("exchangeSubnetRoutes", body.get("exchangeSubnetRoutes", True))),
                            "exportCustomRoutes": bool(nc.get("exportCustomRoutes", False)),
                            "importCustomRoutes": bool(nc.get("importCustomRoutes", False)),
                            "state": "INACTIVE"})
    _refresh_peerings(store, project)
    return _json(200, _operation(project, "global", None, "addPeering", _self_link("global", project, f"networks/{name}"), store))


def _remove_peering(store, project, name, body) -> ComputeResponse:
    rec = store.networks.get(_net_key(project, name))
    if not rec:
        return _not_found(f"The resource 'projects/{project}/global/networks/{name}' was not found")
    pname = str(body.get("name") or "")
    before = len(rec.get("peerings", []))
    rec["peerings"] = [p for p in rec.get("peerings", []) if p["name"] != pname]
    if len(rec["peerings"]) == before:
        return _not_found(f"Peering {pname} not found on network {name}")
    _refresh_peerings(store, project)
    return _json(200, _operation(project, "global", None, "removePeering", _self_link("global", project, f"networks/{name}"), store))


def _patch_network(store: ComputeStore, project: str, name: str, body: dict) -> ComputeResponse:
    rec = store.networks.get(_net_key(project, name))
    if not rec:
        return _not_found(f"The resource 'projects/{project}/global/networks/{name}' was not found")
    if "description" in body:
        rec["description"] = str(body["description"])
    if "mtu" in body:
        rec["mtu"] = int(body["mtu"])
    if "routingConfig" in body and body["routingConfig"].get("routingMode"):
        rec["routingMode"] = body["routingConfig"]["routingMode"]
    return _json(200, _operation(project, "global", None, "patch", _self_link("global", project, f"networks/{name}"), store))


# ── subnetworks ──────────────────────────────────────────────────────────────
def _sub_key(project, region, name):
    return f"{project}/{region}/{name}"


def _subnet_view(rec: dict) -> dict:
    project = rec["project"]
    out = {
        "kind": "compute#subnetwork", "id": rec["id"], "name": rec["name"],
        "description": rec.get("description", ""),
        "network": _self_link("global", project, f"networks/{rec['networkName']}"),
        "region": _self_link("regions", project, rec["region"]),
        "ipCidrRange": rec["ipCidrRange"],
        "gatewayAddress": rec["gatewayAddress"],
        "privateIpGoogleAccess": rec.get("privateIpGoogleAccess", False),
        "stackType": rec.get("stackType", "IPV4_ONLY"),
        "purpose": "PRIVATE",
        "logConfig": {"enable": rec.get("flowLogs", False)},
        "creationTimestamp": rec["creationTimestamp"],
        "selfLink": _self_link("regions", project, f"{rec['region']}/subnetworks/{rec['name']}"),
    }
    if rec.get("stackType") in ("IPV4_IPV6", "IPV6_ONLY"):
        out["ipv6CidrRange"] = rec.get("ipv6CidrRange", "")
        out["ipv6AccessType"] = "EXTERNAL"
    return out


def _resolve_network_name(project: str, ref: str) -> str:
    """A `network` field may be a bare name or a full/partial selfLink."""
    return str(ref or "").rstrip("/").rsplit("/", 1)[-1]


def _create_subnet(store: ComputeStore, project: str, region: str, body: dict, auto=False) -> dict | None:
    name = str(body.get("name", "")).strip()
    try:
        _check_name(name, "Subnet name")
    except _E:
        if auto:
            return None
        raise
    net_name = _resolve_network_name(project, body.get("network"))
    net = store.networks.get(_net_key(project, net_name))
    if not net:
        raise _E(400, "INVALID_ARGUMENT", f"Invalid value for field 'resource.network': network '{net_name}' not found")
    if _sub_key(project, region, name) in store.subnetworks:
        raise _E(409, "ALREADY_EXISTS", f"The resource 'projects/{project}/regions/{region}/subnetworks/{name}' already exists")
    cidr = str(body.get("ipCidrRange", "")).strip()
    try:
        net_ip = ipaddress.ip_network(cidr, strict=False)
        gateway = str(net_ip.network_address + 1)
    except ValueError:
        raise _E(400, "INVALID_ARGUMENT", f"Invalid IPv4 range: {cidr}")
    store.seq["ip"] += 1
    rec = {
        "id": str(20_000 + store.seq["ip"]), "project": project, "region": region, "name": name,
        "description": str(body.get("description", "")), "networkName": net_name, "ipCidrRange": cidr,
        "gatewayAddress": gateway, "privateIpGoogleAccess": bool(body.get("privateIpGoogleAccess", False)),
        "stackType": body.get("stackType", "IPV4_ONLY"), "ipv6CidrRange": body.get("ipv6CidrRange", ""),
        "flowLogs": bool(body.get("flowLogs") or (body.get("logConfig") or {}).get("enable", False)),
        "creationTimestamp": _ts(),
    }
    store.subnetworks[_sub_key(project, region, name)] = rec
    net.setdefault("_subnets", []).append({"region": region, "name": name})
    return rec


def _insert_subnet(store: ComputeStore, project: str, region: str, body: dict) -> ComputeResponse:
    try:
        rec = _create_subnet(store, project, region, body)
    except _E as e:
        return _err(e.status, e.gcp_status, e.message)
    return _json(200, _operation(project, "regional", region, "insert",
                                  _self_link("regions", project, f"{region}/subnetworks/{rec['name']}"), store))


def _list_subnets(store: ComputeStore, project: str, region: str) -> ComputeResponse:
    items = [_subnet_view(r) for k, r in sorted(store.subnetworks.items()) if k.startswith(f"{project}/{region}/")]
    out = {"kind": "compute#subnetworkList", "id": f"projects/{project}/regions/{region}/subnetworks"}
    if items:
        out["items"] = items
    return _json(200, out)


def _aggregated_subnets(store: ComputeStore, project: str) -> ComputeResponse:
    by_region: dict = {}
    for k, r in sorted(store.subnetworks.items()):
        if not k.startswith(f"{project}/"):
            continue
        scope = f"regions/{r['region']}"
        by_region.setdefault(scope, {"subnetworks": []})["subnetworks"].append(_subnet_view(r))
    out = {"kind": "compute#subnetworkAggregatedList", "id": f"projects/{project}/aggregated/subnetworks", "items": by_region}
    return _json(200, out)


def _get_subnet(store: ComputeStore, project: str, region: str, name: str) -> ComputeResponse:
    rec = store.subnetworks.get(_sub_key(project, region, name))
    if not rec:
        return _not_found(f"The resource 'projects/{project}/regions/{region}/subnetworks/{name}' was not found")
    return _json(200, _subnet_view(rec))


def _delete_subnet(store: ComputeStore, project: str, region: str, name: str) -> ComputeResponse:
    key = _sub_key(project, region, name)
    rec = store.subnetworks.get(key)
    if not rec:
        return _not_found(f"The resource 'projects/{project}/regions/{region}/subnetworks/{name}' was not found")
    del store.subnetworks[key]
    net = store.networks.get(_net_key(project, rec["networkName"]))
    if net:
        net["_subnets"] = [s for s in net.get("_subnets", []) if not (s["region"] == region and s["name"] == name)]
    return _json(200, _operation(project, "regional", region, "delete",
                                  _self_link("regions", project, f"{region}/subnetworks/{name}"), store))


# ── firewalls ────────────────────────────────────────────────────────────────
def _fw_key(project, name):
    return f"{project}/{name}"


def _firewall_view(rec: dict) -> dict:
    project = rec["project"]
    out = {
        "kind": "compute#firewall", "id": rec["id"], "name": rec["name"],
        "description": rec.get("description", ""),
        "network": _self_link("global", project, f"networks/{rec['networkName']}"),
        "priority": rec.get("priority", 1000),
        "direction": rec.get("direction", "INGRESS"),
        "disabled": rec.get("disabled", False),
        "logConfig": {"enable": rec.get("logEnable", False)},
        "creationTimestamp": rec["creationTimestamp"],
        "selfLink": _self_link("global", project, f"firewalls/{rec['name']}"),
    }
    if rec.get("sourceRanges"):
        out["sourceRanges"] = rec["sourceRanges"]
    if rec.get("destinationRanges"):
        out["destinationRanges"] = rec["destinationRanges"]
    if rec.get("targetTags"):
        out["targetTags"] = rec["targetTags"]
    if rec.get("sourceTags"):
        out["sourceTags"] = rec["sourceTags"]
    if rec.get("targetServiceAccounts"):
        out["targetServiceAccounts"] = rec["targetServiceAccounts"]
    if rec.get("sourceServiceAccounts"):
        out["sourceServiceAccounts"] = rec["sourceServiceAccounts"]
    if rec.get("allowed") is not None:
        out["allowed"] = rec["allowed"]
    if rec.get("denied") is not None:
        out["denied"] = rec["denied"]
    return out


def _insert_firewall(store: ComputeStore, project: str, body: dict) -> ComputeResponse:
    name = str(body.get("name", "")).strip()
    try:
        _check_name(name, "Firewall rule name")
    except _E as e:
        return _err(e.status, e.gcp_status, e.message)
    if _fw_key(project, name) in store.firewalls:
        return _err(409, "ALREADY_EXISTS", f"The resource 'projects/{project}/global/firewalls/{name}' already exists")
    net_name = _resolve_network_name(project, body.get("network") or "default")
    if _net_key(project, net_name) not in store.networks:
        return _err(400, "INVALID_ARGUMENT", f"Invalid value for field 'resource.network': network '{net_name}' not found")
    if "allowed" not in body and "denied" not in body:
        return _err(400, "INVALID_ARGUMENT", "Firewall rule must specify 'allowed' or 'denied'.")
    if body.get("targetServiceAccounts") and body.get("targetTags"):
        return _err(400, "INVALID_ARGUMENT", "targetTags and targetServiceAccounts cannot be specified together.")
    if body.get("sourceServiceAccounts") and body.get("sourceTags"):
        return _err(400, "INVALID_ARGUMENT", "sourceTags and sourceServiceAccounts cannot be specified together.")
    store.seq["ip"] += 1
    rec = {
        "id": str(30_000 + store.seq["ip"]), "project": project, "name": name,
        "description": str(body.get("description", "")), "networkName": net_name,
        "priority": int(body.get("priority", 1000)), "direction": body.get("direction", "INGRESS"),
        "disabled": bool(body.get("disabled", False)),
        "logEnable": bool((body.get("logConfig") or {}).get("enable", False)),
        "sourceRanges": body.get("sourceRanges") or [],
        "destinationRanges": body.get("destinationRanges") or [],
        "targetTags": body.get("targetTags") or [],
        "sourceTags": body.get("sourceTags") or [],
        "targetServiceAccounts": body.get("targetServiceAccounts") or [],
        "sourceServiceAccounts": body.get("sourceServiceAccounts") or [],
        "allowed": body.get("allowed"), "denied": body.get("denied"),
        "creationTimestamp": _ts(),
    }
    store.firewalls[_fw_key(project, name)] = rec
    return _json(200, _operation(project, "global", None, "insert", _self_link("global", project, f"firewalls/{name}"), store))


def _list_firewalls(store: ComputeStore, project: str) -> ComputeResponse:
    items = [_firewall_view(r) for k, r in sorted(store.firewalls.items()) if k.startswith(f"{project}/")]
    out = {"kind": "compute#firewallList", "id": f"projects/{project}/global/firewalls"}
    if items:
        out["items"] = items
    return _json(200, out)


def _get_firewall(store: ComputeStore, project: str, name: str) -> ComputeResponse:
    rec = store.firewalls.get(_fw_key(project, name))
    if not rec:
        return _not_found(f"The resource 'projects/{project}/global/firewalls/{name}' was not found")
    return _json(200, _firewall_view(rec))


def _delete_firewall(store: ComputeStore, project: str, name: str) -> ComputeResponse:
    key = _fw_key(project, name)
    if key not in store.firewalls:
        return _not_found(f"The resource 'projects/{project}/global/firewalls/{name}' was not found")
    del store.firewalls[key]
    return _json(200, _operation(project, "global", None, "delete", _self_link("global", project, f"firewalls/{name}"), store))


def _patch_firewall(store: ComputeStore, project: str, name: str, body: dict) -> ComputeResponse:
    rec = store.firewalls.get(_fw_key(project, name))
    if not rec:
        return _not_found(f"The resource 'projects/{project}/global/firewalls/{name}' was not found")
    if "logConfig" in body:
        rec["logEnable"] = bool(body["logConfig"].get("enable", rec["logEnable"]))
    if "disabled" in body:
        rec["disabled"] = bool(body["disabled"])
    if "priority" in body:
        rec["priority"] = int(body["priority"])
    for fld in ("sourceRanges", "destinationRanges", "targetTags", "sourceTags", "targetServiceAccounts",
                "sourceServiceAccounts", "allowed", "denied"):
        if fld in body:
            rec[fld] = body[fld] or ([] if fld not in ("allowed", "denied") else None)
    return _json(200, _operation(project, "global", None, "patch", _self_link("global", project, f"firewalls/{name}"), store))


# ── routes ───────────────────────────────────────────────────────────────────
def _route_key(project, name):
    return f"{project}/{name}"


def _route_view(rec: dict) -> dict:
    project = rec["project"]
    out = {
        "kind": "compute#route", "id": rec["id"], "name": rec["name"],
        "description": rec.get("description", ""),
        "network": _self_link("global", project, f"networks/{rec['networkName']}"),
        "destRange": rec["destRange"], "priority": rec.get("priority", 1000),
        "creationTimestamp": rec["creationTimestamp"],
        "selfLink": _self_link("global", project, f"routes/{rec['name']}"),
    }
    if rec.get("tags"):
        out["tags"] = rec["tags"]
    nh = rec.get("nextHop") or {}
    out.update(nh)
    return out


def _next_hop_fields(project: str, body: dict) -> dict:
    if body.get("nextHopGateway"):
        return {"nextHopGateway": _self_link("global", project, "gateways/default-internet-gateway")}
    if body.get("nextHopIp"):
        return {"nextHopIp": body["nextHopIp"]}
    if body.get("nextHopInstance"):
        return {"nextHopInstance": body["nextHopInstance"]}
    if body.get("nextHopVpnTunnel"):
        return {"nextHopVpnTunnel": body["nextHopVpnTunnel"]}
    if body.get("nextHopIlb"):
        return {"nextHopIlb": body["nextHopIlb"]}
    return {"nextHopGateway": _self_link("global", project, "gateways/default-internet-gateway")}


def _insert_route(store: ComputeStore, project: str, body: dict) -> ComputeResponse:
    name = str(body.get("name", "")).strip()
    try:
        _check_name(name, "Route name")
    except _E as e:
        return _err(e.status, e.gcp_status, e.message)
    if _route_key(project, name) in store.routes:
        return _err(409, "ALREADY_EXISTS", f"The resource 'projects/{project}/global/routes/{name}' already exists")
    net_name = _resolve_network_name(project, body.get("network") or "default")
    if _net_key(project, net_name) not in store.networks:
        return _err(400, "INVALID_ARGUMENT", f"Invalid value for field 'resource.network': network '{net_name}' not found")
    dest = str(body.get("destRange", "")).strip()
    try:
        ipaddress.ip_network(dest, strict=False)
    except ValueError:
        return _err(400, "INVALID_ARGUMENT", f"Invalid destination range: {dest}")
    store.seq["ip"] += 1
    rec = {
        "id": str(40_000 + store.seq["ip"]), "project": project, "name": name,
        "description": str(body.get("description", "")), "networkName": net_name, "destRange": dest,
        "priority": int(body.get("priority", 1000)), "tags": body.get("tags") or [],
        "nextHop": _next_hop_fields(project, body), "creationTimestamp": _ts(),
    }
    store.routes[_route_key(project, name)] = rec
    return _json(200, _operation(project, "global", None, "insert", _self_link("global", project, f"routes/{name}"), store))


def _list_routes(store: ComputeStore, project: str) -> ComputeResponse:
    items = [_route_view(r) for k, r in sorted(store.routes.items()) if k.startswith(f"{project}/")]
    out = {"kind": "compute#routeList", "id": f"projects/{project}/global/routes"}
    if items:
        out["items"] = items
    return _json(200, out)


def _get_route(store: ComputeStore, project: str, name: str) -> ComputeResponse:
    rec = store.routes.get(_route_key(project, name))
    if not rec:
        return _not_found(f"The resource 'projects/{project}/global/routes/{name}' was not found")
    return _json(200, _route_view(rec))


def _delete_route(store: ComputeStore, project: str, name: str) -> ComputeResponse:
    key = _route_key(project, name)
    if key not in store.routes:
        return _not_found(f"The resource 'projects/{project}/global/routes/{name}' was not found")
    if store.routes[key].get("_system"):
        net = store.networks.get(_net_key(project, store.routes[key]["networkName"]))
        if net is not None:
            net["_hasDefaultRoute"] = False
    del store.routes[key]
    return _json(200, _operation(project, "global", None, "delete", _self_link("global", project, f"routes/{name}"), store))


# ── addresses (regional + global) ────────────────────────────────────────────
def _addr_key(project, scope, name):
    return f"{project}/{scope}/{name}"


def _gen_ip(store: ComputeStore, internal: bool) -> str:
    store.seq["ip"] += 1
    n = store.seq["ip"]
    return f"10.200.{(n // 256) % 256}.{n % 256}" if internal else f"34.120.{(n // 256) % 256}.{n % 256}"


def _address_view(rec: dict) -> dict:
    project, scope = rec["project"], rec["scope"]
    out = {
        "kind": "compute#address", "id": rec["id"], "name": rec["name"],
        "description": rec.get("description", ""), "address": rec["address"],
        "addressType": rec.get("addressType", "EXTERNAL"), "status": rec.get("status", "RESERVED"),
        "networkTier": rec.get("networkTier", DEFAULT_NETWORK_TIER),
        "ipVersion": rec.get("ipVersion", "IPV4"),
        "creationTimestamp": rec["creationTimestamp"],
        "selfLink": _self_link("global" if scope == "global" else "regions", project,
                                f"addresses/{rec['name']}" if scope == "global" else f"{scope}/addresses/{rec['name']}"),
    }
    if scope != "global":
        out["region"] = _self_link("regions", project, scope)
    if rec.get("users"):
        out["users"] = rec["users"]
        out["status"] = "IN_USE"
    return out


def _insert_address(store: ComputeStore, project: str, scope: str, body: dict) -> ComputeResponse:
    name = str(body.get("name", "")).strip()
    try:
        _check_name(name, "Address name")
    except _E as e:
        return _err(e.status, e.gcp_status, e.message)
    if _addr_key(project, scope, name) in store.addresses:
        return _err(409, "ALREADY_EXISTS", f"The resource '{name}' already exists")
    addr_type = body.get("addressType", "EXTERNAL")
    ip_version = body.get("ipVersion", "IPV4")
    store.seq["ip"] += 1
    rec = {
        "id": str(50_000 + store.seq["ip"]), "project": project, "scope": scope, "name": name,
        "description": str(body.get("description", "")),
        "address": str(body.get("address") or _gen_ip(store, addr_type == "INTERNAL")),
        "addressType": addr_type, "ipVersion": ip_version,
        "networkTier": body.get("networkTier", DEFAULT_NETWORK_TIER),
        "status": "RESERVED", "users": [], "creationTimestamp": _ts(),
    }
    store.addresses[_addr_key(project, scope, name)] = rec
    scope_kind = "global" if scope == "global" else "regional"
    tail = f"addresses/{name}" if scope == "global" else f"{scope}/addresses/{name}"
    return _json(200, _operation(project, scope_kind, None if scope == "global" else scope, "insert",
                                  _self_link("global" if scope == "global" else "regions", project, tail), store))


def _list_addresses(store: ComputeStore, project: str, scope: str) -> ComputeResponse:
    items = [_address_view(r) for k, r in sorted(store.addresses.items()) if k.startswith(f"{project}/{scope}/")]
    out = {"kind": "compute#addressList", "id": f"projects/{project}/{'global' if scope == 'global' else 'regions/' + scope}/addresses"}
    if items:
        out["items"] = items
    return _json(200, out)


def _aggregated_addresses(store: ComputeStore, project: str) -> ComputeResponse:
    by_scope: dict = {}
    for k, r in sorted(store.addresses.items()):
        if not k.startswith(f"{project}/"):
            continue
        scope_name = "global" if r["scope"] == "global" else f"regions/{r['scope']}"
        by_scope.setdefault(scope_name, {"addresses": []})["addresses"].append(_address_view(r))
    out = {"kind": "compute#addressAggregatedList", "id": f"projects/{project}/aggregated/addresses", "items": by_scope}
    return _json(200, out)


def _get_address(store: ComputeStore, project: str, scope: str, name: str) -> ComputeResponse:
    rec = store.addresses.get(_addr_key(project, scope, name))
    if not rec:
        return _not_found(f"The resource '{name}' was not found")
    return _json(200, _address_view(rec))


def _delete_address(store: ComputeStore, project: str, scope: str, name: str) -> ComputeResponse:
    key = _addr_key(project, scope, name)
    rec = store.addresses.get(key)
    if not rec:
        return _not_found(f"The resource '{name}' was not found")
    if rec.get("users"):
        return _err(400, "RESOURCE_IN_USE_BY_ANOTHER_RESOURCE", f"The address resource '{name}' is in use")
    del store.addresses[key]
    scope_kind = "global" if scope == "global" else "regional"
    tail = f"addresses/{name}" if scope == "global" else f"{scope}/addresses/{name}"
    return _json(200, _operation(project, scope_kind, None if scope == "global" else scope, "delete",
                                  _self_link("global" if scope == "global" else "regions", project, tail), store))


# ── operations (polled by SDKs; we complete synchronously) ──────────────────
def _get_operation(project: str, scope_kind: str, name: str) -> ComputeResponse:
    return _json(200, {"kind": "compute#operation", "id": "0", "name": name, "status": "DONE", "progress": 100,
                        "selfLink": _self_link(scope_kind, project, f"operations/{name}")})


# ── Cloud Router (+ Cloud NAT) ───────────────────────────────────────────────
def _router_key(project, region, name):
    return f"{project}/{region}/{name}"


def _router_view(rec: dict) -> dict:
    project, region = rec["project"], rec["region"]
    return {"kind": "compute#router", "id": rec["id"], "name": rec["name"], "description": rec.get("description", ""),
            "network": _self_link("global", project, f"networks/{rec['networkName']}"),
            "region": _self_link("regions", project, region), "bgp": rec.get("bgp", {"asn": 64512}),
            "nats": [dict(n) for n in rec.get("nats", [])], "creationTimestamp": rec["creationTimestamp"],
            "selfLink": _self_link("regions", project, f"{region}/routers/{rec['name']}")}


def _norm_nats(project, region, nats) -> list:
    out = []
    for n in nats or []:
        mode = n.get("sourceSubnetworkIpRangesToNat") or "ALL_SUBNETWORKS_ALL_IP_RANGES"
        subs = [{"name": s["name"] if str(s.get("name", "")).startswith("http") else
                 _self_link("regions", project, f"{region}/subnetworks/{_tail(s.get('name'))}"),
                 "sourceIpRangesToNat": s.get("sourceIpRangesToNat") or ["ALL_IP_RANGES"]}
                for s in n.get("subnetworks") or []]
        out.append({"name": n.get("name", "nat"), "natIpAllocateOption": n.get("natIpAllocateOption") or "AUTO_ONLY",
                    "sourceSubnetworkIpRangesToNat": mode, "subnetworks": subs,
                    "logConfig": n.get("logConfig") or {"enable": False, "filter": "ALL"},
                    "enableEndpointIndependentMapping": bool(n.get("enableEndpointIndependentMapping", False))})
    return out


def _insert_router(store, project, region, body) -> ComputeResponse:
    name = str(body.get("name", "")).strip()
    try:
        _check_name(name, "Router name")
    except _E as e:
        return _err(e.status, e.gcp_status, e.message)
    routers = _bucket(store, "routers")
    if _router_key(project, region, name) in routers:
        return _err(409, "ALREADY_EXISTS", f"The resource 'projects/{project}/regions/{region}/routers/{name}' already exists")
    net = _tail(body.get("network"))
    if _net_key(project, net) not in store.networks:
        return _err(400, "INVALID_ARGUMENT", f"Invalid value for field 'resource.network': network '{net}' not found")
    store.seq["ip"] += 1
    routers[_router_key(project, region, name)] = {
        "id": str(50_000 + store.seq["ip"]), "project": project, "region": region, "name": name,
        "description": str(body.get("description", "")), "networkName": net, "bgp": body.get("bgp") or {"asn": 64512},
        "nats": _norm_nats(project, region, body.get("nats")), "creationTimestamp": _ts()}
    return _json(200, _operation(project, "regional", region, "insert", _self_link("regions", project, f"{region}/routers/{name}"), store))


def _router_crud(store, method, project, region, name, body) -> ComputeResponse:
    routers = _bucket(store, "routers")
    key = _router_key(project, region, name)
    rec = routers.get(key)
    if rec is None:
        return _not_found(f"The resource 'projects/{project}/regions/{region}/routers/{name}' was not found")
    link = _self_link("regions", project, f"{region}/routers/{name}")
    if method == "GET":
        return _json(200, _router_view(rec))
    if method == "DELETE":
        del routers[key]
        return _json(200, _operation(project, "regional", region, "delete", link, store))
    if method in ("PATCH", "PUT"):
        if "nats" in body:
            rec["nats"] = _norm_nats(project, region, body["nats"])
        if "bgp" in body:
            rec["bgp"] = body["bgp"]
        if "description" in body:
            rec["description"] = str(body["description"])
        return _json(200, _operation(project, "regional", region, "patch", link, store))
    return _err(405, "METHOD_NOT_ALLOWED", "Method not allowed")


# ── Network Intelligence Center: Connectivity Tests (networkmanagement v1) — answered by core/netsim ──
_DROP_CAUSE = {"INGRESS_DENIED": "FIREWALL_RULE", "EGRESS_DENIED": "FIREWALL_RULE", "NO_ROUTE": "NO_ROUTE",
               "BLACKHOLE_ROUTE": "ROUTE_BLACKHOLE", "PRIVATE_DEST_VIA_GATEWAY": "PRIVATE_TRAFFIC_TO_INTERNET",
               "NO_PUBLIC_IP": "NO_EXTERNAL_ADDRESS", "NO_DESTINATION": "UNKNOWN_INTERNAL_ADDRESS",
               "NOT_PUBLIC": "UNKNOWN_EXTERNAL_ADDRESS", "SOURCE_DEST_CHECK": "INSTANCE_IP_FORWARDING_DISABLED"}


def _ct_endpoint(topo, ep: dict, project: str):
    inst = ep.get("instance") or ""
    if inst:
        full = inst.split("compute/v1/")[-1].lstrip("/")
        if not full.startswith("projects/"):
            full = f"projects/{project}/{full}"
        iid = full + "/nic0"
        if iid in topo.interfaces:
            return iid, topo.interfaces[iid].ip
        raise _E(400, "INVALID_ARGUMENT", f"Instance {inst} not found or not running")
    ip = str(ep.get("ipAddress") or "")
    if not ip:
        raise _E(400, "INVALID_ARGUMENT", "endpoint needs ipAddress or instance")
    hit = topo.iface_by_ip(ip)
    return (hit.id if hit is not None and hit.ip == ip else ip), ip


def _ct_steps(v, project, src_ref, topo) -> list:
    steps = []
    s_iface = topo.interfaces.get(src_ref) if isinstance(src_ref, str) else None
    if s_iface is not None:
        steps.append({"description": f"Initial state: packet originating from a Compute Engine instance.",
                      "state": "START_FROM_INSTANCE", "projectId": project,
                      "instance": {"displayName": s_iface.instance, "uri": s_iface.id.rsplit("/nic", 1)[0],
                                   "internalIp": s_iface.ip, "externalIp": s_iface.public_ip or "",
                                   "networkTags": list(s_iface.tags)}})
    else:
        steps.append({"description": "Initial state: packet originating from the internet.",
                      "state": "START_FROM_INTERNET", "projectId": project})
    for h in v.hops:
        if h.component == "firewall":
            name = h.detail.split(" ")[0] if h.detail else ""
            steps.append({"description": f"Config checking state: verify {h.direction.upper()} firewall rule.",
                          "state": "APPLY_INGRESS_FIREWALL_RULE" if h.direction == "ingress" else "APPLY_EGRESS_FIREWALL_RULE",
                          "causesDrop": h.decision == "deny", "projectId": project,
                          "firewall": {"displayName": name, "direction": h.direction.upper(),
                                       "action": "ALLOW" if h.decision == "allow" else "DENY",
                                       "firewallRuleType": "IMPLIED_VPC_FIREWALL_RULE" if name.startswith("implied-") else "VPC_FIREWALL_RULE"}})
        elif h.component == "route-table":
            steps.append({"description": "Config checking state: verify route.", "state": "APPLY_ROUTE",
                          "causesDrop": h.decision == "deny", "projectId": project,
                          "route": {"displayName": h.detail, "routeType": "SUBNET" if " via local" in h.detail else "STATIC"}})
        elif h.component in ("internet-gateway", "nat-gateway"):
            steps.append({"description": h.detail, "state": "NAT" if "NAT" in h.detail else "FORWARD",
                          "causesDrop": h.decision == "deny", "projectId": project,
                          **({"forward": {"target": "INTERNET"}} if "NAT" not in h.detail else
                             {"nat": {"type": "CLOUD_NAT", "natGatewayName": h.detail}})})
        elif h.component == "peering":
            steps.append({"description": h.detail, "state": "FORWARD", "causesDrop": h.decision == "deny",
                          "projectId": project, "forward": {"target": "PEERING_VPC"}})
        elif h.component == "destination":
            steps.append({"description": "Final state: packet delivered.", "state": "DELIVER", "projectId": project,
                          "deliver": {"target": "INTERNET" if h.detail == "internet host" else "INSTANCE",
                                      "resourceUri": h.id}})
    if not v.reachable:
        steps.append({"description": f"Final state: packet dropped — {v.reason}", "state": "DROP", "causesDrop": True,
                      "projectId": project, "drop": {"cause": _DROP_CAUSE.get(v.code, v.code), "resourceUri": v.blocked_by}})
    return steps


def _run_connectivity_test(store, vm_store, project, rec) -> None:
    try:
        from core.netsim import evaluate as ev, from_gcp as fg
    except ImportError:                                  # pragma: no cover - flat layout
        from netsim import evaluate as ev, from_gcp as fg   # type: ignore
    topo = fg.from_gcp(store, vm_store, project)
    src_ref, src_ip = _ct_endpoint(topo, rec["source"], project)
    dst_ref, dst_ip = _ct_endpoint(topo, rec["destination"], project)
    proto = str(rec.get("protocol") or "TCP").lower()
    port = rec["destination"].get("port")
    v = ev.reach(topo, src_ref, dst_ref, proto, int(port) if port else None)
    now = _ts()
    rec["reachabilityDetails"] = {
        "result": "REACHABLE" if v.reachable else "UNREACHABLE", "verifyTime": now,
        "traces": [{"endpointInfo": {"sourceIp": src_ip, "destinationIp": dst_ip, "protocol": proto.upper(),
                                      "destinationPort": int(port) if port else 0},
                    "steps": _ct_steps(v, project, src_ref, topo)}]}
    rec["updateTime"] = now


def _ct_view(rec: dict) -> dict:
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def _lro(project: str, response: dict) -> dict:
    return {"name": f"projects/{project}/locations/global/operations/operation-{uuid.uuid4().hex[:12]}", "done": True,
            "metadata": {"@type": "type.googleapis.com/google.cloud.networkmanagement.v1.OperationMetadata"},
            "response": {"@type": "type.googleapis.com/google.cloud.networkmanagement.v1.ConnectivityTest", **response}}


def _connectivity_tests(store, vm_store, method, project, segs, query, payload) -> ComputeResponse:
    tests = _bucket(store, "connectivity_tests")
    rest = segs[5:]                                      # after projects/p/locations/global/connectivityTests
    if not rest:
        if method == "GET":
            items = [_ct_view(r) for k, r in sorted(tests.items()) if k.startswith(f"{project}/")]
            return _json(200, {"resources": items} if items else {})
        if method == "POST":
            tid = str((query or {}).get("testId") or payload.get("name", "").split("/")[-1] or "").strip()
            try:
                _check_name(tid, "Connectivity test id")
            except _E as e:
                return _err(e.status, e.gcp_status, e.message)
            if f"{project}/{tid}" in tests:
                return _err(409, "ALREADY_EXISTS", f"Connectivity test {tid} already exists")
            rec = {"name": f"projects/{project}/locations/global/connectivityTests/{tid}",
                   "description": payload.get("description", ""), "source": payload.get("source") or {},
                   "destination": payload.get("destination") or {}, "protocol": payload.get("protocol") or "TCP",
                   "relatedProjects": payload.get("relatedProjects") or [], "displayName": tid,
                   "labels": payload.get("labels") or {}, "createTime": _ts(), "roundTrip": bool(payload.get("roundTrip"))}
            _run_connectivity_test(store, vm_store, project, rec)
            tests[f"{project}/{tid}"] = rec
            return _json(200, _lro(project, _ct_view(rec)))
        return _err(405, "METHOD_NOT_ALLOWED", "Method not allowed")
    tid, verb = rest[0], ""
    if ":" in tid:
        tid, verb = tid.split(":", 1)
    rec = tests.get(f"{project}/{tid}")
    if rec is None:
        return _not_found(f"Connectivity test projects/{project}/locations/global/connectivityTests/{tid} not found")
    if verb == "rerun" and method == "POST":
        _run_connectivity_test(store, vm_store, project, rec)
        return _json(200, _lro(project, _ct_view(rec)))
    if method == "GET":
        return _json(200, _ct_view(rec))
    if method == "DELETE":
        del tests[f"{project}/{tid}"]
        return _json(200, {"name": f"projects/{project}/locations/global/operations/operation-{uuid.uuid4().hex[:12]}",
                           "done": True, "response": {"@type": "type.googleapis.com/google.protobuf.Empty"}})
    if method == "PATCH":
        for fld in ("source", "destination", "protocol", "description", "labels"):
            if fld in payload:
                rec[fld] = payload[fld]
        _run_connectivity_test(store, vm_store, project, rec)
        return _json(200, _lro(project, _ct_view(rec)))
    return _err(405, "METHOD_NOT_ALLOWED", "Method not allowed")


# ── native-wire dispatcher (REST path + method → operation) ─────────────────
def dispatch(store: ComputeStore, method: str, path: str,
             query: dict | None = None, headers: dict | None = None,
             body: bytes = b"", vm_store=None) -> ComputeResponse:
    """`vm_store` (the gcp_compute_instances_core store) lets Connectivity Tests see the VMs."""
    r = _dispatch(store, method.upper(), path, query, headers, body, vm_store)
    if method.upper() != "GET" and r.status < 300 and hasattr(store, "persist"):
        store.persist()          # durable substrates save here (the in-memory store has no persist)
    return r


def _dispatch(store: ComputeStore, method: str, path: str,
              query: dict | None = None, headers: dict | None = None,
              body: bytes = b"", vm_store=None) -> ComputeResponse:
    method = method.upper()
    p = path.split("?", 1)[0]
    for pre in ("/compute/v1", "/compute/beta", "/v1"):
        if p.startswith(pre):
            p = p[len(pre):]
            break
    segs = [s for s in p.strip("/").split("/") if s != ""]

    if len(segs) < 3 or segs[0] != "projects":
        return _not_found(f"Unknown path: {path}")
    project = segs[1]
    scope = segs[2]   # "global" | "regions" | "zones" | "aggregated"

    try:
        payload = json.loads(body.decode("utf-8")) if body else {}
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    try:
        # ── locations/global/connectivityTests (networkmanagement v1) ─────
        if scope == "locations" and len(segs) >= 5 and segs[4].split(":")[0] == "connectivityTests":
            return _connectivity_tests(store, vm_store, method, project, segs, query, payload)
        # ── global/* ──────────────────────────────────────────────────────
        if scope == "global":
            if len(segs) < 4:
                return _not_found(f"Unknown path: {path}")
            kind = segs[3]
            if kind == "networks":
                if len(segs) == 4:
                    if method == "POST":
                        return _insert_network(store, project, payload)
                    if method == "GET":
                        return _list_networks(store, project)
                elif len(segs) == 5 and ":" not in segs[4]:
                    name = segs[4]
                    if method == "GET":
                        return _get_network(store, project, name)
                    if method == "DELETE":
                        return _delete_network(store, project, name)
                    if method in ("PATCH", "PUT"):
                        return _patch_network(store, project, name, payload)
                if len(segs) == 6 and method == "POST" and segs[5] in ("addPeering", "removePeering"):
                    return (_add_peering if segs[5] == "addPeering" else _remove_peering)(store, project, segs[4], payload)
                if len(segs) == 5 and ":" in segs[4] and method == "POST":
                    nname, verb = segs[4].split(":", 1)
                    if verb in ("addPeering", "removePeering"):
                        return (_add_peering if verb == "addPeering" else _remove_peering)(store, project, nname, payload)
            elif kind == "firewalls":
                if len(segs) == 4:
                    if method == "POST":
                        return _insert_firewall(store, project, payload)
                    if method == "GET":
                        return _list_firewalls(store, project)
                elif len(segs) == 5:
                    name = segs[4]
                    if method == "GET":
                        return _get_firewall(store, project, name)
                    if method == "DELETE":
                        return _delete_firewall(store, project, name)
                    if method in ("PATCH", "PUT"):
                        return _patch_firewall(store, project, name, payload)
            elif kind == "routes":
                if len(segs) == 4:
                    if method == "POST":
                        return _insert_route(store, project, payload)
                    if method == "GET":
                        return _list_routes(store, project)
                elif len(segs) == 5:
                    name = segs[4]
                    if method == "GET":
                        return _get_route(store, project, name)
                    if method == "DELETE":
                        return _delete_route(store, project, name)
            elif kind == "addresses":
                if len(segs) == 4:
                    if method == "POST":
                        return _insert_address(store, project, "global", payload)
                    if method == "GET":
                        return _list_addresses(store, project, "global")
                elif len(segs) == 5:
                    name = segs[4]
                    if method == "GET":
                        return _get_address(store, project, "global", name)
                    if method == "DELETE":
                        return _delete_address(store, project, "global", name)
            elif kind == "operations" and len(segs) == 5:
                return _get_operation(project, "global", segs[4])
            return _not_found(f"Unknown path: {path}")

        # ── regions/{region}/* ───────────────────────────────────────────
        if scope == "regions":
            if len(segs) < 5:
                return _not_found(f"Unknown path: {path}")
            region, kind = segs[3], segs[4]
            if kind == "subnetworks":
                if len(segs) == 5:
                    if method == "POST":
                        return _insert_subnet(store, project, region, payload)
                    if method == "GET":
                        return _list_subnets(store, project, region)
                elif len(segs) == 6:
                    name = segs[5]
                    if method == "GET":
                        return _get_subnet(store, project, region, name)
                    if method == "DELETE":
                        return _delete_subnet(store, project, region, name)
            elif kind == "addresses":
                if len(segs) == 5:
                    if method == "POST":
                        return _insert_address(store, project, region, payload)
                    if method == "GET":
                        return _list_addresses(store, project, region)
                elif len(segs) == 6:
                    name = segs[5]
                    if method == "GET":
                        return _get_address(store, project, region, name)
                    if method == "DELETE":
                        return _delete_address(store, project, region, name)
            elif kind == "routers":
                if len(segs) == 5:
                    if method == "POST":
                        return _insert_router(store, project, region, payload)
                    if method == "GET":
                        items = [_router_view(r) for k, r in sorted(_bucket(store, "routers").items())
                                 if k.startswith(f"{project}/{region}/")]
                        return _json(200, {"kind": "compute#routerList", **({"items": items} if items else {})})
                elif len(segs) == 6:
                    return _router_crud(store, method, project, region, segs[5], payload)
            elif kind == "operations" and len(segs) == 6:
                return _get_operation(project, "regions/" + region, segs[5])
            return _not_found(f"Unknown path: {path}")

        # ── aggregated/* (the console's "all regions" tabs) ─────────────────
        if scope == "aggregated" and len(segs) == 4:
            if segs[3] == "subnetworks" and method == "GET":
                return _aggregated_subnets(store, project)
            if segs[3] == "addresses" and method == "GET":
                return _aggregated_addresses(store, project)
            if segs[3] == "routers" and method == "GET":
                by_region = {}
                for k, r in sorted(_bucket(store, "routers").items()):
                    if k.startswith(f"{project}/"):
                        by_region.setdefault(f"regions/{r['region']}", {"routers": []})["routers"].append(_router_view(r))
                return _json(200, {"kind": "compute#routerAggregatedList", "items": by_region})
            return _not_found(f"Unknown path: {path}")

        return _not_found(f"Unknown path: {path}")
    except _E as e:
        return _err(e.status, e.gcp_status, e.message)
