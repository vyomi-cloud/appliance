"""Azure Virtual Network Manager: DEPLOY + effective-rule evaluation (pure Python, Nano + offline).  Extension resource under a
network manager:   POST|GET {managerId}/providers/Microsoft.Vyomi/networkManagerEngine/{deploy|evaluate|status}

The configurations themselves (groups, static members, connectivity and security admin configs, rule collections, rules) are the
ARM records of core/azure_netcfg_core.py.  Until now nothing acted on them; this engine does:

  deploy   {"commitType": "Connectivity", "configurationIds": [...]}
           HubAndSpoke / Mesh: peerings are WRITTEN into each member virtual network's ``properties.virtualNetworkPeerings``
           (state Connected, named ANM_<config>_<n>, tagged managedBy=networkManager) so Network Watcher next-hop, the netsim
           engine and the VNet Peerings blade see them.  A commit REPLACES the previously managed peerings of this manager
           (configurations left out of the commit are removed).
           {"commitType": "SecurityAdmin", "configurationIds": [...]}
           marks the security admin configuration deployed for its groups; rules are enforced by ``evaluate``.
  evaluate {"vnetId", "direction", "protocol", "sourceAddress", "destinationAddress", "sourcePort", "destinationPort"}
           the deployed rules that apply to that virtual network (via the groups' static members) are evaluated in priority
           order (lowest number first, across collections): Deny -> blocked even if an NSG allows it; AlwaysAllow -> allowed
           and NSGs are bypassed; Allow -> continues to the NSG.  No match -> falls through to the NSG.
Honest limits: only static group members (no Azure Policy conditional membership), no routing configurations, no regions
filtering beyond recording targetLocations, and a Deny/AlwaysAllow verdict is reported here -- the Docker/nftables data path of
the netsim engine does not yet consume it for live packets.
"""
from __future__ import annotations

import datetime
import ipaddress
import re

NM = "microsoft.network/networkmanagers"
VNET = "microsoft.network/virtualnetworks"


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def find_marker(chain):
    low = [c.lower() for c in chain]
    for i in range(len(low) - 2):
        if low[i] == "providers" and low[i + 1] == "microsoft.vyomi" and low[i + 2] == "networkmanagerengine":
            return i
    return None


def _err(status, code, msg):
    return {"status": status, "body": {"error": {"code": code, "message": msg}}}


def _ok(body, status=200):
    return {"status": status, "body": body}


def _children(state, rid, seg):
    pre = rid.lower() + "/" + seg.lower() + "/"
    return [r for r in state.values() if isinstance(r, dict) and str(r.get("id", "")).lower().startswith(pre) and "properties" in r]


def _group_vnets(state, group_id):
    out = []
    for m in _children(state, group_id, "staticMembers"):
        rid = str((m["properties"] or {}).get("resourceId", "")).lower()
        v = state.get(rid)
        if v is not None and (v.get("_type") or "").lower() == VNET:
            out.append(v)
    return out


def _managed(p):
    return [x for x in p.get("virtualNetworkPeerings", []) if isinstance(x, dict) and (x.get("tags") or {}).get("managedBy") == "networkManager"]


def _peer(local, remote, name, use_remote_gw, allow_gw_transit):
    return {"name": name, "id": f"{local['id']}/virtualNetworkPeerings/{name}", "type": "Microsoft.Network/virtualNetworks/virtualNetworkPeerings",
            "tags": {"managedBy": "networkManager"},
            "properties": {"remoteVirtualNetwork": {"id": remote["id"]}, "peeringState": "Connected", "peeringSyncLevel": "FullyInSync",
                           "allowVirtualNetworkAccess": True, "allowForwardedTraffic": True, "allowGatewayTransit": bool(allow_gw_transit),
                           "useRemoteGateways": bool(use_remote_gw), "provisioningState": "Succeeded",
                           "remoteAddressSpace": (remote.get("properties") or {}).get("addressSpace", {"addressPrefixes": []})}}


def deploy(state, nm, body):
    commit = body.get("commitType")
    if commit not in ("Connectivity", "SecurityAdmin"):
        return _err(400, "InvalidCommitType", "commitType must be Connectivity or SecurityAdmin.")
    cfg_ids = [str(c) for c in body.get("configurationIds") or []]
    cfgs = []
    for cid in cfg_ids:
        c = state.get(cid.lower())
        want = NM + ("/connectivityconfigurations" if commit == "Connectivity" else "/securityadminconfigurations")
        if c is None or (c.get("_type") or "").lower() != want or not c["id"].lower().startswith(nm["id"].lower() + "/"):
            return _err(400, "ConfigurationNotFound", f"{cid} is not a {commit} configuration of network manager {nm['name']}.")
        cfgs.append(c)
    commits = nm.setdefault("_commits", [])
    result = {"commitType": commit, "configurationIds": cfg_ids, "targetLocations": body.get("targetLocations") or [], "deploymentStatus": "Deployed", "commitTime": _now()}
    if commit == "Connectivity":
        # remove every peering this manager created before, then write the new set (a commit is the full desired state)
        for v in _children(state, nm["id"], "networkGroups"):
            for vn in _group_vnets(state, v["id"]):
                p = vn.setdefault("properties", {})
                p["virtualNetworkPeerings"] = [x for x in p.get("virtualNetworkPeerings", []) if x not in _managed(p)]
        made = 0
        for c in cfgs:
            cp = c["properties"]
            groups = [g for g in cp.get("appliesToGroups") or []]
            members = []
            for g in groups:
                if g.get("groupConnectivity", "None") == "DirectlyConnected" or cp.get("connectivityTopology") == "HubAndSpoke":
                    members += _group_vnets(state, g.get("networkGroupId", ""))
            seen, uniq = set(), []
            for v in members:
                if v["id"].lower() not in seen:
                    seen.add(v["id"].lower()); uniq.append(v)
            if cp.get("connectivityTopology") == "Mesh":
                pairs = [(a, b) for i, a in enumerate(uniq) for b in uniq[i + 1:]]
            else:
                hub = state.get(str((cp.get("hubs") or [{}])[0].get("resourceId", "")).lower())
                pairs = [(hub, s) for s in uniq if hub is not None and s["id"].lower() != hub["id"].lower()]
            use_gw = any(str(g.get("useHubGateway", "")).lower() == "true" for g in groups)
            for n, (a, b) in enumerate(pairs):
                for local, remote, hub_side in ((a, b, True), (b, a, False)):
                    nm_ = f"ANM_{c['name']}_{local['name']}_to_{remote['name']}"
                    local.setdefault("properties", {}).setdefault("virtualNetworkPeerings", []).append(
                        _peer(local, remote, nm_, use_gw and cp.get("connectivityTopology") == "HubAndSpoke" and not hub_side,
                              use_gw and cp.get("connectivityTopology") == "HubAndSpoke" and hub_side))
                made += 2
        result["peeringsCreated"] = made
    else:
        nm["_secadmin_deployed"] = {"configurationIds": cfg_ids, "commitTime": result["commitTime"]}
        result["rulesDeployed"] = sum(len(_children(state, col["id"], "rules")) for c in cfgs for col in _children(state, c["id"], "ruleCollections"))
    commits.append(result)
    del commits[:-30]
    return _ok(result)


def _match_addr(spec_list, addr, internet_default):
    if not spec_list:
        return True
    for s in spec_list:
        t, pfx = s.get("addressPrefixType"), s.get("addressPrefix")
        if t == "IPPrefix":
            if pfx in ("*", None):
                return True
            try:
                if addr and ipaddress.ip_address(addr) in ipaddress.ip_network(pfx, strict=False):
                    return True
            except ValueError:
                pass
        elif t == "ServiceTag":
            try:
                priv = bool(addr) and ipaddress.ip_address(addr).is_private
            except ValueError:
                priv = False
            if (pfx == "Internet" and addr and not priv) or (pfx == "VirtualNetwork" and priv):
                return True
    return False


def _match_ports(ranges, port):
    if not ranges:
        return True
    for r in ranges:
        r = str(r)
        if r == "*":
            return True
        m = re.match(r"^(\d+)(?:-(\d+))?$", r)
        if m and port is not None and int(m.group(1)) <= int(port) <= int(m.group(2) or m.group(1)):
            return True
    return False


def evaluate(state, nm, req):
    vid = str(req.get("vnetId", "")).lower()
    vnet = state.get(vid)
    if vnet is None or (vnet.get("_type") or "").lower() != VNET:
        return _err(400, "InvalidVnet", "vnetId must be an existing virtual network.")
    dep = nm.get("_secadmin_deployed")
    direction = req.get("direction", "Inbound")
    proto = req.get("protocol", "Tcp")
    out = {"vnetId": vnet["id"], "direction": direction, "deployed": bool(dep), "rulesConsidered": 0, "matchedRule": None, "verdict": "NoAdminRuleMatched", "nextHop": "networkSecurityGroups"}
    if not dep:
        out["note"] = "No security admin configuration is deployed to this network manager; traffic is decided by NSGs."
        return _ok(out)
    rules = []
    for cid in dep["configurationIds"]:
        cfg = state.get(cid.lower())
        for col in _children(state, cfg["id"], "ruleCollections") if cfg else []:
            applies = [str(g.get("networkGroupId", "")).lower() for g in col["properties"].get("appliesToGroups") or []]
            if not any(vnet["id"].lower() in {v["id"].lower() for v in _group_vnets(state, gid)} for gid in applies):
                continue
            for r in _children(state, col["id"], "rules"):
                rules.append((r["properties"].get("priority", 4096), cfg["name"], col["name"], r))
    rules.sort(key=lambda x: x[0])
    for prio, cname, colname, r in rules:
        p = r["properties"]
        if p.get("direction") != direction:
            continue
        out["rulesConsidered"] += 1
        if p.get("protocol") not in ("Any", None) and str(p.get("protocol")).lower() != str(proto).lower():
            continue
        if not (_match_addr(p.get("sources"), req.get("sourceAddress"), True) and _match_addr(p.get("destinations"), req.get("destinationAddress"), True)
                and _match_ports(p.get("sourcePortRanges"), req.get("sourcePort")) and _match_ports(p.get("destinationPortRanges"), req.get("destinationPort"))):
            continue
        out["matchedRule"] = {"configuration": cname, "collection": colname, "rule": r["name"], "priority": prio, "access": p.get("access")}
        acc = p.get("access")
        out["verdict"] = {"Deny": "Denied", "AlwaysAllow": "Allowed", "Allow": "AllowedContinueToNsg"}.get(acc, acc)
        out["nextHop"] = "none" if acc == "Deny" else ("destination" if acc == "AlwaysAllow" else "networkSecurityGroups")
        break
    return _ok(out)


def handle(state, method, nm_id, rest, body):
    nm = state.get(nm_id.lower())
    if nm is None or (nm.get("_type") or "").lower() != NM:
        return _err(404, "ResourceNotFound", "The network manager was not found.")
    action = (rest[0] if rest else "").lower()
    if action == "deploy" and method == "POST":
        return deploy(state, nm, body or {})
    if action == "evaluate" and method == "POST":
        return evaluate(state, nm, body or {})
    if action == "status" and method == "GET":
        return _ok({"commits": list(nm.get("_commits") or []), "securityAdminDeployed": nm.get("_secadmin_deployed")})
    return _err(404, "ActionNotFound", "Use POST deploy, POST evaluate or GET status.")
