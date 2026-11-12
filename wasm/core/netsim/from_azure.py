# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Azure → netsim: build a Topology from the ARM engine state (core/azure_arm_core.AzureArm.state,
the dict keyed by lower-cased resource id) — read-only.

Child resources are accepted in BOTH shapes ARM allows: inline (vnet.properties.subnets[],
nsg.properties.securityRules[], routeTable.properties.routes[], vnet.properties.virtualNetworkPeerings[])
and as separate child entries (…/virtualnetworks/v/subnets/s, …/securityrules/r, …).

Azure semantics captured:
  * NSG at the subnet AND at the NIC: inbound = subnet NSG then NIC NSG, outbound = NIC NSG then
    subnet NSG; both must allow. Subnet NSGs apply to traffic inside the subnet too.
  * default rules on every NSG: 65000 AllowVnetInBound / AllowVnetOutBound (VirtualNetwork),
    65001 AllowAzureLoadBalancerInBound / AllowInternetOutBound, 65500 DenyAllInBound / DenyAllOutBound
  * service tags VirtualNetwork (own space + peered vnets) / Internet / AzureLoadBalancer, ASGs
  * system routes per subnet: vnet space → VnetLocal, peered space → VNetPeering, 0.0.0.0/0 → Internet,
    and next hop None for 10/8, 172.16/12, 192.168/16, 100.64/10 outside the vnet; a UDR on the same
    prefix overrides the system route; next hops VirtualAppliance / Internet / None / VnetLocal
  * internet egress: NIC public IP, else subnet NAT gateway, else default outbound access
    (`defaultOutboundAccess`, true unless the subnet sets it false)
"""
from __future__ import annotations

import re

try:
    from core.netsim.model import (BLACKHOLE, EGRESS, IGW, INGRESS, INSTANCE, LOCAL, NAT, PEERING, RFC1918,
                                   STATEFUL_PRIORITY, Gateway, Interface, Network, Peer, Peering, Route,
                                   RouteTable, Rule, RuleSet, Subnet, Topology, cidr_covers)
except ImportError:
    from model import (BLACKHOLE, EGRESS, IGW, INGRESS, INSTANCE, LOCAL, NAT, PEERING, RFC1918,  # type: ignore
                       STATEFUL_PRIORITY, Gateway, Interface, Network, Peer, Peering, Route,
                       RouteTable, Rule, RuleSet, Subnet, Topology, cidr_covers)

INTERNET_GW = "azure-internet"
_NET = "/providers/microsoft.network/"

DEFAULT_RULES = [
    Rule(direction=INGRESS, action="allow", peers=[Peer("service_tag", "VirtualNetwork")],
         local=[Peer("service_tag", "VirtualNetwork")], priority=65000, name="AllowVnetInBound", implied=True),
    Rule(direction=INGRESS, action="allow", peers=[Peer("service_tag", "AzureLoadBalancer")],
         priority=65001, name="AllowAzureLoadBalancerInBound", implied=True),
    Rule(direction=INGRESS, action="deny", peers=[Peer("any")], priority=65500, name="DenyAllInBound", implied=True),
    Rule(direction=EGRESS, action="allow", peers=[Peer("service_tag", "VirtualNetwork")],
         local=[Peer("service_tag", "VirtualNetwork")], priority=65000, name="AllowVnetOutBound", implied=True),
    Rule(direction=EGRESS, action="allow", peers=[Peer("service_tag", "Internet")], priority=65001,
         name="AllowInternetOutBound", implied=True),
    Rule(direction=EGRESS, action="deny", peers=[Peer("any")], priority=65500, name="DenyAllOutBound", implied=True),
]


def _lid(x) -> str:
    return str((x or {}).get("id") if isinstance(x, dict) else (x or "")).lower()


def _typed(state: dict, typ: str) -> dict:
    """Top-level resources of one Microsoft.Network type: {lower id: resource}."""
    pat = re.compile(rf"{re.escape(_NET)}{typ}/[^/]+$")
    return {k: v for k, v in state.items() if pat.search(k)}


def _children(state: dict, parent_lid: str, inline: list, child: str) -> list:
    out = {}
    for c in inline or []:
        name = c.get("name") or _lid(c).split("/")[-1]
        out[name.lower()] = {"name": name, "id": f"{parent_lid}/{child}/{name}".lower(),
                             "properties": c.get("properties") or {k: v for k, v in c.items() if k not in ("name", "id")}}
    prefix = f"{parent_lid}/{child}/"
    for k, v in state.items():
        if k.startswith(prefix) and "/" not in k[len(prefix):]:
            out[k[len(prefix):]] = {"name": v.get("name") or k[len(prefix):], "id": k, "properties": v.get("properties") or {}}
    return list(out.values())


def _many(props: dict, single: str, plural: str) -> list:
    vals = list(props.get(plural) or [])
    if props.get(single) not in (None, ""):
        vals.append(props[single])
    return vals or ["*"]


def _peer_of(prefix: str) -> Peer:
    p = str(prefix)
    if p in ("*", "0.0.0.0/0", "Any", "any"):
        return Peer("any")
    if p.lower() in ("virtualnetwork", "internet", "azureloadbalancer"):
        return Peer("service_tag", p)
    if "/" not in p and re.match(r"^\d+\.\d+\.\d+\.\d+$", p):
        return Peer("cidr", p + "/32")
    if re.match(r"^\d+\.\d+\.\d+\.\d+/\d+$", p):
        return Peer("cidr", p)
    return Peer("service_tag", p)      # other service tags (Storage, Sql, …): match nothing locally


def _port_list(vals: list) -> list:
    out = []
    for v in vals:
        v = str(v)
        if v in ("*", ""):
            return [None]
        lo, _, hi = v.partition("-")
        out.append((int(lo), int(hi or lo)))
    return out


def _nsg_rules(props: dict) -> list:
    direction = INGRESS if str(props.get("direction", "Inbound")).lower() == "inbound" else EGRESS
    action = "allow" if str(props.get("access", "Allow")).lower() == "allow" else "deny"
    src = [_peer_of(x) for x in _many(props, "sourceAddressPrefix", "sourceAddressPrefixes")]
    dst = [_peer_of(x) for x in _many(props, "destinationAddressPrefix", "destinationAddressPrefixes")]
    src += [Peer("group", _lid(a)) for a in props.get("sourceApplicationSecurityGroups") or []]
    dst += [Peer("group", _lid(a)) for a in props.get("destinationApplicationSecurityGroups") or []]
    if props.get("sourceApplicationSecurityGroups") and _many(props, "sourceAddressPrefix", "sourceAddressPrefixes") == ["*"]:
        src = [p for p in src if p.kind == "group"]
    if props.get("destinationApplicationSecurityGroups") and _many(props, "destinationAddressPrefix", "destinationAddressPrefixes") == ["*"]:
        dst = [p for p in dst if p.kind == "group"]
    remote, local = (src, dst) if direction == INGRESS else (dst, src)
    local_sel = None if any(p.kind == "any" for p in local) else local
    sports = _port_list(_many(props, "sourcePortRange", "sourcePortRanges"))
    out = []
    for dp in _port_list(_many(props, "destinationPortRange", "destinationPortRanges")):
        for sp in sports:
            out.append(Rule(direction=direction, action=action, protocol=str(props.get("protocol", "*")),
                            ports=dp, src_ports=sp, peers=remote, local=local_sel,
                            priority=int(props.get("priority", 1000)), name=props.get("_name", "")))
    return out


def _nsg_ruleset(state, lid, res) -> RuleSet:
    rules = []
    for r in _children(state, lid, (res.get("properties") or {}).get("securityRules"), "securityrules"):
        p = dict(r["properties"])
        p["_name"] = r["name"]
        rules.extend(_nsg_rules(p))
    rules.extend(Rule(**{**r.__dict__}) for r in DEFAULT_RULES)
    return RuleSet(id=lid, mode=STATEFUL_PRIORITY, kind="nsg", name=res.get("name", ""), rules=rules)


def from_azure(state: dict) -> Topology:
    t = Topology(cloud="azure")
    t.add(Gateway(id=INTERNET_GW, kind=IGW, network=""))
    for lid, res in _typed(state, "networksecuritygroups").items():
        t.add(_nsg_ruleset(state, lid, res))
    for lid, res in _typed(state, "natgateways").items():
        t.add(Gateway(id=lid, kind=NAT, name=res.get("name", "")))
    route_tables = _typed(state, "routetables")

    vnets = _typed(state, "virtualnetworks")
    subnets_raw, links = {}, {}
    for lid, res in vnets.items():
        props = res.get("properties") or {}
        t.add(Network(id=lid, cloud="azure", cidrs=list((props.get("addressSpace") or {}).get("addressPrefixes") or []),
                      name=res.get("name", "")))
        for s in _children(state, lid, props.get("subnets"), "subnets"):
            subnets_raw[s["id"]] = (lid, s)
        for p in _children(state, lid, props.get("virtualNetworkPeerings"), "virtualnetworkpeerings"):
            pp = p["properties"]
            links[(lid, _lid(pp.get("remoteVirtualNetwork")))] = (
                p["id"], str(pp.get("peeringState", "Connected")) == "Connected")
    # An Azure peering is TWO link resources (one per vnet); it only carries traffic once both
    # sides exist and are Connected — a one-sided link stays "Initiated". One model Peering per pair.
    for (a, b), (link_id, ok) in sorted(links.items()):
        if (b, a) in links and a > b:
            continue
        back = links.get((b, a))
        t.add(Peering(id=link_id, a=a, b=b, active=bool(ok and back and back[1])))

    for slid, (vlid, s) in subnets_raw.items():
        props = s["properties"]
        prefix = props.get("addressPrefix") or (props.get("addressPrefixes") or [None])[0]
        if not prefix:
            continue
        net = t.networks[vlid]
        routes = [Route(dest=c, kind=LOCAL, origin="system", name="VnetLocal") for c in net.cidrs]
        for p in t.peerings.values():
            other = p.b if p.a == vlid else (p.a if p.b == vlid else None)
            if other and p.active and other in t.networks:
                routes += [Route(dest=c, kind=PEERING, target=p.id, origin="system", name="VNetPeering")
                           for c in t.networks[other].cidrs]
        routes.append(Route(dest="0.0.0.0/0", kind=IGW, target=INTERNET_GW, origin="system", name="Internet"))
        routes += [Route(dest=c, kind=BLACKHOLE, origin="system", name="None (private range)")
                   for c in RFC1918 if not any(cidr_covers(c, x) or cidr_covers(x, c) for x in net.cidrs)]
        rt_lid = _lid(props.get("routeTable"))
        if rt_lid and rt_lid in route_tables:
            for r in _children(state, rt_lid, (route_tables[rt_lid].get("properties") or {}).get("routes"), "routes"):
                rp = r["properties"]
                r = {**r, "name": f"{route_tables[rt_lid].get('id', rt_lid)}/routes/{r['name']}"}   # nextHop reports the table
                nht = str(rp.get("nextHopType", "None")).lower()
                dest = rp.get("addressPrefix", "")
                if nht == "virtualappliance":
                    routes.append(Route(dest=dest, kind=INSTANCE, target=rp.get("nextHopIpAddress", ""), name=r["name"]))
                elif nht == "internet":
                    routes.append(Route(dest=dest, kind=IGW, target=INTERNET_GW, name=r["name"]))
                elif nht == "vnetlocal":
                    routes.append(Route(dest=dest, kind=LOCAL, name=r["name"]))
                elif nht == "none":
                    routes.append(Route(dest=dest, kind=BLACKHOLE, name=r["name"]))
                else:
                    routes.append(Route(dest=dest, kind="unsupported", target=nht, name=r["name"]))
                    t.warnings.append(f"{rt_lid}: route {r['name']} next hop {nht} not simulated")
        t.add(RouteTable(id=f"{slid}/effective-routes", routes=routes))
        nsg = _lid(props.get("networkSecurityGroup"))
        nat = _lid(props.get("natGateway"))
        t.add(Subnet(id=slid, network=vlid, cidr=prefix, route_table=f"{slid}/effective-routes",
                     rulesets=[nsg] if nsg in t.rulesets else [], nat=nat if nat in t.gateways else None,
                     default_outbound=props.get("defaultOutboundAccess", True) is not False, name=s["name"]))

    vm_of_nic = {}
    for lid, res in {k: v for k, v in state.items() if re.search(r"/providers/microsoft.compute/virtualmachines/[^/]+$", k)}.items():
        for n in ((res.get("properties") or {}).get("networkProfile") or {}).get("networkInterfaces") or []:
            vm_of_nic[_lid(n)] = res.get("name", lid)
    pips = {k: (v.get("properties") or {}).get("ipAddress") or "pip:" + k.split("/")[-1]
            for k, v in _typed(state, "publicipaddresses").items()}
    for lid, res in _typed(state, "networkinterfaces").items():
        props = res.get("properties") or {}
        nsg = _lid(props.get("networkSecurityGroup"))
        for i, ipc in enumerate(props.get("ipConfigurations") or []):
            ip = ipc.get("properties") or {}
            slid = _lid(ip.get("subnet"))
            if slid not in t.subnets:
                t.warnings.append(f"{res.get('name')}: ipConfiguration {ipc.get('name')} has no known subnet")
                continue
            pip = _lid(ip.get("publicIPAddress"))
            t.add(Interface(id=lid if i == 0 else f"{lid}#{i}", instance=vm_of_nic.get(lid, ""), subnet=slid,
                            ip=ip.get("privateIPAddress", ""), public_ip=pips.get(pip) if pip else None,
                            groups=[_lid(a) for a in ip.get("applicationSecurityGroups") or []],
                            rulesets=[nsg] if nsg in t.rulesets else [],
                            source_dest_check=not props.get("enableIPForwarding", False), name=res.get("name", "")))
    # VirtualAppliance next hops are IPs → resolve to the interface holding that IP
    for rt in t.route_tables.values():
        for r in rt.routes:
            if r.kind == INSTANCE:
                hit = next((i for i in t.interfaces.values() if i.ip == r.target), None)
                if hit:
                    r.target = hit.id
                else:
                    r.kind = BLACKHOLE
    return t
