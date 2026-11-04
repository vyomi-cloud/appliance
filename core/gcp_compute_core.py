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
        self.internal_ranges: dict = {}   # "project/location/name" -> networkconnectivity Internal Range
        self.vpc_connectors: dict = {}    # "project/region/name" -> vpcaccess Serverless VPC Access connector
        self.psc_connections: dict = {}   # "project/network" -> servicenetworking Connection (Private Service Connection)
        self.xpn: dict = {}               # project -> {"host": bool, "service_projects": [project,...]}
        self.firewall_policies: dict = {}  # "project/region/name" -> regional network firewall policy (+rules/associations)
        self.packet_mirrorings: dict = {}  # "project/region/name" -> Packet Mirroring policy
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
    if rec.get("purpose"):
        out["purpose"] = rec["purpose"]
    if rec.get("network"):
        out["network"] = _self_link("global", project, f"networks/{rec['network']}")
    if rec.get("prefixLength") is not None:
        out["prefixLength"] = rec["prefixLength"]
    return out


def _addr_space_used(store: ComputeStore, project: str, network: str) -> list:
    """Every CIDR already claimed on `network`: subnets + other VPC_PEERING reservations —
    what a new Private Service Connection range or internal range must not overlap."""
    out = []
    for s in store.subnetworks.values():
        if s["project"] == project and s["networkName"] == network:
            out.append(s["ipCidrRange"])
    for a in store.addresses.values():
        if a["project"] == project and a.get("purpose") == "VPC_PEERING" and a.get("network") == network:
            out.append(f"{a['address']}/{a.get('prefixLength', 32)}")
    for r in _bucket(store, "internal_ranges").values():
        if r["project"] == project and r["network"] == network:
            out.append(r["ipCidrRange"])
    return out


def _cidr_overlaps_any(cidr: str, others: list) -> bool:
    try:
        net = ipaddress.ip_network(cidr, strict=False)
    except ValueError:
        return False
    for o in others:
        try:
            if net.overlaps(ipaddress.ip_network(o, strict=False)):
                return True
        except ValueError:
            continue
    return False


def _allocate_cidr(target_ranges: list, prefix_len: int, used: list) -> str | None:
    for t in target_ranges:
        try:
            base = ipaddress.ip_network(t, strict=False)
        except ValueError:
            continue
        if prefix_len < base.prefixlen:
            continue
        for cand in base.subnets(new_prefix=prefix_len):
            c = str(cand)
            if not _cidr_overlaps_any(c, used):
                return c
    return None


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
    purpose = body.get("purpose")
    net_name = None
    address = body.get("address")
    if purpose == "VPC_PEERING":
        # Private Service Connection: a reserved internal block for Google-managed services,
        # real-allocated so it can't collide with this network's own subnets or other reservations.
        net_name = _resolve_network_name(project, body.get("network"))
        if _net_key(project, net_name) not in store.networks:
            return _err(400, "INVALID_ARGUMENT", f"Invalid value for field 'resource.network': network '{net_name}' not found")
        used = _addr_space_used(store, project, net_name)
        prefix_len = int(body.get("prefixLength") or 16)
        if address:
            cidr = f"{address}/{prefix_len}"
            if _cidr_overlaps_any(cidr, used):
                return _err(400, "INVALID_ARGUMENT", f"Range {cidr} overlaps an existing subnet or reserved range on network {net_name}")
        else:
            cidr = _allocate_cidr(["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"], prefix_len, used)
            if not cidr:
                return _err(400, "RESOURCE_EXHAUSTED", "No free internal range of the requested size")
            address = str(ipaddress.ip_network(cidr, strict=False).network_address)
    store.seq["ip"] += 1
    rec = {
        "id": str(50_000 + store.seq["ip"]), "project": project, "scope": scope, "name": name,
        "description": str(body.get("description", "")),
        "address": str(address or _gen_ip(store, addr_type == "INTERNAL")),
        "addressType": addr_type, "ipVersion": ip_version,
        "networkTier": body.get("networkTier", DEFAULT_NETWORK_TIER),
        "status": "RESERVED", "users": [], "creationTimestamp": _ts(),
    }
    if purpose:
        rec["purpose"] = purpose
    if net_name:
        rec["network"] = net_name
        rec["prefixLength"] = int(body.get("prefixLength") or 16)
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


# ── Internal ranges (networkconnectivity.googleapis.com v1 internalRanges) ──────────────────
def _ir_key(project, location, name):
    return f"{project}/{location}/{name}"


def _ir_view(rec: dict) -> dict:
    project, location = rec["project"], rec["location"]
    return {
        "name": f"projects/{project}/locations/{location}/internalRanges/{rec['name']}",
        "description": rec.get("description", ""),
        "ipCidrRange": rec["ipCidrRange"],
        "network": _self_link("global", project, f"networks/{rec['network']}"),
        "usage": rec.get("usage", "FOR_VPC"),
        "peering": rec.get("peering", "FOR_SELF"),
        "prefixLength": ipaddress.ip_network(rec["ipCidrRange"], strict=False).prefixlen,
        "targetCidrRange": rec.get("targetCidrRange") or [],
        "overlaps": rec.get("overlaps") or [],
        "createTime": rec["createTime"], "updateTime": rec["createTime"],
    }


def _nc_lro(project: str, type_name: str, response: dict) -> dict:
    """google.longrunning.Operation, completed synchronously (networkconnectivity / vpcaccess /
    servicenetworking all use LRO-shaped create/delete — unlike Compute Engine's own Operation)."""
    return {"name": f"projects/{project}/locations/global/operations/operation-{uuid.uuid4().hex[:12]}",
            "done": True, "metadata": {}, "response": {"@type": f"type.googleapis.com/{type_name}", **response}}


def _internal_ranges(store: ComputeStore, method: str, project: str, location: str, segs: list, payload: dict, query: dict) -> ComputeResponse:
    irs = _bucket(store, "internal_ranges")
    if not segs:
        if method == "GET":
            items = [_ir_view(r) for k, r in sorted(irs.items()) if k.startswith(f"{project}/{location}/")]
            return _json(200, {"internalRanges": items} if items else {})
        if method == "POST":
            name = _tail(str((query or {}).get("internalRangeId") or payload.get("name") or "")).strip()
            try:
                _check_name(name, "Internal range name")
            except _E as e:
                return _err(e.status, e.gcp_status, e.message)
            key = _ir_key(project, location, name)
            if key in irs:
                return _err(409, "ALREADY_EXISTS", f"Internal range {name} already exists")
            net_name = _resolve_network_name(project, payload.get("network"))
            if _net_key(project, net_name) not in store.networks:
                return _err(400, "INVALID_ARGUMENT", f"network '{net_name}' not found")
            used = _addr_space_used(store, project, net_name)
            cidr = str(payload.get("ipCidrRange") or "").strip()
            if not cidr:
                targets = payload.get("targetCidrRange") or ["10.0.0.0/8"]
                plen = int(payload.get("prefixLength") or 24)
                cidr = _allocate_cidr(targets, plen, used)
                if not cidr:
                    return _err(400, "RESOURCE_EXHAUSTED", "No free CIDR block of the requested size in the target range(s)")
            else:
                try:
                    ipaddress.ip_network(cidr, strict=False)
                except ValueError:
                    return _err(400, "INVALID_ARGUMENT", f"Invalid ipCidrRange: {cidr}")
                if not (payload.get("overlaps") or []) and _cidr_overlaps_any(cidr, used):
                    return _err(400, "INVALID_ARGUMENT", f"ipCidrRange {cidr} overlaps an existing subnet or internal range on network {net_name}")
            irs[key] = {"project": project, "location": location, "name": name,
                        "description": str(payload.get("description", "")), "ipCidrRange": cidr, "network": net_name,
                        "usage": payload.get("usage") or "FOR_VPC", "peering": payload.get("peering") or "FOR_SELF",
                        "targetCidrRange": payload.get("targetCidrRange") or [], "overlaps": payload.get("overlaps") or [],
                        "createTime": _ts()}
            return _json(200, _nc_lro(project, "networkconnectivity.v1.InternalRange", _ir_view(irs[key])))
        return _err(405, "METHOD_NOT_ALLOWED", "Method not allowed")
    name = segs[0]
    key = _ir_key(project, location, name)
    rec = irs.get(key)
    if rec is None:
        return _not_found(f"Internal range {name} not found")
    if method == "GET":
        return _json(200, _ir_view(rec))
    if method == "DELETE":
        del irs[key]
        return _json(200, _nc_lro(project, "google.protobuf.Empty", {}))
    return _err(405, "METHOD_NOT_ALLOWED", "Method not allowed")


# ── Serverless VPC Access connectors (vpcaccess.googleapis.com v1 connectors) ───────────────
_CONNECTOR_STATES = {"READY"}


def _vpcc_key(project, region, name):
    return f"{project}/{region}/{name}"


def _vpcc_view(rec: dict) -> dict:
    project, region = rec["project"], rec["region"]
    out = {
        "name": f"projects/{project}/locations/{region}/connectors/{rec['name']}",
        "network": rec["network"], "ipCidrRange": rec.get("ipCidrRange", ""),
        "minThroughput": rec.get("minThroughput", 200), "maxThroughput": rec.get("maxThroughput", 300),
        "machineType": rec.get("machineType", "e2-micro"), "state": "READY",
        "connectedProjects": [project],
    }
    if rec.get("subnetName"):
        out["subnet"] = {"name": rec["subnetName"]}
    return out


def _connectors(store: ComputeStore, method: str, project: str, region: str, segs: list, payload: dict, query: dict) -> ComputeResponse:
    conns = _bucket(store, "vpc_connectors")
    if not segs:
        if method == "GET":
            items = [_vpcc_view(r) for k, r in sorted(conns.items()) if k.startswith(f"{project}/{region}/")]
            return _json(200, {"connectors": items} if items else {})
        if method == "POST":
            name = str((query or {}).get("connectorId") or payload.get("name") or "").strip()
            try:
                _check_name(name, "Connector name")
            except _E as e:
                return _err(e.status, e.gcp_status, e.message)
            key = _vpcc_key(project, region, name)
            if key in conns:
                return _err(409, "ALREADY_EXISTS", f"Connector {name} already exists")
            net_name = _resolve_network_name(project, payload.get("network"))
            subnet = payload.get("subnet") or {}
            cidr = str(payload.get("ipCidrRange") or "").strip()
            if subnet.get("name"):
                sub_region = subnet.get("region") or region
                srec = store.subnetworks.get(_sub_key(project, sub_region, subnet["name"]))
                if not srec:
                    return _err(400, "INVALID_ARGUMENT", f"Subnet '{subnet['name']}' not found")
                net_name = srec["networkName"]
            else:
                if _net_key(project, net_name) not in store.networks:
                    return _err(400, "INVALID_ARGUMENT", f"network '{net_name}' not found")
                if not cidr:
                    return _err(400, "INVALID_ARGUMENT", "Either ipCidrRange or subnet is required")
                try:
                    cidr_net = ipaddress.ip_network(cidr, strict=False)
                except ValueError:
                    return _err(400, "INVALID_ARGUMENT", f"Invalid ipCidrRange: {cidr}")
                if cidr_net.prefixlen != 28:
                    return _err(400, "INVALID_ARGUMENT", "ipCidrRange must be a /28")
                used = _addr_space_used(store, project, net_name)
                if _cidr_overlaps_any(cidr, used):
                    return _err(400, "INVALID_ARGUMENT", f"ipCidrRange {cidr} overlaps an existing subnet or reservation on network {net_name}")
            min_t, max_t = int(payload.get("minThroughput", 200)), int(payload.get("maxThroughput", 300))
            if not (200 <= min_t <= max_t <= 1000):
                return _err(400, "INVALID_ARGUMENT", "minThroughput/maxThroughput must satisfy 200 <= min <= max <= 1000")
            conns[key] = {"project": project, "region": region, "name": name, "network": payload.get("network") or net_name,
                         "ipCidrRange": cidr, "subnetName": subnet.get("name", ""),
                         "minThroughput": min_t, "maxThroughput": max_t,
                         "machineType": payload.get("machineType") or "e2-micro"}
            return _json(200, _nc_lro(project, "vpcaccess.v1.Connector", _vpcc_view(conns[key])))
        return _err(405, "METHOD_NOT_ALLOWED", "Method not allowed")
    name = segs[0]
    key = _vpcc_key(project, region, name)
    rec = conns.get(key)
    if rec is None:
        return _not_found(f"Connector {name} not found")
    if method == "GET":
        return _json(200, _vpcc_view(rec))
    if method == "DELETE":
        del conns[key]
        return _json(200, _nc_lro(project, "google.protobuf.Empty", {}))
    return _err(405, "METHOD_NOT_ALLOWED", "Method not allowed")


# ── Private Service Connection (servicenetworking.googleapis.com v1 services.connections) ───
def _psc_view(rec: dict) -> dict:
    return {"network": _self_link("global", rec["project"], f"networks/{rec['network']}"),
            "service": "servicenetworking.googleapis.com", "reservedPeeringRanges": list(rec["reservedPeeringRanges"]),
            "peering": "servicenetworking-googleapis-com", "state": "ACTIVE" if rec.get("active", True) else "INACTIVE"}


def _psc_connections(store: ComputeStore, method: str, project_hint: str, segs: list, payload: dict, query: dict) -> ComputeResponse:
    conns = _bucket(store, "psc_connections")
    if not segs:
        if method == "GET":
            net = str((query or {}).get("network") or "")
            net_name = _tail(net)
            proj = net.split("/")[1] if net.startswith("projects/") else project_hint
            rec = conns.get(f"{proj}/{net_name}")
            return _json(200, {"connections": [_psc_view(rec)]} if rec else {})
        if method == "POST":
            net_link = str(payload.get("network") or "")
            if not net_link:
                return _err(400, "INVALID_ARGUMENT", "network is required")
            proj = net_link.split("/")[1] if net_link.startswith("projects/") else project_hint
            net_name = _tail(net_link)
            if _net_key(proj, net_name) not in store.networks:
                return _err(400, "INVALID_ARGUMENT", f"network '{net_name}' not found")
            ranges = payload.get("reservedPeeringRanges") or []
            if not ranges:
                return _err(400, "INVALID_ARGUMENT", "reservedPeeringRanges is required")
            for rname in ranges:
                arec = store.addresses.get(_addr_key(proj, "global", rname))
                if not arec or arec.get("purpose") != "VPC_PEERING":
                    return _err(400, "INVALID_ARGUMENT", f"Reserved range '{rname}' is not a VPC_PEERING address on this project")
                if arec.get("network") != net_name:
                    return _err(400, "INVALID_ARGUMENT", f"Reserved range '{rname}' does not belong to network '{net_name}'")
            key = f"{proj}/{net_name}"
            if key in conns:
                return _err(409, "ALREADY_EXISTS", f"A connection already exists for network '{net_name}'")
            conns[key] = {"project": proj, "network": net_name, "reservedPeeringRanges": list(ranges), "active": True}
            return _json(200, _nc_lro(proj, "servicenetworking.v1.Connection", _psc_view(conns[key])))
        return _err(405, "METHOD_NOT_ALLOWED", "Method not allowed")
    # .../connections/servicenetworking.googleapis.com[:deleteConnection|:patch via PATCH]
    tail, verb = segs[0], ""
    if ":" in tail:
        tail, verb = tail.split(":", 1)
    net_name = str((query or {}).get("network") or payload.get("network") or "")
    net_name = _tail(net_name)
    key = next((k for k in conns if k.endswith(f"/{net_name}")), None) if net_name else None
    if key is None:   # fall back: only one connection in a single-project simulator sweep
        key = next(iter(conns), None)
    rec = conns.get(key) if key else None
    if rec is None:
        return _not_found("Private Service Connection not found")
    if verb == "deleteConnection" and method == "POST":
        del conns[key]
        return _json(200, _nc_lro(rec["project"], "google.protobuf.Empty", {}))
    if method == "PATCH":
        if "reservedPeeringRanges" in payload:
            rec["reservedPeeringRanges"] = list(payload["reservedPeeringRanges"])
        return _json(200, _nc_lro(rec["project"], "servicenetworking.v1.Connection", _psc_view(rec)))
    return _err(405, "METHOD_NOT_ALLOWED", "Method not allowed")


# ── Shared VPC / XPN (compute.googleapis.com v1 projects.*) ─────────────────────────────────
def _xpn_rec(store: ComputeStore, project: str) -> dict:
    xpn = _bucket(store, "xpn")
    return xpn.setdefault(project, {"host": False, "service_projects": []})


def _xpn_host_of(store: ComputeStore, project: str) -> str | None:
    xpn = _bucket(store, "xpn")
    for host, rec in xpn.items():
        if project in rec.get("service_projects", []):
            return host
    return None


def _xpn_resource(ref: dict) -> str:
    return str((ref or {}).get("id") or "")


def _usable_subnet_view(rec: dict) -> dict:
    return {"subnetwork": _self_link("regions", rec["project"], f"{rec['region']}/subnetworks/{rec['name']}"),
            "network": _self_link("global", rec["project"], f"networks/{rec['networkName']}"),
            "ipCidrRange": rec["ipCidrRange"]}


def _xpn_action(store: ComputeStore, method: str, project: str, action: str, payload: dict, query: dict) -> ComputeResponse:
    if action == "enableXpnHost" and method == "POST":
        if _xpn_host_of(store, project):
            return _err(400, "FAILED_PRECONDITION", f"Project {project} is already a service project of another host")
        _xpn_rec(store, project)["host"] = True
        return _json(200, _operation(project, "global", None, "enableXpnHost", _self_link("global", project, ""), store))
    if action == "disableXpnHost" and method == "POST":
        rec = _xpn_rec(store, project)
        if rec["service_projects"]:
            return _err(400, "FAILED_PRECONDITION",
                        f"Project {project} cannot be disabled, it has existing xpn resources attached: {rec['service_projects']}")
        rec["host"] = False
        return _json(200, _operation(project, "global", None, "disableXpnHost", _self_link("global", project, ""), store))
    if action == "enableXpnResource" and method == "POST":
        host = _xpn_rec(store, project)
        if not host["host"]:
            return _err(400, "FAILED_PRECONDITION", f"Project {project} is not set up as a shared VPC host")
        svc_project = _xpn_resource(payload.get("xpnResource"))
        if not svc_project:
            return _err(400, "INVALID_ARGUMENT", "xpnResource.id is required")
        existing = _xpn_host_of(store, svc_project)
        if existing and existing != project:
            return _err(400, "FAILED_PRECONDITION", f"Project {svc_project} is already attached to host {existing}")
        if _xpn_rec(store, svc_project)["host"]:
            return _err(400, "FAILED_PRECONDITION", f"Project {svc_project} is itself a shared VPC host and cannot be a service project")
        if svc_project not in host["service_projects"]:
            host["service_projects"].append(svc_project)
        return _json(200, _operation(project, "global", None, "enableXpnResource", _self_link("global", project, ""), store))
    if action == "disableXpnResource" and method == "POST":
        host = _xpn_rec(store, project)
        svc_project = _xpn_resource(payload.get("xpnResource"))
        host["service_projects"] = [p for p in host["service_projects"] if p != svc_project]
        return _json(200, _operation(project, "global", None, "disableXpnResource", _self_link("global", project, ""), store))
    if action == "listXpnHosts" and method == "POST":
        xpn = _bucket(store, "xpn")
        items = [{"name": p, "kind": "compute#project"} for p, rec in sorted(xpn.items()) if rec.get("host")]
        return _json(200, {"kind": "compute#xpnHostList", **({"items": items} if items else {})})
    if action == "getXpnResources" and method == "GET":
        rec = _xpn_rec(store, project)
        items = [{"id": p, "type": "PROJECT"} for p in rec["service_projects"]]
        return _json(200, {"kind": "compute#projectsGetXpnResources", **({"resources": items} if items else {})})
    return _not_found(f"Unknown shared VPC action: {action}")


def _usable_subnetworks(store: ComputeStore, project: str) -> ComputeResponse:
    """`aggregated/usableSubnetworks` — a service project's own subnets PLUS its shared VPC
    host's subnets (real cross-project sharing, not just bookkeeping flags)."""
    projects = {project}
    host = _xpn_host_of(store, project)
    if host:
        projects.add(host)
    items = [_usable_subnet_view(r) for k, r in sorted(store.subnetworks.items()) if r["project"] in projects]
    return _json(200, {"kind": "compute#usableSubnetworksAggregatedList", **({"items": items} if items else {})})


# ── Network firewall policies (regional, compute.googleapis.com v1 firewallPolicies) ────────
def _nfp_key(project, region, name):
    return f"{project}/{region}/{name}"


def _nfp_rule_view(r: dict) -> dict:
    return {"priority": r["priority"], "action": r["action"], "direction": r.get("direction", "INGRESS"),
            "disabled": r.get("disabled", False), "description": r.get("description", ""),
            "match": r.get("match") or {}}


def _nfp_view(rec: dict) -> dict:
    project, region = rec["project"], rec["region"]
    return {
        "name": rec["name"], "description": rec.get("description", ""),
        "selfLink": _self_link("regions", project, f"{region}/firewallPolicies/{rec['name']}"),
        "ruleTupleCount": len(rec["rules"]),
        "rules": [_nfp_rule_view(r) for r in sorted(rec["rules"], key=lambda r: r["priority"])],
        "associations": [{"name": a["name"], "attachmentTarget": a["network"]} for a in rec["associations"]],
        "creationTimestamp": rec["creationTimestamp"],
    }


def _firewall_policies(store: ComputeStore, method: str, project: str, region: str, segs: list, payload: dict, query: dict) -> ComputeResponse:
    pols = _bucket(store, "firewall_policies")
    if not segs:
        if method == "GET":
            items = [_nfp_view(r) for k, r in sorted(pols.items()) if k.startswith(f"{project}/{region}/")]
            return _json(200, {"kind": "compute#firewallPolicyList", **({"items": items} if items else {})})
        if method == "POST":
            name = str(payload.get("name") or "").strip()
            try:
                _check_name(name, "Firewall policy name")
            except _E as e:
                return _err(e.status, e.gcp_status, e.message)
            key = _nfp_key(project, region, name)
            if key in pols:
                return _err(409, "ALREADY_EXISTS", f"Firewall policy {name} already exists")
            pols[key] = {"project": project, "region": region, "name": name,
                        "description": str(payload.get("description", "")), "rules": [], "associations": [],
                        "creationTimestamp": _ts()}
            return _json(200, _operation(project, "regional", region, "insert",
                                         _self_link("regions", project, f"{region}/firewallPolicies/{name}"), store))
        return _err(405, "METHOD_NOT_ALLOWED", "Method not allowed")
    name, verb = segs[0], ""
    if ":" in name:
        name, verb = name.split(":", 1)
    elif len(segs) > 1:
        verb = segs[1]
    key = _nfp_key(project, region, name)
    rec = pols.get(key)
    if rec is None:
        return _not_found(f"Firewall policy {name} not found")
    link = _self_link("regions", project, f"{region}/firewallPolicies/{name}")
    if not verb:
        if method == "GET":
            return _json(200, _nfp_view(rec))
        if method == "DELETE":
            del pols[key]
            return _json(200, _operation(project, "regional", region, "delete", link, store))
        return _err(405, "METHOD_NOT_ALLOWED", "Method not allowed")
    if verb == "addRule" and method == "POST":
        r = payload.get("firewallPolicyRule") or payload
        priority = r.get("priority")
        if priority is None or r.get("action") not in ("allow", "deny", "goto_next"):
            return _err(400, "INVALID_ARGUMENT", "priority and action (allow|deny|goto_next) are required")
        if any(x["priority"] == priority for x in rec["rules"]):
            return _err(409, "ALREADY_EXISTS", f"A rule at priority {priority} already exists")
        rec["rules"].append({"priority": int(priority), "action": r["action"], "direction": r.get("direction", "INGRESS"),
                             "disabled": bool(r.get("disabled", False)), "description": str(r.get("description", "")),
                             "match": r.get("match") or {}})
        return _json(200, _operation(project, "regional", region, "addRule", link, store))
    if verb == "removeRule" and method == "POST":
        priority = (query or {}).get("priority") if query else None
        priority = int(priority) if priority is not None else payload.get("priority")
        before = len(rec["rules"])
        rec["rules"] = [r for r in rec["rules"] if r["priority"] != priority]
        if len(rec["rules"]) == before:
            return _not_found(f"No rule at priority {priority}")
        return _json(200, _operation(project, "regional", region, "removeRule", link, store))
    if verb == "addAssociation" and method == "POST":
        assoc = payload.get("association") or {}
        aname = str(assoc.get("name") or "").strip() or "default"
        target = assoc.get("attachmentTarget") or ""
        net_name = _resolve_network_name(project, target)
        if _net_key(project, net_name) not in store.networks:
            return _err(400, "INVALID_ARGUMENT", f"network '{net_name}' not found")
        if any(a["name"] == aname for a in rec["associations"]):
            return _err(409, "ALREADY_EXISTS", f"Association {aname} already exists")
        rec["associations"].append({"name": aname, "network": net_name})
        return _json(200, _operation(project, "regional", region, "addAssociation", link, store))
    if verb == "removeAssociation" and method == "POST":
        aname = (query or {}).get("name") if query else None
        aname = aname or payload.get("name")
        before = len(rec["associations"])
        rec["associations"] = [a for a in rec["associations"] if a["name"] != aname]
        if len(rec["associations"]) == before:
            return _not_found(f"No association {aname}")
        return _json(200, _operation(project, "regional", region, "removeAssociation", link, store))
    return _not_found(f"Unknown firewall policy action: {verb}")


# ── Packet mirroring (compute.googleapis.com v1 regions/*/packetMirrorings) ─────────────────
def _pm_key(project, region, name):
    return f"{project}/{region}/{name}"


def _pm_view(rec: dict) -> dict:
    project, region = rec["project"], rec["region"]
    return {
        "name": rec["name"], "description": rec.get("description", ""), "region": _self_link("regions", project, region),
        "network": {"url": _self_link("global", project, f"networks/{rec['network']}")},
        "collectorIlb": {"url": rec["collectorIlb"]}, "mirroredResources": rec["mirroredResources"],
        "filter": rec.get("filter") or {}, "enable": rec.get("enable", "TRUE"),
        "priority": rec.get("priority", 1000), "creationTimestamp": rec["creationTimestamp"],
        "selfLink": _self_link("regions", project, f"{region}/packetMirrorings/{rec['name']}"),
    }


def _packet_mirrorings(store: ComputeStore, method: str, project: str, region: str, segs: list, payload: dict) -> ComputeResponse:
    pms = _bucket(store, "packet_mirrorings")
    if not segs:
        if method == "GET":
            items = [_pm_view(r) for k, r in sorted(pms.items()) if k.startswith(f"{project}/{region}/")]
            return _json(200, {"kind": "compute#packetMirroringList", **({"items": items} if items else {})})
        if method == "POST":
            name = str(payload.get("name") or "").strip()
            try:
                _check_name(name, "Packet mirroring policy name")
            except _E as e:
                return _err(e.status, e.gcp_status, e.message)
            key = _pm_key(project, region, name)
            if key in pms:
                return _err(409, "ALREADY_EXISTS", f"Packet mirroring policy {name} already exists")
            net_ref = (payload.get("network") or {}).get("url") or (payload.get("network") or {}).get("name") or ""
            net_name = _resolve_network_name(project, net_ref)
            if _net_key(project, net_name) not in store.networks:
                return _err(400, "INVALID_ARGUMENT", f"network '{net_name}' not found")
            mirrored = payload.get("mirroredResources") or {}
            subnets = mirrored.get("subnetworks") or []
            tags = mirrored.get("tags") or []
            instances = mirrored.get("instances") or []
            if not subnets and not tags and not instances:
                return _err(400, "INVALID_ARGUMENT", "mirroredResources must specify at least one of subnetworks, instances or tags")
            for s in subnets:
                sname = _tail(s.get("url") or s.get("name") or "")
                if not any(r["name"] == sname and r["networkName"] == net_name
                           for r in store.subnetworks.values() if r["project"] == project):
                    return _err(400, "INVALID_ARGUMENT", f"Mirrored subnetwork '{sname}' not found on network {net_name}")
            collector = (payload.get("collectorIlb") or {}).get("url") or (payload.get("collectorIlb") or {}).get("name") or ""
            if not collector:
                return _err(400, "INVALID_ARGUMENT", "collectorIlb is required (an internal forwarding rule to receive mirrored traffic)")
            pms[key] = {"project": project, "region": region, "name": name, "description": str(payload.get("description", "")),
                       "network": net_name, "collectorIlb": collector, "mirroredResources": mirrored,
                       "filter": payload.get("filter") or {"IPProtocols": [], "cidrRanges": ["0.0.0.0/0"], "direction": "BOTH"},
                       "enable": payload.get("enable", "TRUE"), "priority": int(payload.get("priority", 1000)),
                       "creationTimestamp": _ts()}
            return _json(200, _operation(project, "regional", region, "insert",
                                         _self_link("regions", project, f"{region}/packetMirrorings/{name}"), store))
        return _err(405, "METHOD_NOT_ALLOWED", "Method not allowed")
    name = segs[0]
    key = _pm_key(project, region, name)
    rec = pms.get(key)
    if rec is None:
        return _not_found(f"Packet mirroring policy {name} not found")
    link = _self_link("regions", project, f"{region}/packetMirrorings/{name}")
    if method == "GET":
        return _json(200, _pm_view(rec))
    if method == "DELETE":
        del pms[key]
        return _json(200, _operation(project, "regional", region, "delete", link, store))
    if method in ("PATCH", "PUT"):
        if "enable" in payload:
            rec["enable"] = payload["enable"]
        if "filter" in payload:
            rec["filter"] = payload["filter"]
        return _json(200, _operation(project, "regional", region, "patch", link, store))
    return _err(405, "METHOD_NOT_ALLOWED", "Method not allowed")


def gcp_flow_log_records(store: ComputeStore, project: str, accepted: list, rejected: list, topo) -> list:
    """GCP VPC Flow Logs (compute.googleapis.com%2Fvpc_flows) for the subnets that actually
    have flow logs ON — real per-packet counters in, real per-subnet config gating out, same
    contract as mirrored_packet_log_entries. ACCEPT flows only, like real VPC Flow Logs
    (denials are Firewall Rules Logging, a separate — not yet modelled — log)."""
    try:
        from core.netsim.flowlogs import FlowLogCollector
    except ImportError:                                  # pragma: no cover - flat layout
        from netsim.flowlogs import FlowLogCollector     # type: ignore
    col = FlowLogCollector(topo)
    col.ingest(accepted, rejected)
    out = []
    for rec in col.gcp_records():
        for side in ("src_instance", "dest_instance"):
            inst = rec.get(side)
            if not inst:
                continue
            iface = next((i for i in topo.interfaces.values() if i.instance == inst.get("vm_name")), None)
            if iface is None:
                continue
            srec = store.subnetworks.get(iface.subnet)
            if srec and srec["project"] == project and srec.get("flowLogs"):
                out.append(rec)
                break
    return out


def mirrored_packet_log_entries(store: ComputeStore, project: str, accepted: list, topo) -> list:
    """Real per-packet events (from the netsim enforcer's flow counters, see core/netsim/
    flowlogs.py) that match an ENABLED packet mirroring policy's filter + mirrored resources —
    rendered as structured records a Cloud Logging sink on the collector can show. Offline-only
    (needs real packets); returns [] with no policies or no traffic, never synthesizes data."""
    out = []
    pms = _bucket(store, "packet_mirrorings")
    policies = [r for r in pms.values() if r["project"] == project and r.get("enable", "TRUE") == "TRUE"]
    if not policies:
        return out
    for f in accepted:
        iface = topo.iface_by_ip(f["src"]) or topo.iface_by_ip(f["dst"])
        if iface is None:
            continue
        subnet_name = topo.subnet_of(iface).name if iface.subnet in topo.subnets else ""
        for pol in policies:
            mr = pol["mirroredResources"]
            subnet_match = any(_tail(s.get("url") or s.get("name") or "") == subnet_name for s in mr.get("subnetworks") or [])
            tag_match = any(t in iface.tags for t in mr.get("tags") or [])
            inst_match = any(_tail(i.get("url") or i.get("name") or "") == iface.instance for i in mr.get("instances") or [])
            if not (subnet_match or tag_match or inst_match):
                continue
            cidrs = pol["filter"].get("cidrRanges") or ["0.0.0.0/0"]
            if not any(ip_in_cidr(f["src"], c) or ip_in_cidr(f["dst"], c) for c in cidrs):
                continue
            out.append({"mirroringPolicy": pol["name"], "collectorIlb": pol["collectorIlb"],
                        "connection": {"src_ip": f["src"], "dest_ip": f["dst"], "src_port": f["sport"],
                                       "dest_port": f["dport"], "protocol": f["proto"]},
                        "packets": f["packets"], "bytes": f["bytes"], "timestamp": _ts()})
    return out


def ip_in_cidr(ip: str, cidr: str) -> bool:
    try:
        return ipaddress.ip_address(ip) in ipaddress.ip_network(cidr, strict=False)
    except ValueError:
        return False


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

    try:
        payload = json.loads(body.decode("utf-8")) if body else {}
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    # ── services/servicenetworking.googleapis.com/connections (Private Service Connection) ──
    # no /projects/ segment: the project comes from the `network` link in the body/query.
    if segs[:2] == ["services", "servicenetworking.googleapis.com"]:
        try:
            return _psc_connections(store, method, "", segs[3:], payload, query or {})
        except _E as e:
            return _err(e.status, e.gcp_status, e.message)

    if len(segs) < 3 or segs[0] != "projects":
        return _not_found(f"Unknown path: {path}")
    project = segs[1]
    scope = segs[2]   # "global" | "regions" | "zones" | "aggregated" | "locations" | <xpn verb>

    try:
        # ── locations/{loc}/connectivityTests | internalRanges | connectors ───────────────
        if scope == "locations" and len(segs) >= 5 and segs[4].split(":")[0] == "connectivityTests":
            return _connectivity_tests(store, vm_store, method, project, segs, query, payload)
        if scope == "locations" and len(segs) >= 4 and segs[4] == "internalRanges":
            return _internal_ranges(store, method, project, segs[3], segs[5:], payload, query or {})
        if scope == "locations" and len(segs) >= 4 and segs[4] == "connectors":
            return _connectors(store, method, project, segs[3], segs[5:], payload, query or {})
        # ── projects/{p}:<xpn verb> — shared VPC host/service project lifecycle ────────────
        if len(segs) == 3 and scope in ("enableXpnHost", "disableXpnHost", "enableXpnResource",
                                        "disableXpnResource", "listXpnHosts", "getXpnResources"):
            return _xpn_action(store, method, project, scope, payload, query or {})
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
            elif kind == "firewallPolicies":
                return _firewall_policies(store, method, project, region, segs[5:], payload, query or {})
            elif kind == "packetMirrorings":
                return _packet_mirrorings(store, method, project, region, segs[5:], payload)
            elif kind == "operations" and len(segs) == 6:
                return _get_operation(project, "regions/" + region, segs[5])
            return _not_found(f"Unknown path: {path}")

        # ── aggregated/* (the console's "all regions" tabs) ─────────────────
        if scope == "aggregated" and len(segs) == 4:
            if segs[3] == "subnetworks" and method == "GET":
                return _aggregated_subnets(store, project)
            if segs[3] == "addresses" and method == "GET":
                return _aggregated_addresses(store, project)
            if segs[3] == "usableSubnetworks" and method == "GET":
                return _usable_subnetworks(store, project)
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
