"""AWS → netsim: build a Topology from core/vpc_core.py state (read-only).

Accepts the vpc_core store (anything with `_vpc_model`) or the model dict itself.

Mapping:
  VPC                → Network(cidrs=[vpc cidr])
  subnet             → Subnet(route_table, rulesets=[its NACL])
  route table        → RouteTable; an implicit `local` route for the VPC CIDR is always present
                       (real AWS: every route table has it, even a custom one created without it)
  route targets      igw-* → IGW, nat-* → NAT, pcx-* → PEERING, eni-*/i-* → INSTANCE,
                     missing gateway → blackhole (AWS shows the route as "blackhole")
  security group     → RuleSet(STATEFUL_ALLOW), SG references → Peer(group)
  network ACL        → RuleSet(STATELESS_ORDERED), rule number = priority
  instance / ENI     → Interface(groups = rulesets = its SG ids, public IP as vpc_core assigned it
                       — MapPublicIpOnLaunch / AssociatePublicIpAddress / EIP, like EC2).
"""
from __future__ import annotations

try:
    from core.netsim.model import (BLACKHOLE, EGRESS, GATEWAY_ENDPOINT, IGW, INGRESS, INSTANCE, LOCAL, NAT,
                                   PEERING, STATEFUL_ALLOW, STATELESS_ORDERED, Gateway, Interface, Network,
                                   Peer, Peering, Route, RouteTable, Rule, RuleSet, Subnet, Topology, ip_in)
except ImportError:
    from model import (BLACKHOLE, EGRESS, GATEWAY_ENDPOINT, IGW, INGRESS, INSTANCE, LOCAL, NAT,  # type: ignore
                       PEERING, STATEFUL_ALLOW, STATELESS_ORDERED, Gateway, Interface, Network,
                       Peer, Peering, Route, RouteTable, Rule, RuleSet, Subnet, Topology, ip_in)


def primary_eni(instance_id: str) -> str:
    """vpc_core does not materialise an instance's primary ENI; derive a stable eni- id so flow logs,
    route targets and analyzer paths name it the way AWS does."""
    return "eni-" + instance_id[2:19] if instance_id.startswith("i-") else f"eni-{instance_id}"


def _ports(proto: str, lo, hi):
    if proto in ("-1", "all") or lo is None:
        return None
    lo = int(lo)
    hi = int(hi) if hi is not None else lo
    if lo == -1:                     # ICMP "all types"
        return None
    return (lo, hi)


def _sg_ruleset(sg: dict) -> RuleSet:
    rules = []
    for direction, key in ((INGRESS, "ingress"), (EGRESS, "egress")):
        for p in sg.get(key, []):
            proto = str(p.get("protocol", "-1"))
            peers = [Peer.cidr(c) for c in p.get("cidrs", [])] + [Peer("group", g) for g in p.get("sgs", [])]
            if not peers:
                continue
            rules.append(Rule(direction=direction, action="allow", protocol=proto,
                              ports=_ports(proto, p.get("from_port"), p.get("to_port")), peers=peers,
                              name=p.get("rule_id", "")))
    return RuleSet(id=sg["id"], mode=STATEFUL_ALLOW, kind="security-group", name=sg.get("name", ""), rules=rules)


def _nacl_ruleset(n: dict) -> RuleSet:
    rules = []
    for e in n.get("entries", []):
        proto = str(e.get("protocol", "-1"))
        rules.append(Rule(direction=EGRESS if e.get("egress") else INGRESS,
                          action="allow" if e.get("allow") else "deny", protocol=proto,
                          ports=_ports(proto, e.get("from_port"), e.get("to_port")),
                          peers=[Peer.cidr(e.get("cidr", "0.0.0.0/0"))], priority=int(e.get("rule_number", 100)),
                          name=f"#{e.get('rule_number')}"))
    return RuleSet(id=n["id"], mode=STATELESS_ORDERED, kind="network-acl", rules=rules)


def _route_kind(m: dict, target: str):
    t = str(target or "")
    if t == "local":
        return LOCAL, ""
    if t.startswith("igw-"):
        return (IGW, t) if t in m.get("igws", {}) else (BLACKHOLE, t)
    if t.startswith("nat-"):
        return (NAT, t) if t in m.get("nat_gateways", {}) else (BLACKHOLE, t)
    if t.startswith("pcx-"):
        return (PEERING, t) if t in m.get("peering_connections", {}) else (BLACKHOLE, t)
    if t.startswith("eni-"):
        return INSTANCE, t
    if t.startswith("i-"):
        inst = m.get("instances", {}).get(t)
        return (INSTANCE, primary_eni(t)) if inst else (BLACKHOLE, t)
    if t.startswith("vpce-"):
        ep = m.get("vpc_endpoints", {}).get(t)
        return (GATEWAY_ENDPOINT, t) if ep and ep.get("type") == "Gateway" and ep.get("state") == "available" else (BLACKHOLE, t)
    if t == "blackhole":
        return BLACKHOLE, ""
    return None, t                    # tgw-/vgw-/eigw- … not simulated yet


def from_aws(store_or_model) -> Topology:
    m = store_or_model if isinstance(store_or_model, dict) else getattr(store_or_model, "_vpc_model", None) or {}
    t = Topology(cloud="aws")
    vpcs = m.get("vpcs", {})
    for vid, v in vpcs.items():
        t.add(Network(id=vid, cloud="aws", cidrs=[v["cidr"]] + list(v.get("secondary_cidrs", [])),
                      name=(v.get("tags") or {}).get("Name", "")))
        if v.get("igw"):
            t.add(Gateway(id=v["igw"], kind=IGW, network=vid))
    for gid, g in m.get("igws", {}).items():
        if gid not in t.gateways:
            t.add(Gateway(id=gid, kind=IGW, network=g.get("vpc_id") or ""))
        elif not t.gateways[gid].network:
            t.gateways[gid].network = g.get("vpc_id") or ""
    # detached IGWs: AWS keeps the route but it goes blackhole
    for gid, g in t.gateways.items():
        if g.kind == IGW and (not g.network or vpcs.get(g.network, {}).get("igw") != gid):
            g.network, g.available = "", False
    for nid, g in m.get("nat_gateways", {}).items():
        t.add(Gateway(id=nid, kind=NAT, subnet=g.get("subnet_id", ""), network=g.get("vpc_id", ""),
                      public=g.get("connectivity_type", "public") == "public",
                      available=g.get("state", "available") == "available", ip=g.get("private_ip", "")))
    for pid, p in m.get("peering_connections", {}).items():
        t.add(Peering(id=pid, a=p["requester_vpc_id"], b=p["accepter_vpc_id"], active=p.get("status") == "active"))

    for rid, rt in m.get("route_tables", {}).items():
        vpc = vpcs.get(rt.get("vpc_id"), {})
        routes = []
        if vpc:
            routes.append(Route(dest=vpc["cidr"], kind=LOCAL, origin="system", name="local"))
        for r in rt.get("routes", []):
            if r.get("target") == "local":
                continue
            kind, target = _route_kind(m, r.get("target"))
            if kind is None:
                routes.append(Route(dest=r["dest"], kind="unsupported", target=target, name=target))
                t.warnings.append(f"{rid}: route {r['dest']} → {target} target type not simulated")
            else:
                routes.append(Route(dest=r["dest"], kind=kind, target=target, name=str(r.get("target"))))
        t.add(RouteTable(id=rid, routes=routes))

    for sid, sg in m.get("sgs", {}).items():
        t.add(_sg_ruleset(sg))
    for nid, n in m.get("nacls", {}).items():
        t.add(_nacl_ruleset(n))

    bpa_mode = m.get("account", {}).get("vpc_block_public_access", {}).get("internet_gateway_block_mode", "off")
    bpa_exclusions = m.get("account", {}).get("vpc_block_public_access_exclusions", {})

    def _bpa_block(sid: str, vid: str) -> str:
        if bpa_mode == "off":
            return "off"
        if any(x.get("resource_arn") in (sid, vid) for x in bpa_exclusions.values()):
            return "off"
        return "both" if bpa_mode == "block-bidirectional" else "ingress"

    for sid, s in m.get("subnets", {}).items():
        t.add(Subnet(id=sid, network=s["vpc_id"], cidr=s["cidr"], zone=s.get("az", ""),
                     route_table=s.get("route_table"), rulesets=[s["nacl"]] if s.get("nacl") else [],
                     bpa_block=_bpa_block(sid, s["vpc_id"]),
                     name=(s.get("tags") or {}).get("Name", "")))

    eips = {a.get("instance_id"): a.get("public_ip") for a in m.get("addresses", {}).values() if a.get("instance_id")}
    eni_eips = {a.get("network_interface_id"): a.get("public_ip") for a in m.get("addresses", {}).values()
                if a.get("network_interface_id")}
    for iid, inst in m.get("instances", {}).items():
        if inst.get("state") not in ("running", "pending"):
            continue
        sid = inst.get("subnet_id")
        sub = m.get("subnets", {}).get(sid)
        if sub is None:
            continue
        # vpc_core now assigns a public IPv4 exactly per EC2's rule (MapPublicIpOnLaunch /
        # AssociatePublicIpAddress / EIP), so the instance record is the truth
        public = eips.get(iid) or inst.get("public_ip") or None
        ip = inst.get("private_ip", "")
        if not ip_in(ip, sub["cidr"]):
            t.warnings.append(f"{iid}: private IP {ip} is outside its subnet {sub['cidr']} "
                              f"(vpc_core pseudo-IP; allocate from the subnet before enforcing)")
        t.add(Interface(id=primary_eni(iid), instance=iid, subnet=sid, ip=ip, public_ip=public,
                        groups=list(inst.get("sg_ids", [])), rulesets=list(inst.get("sg_ids", [])),
                        source_dest_check=inst.get("source_dest_check", True),
                        name=inst.get("name", "")))
    for eid, e in m.get("enis", {}).items():
        if not e.get("subnet_id") or e.get("subnet_id") not in m.get("subnets", {}):
            continue
        t.add(Interface(id=eid, instance=(e.get("attachment") or {}).get("instance_id", ""), subnet=e["subnet_id"],
                        ip=e.get("private_ip", ""), public_ip=eni_eips.get(eid) or e.get("public_ip") or None,
                        groups=list(e.get("sg_ids", [])), rulesets=list(e.get("sg_ids", [])),
                        source_dest_check=e.get("source_dest_check", True)))
    # INSTANCE route targets that name an eni must exist as interfaces
    for rt in t.route_tables.values():
        for r in rt.routes:
            if r.kind == INSTANCE and r.target not in t.interfaces:
                r.kind = BLACKHOLE
    return t
