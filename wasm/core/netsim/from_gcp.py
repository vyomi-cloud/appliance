# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""GCP → netsim: build a Topology from core/gcp_compute_core.py (networks, subnetworks,
firewalls, routes) + core/gcp_compute_instances_core.py (instance nics) — read-only.

GCP semantics captured:
  * a VPC network is GLOBAL: no network CIDR, its address space = all subnet ranges; every
    subnet range gets a system `local` route (subnet routes), visible from every region
  * the auto-created default route 0.0.0.0/0 → default-internet-gateway (priority 1000) is
    added unless the network says it was deleted (`_defaultRouteDeleted`) — the core does not
    materialise it yet
  * firewall rules are network-wide, STATEFUL, lowest priority wins, DENY wins a tie;
    target tags / target service accounts select the instances a rule applies to;
    source tags / source service accounts match only instances in the same network
  * implied rules: allow all egress + deny all ingress at priority 65535
  * internet egress needs an external IP (accessConfig) OR Cloud NAT on the subnet
  * custom routes: priority + instance-tag scoping; next hops gateway / instance / ip
  * VPC peering exchanges subnet routes automatically (both sides) and is non-transitive
"""
from __future__ import annotations

try:
    from core.netsim.model import (BLACKHOLE, EGRESS, IGW, INGRESS, INSTANCE, LOCAL, NAT, PEERING,
                                   STATEFUL_PRIORITY, Gateway, Interface, Network, Peer, Peering, Route,
                                   RouteTable, Rule, RuleSet, Subnet, Topology)
except ImportError:
    from model import (BLACKHOLE, EGRESS, IGW, INGRESS, INSTANCE, LOCAL, NAT, PEERING,  # type: ignore
                       STATEFUL_PRIORITY, Gateway, Interface, Network, Peer, Peering, Route,
                       RouteTable, Rule, RuleSet, Subnet, Topology)

IGW_ID = "default-internet-gateway"


def _tail(link: str) -> str:
    return str(link or "").rstrip("/").split("/")[-1]


def _region_of_subnet_link(link: str) -> str:
    parts = str(link or "").split("/")
    return parts[parts.index("regions") + 1] if "regions" in parts else ""


def _port_ranges(entry: dict) -> list:
    ports = entry.get("ports") or []
    if not ports:
        return [None]
    out = []
    for p in ports:
        p = str(p)
        if "-" in p:
            lo, hi = p.split("-", 1)
            out.append((int(lo), int(hi)))
        else:
            out.append((int(p), int(p)))
    return out


def _fw_rules(fw: dict) -> list:
    direction = INGRESS if fw.get("direction", "INGRESS") == "INGRESS" else EGRESS
    if direction == INGRESS:
        peers = [Peer.cidr(c) for c in fw.get("sourceRanges") or []]
        peers += [Peer("tag", x) for x in fw.get("sourceTags") or []]
        peers += [Peer("service_account", x) for x in fw.get("sourceServiceAccounts") or []]
        if not peers:      # GCP: an ingress rule with no source → sourceRanges 0.0.0.0/0
            peers = [Peer("any")]
    else:
        peers = [Peer.cidr(c) for c in fw.get("destinationRanges") or []] or [Peer("any")]
    targets = None
    if fw.get("targetTags"):
        targets = [Peer("tag", x) for x in fw["targetTags"]]
    elif fw.get("targetServiceAccounts"):
        targets = [Peer("service_account", x) for x in fw["targetServiceAccounts"]]
    out = []
    for action, key in (("allow", "allowed"), ("deny", "denied")):
        for entry in fw.get(key) or []:
            proto = str(entry.get("IPProtocol", "all"))
            for pr in _port_ranges(entry):
                out.append(Rule(direction=direction, action=action, protocol=proto, ports=pr, peers=peers,
                                priority=int(fw.get("priority", 1000)), targets=targets, name=fw["name"]))
    return out


def _policy_match_peers(match: dict) -> list:
    ranges = match.get("srcIpRanges") or match.get("destIpRanges") or []
    peers = [Peer.cidr(c) for c in ranges]
    return peers or [Peer("any")]


def _policy_rules(pol: dict) -> list:
    """Regional network firewall policy rules → netsim Rule objects. Evaluated at a priority
    far below any classic VPC firewall rule's range so they ALWAYS win the tier (hierarchical
    policies evaluate before the network's own firewall rules in real GCP), while keeping their
    relative order among themselves. `goto_next` rules are not modelled as a fallthrough (no
    Rule.goto_next field yet) — stored/returned faithfully but evaluated as an implicit allow,
    the closest safe approximation; see the capability's documented limitation."""
    out = []
    for r in pol["rules"]:
        if r.get("disabled"):
            continue
        action = r["action"] if r["action"] in ("allow", "deny") else "allow"
        direction = INGRESS if r.get("direction", "INGRESS") == "INGRESS" else EGRESS
        match = r.get("match") or {}
        proto_ports = match.get("layer4Configs") or [{}]
        for pp in proto_ports:
            proto = str(pp.get("ipProtocol", "all"))
            ports = pp.get("ports") or []
            pr = None
            if ports:
                p0 = str(ports[0])
                pr = tuple(int(x) for x in p0.split("-", 1)) if "-" in p0 else (int(p0), int(p0))
            out.append(Rule(direction=direction, action=action, protocol=proto, ports=pr,
                            peers=_policy_match_peers(match), priority=r["priority"] - 10_000_000,
                            name=f"policy:{pol['name']}:{r['priority']}"))
    return out


def from_gcp(net_store, inst_store=None, project: str | None = None, cloud_nats=None, peerings=None) -> Topology:
    """`cloud_nats`: [{"network": n, "region": r, "subnets": [names] | "ALL"}] (Cloud Router NAT is
    not in the core yet). `peerings`: [{"name", "network", "peerNetwork", "state"}] likewise."""
    t = Topology(cloud="gcp")
    nets = {k: v for k, v in net_store.networks.items() if project is None or v["project"] == project}
    for key, n in nets.items():
        nid = f"{n['project']}/{n['name']}"
        fw_id = f"{nid}/firewall"
        t.add(Network(id=nid, cloud="gcp", cidrs=[], rulesets=[fw_id], name=n["name"]))
        t.add(RuleSet(id=fw_id, mode=STATEFUL_PRIORITY, kind="firewall", name=f"{n['name']} firewall rules", rules=[
            Rule(direction=EGRESS, action="allow", peers=[Peer("any")], priority=65535, name="implied-allow-egress", implied=True),
            Rule(direction=INGRESS, action="deny", peers=[Peer("any")], priority=65535, name="implied-deny-ingress", implied=True),
        ]))
        routes = []
        if "_hasDefaultRoute" not in n and not n.get("_defaultRouteDeleted"):
            # networks created before the core materialised its default route
            routes.append(Route(dest="0.0.0.0/0", kind=IGW, target=IGW_ID, priority=1000, origin="system",
                                name=f"default-route-{n['name']}"))
        t.add(RouteTable(id=f"{nid}/routes", routes=routes, name=f"{n['name']} routes"))
    t.add(Gateway(id=IGW_ID, kind=IGW, network=""))     # one per project, valid for every network

    for key, s in net_store.subnetworks.items():
        nid = f"{s['project']}/{s['networkName']}"
        if nid not in t.networks:
            continue
        sid = f"{s['project']}/{s['region']}/{s['name']}"
        t.networks[nid].cidrs.append(s["ipCidrRange"])
        t.route_tables[f"{nid}/routes"].routes.append(
            Route(dest=s["ipCidrRange"], kind=LOCAL, priority=0, origin="system", name=f"subnet:{s['name']}"))
        t.add(Subnet(id=sid, network=nid, cidr=s["ipCidrRange"], zone=s["region"], route_table=f"{nid}/routes",
                     name=s["name"]))

    for key, fw in net_store.firewalls.items():
        nid = f"{fw['project']}/{fw['networkName']}"
        if nid not in t.networks or fw.get("disabled"):
            continue
        t.rulesets[f"{nid}/firewall"].rules.extend(_fw_rules(fw))
        if fw.get("logEnable"):
            t.rulesets[f"{nid}/firewall"].log = True

    # Regional network firewall policies: a tier that evaluates before classic VPC firewall
    # rules on every network it's associated with (see _policy_rules for the priority trick).
    for pol in (getattr(net_store, "firewall_policies", None) or {}).values():
        if project and pol["project"] != project:
            continue
        rules = _policy_rules(pol)
        if not rules:
            continue
        for assoc in pol.get("associations") or []:
            nid = f"{pol['project']}/{assoc['network']}"
            if nid in t.networks:
                t.rulesets[f"{nid}/firewall"].rules.extend(rules)

    # Cloud Router NAT configs + network peerings straight from the core (params override/extend)
    cloud_nats = list(cloud_nats or [])
    for r in (getattr(net_store, "routers", None) or {}).values():
        if project and r["project"] != project:
            continue
        for nat in r.get("nats") or []:
            mode = nat.get("sourceSubnetworkIpRangesToNat", "ALL_SUBNETWORKS_ALL_IP_RANGES")
            subs = "ALL" if mode.startswith("ALL_SUBNETWORKS") else [_tail(x.get("name")) for x in nat.get("subnetworks") or []]
            cloud_nats.append({"network": f"{r['project']}/{r['networkName']}", "region": r["region"], "subnets": subs,
                               "name": f"{r['name']}/{nat.get('name')}"})
    peerings = list(peerings or [])
    for n in nets.values():
        for p in n.get("peerings") or []:
            if p.get("state") == "ACTIVE" and p.get("exchangeSubnetRoutes", True):
                a, b = f"{n['project']}/{n['name']}", f"{n['project']}/{_tail(p['network'])}"
                if a < b:                                   # one model peering per pair
                    peerings.append({"name": p["name"], "network": a, "peerNetwork": b, "state": "ACTIVE"})
    for nat in cloud_nats:
        nid = f"{project or nat.get('project', '')}/{nat['network']}" if "/" not in nat["network"] else nat["network"]
        gid = f"cloud-nat:{nat.get('name') or nid + ':' + nat.get('region', '')}"
        t.add(Gateway(id=gid, kind=NAT, network=nid))
        for s in t.subnets.values():
            if s.network == nid and s.zone == nat.get("region") and (nat.get("subnets", "ALL") == "ALL" or s.name in nat["subnets"]):
                s.nat = gid

    for p in peerings or []:
        a = p["network"] if "/" in p["network"] else f"{project}/{p['network']}"
        b = p["peerNetwork"] if "/" in p["peerNetwork"] else f"{project}/{_tail(p['peerNetwork'])}"
        pid = f"peering:{p.get('name', a + '~' + b)}"
        active = p.get("state", "ACTIVE") == "ACTIVE"
        t.add(Peering(id=pid, a=a, b=b, active=active))
        if active and a in t.networks and b in t.networks:   # subnet routes are exchanged both ways
            for x, y in ((a, b), (b, a)):
                for c in t.networks[y].cidrs:
                    t.route_tables[f"{x}/routes"].routes.append(
                        Route(dest=c, kind=PEERING, target=pid, priority=0, origin="system", name=f"peering:{y}"))

    # instances → interfaces (nic0..n)
    inst_ifaces = {}
    for full, inst in (getattr(inst_store, "instances", {}) or {}).items() if inst_store is not None else []:
        if inst.get("status", "RUNNING") not in ("RUNNING", "PROVISIONING", "STAGING"):
            continue
        proj = full.split("/")[1] if full.startswith("projects/") else project
        if project and proj != project:
            continue
        tags = list((inst.get("tags") or {}).get("items") or [])
        sas = [x.get("email") for x in inst.get("serviceAccounts") or [] if x.get("email")]
        for i, ni in enumerate(inst.get("networkInterfaces") or []):
            region = _region_of_subnet_link(ni.get("subnetwork"))
            sid = f"{proj}/{region}/{_tail(ni.get('subnetwork'))}"
            if sid not in t.subnets:
                t.warnings.append(f"{inst.get('name')}: nic{i} subnetwork {ni.get('subnetwork')} not found")
                continue
            ext = next((a.get("natIP") for a in ni.get("accessConfigs") or [] if a.get("natIP")), None)
            iid = f"{full}/nic{i}"
            t.add(Interface(id=iid, instance=inst.get("name", full), subnet=sid, ip=ni.get("networkIP", ""),
                            public_ip=ext, tags=tags, service_accounts=sas,
                            source_dest_check=not inst.get("canIpForward", False), name=inst.get("name", "")))
            inst_ifaces.setdefault(_tail(full), iid)
            inst_ifaces.setdefault(full, iid)

    for key, r in net_store.routes.items():
        nid = f"{r['project']}/{r['networkName']}"
        if nid not in t.networks:
            continue
        nh = r.get("nextHop") or {}
        if nh.get("nextHopGateway"):
            kind, target = IGW, IGW_ID
        elif nh.get("nextHopInstance"):
            target = inst_ifaces.get(_tail(nh["nextHopInstance"])) or inst_ifaces.get(nh["nextHopInstance"])
            kind = INSTANCE if target else BLACKHOLE
            target = target or nh["nextHopInstance"]
        elif nh.get("nextHopIp"):
            hit = next((i for i in t.interfaces.values() if i.ip == nh["nextHopIp"]), None)
            kind, target = (INSTANCE, hit.id) if hit else (BLACKHOLE, nh["nextHopIp"])
        else:
            kind, target = "unsupported", next(iter(nh.values()), "")
            t.warnings.append(f"route {r['name']}: next hop {target} not simulated")
        t.route_tables[f"{nid}/routes"].routes.append(
            Route(dest=r["destRange"], kind=kind, target=target, priority=int(r.get("priority", 1000)),
                  tags=list(r.get("tags") or []) or None, origin="system" if r.get("_system") else "user", name=r["name"]))
    return t
