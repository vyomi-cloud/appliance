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

from core import cloudwatch_core as _cw_core

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
             "igws": {}, "nacls": {}, "nat_gateways": {}, "eigws": {},
             "dhcp_options": {}, "prefix_lists": {}, "peering_connections": {},
             "route_servers": {}, "flow_logs": {}, "subnet_cidr_reservations": {},
             # EC2 compute/storage/network resources (same account, same Query-protocol
             # wire — boto3's "ec2" client signs ALL of this under one service).
             "instances": {}, "images": {}, "volumes": {}, "snapshots": {},
             "key_pairs": {}, "addresses": {}, "enis": {}, "placement_groups": {},
             "launch_templates": {}, "tags": {},
             "account": {"ebs_encryption_by_default": False, "ebs_default_kms_key_id": "alias/aws/ebs",
                         "allowed_images_enabled": False, "allowed_images_criteria": [],
                         "serial_console_enabled": True,
                         "default_credit_specification": {"t2": "standard", "t3": "unlimited", "t4g": "unlimited"},
                         "asg_default_instance_warmup": 0},
             "seeded_amis": False}
        store._vpc_model = m
    return m


def _vpc_default_sg(m: dict, vpc_id: str, fallback: str) -> str:
    """The VPC's `default` security group (created on first use, like AWS creates it with the VPC)."""
    sg = next((g["id"] for g in m["sgs"].values() if g.get("vpc_id") == vpc_id and g.get("is_default")), None)
    if sg or vpc_id not in m["vpcs"]:
        return sg or fallback
    sg_id = _rid("sg")
    m["sgs"][sg_id] = {"id": sg_id, "vpc_id": vpc_id, "name": "default", "description": "default VPC security group",
                       "is_default": True, "tags": {},
                       "ingress": [{"protocol": "-1", "from_port": None, "to_port": None, "cidrs": [], "sgs": [sg_id],
                                    "rule_id": _rid("sgr", 8), "description": ""}],
                       "egress": [{"protocol": "-1", "from_port": None, "to_port": None, "cidrs": ["0.0.0.0/0"], "sgs": [],
                                   "rule_id": _rid("sgr", 8), "description": ""}]}
    return sg_id


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
def _default_dhcp_options(m: dict) -> str:
    existing = next((d["id"] for d in m["dhcp_options"].values() if d.get("default")), None)
    if existing:
        return existing
    dopt_id = _rid("dopt")
    m["dhcp_options"][dopt_id] = {"id": dopt_id, "default": True, "tags": {},
                                  "options": {"domain-name": "ec2.internal", "domain-name-servers": "AmazonProvidedDNS"}}
    return dopt_id


def _create_default_nacl(m: dict, vpc_id: str) -> str:
    nacl_id = _rid("acl")
    m["nacls"][nacl_id] = {"id": nacl_id, "vpc_id": vpc_id, "default": True, "subnets": [], "tags": {},
                           "entries": [{"rule_number": 32767, "protocol": "-1", "allow": True, "egress": False, "cidr": "0.0.0.0/0", "from_port": None, "to_port": None},
                                       {"rule_number": 32767, "protocol": "-1", "allow": True, "egress": True, "cidr": "0.0.0.0/0", "from_port": None, "to_port": None}]}
    return nacl_id


def _create_vpc(store, params):
    cidr = str(params.get("CidrBlock", ""))
    try:
        ipaddress.ip_network(cidr, strict=False)
    except ValueError:
        raise VpcError("InvalidParameterValue", f"Invalid CIDR: {cidr}")
    m = _model(store)
    vpc_id = _rid("vpc")
    nacl_id = _create_default_nacl(m, vpc_id)
    m["vpcs"][vpc_id] = {"id": vpc_id, "cidr": cidr, "igw": None, "default_nacl": nacl_id,
                         "tenancy": str(params.get("InstanceTenancy") or "default"),
                         "dhcp_options_id": _default_dhcp_options(m), "enable_dns_hostnames": False,
                         "enable_dns_support": True, "tags": _parse_tag_specifications(params).get("vpc", {})}
    # default (main) route table with the implicit local route
    rt_id = _rid("rtb")
    m["route_tables"][rt_id] = {"id": rt_id, "vpc_id": vpc_id, "main": True,
                               "routes": [{"dest": cidr, "target": "local"}],
                               "subnets": [], "tags": {}}
    return _envelope("CreateVpc", f"<vpc><vpcId>{vpc_id}</vpcId><cidrBlock>{cidr}</cidrBlock>"
                                  f"<state>available</state><instanceTenancy>{_xml_escape(m['vpcs'][vpc_id]['tenancy'])}</instanceTenancy>"
                                  f"<dhcpOptionsId>{_xml_escape(m['vpcs'][vpc_id]['dhcp_options_id'])}</dhcpOptionsId>"
                                  f"<isDefault>false</isDefault></vpc>")


def _modify_vpc_attribute(store, params):
    m = _model(store)
    vpc_id = str(params.get("VpcId", ""))
    v = m["vpcs"].get(vpc_id)
    if v is None:
        raise VpcError("InvalidVpcID.NotFound", f"VPC {vpc_id} not found.")
    if "EnableDnsHostnames.Value" in params:
        v["enable_dns_hostnames"] = str(params["EnableDnsHostnames.Value"]).lower() == "true"
    if "EnableDnsSupport.Value" in params:
        v["enable_dns_support"] = str(params["EnableDnsSupport.Value"]).lower() == "true"
    return _envelope("ModifyVpcAttribute", "<return>true</return>")


def _describe_vpc_attribute(store, params):
    m = _model(store)
    vpc_id = str(params.get("VpcId", ""))
    v = m["vpcs"].get(vpc_id)
    if v is None:
        raise VpcError("InvalidVpcID.NotFound", f"VPC {vpc_id} not found.")
    attr = str(params.get("Attribute", ""))
    key = "enable_dns_hostnames" if attr == "enableDnsHostnames" else "enable_dns_support"
    tag = "enableDnsHostnames" if attr == "enableDnsHostnames" else "enableDnsSupport"
    return _envelope("DescribeVpcAttribute", f"<vpcId>{_xml_escape(vpc_id)}</vpcId>"
                                             f"<{tag}><value>{str(v.get(key, False)).lower()}</value></{tag}>")


def _delete_vpc(store, params):
    m = _model(store)
    vpc_id = str(params.get("VpcId", ""))
    if vpc_id not in m["vpcs"]:
        raise VpcError("InvalidVpcID.NotFound", f"VPC {vpc_id} not found.")
    if any(s["vpc_id"] == vpc_id for s in m["subnets"].values()):
        raise VpcError("DependencyViolation", f"The vpc '{vpc_id}' has dependencies and cannot be deleted.")
    if any(sg.get("vpc_id") == vpc_id and not sg.get("is_default") for sg in m["sgs"].values()):
        raise VpcError("DependencyViolation", f"The vpc '{vpc_id}' has dependencies and cannot be deleted.")
    if m["vpcs"][vpc_id].get("igw"):
        raise VpcError("DependencyViolation", f"The vpc '{vpc_id}' has dependencies and cannot be deleted.")
    for rt_id in [k for k, rt in m["route_tables"].items() if rt["vpc_id"] == vpc_id]:
        m["route_tables"].pop(rt_id)
    for nacl_id in [k for k, n in m["nacls"].items() if n["vpc_id"] == vpc_id]:
        m["nacls"].pop(nacl_id)
    for sg_id in [k for k, sg in m["sgs"].items() if sg.get("vpc_id") == vpc_id and sg.get("is_default")]:
        m["sgs"].pop(sg_id)
    m["vpcs"].pop(vpc_id)
    return _envelope("DeleteVpc", "<return>true</return>")


def _create_subnet(store, params):
    vpc_id = str(params.get("VpcId", ""))
    cidr = str(params.get("CidrBlock", ""))
    m = _model(store)
    if vpc_id not in m["vpcs"]:
        raise VpcError("InvalidVpcID.NotFound", f"VPC {vpc_id} not found.")
    subnet_id = _rid("subnet")
    main_rt = next((rt["id"] for rt in m["route_tables"].values()
                    if rt["vpc_id"] == vpc_id and rt.get("main")), None)
    az = str(params.get("AvailabilityZone") or _AZS[len(m["subnets"]) % len(_AZS)])
    m["subnets"][subnet_id] = {"id": subnet_id, "vpc_id": vpc_id, "cidr": cidr, "az": az,
                               "route_table": main_rt, "nacl": m["vpcs"][vpc_id].get("default_nacl"),
                               "map_public_ip": False, "tags": _parse_tag_specifications(params).get("subnet", {})}
    if main_rt:
        m["route_tables"][main_rt]["subnets"].append(subnet_id)
    nacl_id = m["subnets"][subnet_id]["nacl"]
    if nacl_id and nacl_id in m["nacls"]:
        m["nacls"][nacl_id]["subnets"].append(subnet_id)
    return _envelope("CreateSubnet", f"<subnet><subnetId>{subnet_id}</subnetId>"
                                     f"<vpcId>{vpc_id}</vpcId><cidrBlock>{cidr}</cidrBlock>"
                                     f"<availabilityZone>{_xml_escape(az)}</availabilityZone>"
                                     f"<state>available</state></subnet>")


def _delete_subnet(store, params):
    m = _model(store)
    subnet_id = str(params.get("SubnetId", ""))
    sn = m["subnets"].get(subnet_id)
    if sn is None:
        raise VpcError("InvalidSubnetID.NotFound", f"The subnet '{subnet_id}' does not exist.")
    if any(i.get("subnet_id") == subnet_id and i.get("state") != "terminated" for i in m["instances"].values()):
        raise VpcError("DependencyViolation", f"The subnet '{subnet_id}' has dependencies and cannot be deleted.")
    rt = m["route_tables"].get(sn.get("route_table"))
    if rt and subnet_id in rt["subnets"]:
        rt["subnets"].remove(subnet_id)
    nacl = m["nacls"].get(sn.get("nacl"))
    if nacl and subnet_id in nacl["subnets"]:
        nacl["subnets"].remove(subnet_id)
    for rid in [r["id"] for r in m["subnet_cidr_reservations"].values() if r["subnet_id"] == subnet_id]:
        m["subnet_cidr_reservations"].pop(rid)
    m["subnets"].pop(subnet_id)
    return _envelope("DeleteSubnet", "<return>true</return>")


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


def _igw_xml(igw: dict) -> str:
    att = (f"<item><vpcId>{_xml_escape(igw['vpc_id'])}</vpcId><state>available</state></item>"
           if igw.get("vpc_id") else "")
    return ("<item>"
            f"<internetGatewayId>{_xml_escape(igw['id'])}</internetGatewayId>"
            f"<attachmentSet>{att}</attachmentSet>{_tags_xml(igw.get('tags', {}))}"
            "</item>")


def _create_internet_gateway(store, params):
    igw_id = _rid("igw")
    m = _model(store)
    m["igws"][igw_id] = {"id": igw_id, "vpc_id": None, "tags": _parse_tag_specifications(params).get("internet-gateway", {})}
    return _envelope("CreateInternetGateway",
                     f"<internetGateway><internetGatewayId>{igw_id}</internetGatewayId><attachmentSet/>"
                     f"{_tags_xml(m['igws'][igw_id]['tags'])}</internetGateway>")


def _describe_internet_gateways(store, params):
    m = _model(store)
    ids = [v for k, v in params.items() if k.startswith("InternetGatewayId.")]
    rows = list(m["igws"].values())
    if ids:
        rows = [g for g in rows if g["id"] in ids]
    return _envelope("DescribeInternetGateways", f"<internetGatewaySet>{''.join(_igw_xml(g) for g in rows)}</internetGatewaySet>")


def _attach_internet_gateway(store, params):
    igw_id = str(params.get("InternetGatewayId", ""))
    vpc_id = str(params.get("VpcId", ""))
    m = _model(store)
    if igw_id not in m["igws"] or vpc_id not in m["vpcs"]:
        raise VpcError("InvalidParameterValue", "IGW or VPC not found.")
    if m["igws"][igw_id]["vpc_id"]:
        raise VpcError("Resource.AlreadyAssociated", f"resource {igw_id} is already attached to a VPC.")
    m["igws"][igw_id]["vpc_id"] = vpc_id
    m["vpcs"][vpc_id]["igw"] = igw_id
    return _envelope("AttachInternetGateway", "<return>true</return>")


def _detach_internet_gateway(store, params):
    igw_id = str(params.get("InternetGatewayId", ""))
    vpc_id = str(params.get("VpcId", ""))
    m = _model(store)
    igw = m["igws"].get(igw_id)
    if igw is None or igw.get("vpc_id") != vpc_id:
        raise VpcError("Gateway.NotAttached", f"resource {igw_id} is not attached to network {vpc_id}")
    igw["vpc_id"] = None
    m["vpcs"][vpc_id]["igw"] = None
    return _envelope("DetachInternetGateway", "<return>true</return>")


def _delete_internet_gateway(store, params):
    igw_id = str(params.get("InternetGatewayId", ""))
    m = _model(store)
    igw = m["igws"].get(igw_id)
    if igw is None:
        raise VpcError("InvalidInternetGatewayID.NotFound", f"The internetGateway ID '{igw_id}' does not exist.")
    if igw.get("vpc_id"):
        raise VpcError("DependencyViolation", f"The internetGateway '{igw_id}' has dependencies and cannot be deleted.")
    m["igws"].pop(igw_id)
    return _envelope("DeleteInternetGateway", "<return>true</return>")


# ── route tables ─────────────────────────────────────────────────────────
_ROUTE_TARGET_TAG = (("nat-", "natGatewayId"), ("pcx-", "vpcPeeringConnectionId"), ("eni-", "networkInterfaceId"),
                     ("i-", "instanceId"))


def _route_xml(r: dict) -> str:
    t = str(r.get("target", ""))
    tag = next((tg for pre, tg in _ROUTE_TARGET_TAG if t.startswith(pre)), "gatewayId")
    state = r.get("state", "active")
    origin = "CreateRouteTable" if t == "local" else "CreateRoute"
    return (f"<item><destinationCidrBlock>{_xml_escape(r['dest'])}</destinationCidrBlock>"
            f"<{tag}>{_xml_escape(t)}</{tag}><state>{state}</state><origin>{origin}</origin></item>")


def _rt_xml(rt: dict) -> str:
    routes = "".join(_route_xml(r) for r in rt["routes"])
    assocs = ""
    if rt.get("main"):
        assocs += (f"<item><routeTableAssociationId>rtbassoc-main-{_xml_escape(rt['vpc_id'])}</routeTableAssociationId>"
                   f"<routeTableId>{_xml_escape(rt['id'])}</routeTableId><main>true</main></item>")
    assocs += "".join(f"<item><routeTableAssociationId>rtbassoc-{_xml_escape(sid)}</routeTableAssociationId>"
                       f"<routeTableId>{_xml_escape(rt['id'])}</routeTableId><subnetId>{_xml_escape(sid)}</subnetId>"
                       f"<main>false</main></item>" for sid in rt["subnets"])
    return ("<item>"
            f"<routeTableId>{_xml_escape(rt['id'])}</routeTableId><vpcId>{_xml_escape(rt['vpc_id'])}</vpcId>"
            f"<routeSet>{routes}</routeSet><associationSet>{assocs}</associationSet>"
            f"{_tags_xml(rt.get('tags', {}))}"
            "</item>")


def _create_route_table(store, params):
    vpc_id = str(params.get("VpcId", ""))
    m = _model(store)
    if vpc_id not in m["vpcs"]:
        raise VpcError("InvalidVpcID.NotFound", f"VPC {vpc_id} not found.")
    rt_id = _rid("rtb")
    m["route_tables"][rt_id] = {"id": rt_id, "vpc_id": vpc_id, "main": False,
                               "routes": [{"dest": m["vpcs"][vpc_id]["cidr"], "target": "local"}], "subnets": [],
                               "tags": _parse_tag_specifications(params).get("route-table", {})}
    return _envelope("CreateRouteTable", f"<routeTable>{_rt_xml(m['route_tables'][rt_id])[len('<item>'):-len('</item>')]}</routeTable>")


def _describe_route_tables(store, params):
    m = _model(store)
    ids = [v for k, v in params.items() if k.startswith("RouteTableId.")]
    rows = list(m["route_tables"].values())
    if ids:
        rows = [rt for rt in rows if rt["id"] in ids]
    return _envelope("DescribeRouteTables", f"<routeTableSet>{''.join(_rt_xml(rt) for rt in rows)}</routeTableSet>")


def _delete_route_table(store, params):
    rt_id = str(params.get("RouteTableId", ""))
    m = _model(store)
    rt = m["route_tables"].get(rt_id)
    if rt is None:
        raise VpcError("InvalidRouteTableID.NotFound", f"The routeTable ID '{rt_id}' does not exist.")
    if rt.get("main"):
        raise VpcError("DependencyViolation", "The main route table cannot be deleted.")
    if rt["subnets"]:
        raise VpcError("DependencyViolation", f"The routeTable '{rt_id}' has dependencies and cannot be deleted.")
    m["route_tables"].pop(rt_id)
    return _envelope("DeleteRouteTable", "<return>true</return>")


def _create_route(store, params):
    rt_id = str(params.get("RouteTableId", ""))
    m = _model(store)
    rt = m["route_tables"].get(rt_id)
    if not rt:
        raise VpcError("InvalidRouteTableID.NotFound", f"Route table {rt_id} not found.")
    dest = str(params.get("DestinationCidrBlock", ""))
    try:
        ipaddress.ip_network(dest, strict=False)
    except ValueError:
        raise VpcError("InvalidParameterValue", f"Value ({dest}) for parameter destinationCidrBlock is invalid.")
    target = str(params.get("GatewayId") or params.get("NatGatewayId") or params.get("VpcPeeringConnectionId")
                 or params.get("NetworkInterfaceId") or params.get("InstanceId") or "")
    if not target:
        raise VpcError("MissingParameter", "The request must contain exactly one of gatewayId, natGatewayId, "
                                           "networkInterfaceId, vpcPeeringConnectionId or instanceId")
    if target.startswith("i-"):
        _find_instance(m, target)
    elif target.startswith("eni-") and target not in m["enis"]:
        raise VpcError("InvalidNetworkInterfaceID.NotFound", f"The networkInterface ID '{target}' does not exist")
    if any(r["dest"] == dest for r in rt["routes"]):
        raise VpcError("RouteAlreadyExists", f"The route identified by {dest} already exists.")
    rt["routes"].append({"dest": dest, "target": target})
    return _envelope("CreateRoute", "<return>true</return>")


def _delete_route(store, params):
    rt_id = str(params.get("RouteTableId", ""))
    dest = str(params.get("DestinationCidrBlock", ""))
    m = _model(store)
    rt = m["route_tables"].get(rt_id)
    if not rt:
        raise VpcError("InvalidRouteTableID.NotFound", f"Route table {rt_id} not found.")
    rt["routes"] = [r for r in rt["routes"] if r["dest"] != dest]
    return _envelope("DeleteRoute", "<return>true</return>")


def _reassign_subnet_route_table(m: dict, subnet_id: str, new_rt_id: str) -> None:
    sn = m["subnets"][subnet_id]
    old_rt = m["route_tables"].get(sn.get("route_table"))
    if old_rt and subnet_id in old_rt["subnets"]:
        old_rt["subnets"].remove(subnet_id)
    sn["route_table"] = new_rt_id
    m["route_tables"][new_rt_id]["subnets"].append(subnet_id)


def _associate_route_table(store, params):
    m = _model(store)
    rt_id = str(params.get("RouteTableId", ""))
    subnet_id = str(params.get("SubnetId", ""))
    if rt_id not in m["route_tables"] or subnet_id not in m["subnets"]:
        raise VpcError("InvalidParameterValue", "Route table or subnet not found.")
    _reassign_subnet_route_table(m, subnet_id, rt_id)
    return _envelope("AssociateRouteTable", f"<associationId>rtbassoc-{_xml_escape(subnet_id)}</associationId>"
                                            f"<associationState><state>associated</state></associationState>")


def _disassociate_route_table(store, params):
    m = _model(store)
    assoc_id = str(params.get("AssociationId", ""))
    if assoc_id.startswith("rtbassoc-main-"):
        raise VpcError("InvalidParameterValue", "The main route table association cannot be disassociated.")
    subnet_id = assoc_id[len("rtbassoc-"):]
    sn = m["subnets"].get(subnet_id)
    if sn is None:
        raise VpcError("InvalidAssociationID.NotFound", f"The association ID '{assoc_id}' does not exist.")
    main_rt = next((rt["id"] for rt in m["route_tables"].values() if rt["vpc_id"] == sn["vpc_id"] and rt.get("main")), None)
    if main_rt:
        _reassign_subnet_route_table(m, subnet_id, main_rt)
    return _envelope("DisassociateRouteTable", "<return>true</return>")


def _replace_route_table_association(store, params):
    m = _model(store)
    assoc_id = str(params.get("AssociationId", ""))
    rt_id = str(params.get("RouteTableId", ""))
    if rt_id not in m["route_tables"]:
        raise VpcError("InvalidRouteTableID.NotFound", f"Route table {rt_id} not found.")
    if assoc_id.startswith("rtbassoc-main-"):
        vpc_id = assoc_id[len("rtbassoc-main-"):]
        old_main = next((rt for rt in m["route_tables"].values() if rt["vpc_id"] == vpc_id and rt.get("main")), None)
        if old_main:
            old_main["main"] = False
        m["route_tables"][rt_id]["main"] = True
        new_assoc = f"rtbassoc-main-{vpc_id}"
    else:
        subnet_id = assoc_id[len("rtbassoc-"):]
        if subnet_id not in m["subnets"]:
            raise VpcError("InvalidAssociationID.NotFound", f"The association ID '{assoc_id}' does not exist.")
        _reassign_subnet_route_table(m, subnet_id, rt_id)
        new_assoc = f"rtbassoc-{subnet_id}"
    return _envelope("ReplaceRouteTableAssociation", f"<newAssociationId>{_xml_escape(new_assoc)}</newAssociationId>")


# ── network ACLs ────────────────────────────────────────────────────────
def _nacl_xml(nacl: dict) -> str:
    entries = "".join(
        f"<item><ruleNumber>{e['rule_number']}</ruleNumber><protocol>{_xml_escape(e['protocol'])}</protocol>"
        f"<ruleAction>{'allow' if e['allow'] else 'deny'}</ruleAction><egress>{str(e['egress']).lower()}</egress>"
        f"<cidrBlock>{_xml_escape(e['cidr'])}</cidrBlock>"
        + (f"<portRange><from>{e['from_port']}</from><to>{e['to_port']}</to></portRange>" if e.get("from_port") is not None else "")
        + "</item>" for e in nacl["entries"])
    assocs = "".join(f"<item><networkAclAssociationId>aclassoc-{_xml_escape(sid)}</networkAclAssociationId>"
                      f"<networkAclId>{_xml_escape(nacl['id'])}</networkAclId><subnetId>{_xml_escape(sid)}</subnetId></item>"
                      for sid in nacl["subnets"])
    return ("<item>"
            f"<networkAclId>{_xml_escape(nacl['id'])}</networkAclId><vpcId>{_xml_escape(nacl['vpc_id'])}</vpcId>"
            f"<default>{str(nacl.get('default', False)).lower()}</default>"
            f"<entrySet>{entries}</entrySet><associationSet>{assocs}</associationSet>"
            f"{_tags_xml(nacl.get('tags', {}))}"
            "</item>")


def _create_network_acl(store, params):
    vpc_id = str(params.get("VpcId", ""))
    m = _model(store)
    if vpc_id not in m["vpcs"]:
        raise VpcError("InvalidVpcID.NotFound", f"VPC {vpc_id} not found.")
    nacl_id = _rid("acl")
    m["nacls"][nacl_id] = {"id": nacl_id, "vpc_id": vpc_id, "entries": [], "subnets": [], "default": False,
                          "tags": _parse_tag_specifications(params).get("network-acl", {})}
    return _envelope("CreateNetworkAcl",
                     f"<networkAcl>{_nacl_xml(m['nacls'][nacl_id])[len('<item>'):-len('</item>')]}</networkAcl>")


def _describe_network_acls(store, params):
    m = _model(store)
    ids = [v for k, v in params.items() if k.startswith("NetworkAclId.")]
    rows = list(m["nacls"].values())
    if ids:
        rows = [n for n in rows if n["id"] in ids]
    return _envelope("DescribeNetworkAcls", f"<networkAclSet>{''.join(_nacl_xml(n) for n in rows)}</networkAclSet>")


def _delete_network_acl(store, params):
    nacl_id = str(params.get("NetworkAclId", ""))
    m = _model(store)
    nacl = m["nacls"].get(nacl_id)
    if nacl is None:
        raise VpcError("InvalidNetworkAclID.NotFound", f"The networkAcl ID '{nacl_id}' does not exist.")
    if nacl.get("default"):
        raise VpcError("InvalidParameterValue", "The default network ACL cannot be deleted.")
    if nacl["subnets"]:
        raise VpcError("DependencyViolation", f"The networkAcl '{nacl_id}' has dependencies and cannot be deleted.")
    m["nacls"].pop(nacl_id)
    return _envelope("DeleteNetworkAcl", "<return>true</return>")


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


def _delete_network_acl_entry(store, params):
    m = _model(store)
    nacl = m["nacls"].get(str(params.get("NetworkAclId", "")))
    if not nacl:
        raise VpcError("InvalidNetworkAclID.NotFound", "Network ACL not found.")
    rule_number = int(params.get("RuleNumber", -1))
    egress = str(params.get("Egress", "false")).lower() == "true"
    nacl["entries"] = [e for e in nacl["entries"] if not (e["rule_number"] == rule_number and e["egress"] == egress)]
    return _envelope("DeleteNetworkAclEntry", "<return>true</return>")


def _associate_network_acl(store, params):
    """Attach a NACL to a subnet (simulator convenience; real EC2 uses
    ReplaceNetworkAclAssociation with an association id)."""
    m = _model(store)
    nacl_id = str(params.get("NetworkAclId", ""))
    subnet_id = str(params.get("SubnetId", ""))
    if nacl_id not in m["nacls"] or subnet_id not in m["subnets"]:
        raise VpcError("InvalidParameterValue", "NACL or subnet not found.")
    old_nacl = m["nacls"].get(m["subnets"][subnet_id]["nacl"])
    if old_nacl and subnet_id in old_nacl["subnets"]:
        old_nacl["subnets"].remove(subnet_id)
    m["subnets"][subnet_id]["nacl"] = nacl_id
    m["nacls"][nacl_id]["subnets"].append(subnet_id)
    return _envelope("AssociateNetworkAcl", "<return>true</return>")


def _replace_network_acl_association(store, params):
    m = _model(store)
    assoc_id = str(params.get("AssociationId", ""))
    nacl_id = str(params.get("NetworkAclId", ""))
    subnet_id = assoc_id[len("aclassoc-"):]
    if nacl_id not in m["nacls"] or subnet_id not in m["subnets"]:
        raise VpcError("InvalidParameterValue", "NACL or association not found.")
    old_nacl = m["nacls"].get(m["subnets"][subnet_id]["nacl"])
    if old_nacl and subnet_id in old_nacl["subnets"]:
        old_nacl["subnets"].remove(subnet_id)
    m["subnets"][subnet_id]["nacl"] = nacl_id
    m["nacls"][nacl_id]["subnets"].append(subnet_id)
    return _envelope("ReplaceNetworkAclAssociation", f"<newAssociationId>aclassoc-{_xml_escape(subnet_id)}</newAssociationId>")


# ── NAT gateways ────────────────────────────────────────────────────────
def _natgw_xml(gw: dict) -> str:
    addr = (f"<item><allocationId>{_xml_escape(gw['allocation_id'])}</allocationId>"
            f"<publicIp>{_xml_escape(gw.get('public_ip', ''))}</publicIp>"
            f"<privateIp>{_xml_escape(gw.get('private_ip', ''))}</privateIp>"
            f"<networkInterfaceId>{_xml_escape(gw.get('eni_id', ''))}</networkInterfaceId></item>"
            if gw.get("allocation_id") else "")
    return ("<item>"
            f"<natGatewayId>{_xml_escape(gw['id'])}</natGatewayId><vpcId>{_xml_escape(gw['vpc_id'])}</vpcId>"
            f"<subnetId>{_xml_escape(gw['subnet_id'])}</subnetId><state>{_xml_escape(gw['state'])}</state>"
            f"<connectivityType>{_xml_escape(gw['connectivity_type'])}</connectivityType>"
            f"<createTime>{_xml_escape(gw['create_time'])}</createTime>"
            f"<natGatewayAddressSet>{addr}</natGatewayAddressSet>"
            f"{_tags_xml(gw.get('tags', {}))}"
            "</item>")


def _create_nat_gateway(store, params):
    m = _model(store)
    subnet_id = str(params.get("SubnetId", ""))
    subnet = m["subnets"].get(subnet_id)
    if subnet is None:
        raise VpcError("InvalidSubnetID.NotFound", f"The subnet ID '{subnet_id}' does not exist.")
    connectivity = str(params.get("ConnectivityType") or "public")
    natgw_id = _rid("nat")
    gw = {"id": natgw_id, "vpc_id": subnet["vpc_id"], "subnet_id": subnet_id, "state": "available",
          "connectivity_type": connectivity, "create_time": _now(), "allocation_id": "",
          "tags": _parse_tag_specifications(params).get("natgateway", {})}
    if connectivity == "public":
        alloc_id = str(params.get("AllocationId") or "")
        if alloc_id and alloc_id in m["addresses"]:
            addr = m["addresses"][alloc_id]
        else:
            n = len(m["addresses"])
            alloc_id = _rid("eipalloc")
            addr = {"allocation_id": alloc_id, "public_ip": _pseudo_public_ip(n + 2000), "domain": "vpc",
                    "instance_id": "", "association_id": "", "network_interface_id": "", "private_ip": "", "tags": {}}
            m["addresses"][alloc_id] = addr
        gw["allocation_id"] = alloc_id
        gw["public_ip"] = addr["public_ip"]
    gw["private_ip"] = _allocate_private_ip(m, subnet_id, str(params.get("PrivateIpAddress") or ""))
    gw["eni_id"] = _rid("eni")
    m["nat_gateways"][natgw_id] = gw
    return _envelope("CreateNatGateway", f"<natGateway>{_natgw_xml(gw)[len('<item>'):-len('</item>')]}</natGateway>")


def _describe_nat_gateways(store, params):
    m = _model(store)
    ids = [v for k, v in params.items() if k.startswith("NatGatewayId.")]
    rows = list(m["nat_gateways"].values())
    if ids:
        rows = [g for g in rows if g["id"] in ids]
    return _envelope("DescribeNatGateways", f"<natGatewaySet>{''.join(_natgw_xml(g) for g in rows)}</natGatewaySet>")


def _delete_nat_gateway(store, params):
    natgw_id = str(params.get("NatGatewayId", ""))
    m = _model(store)
    if natgw_id not in m["nat_gateways"]:
        raise VpcError("NatGatewayNotFound", f"The Nat Gateway ID '{natgw_id}' does not exist.")
    m["nat_gateways"][natgw_id]["state"] = "deleted"
    m["nat_gateways"].pop(natgw_id)
    return _envelope("DeleteNatGateway", "<return>true</return>")


# ── egress-only internet gateways ───────────────────────────────────────
def _eigw_xml(g: dict) -> str:
    att = f"<item><vpcId>{_xml_escape(g['vpc_id'])}</vpcId><state>attached</state></item>" if g.get("vpc_id") else ""
    return ("<item>"
            f"<egressOnlyInternetGatewayId>{_xml_escape(g['id'])}</egressOnlyInternetGatewayId>"
            f"<attachmentSet>{att}</attachmentSet>{_tags_xml(g.get('tags', {}))}"
            "</item>")


def _create_egress_only_internet_gateway(store, params):
    m = _model(store)
    vpc_id = str(params.get("VpcId", ""))
    if vpc_id not in m["vpcs"]:
        raise VpcError("InvalidVpcID.NotFound", f"VPC {vpc_id} not found.")
    eigw_id = _rid("eigw")
    m["eigws"][eigw_id] = {"id": eigw_id, "vpc_id": vpc_id, "tags": _parse_tag_specifications(params).get("egress-only-internet-gateway", {})}
    return _envelope("CreateEgressOnlyInternetGateway", f"<egressOnlyInternetGateway>{_eigw_xml(m['eigws'][eigw_id])[len('<item>'):-len('</item>')]}</egressOnlyInternetGateway>")


def _describe_egress_only_internet_gateways(store, params):
    m = _model(store)
    return _envelope("DescribeEgressOnlyInternetGateways", f"<egressOnlyInternetGatewaySet>{''.join(_eigw_xml(g) for g in m['eigws'].values())}</egressOnlyInternetGatewaySet>")


def _delete_egress_only_internet_gateway(store, params):
    eigw_id = str(params.get("EgressOnlyInternetGatewayId", ""))
    m = _model(store)
    if eigw_id not in m["eigws"]:
        raise VpcError("InvalidGatewayID.NotFound", f"The gateway ID '{eigw_id}' does not exist.")
    m["eigws"].pop(eigw_id)
    return _envelope("DeleteEgressOnlyInternetGateway", "<return>true</return>")


# ── DHCP option sets ─────────────────────────────────────────────────────
def _parse_dhcp_configurations(params: dict) -> dict:
    opts: dict = {}
    idxs = sorted({k.split(".")[1] for k in params if k.startswith("DhcpConfiguration.") and len(k.split(".")) >= 3}, key=int)
    for i in idxs:
        key = params.get(f"DhcpConfiguration.{i}.Key")
        if not key:
            continue
        vals = [v for k, v in params.items() if k.startswith(f"DhcpConfiguration.{i}.Value.")]
        opts[str(key)] = ", ".join(str(v) for v in vals) if vals else ""
    return opts


def _dopt_xml(d: dict) -> str:
    cfgs = "".join(f"<item><key>{_xml_escape(k)}</key><valueSet><item><value>{_xml_escape(v)}</value></item></valueSet></item>"
                    for k, v in d.get("options", {}).items())
    return ("<item>"
            f"<dhcpOptionsId>{_xml_escape(d['id'])}</dhcpOptionsId><dhcpConfigurationSet>{cfgs}</dhcpConfigurationSet>"
            f"{_tags_xml(d.get('tags', {}))}"
            "</item>")


def _create_dhcp_options(store, params):
    m = _model(store)
    dopt_id = _rid("dopt")
    m["dhcp_options"][dopt_id] = {"id": dopt_id, "default": False, "options": _parse_dhcp_configurations(params),
                                  "tags": _parse_tag_specifications(params).get("dhcp-options", {})}
    return _envelope("CreateDhcpOptions", f"<dhcpOptions>{_dopt_xml(m['dhcp_options'][dopt_id])[len('<item>'):-len('</item>')]}</dhcpOptions>")


def _describe_dhcp_options(store, params):
    m = _model(store)
    return _envelope("DescribeDhcpOptions", f"<dhcpOptionsSet>{''.join(_dopt_xml(d) for d in m['dhcp_options'].values())}</dhcpOptionsSet>")


def _delete_dhcp_options(store, params):
    dopt_id = str(params.get("DhcpOptionsId", ""))
    m = _model(store)
    if dopt_id not in m["dhcp_options"]:
        raise VpcError("InvalidDhcpOptionsID.NotFound", f"The dhcpOptions ID '{dopt_id}' does not exist.")
    if m["dhcp_options"][dopt_id].get("default"):
        raise VpcError("InvalidParameterValue", "The default DHCP options set cannot be deleted.")
    m["dhcp_options"].pop(dopt_id)
    return _envelope("DeleteDhcpOptions", "<return>true</return>")


def _associate_dhcp_options(store, params):
    m = _model(store)
    vpc_id = str(params.get("VpcId", ""))
    dopt_id = str(params.get("DhcpOptionsId", ""))
    if vpc_id not in m["vpcs"]:
        raise VpcError("InvalidVpcID.NotFound", f"VPC {vpc_id} not found.")
    if dopt_id != "default" and dopt_id not in m["dhcp_options"]:
        raise VpcError("InvalidDhcpOptionsID.NotFound", f"The dhcpOptions ID '{dopt_id}' does not exist.")
    m["vpcs"][vpc_id]["dhcp_options_id"] = dopt_id if dopt_id != "default" else _default_dhcp_options(m)
    return _envelope("AssociateDhcpOptions", "<return>true</return>")


# ── managed prefix lists ─────────────────────────────────────────────────
def _parse_prefix_entries(params: dict) -> list:
    entries = []
    idxs = sorted({k.split(".")[1] for k in params if k.startswith("Entry.") and len(k.split(".")) >= 3}, key=int)
    for i in idxs:
        cidr = params.get(f"Entry.{i}.Cidr")
        if cidr:
            entries.append({"cidr": str(cidr), "description": str(params.get(f"Entry.{i}.Description", ""))})
    return entries


def _pl_xml(pl: dict) -> str:
    return ("<item>"
            f"<prefixListId>{_xml_escape(pl['id'])}</prefixListId><prefixListName>{_xml_escape(pl['name'])}</prefixListName>"
            f"<addressFamily>{_xml_escape(pl['address_family'])}</addressFamily><maxEntries>{pl['max_entries']}</maxEntries>"
            f"<state>{_xml_escape(pl['state'])}</state><ownerId>{OWNER_ID}</ownerId><version>{pl['version']}</version>"
            f"{_tags_xml(pl.get('tags', {}))}"
            "</item>")


def _create_managed_prefix_list(store, params):
    m = _model(store)
    name = str(params.get("PrefixListName", ""))
    pl_id = _rid("pl")
    pl = {"id": pl_id, "name": name, "max_entries": int(params.get("MaxEntries", 10) or 10),
          "address_family": str(params.get("AddressFamily") or "IPv4"), "state": "create-complete", "version": 1,
          "entries": _parse_prefix_entries(params), "tags": _parse_tag_specifications(params).get("prefix-list", {})}
    m["prefix_lists"][pl_id] = pl
    return _envelope("CreateManagedPrefixList", f"<prefixList>{_pl_xml(pl)[len('<item>'):-len('</item>')]}</prefixList>")


def _describe_managed_prefix_lists(store, params):
    m = _model(store)
    return _envelope("DescribeManagedPrefixLists", f"<prefixListSet>{''.join(_pl_xml(pl) for pl in m['prefix_lists'].values())}</prefixListSet>")


def _delete_managed_prefix_list(store, params):
    pl_id = str(params.get("PrefixListId", ""))
    m = _model(store)
    pl = m["prefix_lists"].get(pl_id)
    if pl is None:
        raise VpcError("InvalidPrefixListID.NotFound", f"The prefix list ID '{pl_id}' does not exist.")
    pl["state"] = "delete-complete"
    m["prefix_lists"].pop(pl_id)
    return _envelope("DeleteManagedPrefixList", f"<prefixList>{_pl_xml(pl)[len('<item>'):-len('</item>')]}</prefixList>")


# ── VPC peering connections ──────────────────────────────────────────────
def _pcx_xml(pcx: dict) -> str:
    return ("<item>"
            f"<vpcPeeringConnectionId>{_xml_escape(pcx['id'])}</vpcPeeringConnectionId>"
            f"<requesterVpcInfo><vpcId>{_xml_escape(pcx['requester_vpc_id'])}</vpcId><ownerId>{OWNER_ID}</ownerId></requesterVpcInfo>"
            f"<accepterVpcInfo><vpcId>{_xml_escape(pcx['accepter_vpc_id'])}</vpcId><ownerId>{OWNER_ID}</ownerId></accepterVpcInfo>"
            f"<status><code>{_xml_escape(pcx['status'])}</code></status>"
            f"{_tags_xml(pcx.get('tags', {}))}"
            "</item>")


def _create_vpc_peering_connection(store, params):
    m = _model(store)
    vpc_id = str(params.get("VpcId", ""))
    peer_vpc_id = str(params.get("PeerVpcId", ""))
    if vpc_id not in m["vpcs"] or peer_vpc_id not in m["vpcs"]:
        raise VpcError("InvalidVpcID.NotFound", "VPC or peer VPC not found.")
    pcx_id = _rid("pcx")
    m["peering_connections"][pcx_id] = {"id": pcx_id, "requester_vpc_id": vpc_id, "accepter_vpc_id": peer_vpc_id,
                                        "status": "pending-acceptance", "tags": _parse_tag_specifications(params).get("vpc-peering-connection", {})}
    return _envelope("CreateVpcPeeringConnection", f"<vpcPeeringConnection>{_pcx_xml(m['peering_connections'][pcx_id])[len('<item>'):-len('</item>')]}</vpcPeeringConnection>")


def _describe_vpc_peering_connections(store, params):
    m = _model(store)
    return _envelope("DescribeVpcPeeringConnections", f"<vpcPeeringConnectionSet>{''.join(_pcx_xml(p) for p in m['peering_connections'].values())}</vpcPeeringConnectionSet>")


def _accept_vpc_peering_connection(store, params):
    m = _model(store)
    pcx_id = str(params.get("VpcPeeringConnectionId", ""))
    pcx = m["peering_connections"].get(pcx_id)
    if pcx is None:
        raise VpcError("InvalidVpcPeeringConnectionID.NotFound", f"The VPC peering connection '{pcx_id}' does not exist.")
    pcx["status"] = "active"
    return _envelope("AcceptVpcPeeringConnection", f"<vpcPeeringConnection>{_pcx_xml(pcx)[len('<item>'):-len('</item>')]}</vpcPeeringConnection>")


def _delete_vpc_peering_connection(store, params):
    pcx_id = str(params.get("VpcPeeringConnectionId", ""))
    m = _model(store)
    if pcx_id not in m["peering_connections"]:
        raise VpcError("InvalidVpcPeeringConnectionID.NotFound", f"The VPC peering connection '{pcx_id}' does not exist.")
    m["peering_connections"][pcx_id]["status"] = "deleted"
    m["peering_connections"].pop(pcx_id)
    return _envelope("DeleteVpcPeeringConnection", "<return>true</return>")


# ── VPC route servers ────────────────────────────────────────────────────
def _rs_xml(rs: dict) -> str:
    return ("<item>"
            f"<routeServerId>{_xml_escape(rs['id'])}</routeServerId><amazonSideAsn>{rs['asn']}</amazonSideAsn>"
            f"<state>{_xml_escape(rs['state'])}</state>"
            f"{_tags_xml(rs.get('tags', {}))}"
            "</item>")


def _create_route_server(store, params):
    m = _model(store)
    rs_id = _rid("rs")
    rs = {"id": rs_id, "asn": int(params.get("AmazonSideAsn", 64512) or 64512), "state": "available",
          "tags": _parse_tag_specifications(params).get("route-server", {})}
    m["route_servers"][rs_id] = rs
    return _envelope("CreateRouteServer", f"<routeServer>{_rs_xml(rs)[len('<item>'):-len('</item>')]}</routeServer>")


def _describe_route_servers(store, params):
    m = _model(store)
    return _envelope("DescribeRouteServers", f"<routeServerSet>{''.join(_rs_xml(rs) for rs in m['route_servers'].values())}</routeServerSet>")


def _delete_route_server(store, params):
    rs_id = str(params.get("RouteServerId", ""))
    m = _model(store)
    if rs_id not in m["route_servers"]:
        raise VpcError("InvalidRouteServerID.NotFound", f"The route server ID '{rs_id}' does not exist.")
    m["route_servers"].pop(rs_id)
    return _envelope("DeleteRouteServer", "<return>true</return>")


def _vpc_xml(v: dict, m: dict) -> str:
    main_rt = next((rt["id"] for rt in m["route_tables"].values() if rt["vpc_id"] == v["id"] and rt.get("main")), "")
    return ("<item>"
            f"<vpcId>{_xml_escape(v['id'])}</vpcId><cidrBlock>{_xml_escape(v['cidr'])}</cidrBlock>"
            f"<state>available</state><instanceTenancy>{_xml_escape(v.get('tenancy', 'default'))}</instanceTenancy>"
            f"<dhcpOptionsId>{_xml_escape(v.get('dhcp_options_id', ''))}</dhcpOptionsId>"
            f"<isDefault>{str(bool(v.get('default'))).lower()}</isDefault>"
            f"<mainRouteTableId>{_xml_escape(main_rt)}</mainRouteTableId>"
            f"<mainNetworkAclId>{_xml_escape(v.get('default_nacl', ''))}</mainNetworkAclId>"
            f"<ownerId>{OWNER_ID}</ownerId>{_tags_xml(v.get('tags', {}))}"
            "</item>")


def _describe_vpcs(store, params):
    m = _model(store)
    _ensure_default_network(m)
    ids = [v for k, v in params.items() if k.startswith("VpcId.")]
    rows = list(m["vpcs"].values())
    if ids:
        rows = [v for v in rows if v["id"] in ids]
    items = "".join(_vpc_xml(v, m) for v in rows)
    return _envelope("DescribeVpcs", f"<vpcSet>{items}</vpcSet>")


def _subnet_xml(s: dict) -> str:
    return ("<item>"
            f"<subnetId>{_xml_escape(s['id'])}</subnetId><vpcId>{_xml_escape(s['vpc_id'])}</vpcId>"
            f"<cidrBlock>{_xml_escape(s['cidr'])}</cidrBlock><availabilityZone>{_xml_escape(s.get('az', ''))}</availabilityZone>"
            f"<state>available</state><defaultForAz>{str(bool(s.get('default'))).lower()}</defaultForAz>"
            f"<mapPublicIpOnLaunch>{str(bool(s.get('map_public_ip'))).lower()}</mapPublicIpOnLaunch>"
            f"<availableIpAddressCount>{max(0, _subnet_capacity(s['cidr']) - 5)}</availableIpAddressCount>"
            f"<routeTableId>{_xml_escape(s.get('route_table') or '')}</routeTableId>"
            f"<networkAclId>{_xml_escape(s.get('nacl') or '')}</networkAclId>"
            f"<ownerId>{OWNER_ID}</ownerId>{_tags_xml(s.get('tags', {}))}"
            "</item>")


def _subnet_capacity(cidr: str) -> int:
    try:
        return ipaddress.ip_network(cidr, strict=False).num_addresses
    except ValueError:
        return 0


def _describe_subnets(store, params):
    m = _model(store)
    _ensure_default_network(m)
    ids = [v for k, v in params.items() if k.startswith("SubnetId.")]
    rows = list(m["subnets"].values())
    if ids:
        rows = [s for s in rows if s["id"] in ids]
    items = "".join(_subnet_xml(s) for s in rows)
    return _envelope("DescribeSubnets", f"<subnetSet>{items}</subnetSet>")


# ── subnet CIDR reservations ────────────────────────────────────────────────
# AWS carves out a piece of a subnet's CIDR (e.g. for an on-prem range mapped into the
# subnet) so EC2 never auto-assigns an address from it; _allocate_private_ip enforces that.
def _scr_xml(r: dict) -> str:
    return ("<item>"
            f"<subnetCidrReservationId>{_xml_escape(r['id'])}</subnetCidrReservationId>"
            f"<subnetId>{_xml_escape(r['subnet_id'])}</subnetId><cidr>{_xml_escape(r['cidr'])}</cidr>"
            f"<reservationType>{_xml_escape(r['reservation_type'])}</reservationType>"
            f"<ownerId>{OWNER_ID}</ownerId><description>{_xml_escape(r.get('description', ''))}</description>"
            "</item>")


def _create_subnet_cidr_reservation(store, params):
    m = _model(store)
    subnet_id = str(params.get("SubnetId", ""))
    sn = m["subnets"].get(subnet_id)
    if sn is None:
        raise VpcError("InvalidSubnetID.NotFound", f"The subnet '{subnet_id}' does not exist.")
    cidr = str(params.get("Cidr", ""))
    subnet_net = ipaddress.ip_network(sn["cidr"], strict=False)
    try:
        res_net = ipaddress.ip_network(cidr, strict=False)
    except ValueError:
        raise VpcError("InvalidParameterValue", f"Invalid CIDR: {cidr}")
    if not (res_net.network_address >= subnet_net.network_address and res_net.broadcast_address <= subnet_net.broadcast_address):
        raise VpcError("InvalidParameterValue", f"CIDR {cidr} is not within the subnet's CIDR block {sn['cidr']}")
    used = _used_ips(m, subnet_id)
    if any(ipaddress.ip_address(ip) in res_net for ip in used if ip):
        raise VpcError("InvalidParameterValue", f"CIDR {cidr} overlaps an address already in use in subnet {subnet_id}")
    for other in m["subnet_cidr_reservations"].values():
        if other["subnet_id"] == subnet_id and res_net.overlaps(ipaddress.ip_network(other["cidr"], strict=False)):
            raise VpcError("InvalidParameterValue", f"CIDR {cidr} overlaps an existing reservation ({other['cidr']})")
    r_id = _rid("scr")
    reservation_type = str(params.get("ReservationType") or "explicit")
    r = {"id": r_id, "subnet_id": subnet_id, "cidr": cidr, "reservation_type": reservation_type,
         "description": str(params.get("Description", ""))}
    m["subnet_cidr_reservations"][r_id] = r
    return _envelope("CreateSubnetCidrReservation", f"<subnetCidrReservation>{_scr_xml(r)[len('<item>'):-len('</item>')]}</subnetCidrReservation>")


def _get_subnet_cidr_reservations(store, params):
    m = _model(store)
    subnet_id = str(params.get("SubnetId", ""))
    rows = [r for r in m["subnet_cidr_reservations"].values() if r["subnet_id"] == subnet_id]
    items = "".join(_scr_xml(r) for r in rows)
    return _envelope("GetSubnetCidrReservations", f"<subnetIpv4CidrReservationSet>{items}</subnetIpv4CidrReservationSet><subnetIpv6CidrReservationSet></subnetIpv6CidrReservationSet>")


def _delete_subnet_cidr_reservation(store, params):
    m = _model(store)
    r_id = str(params.get("SubnetCidrReservationId", ""))
    r = m["subnet_cidr_reservations"].get(r_id)
    if r is None:
        raise VpcError("InvalidParameterValue", f"The subnet CIDR reservation '{r_id}' does not exist.")
    m["subnet_cidr_reservations"].pop(r_id)
    return _envelope("DeleteSubnetCidrReservation", f"<deletedSubnetCidrReservation>{_scr_xml(r)[len('<item>'):-len('</item>')]}</deletedSubnetCidrReservation>")


# ── data plane: reachability analyzer ──────────────────────────────────────
# ── reachability: ONE evaluator (core/netsim) for the analyzer verb, Reachability Analyzer
#    (Network Insights paths/analyses) and the offline packet enforcer ─────────────────────
def _netsim():
    try:
        from core.netsim import evaluate as ev, from_aws as fa, model as nm
    except ImportError:                                  # pragma: no cover - flat layout
        from netsim import evaluate as ev, from_aws as fa, model as nm   # type: ignore
    return ev, fa, nm


def _find_subnet_for_ip(m, ip):
    for sn in m["subnets"].values():
        try:
            if ipaddress.ip_address(ip) in ipaddress.ip_network(sn["cidr"], strict=False):
                return sn
        except ValueError:
            continue
    return None


_CODE_TEXT = {
    "NO_ROUTE": "no route to the destination", "BLACKHOLE_ROUTE": "route is a blackhole",
    "INGRESS_DENIED": "destination security group ingress does not allow it",
    "EGRESS_DENIED": "source security group egress does not allow it",
    "ACL_INGRESS_DENIED": "destination subnet NACL blocks ingress", "ACL_EGRESS_DENIED": "source subnet NACL blocks egress",
    "ACL_RETURN_DENIED": "subnet NACL blocks the return traffic (stateless)",
    "NO_PUBLIC_IP": "no public IPv4 address for internet gateway egress",
    "IGW_DETACHED": "route to a detached internet gateway (blackhole)",
    "NAT_UNAVAILABLE": "NAT gateway unavailable", "NAT_NO_IGW_ROUTE": "NAT gateway's subnet has no route to an internet gateway",
    "NAT_PRIVATE": "private NAT gateway cannot reach the internet",
    "PEERING_INACTIVE": "VPC peering connection not active", "PEERING_NOT_TRANSITIVE": "VPC peering is not transitive",
    "PEERING_NO_RETURN_ROUTE": "no return route over the VPC peering connection",
    "PRIVATE_DEST_VIA_GATEWAY": "private destination is not routable via a gateway",
    "SOURCE_DEST_CHECK": "appliance has source/destination check enabled",
    "NOT_PUBLIC": "destination has no public IPv4 address", "NO_DESTINATION": "no network interface at the destination",
    "UNSUPPORTED_TARGET": "route target type is not simulated",
}
# Reachability Analyzer explanation codes (closest native code; others pass the netsim code through)
_EXPLANATION_CODE = {
    "INGRESS_DENIED": "ENI_SG_RULES_MISMATCH", "EGRESS_DENIED": "ENI_SG_RULES_MISMATCH",
    "ACL_INGRESS_DENIED": "SUBNET_ACL_RESTRICTION", "ACL_EGRESS_DENIED": "SUBNET_ACL_RESTRICTION",
    "ACL_RETURN_DENIED": "SUBNET_ACL_RESTRICTION", "NO_ROUTE": "NO_ROUTE_TO_DESTINATION",
    "PRIVATE_DEST_VIA_GATEWAY": "NO_ROUTE_TO_DESTINATION", "BLACKHOLE_ROUTE": "NO_ROUTE_TO_DESTINATION",
}


def _endpoint_ref(m, topo, ep: dict, nm):
    """Resolve an analyzer endpoint {instance_id | eni_id | ip [+ security_group_ids]} to a netsim
    interface id, or to a plain IP string (= outside the VPCs). A bare in-subnet IP that is no
    interface becomes a synthetic interface carrying the given SGs (the legacy verb's contract)."""
    if ep.get("instance_id"):
        _find_instance(m, ep["instance_id"])
        return _netsim()[1].primary_eni(ep["instance_id"])
    if ep.get("eni_id"):
        if ep["eni_id"] not in topo.interfaces:
            raise VpcError("InvalidNetworkInterfaceID.NotFound", f"The networkInterface ID '{ep['eni_id']}' does not exist")
        return ep["eni_id"]
    ip = ep.get("ip", "")
    hit = topo.iface_by_ip(ip)
    if hit is not None and hit.ip == ip:
        return hit.id
    sn = _find_subnet_for_ip(m, ip)
    if sn is not None and sn["id"] in topo.subnets:
        sgs = list(ep.get("security_group_ids") or [])
        iid = f"ip:{ip}"
        topo.add(nm.Interface(id=iid, subnet=sn["id"], ip=ip, groups=sgs, rulesets=sgs))
        return iid
    return ip


def reach(store, source: dict, dest: dict, port, protocol: str = "tcp", src_port=None):
    """netsim Verdict for two analyzer endpoints (dicts, see _endpoint_ref)."""
    ev, fa, nm = _netsim()
    m = _model(store)
    topo = fa.from_aws(m)
    src = _endpoint_ref(m, topo, source, nm)
    dst = _endpoint_ref(m, topo, dest, nm)
    return ev.reach(topo, src, dst, protocol, int(port) if port not in (None, "") else None, src_port)


def analyze_reachability(store, source: dict, dest: dict, port: int, protocol: str = "tcp") -> dict:
    """Evaluate whether `source` can reach `dest` on `port` with the shared netsim evaluator
    (routes, IGW/NAT/peering semantics, SGs, stateless NACLs incl. the ephemeral return path).
    source/dest: {ip, security_group_ids?} | {instance_id} | {eni_id}.
    Returns {reachable, reason, path: [step strings], code, hops: [...]}"""
    m = _model(store)
    if not (source.get("instance_id") or source.get("eni_id")) and _find_subnet_for_ip(m, source.get("ip", "")) is None:
        return {"reachable": False, "reason": "source IP is not in any subnet", "path": [], "code": "NO_SOURCE", "hops": []}
    v = reach(store, source, dest, port, protocol)
    path = [f"{h.component} {h.id}: {h.decision}" + (f" ({h.detail})" if h.detail else "") for h in v.hops]
    reason = "path is open" if v.reachable else f"{_CODE_TEXT.get(v.code, v.code)} — {v.reason}"
    return {"reachable": v.reachable, "reason": reason, "path": path, "code": v.code,
            "hops": [h.__dict__ for h in v.hops]}


def _analyze_reachability_action(store, params):
    """Simulator data-plane verb: AnalyzeReachability. Endpoints via Source.Ip /
    Source.SecurityGroupId.N / Source.InstanceId / Source.NetworkInterfaceId (same for Destination)."""
    def endpoint(prefix):
        sgs = [v for k, v in params.items() if k.startswith(f"{prefix}.SecurityGroupId")]
        return {"ip": params.get(f"{prefix}.Ip", ""), "security_group_ids": sgs,
                "instance_id": params.get(f"{prefix}.InstanceId", ""), "eni_id": params.get(f"{prefix}.NetworkInterfaceId", "")}
    result = analyze_reachability(store, endpoint("Source"), endpoint("Destination"),
                                  int(params.get("DestinationPort", 0) or 0),
                                  str(params.get("Protocol", "tcp")))
    steps = "".join(f"<item>{_xml_escape(s)}</item>" for s in result["path"])
    return _envelope("AnalyzeReachability",
                     f"<reachable>{str(result['reachable']).lower()}</reachable>"
                     f"<reason>{_xml_escape(result['reason'])}</reason>"
                     f"<code>{_xml_escape(result['code'])}</code>"
                     f"<path>{steps}</path>")


# ── VPC Reachability Analyzer (native EC2 API: Network Insights paths + analyses) ──
def _nip_xml(p: dict) -> str:
    return ("<item>"
            f"<networkInsightsPathId>{p['id']}</networkInsightsPathId>"
            f"<networkInsightsPathArn>arn:aws:ec2:us-east-1:{OWNER_ID}:network-insights-path/{p['id']}</networkInsightsPathArn>"
            f"<createdDate>{p['created']}</createdDate><source>{_xml_escape(p['source'])}</source>"
            f"<destination>{_xml_escape(p.get('destination', ''))}</destination>"
            + (f"<sourceIp>{_xml_escape(p['source_ip'])}</sourceIp>" if p.get("source_ip") else "")
            + (f"<destinationIp>{_xml_escape(p['destination_ip'])}</destinationIp>" if p.get("destination_ip") else "")
            + f"<protocol>{_xml_escape(p['protocol'])}</protocol>"
            + (f"<destinationPort>{p['destination_port']}</destinationPort>" if p.get("destination_port") is not None else "")
            + f"{_tags_xml(p.get('tags', {}))}</item>")


def _create_network_insights_path(store, params):
    m = _model(store)
    src, dst = str(params.get("Source", "")), str(params.get("Destination", ""))
    if not src:
        raise VpcError("MissingParameter", "The request must contain the parameter Source")
    if not dst and not params.get("DestinationIp"):
        raise VpcError("MissingParameter", "The request must contain Destination or DestinationIp")
    pid = _rid("nip", 17)
    m.setdefault("insights_paths", {})[pid] = {
        "id": pid, "created": _now(), "source": src, "destination": dst,
        "source_ip": str(params.get("SourceIp") or ""), "destination_ip": str(params.get("DestinationIp") or ""),
        "protocol": str(params.get("Protocol") or "tcp").lower(),
        "destination_port": int(params["DestinationPort"]) if params.get("DestinationPort") else None,
        "tags": _parse_tag_specifications(params).get("network-insights-path", {})}
    return _envelope("CreateNetworkInsightsPath",
                     f"<networkInsightsPath>{_nip_xml(m['insights_paths'][pid])[6:-7]}</networkInsightsPath>")


def _describe_network_insights_paths(store, params):
    m = _model(store)
    ids = [v for k, v in params.items() if k.startswith("NetworkInsightsPathId.")]
    rows = [p for p in m.get("insights_paths", {}).values() if not ids or p["id"] in ids]
    return _envelope("DescribeNetworkInsightsPaths", f"<networkInsightsPathSet>{''.join(_nip_xml(p) for p in rows)}</networkInsightsPathSet>")


def _delete_network_insights_path(store, params):
    m = _model(store)
    pid = str(params.get("NetworkInsightsPathId", ""))
    if pid not in m.get("insights_paths", {}):
        raise VpcError("InvalidNetworkInsightsPathId.NotFound", f"The network insights path '{pid}' does not exist")
    if any(a["path_id"] == pid for a in m.get("insights_analyses", {}).values()):
        raise VpcError("DependencyViolation", f"Network insights path {pid} has analyses; delete them first")
    m["insights_paths"].pop(pid)
    return _envelope("DeleteNetworkInsightsPath", f"<networkInsightsPathId>{pid}</networkInsightsPathId>")


def _insights_endpoint(m, rid: str, ip: str) -> dict:
    if rid.startswith("i-"):
        return {"instance_id": rid}
    if rid.startswith("eni-"):
        inst = next((i for i in m["instances"].values() if _netsim()[1].primary_eni(i["id"]) == rid), None)
        return {"instance_id": inst["id"]} if inst else {"eni_id": rid}
    if rid.startswith("igw-"):
        if rid not in m["igws"]:
            raise VpcError("InvalidInternetGatewayID.NotFound", f"The internetGateway ID '{rid}' does not exist")
        return {"ip": ip or "198.51.100.1"}                    # "the internet" behind this IGW
    return {"ip": ip or rid}


def _start_network_insights_analysis(store, params):
    m = _model(store)
    pid = str(params.get("NetworkInsightsPathId", ""))
    p = m.get("insights_paths", {}).get(pid)
    if p is None:
        raise VpcError("InvalidNetworkInsightsPathId.NotFound", f"The network insights path '{pid}' does not exist")
    src = _insights_endpoint(m, p["source"], p.get("source_ip", ""))
    dst = _insights_endpoint(m, p.get("destination") or "", p.get("destination_ip", ""))
    if p["source"].startswith("igw-"):                   # inbound: internet → resource
        src = {"ip": p.get("source_ip") or "198.51.100.1"}
        if dst.get("instance_id"):
            inst = _find_instance(m, dst["instance_id"])
            dst = {"ip": inst.get("public_ip") or inst.get("private_ip", "")}
    v = reach(store, src, dst, p.get("destination_port"), p["protocol"])
    aid = _rid("nia", 17)
    m.setdefault("insights_analyses", {})[aid] = {
        "id": aid, "path_id": pid, "start": _now(), "status": "succeeded", "found": v.reachable,
        "code": v.code, "reason": v.reason, "blocked_by": v.blocked_by,
        "hops": [h.__dict__ for h in v.hops], "tags": _parse_tag_specifications(params).get("network-insights-analysis", {})}
    return _envelope("StartNetworkInsightsAnalysis",
                     f"<networkInsightsAnalysis>{_nia_xml(m['insights_analyses'][aid])[6:-7]}</networkInsightsAnalysis>")


def _nia_xml(a: dict) -> str:
    comps = "".join(
        f"<item><sequenceNumber>{n}</sequenceNumber><component><id>{_xml_escape(h['id'])}</id>"
        f"<name>{_xml_escape(h['component'])}</name></component></item>"
        for n, h in enumerate((h for h in a["hops"] if h["decision"] != "deny"), 1))
    expl = ""
    if not a["found"]:
        expl = (f"<item><explanationCode>{_EXPLANATION_CODE.get(a['code'], a['code'])}</explanationCode>"
                f"<component><id>{_xml_escape(a.get('blocked_by') or '')}</id></component>"
                f"<direction>{'ingress' if 'INGRESS' in a['code'] else 'egress'}</direction>"
                f"<state>{_xml_escape(a['code'])}</state>"
                f"<explanation>{_xml_escape(_CODE_TEXT.get(a['code'], a['code']) + ' — ' + a['reason'])}</explanation></item>")
    return ("<item>"
            f"<networkInsightsAnalysisId>{a['id']}</networkInsightsAnalysisId>"
            f"<networkInsightsAnalysisArn>arn:aws:ec2:us-east-1:{OWNER_ID}:network-insights-analysis/{a['id']}</networkInsightsAnalysisArn>"
            f"<networkInsightsPathId>{a['path_id']}</networkInsightsPathId><startDate>{a['start']}</startDate>"
            f"<status>{a['status']}</status><networkPathFound>{str(a['found']).lower()}</networkPathFound>"
            f"<forwardPathComponentSet>{comps}</forwardPathComponentSet><explanationSet>{expl}</explanationSet>"
            f"{_tags_xml(a.get('tags', {}))}</item>")


def _describe_network_insights_analyses(store, params):
    m = _model(store)
    ids = [v for k, v in params.items() if k.startswith("NetworkInsightsAnalysisId.")]
    pid = params.get("NetworkInsightsPathId")
    rows = [a for a in m.get("insights_analyses", {}).values()
            if (not ids or a["id"] in ids) and (not pid or a["path_id"] == pid)]
    return _envelope("DescribeNetworkInsightsAnalyses",
                     f"<networkInsightsAnalysisSet>{''.join(_nia_xml(a) for a in rows)}</networkInsightsAnalysisSet>")


def _delete_network_insights_analysis(store, params):
    m = _model(store)
    aid = str(params.get("NetworkInsightsAnalysisId", ""))
    if aid not in m.get("insights_analyses", {}):
        raise VpcError("InvalidNetworkInsightsAnalysisId.NotFound", f"The network insights analysis '{aid}' does not exist")
    m["insights_analyses"].pop(aid)
    return _envelope("DeleteNetworkInsightsAnalysis", f"<networkInsightsAnalysisId>{aid}</networkInsightsAnalysisId>")


# ── VPC/subnet Flow Logs (config + lifecycle; see core/netsim/flowlogs.py for the
#    real per-flow record renderer the offline Docker enforcer feeds — not wired to this
#    EC2 API yet, so DescribeFlowLogs always answers with an empty record stream) ──
_FLOW_RESOURCE_PREFIXES = {"VPC": ("vpc-", "vpcs"), "Subnet": ("subnet-", "subnets"), "NetworkInterface": ("eni-", "enis")}


def _flow_log_xml(f: dict) -> str:
    return ("<item>"
            f"<flowLogId>{f['id']}</flowLogId><flowLogStatus>{f['status']}</flowLogStatus>"
            f"<creationTime>{f['created']}</creationTime><resourceId>{f['resource_id']}</resourceId>"
            f"<trafficType>{f['traffic_type']}</trafficType><logDestinationType>{f['log_destination_type']}</logDestinationType>"
            + (f"<logGroupName>{_xml_escape(f['log_group_name'])}</logGroupName>" if f.get("log_group_name") else "")
            + (f"<logDestination>{_xml_escape(f['log_destination'])}</logDestination>" if f.get("log_destination") else "")
            + f"<logFormat>{_xml_escape(f['log_format'])}</logFormat>"
            + f"<deliverLogsStatus>{f['deliver_logs_status']}</deliverLogsStatus>"
            + (f"<deliverLogsPermissionArn>{_xml_escape(f['deliver_logs_permission_arn'])}</deliverLogsPermissionArn>" if f.get("deliver_logs_permission_arn") else "")
            + f"<maxAggregationInterval>{f['max_aggregation_interval']}</maxAggregationInterval>"
            + f"{_tags_xml(f.get('tags', {}))}</item>")


def _create_flow_logs(store, params):
    m = _model(store)
    rtype = str(params.get("ResourceType", "VPC"))
    if rtype not in _FLOW_RESOURCE_PREFIXES:
        raise VpcError("InvalidParameterValue", f"ResourceType '{rtype}' is not supported")
    prefix, coll_name = _FLOW_RESOURCE_PREFIXES[rtype]
    rids = [v for k, v in sorted(params.items()) if k.startswith("ResourceId.") or k.startswith("ResourceIds.")]
    if not rids:
        raise VpcError("MissingParameter", "The request must contain the parameter ResourceId")
    coll = m[coll_name]
    ids, unsuccessful = [], []
    for rid in rids:
        if not str(rid).startswith(prefix) or rid not in coll:
            unsuccessful.append((rid, "InvalidParameterValue", f"{rtype} '{rid}' does not exist"))
            continue
        fid = _rid("fl", 17)
        m.setdefault("flow_logs", {})[fid] = {
            "id": fid, "resource_id": rid, "resource_type": rtype, "status": "ACTIVE",
            "traffic_type": str(params.get("TrafficType", "ALL")),
            "log_destination_type": str(params.get("LogDestinationType", "cloud-watch-logs")),
            "log_group_name": str(params.get("LogGroupName", "")), "log_destination": str(params.get("LogDestination", "")),
            "log_format": str(params.get("LogFormat") or "${version} ${account-id} ${interface-id} ${srcaddr} ${dstaddr} ${srcport} ${dstport} ${protocol} ${packets} ${bytes} ${start} ${end} ${action} ${log-status}"),
            "deliver_logs_status": "SUCCESS", "deliver_logs_permission_arn": str(params.get("DeliverLogsPermissionArn", "")),
            "max_aggregation_interval": int(params.get("MaxAggregationInterval", 600) or 600),
            "created": _now(), "tags": _parse_tag_specifications(params).get("vpc-flow-log", {})}
        ids.append(fid)
    body = "<flowLogIdSet>" + "".join(f"<item>{i}</item>" for i in ids) + "</flowLogIdSet>"
    body += "<unsuccessful>" + "".join(
        f"<item><resourceId>{_xml_escape(str(rid))}</resourceId><error><code>{code}</code><message>{_xml_escape(msg)}</message></error></item>"
        for rid, code, msg in unsuccessful) + "</unsuccessful>"
    return _envelope("CreateFlowLogs", body)


def _describe_flow_logs(store, params):
    m = _model(store)
    ids = [v for k, v in params.items() if k.startswith("FlowLogId.")]
    rows = [f for f in m.get("flow_logs", {}).values() if not ids or f["id"] in ids]
    return _envelope("DescribeFlowLogs", f"<flowLogSet>{''.join(_flow_log_xml(f) for f in rows)}</flowLogSet>")


def _delete_flow_logs(store, params):
    m = _model(store)
    ids = [v for k, v in params.items() if k.startswith("FlowLogId.")]
    unsuccessful = []
    for fid in ids:
        if fid in m.get("flow_logs", {}):
            m["flow_logs"].pop(fid)
        else:
            unsuccessful.append(fid)
    body = "<unsuccessful>" + "".join(
        f"<item><resourceId>{fid}</resourceId><error><code>InvalidFlowLogId.NotFound</code><message>FlowLog '{fid}' does not exist</message></error></item>"
        for fid in unsuccessful) + "</unsuccessful>"
    return _envelope("DeleteFlowLogs", body)


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
        nacl_id = _create_default_nacl(m, vpc_id)
        m["vpcs"][vpc_id] = {"id": vpc_id, "cidr": "172.31.0.0/16", "igw": None, "default": True,
                             "default_nacl": nacl_id, "tenancy": "default", "dhcp_options_id": _default_dhcp_options(m),
                             "enable_dns_hostnames": True, "enable_dns_support": True, "tags": {}}
        rt_id = _rid("rtb")
        m["route_tables"][rt_id] = {"id": rt_id, "vpc_id": vpc_id, "main": True,
                                    "routes": [{"dest": "172.31.0.0/16", "target": "local"}], "subnets": [], "tags": {}}
        for i, az in enumerate(_AZS):
            subnet_id = _rid("subnet")
            m["subnets"][subnet_id] = {"id": subnet_id, "vpc_id": vpc_id, "cidr": f"172.31.{i}.0/24",
                                       "az": az, "route_table": rt_id, "nacl": nacl_id, "default": True,
                                       "map_public_ip": True, "tags": {}}
            m["route_tables"][rt_id]["subnets"].append(subnet_id)
            m["nacls"][nacl_id]["subnets"].append(subnet_id)
        igw_id = _rid("igw")
        m["igws"][igw_id] = {"id": igw_id, "vpc_id": vpc_id, "tags": {}}
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
            m["addresses"], m["enis"], m["placement_groups"], m["launch_templates"], m["key_pairs"],
            m["vpcs"], m["subnets"], m["route_tables"], m["igws"], m["nacls"], m["nat_gateways"],
            m["eigws"], m["dhcp_options"], m["prefix_lists"], m["peering_connections"], m["route_servers"],
            m.get("flow_logs", {}), m.get("insights_paths", {}), m.get("insights_analyses", {})]


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


def _used_ips(m: dict, subnet_id: str) -> set:
    used = set()
    for i in m["instances"].values():
        if i.get("subnet_id") == subnet_id and i.get("state") != "terminated":
            used.add(i.get("private_ip"))
    for e in m["enis"].values():
        if e.get("subnet_id") == subnet_id:
            used.add(e.get("private_ip"))
    for g in m["nat_gateways"].values():
        if g.get("subnet_id") == subnet_id:
            used.add(g.get("private_ip"))
    return used


def _allocate_private_ip(m: dict, subnet_id: str, requested: str = "") -> str:
    """A private IPv4 from the SUBNET's own CIDR, like EC2: the first four addresses (network,
    VPC router, DNS, reserved) and the last (broadcast) are never handed out; a requested
    address must be inside the subnet, not reserved and not in use."""
    sn = m["subnets"].get(subnet_id)
    if sn is None:
        return requested or _pseudo_ip(len(m["instances"]))
    net = ipaddress.ip_network(sn["cidr"], strict=False)
    used = _used_ips(m, subnet_id)
    reserved = [ipaddress.ip_network(r["cidr"], strict=False) for r in m["subnet_cidr_reservations"].values()
                if r["subnet_id"] == subnet_id]
    first, last = int(net.network_address) + 4, int(net.broadcast_address) - 1
    if requested:
        try:
            ip = ipaddress.ip_address(requested)
        except ValueError:
            raise VpcError("InvalidParameterValue", f"Invalid IPv4 address: {requested}")
        if ip not in net:
            raise VpcError("InvalidParameterValue", f"Address {requested} does not fall within the subnet's address range")
        if not first <= int(ip) <= last:
            raise VpcError("InvalidParameterValue", f"Address {requested} is reserved by AWS in subnet {subnet_id}")
        if any(ip in r for r in reserved):
            raise VpcError("InvalidParameterValue", f"Address {requested} is in a reserved CIDR block in subnet {subnet_id}")
        if requested in used:
            raise VpcError("InvalidIPAddress.InUse", f"Address {requested} is in use.")
        return requested
    for n in range(first, last + 1):
        cand_ip = ipaddress.ip_address(n)
        cand = str(cand_ip)
        if cand not in used and not any(cand_ip in r for r in reserved):
            return cand
    raise VpcError("InsufficientFreeAddressesInSubnet", f"There are not enough free addresses in subnet '{subnet_id}' to satisfy the requested number of instances.")


def _bool_param(params: dict, key: str):
    v = params.get(key)
    return None if v is None or v == "" else str(v).lower() == "true"


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
    partition_xml = f"<partitionNumber>{inst['partition_number']}</partitionNumber>" if inst.get("partition_number") else ""
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
        f"<groupName>{_xml_escape(inst.get('placement_group', ''))}</groupName>{partition_xml}</placement>"
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
        f"<sourceDestCheck>{str(inst.get('source_dest_check', True)).lower()}</sourceDestCheck>"
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


def _image_provider(image: dict) -> str:
    owner = image.get("owner_id", "")
    if owner == "amazon":
        return "amazon"
    if owner == OWNER_ID:
        return "self"
    return "aws-marketplace"


def _check_allowed_images(m: dict, image: dict) -> None:
    acct = m["account"]
    if not acct["allowed_images_enabled"]:
        return
    criteria = acct["allowed_images_criteria"]
    provider = _image_provider(image)
    if not any(provider in c.get("providers", []) for c in criteria):
        raise VpcError("UnauthorizedImage",
                        f"The image '{image['id']}' is not on the account's allowed AMIs list "
                        f"(provider '{provider}' doesn't match any configured image criteria).")


def _launch_one(m: dict, params: dict, tag_specs: dict, idx: int) -> dict:
    image_id = str(params.get("ImageId") or _default_ami_id(m))
    image = m["images"].get(image_id)
    if image is None:
        raise VpcError("InvalidAMIID.NotFound", f"The image id '[{image_id}]' does not exist.")
    _check_allowed_images(m, image)
    vpc_id, default_subnet, default_sg = _ensure_default_network(m)
    subnet_id = str(params.get("SubnetId") or params.get("NetworkInterface.1.SubnetId") or default_subnet)
    subnet = m["subnets"].get(subnet_id)
    if params.get("SubnetId") and subnet is None:
        raise VpcError("InvalidSubnetID.NotFound", f"The subnet ID '{subnet_id}' does not exist")
    if subnet is not None:
        vpc_id = subnet["vpc_id"]
    az = str(params.get("Placement.AvailabilityZone") or (subnet or {}).get("az") or _AZS[idx % len(_AZS)])
    sg_ids = [v for k, v in params.items() if k.startswith("SecurityGroupId.")] or \
             [v for k, v in params.items() if k.startswith("SecurityGroupIds.")] or \
             [v for k, v in params.items() if k.startswith("NetworkInterface.1.SecurityGroupId.")] or \
             [_vpc_default_sg(m, vpc_id, default_sg)]
    for sgid in sg_ids:
        sg = m["sgs"].get(sgid)
        if sg is None:
            raise VpcError("InvalidGroup.NotFound", f"The security group '{sgid}' does not exist.")
        if sg["vpc_id"] != vpc_id and vpc_id not in sg.get("vpc_associations", []):
            raise VpcError("InvalidParameterValue",
                            f"Security group {sgid} and subnet/VPC {vpc_id} belong to different networks "
                            f"(associate it with this VPC first — AssociateSecurityGroupVpc).")
    group_name = str(params.get("Placement.GroupName") or "")
    partition_number = None
    if group_name:
        pg = next((p for p in m["placement_groups"].values() if p["name"] == group_name), None)
        if pg is None:
            raise VpcError("InvalidPlacementGroup.Unknown", f"The placement group '{group_name}' is unknown.")
        members = [i for i in m["instances"].values() if i.get("placement_group") == group_name and i["state"] in ("pending", "running")]
        if pg["strategy"] == "spread":
            in_az = sum(1 for i in members if i["az"] == az)
            if in_az >= 7:
                raise VpcError("InsufficientInstanceCapacity",
                                f"Insufficient capacity to launch instance into spread placement group '{group_name}': "
                                f"a spread placement group supports a maximum of 7 running instances per Availability Zone.")
        elif pg["strategy"] == "partition":
            partition_count = pg.get("partition_count") or 2
            partition_number = (len(members) % partition_count) + 1
    instance_id = "i-" + uuid.uuid4().hex[:17]
    n = len(m["instances"]) + idx
    requested_ip = str(params.get("PrivateIpAddress") or params.get("NetworkInterface.1.PrivateIpAddress") or "")
    private_ip = _allocate_private_ip(m, subnet_id, requested_ip if idx == 0 else "")
    # EC2 rule: a public IPv4 only when the launch asks for one (AssociatePublicIpAddress on the
    # primary interface) or, absent that, when the subnet has MapPublicIpOnLaunch (default VPC: on).
    assoc = _bool_param(params, "NetworkInterface.1.AssociatePublicIpAddress")
    auto_public = assoc if assoc is not None else bool((subnet or {}).get("map_public_ip"))
    public_ip = _pseudo_public_ip(n) if auto_public else ""
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
    instance_type = str(params.get("InstanceType") or "t3.micro")
    family = instance_type.split(".")[0]
    default_credits = m["account"]["default_credit_specification"].get(family, "standard")
    inst = {
        "id": instance_id, "image_id": image_id, "state": "running", "instance_type": instance_type,
        "launch_time": _now(), "az": az, "vpc_id": vpc_id, "subnet_id": subnet_id, "sg_ids": sg_ids,
        "private_ip": private_ip, "public_ip": public_ip, "auto_public_ip": auto_public, "source_dest_check": True,
        "public_dns": f"ec2-{public_ip.replace('.', '-')}.compute-1.amazonaws.com" if public_ip else "",
        "private_dns": f"ip-{private_ip.replace('.', '-')}.ec2.internal",
        "key_name": str(params.get("KeyName") or ""), "monitoring": str(params.get("Monitoring.Enabled", "")).lower() == "true",
        "architecture": image.get("architecture", "x86_64"), "root_device_type": "ebs", "root_device_name": "/dev/xvda",
        "virtualization_type": image.get("virtualization_type", "hvm"), "hypervisor": "nitro",
        "platform": image.get("platform", ""), "platform_details": "Windows" if image.get("platform") == "windows" else "Linux/UNIX",
        "ebs_optimized": True, "termination_protection": str(params.get("DisableApiTermination", "")).lower() == "true",
        "stop_protection": False, "shutdown_behavior": str(params.get("InstanceInitiatedShutdownBehavior") or "stop"),
        "tenancy": str(params.get("Placement.Tenancy") or "default"), "placement_group": group_name, "partition_number": partition_number,
        "iam_instance_profile": str(params.get("IamInstanceProfile.Name") or params.get("IamInstanceProfile.Arn") or ""),
        "credit_spec": str(params.get("CreditSpecification.CpuCredits") or default_credits),
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
            if not inst.get("elastic_ip"):
                inst["public_dns"] = ""
        if action == "start":
            n = len(m["instances"])
            if not inst.get("elastic_ip") and inst.get("auto_public_ip", True):
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


def apply_alarm_action(store, instance_id: str, action: str) -> bool:
    """Called by cloudwatch_core when a CloudWatch alarm fires an EC2 action ARN
    (arn:aws:automate:<region>:ec2:stop|terminate|reboot — see
    aws.cloudwatch.alarms.actions.ec2). Reuses the same state-change path RunInstances'
    StopInstances/TerminateInstances/RebootInstances go through, so stop/termination
    protection is honoured exactly as it is for a direct API call: a protected instance's
    action fails, which the alarm records as a failed action, same as real AWS."""
    m = _model(store)
    if instance_id not in m["instances"]:
        return False
    try:
        if action == "stop":
            _instance_state_change(store, {"InstanceId.1": instance_id}, "stop", "stopped")
        elif action == "terminate":
            _instance_state_change(store, {"InstanceId.1": instance_id}, "terminate", "terminated")
        elif action == "reboot":
            _reboot_instances(store, {"InstanceId.1": instance_id})
        else:
            return False
    except VpcError:
        return False
    return True


def launch_for_autoscaling(store, az: str | None = None, instance_type: str | None = None,
                            image_id: str | None = None, tags: dict | None = None,
                            subnet_id: str | None = None, security_group_ids: list | None = None,
                            key_name: str | None = None) -> str:
    """Called by autoscaling_core when a group scales out: launches one instance through
    the SAME `_launch_one` path RunInstances uses, so a scaled group's instances are
    indistinguishable from any other EC2 instance in the console (see
    aws.cloudwatch.alarms.actions.compute and ec2.auto-scaling)."""
    m = _model(store)
    params: dict = {}
    if image_id:
        params["ImageId"] = image_id
    if instance_type:
        params["InstanceType"] = instance_type
    if az:
        params["Placement.AvailabilityZone"] = az
    if subnet_id:
        params["SubnetId"] = subnet_id
    if key_name:
        params["KeyName"] = key_name
    for i, sgid in enumerate(security_group_ids or [], start=1):
        params[f"SecurityGroupIds.{i}"] = sgid
    inst = _launch_one(m, params, {"instance": dict(tags or {})}, 0)
    return inst["id"]


def resolve_launch_template(store, lt_id: str | None, lt_name: str | None, version: str | None) -> dict | None:
    """Auto Scaling groups and `aws ec2 run-instances --launch-template` both reference a
    template by id/name + version ($Latest/$Default/N) — resolve to its LaunchTemplateData
    dict (or None if not found), for callers (autoscaling_core) that need ImageId/InstanceType/
    SubnetId/SecurityGroupIds/KeyName without re-implementing the version lookup."""
    m = _model(store)
    lt = None
    if lt_id:
        lt = m["launch_templates"].get(str(lt_id))
    elif lt_name:
        lt = next((t for t in m["launch_templates"].values() if t["name"] == lt_name), None)
    if lt is None:
        return None
    v = str(version or "$Default")
    if v == "$Default":
        vnum = lt["default_version"]
    elif v == "$Latest":
        vnum = lt["latest_version"]
    else:
        try:
            vnum = int(v)
        except ValueError:
            return None
    ver = lt["versions"].get(vnum)
    return dict(ver["data"]) if ver else None


def terminate_for_autoscaling(store, instance_id: str) -> bool:
    """Called by autoscaling_core when a group scales in: reuses the same termination
    path TerminateInstances uses (see aws.cloudwatch.alarms.actions.compute)."""
    try:
        _instance_state_change(store, {"InstanceId.1": instance_id}, "terminate", "terminated")
        return True
    except VpcError:
        return False


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
    sdc = _bool_param(params, "SourceDestCheck.Value")
    if sdc is not None:
        inst["source_dest_check"] = sdc
    groups = [v for k, v in params.items() if k.startswith("GroupId.")]
    if groups:
        inst["sg_ids"] = groups
    return _envelope("ModifyInstanceAttribute", "<return>true</return>")


def _modify_subnet_attribute(store, params):
    m = _model(store)
    sid = str(params.get("SubnetId", ""))
    sn = m["subnets"].get(sid)
    if sn is None:
        raise VpcError("InvalidSubnetID.NotFound", f"The subnet ID '{sid}' does not exist")
    v = _bool_param(params, "MapPublicIpOnLaunch.Value")
    if v is not None:
        sn["map_public_ip"] = v
    return _envelope("ModifySubnetAttribute", "<return>true</return>")


def _modify_network_interface_attribute(store, params):
    m = _model(store)
    eni_id = str(params.get("NetworkInterfaceId", ""))
    e = m["enis"].get(eni_id)
    if e is None:
        raise VpcError("InvalidNetworkInterfaceID.NotFound", f"The networkInterface ID '{eni_id}' does not exist")
    sdc = _bool_param(params, "SourceDestCheck.Value")
    if sdc is not None:
        e["source_dest_check"] = sdc
    if "Description.Value" in params:
        e["description"] = str(params["Description.Value"])
    groups = [v for k, v in params.items() if k.startswith("SecurityGroupId.")]
    if groups:
        e["sg_ids"] = groups
    return _envelope("ModifyNetworkInterfaceAttribute", "<return>true</return>")


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


def _instance_status_xml(inst: dict) -> str:
    ok = inst["state"] == "running"
    status = "ok" if ok else "not-applicable"
    details = ("<details><item><name>reachability</name><status>passed</status></item></details>" if ok else "")
    return ("<item>"
            f"<instanceId>{_xml_escape(inst['id'])}</instanceId>"
            f"<availabilityZone>{_xml_escape(inst['az'])}</availabilityZone>"
            f"<instanceState><code>{_STATE_CODE.get(inst['state'], 0)}</code><name>{_xml_escape(inst['state'])}</name></instanceState>"
            f"<systemStatus><status>{status}</status>{details}</systemStatus>"
            f"<instanceStatus><status>{status}</status>{details}</instanceStatus>"
            "<eventsSet/>"
            "</item>")


_STATUS_METRICS = ("StatusCheckFailed", "StatusCheckFailed_Instance", "StatusCheckFailed_System")


def _push_status_metrics(store, inst: dict, now: float) -> None:
    """Publish the one CloudWatch metric family Vyomi can honestly derive from an instance's
    own lifecycle state (see ec2.instances.monitoring / ec2.instances.alarms-metrics): a
    running instance always passes, so each point is 0. The 'detailed monitoring' flag sets
    how often a poll is allowed to record a fresh point (1 vs 5 minutes), same as AWS's basic
    vs detailed monitoring granularity — there's no background ticker, so a point lands only
    when something (DescribeInstanceStatus) actually asks."""
    cw = getattr(store, "cw_store", None)
    if cw is None or inst.get("state") != "running":
        return
    period = 60.0 if inst.get("monitoring") else 300.0
    if now - (inst.get("_last_metric_ts") or 0.0) < period:
        return
    inst["_last_metric_ts"] = now
    dims = [{"Name": "InstanceId", "Value": inst["id"]}]
    for name in _STATUS_METRICS:
        _cw_core.ingest_internal_metric(cw, "AWS/EC2", name, dims, 0.0, unit="Count", ts=now)


def _describe_instance_status(store, params):
    m = _model(store)
    ids = [v for k, v in params.items() if k.startswith("InstanceId.")]
    include_all = str(params.get("IncludeAllInstances", "")).lower() == "true"
    rows = [m["instances"][i] for i in ids if i in m["instances"]] if ids else list(m["instances"].values())
    if not include_all:
        rows = [r for r in rows if r["state"] == "running"]
    now = time.time()
    for r in rows:
        _push_status_metrics(store, r, now)
    return _envelope("DescribeInstanceStatus", f"<instanceStatusSet>{''.join(_instance_status_xml(r) for r in rows)}</instanceStatusSet>")


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
            f"<groupSet>{sgs}</groupSet>{att_xml}<sourceDestCheck>{str(e.get('source_dest_check', True)).lower()}</sourceDestCheck>"
            f"{_tags_xml(e.get('tags', {}))}"
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
         "private_ip": _allocate_private_ip(m, subnet_id, str(params.get("PrivateIpAddress") or "")), "public_ip": "",
         "sg_ids": sgs or [_vpc_default_sg(m, subnet["vpc_id"], "")], "attachment": None, "source_dest_check": True,
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


# ── security group VPC associations (AssociateSecurityGroupVpc) ────────────
# The real AWS RAM service shares resources ACROSS accounts; Vyomi simulates one
# account, so there is no second principal to share with (ec2.security-groups.sharing
# limitation). What IS a real, same-account AWS feature — and what AWS's own console
# surfaces under this same "sharing" workflow — is making a security group created in
# one VPC usable by ENIs/instances in ANOTHER VPC, without copying its rules. We model
# that for real: RunInstances enforces it (see _launch_one), so a security group from a
# foreign VPC is genuinely rejected unless associated first.
def _sgvpc_assoc_xml(sg: dict, vpc_id: str, state: str) -> str:
    return ("<item>"
            f"<groupId>{_xml_escape(sg['id'])}</groupId><vpcId>{_xml_escape(vpc_id)}</vpcId>"
            f"<state>{_xml_escape(state)}</state>"
            "</item>")


def _associate_security_group_vpc(store, params):
    m = _model(store)
    sg = _find_sg(m, params.get("GroupId"))
    vpc_id = str(_req(params, "VpcId"))
    if vpc_id not in m["vpcs"]:
        raise VpcError("InvalidVpcID.NotFound", f"VPC {vpc_id} not found.")
    if vpc_id == sg["vpc_id"]:
        raise VpcError("InvalidParameterValue", "The security group already belongs to this VPC.")
    assoc = sg.setdefault("vpc_associations", [])
    if vpc_id not in assoc:
        assoc.append(vpc_id)
    return _envelope("AssociateSecurityGroupVpc", _sgvpc_assoc_xml(sg, vpc_id, "associated"))


def _disassociate_security_group_vpc(store, params):
    m = _model(store)
    sg = _find_sg(m, params.get("GroupId"))
    vpc_id = str(_req(params, "VpcId"))
    assoc = sg.setdefault("vpc_associations", [])
    for inst in m["instances"].values():
        if inst.get("vpc_id") == vpc_id and sg["id"] in inst.get("sg_ids", []) and inst["state"] != "terminated":
            raise VpcError("DependencyViolation",
                            f"resource {sg['id']} has a dependent object in VPC {vpc_id} (in use by {inst['id']}).")
    if vpc_id in assoc:
        assoc.remove(vpc_id)
    return _envelope("DisassociateSecurityGroupVpc", _sgvpc_assoc_xml(sg, vpc_id, "disassociated"))


def _describe_security_group_vpc_associations(store, params):
    m = _model(store)
    group_ids = [v for k, v in params.items() if k.startswith("GroupId.")]
    vpc_ids = [v for k, v in params.items() if k.startswith("VpcId.")]
    rows = []
    for sg in m["sgs"].values():
        if group_ids and sg["id"] not in group_ids:
            continue
        for vpc_id in sg.get("vpc_associations", []):
            if vpc_ids and vpc_id not in vpc_ids:
                continue
            rows.append(_sgvpc_assoc_xml(sg, vpc_id, "associated"))
    return _envelope("DescribeSecurityGroupVpcAssociations", f"<securityGroupVpcAssociationSet>{''.join(rows)}</securityGroupVpcAssociationSet>")


def _req(params, key):
    v = params.get(key)
    if v is None or v == "":
        raise VpcError("MissingParameter", f"The request must contain the parameter {key}.")
    return v


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
    strategy = str(params.get("Strategy") or "cluster")
    partition_count = int(params["PartitionCount"]) if params.get("PartitionCount") else (2 if strategy == "partition" else None)
    pg = {"id": pg_id, "name": name, "strategy": strategy, "state": "available",
          "partition_count": partition_count,
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
    in_use = any(i.get("placement_group") == name and i["state"] in ("pending", "running", "stopping", "stopped") for i in m["instances"].values())
    if in_use:
        raise VpcError("InvalidPlacementGroup.InUse", f"The placement group '{name}' has running or stopped instances in it and cannot be deleted.")
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


def _lt_version_data_xml(data: dict) -> str:
    out = []
    if data.get("ImageId"):
        out.append(f"<imageId>{_xml_escape(data['ImageId'])}</imageId>")
    if data.get("InstanceType"):
        out.append(f"<instanceType>{_xml_escape(data['InstanceType'])}</instanceType>")
    if data.get("KeyName"):
        out.append(f"<keyName>{_xml_escape(data['KeyName'])}</keyName>")
    if data.get("SubnetId"):
        out.append(f"<networkInterfaceSet><item><subnetId>{_xml_escape(data['SubnetId'])}</subnetId></item></networkInterfaceSet>")
    sg_ids = [v for k, v in data.items() if k.startswith("SecurityGroupIds.")]
    if sg_ids:
        out.append("<securityGroupIdSet>" + "".join(f"<item>{_xml_escape(g)}</item>" for g in sg_ids) + "</securityGroupIdSet>")
    if data.get("UserData"):
        out.append(f"<userData>{_xml_escape(data['UserData'])}</userData>")
    if data.get("InstanceInitiatedShutdownBehavior"):
        out.append(f"<instanceInitiatedShutdownBehavior>{_xml_escape(data['InstanceInitiatedShutdownBehavior'])}</instanceInitiatedShutdownBehavior>")
    if "DisableApiTermination" in data:
        out.append(f"<disableApiTermination>{str(data['DisableApiTermination']).lower()}</disableApiTermination>")
    name = data.get("IamInstanceProfile.Name")
    if name:
        out.append(f"<iamInstanceProfile><name>{_xml_escape(name)}</name></iamInstanceProfile>")
    bdm = "".join(
        f"<item><deviceName>{_xml_escape(v)}</deviceName></item>"
        for k, v in data.items() if k.endswith(".DeviceName") and k.startswith("BlockDeviceMapping."))
    if bdm:
        out.append(f"<blockDeviceMappingSet>{bdm}</blockDeviceMappingSet>")
    return "".join(out)


def _ltv_xml(lt: dict, v: dict) -> str:
    return ("<item>"
            f"<launchTemplateId>{_xml_escape(lt['id'])}</launchTemplateId><launchTemplateName>{_xml_escape(lt['name'])}</launchTemplateName>"
            f"<versionNumber>{v['version']}</versionNumber><versionDescription>{_xml_escape(v.get('description', ''))}</versionDescription>"
            f"<createTime>{_xml_escape(v.get('create_time') or lt['create_time'])}</createTime><createdBy>{_xml_escape(lt['created_by'])}</createdBy>"
            f"<defaultVersion>{str(v['version'] == lt['default_version']).lower()}</defaultVersion>"
            f"<launchTemplateData>{_lt_version_data_xml(v.get('data', {}))}</launchTemplateData>"
            "</item>")


def _find_launch_template(m, params) -> dict:
    lt_id = params.get("LaunchTemplateId")
    name = params.get("LaunchTemplateName")
    target = next((lt for lt in m["launch_templates"].values() if (lt_id and lt["id"] == lt_id) or (name and lt["name"] == name)), None)
    if target is None:
        raise VpcError("InvalidLaunchTemplateId.NotFound", "Launch template not found.")
    # Nano persists state as JSON, which turns the int version keys into strings
    if any(not isinstance(k, int) for k in target["versions"]):
        target["versions"] = {int(k): v for k, v in target["versions"].items()}
    return target


def _create_launch_template(store, params):
    m = _model(store)
    name = str(params.get("LaunchTemplateName"))
    if any(lt["name"] == name for lt in m["launch_templates"].values()):
        raise VpcError("InvalidLaunchTemplateName.AlreadyExistsException", f"Launch template name '{name}' already in use.")
    lt_id = _rid("lt")
    lt = {"id": lt_id, "name": name, "default_version": 1, "latest_version": 1, "create_time": _now(),
          "created_by": f"arn:aws:iam::{OWNER_ID}:root", "tags": _parse_tag_specifications(params).get("launch-template", {}),
          "versions": {1: {"version": 1, "description": str(params.get("VersionDescription") or ""), "data": _lt_data(params), "create_time": _now()}}}
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


def _create_launch_template_version(store, params):
    m = _model(store)
    lt = _find_launch_template(m, params)
    source_version = params.get("SourceVersion")
    base_data = {}
    if source_version is not None:
        sv = lt["versions"].get(int(source_version))
        if sv is None:
            raise VpcError("InvalidLaunchTemplateId.VersionNotFound", f"Launch template version '{source_version}' is unknown.")
        base_data = dict(sv["data"])
    new_data = {**base_data, **_lt_data(params)}
    version_num = lt["latest_version"] + 1
    v = {"version": version_num, "description": str(params.get("VersionDescription") or ""), "data": new_data, "create_time": _now()}
    lt["versions"][version_num] = v
    lt["latest_version"] = version_num
    return _envelope("CreateLaunchTemplateVersion", _ltv_xml(lt, v).replace("<item>", "<launchTemplateVersion>").replace("</item>", "</launchTemplateVersion>"))


def _describe_launch_template_versions(store, params):
    m = _model(store)
    lt = _find_launch_template(m, params)
    versions = [lt["versions"][k] for k in sorted(lt["versions"])]
    wanted = [v for k, v in params.items() if k.startswith("LaunchTemplateVersion.")]
    if wanted:
        versions = [v for v in versions if str(v["version"]) in wanted]
    else:
        min_v, max_v = params.get("MinVersion"), params.get("MaxVersion")
        if min_v is not None:
            versions = [v for v in versions if v["version"] >= int(min_v)]
        if max_v is not None:
            versions = [v for v in versions if v["version"] <= int(max_v)]
    return _envelope("DescribeLaunchTemplateVersions", f"<launchTemplateVersionSet>{''.join(_ltv_xml(lt, v) for v in versions)}</launchTemplateVersionSet>")


def _modify_launch_template(store, params):
    m = _model(store)
    lt = _find_launch_template(m, params)
    default_version = params.get("DefaultVersion")
    if default_version is not None:
        v = int(default_version)
        if v not in lt["versions"]:
            raise VpcError("InvalidLaunchTemplateId.VersionNotFound", f"Launch template version '{default_version}' is unknown.")
        lt["default_version"] = v
    return _envelope("ModifyLaunchTemplate", _lt_xml(lt).replace("<item>", "<launchTemplate>").replace("</item>", "</launchTemplate>"))


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


# ── Allowed AMIs (account setting, EC2 Settings > Allowed AMIs) ─────────────
def _allowed_images_xml(acct: dict) -> str:
    criteria = "".join(
        "<item><imageProviders>" + "".join(f"<item>{_xml_escape(p)}</item>" for p in c.get("providers", [])) + "</imageProviders></item>"
        for c in acct["allowed_images_criteria"])
    return (f"<allowedImagesSettingsState>{'enabled' if acct['allowed_images_enabled'] else 'disabled'}</allowedImagesSettingsState>"
            f"<imageCriteria>{criteria}</imageCriteria>")


def _get_allowed_images_settings(store, params):
    return _envelope("GetAllowedImagesSettings", _allowed_images_xml(_model(store)["account"]))


def _set_allowed_images_settings(store, params, enabled):
    acct = _model(store)["account"]
    acct["allowed_images_enabled"] = enabled
    action = "EnableAllowedImagesSettings" if enabled else "DisableAllowedImagesSettings"
    return _envelope(action, f"<allowedImagesSettingsState>{'enabled' if enabled else 'disabled'}</allowedImagesSettingsState>")


def _replace_image_criteria_in_allowed_images_settings(store, params):
    acct = _model(store)["account"]
    criteria = []
    i = 1
    while f"ImageCriteria.{i}.ImageProviders.1" in params or any(k.startswith(f"ImageCriteria.{i}.ImageProviders.") for k in params):
        providers = [v for k, v in params.items() if k.startswith(f"ImageCriteria.{i}.ImageProviders.")]
        if not providers:
            break
        criteria.append({"providers": providers})
        i += 1
    acct["allowed_images_criteria"] = criteria
    return _envelope("ReplaceImageCriteriaInAllowedImagesSettings", "<return>true</return>")


# ── EC2 Serial Console access (account setting) ─────────────────────────────
def _get_serial_console_access_status(store, params):
    enabled = _model(store)["account"]["serial_console_enabled"]
    return _envelope("GetSerialConsoleAccessStatus", f"<serialConsoleAccessEnabled>{str(enabled).lower()}</serialConsoleAccessEnabled>")


def _set_serial_console_access(store, params, enabled):
    _model(store)["account"]["serial_console_enabled"] = enabled
    action = "EnableSerialConsoleAccess" if enabled else "DisableSerialConsoleAccess"
    return _envelope(action, f"<serialConsoleAccessEnabled>{str(enabled).lower()}</serialConsoleAccessEnabled>")


# ── Default credit specification (account setting, per T-family) ────────────
def _get_default_credit_specification(store, params):
    family = str(_req(params, "InstanceFamily"))
    spec = _model(store)["account"]["default_credit_specification"].get(family, "standard")
    return _envelope("GetDefaultCreditSpecification",
                      f"<instanceFamilyCreditSpecification><instanceFamily>{_xml_escape(family)}</instanceFamily>"
                      f"<cpuCredits>{_xml_escape(spec)}</cpuCredits></instanceFamilyCreditSpecification>")


def _modify_default_credit_specification(store, params):
    family = str(_req(params, "InstanceFamily"))
    credits = str(_req(params, "CpuCredits"))
    _model(store)["account"]["default_credit_specification"][family] = credits
    return _envelope("ModifyDefaultCreditSpecification",
                      f"<instanceFamilyCreditSpecification><instanceFamily>{_xml_escape(family)}</instanceFamily>"
                      f"<cpuCredits>{_xml_escape(credits)}</cpuCredits></instanceFamilyCreditSpecification>")


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
    "DescribeInternetGateways": _describe_internet_gateways,
    "AttachInternetGateway": _attach_internet_gateway,
    "DetachInternetGateway": _detach_internet_gateway,
    "DeleteInternetGateway": _delete_internet_gateway,
    "CreateRoute": _create_route, "DeleteRoute": _delete_route,
    "DescribeVpcs": _describe_vpcs, "DeleteVpc": _delete_vpc,
    "ModifyVpcAttribute": _modify_vpc_attribute, "DescribeVpcAttribute": _describe_vpc_attribute,
    "DescribeSubnets": _describe_subnets, "DeleteSubnet": _delete_subnet,
    "CreateSubnetCidrReservation": _create_subnet_cidr_reservation,
    "GetSubnetCidrReservations": _get_subnet_cidr_reservations,
    "DeleteSubnetCidrReservation": _delete_subnet_cidr_reservation,
    "CreateRouteTable": _create_route_table, "DescribeRouteTables": _describe_route_tables,
    "DeleteRouteTable": _delete_route_table,
    "AssociateRouteTable": _associate_route_table, "DisassociateRouteTable": _disassociate_route_table,
    "ReplaceRouteTableAssociation": _replace_route_table_association,
    "CreateNetworkAcl": _create_network_acl, "DescribeNetworkAcls": _describe_network_acls,
    "DeleteNetworkAcl": _delete_network_acl,
    "CreateNetworkAclEntry": _create_network_acl_entry,
    "DeleteNetworkAclEntry": _delete_network_acl_entry,
    "AssociateNetworkAcl": _associate_network_acl,
    "ReplaceNetworkAclAssociation": _replace_network_acl_association,
    "CreateNatGateway": _create_nat_gateway, "DescribeNatGateways": _describe_nat_gateways,
    "DeleteNatGateway": _delete_nat_gateway,
    "CreateEgressOnlyInternetGateway": _create_egress_only_internet_gateway,
    "DescribeEgressOnlyInternetGateways": _describe_egress_only_internet_gateways,
    "DeleteEgressOnlyInternetGateway": _delete_egress_only_internet_gateway,
    "CreateDhcpOptions": _create_dhcp_options, "DescribeDhcpOptions": _describe_dhcp_options,
    "DeleteDhcpOptions": _delete_dhcp_options, "AssociateDhcpOptions": _associate_dhcp_options,
    "CreateManagedPrefixList": _create_managed_prefix_list,
    "DescribeManagedPrefixLists": _describe_managed_prefix_lists,
    "DeleteManagedPrefixList": _delete_managed_prefix_list,
    "CreateVpcPeeringConnection": _create_vpc_peering_connection,
    "DescribeVpcPeeringConnections": _describe_vpc_peering_connections,
    "AcceptVpcPeeringConnection": _accept_vpc_peering_connection,
    "DeleteVpcPeeringConnection": _delete_vpc_peering_connection,
    "CreateRouteServer": _create_route_server, "DescribeRouteServers": _describe_route_servers,
    "DeleteRouteServer": _delete_route_server,
    "AnalyzeReachability": _analyze_reachability_action,
    "CreateFlowLogs": _create_flow_logs, "DescribeFlowLogs": _describe_flow_logs, "DeleteFlowLogs": _delete_flow_logs,
    # instances
    "RunInstances": _run_instances, "DescribeInstances": _describe_instances,
    "StartInstances": lambda s, p: _instance_state_change(s, p, "start", "running"),
    "StopInstances": lambda s, p: _instance_state_change(s, p, "stop", "stopped"),
    "TerminateInstances": lambda s, p: _instance_state_change(s, p, "terminate", "terminated"),
    "RebootInstances": _reboot_instances,
    "ModifyInstanceAttribute": _modify_instance_attribute,
    "ModifySubnetAttribute": _modify_subnet_attribute,
    "CreateNetworkInsightsPath": _create_network_insights_path,
    "DescribeNetworkInsightsPaths": _describe_network_insights_paths,
    "DeleteNetworkInsightsPath": _delete_network_insights_path,
    "StartNetworkInsightsAnalysis": _start_network_insights_analysis,
    "DescribeNetworkInsightsAnalyses": _describe_network_insights_analyses,
    "DeleteNetworkInsightsAnalysis": _delete_network_insights_analysis,
    "ModifyNetworkInterfaceAttribute": _modify_network_interface_attribute,
    "MonitorInstances": lambda s, p: _monitor_instances(s, p, True),
    "UnmonitorInstances": lambda s, p: _monitor_instances(s, p, False),
    "DescribeInstanceTypes": _describe_instance_types,
    "DescribeAvailabilityZones": _describe_availability_zones,
    "DescribeInstanceStatus": _describe_instance_status,
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
    "CreateLaunchTemplateVersion": _create_launch_template_version,
    "DescribeLaunchTemplateVersions": _describe_launch_template_versions,
    "ModifyLaunchTemplate": _modify_launch_template,
    # tags
    "CreateTags": _create_tags, "DeleteTags": _delete_tags, "DescribeTags": _describe_tags,
    # EBS account defaults
    "GetEbsEncryptionByDefault": _get_ebs_encryption_by_default,
    "EnableEbsEncryptionByDefault": lambda s, p: _set_ebs_encryption_by_default(s, p, True),
    "DisableEbsEncryptionByDefault": lambda s, p: _set_ebs_encryption_by_default(s, p, False),
    "GetEbsDefaultKmsKeyId": _get_ebs_default_kms_key_id,
    "ModifyEbsDefaultKmsKeyId": _modify_ebs_default_kms_key_id,
    "ResetEbsDefaultKmsKeyId": _reset_ebs_default_kms_key_id,
    # security group VPC associations (ec2.security-groups.sharing)
    "AssociateSecurityGroupVpc": _associate_security_group_vpc,
    "DisassociateSecurityGroupVpc": _disassociate_security_group_vpc,
    "DescribeSecurityGroupVpcAssociations": _describe_security_group_vpc_associations,
    # Allowed AMIs (ec2.settings.other)
    "GetAllowedImagesSettings": _get_allowed_images_settings,
    "EnableAllowedImagesSettings": lambda s, p: _set_allowed_images_settings(s, p, True),
    "DisableAllowedImagesSettings": lambda s, p: _set_allowed_images_settings(s, p, False),
    "ReplaceImageCriteriaInAllowedImagesSettings": _replace_image_criteria_in_allowed_images_settings,
    # EC2 Serial Console (ec2.settings.other)
    "GetSerialConsoleAccessStatus": _get_serial_console_access_status,
    "EnableSerialConsoleAccess": lambda s, p: _set_serial_console_access(s, p, True),
    "DisableSerialConsoleAccess": lambda s, p: _set_serial_console_access(s, p, False),
    # Default credit specification (ec2.settings.other)
    "GetDefaultCreditSpecification": _get_default_credit_specification,
    "ModifyDefaultCreditSpecification": _modify_default_credit_specification,
}


# ── upgrade path: adopt the pre-v4 offline VPC store (server.py `vpc_state`) ─────────────
# Before v4 the offline appliance served CreateVpc / subnets / security groups / route tables /
# internet gateways from its own `vpc_state` dict (service_states["vpc"]). vpc_core is now the
# one engine; this copies every legacy object into the core model ONCE per space, keeping the
# IDs (so EC2 instances, RDS subnet groups … that reference them keep working). Idempotent at two
# levels: a per-model marker, and per-object "already present → skip". The pre-v4 store never had
# EIPs, NAT gateways, NACLs, peering or ENIs (those were always vpc_core), so there is nothing else
# to carry over. Pure dict code — runs anywhere.
def _legacy_tags(rec: dict) -> dict:
    out = {}
    for t in rec.get("tags") or []:
        if isinstance(t, dict) and (t.get("key") or t.get("Key")):
            out[str(t.get("key") or t.get("Key"))] = str(t.get("value", t.get("Value", "")))
    return out


def _legacy_perm(rule: dict) -> dict:
    proto = str(rule.get("protocol", "-1"))
    proto = {"all": "-1", "6": "tcp", "17": "udp", "1": "icmp"}.get(proto.lower(), proto.lower())
    src_sg = str(rule.get("source_sg") or "")
    cidr = str(rule.get("cidr") or "")
    # the pre-v4 handler stored a 0.0.0.0/0 default next to a source SG; a SG-referencing rule
    # never meant "everyone", so only an explicit non-default CIDR is kept alongside the SG
    cidrs = [cidr] if cidr and not (src_sg and cidr == "0.0.0.0/0") else []
    allp = proto == "-1"
    return {"protocol": proto, "from_port": None if allp else int(rule.get("from_port") or 0),
            "to_port": None if allp else int(rule.get("to_port") if rule.get("to_port") is not None else 65535),
            "cidrs": cidrs, "sgs": [src_sg] if src_sg else [], "rule_id": _rid("sgr", 8),
            "description": str(rule.get("description") or "")}


def adopt_legacy(model, legacy: dict) -> tuple[dict, dict]:
    """Merge the pre-v4 `vpc_state` dict into a vpc_core model (created if None).
    Returns (model, counts). Re-running adds nothing."""
    holder = type("S", (), {})()
    if model is not None:
        holder._vpc_model = model
    m = _model(holder)
    counts = {"vpcs": 0, "subnets": 0, "security_groups": 0, "route_tables": 0, "routes": 0, "internet_gateways": 0}
    legacy = legacy if isinstance(legacy, dict) else {}

    def live(coll):
        d = legacy.get(coll)
        return [(k, v) for k, v in (d.items() if isinstance(d, dict) else [])
                if isinstance(v, dict) and v.get("_engine") != "vpc_core"]      # skip our own mirrors

    for vid, v in live("vpcs"):
        if vid in m["vpcs"]:
            continue
        dopt = str(v.get("dhcp_options_id") or "") or _default_dhcp_options(m)
        m["dhcp_options"].setdefault(dopt, {"id": dopt, "default": True, "tags": {},
                                            "options": {"domain-name": "ec2.internal", "domain-name-servers": "AmazonProvidedDNS"}})
        m["vpcs"][vid] = {"id": vid, "cidr": str(v.get("cidr_block") or "10.0.0.0/16"), "igw": None,
                          "default_nacl": _create_default_nacl(m, vid), "tenancy": str(v.get("tenancy") or "default"),
                          "dhcp_options_id": dopt, "enable_dns_hostnames": False, "enable_dns_support": True,
                          "tags": _legacy_tags(v), "created": v.get("created", ""), "adopted_from": "vpc_state"}
        counts["vpcs"] += 1
    for rid, rt in live("route_tables"):
        if rid in m["route_tables"] or rt.get("vpc_id") not in m["vpcs"]:
            continue
        vpc = m["vpcs"][rt["vpc_id"]]
        routes = [{"dest": vpc["cidr"], "target": "local"}]
        for r in rt.get("routes") or []:
            dest, ttype, tid = str(r.get("destination") or ""), str(r.get("target_type") or ""), str(r.get("target_id") or "")
            if not dest or ttype == "local" or not tid or any(x["dest"] == dest for x in routes):
                continue
            routes.append({"dest": dest, "target": tid})
            counts["routes"] += 1
        main = bool(rt.get("is_main"))
        if main and any(x.get("main") for x in m["route_tables"].values() if x["vpc_id"] == rt["vpc_id"]):
            main = False
        m["route_tables"][rid] = {"id": rid, "vpc_id": rt["vpc_id"], "main": main, "routes": routes, "subnets": [],
                                  "tags": _legacy_tags(rt)}
        counts["route_tables"] += 1
    for vid in list(m["vpcs"]):                      # every VPC needs a main route table
        if not any(x.get("main") for x in m["route_tables"].values() if x["vpc_id"] == vid):
            rid = _rid("rtb")
            m["route_tables"][rid] = {"id": rid, "vpc_id": vid, "main": True, "subnets": [], "tags": {},
                                      "routes": [{"dest": m["vpcs"][vid]["cidr"], "target": "local"}]}
    for sid, sn in live("subnets"):
        if sid in m["subnets"] or sn.get("vpc_id") not in m["vpcs"]:
            continue
        vid = sn["vpc_id"]
        rt = sn.get("route_table_id") if sn.get("route_table_id") in m["route_tables"] else \
            next((x["id"] for x in m["route_tables"].values() if x["vpc_id"] == vid and x.get("main")), None)
        nacl = m["vpcs"][vid].get("default_nacl")
        m["subnets"][sid] = {"id": sid, "vpc_id": vid, "cidr": str(sn.get("cidr_block") or ""),
                             "az": str(sn.get("availability_zone") or _AZS[0]), "route_table": rt, "nacl": nacl,
                             "map_public_ip": bool(sn.get("map_public_ip_on_launch", False)), "tags": _legacy_tags(sn)}
        if rt and sid not in m["route_tables"][rt]["subnets"]:
            m["route_tables"][rt]["subnets"].append(sid)
        if nacl in m["nacls"] and sid not in m["nacls"][nacl]["subnets"]:
            m["nacls"][nacl]["subnets"].append(sid)
        counts["subnets"] += 1
    for gid, g in live("security_groups"):
        if gid in m["sgs"] or g.get("vpc_id") not in m["vpcs"]:
            continue
        m["sgs"][gid] = {"id": gid, "vpc_id": g["vpc_id"], "name": str(g.get("group_name") or ""),
                         "description": str(g.get("description") or ""), "is_default": bool(g.get("is_default")),
                         "tags": _legacy_tags(g),
                         "ingress": [_legacy_perm(r) for r in g.get("ingress") or [] if isinstance(r, dict)],
                         "egress": [_legacy_perm(r) for r in g.get("egress") or [] if isinstance(r, dict)]}
        counts["security_groups"] += 1
    for iid, igw in live("internet_gateways"):
        if iid in m["igws"]:
            continue
        vid = str(igw.get("attached_vpc_id") or "") or None
        if vid and vid not in m["vpcs"]:
            vid = None
        m["igws"][iid] = {"id": iid, "vpc_id": vid, "tags": _legacy_tags(igw)}
        if vid and not m["vpcs"][vid].get("igw"):
            m["vpcs"][vid]["igw"] = iid
        counts["internet_gateways"] += 1
    return m, counts


def adopt_legacy_slot(service_states: dict, legacy: dict | None = None):
    """Once per space: adopt service_states["vpc"] (the pre-v4 store) into
    service_states["ec2_vpc_core"]. Returns the (possibly new) model, or the existing one."""
    model = service_states.get("ec2_vpc_core")
    if isinstance(model, dict) and model.get("_adopted_legacy"):
        return model
    legacy = legacy if legacy is not None else service_states.get("vpc")
    has_legacy = isinstance(legacy, dict) and any(
        isinstance(legacy.get(c), dict) and any(isinstance(v, dict) and v.get("_engine") != "vpc_core"
                                                for v in legacy[c].values())
        for c in ("vpcs", "subnets", "security_groups", "route_tables", "internet_gateways"))
    if not has_legacy:
        if isinstance(model, dict):
            model["_adopted_legacy"] = _now()
        return model
    model, counts = adopt_legacy(model, legacy)
    model["_adopted_legacy"] = _now()
    model["_adopted_counts"] = counts
    service_states["ec2_vpc_core"] = model
    return model


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
