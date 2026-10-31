# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""netsim model — ONE cloud-neutral network topology for AWS VPC, GCP VPC and Azure VNet.

Pure Python (stdlib `ipaddress` + dataclasses only): no I/O, no subprocess, no socket →
the same file runs offline (where `enforce.py` compiles it to Docker networks + nftables)
and inside Pyodide for Nano (where `evaluate.py` IS the network behaviour).

The model is deliberately the *intersection of semantics*, not of APIs:

    Network        a VPC / VNet: address space (cidrs), network-level rulesets (GCP firewall)
    Subnet         cidr + zone + route table + subnet-level rulesets (AWS NACL, Azure subnet NSG)
                   + implicit NAT (GCP Cloud NAT / Azure NAT gateway) + default outbound (Azure)
    Interface      an ENI / GCE nic / Azure NIC: ip, public ip, group membership (SG ids / ASG ids),
                   network tags + service accounts (GCP), attached rulesets (SGs / NIC NSG)
    RuleSet        three evaluation MODES cover every cloud firewall primitive:
                     STATEFUL_ALLOW     AWS security group: allow-only, union of all SGs on the ENI,
                                        return traffic implicitly allowed
                     STATELESS_ORDERED  AWS network ACL: numbered allow/deny, first match wins, applied
                                        only at the subnet boundary, return traffic evaluated separately
                     STATEFUL_PRIORITY  GCP VPC firewall + Azure NSG: lowest priority number wins,
                                        deny beats allow on a tie (GCP), stateful
    Rule           direction, action, protocol, dest-port range, remote peers (cidr / group / tag /
                   service account / service tag), optional local selector + GCP targets
    RouteTable     routes dest-cidr → target kind (local / igw / nat / peering / blackhole / instance /
                   unsupported), with GCP priority + network-tag scoping, user-vs-system origin (Azure UDR)
    Gateway        igw (AWS IGW, GCP default-internet-gateway, Azure "Internet" next hop), nat (AWS NAT
                   gateway, GCP Cloud NAT, Azure NAT gateway)
    Peering        two networks, active flag. Non-transitive by construction.
"""
from __future__ import annotations

import ipaddress
from dataclasses import asdict, dataclass, field

# ── rule-set evaluation modes ────────────────────────────────────────────────
STATEFUL_ALLOW = "stateful_allow"          # AWS security group
STATELESS_ORDERED = "stateless_ordered"    # AWS network ACL
STATEFUL_PRIORITY = "stateful_priority"    # GCP firewall rule set, Azure NSG

INGRESS = "ingress"
EGRESS = "egress"

# Route target kinds
LOCAL, IGW, NAT, PEERING, BLACKHOLE, INSTANCE, UNSUPPORTED = (
    "local", "igw", "nat", "peering", "blackhole", "instance", "unsupported")

# Linux default ephemeral range (net.ipv4.ip_local_port_range) — what a client's source
# port really is on a Vyomi instance, and therefore what a stateless NACL must let back in.
LINUX_EPHEMERAL = (32768, 60999)

RFC1918 = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10")
AZURE_LB_IP = "168.63.129.16/32"

_PROTO_NUM = {"6": "tcp", "17": "udp", "1": "icmp", "-1": "all", "*": "all", "any": "all"}


def norm_proto(p) -> str:
    s = str(p if p is not None else "all").strip().lower()
    return _PROTO_NUM.get(s, s or "all")


def ip_in(ip: str, cidr: str) -> bool:
    try:
        return ipaddress.ip_address(ip) in ipaddress.ip_network(cidr, strict=False)
    except ValueError:
        return False


def prefix_len(cidr: str) -> int:
    return ipaddress.ip_network(cidr, strict=False).prefixlen


def cidr_covers(outer: str, inner: str) -> bool:
    try:
        return ipaddress.ip_network(inner, strict=False).subnet_of(ipaddress.ip_network(outer, strict=False))
    except (ValueError, TypeError):
        return False


# ── selectors ────────────────────────────────────────────────────────────────
@dataclass
class Peer:
    """Who is on the far side of a rule (or, as `Rule.local`, the near side).

    kind:
      any              everything
      cidr             value = "10.0.0.0/16"
      group            value = SG id / Azure ASG id — matches interfaces that are members
      tag              value = GCP network tag
      service_account  value = GCP service-account email
      service_tag      value = Azure service tag: VirtualNetwork | Internet | AzureLoadBalancer
    """
    kind: str
    value: str = ""

    @staticmethod
    def cidr(c: str) -> "Peer":
        return Peer("any") if c in ("0.0.0.0/0", "*", "any", "Any") else Peer("cidr", c)


@dataclass
class Rule:
    direction: str                      # ingress | egress
    action: str = "allow"               # allow | deny
    protocol: str = "all"               # all | tcp | udp | icmp | <ip proto number>
    ports: tuple | None = None          # destination port range (lo, hi); None = all ports
    peers: list = field(default_factory=lambda: [Peer("any")])   # remote side; OR semantics
    priority: int = 1000                # NACL rule number / GCP / Azure priority (SG: unused)
    targets: list | None = None         # GCP targetTags/targetServiceAccounts (None = all instances)
    local: list | None = None           # Azure: destinationAddressPrefix on inbound / source on outbound
    src_ports: tuple | None = None      # Azure sourcePortRange (rare); None = any
    name: str = ""
    implied: bool = False               # cloud-implied/default rule (GCP 65535, Azure 65000+)

    def __post_init__(self):
        self.protocol = norm_proto(self.protocol)
        if self.ports is not None:
            self.ports = tuple(int(x) for x in self.ports)
        if self.src_ports is not None:
            self.src_ports = tuple(int(x) for x in self.src_ports)
        self.peers = [p if isinstance(p, Peer) else Peer(**p) for p in (self.peers or [Peer("any")])]
        if self.targets is not None:
            self.targets = [p if isinstance(p, Peer) else Peer(**p) for p in self.targets]
        if self.local is not None:
            self.local = [p if isinstance(p, Peer) else Peer(**p) for p in self.local]


@dataclass
class RuleSet:
    id: str
    mode: str                           # STATEFUL_ALLOW | STATELESS_ORDERED | STATEFUL_PRIORITY
    kind: str = ""                      # trace label: security-group | network-acl | firewall | nsg
    name: str = ""
    rules: list = field(default_factory=list)
    default_action: str = "deny"        # when no rule matches (all four clouds: deny; GCP's implied
                                        # allow-egress is modelled as an explicit implied rule)
    log: bool = False                   # flow/firewall logging requested for this rule set

    def __post_init__(self):
        self.rules = [r if isinstance(r, Rule) else Rule(**r) for r in self.rules]


# ── routing ──────────────────────────────────────────────────────────────────
@dataclass
class Route:
    dest: str
    kind: str                           # LOCAL | IGW | NAT | PEERING | BLACKHOLE | INSTANCE | UNSUPPORTED
    target: str = ""                    # gateway / peering / interface id
    priority: int = 1000                # GCP route priority (lower wins on equal prefix)
    tags: list | None = None            # GCP instance-tag scoping (None = all instances)
    origin: str = "user"                # user (AWS route / GCP custom / Azure UDR) | system
    name: str = ""


@dataclass
class RouteTable:
    id: str
    routes: list = field(default_factory=list)
    name: str = ""

    def __post_init__(self):
        self.routes = [r if isinstance(r, Route) else Route(**r) for r in self.routes]


@dataclass
class Gateway:
    id: str
    kind: str                           # igw | nat
    network: str = ""                   # igw: the network it is attached to ("" = detached)
    subnet: str = ""                    # nat: the subnet it lives in (AWS NAT GW)
    public: bool = True                 # nat: public vs private connectivity
    available: bool = True
    ip: str = ""                        # nat: its private ip (flow-log srcaddr), informational
    name: str = ""


@dataclass
class Peering:
    id: str
    a: str                              # network id
    b: str
    active: bool = True
    name: str = ""


# ── topology objects ────────────────────────────────────────────────────────
@dataclass
class Network:
    id: str
    cloud: str = ""                     # aws | gcp | azure
    cidrs: list = field(default_factory=list)
    rulesets: list = field(default_factory=list)    # network-wide (GCP firewall)
    name: str = ""


@dataclass
class Subnet:
    id: str
    network: str
    cidr: str
    zone: str = ""
    route_table: str | None = None
    rulesets: list = field(default_factory=list)    # AWS NACL (stateless) / Azure subnet NSG
    nat: str | None = None              # implicit NAT gateway id (GCP Cloud NAT / Azure NAT GW)
    default_outbound: bool = False      # Azure "default outbound access"
    name: str = ""


@dataclass
class Interface:
    id: str
    subnet: str
    ip: str
    instance: str = ""
    public_ip: str | None = None
    groups: list = field(default_factory=list)      # membership for group refs (SG ids, Azure ASGs)
    rulesets: list = field(default_factory=list)    # attached at the nic (SGs, NIC NSG)
    tags: list = field(default_factory=list)        # GCP network tags
    service_accounts: list = field(default_factory=list)
    source_dest_check: bool = True      # AWS: must be off for an appliance route target
    name: str = ""


@dataclass
class Topology:
    networks: dict = field(default_factory=dict)
    subnets: dict = field(default_factory=dict)
    interfaces: dict = field(default_factory=dict)
    rulesets: dict = field(default_factory=dict)
    route_tables: dict = field(default_factory=dict)
    gateways: dict = field(default_factory=dict)
    peerings: dict = field(default_factory=dict)
    cloud: str = ""
    warnings: list = field(default_factory=list)

    # builders (chainable, used by translators + tests)
    def add(self, obj):
        bucket = {Network: self.networks, Subnet: self.subnets, Interface: self.interfaces,
                  RuleSet: self.rulesets, RouteTable: self.route_tables, Gateway: self.gateways,
                  Peering: self.peerings}[type(obj)]
        bucket[obj.id] = obj
        return obj

    # lookups
    def iface_by_ip(self, ip: str):
        for i in self.interfaces.values():
            if i.ip == ip or (i.public_ip and i.public_ip == ip):
                return i
        return None

    def subnet_of(self, iface: Interface) -> Subnet:
        return self.subnets[iface.subnet]

    def network_of(self, iface: Interface) -> Network:
        return self.networks[self.subnets[iface.subnet].network]

    def all_cidrs(self) -> list:
        out = []
        for n in self.networks.values():
            out.extend(n.cidrs)
        for s in self.subnets.values():
            if not any(cidr_covers(c, s.cidr) for c in out):
                out.append(s.cidr)
        return out

    def network_of_ip(self, ip: str):
        for n in self.networks.values():
            if any(ip_in(ip, c) for c in n.cidrs):
                return n
        for s in self.subnets.values():
            if ip_in(ip, s.cidr):
                return self.networks.get(s.network)
        return None

    def is_internal(self, ip: str) -> bool:
        return self.network_of_ip(ip) is not None

    def peers_of(self, network_id: str) -> list:
        out = []
        for p in self.peerings.values():
            if not p.active:
                continue
            if p.a == network_id:
                out.append(p.b)
            elif p.b == network_id:
                out.append(p.a)
        return out

    def vnet_space(self, network_id: str) -> list:
        """Azure `VirtualNetwork` service tag: own address space + directly peered networks."""
        out = list(self.networks[network_id].cidrs)
        for nid in self.peers_of(network_id):
            out.extend(self.networks[nid].cidrs)
        return out

    # serialisation (JSON-safe; netd / Nano can receive a topology as plain data)
    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Topology":
        t = Topology(cloud=d.get("cloud", ""), warnings=list(d.get("warnings", [])))
        for k, cls in (("networks", Network), ("subnets", Subnet), ("interfaces", Interface),
                       ("rulesets", RuleSet), ("route_tables", RouteTable), ("gateways", Gateway),
                       ("peerings", Peering)):
            for v in (d.get(k) or {}).values():
                t.add(cls(**v))
        return t
