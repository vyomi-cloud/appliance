# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""VPC core — substrate-independent network-simulation data plane (PARITY P4 #15).
The last open parity data plane and the first real one for networking: model a VPC
(subnets, security groups, route tables, internet gateways, network ACLs) and
**analyze reachability** — given a source + destination + port, evaluate the whole
path (route table → security groups → network ACLs) and report reachable / blocked
AND the reason. No catalog stub can fake that; it requires evaluating the real
network semantics.

Speaks the native **EC2 Query protocol** (form-encoded `Action=CreateVpc&...`, XML
responses) so an unmodified boto3 `ec2` client manages the topology; the reachability
analyzer is exposed as a simulator data-plane verb (`AnalyzeReachability`) + a core
function. NO fastapi / boto3 / socket imports (stdlib `ipaddress` only) → loads under
Pyodide.

Semantics modeled faithfully:
  - **routes**: same-VPC dest → implicit `local`; other dests need a matching route
    (e.g. 0.0.0.0/0 → an attached internet gateway).
  - **security groups**: STATEFUL — default deny ingress, allow-all egress; a rule
    matches on protocol + port range + source (CIDR or referenced SG). Return traffic
    is implicitly allowed (stateful), so only the forward direction is evaluated.
  - **network ACLs**: STATELESS — ordered numbered allow/deny entries, first match
    wins; the default NACL allows all. Forward path checks source-subnet egress +
    dest-subnet ingress.

Scope (v1 slice): the CRUD above + reachability. VPC peering, NAT gateways, transit
gateways and full NACL return-path/ephemeral evaluation slot in behind the same model.
"""
from __future__ import annotations

import ipaddress
import time
import uuid
from dataclasses import dataclass, field
from xml.sax.saxutils import escape as _xml_escape

EC2_NS = "http://ec2.amazonaws.com/doc/2016-11-15/"


@dataclass
class VpcResponse:
    status: int = 200
    body: str = ""
    headers: dict = field(default_factory=dict)
    media_type: str = "text/xml"


class VpcError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def _model(store) -> dict:
    m = getattr(store, "_vpc_model", None)
    if m is None:
        m = {"vpcs": {}, "subnets": {}, "sgs": {}, "route_tables": {},
             "igws": {}, "nacls": {},
             # EC2 compute/storage/network resources (same account, same Query-protocol
             # wire — boto3's "ec2" client signs ALL of this under one service).
             "instances": {}, "images": {}, "volumes": {}, "snapshots": {},
             "key_pairs": {}, "addresses": {}, "enis": {}, "placement_groups": {},
             "launch_templates": {}, "tags": {},
             "account": {"ebs_encryption_by_default": False, "ebs_default_kms_key_id": "alias/aws/ebs"},
             "seeded_amis": False}
        store._vpc_model = m
    return m


def _rid(prefix: str, n: int = 12) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:n]}"


# ── XML response builders (EC2 Query protocol) ─────────────────────────────
def _envelope(action: str, inner: str) -> VpcResponse:
    xml = ('<?xml version="1.0" encoding="UTF-8"?>'
           f'<{action}Response xmlns="{EC2_NS}">'
           f'<requestId>{uuid.uuid4().hex}</requestId>{inner}</{action}Response>')
    return VpcResponse(body=xml)


def _error(code: str, message: str, status: int = 400) -> VpcResponse:
    xml = ('<?xml version="1.0" encoding="UTF-8"?>'
           f'<Response><Errors><Error><Code>{_xml_escape(code)}</Code>'
           f'<Message>{_xml_escape(message)}</Message></Error></Errors>'
           f'<RequestID>{uuid.uuid4().hex}</RequestID></Response>')
    return VpcResponse(status=status, body=xml)


# ── security-group rule parsing (flattened Query form) ─────────────────────
def _parse_ip_permissions(params: dict) -> list:
    """Reconstruct IpPermissions from the flattened boto3 Query wire:
    IpPermissions.1.IpProtocol / .FromPort / .ToPort / .IpRanges.1.CidrIp /
    .Groups.1.GroupId."""
    perms: dict = {}
    for key, val in params.items():
        parts = key.split(".")
        if parts[0] != "IpPermissions" or len(parts) < 3:
            continue
        idx = parts[1]
        p = perms.setdefault(idx, {"protocol": "-1", "from_port": None, "to_port": None,
                                   "cidrs": [], "sgs": []})
        field_ = parts[2]
        if field_ == "IpProtocol":
            p["protocol"] = str(val)
        elif field_ == "FromPort":
            p["from_port"] = int(val)
        elif field_ == "ToPort":
            p["to_port"] = int(val)
        elif field_ == "IpRanges" and len(parts) >= 5 and parts[4] == "CidrIp":
            p["cidrs"].append(str(val))
        elif field_ == "IpRanges" and len(parts) >= 5 and parts[4] == "Description":
            p["description"] = str(val)
        elif field_ == "Groups" and len(parts) >= 5 and parts[4] == "GroupId":
            p["sgs"].append(str(val))
    return list(perms.values())


def _rule_matches(rule: dict, protocol: str, port: int, source_ip, source_sgs) -> bool:
    # protocol: "-1" (all) matches anything
    if rule["protocol"] not in ("-1", protocol, str(protocol)):
        return False
    if rule["protocol"] != "-1" and rule.get("from_port") is not None:
        if not (rule["from_port"] <= port <= rule["to_port"]):
            return False
    # source match: any listed CIDR contains source_ip, OR any listed SG is a source SG
    for cidr in rule.get("cidrs", []):
        try:
            if ipaddress.ip_address(source_ip) in ipaddress.ip_network(cidr, strict=False):
                return True
        except ValueError:
            continue
    for sg in rule.get("sgs", []):
        if sg in (source_sgs or []):
            return True
    return False


# ── control-plane operations ────────────────────────────────────────────────
def _create_vpc(store, params):
    cidr = str(params.get("CidrBlock", ""))
    try:
        ipaddress.ip_network(cidr, strict=False)
    except ValueError:
        raise VpcError("InvalidParameterValue", f"Invalid CIDR: {cidr}")
    vpc_id = _rid("vpc")
    _model(store)["vpcs"][vpc_id] = {"id": vpc_id, "cidr": cidr, "igw": None}
    # default (main) route table with the implicit local route
    rt_id = _rid("rtb")
    _model(store)["route_tables"][rt_id] = {"id": rt_id, "vpc_id": vpc_id, "main": True,
                                            "routes": [{"dest": cidr, "target": "local"}],
                                            "subnets": []}
    return _envelope("CreateVpc", f"<vpc><vpcId>{vpc_id}</vpcId><cidrBlock>{cidr}</cidrBlock>"
                                  f"<state>available</state></vpc>")


def _create_subnet(store, params):
    vpc_id = str(params.get("VpcId", ""))
    cidr = str(params.get("CidrBlock", ""))
    m = _model(store)
    if vpc_id not in m["vpcs"]:
        raise VpcError("InvalidVpcID.NotFound", f"VPC {vpc_id} not found.")
    subnet_id = _rid("subnet")
    main_rt = next((rt["id"] for rt in m["route_tables"].values()
                    if rt["vpc_id"] == vpc_id and rt.get("main")), None)
    m["subnets"][subnet_id] = {"id": subnet_id, "vpc_id": vpc_id, "cidr": cidr,
                               "route_table": main_rt, "nacl": None}
    if main_rt:
        m["route_tables"][main_rt]["subnets"].append(subnet_id)
    return _envelope("CreateSubnet", f"<subnet><subnetId>{subnet_id}</subnetId>"
                                     f"<vpcId>{vpc_id}</vpcId><cidrBlock>{cidr}</cidrBlock>"
                                     f"<state>available</state></subnet>")


def _create_security_group(store, params):
    m = _model(store)
    vpc_id = str(params.get("VpcId", "")) or None
    if vpc_id and vpc_id not in m["vpcs"]:
        raise VpcError("InvalidVpcID.NotFound", f"VPC {vpc_id} not found.")
    if vpc_id is None:
        vpc_id, _subnet, _sg = _ensure_default_network(m)
    sg_id = _rid("sg")
    # default: deny all ingress, allow all egress (AWS SG defaults)
    m["sgs"][sg_id] = {"id": sg_id, "vpc_id": vpc_id, "name": str(params.get("GroupName", "")),
                       "description": str(params.get("GroupDescription", "")), "is_default": False,
                       "tags": _parse_tag_specifications(params).get("security-group", {}), "ingress": [],
                       "egress": [{"protocol": "-1", "from_port": None, "to_port": None,
                                   "cidrs": ["0.0.0.0/0"], "sgs": [], "rule_id": _rid("sgr", 8), "description": ""}]}
    return _envelope("CreateSecurityGroup", f"<groupId>{sg_id}</groupId>")


def _authorize(store, params, direction):
    sg_id = str(params.get("GroupId", ""))
    m = _model(store)
    sg = m["sgs"].get(sg_id)
    if not sg:
        raise VpcError("InvalidGroup.NotFound", f"Security group {sg_id} not found.")
    perms = _parse_ip_permissions(params)
    # simple single-rule form (CidrIp/IpProtocol/FromPort/ToPort) as a fallback
    if not perms and params.get("IpProtocol"):
        perms = [{"protocol": str(params["IpProtocol"]),
                  "from_port": int(params.get("FromPort", 0) or 0),
                  "to_port": int(params.get("ToPort", 0) or 0),
                  "cidrs": [params["CidrIp"]] if params.get("CidrIp") else [],
                  "sgs": [params["SourceSecurityGroupId"]] if params.get("SourceSecurityGroupId") else [],
                  "description": str(params.get("Description", ""))}]
    for p in perms:
        p.setdefault("rule_id", _rid("sgr", 8))
        p.setdefault("description", "")
    sg["ingress" if direction == "ingress" else "egress"].extend(perms)
    action = "AuthorizeSecurityGroupIngress" if direction == "ingress" else "AuthorizeSecurityGroupEgress"
    return _envelope(action, "<return>true</return>")


def _create_internet_gateway(store, params):
    igw_id = _rid("igw")
    _model(store)["igws"][igw_id] = {"id": igw_id, "vpc_id": None}
    return _envelope("CreateInternetGateway",
                     f"<internetGateway><internetGatewayId>{igw_id}</internetGatewayId></internetGateway>")


def _attach_internet_gateway(store, params):
    igw_id = str(params.get("InternetGatewayId", ""))
    vpc_id = str(params.get("VpcId", ""))
    m = _model(store)
    if igw_id not in m["igws"] or vpc_id not in m["vpcs"]:
        raise VpcError("InvalidParameterValue", "IGW or VPC not found.")
    m["igws"][igw_id]["vpc_id"] = vpc_id
    m["vpcs"][vpc_id]["igw"] = igw_id
    return _envelope("AttachInternetGateway", "<return>true</return>")


def _create_route(store, params):
    rt_id = str(params.get("RouteTableId", ""))
    m = _model(store)
    rt = m["route_tables"].get(rt_id)
    if not rt:
        raise VpcError("InvalidRouteTableID.NotFound", f"Route table {rt_id} not found.")
    dest = str(params.get("DestinationCidrBlock", ""))
    target = str(params.get("GatewayId") or params.get("NatGatewayId")
                 or params.get("VpcPeeringConnectionId") or "local")
    rt["routes"].append({"dest": dest, "target": target})
    return _envelope("CreateRoute", "<return>true</return>")


def _create_network_acl(store, params):
    vpc_id = str(params.get("VpcId", ""))
    m = _model(store)
    if vpc_id not in m["vpcs"]:
        raise VpcError("InvalidVpcID.NotFound", f"VPC {vpc_id} not found.")
    nacl_id = _rid("acl")
    m["nacls"][nacl_id] = {"id": nacl_id, "vpc_id": vpc_id, "entries": [], "subnets": []}
    return _envelope("CreateNetworkAcl",
                     f"<networkAcl><networkAclId>{nacl_id}</networkAclId></networkAcl>")


def _create_network_acl_entry(store, params):
    m = _model(store)
    nacl = m["nacls"].get(str(params.get("NetworkAclId", "")))
    if not nacl:
        raise VpcError("InvalidNetworkAclID.NotFound", "Network ACL not found.")
    nacl["entries"].append({
        "rule_number": int(params.get("RuleNumber", 100)),
        "protocol": str(params.get("Protocol", "-1")),
        "allow": str(params.get("RuleAction", "allow")).lower() == "allow",
        "egress": str(params.get("Egress", "false")).lower() == "true",
        "cidr": str(params.get("CidrBlock", "0.0.0.0/0")),
        "from_port": int(params["PortRange.From"]) if params.get("PortRange.From") else None,
        "to_port": int(params["PortRange.To"]) if params.get("PortRange.To") else None,
    })
    return _envelope("CreateNetworkAclEntry", "<return>true</return>")


def _associate_network_acl(store, params):
    """Attach a NACL to a subnet (simulator convenience; real EC2 uses
    ReplaceNetworkAclAssociation with an association id)."""
    m = _model(store)
    nacl_id = str(params.get("NetworkAclId", ""))
    subnet_id = str(params.get("SubnetId", ""))
    if nacl_id not in m["nacls"] or subnet_id not in m["subnets"]:
        raise VpcError("InvalidParameterValue", "NACL or subnet not found.")
    m["subnets"][subnet_id]["nacl"] = nacl_id
    m["nacls"][nacl_id]["subnets"].append(subnet_id)
    return _envelope("AssociateNetworkAcl", "<return>true</return>")


def _describe_vpcs(store, params):
    m = _model(store)
    _ensure_default_network(m)
    items = "".join(f"<item><vpcId>{v['id']}</vpcId><cidrBlock>{v['cidr']}</cidrBlock>"
                    f"<state>available</state></item>" for v in m["vpcs"].values())
    return _envelope("DescribeVpcs", f"<vpcSet>{items}</vpcSet>")


def _describe_subnets(store, params):
    m = _model(store)
    _ensure_default_network(m)
    items = "".join(f"<item><subnetId>{s['id']}</subnetId><vpcId>{s['vpc_id']}</vpcId>"
                    f"<cidrBlock>{s['cidr']}</cidrBlock><availabilityZone>{s.get('az', '')}</availabilityZone>"
                    f"<state>available</state></item>" for s in m["subnets"].values())
    return _envelope("DescribeSubnets", f"<subnetSet>{items}</subnetSet>")


# ── data plane: reachability analyzer ──────────────────────────────────────
def _find_subnet_for_ip(m, ip):
    for sn in m["subnets"].values():
        try:
            if ipaddress.ip_address(ip) in ipaddress.ip_network(sn["cidr"], strict=False):
                return sn
        except ValueError:
            pass
    return None


def _route_allows(m, subnet, dest_ip) -> tuple[bool, str]:
    """Does the subnet's route table have a route to dest_ip?"""
    rt = m["route_tables"].get(subnet.get("route_table")) if subnet else None
    if not rt:
        return False, "source subnet has no route table"
    best = None
    for r in rt["routes"]:
        try:
            net = ipaddress.ip_network(r["dest"], strict=False)
        except ValueError:
            continue
        if ipaddress.ip_address(dest_ip) in net:
            if best is None or net.prefixlen > best[0]:
                best = (net.prefixlen, r)
    if best is None:
        return False, f"no route to {dest_ip}"
    return True, f"route {best[1]['dest']} → {best[1]['target']}"


def _nacl_allows(m, subnet, protocol, port, direction) -> tuple[bool, str]:
    """Stateless NACL check. No custom NACL → default-allow. Entries are ordered
    numbered allow/deny; first match wins."""
    nacl = m["nacls"].get(subnet.get("nacl")) if subnet else None
    if not nacl:
        return True, "default NACL (allow all)"
    entries = sorted((e for e in nacl["entries"] if e["egress"] == (direction == "egress")),
                     key=lambda e: e["rule_number"])
    for e in entries:
        if e["protocol"] not in ("-1", protocol):
            continue
        if e["protocol"] != "-1" and e.get("from_port") is not None:
            if not (e["from_port"] <= port <= e["to_port"]):
                continue
        return (e["allow"], f"NACL rule {e['rule_number']} {'allow' if e['allow'] else 'deny'}")
    return False, "no matching NACL entry (implicit deny)"


def analyze_reachability(store, source: dict, dest: dict, port: int, protocol: str = "tcp") -> dict:
    """Evaluate whether `source` can reach `dest` on `port`. source/dest are dicts:
    {ip, security_group_ids?}. dest may be external (no subnet). Returns
    {reachable: bool, reason: str, path: [...]}."""
    m = _model(store)
    src_ip, dst_ip = source["ip"], dest["ip"]
    src_sn = _find_subnet_for_ip(m, src_ip)
    dst_sn = _find_subnet_for_ip(m, dst_ip)
    src_sgs = source.get("security_group_ids", [])
    dst_sgs = dest.get("security_group_ids", [])
    path = []

    if src_sn is None:
        return {"reachable": False, "reason": "source IP is not in any subnet", "path": path}

    # 1. route
    ok, why = _route_allows(m, src_sn, dst_ip)
    path.append(f"route: {why}")
    if not ok:
        return {"reachable": False, "reason": why, "path": path}

    # 2. source SG egress (stateful → return traffic auto-allowed)
    egress_ok = any(_rule_matches(r, protocol, port, dst_ip, dst_sgs)
                    for sg in src_sgs for r in m["sgs"].get(sg, {}).get("egress", []))
    if not src_sgs:
        egress_ok = True  # no SG attached → default egress allow-all
    path.append(f"source SG egress: {'allow' if egress_ok else 'DENY'}")
    if not egress_ok:
        return {"reachable": False, "reason": "source security group egress does not allow it", "path": path}

    # 3. dest SG ingress (default deny — must be explicitly allowed)
    if dst_sgs:
        ingress_ok = any(_rule_matches(r, protocol, port, src_ip, src_sgs)
                         for sg in dst_sgs for r in m["sgs"].get(sg, {}).get("ingress", []))
        path.append(f"dest SG ingress: {'allow' if ingress_ok else 'DENY'}")
        if not ingress_ok:
            return {"reachable": False,
                    "reason": f"destination security group ingress does not allow {protocol}:{port} from {src_ip}",
                    "path": path}

    # 4. NACLs (stateless, forward path)
    ok, why = _nacl_allows(m, src_sn, protocol, port, "egress")
    path.append(f"source NACL egress: {why}")
    if not ok:
        return {"reachable": False, "reason": f"source subnet NACL blocks egress ({why})", "path": path}
    if dst_sn is not None:
        ok, why = _nacl_allows(m, dst_sn, protocol, port, "ingress")
        path.append(f"dest NACL ingress: {why}")
        if not ok:
            return {"reachable": False, "reason": f"destination subnet NACL blocks ingress ({why})", "path": path}

    return {"reachable": True, "reason": "path is open", "path": path}


def _analyze_reachability_action(store, params):
    """Simulator data-plane verb: AnalyzeReachability. Endpoints via
    Source.Ip / Source.SecurityGroupId.N / Destination.Ip / Destination.SecurityGroupId.N."""
    def endpoint(prefix):
        sgs = [v for k, v in params.items()
               if k.startswith(f"{prefix}.SecurityGroupId")]
        return {"ip": params.get(f"{prefix}.Ip", ""), "security_group_ids": sgs}
    result = analyze_reachability(store, endpoint("Source"), endpoint("Destination"),
                                  int(params.get("DestinationPort", 0) or 0),
                                  str(params.get("Protocol", "tcp")))
    steps = "".join(f"<item>{_xml_escape(s)}</item>" for s in result["path"])
    return _envelope("AnalyzeReachability",
                     f"<reachable>{str(result['reachable']).lower()}</reachable>"
                     f"<reason>{_xml_escape(result['reason'])}</reason>"
                     f"<path>{steps}</path>")


OWNER_ID = "123456789012"
_AZS = ["us-east-1a", "us-east-1b", "us-east-1c"]
_STATE_CODE = {"pending": 0, "running": 16, "shutting-down": 32, "terminated": 48, "stopping": 64, "stopped": 80}

_INSTANCE_TYPES = {
    "t2.micro": dict(vcpu=1, mem=1.0, arch=["i386", "x86_64"], family="t2", net="Low to Moderate", free_tier=True, hypervisor="xen"),
    "t3.micro": dict(vcpu=2, mem=1.0, arch=["x86_64"], family="t3", net="Up to 5 Gigabit", free_tier=True, hypervisor="nitro"),
    "t3.small": dict(vcpu=2, mem=2.0, arch=["x86_64"], family="t3", net="Up to 5 Gigabit", free_tier=False, hypervisor="nitro"),
    "t3.medium": dict(vcpu=2, mem=4.0, arch=["x86_64"], family="t3", net="Up to 5 Gigabit", free_tier=False, hypervisor="nitro"),
    "t3.large": dict(vcpu=2, mem=8.0, arch=["x86_64"], family="t3", net="Up to 5 Gigabit", free_tier=False, hypervisor="nitro"),
    "t3a.micro": dict(vcpu=2, mem=1.0, arch=["x86_64"], family="t3a", net="Up to 5 Gigabit", free_tier=False, hypervisor="nitro"),
    "t4g.micro": dict(vcpu=2, mem=1.0, arch=["arm64"], family="t4g", net="Up to 5 Gigabit", free_tier=False, hypervisor="nitro"),
    "m5.large": dict(vcpu=2, mem=8.0, arch=["x86_64"], family="m5", net="Up to 10 Gigabit", free_tier=False, hypervisor="nitro"),
    "m5.xlarge": dict(vcpu=4, mem=16.0, arch=["x86_64"], family="m5", net="Up to 10 Gigabit", free_tier=False, hypervisor="nitro"),
    "m5.2xlarge": dict(vcpu=8, mem=32.0, arch=["x86_64"], family="m5", net="Up to 10 Gigabit", free_tier=False, hypervisor="nitro"),
    "m6g.large": dict(vcpu=2, mem=8.0, arch=["arm64"], family="m6g", net="Up to 10 Gigabit", free_tier=False, hypervisor="nitro"),
    "c5.large": dict(vcpu=2, mem=4.0, arch=["x86_64"], family="c5", net="Up to 10 Gigabit", free_tier=False, hypervisor="nitro"),
    "c5.xlarge": dict(vcpu=4, mem=8.0, arch=["x86_64"], family="c5", net="Up to 10 Gigabit", free_tier=False, hypervisor="nitro"),
    "c6g.large": dict(vcpu=2, mem=4.0, arch=["arm64"], family="c6g", net="Up to 10 Gigabit", free_tier=False, hypervisor="nitro"),
    "r5.large": dict(vcpu=2, mem=16.0, arch=["x86_64"], family="r5", net="Up to 10 Gigabit", free_tier=False, hypervisor="nitro"),
    "r5.xlarge": dict(vcpu=4, mem=32.0, arch=["x86_64"], family="r5", net="Up to 10 Gigabit", free_tier=False, hypervisor="nitro"),
    "t2.small": dict(vcpu=1, mem=2.0, arch=["x86_64"], family="t2", net="Low to Moderate", free_tier=False, hypervisor="xen", current_gen=False),
    "m4.large": dict(vcpu=2, mem=8.0, arch=["x86_64"], family="m4", net="Moderate", free_tier=False, hypervisor="xen", current_gen=False),
}

_QUICKSTART_AMIS = [
    {"name": "Amazon Linux 2023 kernel-6.18 AMI", "arch": "x86_64", "platform": ""},
    {"name": "Ubuntu Server 22.04 LTS (HVM)", "arch": "x86_64", "platform": ""},
    {"name": "Debian 12 (HVM)", "arch": "x86_64", "platform": ""},
    {"name": "Red Hat Enterprise Linux 9 (HVM)", "arch": "x86_64", "platform": ""},
    {"name": "SUSE Linux Enterprise Server 15 SP5 (HVM)", "arch": "x86_64", "platform": ""},
    {"name": "Microsoft Windows Server 2022 Base", "arch": "x86_64", "platform": "windows"},
]


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())


def _tags_xml(tags: dict) -> str:
    return "<tagSet>" + "".join(f"<item><key>{_xml_escape(k)}</key><value>{_xml_escape(v)}</value></item>" for k, v in (tags or {}).items()) + "</tagSet>"


def _ensure_default_network(m: dict) -> tuple[str, str, str]:
    """Lazily create the account's default VPC/subnets/IGW/security group (same
    bootstrap every AWS account gets), then return (vpc_id, a_subnet_id, default_sg_id)."""
    default_vpc = next((v for v in m["vpcs"].values() if v.get("default")), None)
    if default_vpc is None:
        vpc_id = _rid("vpc")
        m["vpcs"][vpc_id] = {"id": vpc_id, "cidr": "172.31.0.0/16", "igw": None, "default": True}
        rt_id = _rid("rtb")
        m["route_tables"][rt_id] = {"id": rt_id, "vpc_id": vpc_id, "main": True,
                                    "routes": [{"dest": "172.31.0.0/16", "target": "local"}], "subnets": []}
        for i, az in enumerate(_AZS):
            subnet_id = _rid("subnet")
            m["subnets"][subnet_id] = {"id": subnet_id, "vpc_id": vpc_id, "cidr": f"172.31.{i}.0/24",
                                       "az": az, "route_table": rt_id, "nacl": None, "default": True}
            m["route_tables"][rt_id]["subnets"].append(subnet_id)
        igw_id = _rid("igw")
        m["igws"][igw_id] = {"id": igw_id, "vpc_id": vpc_id}
        m["vpcs"][vpc_id]["igw"] = igw_id
        m["route_tables"][rt_id]["routes"].append({"dest": "0.0.0.0/0", "target": igw_id})
        default_vpc = m["vpcs"][vpc_id]
    vpc_id = default_vpc["id"]
    subnet_id = next(s["id"] for s in m["subnets"].values() if s["vpc_id"] == vpc_id)
    default_sg = next((sg["id"] for sg in m["sgs"].values() if sg.get("vpc_id") == vpc_id and sg.get("is_default")), None)
    if default_sg is None:
        sg_id = _rid("sg")
        m["sgs"][sg_id] = {"id": sg_id, "vpc_id": vpc_id, "name": "default", "description": "default VPC security group",
                           "is_default": True, "tags": {},
                           "ingress": [{"protocol": "-1", "from_port": None, "to_port": None, "cidrs": [], "sgs": [sg_id], "rule_id": _rid("sgr", 8), "description": ""}],
                           "egress": [{"protocol": "-1", "from_port": None, "to_port": None, "cidrs": ["0.0.0.0/0"], "sgs": [], "rule_id": _rid("sgr", 8), "description": ""}]}
        default_sg = sg_id
    return vpc_id, subnet_id, default_sg


def _seed_amis(m: dict) -> None:
    if m["seeded_amis"]:
        return
    m["seeded_amis"] = True
    for spec in _QUICKSTART_AMIS:
        ami_id = "ami-" + uuid.uuid4().hex[:17]
        m["images"][ami_id] = {
            "id": ami_id, "name": spec["name"], "description": spec["name"], "owner_id": "amazon",
            "public": True, "state": "available", "architecture": spec["arch"], "platform": spec["platform"],
            "root_device_type": "ebs", "root_device_name": "/dev/xvda", "virtualization_type": "hvm",
            "creation_date": _now(), "source": "quickstart", "tags": {}, "launch_permissions": [],
            "block_devices": [{"device_name": "/dev/xvda", "snapshot_id": "snap-" + uuid.uuid4().hex[:12],
                               "size": 8, "volume_type": "gp3", "delete_on_termination": True}],
        }


def _default_ami_id(m: dict) -> str:
    _seed_amis(m)
    return next(i["id"] for i in m["images"].values() if i["name"].startswith("Amazon Linux"))


def _taggable_collections(m: dict) -> list:
    return [m["instances"], m["volumes"], m["snapshots"], m["images"], m["sgs"],
            m["addresses"], m["enis"], m["placement_groups"], m["launch_templates"], m["key_pairs"]]


def _find_resource(m: dict, rid: str):
    for coll in _taggable_collections(m):
        if rid in coll:
            return coll[rid]
    return None


def _parse_flat_tags(params: dict, prefix: str = "Tag") -> dict:
    """Flattened Query-wire tags: Tag.1.Key / Tag.1.Value."""
    tags = {}
    idxs = sorted({k.split(".")[1] for k in params if k.startswith(f"{prefix}.") and len(k.split(".")) >= 3}, key=int)
    for i in idxs:
        key = params.get(f"{prefix}.{i}.Key")
        if key:
            tags[str(key)] = str(params.get(f"{prefix}.{i}.Value", ""))
    return tags


def _parse_tag_specifications(params: dict) -> dict:
    """TagSpecification.N.ResourceType + .Tag.M.Key/.Value -> {resource_type: {key: value}}."""
    import re as _re
    types = {}
    for k, v in params.items():
        mm = _re.match(r"TagSpecification\.(\d+)\.ResourceType$", k)
        if mm:
            types[mm.group(1)] = str(v)
    out = {}
    for idx, rtype in types.items():
        tags = {}
        tidxs = sorted({k.split(".")[3] for k in params if k.startswith(f"TagSpecification.{idx}.Tag.")}, key=int)
        for ti in tidxs:
            key = params.get(f"TagSpecification.{idx}.Tag.{ti}.Key")
            if key:
                tags[str(key)] = str(params.get(f"TagSpecification.{idx}.Tag.{ti}.Value", ""))
        out[rtype] = tags
    return out


def _pseudo_ip(n: int, base=(10, 0, 1)) -> str:
    return f"{base[0]}.{base[1]}.{base[2]}.{10 + (n % 240)}"


def _pseudo_public_ip(n: int) -> str:
    return f"54.{(n * 7) % 220 + 10}.{(n * 13) % 250}.{(n * 29) % 250}"


# ── instances ───────────────────────────────────────────────────────────
def _instance_xml(inst: dict) -> str:
    bdm = "".join(
        f"<item><deviceName>{_xml_escape(bd['device_name'])}</deviceName>"
        f"<ebs><volumeId>{_xml_escape(bd['volume_id'])}</volumeId><status>attached</status>"
        f"<deleteOnTermination>{str(bd.get('delete_on_termination', True)).lower()}</deleteOnTermination></ebs></item>"
        for bd in inst.get("block_devices", []))
    sgs = "".join(f"<item><groupId>{_xml_escape(g)}</groupId><groupName>{_xml_escape(g)}</groupName></item>" for g in inst.get("sg_ids", []))
    return (
        "<item>"
        f"<instanceId>{_xml_escape(inst['id'])}</instanceId>"
        f"<imageId>{_xml_escape(inst['image_id'])}</imageId>"
        f"<instanceState><code>{_STATE_CODE.get(inst['state'], 0)}</code><name>{_xml_escape(inst['state'])}</name></instanceState>"
        f"<privateDnsName>{_xml_escape(inst.get('private_dns', ''))}</privateDnsName>"
        f"<dnsName>{_xml_escape(inst.get('public_dns', ''))}</dnsName>"
        f"<instanceType>{_xml_escape(inst['instance_type'])}</instanceType>"
        f"<launchTime>{_xml_escape(inst['launch_time'])}</launchTime>"
        f"<placement><availabilityZone>{_xml_escape(inst['az'])}</availabilityZone><tenancy>{_xml_escape(inst.get('tenancy', 'default'))}</tenancy>"
        f"<groupName>{_xml_escape(inst.get('placement_group', ''))}</groupName></placement>"
        f"<platform>{_xml_escape(inst.get('platform', ''))}</platform>"
        f"<platformDetails>{_xml_escape(inst.get('platform_details', 'Linux/UNIX'))}</platformDetails>"
        f"<privateIpAddress>{_xml_escape(inst.get('private_ip', ''))}</privateIpAddress>"
        f"<ipAddress>{_xml_escape(inst.get('public_ip', ''))}</ipAddress>"
        f"<groupSet>{sgs}</groupSet>"
        f"<keyName>{_xml_escape(inst.get('key_name', ''))}</keyName>"
        f"<monitoring><state>{'enabled' if inst.get('monitoring') else 'disabled'}</state></monitoring>"
        f"<subnetId>{_xml_escape(inst.get('subnet_id', ''))}</subnetId>"
        f"<vpcId>{_xml_escape(inst.get('vpc_id', ''))}</vpcId>"
        f"<architecture>{_xml_escape(inst.get('architecture', 'x86_64'))}</architecture>"
        f"<rootDeviceType>{_xml_escape(inst.get('root_device_type', 'ebs'))}</rootDeviceType>"
        f"<rootDeviceName>{_xml_escape(inst.get('root_device_name', '/dev/xvda'))}</rootDeviceName>"
        f"<blockDeviceMapping>{bdm}</blockDeviceMapping>"
        f"<virtualizationType>{_xml_escape(inst.get('virtualization_type', 'hvm'))}</virtualizationType>"
        f"<hypervisor>{_xml_escape(inst.get('hypervisor', 'nitro'))}</hypervisor>"
        f"<ebsOptimized>{str(inst.get('ebs_optimized', True)).lower()}</ebsOptimized>"
        f"<disableApiTermination>{str(inst.get('termination_protection', False)).lower()}</disableApiTermination>"
        f"<disableApiStop>{str(inst.get('stop_protection', False)).lower()}</disableApiStop>"
        f"<instanceInitiatedShutdownBehavior>{_xml_escape(inst.get('shutdown_behavior', 'stop'))}</instanceInitiatedShutdownBehavior>"
        f"<iamInstanceProfile><arn>{_xml_escape(inst.get('iam_instance_profile', ''))}</arn></iamInstanceProfile>"
        f"<creditSpecification><cpuCredits>{_xml_escape(inst.get('credit_spec', 'standard'))}</cpuCredits></creditSpecification>"
        f"<hibernationOptions><configured>{str(inst.get('hibernation', False)).lower()}</configured></hibernationOptions>"
        f"<metadataOptions><httpTokens>{_xml_escape(inst.get('metadata_tokens', 'required'))}</httpTokens>"
        f"<httpEndpoint>{_xml_escape(inst.get('metadata_endpoint', 'enabled'))}</httpEndpoint></metadataOptions>"
        f"<usageOperation>{_xml_escape(inst.get('usage_operation', 'RunInstances'))}</usageOperation>"
        f"{_tags_xml(inst.get('tags', {}))}"
        "</item>"
    )


def _launch_one(m: dict, params: dict, tag_specs: dict, idx: int) -> dict:
    image_id = str(params.get("ImageId") or _default_ami_id(m))
    image = m["images"].get(image_id)
    if image is None:
        raise VpcError("InvalidAMIID.NotFound", f"The image id '[{image_id}]' does not exist.")
    vpc_id, default_subnet, default_sg = _ensure_default_network(m)
    subnet_id = str(params.get("SubnetId") or default_subnet)
    subnet = m["subnets"].get(subnet_id)
    az = str(params.get("Placement.AvailabilityZone") or (subnet or {}).get("az") or _AZS[idx % len(_AZS)])
    sg_ids = [v for k, v in params.items() if k.startswith("SecurityGroupId.")] or \
             [v for k, v in params.items() if k.startswith("SecurityGroupIds.")] or [default_sg]
    instance_id = "i-" + uuid.uuid4().hex[:17]
    n = len(m["instances"]) + idx
    private_ip = _pseudo_ip(n)
    public_ip = _pseudo_public_ip(n)
    tags = dict(tag_specs.get("instance", {}))
    size = int(params.get("BlockDeviceMapping.1.Ebs.VolumeSize") or image.get("block_devices", [{}])[0].get("size", 8))
    vol_type = str(params.get("BlockDeviceMapping.1.Ebs.VolumeType") or "gp3")
    encrypted = str(params.get("BlockDeviceMapping.1.Ebs.Encrypted", "")).lower() == "true" or m["account"]["ebs_encryption_by_default"]
    volume_id = _rid("vol")
    m["volumes"][volume_id] = {
        "id": volume_id, "size": size, "type": vol_type, "iops": 3000 if vol_type == "gp3" else None,
        "throughput": 125 if vol_type == "gp3" else None, "az": az, "state": "in-use", "snapshot_id": "",
        "encrypted": encrypted, "kms_key_id": m["account"]["ebs_default_kms_key_id"] if encrypted else "",
        "multi_attach": False, "created": _now(), "tags": {},
        "attachments": [{"instance_id": instance_id, "device": "/dev/xvda", "delete_on_termination": True, "attach_time": _now()}],
    }
    inst = {
        "id": instance_id, "image_id": image_id, "state": "running", "instance_type": str(params.get("InstanceType") or "t3.micro"),
        "launch_time": _now(), "az": az, "vpc_id": vpc_id, "subnet_id": subnet_id, "sg_ids": sg_ids,
        "private_ip": private_ip, "public_ip": public_ip,
        "public_dns": f"ec2-{public_ip.replace('.', '-')}.compute-1.amazonaws.com",
        "private_dns": f"ip-{private_ip.replace('.', '-')}.ec2.internal",
        "key_name": str(params.get("KeyName") or ""), "monitoring": str(params.get("Monitoring.Enabled", "")).lower() == "true",
        "architecture": image.get("architecture", "x86_64"), "root_device_type": "ebs", "root_device_name": "/dev/xvda",
        "virtualization_type": image.get("virtualization_type", "hvm"), "hypervisor": "nitro",
        "platform": image.get("platform", ""), "platform_details": "Windows" if image.get("platform") == "windows" else "Linux/UNIX",
        "ebs_optimized": True, "termination_protection": str(params.get("DisableApiTermination", "")).lower() == "true",
        "stop_protection": False, "shutdown_behavior": str(params.get("InstanceInitiatedShutdownBehavior") or "stop"),
        "tenancy": str(params.get("Placement.Tenancy") or "default"), "placement_group": str(params.get("Placement.GroupName") or ""),
        "iam_instance_profile": str(params.get("IamInstanceProfile.Name") or params.get("IamInstanceProfile.Arn") or ""),
        "credit_spec": str(params.get("CreditSpecification.CpuCredits") or "standard"),
        "hibernation": str(params.get("HibernationOptions.Configured", "")).lower() == "true",
        "auto_recovery": str(params.get("MaintenanceOptions.AutoRecovery") or "default"),
        "hostname_type": str(params.get("PrivateDnsNameOptions.HostnameType") or "ip-name"),
        "metadata_tokens": str(params.get("MetadataOptions.HttpTokens") or "required"),
        "metadata_endpoint": str(params.get("MetadataOptions.HttpEndpoint") or "enabled"),
        "user_data": str(params.get("UserData") or ""), "block_devices": [{"device_name": "/dev/xvda", "volume_id": volume_id, "delete_on_termination": True}],
        "tags": tags,
    }
    if tags.get("Name"):
        inst["name"] = tags["Name"]
    m["instances"][instance_id] = inst
    return inst


def _run_instances(store, params):
    m = _model(store)
    tag_specs = _parse_tag_specifications(params)
    count = max(1, int(params.get("MaxCount") or params.get("MinCount") or 1))
    insts = [_launch_one(m, params, tag_specs, i) for i in range(count)]
    items = "".join(_instance_xml(i) for i in insts)
    return _envelope("RunInstances",
                      f"<reservationId>{_rid('r')}</reservationId><ownerId>{OWNER_ID}</ownerId>"
                      f"<groupSet/><instancesSet>{items}</instancesSet>")


def _find_instance(m, instance_id) -> dict:
    inst = m["instances"].get(str(instance_id))
    if inst is None:
        raise VpcError("InvalidInstanceID.NotFound", f"The instance ID '{instance_id}' does not exist.", 400)
    return inst


def _describe_instances(store, params):
    m = _model(store)
    ids = [v for k, v in params.items() if k.startswith("InstanceId.") or k.startswith("InstanceIds.")]
    rows = [m["instances"][i] for i in ids if i in m["instances"]] if ids else list(m["instances"].values())
    items = "".join(f"<item><reservationId>{_rid('r')}</reservationId><ownerId>{OWNER_ID}</ownerId>"
                     f"<groupSet/><instancesSet>{_instance_xml(r)}</instancesSet></item>" for r in rows)
    return _envelope("DescribeInstances", f"<reservationSet>{items}</reservationSet>")


def _instance_state_change(store, params, action, target_state):
    m = _model(store)
    ids = [v for k, v in params.items() if k.startswith("InstanceId.")]
    force = str(params.get("Force", "")).lower() == "true"
    items = []
    for iid in ids:
        inst = _find_instance(m, iid)
        prev = inst["state"]
        if action == "terminate" and inst.get("termination_protection") and not force:
            raise VpcError("OperationNotPermitted", f"The instance '{iid}' may not be terminated. Modify its 'disableApiTermination' instance attribute and try again.")
        if action == "stop" and inst.get("stop_protection") and not force:
            raise VpcError("OperationNotPermitted", f"The instance '{iid}' may not be stopped. Modify its 'disableApiStop' instance attribute and try again.")
        inst["state"] = target_state
        if action == "stop":
            inst["public_ip"] = "" if not inst.get("elastic_ip") else inst["public_ip"]
        if action == "start":
            n = len(m["instances"])
            if not inst.get("elastic_ip"):
                inst["public_ip"] = _pseudo_public_ip(n)
                inst["public_dns"] = f"ec2-{inst['public_ip'].replace('.', '-')}.compute-1.amazonaws.com"
        if action == "terminate":
            for bd in inst.get("block_devices", []):
                vol = m["volumes"].get(bd["volume_id"])
                if vol and bd.get("delete_on_termination", True):
                    m["volumes"].pop(bd["volume_id"], None)
                elif vol:
                    vol["attachments"] = []
                    vol["state"] = "available"
        items.append(f"<item><instanceId>{_xml_escape(iid)}</instanceId>"
                     f"<previousState><code>{_STATE_CODE.get(prev, 0)}</code><name>{_xml_escape(prev)}</name></previousState>"
                     f"<currentState><code>{_STATE_CODE.get(inst['state'], 0)}</code><name>{_xml_escape(inst['state'])}</name></currentState></item>")
    tag = {"stop": "StoppingInstances", "start": "StartingInstances", "terminate": "TerminatingInstances"}[action]
    return _envelope(action.capitalize() + "Instances", f"<{tag}>{''.join(items)}</{tag}>")


def _reboot_instances(store, params):
    m = _model(store)
    for k, v in params.items():
        if k.startswith("InstanceId."):
            _find_instance(m, v)
    return _envelope("RebootInstances", "<return>true</return>")


def _modify_instance_attribute(store, params):
    m = _model(store)
    inst = _find_instance(m, params.get("InstanceId"))
    if "DisableApiTermination.Value" in params:
        inst["termination_protection"] = str(params["DisableApiTermination.Value"]).lower() == "true"
    if "DisableApiStop.Value" in params:
        inst["stop_protection"] = str(params["DisableApiStop.Value"]).lower() == "true"
    if "InstanceInitiatedShutdownBehavior.Value" in params:
        inst["shutdown_behavior"] = str(params["InstanceInitiatedShutdownBehavior.Value"])
    if "InstanceType.Value" in params:
        inst["instance_type"] = str(params["InstanceType.Value"])
    if "EbsOptimized.Value" in params:
        inst["ebs_optimized"] = str(params["EbsOptimized.Value"]).lower() == "true"
    groups = [v for k, v in params.items() if k.startswith("GroupId.")]
    if groups:
        inst["sg_ids"] = groups
    return _envelope("ModifyInstanceAttribute", "<return>true</return>")


def _monitor_instances(store, params, enabled):
    m = _model(store)
    items = []
    for k, v in params.items():
        if k.startswith("InstanceId."):
            inst = _find_instance(m, v)
            inst["monitoring"] = enabled
            items.append(f"<item><instanceId>{_xml_escape(v)}</instanceId><monitoring><state>{'enabled' if enabled else 'disabled'}</state></monitoring></item>")
    tag = "instancesSet"
    return _envelope("MonitorInstances" if enabled else "UnmonitorInstances", f"<{tag}>{''.join(items)}</{tag}>")


# ── AMIs ────────────────────────────────────────────────────────────────
def _image_xml(img: dict) -> str:
    bdm = "".join(f"<item><deviceName>{_xml_escape(bd['device_name'])}</deviceName>"
                  f"<ebs><snapshotId>{_xml_escape(bd['snapshot_id'])}</snapshotId><volumeSize>{bd['size']}</volumeSize>"
                  f"<volumeType>{_xml_escape(bd['volume_type'])}</volumeType>"
                  f"<deleteOnTermination>{str(bd.get('delete_on_termination', True)).lower()}</deleteOnTermination></ebs></item>"
                  for bd in img.get("block_devices", []))
    perms = "".join(f"<item><userId>{_xml_escape(u)}</userId></item>" for u in img.get("launch_permissions", []))
    return ("<item>"
            f"<imageId>{_xml_escape(img['id'])}</imageId><imageType>machine</imageType>"
            f"<name>{_xml_escape(img['name'])}</name><description>{_xml_escape(img.get('description', ''))}</description>"
            f"<imageOwnerId>{_xml_escape(img['owner_id'])}</imageOwnerId><isPublic>{str(img.get('public', False)).lower()}</isPublic>"
            f"<imageState>{_xml_escape(img['state'])}</imageState><architecture>{_xml_escape(img['architecture'])}</architecture>"
            f"<platformDetails>{_xml_escape('Windows' if img.get('platform') == 'windows' else 'Linux/UNIX')}</platformDetails>"
            f"<rootDeviceType>{_xml_escape(img['root_device_type'])}</rootDeviceType><rootDeviceName>{_xml_escape(img['root_device_name'])}</rootDeviceName>"
            f"<virtualizationType>{_xml_escape(img['virtualization_type'])}</virtualizationType>"
            f"<creationDate>{_xml_escape(img['creation_date'])}</creationDate>"
            f"<blockDeviceMapping>{bdm}</blockDeviceMapping><launchPermission>{perms}</launchPermission>"
            f"{_tags_xml(img.get('tags', {}))}"
            "</item>")


def _create_image(store, params):
    m = _model(store)
    inst = _find_instance(m, params.get("InstanceId"))
    image_id = "ami-" + uuid.uuid4().hex[:17]
    bds = []
    for bd in inst.get("block_devices", []):
        vol = m["volumes"].get(bd["volume_id"], {})
        snap_id = _rid("snap")
        m["snapshots"][snap_id] = {"id": snap_id, "volume_id": bd["volume_id"], "volume_size": vol.get("size", 8),
                                   "description": f"Created by CreateImage({inst['id']}) for {image_id}",
                                   "state": "completed", "progress": "100%", "started": _now(),
                                   "encrypted": vol.get("encrypted", False), "kms_key_id": vol.get("kms_key_id", ""),
                                   "owner_id": OWNER_ID, "tags": {}}
        bds.append({"device_name": bd["device_name"], "snapshot_id": snap_id, "size": vol.get("size", 8),
                    "volume_type": vol.get("type", "gp3"), "delete_on_termination": True})
    m["images"][image_id] = {
        "id": image_id, "name": str(params.get("Name") or f"image-{image_id}"), "description": str(params.get("Description") or ""),
        "owner_id": OWNER_ID, "public": False, "state": "available", "architecture": inst.get("architecture", "x86_64"),
        "platform": inst.get("platform", ""), "root_device_type": "ebs", "root_device_name": inst.get("root_device_name", "/dev/xvda"),
        "virtualization_type": inst.get("virtualization_type", "hvm"), "creation_date": _now(), "source": inst["id"],
        "tags": _parse_tag_specifications(params).get("image", {}), "launch_permissions": [], "block_devices": bds,
    }
    return _envelope("CreateImage", f"<imageId>{_xml_escape(image_id)}</imageId>")


def _describe_images(store, params):
    m = _model(store)
    _seed_amis(m)
    ids = [v for k, v in params.items() if k.startswith("ImageId.")]
    owners = [v for k, v in params.items() if k.startswith("Owner.")]
    rows = list(m["images"].values())
    if ids:
        rows = [i for i in rows if i["id"] in ids]
    if owners:
        rows = [i for i in rows if ("self" in owners and i["owner_id"] == OWNER_ID) or i["owner_id"] in owners]
    items = "".join(_image_xml(i) for i in rows)
    return _envelope("DescribeImages", f"<imagesSet>{items}</imagesSet>")


def _deregister_image(store, params):
    m = _model(store)
    image_id = str(params.get("ImageId"))
    if image_id not in m["images"]:
        raise VpcError("InvalidAMIID.NotFound", f"The image id '[{image_id}]' does not exist.")
    m["images"].pop(image_id)
    return _envelope("DeregisterImage", "<return>true</return>")


def _copy_image(store, params):
    m = _model(store)
    src = m["images"].get(str(params.get("SourceImageId")))
    if src is None:
        raise VpcError("InvalidAMIID.NotFound", "Source AMI not found.")
    image_id = "ami-" + uuid.uuid4().hex[:17]
    m["images"][image_id] = {**src, "id": image_id, "name": str(params.get("Name") or f"{src['name']} - copy"),
                             "owner_id": OWNER_ID, "public": False, "source": src["id"], "creation_date": _now(), "tags": {}}
    return _envelope("CopyImage", f"<imageId>{_xml_escape(image_id)}</imageId>")


def _modify_image_attribute(store, params):
    m = _model(store)
    img = m["images"].get(str(params.get("ImageId")))
    if img is None:
        raise VpcError("InvalidAMIID.NotFound", "AMI not found.")
    for k, v in params.items():
        if k.startswith("LaunchPermission.Add.") and k.endswith(".UserId"):
            if v not in img["launch_permissions"]:
                img["launch_permissions"].append(str(v))
        if k.startswith("LaunchPermission.Remove.") and k.endswith(".UserId") and v in img["launch_permissions"]:
            img["launch_permissions"].remove(str(v))
    return _envelope("ModifyImageAttribute", "<return>true</return>")


# ── EBS volumes & snapshots ────────────────────────────────────────────
def _volume_xml(v: dict) -> str:
    atts = "".join(f"<item><volumeId>{_xml_escape(v['id'])}</volumeId><instanceId>{_xml_escape(a['instance_id'])}</instanceId>"
                   f"<device>{_xml_escape(a['device'])}</device><status>attached</status>"
                   f"<attachTime>{_xml_escape(a['attach_time'])}</attachTime>"
                   f"<deleteOnTermination>{str(a.get('delete_on_termination', True)).lower()}</deleteOnTermination></item>" for a in v.get("attachments", []))
    return ("<item>"
            f"<volumeId>{_xml_escape(v['id'])}</volumeId><size>{v['size']}</size><volumeType>{_xml_escape(v['type'])}</volumeType>"
            f"<snapshotId>{_xml_escape(v.get('snapshot_id', ''))}</snapshotId><availabilityZone>{_xml_escape(v['az'])}</availabilityZone>"
            f"<status>{_xml_escape(v['state'])}</status><createTime>{_xml_escape(v['created'])}</createTime>"
            f"<encrypted>{str(v.get('encrypted', False)).lower()}</encrypted><kmsKeyId>{_xml_escape(v.get('kms_key_id', ''))}</kmsKeyId>"
            f"<iops>{v.get('iops') or ''}</iops><throughput>{v.get('throughput') or ''}</throughput>"
            f"<multiAttachEnabled>{str(v.get('multi_attach', False)).lower()}</multiAttachEnabled>"
            f"<attachmentSet>{atts}</attachmentSet>{_tags_xml(v.get('tags', {}))}"
            "</item>")


def _create_volume(store, params):
    m = _model(store)
    vol_id = _rid("vol")
    encrypted = str(params.get("Encrypted", "")).lower() == "true" or m["account"]["ebs_encryption_by_default"]
    vol_type = str(params.get("VolumeType") or "gp3")
    snap_id = str(params.get("SnapshotId") or "")
    size = int(params.get("Size") or (m["snapshots"].get(snap_id, {}).get("volume_size", 8) if snap_id else 8))
    m["volumes"][vol_id] = {
        "id": vol_id, "size": size, "type": vol_type,
        "iops": int(params["Iops"]) if params.get("Iops") else (3000 if vol_type == "gp3" else None),
        "throughput": int(params["Throughput"]) if params.get("Throughput") else (125 if vol_type == "gp3" else None),
        "az": str(params.get("AvailabilityZone") or _AZS[0]), "state": "available", "snapshot_id": snap_id,
        "encrypted": encrypted, "kms_key_id": str(params.get("KmsKeyId") or (m["account"]["ebs_default_kms_key_id"] if encrypted else "")),
        "multi_attach": str(params.get("MultiAttachEnabled", "")).lower() == "true", "created": _now(),
        "tags": _parse_tag_specifications(params).get("volume", {}), "attachments": [],
    }
    return _envelope("CreateVolume", _volume_xml(m["volumes"][vol_id]).replace("<item>", "").replace("</item>", ""))


def _find_volume(m, vid) -> dict:
    vol = m["volumes"].get(str(vid))
    if vol is None:
        raise VpcError("InvalidVolume.NotFound", f"The volume '{vid}' does not exist.")
    return vol


def _describe_volumes(store, params):
    m = _model(store)
    ids = [v for k, v in params.items() if k.startswith("VolumeId.")]
    rows = [m["volumes"][i] for i in ids if i in m["volumes"]] if ids else list(m["volumes"].values())
    return _envelope("DescribeVolumes", f"<volumeSet>{''.join(_volume_xml(v) for v in rows)}</volumeSet>")


def _attach_volume(store, params):
    m = _model(store)
    vol = _find_volume(m, params.get("VolumeId"))
    inst = _find_instance(m, params.get("InstanceId"))
    device = str(params.get("Device") or "/dev/sdf")
    att = {"instance_id": inst["id"], "device": device, "delete_on_termination": False, "attach_time": _now()}
    vol["attachments"].append(att)
    vol["state"] = "in-use"
    inst["block_devices"].append({"device_name": device, "volume_id": vol["id"], "delete_on_termination": False})
    return _envelope("AttachVolume", f"<volumeId>{_xml_escape(vol['id'])}</volumeId><instanceId>{_xml_escape(inst['id'])}</instanceId>"
                                     f"<device>{_xml_escape(device)}</device><status>attached</status>")


def _detach_volume(store, params):
    m = _model(store)
    vol = _find_volume(m, params.get("VolumeId"))
    instance_id = params.get("InstanceId")
    removed = None
    for a in list(vol["attachments"]):
        if instance_id is None or a["instance_id"] == str(instance_id):
            vol["attachments"].remove(a)
            removed = a
            inst = m["instances"].get(a["instance_id"])
            if inst:
                inst["block_devices"] = [bd for bd in inst["block_devices"] if bd["volume_id"] != vol["id"]]
            break
    if not vol["attachments"]:
        vol["state"] = "available"
    return _envelope("DetachVolume", f"<volumeId>{_xml_escape(vol['id'])}</volumeId>"
                                     f"<instanceId>{_xml_escape((removed or {}).get('instance_id', ''))}</instanceId>"
                                     f"<device>{_xml_escape((removed or {}).get('device', ''))}</device><status>detached</status>")


def _delete_volume(store, params):
    m = _model(store)
    vol = _find_volume(m, params.get("VolumeId"))
    if vol["attachments"]:
        raise VpcError("VolumeInUse", f"Volume {vol['id']} is currently attached to an instance.")
    m["volumes"].pop(vol["id"])
    return _envelope("DeleteVolume", "<return>true</return>")


def _modify_volume(store, params):
    m = _model(store)
    vol = _find_volume(m, params.get("VolumeId"))
    if params.get("Size"):
        vol["size"] = int(params["Size"])
    if params.get("VolumeType"):
        vol["type"] = str(params["VolumeType"])
    if params.get("Iops"):
        vol["iops"] = int(params["Iops"])
    if params.get("Throughput"):
        vol["throughput"] = int(params["Throughput"])
    return _envelope("ModifyVolume", f"<volumeModification><volumeId>{_xml_escape(vol['id'])}</volumeId>"
                                     f"<modificationState>completed</modificationState><targetSize>{vol['size']}</targetSize>"
                                     f"<targetVolumeType>{_xml_escape(vol['type'])}</targetVolumeType></volumeModification>")


def _snapshot_xml(s: dict) -> str:
    return ("<item>"
            f"<snapshotId>{_xml_escape(s['id'])}</snapshotId><volumeId>{_xml_escape(s['volume_id'])}</volumeId>"
            f"<volumeSize>{s['volume_size']}</volumeSize><description>{_xml_escape(s.get('description', ''))}</description>"
            f"<status>{_xml_escape(s['state'])}</status><progress>{_xml_escape(s['progress'])}</progress>"
            f"<startTime>{_xml_escape(s['started'])}</startTime><ownerId>{_xml_escape(s['owner_id'])}</ownerId>"
            f"<encrypted>{str(s.get('encrypted', False)).lower()}</encrypted><kmsKeyId>{_xml_escape(s.get('kms_key_id', ''))}</kmsKeyId>"
            f"{_tags_xml(s.get('tags', {}))}"
            "</item>")


def _create_snapshot(store, params):
    m = _model(store)
    vol = _find_volume(m, params.get("VolumeId"))
    snap_id = _rid("snap")
    m["snapshots"][snap_id] = {"id": snap_id, "volume_id": vol["id"], "volume_size": vol["size"],
                               "description": str(params.get("Description") or ""), "state": "completed", "progress": "100%",
                               "started": _now(), "encrypted": vol.get("encrypted", False), "kms_key_id": vol.get("kms_key_id", ""),
                               "owner_id": OWNER_ID, "tags": _parse_tag_specifications(params).get("snapshot", {})}
    vol["snapshot_id"] = snap_id
    return _envelope("CreateSnapshot", _snapshot_xml(m["snapshots"][snap_id]).replace("<item>", "").replace("</item>", ""))


def _describe_snapshots(store, params):
    m = _model(store)
    ids = [v for k, v in params.items() if k.startswith("SnapshotId.")]
    owners = [v for k, v in params.items() if k.startswith("Owner.")]
    rows = [m["snapshots"][i] for i in ids if i in m["snapshots"]] if ids else list(m["snapshots"].values())
    if owners:
        rows = [s for s in rows if ("self" in owners and s["owner_id"] == OWNER_ID) or s["owner_id"] in owners]
    return _envelope("DescribeSnapshots", f"<snapshotSet>{''.join(_snapshot_xml(s) for s in rows)}</snapshotSet>")


def _delete_snapshot(store, params):
    m = _model(store)
    sid = str(params.get("SnapshotId"))
    if sid not in m["snapshots"]:
        raise VpcError("InvalidSnapshot.NotFound", f"The snapshot '{sid}' does not exist.")
    m["snapshots"].pop(sid)
    return _envelope("DeleteSnapshot", "<return>true</return>")


def _copy_snapshot(store, params):
    m = _model(store)
    src = m["snapshots"].get(str(params.get("SourceSnapshotId")))
    if src is None:
        raise VpcError("InvalidSnapshot.NotFound", "Source snapshot not found.")
    snap_id = _rid("snap")
    m["snapshots"][snap_id] = {**src, "id": snap_id, "description": str(params.get("Description") or f"Copy of {src['id']}"),
                               "started": _now(), "owner_id": OWNER_ID, "tags": {}}
    return _envelope("CopySnapshot", f"<snapshotId>{_xml_escape(snap_id)}</snapshotId>")


# ── key pairs ───────────────────────────────────────────────────────────
def _keypair_fingerprint(seed: str) -> str:
    import hashlib
    h = hashlib.sha256(seed.encode()).hexdigest()[:40]
    return ":".join(h[i:i + 2] for i in range(0, 40, 2))


def _keypair_xml(kp: dict) -> str:
    return ("<item>"
            f"<keyName>{_xml_escape(kp['name'])}</keyName><keyPairId>{_xml_escape(kp['id'])}</keyPairId>"
            f"<keyFingerprint>{_xml_escape(kp['fingerprint'])}</keyFingerprint><keyType>{_xml_escape(kp['type'])}</keyType>"
            f"<createTime>{_xml_escape(kp['created'])}</createTime>{_tags_xml(kp.get('tags', {}))}"
            "</item>")


def _create_key_pair(store, params):
    m = _model(store)
    name = str(params.get("KeyName"))
    if any(kp["name"] == name for kp in m["key_pairs"].values()):
        raise VpcError("InvalidKeyPair.Duplicate", f"The keypair '{name}' already exists.")
    kp_id = _rid("key")
    material = "-----BEGIN RSA PRIVATE KEY-----\n" + uuid.uuid4().hex + uuid.uuid4().hex + "\n-----END RSA PRIVATE KEY-----"
    kp = {"id": kp_id, "name": name, "type": str(params.get("KeyType") or "rsa"),
          "fingerprint": _keypair_fingerprint(kp_id), "created": _now(), "tags": _parse_tag_specifications(params).get("key-pair", {})}
    m["key_pairs"][kp_id] = kp
    return _envelope("CreateKeyPair", f"<keyName>{_xml_escape(name)}</keyName><keyPairId>{_xml_escape(kp_id)}</keyPairId>"
                                      f"<keyFingerprint>{_xml_escape(kp['fingerprint'])}</keyFingerprint>"
                                      f"<keyMaterial>{_xml_escape(material)}</keyMaterial>")


def _import_key_pair(store, params):
    m = _model(store)
    name = str(params.get("KeyName"))
    if any(kp["name"] == name for kp in m["key_pairs"].values()):
        raise VpcError("InvalidKeyPair.Duplicate", f"The keypair '{name}' already exists.")
    kp_id = _rid("key")
    material = str(params.get("PublicKeyMaterial") or "")
    kp = {"id": kp_id, "name": name, "type": "rsa", "fingerprint": _keypair_fingerprint(material or kp_id),
          "created": _now(), "tags": _parse_tag_specifications(params).get("key-pair", {})}
    m["key_pairs"][kp_id] = kp
    return _envelope("ImportKeyPair", f"<keyName>{_xml_escape(name)}</keyName><keyPairId>{_xml_escape(kp_id)}</keyPairId>"
                                      f"<keyFingerprint>{_xml_escape(kp['fingerprint'])}</keyFingerprint>")


def _describe_key_pairs(store, params):
    m = _model(store)
    names = [v for k, v in params.items() if k.startswith("KeyName.")]
    rows = [kp for kp in m["key_pairs"].values() if not names or kp["name"] in names]
    return _envelope("DescribeKeyPairs", f"<keySet>{''.join(_keypair_xml(kp) for kp in rows)}</keySet>")


def _delete_key_pair(store, params):
    m = _model(store)
    name = params.get("KeyName")
    kp_id = params.get("KeyPairId")
    target = next((k for k, kp in m["key_pairs"].items() if (name and kp["name"] == name) or (kp_id and k == kp_id)), None)
    if target:
        m["key_pairs"].pop(target)
    return _envelope("DeleteKeyPair", "<return>true</return>")


# ── elastic IPs ─────────────────────────────────────────────────────────
def _address_xml(a: dict) -> str:
    return ("<item>"
            f"<publicIp>{_xml_escape(a['public_ip'])}</publicIp><allocationId>{_xml_escape(a['allocation_id'])}</allocationId>"
            f"<domain>{_xml_escape(a['domain'])}</domain><instanceId>{_xml_escape(a.get('instance_id', ''))}</instanceId>"
            f"<associationId>{_xml_escape(a.get('association_id', ''))}</associationId>"
            f"<networkInterfaceId>{_xml_escape(a.get('network_interface_id', ''))}</networkInterfaceId>"
            f"<privateIpAddress>{_xml_escape(a.get('private_ip', ''))}</privateIpAddress>"
            f"<networkBorderGroup>{_xml_escape(a.get('network_border_group', 'us-east-1'))}</networkBorderGroup>"
            f"{_tags_xml(a.get('tags', {}))}"
            "</item>")


def _allocate_address(store, params):
    m = _model(store)
    alloc_id = _rid("eipalloc")
    n = len(m["addresses"])
    a = {"allocation_id": alloc_id, "public_ip": _pseudo_public_ip(n + 1000), "domain": "vpc",
         "instance_id": "", "association_id": "", "network_interface_id": "", "private_ip": "",
         "network_border_group": str(params.get("NetworkBorderGroup") or "us-east-1"),
         "tags": _parse_tag_specifications(params).get("elastic-ip", {})}
    m["addresses"][alloc_id] = a
    return _envelope("AllocateAddress", f"<publicIp>{_xml_escape(a['public_ip'])}</publicIp><allocationId>{_xml_escape(alloc_id)}</allocationId><domain>vpc</domain>")


def _describe_addresses(store, params):
    m = _model(store)
    return _envelope("DescribeAddresses", f"<addressesSet>{''.join(_address_xml(a) for a in m['addresses'].values())}</addressesSet>")


def _associate_address(store, params):
    m = _model(store)
    a = m["addresses"].get(str(params.get("AllocationId")))
    if a is None:
        raise VpcError("InvalidAllocationID.NotFound", "Elastic IP allocation not found.")
    inst = _find_instance(m, params.get("InstanceId"))
    a["instance_id"] = inst["id"]
    a["association_id"] = _rid("eipassoc")
    a["private_ip"] = inst.get("private_ip", "")
    inst["public_ip"] = a["public_ip"]
    inst["public_dns"] = f"ec2-{a['public_ip'].replace('.', '-')}.compute-1.amazonaws.com"
    inst["elastic_ip"] = a["allocation_id"]
    return _envelope("AssociateAddress", f"<associationId>{_xml_escape(a['association_id'])}</associationId>")


def _disassociate_address(store, params):
    m = _model(store)
    assoc_id = params.get("AssociationId")
    a = next((x for x in m["addresses"].values() if x.get("association_id") == assoc_id), None)
    if a is None:
        raise VpcError("InvalidAssociationID.NotFound", "Association not found.")
    inst = m["instances"].get(a["instance_id"])
    if inst:
        inst["public_ip"] = ""
        inst.pop("elastic_ip", None)
    a["instance_id"] = ""; a["association_id"] = ""; a["private_ip"] = ""
    return _envelope("DisassociateAddress", "<return>true</return>")


def _release_address(store, params):
    m = _model(store)
    alloc_id = str(params.get("AllocationId"))
    a = m["addresses"].get(alloc_id)
    if a is None:
        raise VpcError("InvalidAllocationID.NotFound", "Elastic IP allocation not found.")
    if a.get("instance_id"):
        raise VpcError("AuthFailure", "Address is still associated; disassociate it first.")
    m["addresses"].pop(alloc_id)
    return _envelope("ReleaseAddress", "<return>true</return>")


# ── network interfaces ─────────────────────────────────────────────────
def _eni_xml(e: dict) -> str:
    sgs = "".join(f"<item><groupId>{_xml_escape(g)}</groupId></item>" for g in e.get("sg_ids", []))
    att = e.get("attachment") or {}
    att_xml = f"<attachment><instanceId>{_xml_escape(att.get('instance_id', ''))}</instanceId><deviceIndex>{att.get('device_index', 0)}</deviceIndex><status>{'attached' if att else 'detached'}</status></attachment>" if att else ""
    return ("<item>"
            f"<networkInterfaceId>{_xml_escape(e['id'])}</networkInterfaceId><subnetId>{_xml_escape(e['subnet_id'])}</subnetId>"
            f"<vpcId>{_xml_escape(e['vpc_id'])}</vpcId><availabilityZone>{_xml_escape(e['az'])}</availabilityZone>"
            f"<description>{_xml_escape(e.get('description', ''))}</description><status>{_xml_escape(e['status'])}</status>"
            f"<privateIpAddress>{_xml_escape(e['private_ip'])}</privateIpAddress><association><publicIp>{_xml_escape(e.get('public_ip', ''))}</publicIp></association>"
            f"<groupSet>{sgs}</groupSet>{att_xml}{_tags_xml(e.get('tags', {}))}"
            "</item>")


def _create_network_interface(store, params):
    m = _model(store)
    subnet_id = str(params.get("SubnetId"))
    subnet = m["subnets"].get(subnet_id)
    if subnet is None:
        raise VpcError("InvalidSubnetID.NotFound", f"The subnet '{subnet_id}' does not exist.")
    eni_id = _rid("eni")
    sgs = [v for k, v in params.items() if k.startswith("SecurityGroupId.")]
    n = len(m["enis"])
    e = {"id": eni_id, "subnet_id": subnet_id, "vpc_id": subnet["vpc_id"], "az": subnet.get("az", _AZS[0]),
         "description": str(params.get("Description") or ""), "status": "available",
         "private_ip": _pseudo_ip(n, base=(10, 0, 2)), "public_ip": "", "sg_ids": sgs, "attachment": None,
         "tags": _parse_tag_specifications(params).get("network-interface", {})}
    m["enis"][eni_id] = e
    return _envelope("CreateNetworkInterface", _eni_xml(e).replace("<item>", "<networkInterface>").replace("</item>", "</networkInterface>"))


def _describe_network_interfaces(store, params):
    m = _model(store)
    return _envelope("DescribeNetworkInterfaces", f"<networkInterfaceSet>{''.join(_eni_xml(e) for e in m['enis'].values())}</networkInterfaceSet>")


def _delete_network_interface(store, params):
    m = _model(store)
    eni_id = str(params.get("NetworkInterfaceId"))
    e = m["enis"].get(eni_id)
    if e is None:
        raise VpcError("InvalidNetworkInterfaceID.NotFound", f"The network interface '{eni_id}' does not exist.")
    if e.get("attachment"):
        raise VpcError("InvalidParameterValue", "Network interface is attached; detach it first.")
    m["enis"].pop(eni_id)
    return _envelope("DeleteNetworkInterface", "<return>true</return>")


def _attach_network_interface(store, params):
    m = _model(store)
    e = m["enis"].get(str(params.get("NetworkInterfaceId")))
    if e is None:
        raise VpcError("InvalidNetworkInterfaceID.NotFound", "Network interface not found.")
    inst = _find_instance(m, params.get("InstanceId"))
    att_id = _rid("eni-attach")
    e["attachment"] = {"id": att_id, "instance_id": inst["id"], "device_index": int(params.get("DeviceIndex") or 1)}
    e["status"] = "in-use"
    return _envelope("AttachNetworkInterface", f"<attachmentId>{_xml_escape(att_id)}</attachmentId>")


def _detach_network_interface(store, params):
    m = _model(store)
    att_id = params.get("AttachmentId")
    e = next((x for x in m["enis"].values() if (x.get("attachment") or {}).get("id") == att_id), None)
    if e is None:
        raise VpcError("InvalidAttachmentID.NotFound", "Attachment not found.")
    e["attachment"] = None
    e["status"] = "available"
    return _envelope("DetachNetworkInterface", "<return>true</return>")


# ── security groups: describe / delete / revoke (create + authorize already above) ──
def _perm_xml(p: dict) -> str:
    cidrs = "".join(f"<item><cidrIp>{_xml_escape(c)}</cidrIp></item>" for c in p.get("cidrs", []))
    groups = "".join(f"<item><groupId>{_xml_escape(g)}</groupId></item>" for g in p.get("sgs", []))
    ports = f"<fromPort>{p['from_port']}</fromPort><toPort>{p['to_port']}</toPort>" if p.get("from_port") is not None else ""
    return (f"<item><ipProtocol>{_xml_escape(p['protocol'])}</ipProtocol>{ports}"
            f"<ipRanges>{cidrs}</ipRanges><groups>{groups}</groups>"
            f"<securityGroupRuleId>{_xml_escape(p.get('rule_id', ''))}</securityGroupRuleId>"
            f"<description>{_xml_escape(p.get('description', ''))}</description></item>")


def _find_sg(m, group_id) -> dict:
    sg = m["sgs"].get(str(group_id))
    if sg is None:
        raise VpcError("InvalidGroup.NotFound", f"The security group '{group_id}' does not exist.")
    return sg


def _sg_xml(sg: dict) -> str:
    ingress = "".join(_perm_xml(p) for p in sg.get("ingress", []))
    egress = "".join(_perm_xml(p) for p in sg.get("egress", []))
    return ("<item>"
            f"<groupId>{_xml_escape(sg['id'])}</groupId><groupName>{_xml_escape(sg.get('name', ''))}</groupName>"
            f"<groupDescription>{_xml_escape(sg.get('description', ''))}</groupDescription><vpcId>{_xml_escape(sg['vpc_id'])}</vpcId>"
            f"<ownerId>{OWNER_ID}</ownerId><ipPermissions>{ingress}</ipPermissions><ipPermissionsEgress>{egress}</ipPermissionsEgress>"
            f"{_tags_xml(sg.get('tags', {}))}"
            "</item>")


def _describe_security_groups(store, params):
    m = _model(store)
    _ensure_default_network(m)
    ids = [v for k, v in params.items() if k.startswith("GroupId.")]
    names = [v for k, v in params.items() if k.startswith("GroupName.")]
    rows = list(m["sgs"].values())
    if ids:
        rows = [sg for sg in rows if sg["id"] in ids]
    elif names:
        rows = [sg for sg in rows if sg.get("name") in names]
    return _envelope("DescribeSecurityGroups", f"<securityGroupInfo>{''.join(_sg_xml(sg) for sg in rows)}</securityGroupInfo>")


def _delete_security_group(store, params):
    m = _model(store)
    sg = _find_sg(m, params.get("GroupId"))
    if sg.get("is_default"):
        raise VpcError("CannotDelete", "The default security group cannot be deleted.")
    for inst in m["instances"].values():
        if sg["id"] in inst.get("sg_ids", []):
            raise VpcError("DependencyViolation", f"resource {sg['id']} has a dependent object (in use by {inst['id']}).")
    m["sgs"].pop(sg["id"])
    return _envelope("DeleteSecurityGroup", "<return>true</return>")


def _revoke(store, params, direction):
    m = _model(store)
    sg = _find_sg(m, params.get("GroupId"))
    key = "ingress" if direction == "ingress" else "egress"
    rule_ids = [v for k, v in params.items() if k.startswith("SecurityGroupRuleId.")]
    if rule_ids:
        sg[key] = [r for r in sg[key] if r.get("rule_id") not in rule_ids]
    else:
        perms = _parse_ip_permissions(params)
        if not perms and params.get("IpProtocol"):
            perms = [{"protocol": str(params["IpProtocol"]), "from_port": int(params.get("FromPort", 0) or 0),
                     "to_port": int(params.get("ToPort", 0) or 0),
                     "cidrs": [params["CidrIp"]] if params.get("CidrIp") else [],
                     "sgs": [params["SourceSecurityGroupId"]] if params.get("SourceSecurityGroupId") else []}]

        def _hit(r, p):
            return (r["protocol"] == p["protocol"] and r.get("from_port") == p.get("from_port") and r.get("to_port") == p.get("to_port")
                    and (set(r.get("cidrs", [])) & set(p.get("cidrs", [])) or set(r.get("sgs", [])) & set(p.get("sgs", []))))
        sg[key] = [r for r in sg[key] if not any(_hit(r, p) for p in perms)]
    action = "RevokeSecurityGroupIngress" if direction == "ingress" else "RevokeSecurityGroupEgress"
    return _envelope(action, "<return>true</return>")


# ── placement groups ────────────────────────────────────────────────────
def _pg_xml(pg: dict) -> str:
    return ("<item>"
            f"<groupName>{_xml_escape(pg['name'])}</groupName><groupId>{_xml_escape(pg['id'])}</groupId>"
            f"<strategy>{_xml_escape(pg['strategy'])}</strategy><state>{_xml_escape(pg['state'])}</state>"
            f"<partitionCount>{pg.get('partition_count') or 0}</partitionCount><groupArn>{_xml_escape(pg['arn'])}</groupArn>"
            f"{_tags_xml(pg.get('tags', {}))}"
            "</item>")


def _create_placement_group(store, params):
    m = _model(store)
    name = str(params.get("GroupName") or f"pg-{uuid.uuid4().hex[:6]}")
    pg_id = _rid("pg")
    pg = {"id": pg_id, "name": name, "strategy": str(params.get("Strategy") or "cluster"), "state": "available",
          "partition_count": int(params["PartitionCount"]) if params.get("PartitionCount") else None,
          "arn": f"arn:aws:ec2:us-east-1:{OWNER_ID}:placement-group/{name}", "tags": _parse_tag_specifications(params).get("placement-group", {})}
    m["placement_groups"][pg_id] = pg
    return _envelope("CreatePlacementGroup", _pg_xml(pg).replace("<item>", "").replace("</item>", ""))


def _describe_placement_groups(store, params):
    m = _model(store)
    return _envelope("DescribePlacementGroups", f"<placementGroupSet>{''.join(_pg_xml(pg) for pg in m['placement_groups'].values())}</placementGroupSet>")


def _delete_placement_group(store, params):
    m = _model(store)
    name = str(params.get("GroupName"))
    target = next((k for k, pg in m["placement_groups"].items() if pg["name"] == name), None)
    if target is None:
        raise VpcError("InvalidPlacementGroup.Unknown", f"The placement group '{name}' is unknown.")
    m["placement_groups"].pop(target)
    return _envelope("DeletePlacementGroup", "<return>true</return>")


# ── launch templates ────────────────────────────────────────────────────
def _lt_data(params: dict) -> dict:
    return {k[len("LaunchTemplateData."):]: v for k, v in params.items() if k.startswith("LaunchTemplateData.")}


def _lt_xml(lt: dict) -> str:
    return ("<item>"
            f"<launchTemplateId>{_xml_escape(lt['id'])}</launchTemplateId><launchTemplateName>{_xml_escape(lt['name'])}</launchTemplateName>"
            f"<defaultVersionNumber>{lt['default_version']}</defaultVersionNumber><latestVersionNumber>{lt['latest_version']}</latestVersionNumber>"
            f"<createTime>{_xml_escape(lt['create_time'])}</createTime><createdBy>{_xml_escape(lt['created_by'])}</createdBy>"
            f"{_tags_xml(lt.get('tags', {}))}"
            "</item>")


def _create_launch_template(store, params):
    m = _model(store)
    name = str(params.get("LaunchTemplateName"))
    if any(lt["name"] == name for lt in m["launch_templates"].values()):
        raise VpcError("InvalidLaunchTemplateName.AlreadyExistsException", f"Launch template name '{name}' already in use.")
    lt_id = _rid("lt")
    lt = {"id": lt_id, "name": name, "default_version": 1, "latest_version": 1, "create_time": _now(),
          "created_by": f"arn:aws:iam::{OWNER_ID}:root", "tags": _parse_tag_specifications(params).get("launch-template", {}),
          "versions": {1: {"version": 1, "description": str(params.get("VersionDescription") or ""), "data": _lt_data(params)}}}
    m["launch_templates"][lt_id] = lt
    return _envelope("CreateLaunchTemplate", _lt_xml(lt).replace("<item>", "<launchTemplate>").replace("</item>", "</launchTemplate>"))


def _describe_launch_templates(store, params):
    m = _model(store)
    ids = [v for k, v in params.items() if k.startswith("LaunchTemplateId.")]
    names = [v for k, v in params.items() if k.startswith("LaunchTemplateName.")]
    rows = list(m["launch_templates"].values())
    if ids:
        rows = [lt for lt in rows if lt["id"] in ids]
    elif names:
        rows = [lt for lt in rows if lt["name"] in names]
    return _envelope("DescribeLaunchTemplates", f"<launchTemplates>{''.join(_lt_xml(lt) for lt in rows)}</launchTemplates>")


def _delete_launch_template(store, params):
    m = _model(store)
    lt_id = params.get("LaunchTemplateId")
    name = params.get("LaunchTemplateName")
    target = next((k for k, lt in m["launch_templates"].items() if (lt_id and k == lt_id) or (name and lt["name"] == name)), None)
    if target is None:
        raise VpcError("InvalidLaunchTemplateId.NotFound", "Launch template not found.")
    lt = m["launch_templates"].pop(target)
    return _envelope("DeleteLaunchTemplate", _lt_xml(lt).replace("<item>", "<launchTemplate>").replace("</item>", "</launchTemplate>"))


# ── tags (generic, any resource) ────────────────────────────────────────
def _create_tags(store, params):
    m = _model(store)
    ids = [v for k, v in params.items() if k.startswith("ResourceId.")]
    tags = _parse_flat_tags(params)
    for rid in ids:
        res = _find_resource(m, rid)
        if res is None:
            raise VpcError("InvalidID", f"The ID '{rid}' is not valid.")
        res.setdefault("tags", {}).update(tags)
        if rid in m["instances"] and tags.get("Name"):
            res["name"] = tags["Name"]
    return _envelope("CreateTags", "<return>true</return>")


def _delete_tags(store, params):
    m = _model(store)
    ids = [v for k, v in params.items() if k.startswith("ResourceId.")]
    keys = [v for k, v in params.items() if k.startswith("Tag.") and k.endswith(".Key")]
    for rid in ids:
        res = _find_resource(m, rid)
        if res is None:
            continue
        tags = res.get("tags", {})
        for key in (keys or list(tags.keys())):
            tags.pop(key, None)
    return _envelope("DeleteTags", "<return>true</return>")


def _describe_tags(store, params):
    m = _model(store)
    rows = []
    for coll in _taggable_collections(m):
        for rid, res in coll.items():
            for k, v in (res.get("tags") or {}).items():
                rows.append((rid, k, v))
    items = "".join(f"<item><resourceId>{_xml_escape(rid)}</resourceId><key>{_xml_escape(k)}</key><value>{_xml_escape(v)}</value></item>" for rid, k, v in rows)
    return _envelope("DescribeTags", f"<tagSet>{items}</tagSet>")


# ── instance types / availability zones / EBS defaults ─────────────────
def _instance_type_xml(name: str, spec: dict) -> str:
    return ("<item>"
            f"<instanceType>{_xml_escape(name)}</instanceType><currentGeneration>{str(spec.get('current_gen', True)).lower()}</currentGeneration>"
            f"<freeTierEligible>{str(spec['free_tier']).lower()}</freeTierEligible><bareMetal>false</bareMetal>"
            f"<hypervisor>{_xml_escape(spec['hypervisor'])}</hypervisor>"
            f"<vCpuInfo><defaultVCpus>{spec['vcpu']}</defaultVCpus></vCpuInfo>"
            f"<memoryInfo><sizeInMiB>{int(spec['mem'] * 1024)}</sizeInMiB></memoryInfo>"
            f"<instanceStorageInfo><encryptionSupport>unsupported</encryptionSupport></instanceStorageInfo>"
            f"<processorInfo><supportedArchitectures>{''.join(f'<item>{a}</item>' for a in spec['arch'])}</supportedArchitectures></processorInfo>"
            f"<networkInfo><networkPerformance>{_xml_escape(spec['net'])}</networkPerformance></networkInfo>"
            f"<ebsInfo><ebsOptimizedSupport>default</ebsOptimizedSupport></ebsInfo>"
            "</item>")


def _describe_instance_types(store, params):
    types = [v for k, v in params.items() if k.startswith("InstanceType.")]
    rows = {k: v for k, v in _INSTANCE_TYPES.items() if not types or k in types}
    return _envelope("DescribeInstanceTypes", f"<instanceTypeSet>{''.join(_instance_type_xml(k, v) for k, v in rows.items())}</instanceTypeSet>")


def _describe_availability_zones(store, params):
    items = "".join(f"<item><zoneName>{az}</zoneName><zoneId>{'use1-az' + str(i + 1)}</zoneId><state>available</state>"
                     f"<regionName>us-east-1</regionName></item>" for i, az in enumerate(_AZS))
    return _envelope("DescribeAvailabilityZones", f"<availabilityZoneInfo>{items}</availabilityZoneInfo>")


def _get_ebs_encryption_by_default(store, params):
    m = _model(store)
    return _envelope("GetEbsEncryptionByDefault", f"<ebsEncryptionByDefault>{str(m['account']['ebs_encryption_by_default']).lower()}</ebsEncryptionByDefault>")


def _set_ebs_encryption_by_default(store, params, enabled):
    m = _model(store)
    m["account"]["ebs_encryption_by_default"] = enabled
    action = "EnableEbsEncryptionByDefault" if enabled else "DisableEbsEncryptionByDefault"
    return _envelope(action, f"<ebsEncryptionByDefault>{str(enabled).lower()}</ebsEncryptionByDefault>")


def _get_ebs_default_kms_key_id(store, params):
    m = _model(store)
    return _envelope("GetEbsDefaultKmsKeyId", f"<kmsKeyId>{_xml_escape(m['account']['ebs_default_kms_key_id'])}</kmsKeyId>")


def _modify_ebs_default_kms_key_id(store, params):
    m = _model(store)
    m["account"]["ebs_default_kms_key_id"] = str(params.get("KmsKeyId") or "alias/aws/ebs")
    return _envelope("ModifyEbsDefaultKmsKeyId", f"<kmsKeyId>{_xml_escape(m['account']['ebs_default_kms_key_id'])}</kmsKeyId>")


def _reset_ebs_default_kms_key_id(store, params):
    m = _model(store)
    m["account"]["ebs_default_kms_key_id"] = "alias/aws/ebs"
    return _envelope("ResetEbsDefaultKmsKeyId", "<kmsKeyId>alias/aws/ebs</kmsKeyId>")


# ── dispatch (EC2 Query protocol) ──────────────────────────────────────────
_OPS = {
    "CreateVpc": _create_vpc, "CreateSubnet": _create_subnet,
    "CreateSecurityGroup": _create_security_group,
    "AuthorizeSecurityGroupIngress": lambda s, p: _authorize(s, p, "ingress"),
    "AuthorizeSecurityGroupEgress": lambda s, p: _authorize(s, p, "egress"),
    "RevokeSecurityGroupIngress": lambda s, p: _revoke(s, p, "ingress"),
    "RevokeSecurityGroupEgress": lambda s, p: _revoke(s, p, "egress"),
    "DescribeSecurityGroups": _describe_security_groups,
    "DeleteSecurityGroup": _delete_security_group,
    "CreateInternetGateway": _create_internet_gateway,
    "AttachInternetGateway": _attach_internet_gateway,
    "CreateRoute": _create_route, "DescribeVpcs": _describe_vpcs, "DescribeSubnets": _describe_subnets,
    "CreateNetworkAcl": _create_network_acl,
    "CreateNetworkAclEntry": _create_network_acl_entry,
    "AssociateNetworkAcl": _associate_network_acl,
    "AnalyzeReachability": _analyze_reachability_action,
    # instances
    "RunInstances": _run_instances, "DescribeInstances": _describe_instances,
    "StartInstances": lambda s, p: _instance_state_change(s, p, "start", "running"),
    "StopInstances": lambda s, p: _instance_state_change(s, p, "stop", "stopped"),
    "TerminateInstances": lambda s, p: _instance_state_change(s, p, "terminate", "terminated"),
    "RebootInstances": _reboot_instances,
    "ModifyInstanceAttribute": _modify_instance_attribute,
    "MonitorInstances": lambda s, p: _monitor_instances(s, p, True),
    "UnmonitorInstances": lambda s, p: _monitor_instances(s, p, False),
    "DescribeInstanceTypes": _describe_instance_types,
    "DescribeAvailabilityZones": _describe_availability_zones,
    # AMIs
    "CreateImage": _create_image, "DescribeImages": _describe_images,
    "DeregisterImage": _deregister_image, "CopyImage": _copy_image,
    "ModifyImageAttribute": _modify_image_attribute,
    # volumes & snapshots
    "CreateVolume": _create_volume, "DescribeVolumes": _describe_volumes,
    "AttachVolume": _attach_volume, "DetachVolume": _detach_volume,
    "DeleteVolume": _delete_volume, "ModifyVolume": _modify_volume,
    "CreateSnapshot": _create_snapshot, "DescribeSnapshots": _describe_snapshots,
    "DeleteSnapshot": _delete_snapshot, "CopySnapshot": _copy_snapshot,
    # key pairs
    "CreateKeyPair": _create_key_pair, "ImportKeyPair": _import_key_pair,
    "DescribeKeyPairs": _describe_key_pairs, "DeleteKeyPair": _delete_key_pair,
    # elastic IPs
    "AllocateAddress": _allocate_address, "DescribeAddresses": _describe_addresses,
    "AssociateAddress": _associate_address, "DisassociateAddress": _disassociate_address,
    "ReleaseAddress": _release_address,
    # network interfaces
    "CreateNetworkInterface": _create_network_interface, "DescribeNetworkInterfaces": _describe_network_interfaces,
    "DeleteNetworkInterface": _delete_network_interface, "AttachNetworkInterface": _attach_network_interface,
    "DetachNetworkInterface": _detach_network_interface,
    # placement groups
    "CreatePlacementGroup": _create_placement_group, "DescribePlacementGroups": _describe_placement_groups,
    "DeletePlacementGroup": _delete_placement_group,
    # launch templates
    "CreateLaunchTemplate": _create_launch_template, "DescribeLaunchTemplates": _describe_launch_templates,
    "DeleteLaunchTemplate": _delete_launch_template,
    # tags
    "CreateTags": _create_tags, "DeleteTags": _delete_tags, "DescribeTags": _describe_tags,
    # EBS account defaults
    "GetEbsEncryptionByDefault": _get_ebs_encryption_by_default,
    "EnableEbsEncryptionByDefault": lambda s, p: _set_ebs_encryption_by_default(s, p, True),
    "DisableEbsEncryptionByDefault": lambda s, p: _set_ebs_encryption_by_default(s, p, False),
    "GetEbsDefaultKmsKeyId": _get_ebs_default_kms_key_id,
    "ModifyEbsDefaultKmsKeyId": _modify_ebs_default_kms_key_id,
    "ResetEbsDefaultKmsKeyId": _reset_ebs_default_kms_key_id,
}


def dispatch(store, params: dict | None = None) -> VpcResponse:
    """Native EC2 Query-protocol router. `params` is the parsed form body
    ({"Action": "CreateVpc", "CidrBlock": "10.0.0.0/16", ...})."""
    params = params if isinstance(params, dict) else {}
    action = str(params.get("Action", "")).strip()
    op = _OPS.get(action)
    if op is None:
        return _error("InvalidAction", f"The action {action} is not implemented.", 400)
    try:
        return op(store, params)
    except VpcError as e:
        return _error(e.code, e.message, e.status)
