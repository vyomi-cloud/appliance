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
             "igws": {}, "nacls": {}}
        store._vpc_model = m
    return m


def _rid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


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
    vpc_id = str(params.get("VpcId", ""))
    m = _model(store)
    if vpc_id not in m["vpcs"]:
        raise VpcError("InvalidVpcID.NotFound", f"VPC {vpc_id} not found.")
    sg_id = _rid("sg")
    # default: deny all ingress, allow all egress (AWS SG defaults)
    m["sgs"][sg_id] = {"id": sg_id, "vpc_id": vpc_id, "ingress": [],
                       "egress": [{"protocol": "-1", "from_port": None, "to_port": None,
                                   "cidrs": ["0.0.0.0/0"], "sgs": []}]}
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
                  "sgs": [params["SourceSecurityGroupId"]] if params.get("SourceSecurityGroupId") else []}]
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
    items = "".join(f"<item><vpcId>{v['id']}</vpcId><cidrBlock>{v['cidr']}</cidrBlock>"
                    f"<state>available</state></item>" for v in _model(store)["vpcs"].values())
    return _envelope("DescribeVpcs", f"<vpcSet>{items}</vpcSet>")


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


# ── dispatch (EC2 Query protocol) ──────────────────────────────────────────
_OPS = {
    "CreateVpc": _create_vpc, "CreateSubnet": _create_subnet,
    "CreateSecurityGroup": _create_security_group,
    "AuthorizeSecurityGroupIngress": lambda s, p: _authorize(s, p, "ingress"),
    "AuthorizeSecurityGroupEgress": lambda s, p: _authorize(s, p, "egress"),
    "CreateInternetGateway": _create_internet_gateway,
    "AttachInternetGateway": _attach_internet_gateway,
    "CreateRoute": _create_route, "DescribeVpcs": _describe_vpcs,
    "CreateNetworkAcl": _create_network_acl,
    "CreateNetworkAclEntry": _create_network_acl_entry,
    "AssociateNetworkAcl": _associate_network_acl,
    "AnalyzeReachability": _analyze_reachability_action,
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
