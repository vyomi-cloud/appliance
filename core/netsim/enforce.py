"""netsim offline enforcer — compile a Topology into REAL packet behaviour on the Docker host.

Two outputs:
  (a) one Docker bridge network per subnet, with the subnet's real CIDR, gateway = .1 (the
      VPC router address on all three clouds), Docker's own masquerade OFF — instances are
      started with `--network <subnet net> --ip <iface ip>`
  (b) one nftables table per space, `table inet vyomi_<space>`, applied atomically
      (`nft -f`: create-if-missing + delete + full redefine in ONE transaction → idempotent,
      no window with half a ruleset), from a sidecar in the host network namespace
      (`--network host --cap-add NET_ADMIN`, image docker/netd/)

Forward-chain pipeline (priority filter-10, so it runs before Docker's iptables-nft filter; our
`drop` is final, our `accept` only means "no objection"):

    not our space            → accept (leave other traffic alone)
    management cidrs         → accept (appliance console / SSH bridge; documented exception)
    stateless subnet ACLs    → per-subnet chains acl_N_out / acl_N_in on EVERY packet, both ways,
                               only when crossing the subnet boundary (AWS NACL semantics — a reply
                               needs its own ephemeral-port allow, nothing remembers the request);
                               plus the NAT gateway subnet's ACL for flows NATed through it
    ct established,related   → accept (this is what makes SG / firewall / NSG stateful)
    new from outside space   → drop (no public-IP DNAT yet → nothing is reachable from "internet")
    route chain per nic      → longest-prefix / priority order compiled from the SAME helpers the
                               evaluator uses: local / peering (+return route) / igw (public IP) /
                               NAT (functional) → continue; blackhole / no route → drop
    egress chain per nic     → nic layer (SG union / NIC NSG) → subnet layer (subnet NSG) →
                               network layer (GCP firewall, target-filtered)
    ingress chain per nic    → network → subnet → nic
    pass                     → per-flow counters (flow logs) + accept

Postrouting: masquerade ONLY for interfaces whose internet path is real (public IP behind an IGW,
NAT gateway, Cloud NAT, Azure default outbound) and only toward non-space destinations.

Docker coexistence: Docker drops traffic between different bridges (`! -i br -o br -j DROP`
in its DOCKER chain). The netd adds `DOCKER-USER -s/-d <space cidr> -j ACCEPT` (comment
vyomi_<space>) so the inter-subnet decision is ours alone.
"""
from __future__ import annotations

import hashlib
import ipaddress
import re
import subprocess
from dataclasses import dataclass, field

try:
    from core.netsim import evaluate as ev
    from core.netsim.model import (EGRESS, IGW, INGRESS, INSTANCE, LOCAL, NAT, PEERING, RFC1918, AZURE_LB_IP,
                                   STATEFUL_ALLOW, STATEFUL_PRIORITY, STATELESS_ORDERED, Topology, cidr_covers,
                                   ip_in, prefix_len)
except ImportError:
    import evaluate as ev  # type: ignore
    from model import (EGRESS, IGW, INGRESS, INSTANCE, LOCAL, NAT, PEERING, RFC1918, AZURE_LB_IP,  # type: ignore
                       STATEFUL_ALLOW, STATEFUL_PRIORITY, STATELESS_ORDERED, Topology, cidr_covers,
                       ip_in, prefix_len)

FLOW_KEY = "ip saddr . ip daddr . meta l4proto . th sport . th dport"
PUBLIC_MARK = "0x00007653"      # conntrack mark: connection entered through an interface's public IP


def table_name(space: str) -> str:
    return "vyomi_" + re.sub(r"[^A-Za-z0-9_]", "_", space)[:40]


def _collapse(prefixes) -> list:
    nets = []
    for p in prefixes:
        try:
            nets.append(ipaddress.ip_network(p, strict=False))
        except ValueError:
            continue
    return [str(n) for n in ipaddress.collapse_addresses(n for n in nets if n.version == 4)]


def _set(prefixes) -> str:
    c = _collapse(prefixes)
    return c[0] if len(c) == 1 else "{ " + ", ".join(c) + " }"


def _dst(cidr: str) -> str:
    return "" if cidr == "0.0.0.0/0" else f"ip daddr {cidr} "


def _q(s: str) -> str:
    return '"' + str(s).replace('"', "'")[:120] + '"'


@dataclass
class Plan:
    table: str
    nft: str
    networks: list = field(default_factory=list)       # [{name, subnet, cidr, gateway, bridge}]
    docker_user: list = field(default_factory=list)    # cidrs accepted in DOCKER-USER
    warnings: list = field(default_factory=list)


class _Compiler:
    def __init__(self, topo: Topology, space: str, mgmt_cidrs=(), inbound_dnat: bool = False):
        self.t = topo
        self.inbound_dnat = inbound_dnat
        self.space = space
        self.mgmt = list(mgmt_cidrs)
        self.chains: dict = {}         # name -> [rule lines]
        self.warnings = list(topo.warnings)
        self.ifaces = list(topo.interfaces.values())
        self.idx = {i.id: n for n, i in enumerate(self.ifaces)}
        self.sidx = {s: n for n, s in enumerate(topo.subnets)}
        # `space` = what Docker owns here: subnets that have at least one interface (a bridge each).
        # `model` = every address the topology knows (VPC/VNet space, unused subnets, peers): it is
        # "internal" for routing decisions but has no bridge, so it must never leak to the host route.
        used = {i.subnet for i in self.ifaces}
        self.enforced = [s for s in topo.subnets.values() if s.id in used]
        self.space_cidrs = _collapse([s.cidr for s in self.enforced])
        self.model_cidrs = _collapse(topo.all_cidrs())

    # ── selectors → nft address matches ──
    def _addr_alts(self, field_, peers, local_net) -> list | None:
        """OR-list of address matches for the remote side; [] = match anything; None = can match nothing."""
        prefixes, alts = [], []
        for p in peers:
            if p.kind == "any":
                return []
            if p.kind == "cidr":
                prefixes.append(p.value)
            elif p.kind == "group":
                prefixes += [f"{i.ip}/32" for i in self.ifaces if p.value in i.groups]
            elif p.kind in ("tag", "service_account"):
                attr = "tags" if p.kind == "tag" else "service_accounts"
                prefixes += [f"{i.ip}/32" for i in self.ifaces
                             if p.value in getattr(i, attr) and self.t.network_of(i).id == local_net]
            elif p.kind == "service_tag":
                tag = p.value.lower()
                if tag == "virtualnetwork":
                    prefixes += self.t.vnet_space(local_net)
                elif tag == "internet":
                    alts.append(f"{field_} != {_set(self.t.vnet_space(local_net) + list(RFC1918))}")
                elif tag == "azureloadbalancer":
                    prefixes.append(AZURE_LB_IP)
        if prefixes:
            alts.insert(0, f"{field_} {_set(prefixes)}")
        return alts or None

    @staticmethod
    def _l4(rule) -> str | None:
        p = rule.protocol
        if p == "all":
            return ""
        if p in ("tcp", "udp"):
            s = f"meta l4proto {p}"
            if rule.ports is not None and rule.ports != (0, 65535):
                lo, hi = rule.ports
                s += f" th dport {lo}" if lo == hi else f" th dport {lo}-{hi}"
            if rule.src_ports is not None and rule.src_ports != (0, 65535):
                lo, hi = rule.src_ports
                s += f" th sport {lo}" if lo == hi else f" th sport {lo}-{hi}"
            return s
        if p == "icmp":
            return "meta l4proto icmp"
        if p.isdigit():
            return f"meta l4proto {p}"
        return None

    def _rule_lines(self, rule, field_, local_net, verdict, comment) -> list:
        l4 = self._l4(rule)
        if l4 is None:
            self.warnings.append(f"protocol {rule.protocol} not enforceable; rule {comment} skipped")
            return []
        alts = self._addr_alts(field_, rule.peers, local_net)
        if alts is None:
            return []
        alts = alts or [""]
        return [" ".join(x for x in (a, l4, "counter", verdict, f"comment {_q(comment)}") if x) for a in alts]

    # ── stateless subnet ACLs ──
    def _acl_chain(self, sub, direction) -> str | None:
        rss = [self.t.rulesets[r] for r in sub.rulesets
               if r in self.t.rulesets and self.t.rulesets[r].mode == STATELESS_ORDERED]
        if not rss:
            return None
        name = f"acl_s{self.sidx[sub.id]}_{'in' if direction == INGRESS else 'out'}"
        if name in self.chains:
            return name
        field_ = "ip saddr" if direction == INGRESS else "ip daddr"
        lines = []
        for rs in rss:
            body = []
            for r in sorted((r for r in rs.rules if r.direction == direction), key=lambda r: r.priority):
                body += self._rule_lines(r, field_, sub.network, "return" if r.action == "allow" else "goto deny",
                                         f"{rs.id} {direction} #{r.priority}")
            body.append(f"counter goto deny comment {_q(rs.id + ' ' + direction + ' * implicit deny')}")
            if len(rss) == 1:
                lines = body
            else:
                sub_name = f"{name}_{len(lines)}"
                self.chains[sub_name] = body
                lines.append(f"jump {sub_name}")
        self.chains[name] = lines
        return name

    # ── routes ──
    def _route_chain(self, iface) -> str:
        n = self.idx[iface.id]
        name = f"rt_i{n}"
        t = self.t
        S = t.subnet_of(iface)
        N = t.network_of(iface)
        lines = [f"ip daddr {S.cidr} return comment {_q('subnet-local')}"]
        rt = t.route_tables.get(S.route_table or "")
        routes = []
        if rt:
            routes = [r for r in rt.routes if not (r.tags and not set(r.tags) & set(iface.tags))]
            routes.sort(key=lambda r: (-prefix_len(r.dest), r.priority, 0 if r.origin == "user" else 1))
        for r in routes:
            c = f"{S.route_table}: {r.dest} → {r.kind} {r.target}"
            if r.kind == LOCAL:
                lines.append(f"{_dst(r.dest)}return comment {_q(c)}")
            elif r.kind == PEERING:
                p = t.peerings.get(r.target)
                if p is not None and p.active and N.id in (p.a, p.b):
                    other = p.b if p.a == N.id else p.a
                    for T in (s for s in t.subnets.values() if s.network == other):
                        if not cidr_covers(r.dest, T.cidr):
                            continue
                        back = ev.route_lookup(t, T, iface.ip)
                        if back is not None and back.kind == PEERING and back.target == p.id:
                            lines.append(f"ip daddr {T.cidr} return comment {_q(c + ' (return route ok)')}")
                lines.append(f"{_dst(r.dest)}counter goto deny comment {_q(c + ' (non-transitive / no return route)')}")
            elif r.kind in (IGW, NAT):
                net = ipaddress.ip_network(r.dest, strict=False)
                sample = "198.51.100.1" if net.prefixlen == 0 else str(net.network_address + (1 if net.num_addresses > 1 else 0))
                ok, path, code, why, _ = ev.internet_egress(t, iface, r, sample)
                if ok:
                    lines.append(f"{_dst(r.dest)}ip daddr @model counter goto deny comment {_q(c + ' private dest via gateway')}")
                    lines.append(f"{_dst(r.dest)}return comment {_q(c + ' ' + path)}")
                else:
                    lines.append(f"{_dst(r.dest)}counter goto deny comment {_q(c + ' ' + code)}")
            else:
                if r.kind == INSTANCE:
                    self.warnings.append(f"{S.route_table}: appliance route {r.dest} → {r.target} is evaluated "
                                         f"but not enforced (enforced as drop)")
                lines.append(f"{_dst(r.dest)}counter goto deny comment {_q(c)}")
        lines.append(f"counter goto deny comment {_q('no route')}")
        self.chains[name] = lines
        return name

    # ── stateful layers ──
    def _layer_chains(self, iface, direction) -> str:
        n = self.idx[iface.id]
        d = "in" if direction == INGRESS else "eg"
        name = f"{d}_i{n}"
        t = self.t
        S, N = t.subnet_of(iface), t.network_of(iface)
        field_ = "ip saddr" if direction == INGRESS else "ip daddr"
        levels = [iface.rulesets, S.rulesets, N.rulesets]
        if direction == INGRESS:
            levels.reverse()
        lines = []
        for k, ids in enumerate(levels):
            rss = [t.rulesets[i] for i in ids if i in t.rulesets]
            sgs = [rs for rs in rss if rs.mode == STATEFUL_ALLOW]
            if sgs:
                cname = f"{d}_i{n}_sg"
                body = []
                for rs in sgs:
                    for r in rs.rules:
                        if r.direction == direction and r.action == "allow":
                            body += self._rule_lines(r, field_, N.id, "return", f"{rs.id} {r.name}")
                body.append(f"counter goto deny comment {_q(','.join(rs.id for rs in sgs) + ' no allow rule')}")
                self.chains[cname] = body
                lines.append(f"jump {cname}")
            for j, rs in enumerate(r for r in rss if r.mode == STATEFUL_PRIORITY):
                cname = f"{d}_i{n}_l{k}_{j}"
                body = []
                for r in ev.sorted_priority_rules(rs, direction):
                    if not ev.target_applies(t, r, iface) or not ev._local_matches(t, r, iface):
                        continue
                    body += self._rule_lines(r, field_, N.id, "return" if r.action == "allow" else "goto deny",
                                             f"{rs.id} {r.name} p{r.priority}")
                body.append(f"counter {'return' if rs.default_action == 'allow' else 'goto deny'} "
                            f"comment {_q(rs.id + ' default')}")
                self.chains[cname] = body
                lines.append(f"jump {cname}")
        self.chains[name] = lines
        return name

    def compile(self) -> Plan:
        t = self.t
        tbl = table_name(self.space)
        fwd = ["ip saddr != @space ip daddr != @space accept",
               # Docker published ports (the console's SSH port-publish path) arrive DNAT'd by Docker:
               # management access, like the cloud consoles' own connect paths — not tenant traffic
               f"ct mark != {PUBLIC_MARK} ct status dnat accept comment \"docker published port (management)\""]
        if self.mgmt:
            fwd += ["ip saddr @mgmt accept comment \"management (console/ssh bridge)\"",
                    "ip daddr @mgmt accept comment \"management replies\""]
        # stateless ACLs at subnet boundaries
        for s in self.enforced:
            o, i = self._acl_chain(s, EGRESS), self._acl_chain(s, INGRESS)
            if o:
                fwd.append(f"ip saddr {s.cidr} ip daddr != {s.cidr} jump {o}")
            if i:
                fwd.append(f"ip daddr {s.cidr} ip saddr != {s.cidr} jump {i}")
        # NAT gateway subnet ACLs for flows NATed through it (AWS)
        masq, dnat = [], []
        for iface in self.ifaces:
            path, nsub = ev.internet_egress_mode(t, iface)
            if path:
                masq.append(iface.ip)
            if self.inbound_dnat and path == "internet-via-igw" and iface.public_ip:
                dnat.append((iface.public_ip, iface.ip, iface.id))
            if nsub is not None:
                gi, go = self._acl_chain(nsub, INGRESS), self._acl_chain(nsub, EGRESS)
                for ch in (gi, go):
                    if ch:
                        fwd.append(f"ip saddr {iface.ip} ip daddr != @model jump {ch} comment {_q('via NAT subnet ' + nsub.id)}")
                        fwd.append(f"ip daddr {iface.ip} ip saddr != @model jump {ch} comment {_q('reply via NAT subnet ' + nsub.id)}")
        fwd += ["ct state established,related goto pass",
                "ct state invalid counter drop",
                f"ip saddr != @space ct mark != {PUBLIC_MARK} counter goto deny comment \"inbound from outside the space, not to a public IP\"",
                "ip daddr @model ip daddr != @space counter goto deny comment \"internal address with no interface\""]
        for iface in self.ifaces:
            fwd.append(f"ip saddr {iface.ip} jump {self._route_chain(iface)} comment {_q(iface.id + ' routes')}")
        for iface in self.ifaces:
            fwd.append(f"ip saddr {iface.ip} jump {self._layer_chains(iface, EGRESS)} comment {_q(iface.id + ' egress')}")
            fwd.append(f"ip daddr {iface.ip} jump {self._layer_chains(iface, INGRESS)} comment {_q(iface.id + ' ingress')}")
        if self.ifaces:
            fwd.append("ip saddr @space ip saddr != @ifaces counter goto deny comment \"unknown source in space\"")
        fwd.append("goto pass")

        out = [f"table inet {tbl}", f"delete table inet {tbl}", f"table inet {tbl} {{"]
        out.append(f"  set space {{ type ipv4_addr; flags interval; elements = {{ {', '.join(self.space_cidrs) or '0.0.0.0/32'} }} }}")
        out.append(f"  set model {{ type ipv4_addr; flags interval; elements = {{ {', '.join(self.model_cidrs) or '0.0.0.0/32'} }} }}")
        ips = sorted({i.ip for i in self.ifaces if i.ip})
        out.append(f"  set ifaces {{ type ipv4_addr; {'elements = { ' + ', '.join(ips) + ' }' if ips else ''} }}")
        if self.mgmt:
            out.append(f"  set mgmt {{ type ipv4_addr; flags interval; elements = {{ {', '.join(_collapse(self.mgmt))} }} }}")
        for s in ("flows", "rejects"):
            out.append(f"  set {s} {{ typeof {FLOW_KEY}; flags dynamic,timeout; timeout 15m; size 65535; counter; }}")
        out.append("  chain forward {\n    type filter hook forward priority filter - 10; policy accept;")
        out += [f"    {line}" for line in fwd]
        out.append("  }")
        out.append("  chain pass {\n    meta l4proto { tcp, udp } update @flows { " + FLOW_KEY + " }\n    accept\n  }")
        out.append("  chain deny {\n    meta l4proto { tcp, udp } update @rejects { " + FLOW_KEY + " }\n    counter drop\n  }")
        for name, lines in self.chains.items():
            out.append(f"  chain {name} {{")
            out += [f"    {line}" for line in lines]
            out.append("  }")
        out.append("  chain prerouting {\n    type nat hook prerouting priority dstnat - 10; policy accept;")
        for pub, priv, iid in dnat:   # 1:1 public IP → interface (IGW semantics); marked so ingress rules apply
            out.append(f"    ip daddr {pub} ip saddr != @model ct mark set {PUBLIC_MARK} dnat ip to {priv} comment {_q(iid + ' public IP')}")
        out.append("  }")
        out.append("  chain postrouting {\n    type nat hook postrouting priority srcnat - 10; policy accept;")
        for ip in masq:
            out.append(f"    ip saddr {ip} ip daddr != @model masquerade comment \"internet egress\"")
        out.append("  }")
        out.append("}")
        plan = Plan(table=tbl, nft="\n".join(out) + "\n", warnings=self.warnings)
        plan.docker_user = list(self.space_cidrs)
        return plan


def compile_nft(topo: Topology, space: str, mgmt_cidrs=(), inbound_dnat: bool = False) -> Plan:
    return _Compiler(topo, space, mgmt_cidrs, inbound_dnat).compile()


def network_plan(topo: Topology, space: str, prefix: str = "vyomi-net-") -> list:
    """One bridge per subnet that has interfaces (an empty subnet needs no bridge, and skipping it
    avoids claiming address space — e.g. the default VPC's 172.31/16 — that Docker may be using)."""
    out = []
    used = {i.subnet for i in topo.interfaces.values()}
    for sid, s in topo.subnets.items():
        if sid not in used:
            continue
        net = ipaddress.ip_network(s.cidr, strict=False)
        h = hashlib.sha1(f"{space}/{sid}".encode()).hexdigest()[:10]
        label = re.sub(r"[^a-zA-Z0-9_.-]", "-", s.name or sid.split("/")[-1])[:24]
        out.append({"name": f"{prefix}{space}-{label}-{h[:6]}", "subnet": sid, "cidr": str(net),
                    "gateway": str(net.network_address + 1), "bridge": f"vn{h}"[:15]})
    return out


def compile_plan(topo: Topology, space: str, prefix: str = "vyomi-net-", mgmt_cidrs=(), inbound_dnat: bool = False) -> Plan:
    plan = compile_nft(topo, space, mgmt_cidrs, inbound_dnat)
    plan.networks = network_plan(topo, space, prefix)
    for i in topo.interfaces.values():
        s = topo.subnet_of(i)
        if not ip_in(i.ip, s.cidr):
            plan.warnings.append(f"{i.id}: {i.ip} not in subnet {s.cidr}; cannot be attached with --ip")
        elif i.ip == str(ipaddress.ip_network(s.cidr, strict=False).network_address + 1):
            plan.warnings.append(f"{i.id}: {i.ip} is the subnet router address (.1), reserved")
    return plan


# ── Docker driver ────────────────────────────────────────────────────────────
class DockerEnforcer:
    """Drives the plan on a Docker host. All side effects go through `docker` CLI calls so the
    appliance container only needs the docker socket (same as DockerComputeBackend)."""

    def __init__(self, space: str, *, prefix: str = "vyomi-net-", netd_name: str = "vyomi-netd",
                 netd_image: str = "vyomi/netd:1", docker: str = "docker", mgmt_cidrs=(),
                 inbound_dnat: bool = False):
        self.space = space
        self.inbound_dnat = inbound_dnat
        self.prefix = prefix
        self.netd_name = netd_name
        self.netd_image = netd_image
        self.docker = docker
        self.mgmt = list(mgmt_cidrs)
        self.table = table_name(space)
        self.last_plan: Plan | None = None
        self._carry: dict = {}

    def _run(self, *args, input_: str | None = None, check: bool = True) -> subprocess.CompletedProcess:
        p = subprocess.run([self.docker, *args], input=input_, capture_output=True, text=True)
        if check and p.returncode != 0:
            raise RuntimeError(f"docker {' '.join(args[:4])} failed: {p.stderr.strip() or p.stdout.strip()}")
        return p

    def netd(self, *cmd, input_: str | None = None, check: bool = True):
        return self._run("exec", "-i", self.netd_name, *cmd, input_=input_, check=check)

    def ensure_netd(self) -> None:
        st = self._run("inspect", "-f", "{{.State.Running}}", self.netd_name, check=False)
        if st.returncode == 0 and st.stdout.strip() == "true":
            return
        if st.returncode == 0:
            self._run("rm", "-f", self.netd_name, check=False)
        self._run("run", "-d", "--name", self.netd_name, "--network", "host", "--cap-add", "NET_ADMIN",
                  "--restart", "unless-stopped", "--label", "vyomi.netsim=netd", self.netd_image)

    def ensure_networks(self, plan: Plan) -> None:
        for n in plan.networks:
            st = self._run("network", "inspect", "-f", "{{range .IPAM.Config}}{{.Subnet}}{{end}}", n["name"], check=False)
            if st.returncode == 0:
                if st.stdout.strip() != n["cidr"]:
                    raise RuntimeError(f"network {n['name']} exists with {st.stdout.strip()}, want {n['cidr']}")
                continue
            self._run("network", "create", "--driver", "bridge", "--subnet", n["cidr"], "--gateway", n["gateway"],
                      "-o", "com.docker.network.bridge.enable_ip_masquerade=false",
                      "-o", f"com.docker.network.bridge.name={n['bridge']}",
                      "--label", f"vyomi.netsim.space={self.space}", "--label", f"vyomi.netsim.subnet={n['subnet']}",
                      n["name"])

    def _docker_user(self, cidrs) -> None:
        tag = self.table
        for c in cidrs:
            for flag in ("-s", "-d"):
                rule = ["DOCKER-USER", flag, c, "-m", "comment", "--comment", tag, "-j", "ACCEPT"]
                if self.netd("iptables", "-C", *rule, check=False).returncode != 0:
                    self.netd("iptables", "-I", *rule)

    def _clear_docker_user(self) -> None:
        cur = self.netd("iptables", "-S", "DOCKER-USER", check=False).stdout.splitlines()
        for line in cur:
            if f"--comment {self.table}" in line and line.startswith("-A "):
                self.netd("iptables", *line.replace("-A ", "-D ", 1).split(), check=False)

    def apply(self, topo: Topology) -> Plan:
        plan = compile_plan(topo, self.space, self.prefix, self.mgmt, self.inbound_dnat)
        self.ensure_netd()
        self.ensure_networks(plan)
        if self.last_plan is not None:
            # the atomic redefine recreates the dynamic flow sets → carry their counters over so
            # flow logs stay monotonic across rule changes
            self._carry_flows()
        self.netd("nft", "-f", "-", input_=plan.nft)
        self._clear_docker_user()
        self._docker_user(plan.docker_user)
        self.last_plan = plan
        return plan

    def run_args(self, topo: Topology, iface_id: str) -> list:
        """`docker run` args that put an instance on its subnet with its model IP."""
        i = topo.interfaces[iface_id]
        plan = self.last_plan or compile_plan(topo, self.space, self.prefix)
        net = next(n for n in plan.networks if n["subnet"] == i.subnet)
        return ["--network", net["name"], "--ip", i.ip]

    def _read_sets(self) -> tuple:
        try:
            from core.netsim.flowlogs import parse_nft_set
        except ImportError:
            from flowlogs import parse_nft_set  # type: ignore
        acc = self.netd("nft", "-j", "list", "set", "inet", self.table, "flows", check=False)
        rej = self.netd("nft", "-j", "list", "set", "inet", self.table, "rejects", check=False)
        return (parse_nft_set(acc.stdout) if acc.returncode == 0 else [],
                parse_nft_set(rej.stdout) if rej.returncode == 0 else [])

    def _carry_flows(self) -> None:
        for bucket, flows in zip(("flows", "rejects"), self._read_sets()):
            for f in flows:
                k = (bucket, f["src"], f["dst"], f["proto"], f["sport"], f["dport"])
                p, b = self._carry.get(k, (0, 0))
                self._carry[k] = (p + f["packets"], b + f["bytes"])

    def flow_sets(self) -> tuple:
        """(accepted, rejected) per-5-tuple counters, monotonic across re-applies."""
        merged = {k: list(v) for k, v in self._carry.items()}
        for bucket, flows in zip(("flows", "rejects"), self._read_sets()):
            for f in flows:
                k = (bucket, f["src"], f["dst"], f["proto"], f["sport"], f["dport"])
                cur = merged.setdefault(k, [0, 0])
                cur[0] += f["packets"]
                cur[1] += f["bytes"]
        out = ([], [])
        for (bucket, src, dst, proto, sport, dport), (pk, by) in merged.items():
            out[0 if bucket == "flows" else 1].append({"src": src, "dst": dst, "proto": proto, "sport": sport,
                                                       "dport": dport, "packets": pk, "bytes": by})
        return out

    def teardown(self, remove_networks: bool = True, remove_netd: bool = False) -> None:
        if self._run("inspect", self.netd_name, check=False).returncode == 0:
            self.netd("nft", "delete", "table", "inet", self.table, check=False)
            self._clear_docker_user()
        if remove_networks:
            ls = self._run("network", "ls", "-q", "--filter", f"label=vyomi.netsim.space={self.space}", check=False)
            for nid in ls.stdout.split():
                self._run("network", "rm", nid, check=False)
        if remove_netd:
            self._run("rm", "-f", self.netd_name, check=False)
