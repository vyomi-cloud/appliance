# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""netsim evaluator — the ONE reachability engine for AWS VPC, GCP VPC and Azure VNet.

    reach(topo, src, dst, protocol="tcp", port=22, src_port=None) -> Verdict

`src` / `dst` are an interface id, an interface object, or an IP string (an IP that is not
an interface is "the internet"). The verdict carries `reachable`, a stable blocked `code`,
a human `reason`, and the hop-by-hop trace of every route / gateway / rule decision —
the same shape every cloud's analyzer needs (AWS Reachability Analyzer explanations, GCP
Connectivity Tests trace, Azure Network Watcher IP flow verify / next hop).

This module is also Nano's network behaviour (no packets in a browser), and the offline
enforcer (`enforce.py`) compiles the SAME decisions into nftables — the e2e test asserts
verdict == real packet outcome.

Evaluation order (what a packet really traverses):
  1. route lookup in the source subnet's table: longest prefix, then priority (GCP), then
     user-over-system (Azure UDR); GCP tag-scoped routes only for tagged instances
  2. target semantics: local / peering (active, non-transitive, return route) / igw (attached,
     needs a public IP — else implicit NAT / Azure default outbound) / NAT (available,
     public, its own subnet must route to an igw) / blackhole / appliance (src/dst check)
  3. source egress layers: nic (SG union / NIC NSG) → subnet (NACL at boundary / subnet NSG)
     → network (GCP firewall, target-filtered)
  4. NAT-gateway subnet NACL (AWS: the NAT GW sits in a subnet whose NACL also applies)
  5. destination ingress layers: network → subnet → nic
  6. stateless return path: every NACL the reply crosses, with the client's real ephemeral
     source port (Linux 32768-60999 unless `src_port` pins it)
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

try:
    from core.netsim.model import (BLACKHOLE, EGRESS, GATEWAY_ENDPOINT, IGW, INGRESS, INSTANCE,
                                   LINUX_EPHEMERAL, LOCAL, NAT, PEERING, RFC1918, STATEFUL_ALLOW,
                                   STATEFUL_PRIORITY, STATELESS_ORDERED, UNSUPPORTED, AZURE_LB_IP,
                                   Interface, Route, Topology, ip_in, norm_proto, prefix_len)
except ImportError:                                   # Pyodide: cores are flat on sys.path
    from model import (BLACKHOLE, EGRESS, GATEWAY_ENDPOINT, IGW, INGRESS, INSTANCE,  # type: ignore
                       LINUX_EPHEMERAL, LOCAL, NAT, PEERING, RFC1918, STATEFUL_ALLOW,
                       STATEFUL_PRIORITY, STATELESS_ORDERED, UNSUPPORTED, AZURE_LB_IP,
                       Interface, Route, Topology, ip_in, norm_proto, prefix_len)


@dataclass
class Hop:
    component: str          # route-table | internet-gateway | nat-gateway | peering | security-group |
                            # network-acl | firewall | nsg | appliance | destination
    id: str
    decision: str           # allow | deny | pass
    detail: str = ""
    direction: str = ""


@dataclass
class Verdict:
    reachable: bool = True
    code: str = "REACHABLE"
    reason: str = ""
    path: str = ""          # intra-network | peering | internet-via-igw | internet-via-nat | ...
    blocked_by: str = ""    # id of the route table / rule set / gateway that blocked
    hops: list = field(default_factory=list)

    def add(self, component, id_, decision, detail="", direction=""):
        self.hops.append(Hop(component, id_, decision, detail, direction))

    def block(self, code, reason, by="") -> "Verdict":
        self.reachable, self.code, self.reason, self.blocked_by = False, code, reason, by
        return self

    def to_dict(self) -> dict:
        return asdict(self)

    def explain(self) -> str:
        lines = [f"{'REACHABLE' if self.reachable else 'BLOCKED'} [{self.code}] {self.reason}".rstrip()]
        for h in self.hops:
            lines.append(f"  {h.decision:5} {h.component:16} {h.id:24} {h.direction:7} {h.detail}")
        return "\n".join(lines)


# ── matching ────────────────────────────────────────────────────────────────
def _proto_matches(rule_proto: str, proto: str) -> bool:
    return rule_proto == "all" or rule_proto == proto


def _port_matches(rule, proto: str, port) -> bool:
    if rule.protocol in ("all", "icmp") or proto not in ("tcp", "udp") or rule.ports is None:
        return True
    if port is None:
        return False
    return rule.ports[0] <= int(port) <= rule.ports[1]


def peer_matches(topo: Topology, peer, ip, iface, local_net: str) -> bool:
    """Does the remote endpoint (ip, and iface if it is one of ours) satisfy a selector?"""
    k = peer.kind
    if k == "any":
        return True
    if k == "cidr":
        return ip is not None and ip_in(ip, peer.value)
    if k == "group":
        return iface is not None and peer.value in iface.groups
    if k == "tag":
        return iface is not None and peer.value in iface.tags and topo.network_of(iface).id == local_net
    if k == "service_account":
        return iface is not None and peer.value in iface.service_accounts and topo.network_of(iface).id == local_net
    if k == "service_tag":
        tag = peer.value.lower()
        space = topo.vnet_space(local_net)
        if tag == "virtualnetwork":
            return ip is not None and any(ip_in(ip, c) for c in space)
        if tag == "internet":
            return ip is not None and not any(ip_in(ip, c) for c in space) and not any(ip_in(ip, c) for c in RFC1918)
        if tag == "azureloadbalancer":
            return ip is not None and ip_in(ip, AZURE_LB_IP)
        return False
    return False


def target_applies(topo: Topology, rule, iface: Interface) -> bool:
    if rule.targets is None:
        return True
    net = topo.network_of(iface).id
    return any(peer_matches(topo, t, iface.ip, iface, net) for t in rule.targets)


def _local_matches(topo, rule, iface) -> bool:
    if rule.local is None:
        return True
    net = topo.network_of(iface).id
    return any(peer_matches(topo, p, iface.ip, iface, net) for p in rule.local)


def _src_port_matches(rule, src_port) -> bool:
    if rule.src_ports is None:
        return True
    lo, hi = (src_port, src_port) if src_port is not None else LINUX_EPHEMERAL
    return rule.src_ports[0] <= lo and hi <= rule.src_ports[1]


def rule_matches(topo, rule, direction, proto, port, remote_ip, remote_iface, local_iface, src_port=None) -> bool:
    if rule.direction != direction or not _proto_matches(rule.protocol, proto):
        return False
    if not _port_matches(rule, proto, port) or not _src_port_matches(rule, src_port):
        return False
    net = topo.network_of(local_iface).id
    if not any(peer_matches(topo, p, remote_ip, remote_iface, net) for p in rule.peers):
        return False
    return _local_matches(topo, rule, local_iface)


def _rule_desc(rs, rule) -> str:
    ports = "all" if rule.ports is None else (f"{rule.ports[0]}" if rule.ports[0] == rule.ports[1]
                                               else f"{rule.ports[0]}-{rule.ports[1]}")
    peers = ",".join(p.value or p.kind for p in rule.peers)
    label = rule.name or (f"#{rule.priority}" if rs.mode != STATEFUL_ALLOW else "")
    return f"{label} {rule.action} {rule.protocol}/{ports} {peers}".strip()


def sorted_priority_rules(rs, direction) -> list:
    """Lowest priority number first; on a tie DENY wins (GCP documented behaviour; Azure
    priorities are unique per direction so the tie-break never fires there)."""
    return sorted((r for r in rs.rules if r.direction == direction),
                  key=lambda r: (r.priority, 0 if r.action == "deny" else 1))


def eval_stateful_allow(topo, rulesets, direction, proto, port, remote_ip, remote_iface, iface, src_port=None):
    for rs in rulesets:
        for r in rs.rules:
            if r.action == "allow" and rule_matches(topo, r, direction, proto, port, remote_ip, remote_iface, iface, src_port):
                return True, f"{rs.id}: {_rule_desc(rs, r)}"
    return False, f"no allow rule in {', '.join(rs.id for rs in rulesets)}"


def eval_priority(topo, rs, direction, proto, port, remote_ip, remote_iface, iface, src_port=None):
    for r in sorted_priority_rules(rs, direction):
        if not target_applies(topo, r, iface):
            continue
        if rule_matches(topo, r, direction, proto, port, remote_ip, remote_iface, iface, src_port):
            return r.action == "allow", _rule_desc(rs, r)
    return rs.default_action == "allow", f"no rule matched → default {rs.default_action}"


def stateless_segments(topo, rs, direction, proto, port_range, remote_ip):
    """First-match evaluation of a stateless ordered rule set over a destination-port RANGE.
    Returns [(lo, hi, allowed, rule_desc)] covering the range — this is how the ephemeral
    return path is judged honestly (a NACL that allows 1024-65535 passes, one that allows
    only 49152-65535 fails part of the Linux range)."""
    lo, hi = port_range if port_range else (0, 65535)
    remaining = [(lo, hi)]
    out = []
    rules = sorted((r for r in rs.rules if r.direction == direction), key=lambda r: r.priority)
    for r in rules:
        if not remaining:
            break
        if not _proto_matches(r.protocol, proto):
            continue
        if not any(p.kind == "any" or (p.kind == "cidr" and ip_in(remote_ip, p.value)) for p in r.peers):
            continue
        if r.protocol in ("all", "icmp") or proto not in ("tcp", "udp") or r.ports is None:
            rlo, rhi = 0, 65535
        else:
            rlo, rhi = r.ports
        nxt = []
        for a, b in remaining:
            ia, ib = max(a, rlo), min(b, rhi)
            if ia > ib:
                nxt.append((a, b))
                continue
            out.append((ia, ib, r.action == "allow", _rule_desc(rs, r)))
            if a < ia:
                nxt.append((a, ia - 1))
            if ib < b:
                nxt.append((ib + 1, b))
        remaining = nxt
    for a, b in remaining:
        out.append((a, b, rs.default_action == "allow", "* (implicit) deny"))
    return sorted(out)


def _stateless_check(topo, rs, direction, proto, port_range, remote_ip):
    segs = stateless_segments(topo, rs, direction, proto, port_range, remote_ip)
    bad = [s for s in segs if not s[2]]
    if not bad:
        return True, "; ".join(sorted({s[3] for s in segs}))
    if len(bad) == len(segs):
        return False, bad[0][3]
    spans = ", ".join(f"{a}-{b}" for a, b, _, _ in bad)
    return False, f"ports {spans} of {port_range[0]}-{port_range[1]} denied by {bad[0][3]}"


# ── routing ─────────────────────────────────────────────────────────────────
def route_lookup(topo: Topology, subnet, dst_ip: str, iface: Interface | None = None):
    """Longest-prefix match → priority → user-over-system. GCP tag-scoped routes apply only
    to instances carrying one of the tags."""
    rt = topo.route_tables.get(subnet.route_table or "")
    if rt is None:
        return None
    cands = []
    for r in rt.routes:
        if not ip_in(dst_ip, r.dest):
            continue
        if r.tags and (iface is None or not set(r.tags) & set(iface.tags)):
            continue
        cands.append(r)
    if not cands:
        return None
    cands.sort(key=lambda r: (-prefix_len(r.dest), r.priority, 0 if r.origin == "user" else 1))
    return cands[0]


def _igw_ok(topo, gw_id, network_id):
    g = topo.gateways.get(gw_id)
    return g is not None and g.kind == IGW and g.available and (not g.network or g.network == network_id)


def internet_egress(topo: Topology, iface: Interface, route, dst_ip: str):
    """(ok, path, code, reason, nat_subnet) for a route whose target leads to the internet."""
    sub = topo.subnet_of(iface)
    net = topo.network_of(iface)
    if route.kind == IGW:
        if sub.bpa_block == "both":
            return (False, "", "BLOCKED_PUBLIC_ACCESS",
                    f"VPC Block Public Access blocks internet gateway traffic for {sub.id}", None)
        if not _igw_ok(topo, route.target, net.id):
            return False, "", "IGW_DETACHED", f"internet gateway {route.target} is not attached to {net.id} (blackhole)", None
        if iface.public_ip:
            return True, "internet-via-igw", "", f"public IP {iface.public_ip}", None
        if sub.nat and topo.gateways.get(sub.nat) and topo.gateways[sub.nat].available:
            return True, "internet-via-nat", "", f"implicit NAT {sub.nat}", None
        if sub.default_outbound:
            return True, "internet-via-default-outbound", "", "default outbound access", None
        return False, "", "NO_PUBLIC_IP", (f"{iface.id} has no public IP and its subnet has no NAT — an internet "
                                           f"gateway only forwards for interfaces with a public address"), None
    if route.kind == NAT:
        g = topo.gateways.get(route.target)
        if g is None or not g.available or g.kind != NAT:
            return False, "", "NAT_UNAVAILABLE", f"NAT gateway {route.target} does not exist / is not available (blackhole)", None
        if not g.public:
            return False, "", "NAT_PRIVATE", f"{g.id} is a private NAT gateway — it cannot reach the internet", None
        gsub = topo.subnets.get(g.subnet)
        if gsub is None:
            return False, "", "NAT_UNAVAILABLE", f"NAT gateway {g.id} has no subnet", None
        r2 = route_lookup(topo, gsub, dst_ip)
        if r2 is None or r2.kind != IGW or not _igw_ok(topo, r2.target, gsub.network):
            return False, "", "NAT_NO_IGW_ROUTE", (f"NAT gateway {g.id} sits in {gsub.id}, whose route table has no "
                                                   f"route to an attached internet gateway"), None
        return True, "internet-via-nat", "", f"NAT gateway {g.id} in {gsub.id} → {r2.target}", gsub
    return False, "", "NO_ROUTE", "not an internet route", None


def internet_egress_mode(topo: Topology, iface: Interface, dst_ip: str = "198.51.100.1"):
    """How (if at all) this interface reaches the internet — used by the enforcer to decide
    where masquerade is legitimate. Returns (path, nat_subnet) or (None, None)."""
    r = route_lookup(topo, topo.subnet_of(iface), dst_ip, iface)
    if r is None or r.kind not in (IGW, NAT):
        return None, None
    ok, path, _, _, nsub = internet_egress(topo, iface, r, dst_ip)
    return (path, nsub) if ok else (None, None)


# ── security layers ─────────────────────────────────────────────────────────
_KIND_COMPONENT = {"security-group": "security-group", "network-acl": "network-acl",
                   "firewall": "firewall", "nsg": "nsg"}


def _layers(topo, iface, direction, proto, port, remote_ip, remote_iface, crossing, v, src_port=None) -> bool:
    sub = topo.subnet_of(iface)
    net = topo.network_of(iface)
    levels = [("nic", iface.rulesets), ("subnet", sub.rulesets), ("network", net.rulesets)]
    if direction == INGRESS:
        levels.reverse()
    for _level, ids in levels:
        rss = [topo.rulesets[i] for i in ids if i in topo.rulesets]
        sgs = [rs for rs in rss if rs.mode == STATEFUL_ALLOW]
        if sgs:
            ok, desc = eval_stateful_allow(topo, sgs, direction, proto, port, remote_ip, remote_iface, iface, src_port)
            comp = sgs[0].kind or "security-group"
            v.add(comp, ",".join(rs.id for rs in sgs), "allow" if ok else "deny", desc, direction)
            if not ok:
                v.block(f"{'INGRESS' if direction == INGRESS else 'EGRESS'}_DENIED",
                        f"{comp} on {iface.id} denies {direction} {proto}/{port}", ",".join(rs.id for rs in sgs))
                return False
        for rs in rss:
            if rs.mode == STATEFUL_PRIORITY:
                ok, desc = eval_priority(topo, rs, direction, proto, port, remote_ip, remote_iface, iface, src_port)
                v.add(rs.kind or "firewall", rs.id, "allow" if ok else "deny", desc, direction)
                if not ok:
                    v.block(f"{'INGRESS' if direction == INGRESS else 'EGRESS'}_DENIED",
                            f"{rs.kind or 'firewall'} {rs.id} denies {direction} {proto}/{port} ({desc})", rs.id)
                    return False
            elif rs.mode == STATELESS_ORDERED and crossing:
                ok, desc = _stateless_check(topo, rs, direction, proto, (port, port) if port is not None else None, remote_ip)
                v.add(rs.kind or "network-acl", rs.id, "allow" if ok else "deny", desc, direction)
                if not ok:
                    v.block(f"ACL_{'INGRESS' if direction == INGRESS else 'EGRESS'}_DENIED",
                            f"{rs.kind or 'network-acl'} {rs.id} on {sub.id} denies {direction} {proto}/{port} ({desc})", rs.id)
                    return False
    return True


def _acl_hop(topo, subnet, direction, proto, port_range, remote_ip, v, code, label) -> bool:
    """Stateless subnet ACLs on one boundary crossing (used for return paths + NAT subnet)."""
    for rid in subnet.rulesets:
        rs = topo.rulesets.get(rid)
        if rs is None or rs.mode != STATELESS_ORDERED:
            continue
        ok, desc = _stateless_check(topo, rs, direction, proto, port_range, remote_ip)
        v.add(rs.kind or "network-acl", rs.id, "allow" if ok else "deny", f"{label}: {desc}", direction)
        if not ok:
            pr = f"{port_range[0]}-{port_range[1]}" if port_range else "all"
            v.block(code, f"{rs.kind or 'network-acl'} {rs.id} on {subnet.id} denies {label} ({direction} {proto} "
                          f"ports {pr}: {desc}) — stateless rules must allow the reply explicitly", rs.id)
            return False
    return True


# ── public entry ────────────────────────────────────────────────────────────
def _as_iface(topo, x):
    if isinstance(x, Interface):
        return x
    if isinstance(x, str):
        if x in topo.interfaces:
            return topo.interfaces[x]
        i = topo.iface_by_ip(x)
        if i is not None and i.ip == x:
            return i
    return None


def reach(topo: Topology, src, dst, protocol: str = "tcp", port=None, src_port=None, _depth: int = 0) -> Verdict:
    proto = norm_proto(protocol)
    if proto not in ("tcp", "udp"):
        port = None
    eph = (int(src_port), int(src_port)) if src_port else LINUX_EPHEMERAL
    if proto not in ("tcp", "udp"):
        eph = None
    v = Verdict()
    s = _as_iface(topo, src)
    if s is None:
        return _reach_from_external(topo, str(src), dst, proto, port, eph, src_port, v)

    if isinstance(dst, Interface):
        d, dst_ip = dst, dst.ip
    elif dst in topo.interfaces:
        d = topo.interfaces[dst]
        dst_ip = d.ip
    else:
        dst_ip = str(dst)
        d = topo.iface_by_ip(dst_ip)
        if d is not None and d.ip != dst_ip:
            # addressed by its PUBLIC IP from inside → hairpin through the internet path
            d = None
    S, N = topo.subnet_of(s), topo.network_of(s)
    nat_subnet = None

    # 1. route
    if d is not None and d.subnet == s.subnet:
        route = Route(S.cidr, LOCAL, origin="system", name="subnet-local")
    else:
        route = route_lookup(topo, S, dst_ip, s)
    if route is None:
        v.add("route-table", S.route_table or "-", "deny", f"no route to {dst_ip}")
        return v.block("NO_ROUTE", f"route table {S.route_table} of {S.id} has no route to {dst_ip}", S.route_table or "")
    v.add("route-table", S.route_table or "-", "pass", f"{dst_ip} → {route.dest} via {route.kind} {route.target}".rstrip())

    # 2. target semantics
    if route.kind == LOCAL:
        if d is None:
            return v.block("NO_DESTINATION", f"no interface at {dst_ip} in {N.id}")
        if topo.network_of(d).id != N.id:
            return v.block("NO_DESTINATION", f"{dst_ip} is not in {N.id} (local route mismatch)", S.route_table or "")
        v.path = "intra-subnet" if d.subnet == s.subnet else "intra-network"
    elif route.kind == PEERING:
        p = topo.peerings.get(route.target)
        if p is None or N.id not in (p.a, p.b):
            return v.block("BLACKHOLE_ROUTE", f"peering {route.target} does not exist (blackhole)", route.target)
        if not p.active:
            v.add("peering", p.id, "deny", "not active")
            return v.block("PEERING_INACTIVE", f"peering {p.id} is not active", p.id)
        other = topo.networks[p.b if p.a == N.id else p.a]
        if not any(ip_in(dst_ip, c) for c in other.cidrs):
            v.add("peering", p.id, "deny", f"{dst_ip} is not in {other.id} {other.cidrs}")
            return v.block("PEERING_NOT_TRANSITIVE", f"{dst_ip} is beyond {other.id}; peering is not transitive", p.id)
        if d is None:
            return v.block("NO_DESTINATION", f"no interface at {dst_ip} in {other.id}")
        back = route_lookup(topo, topo.subnet_of(d), s.ip, d)
        if back is None or back.kind != PEERING or back.target != p.id:
            v.add("peering", p.id, "deny", f"{topo.subnet_of(d).route_table} has no route back to {s.ip} via {p.id}")
            return v.block("PEERING_NO_RETURN_ROUTE", f"return route missing: {topo.subnet_of(d).id}'s route table "
                                                      f"does not route {s.ip} via {p.id}", topo.subnet_of(d).route_table or "")
        v.add("peering", p.id, "pass", f"{N.id} → {other.id}")
        v.path = "peering"
    elif route.kind in (IGW, NAT):
        if topo.is_internal(dst_ip):
            return v.block("PRIVATE_DEST_VIA_GATEWAY",
                           f"{dst_ip} is a private address in another network; it is not routable via {route.target}", route.target)
        ok, path, code, why, nat_subnet = internet_egress(topo, s, route, dst_ip)
        comp = "internet-gateway" if route.kind == IGW else "nat-gateway"
        v.add(comp, route.target, "pass" if ok else "deny", why)
        if not ok:
            return v.block(code, why, route.target)
        v.path = path
        d = None
    elif route.kind == GATEWAY_ENDPOINT:
        # AWS Gateway VPC Endpoint (S3/DynamoDB): routed over the AWS backbone, never the
        # internet/NAT — no public IP needed, no destination interface, SG/NACL still evaluated.
        v.add("vpc-endpoint", route.target, "pass", f"gateway endpoint {route.target}")
        v.path = "via-gateway-endpoint"
        d = None
    elif route.kind == BLACKHOLE:
        return v.block("BLACKHOLE_ROUTE", f"route {route.dest} is a blackhole ({route.name or route.target or 'None'})",
                       S.route_table or "")
    elif route.kind == INSTANCE:
        return _via_appliance(topo, s, d, dst_ip, route, proto, port, src_port, eph, v, _depth)
    else:
        return v.block("UNSUPPORTED_TARGET", f"route target {route.target or route.name} is not simulated", S.route_table or "")

    crossing = d is None or d.subnet != s.subnet
    # 3. source egress
    if not _layers(topo, s, EGRESS, proto, port, dst_ip, d, crossing, v, src_port):
        return v
    # 4. NAT gateway's own subnet (AWS)
    if nat_subnet is not None:
        if not _acl_hop(topo, nat_subnet, INGRESS, proto, (port, port) if port else None, s.ip, v,
                        "ACL_INGRESS_DENIED", "into NAT subnet"):
            return v
        if not _acl_hop(topo, nat_subnet, EGRESS, proto, (port, port) if port else None, dst_ip, v,
                        "ACL_EGRESS_DENIED", "NAT subnet to internet"):
            return v
    # 5. destination ingress
    if d is not None:
        if not _layers(topo, d, INGRESS, proto, port, s.ip, s, crossing, v, src_port):
            return v
        v.add("destination", d.id, "allow", f"{d.ip}")
    else:
        v.add("destination", dst_ip, "allow", "internet host")
    # 6. stateless return path
    if crossing:
        if d is not None:
            if not _acl_hop(topo, topo.subnet_of(d), EGRESS, proto, eph, s.ip, v, "ACL_RETURN_DENIED", "reply leaving destination subnet"):
                return v
            if not _acl_hop(topo, S, INGRESS, proto, eph, d.ip, v, "ACL_RETURN_DENIED", "reply entering source subnet"):
                return v
        else:
            if nat_subnet is not None:
                if not _acl_hop(topo, nat_subnet, INGRESS, proto, eph, dst_ip, v, "ACL_RETURN_DENIED", "reply into NAT subnet"):
                    return v
                if not _acl_hop(topo, nat_subnet, EGRESS, proto, eph, s.ip, v, "ACL_RETURN_DENIED", "reply from NAT subnet"):
                    return v
            if not _acl_hop(topo, S, INGRESS, proto, eph, dst_ip, v, "ACL_RETURN_DENIED", "reply entering source subnet"):
                return v
    v.reason = v.reason or f"{s.ip} → {dst_ip} {proto}/{port if port is not None else '*'} via {v.path}"
    return v


def _via_appliance(topo, s, d, dst_ip, route, proto, port, src_port, eph, v, depth):
    app = topo.interfaces.get(route.target)
    if app is None:
        return v.block("BLACKHOLE_ROUTE", f"appliance {route.target} does not exist (blackhole)", route.target)
    if app.source_dest_check:
        v.add("appliance", app.id, "deny", "source/destination check is enabled")
        return v.block("SOURCE_DEST_CHECK", f"{app.id} drops forwarded traffic: source/destination check is enabled", app.id)
    if depth >= 3:
        return v.block("ROUTING_LOOP", "appliance chain too deep", app.id)
    crossing = app.subnet != s.subnet
    if not _layers(topo, s, EGRESS, proto, port, dst_ip, d, crossing, v, src_port):
        return v
    if not _layers(topo, app, INGRESS, proto, port, s.ip, s, crossing, v, src_port):
        return v
    v.add("appliance", app.id, "pass", "forwarded by the appliance (second leg evaluated from the appliance)")
    leg2 = reach(topo, app, d if d is not None else dst_ip, proto, port, src_port, depth + 1)
    v.hops.extend(leg2.hops)
    if not leg2.reachable:
        return v.block(leg2.code, f"after appliance {app.id}: {leg2.reason}", leg2.blocked_by)
    v.path = f"via-appliance:{leg2.path}"
    return v


def _reach_from_external(topo, src_ip, dst, proto, port, eph, src_port, v):
    """Internet host → an interface. Only a public IP is reachable from outside."""
    d = topo.interfaces.get(dst) if isinstance(dst, str) and dst in topo.interfaces else (
        dst if isinstance(dst, Interface) else topo.iface_by_ip(str(dst)))
    dst_ip = dst.ip if isinstance(dst, Interface) else (d.public_ip if isinstance(dst, str) and dst in topo.interfaces else str(dst))
    if d is None:
        return v.block("NO_DESTINATION", f"no interface with address {dst_ip}")
    if not d.public_ip:
        return v.block("NOT_PUBLIC", f"{d.id} has no public IP; private addresses are not routable from the internet", d.id)
    if dst_ip == d.ip:
        return v.block("NOT_PUBLIC", f"{dst_ip} is private; address the public IP {d.public_ip}", d.id)
    sub, net = topo.subnet_of(d), topo.network_of(d)
    if sub.bpa_block in ("both", "ingress"):
        return v.block("BLOCKED_PUBLIC_ACCESS", f"VPC Block Public Access blocks inbound internet gateway traffic for {sub.id}", sub.id)
    back = route_lookup(topo, sub, src_ip, d)
    if back is None or back.kind != IGW or not _igw_ok(topo, back.target, net.id):
        v.add("route-table", sub.route_table or "-", "deny", f"no internet-gateway route back to {src_ip}")
        return v.block("NO_ROUTE", f"{sub.id} has no route to an attached internet gateway for the reply", sub.route_table or "")
    v.add("internet-gateway", back.target, "pass", f"{d.public_ip} → {d.ip}")
    if not _layers(topo, d, INGRESS, proto, port, src_ip, None, True, v, src_port):
        return v
    if not _acl_hop(topo, sub, EGRESS, proto, eph, src_ip, v, "ACL_RETURN_DENIED", "reply leaving destination subnet"):
        return v
    v.add("destination", d.id, "allow", d.ip)
    v.path = "inbound-via-igw"
    v.reason = f"{src_ip} → {d.public_ip} ({d.ip}) {proto}/{port}"
    return v
