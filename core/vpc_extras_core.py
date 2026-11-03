"""EC2/VPC extras merged into vpc_core._OPS: Client VPN, Site-to-Site VPN concentrators, route-table
edge associations, VPC CIDR associations, Traffic Mirroring, Transit Gateway policy tables / multicast
domains / metering policies. Real state + validation (each module section says what is evaluated);
see core/capabilities/aws/vpc.json for the honest limits."""
from __future__ import annotations

import ipaddress
import re


def _V():
    from core import vpc_core
    return vpc_core


def _err(code, msg):
    return _V().VpcError(code, msg)


def xml(v, tag=None):
    """Tiny renderer: dict -> children, list -> <item> children, scalar -> text, bool -> true/false."""
    esc = _V()._xml_escape
    if isinstance(v, bool):
        s = "true" if v else "false"
    elif isinstance(v, dict):
        s = "".join(xml(x, k) for k, x in v.items() if x is not None)
    elif isinstance(v, list):
        s = "".join(xml(x, "item") for x in v)
    elif v is None:
        s = ""
    else:
        s = esc(str(v))
    return f"<{tag}>{s}</{tag}>" if tag else s


def tags(t):
    return {"tagSet": [{"key": k, "value": v} for k, v in (t or {}).items()]}


def ids(p, prefix):
    return [v for k, v in sorted(p.items()) if k.startswith(prefix + ".")]


def idx_list(p, prefix, sub=None):
    """Collect `Prefix.N[.Sub]` values in numeric order."""
    out = {}
    for k, v in p.items():
        mm = re.match(rf"{re.escape(prefix)}\.(\d+)" + (rf"\.{re.escape(sub)}" if sub else "") + "$", k)
        if mm:
            out[int(mm.group(1))] = v
    return [out[i] for i in sorted(out)]


def struct_list(p, prefix):
    """`Prefix.N.Field[.M]` -> [{Field: value}] per N (dotted sub-keys kept as keys)."""
    out = {}
    for k, v in p.items():
        mm = re.match(rf"{re.escape(prefix)}\.(\d+)\.(.+)$", k)
        if mm:
            out.setdefault(int(mm.group(1)), {})[mm.group(2)] = v
    return [out[i] for i in sorted(out)]


def boolp(p, k, default=False):
    v = p.get(k)
    return default if v is None else str(v).lower() == "true"


def reply(action, tag, body, store_resp=True):
    return _V()._envelope(action, xml(body, tag) if tag else xml(body))


def cidr4(s, what="CIDR"):
    try:
        return ipaddress.IPv4Network(str(s), strict=True)
    except ValueError:
        raise _err("InvalidParameterValue", f"Value ({s}) for parameter {what} is invalid.")


def bag(m, name):
    return m.setdefault(name, {})


def tag_of(p, rtype):
    return _V()._parse_tag_specifications(p).get(rtype, {})


# ── Client VPN ───────────────────────────────────────────────────────────
# Endpoint lifecycle (pending-associate -> available once a target network is associated), target
# networks (one per AZ, all in the same VPC), authorization rules and routes with AWS validation, the
# automatic VPC-CIDR route. No OpenVPN server exists, so the connections list is always empty.
def _cvpn_need(m, eid):
    e = bag(m, "cvpn_endpoints").get(eid)
    if not e:
        raise _err("InvalidClientVpnEndpointId.NotFound", f"The Client VPN endpoint ID '{eid}' does not exist")
    return e


def _cvpn_xml(e):
    st = "available" if e["targets"] else "pending-associate"
    return {"clientVpnEndpointId": e["id"], "description": e["description"], "status": {"code": st},
            "creationTime": e["created"], "dnsName": f"*.{e['id']}.prod.clientvpn.us-east-1.amazonaws.com",
            "clientCidrBlock": e["client_cidr"], "dnsServer": [x for x in e["dns"]] or None,
            "splitTunnel": e["split_tunnel"], "vpnProtocol": "openvpn", "transportProtocol": e["transport"],
            "vpnPort": e["port"], "serverCertificateArn": e["server_cert"],
            "authenticationOptions": [{"type": a["Type"],
                                       **({"mutualAuthentication": {"clientRootCertificateChain": a.get("RootCertificateChainArn", "")}} if a["Type"] == "certificate-authentication" else {}),
                                       **({"activeDirectory": {"directoryId": a.get("DirectoryId", "")}} if a["Type"] == "directory-service-authentication" else {}),
                                       **({"federatedAuthentication": {"samlProviderArn": a.get("SAMLProviderArn", "")}} if a["Type"] == "federated-authentication" else {})}
                                      for a in e["auth"]],
            "connectionLogOptions": {"enabled": e["log_enabled"], **({"cloudwatchLogGroup": e["log_group"]} if e.get("log_group") else {})},
            "securityGroupIdSet": [x for x in e["sgs"]] or None, "vpcId": e["vpc_id"] or None,
            "selfServicePortalUrl": None, "clientConnectOptions": {"enabled": False},
            "sessionTimeoutHours": e["session_hours"], **tags(e["tags"])}


def _cvpn_create(store, p):
    V = _V(); m = V._model(store)
    cidr = cidr4(p.get("ClientCidrBlock", ""), "clientCidrBlock")
    if not (12 <= cidr.prefixlen <= 22):
        raise _err("InvalidParameterValue", "The client CIDR block must have a prefix length between /12 and /22.")
    if not p.get("ServerCertificateArn"):
        raise _err("MissingParameter", "The request must contain the parameter ServerCertificateArn")
    auth = struct_list(p, "Authentication")
    if not auth:
        raise _err("MissingParameter", "The request must contain the parameter Authentication")
    for a in auth:
        if a.get("Type") not in ("certificate-authentication", "directory-service-authentication", "federated-authentication"):
            raise _err("InvalidParameterValue", f"Value ({a.get('Type')}) for parameter authentication type is invalid.")
        if a["Type"] == "certificate-authentication" and not a.get("MutualAuthentication.ClientRootCertificateChainArn"):
            raise _err("MissingParameter", "Certificate authentication requires MutualAuthentication.ClientRootCertificateChainArn")
        if a["Type"] == "directory-service-authentication" and not a.get("ActiveDirectory.DirectoryId"):
            raise _err("MissingParameter", "Directory authentication requires ActiveDirectory.DirectoryId")
        if a["Type"] == "federated-authentication" and not a.get("FederatedAuthentication.SAMLProviderArn"):
            raise _err("MissingParameter", "Federated authentication requires FederatedAuthentication.SAMLProviderArn")
    proto = str(p.get("TransportProtocol", "udp"))
    if proto not in ("tcp", "udp"):
        raise _err("InvalidParameterValue", "TransportProtocol must be tcp or udp.")
    vpc_id = str(p.get("VpcId", ""))
    if vpc_id and vpc_id not in m["vpcs"]:
        raise _err("InvalidVpcID.NotFound", f"The vpc ID '{vpc_id}' does not exist")
    eid = V._rid("cvpn-endpoint", 17)
    auths = [{"Type": a["Type"], "RootCertificateChainArn": a.get("MutualAuthentication.ClientRootCertificateChainArn", ""),
              "DirectoryId": a.get("ActiveDirectory.DirectoryId", ""), "SAMLProviderArn": a.get("FederatedAuthentication.SAMLProviderArn", "")} for a in auth]
    bag(m, "cvpn_endpoints")[eid] = {
        "id": eid, "description": str(p.get("Description", "")), "client_cidr": str(cidr), "server_cert": str(p["ServerCertificateArn"]),
        "auth": auths, "log_enabled": boolp(p, "ConnectionLogOptions.Enabled"), "log_group": str(p.get("ConnectionLogOptions.CloudwatchLogGroup", "")),
        "dns": idx_list(p, "DnsServers"), "split_tunnel": boolp(p, "SplitTunnel"), "transport": proto, "port": int(p.get("VpnPort", 443)),
        "sgs": idx_list(p, "SecurityGroupId"), "vpc_id": vpc_id, "session_hours": int(p.get("SessionTimeoutHours", 24)),
        "created": V._now(), "targets": {}, "auth_rules": [], "routes": [], "tags": tag_of(p, "client-vpn-endpoint")}
    return V._envelope("CreateClientVpnEndpoint", xml({"clientVpnEndpointId": eid, "status": {"code": "pending-associate"}, "dnsName": f"*.{eid}.prod.clientvpn.us-east-1.amazonaws.com"}))


def _cvpn_describe(store, p):
    m = _V()._model(store)
    eps = [_cvpn_need(m, i) for i in ids(p, "ClientVpnEndpointId")] or list(bag(m, "cvpn_endpoints").values())
    return _V()._envelope("DescribeClientVpnEndpoints", xml([_cvpn_xml(e) for e in eps], "clientVpnEndpoint"))


def _cvpn_modify(store, p):
    m = _V()._model(store); e = _cvpn_need(m, str(p.get("ClientVpnEndpointId", "")))
    if "Description" in p: e["description"] = str(p["Description"])
    if "ServerCertificateArn" in p: e["server_cert"] = str(p["ServerCertificateArn"])
    if "SplitTunnel" in p: e["split_tunnel"] = boolp(p, "SplitTunnel")
    if "ConnectionLogOptions.Enabled" in p: e["log_enabled"] = boolp(p, "ConnectionLogOptions.Enabled")
    if "ConnectionLogOptions.CloudwatchLogGroup" in p: e["log_group"] = str(p["ConnectionLogOptions.CloudwatchLogGroup"])
    if "DnsServers.Enabled" in p or idx_list(p, "DnsServers.CustomDnsServers"): e["dns"] = idx_list(p, "DnsServers.CustomDnsServers")
    if "SessionTimeoutHours" in p: e["session_hours"] = int(p["SessionTimeoutHours"])
    sgs = idx_list(p, "SecurityGroupId")
    if sgs:
        e["sgs"] = sgs
        if "VpcId" in p: e["vpc_id"] = str(p["VpcId"])
    return _V()._envelope("ModifyClientVpnEndpoint", "<return>true</return>")


def _cvpn_delete(store, p):
    m = _V()._model(store); e = _cvpn_need(m, str(p.get("ClientVpnEndpointId", "")))
    if e["targets"]:
        raise _err("InvalidClientVpnActiveAssociationExists", f"{e['id']} still has target network associations; disassociate them first.")
    bag(m, "cvpn_endpoints").pop(e["id"])
    return _V()._envelope("DeleteClientVpnEndpoint", xml({"status": {"code": "deleting"}}))


def _cvpn_associate(store, p):
    V = _V(); m = V._model(store); e = _cvpn_need(m, str(p.get("ClientVpnEndpointId", "")))
    sid = str(p.get("SubnetId", ""))
    sub = m["subnets"].get(sid)
    if not sub:
        raise _err("InvalidSubnetID.NotFound", f"The subnet ID '{sid}' does not exist")
    if e["targets"] and next(iter(e["targets"].values()))["vpc"] != sub["vpc_id"]:
        raise _err("InvalidParameterValue", "All target networks of a Client VPN endpoint must be in the same VPC.")
    if e["vpc_id"] and e["vpc_id"] != sub["vpc_id"]:
        raise _err("InvalidParameterValue", f"The endpoint is configured for {e['vpc_id']}.")
    if any(t["az"] == sub["az"] for t in e["targets"].values()):
        raise _err("InvalidClientVpnDuplicateAssociationException", f"A subnet in {sub['az']} is already associated with {e['id']}.")
    vcidr = ipaddress.ip_network(m["vpcs"][sub["vpc_id"]]["cidr"])
    if ipaddress.ip_network(e["client_cidr"]).overlaps(vcidr):
        raise _err("InvalidParameterValue", f"The client CIDR {e['client_cidr']} overlaps the VPC CIDR {vcidr}.")
    aid = V._rid("cvpn-assoc", 17)
    first = not e["targets"]
    e["targets"][aid] = {"id": aid, "subnet": sid, "vpc": sub["vpc_id"], "az": sub["az"]}
    e["vpc_id"] = e["vpc_id"] or sub["vpc_id"]
    if first:
        e["routes"].append({"dest": str(vcidr), "subnet": sid, "origin": "associate", "description": "Default Route", "status": "active"})
    return V._envelope("AssociateClientVpnTargetNetwork", xml({"associationId": aid, "status": {"code": "associated"}}))


def _cvpn_disassociate(store, p):
    V = _V(); m = V._model(store); e = _cvpn_need(m, str(p.get("ClientVpnEndpointId", "")))
    aid = str(p.get("AssociationId", ""))
    t = e["targets"].get(aid)
    if not t:
        raise _err("InvalidAssociationID.NotFound", f"The association ID '{aid}' does not exist")
    e["targets"].pop(aid)
    e["routes"] = [r for r in e["routes"] if r["subnet"] != t["subnet"]]
    if not e["targets"]:
        e["routes"] = []
    return V._envelope("DisassociateClientVpnTargetNetwork", xml({"associationId": aid, "status": {"code": "disassociating"}}))


def _cvpn_targets(store, p):
    m = _V()._model(store); e = _cvpn_need(m, str(p.get("ClientVpnEndpointId", "")))
    rows = [{"clientVpnEndpointId": e["id"], "associationId": t["id"], "vpcId": t["vpc"], "targetNetworkId": t["subnet"],
             "status": {"code": "associated"}, "securityGroups": [x for x in e["sgs"]] or None} for t in e["targets"].values()]
    return _V()._envelope("DescribeClientVpnTargetNetworks", xml(rows, "clientVpnTargetNetworks"))


def _cvpn_authorize(store, p):
    m = _V()._model(store); e = _cvpn_need(m, str(p.get("ClientVpnEndpointId", "")))
    cidr = str(cidr4(p.get("TargetNetworkCidr", ""), "targetNetworkCidr"))
    allg, grp = boolp(p, "AuthorizeAllGroups"), str(p.get("AccessGroupId", ""))
    if allg == bool(grp):
        raise _err("InvalidParameterCombination", "Specify exactly one of AuthorizeAllGroups or AccessGroupId.")
    if any(r["cidr"] == cidr and r["all"] == allg and r["group"] == grp for r in e["auth_rules"]):
        raise _err("InvalidClientVpnDuplicateAuthorizationRule", f"An authorization rule for {cidr} already exists.")
    e["auth_rules"].append({"cidr": cidr, "all": allg, "group": grp, "description": str(p.get("Description", ""))})
    return _V()._envelope("AuthorizeClientVpnIngress", xml({"status": {"code": "active"}}))


def _cvpn_revoke(store, p):
    m = _V()._model(store); e = _cvpn_need(m, str(p.get("ClientVpnEndpointId", "")))
    cidr = str(p.get("TargetNetworkCidr", "")); allg, grp = boolp(p, "RevokeAllGroups"), str(p.get("AccessGroupId", ""))
    n = len(e["auth_rules"])
    e["auth_rules"] = [r for r in e["auth_rules"] if not (r["cidr"] == cidr and r["all"] == allg and r["group"] == grp)]
    if len(e["auth_rules"]) == n:
        raise _err("InvalidClientVpnAuthorizationRuleNotFound", f"No authorization rule for {cidr} exists.")
    return _V()._envelope("RevokeClientVpnIngress", xml({"status": {"code": "revoking"}}))


def _cvpn_rules(store, p):
    m = _V()._model(store); e = _cvpn_need(m, str(p.get("ClientVpnEndpointId", "")))
    rows = [{"clientVpnEndpointId": e["id"], "description": r["description"], "groupId": r["group"] or None, "accessAll": r["all"],
             "destinationCidr": r["cidr"], "status": {"code": "active"}} for r in e["auth_rules"]]
    return _V()._envelope("DescribeClientVpnAuthorizationRules", xml(rows, "authorizationRule"))


def _cvpn_create_route(store, p):
    m = _V()._model(store); e = _cvpn_need(m, str(p.get("ClientVpnEndpointId", "")))
    dest = str(cidr4(p.get("DestinationCidrBlock", ""), "destinationCidrBlock")); sid = str(p.get("TargetVpcSubnetId", ""))
    if not any(t["subnet"] == sid for t in e["targets"].values()):
        raise _err("InvalidClientVpnAssociationId.NotFound", f"{sid} is not an associated target network of {e['id']}.")
    if any(r["dest"] == dest and r["subnet"] == sid for r in e["routes"]):
        raise _err("InvalidClientVpnDuplicateRoute", f"A route to {dest} via {sid} already exists.")
    e["routes"].append({"dest": dest, "subnet": sid, "origin": "add-route", "description": str(p.get("Description", "")), "status": "active"})
    return _V()._envelope("CreateClientVpnRoute", xml({"status": {"code": "creating"}}))


def _cvpn_delete_route(store, p):
    m = _V()._model(store); e = _cvpn_need(m, str(p.get("ClientVpnEndpointId", "")))
    dest, sid = str(p.get("DestinationCidrBlock", "")), str(p.get("TargetVpcSubnetId", ""))
    keep = [r for r in e["routes"] if not (r["dest"] == dest and (not sid or r["subnet"] == sid))]
    if len(keep) == len(e["routes"]):
        raise _err("InvalidClientVpnRouteNotFound", f"No route to {dest} exists.")
    e["routes"] = keep
    return _V()._envelope("DeleteClientVpnRoute", xml({"status": {"code": "deleting"}}))


def _cvpn_routes(store, p):
    m = _V()._model(store); e = _cvpn_need(m, str(p.get("ClientVpnEndpointId", "")))
    rows = [{"clientVpnEndpointId": e["id"], "destinationCidr": r["dest"], "targetSubnet": r["subnet"], "type": "Nat",
             "origin": r["origin"], "status": {"code": r["status"]}, "description": r["description"]} for r in e["routes"]]
    return _V()._envelope("DescribeClientVpnRoutes", xml(rows, "routes"))


def _cvpn_connections(store, p):
    m = _V()._model(store); e = _cvpn_need(m, str(p.get("ClientVpnEndpointId", "")))
    return _V()._envelope("DescribeClientVpnConnections", xml([], "connections"))


def _cvpn_terminate(store, p):
    m = _V()._model(store); _cvpn_need(m, str(p.get("ClientVpnEndpointId", "")))
    return _V()._envelope("TerminateClientVpnConnections", xml({"clientVpnEndpointId": p.get("ClientVpnEndpointId"), "connectionStatuses": []}))


CVPN_OPS = {
    "CreateClientVpnEndpoint": _cvpn_create, "DescribeClientVpnEndpoints": _cvpn_describe, "ModifyClientVpnEndpoint": _cvpn_modify,
    "DeleteClientVpnEndpoint": _cvpn_delete, "AssociateClientVpnTargetNetwork": _cvpn_associate,
    "DisassociateClientVpnTargetNetwork": _cvpn_disassociate, "DescribeClientVpnTargetNetworks": _cvpn_targets,
    "AuthorizeClientVpnIngress": _cvpn_authorize, "RevokeClientVpnIngress": _cvpn_revoke,
    "DescribeClientVpnAuthorizationRules": _cvpn_rules, "CreateClientVpnRoute": _cvpn_create_route,
    "DeleteClientVpnRoute": _cvpn_delete_route, "DescribeClientVpnRoutes": _cvpn_routes,
    "DescribeClientVpnConnections": _cvpn_connections, "TerminateClientVpnConnections": _cvpn_terminate,
}


# ── Site-to-Site VPN concentrators (attach a TGW; VPN connections may terminate on one) ──
def _vc_xml(c):
    return {"vpnConcentratorId": c["id"], "state": c["state"], "transitGatewayId": c["tgw"], "type": "ipsec.1", **tags(c["tags"])}


def _vc_create(store, p):
    V = _V(); m = V._model(store)
    tgw = str(p.get("TransitGatewayId", ""))
    if tgw not in m.setdefault("tgws", {}):
        raise _err("InvalidTransitGatewayID.NotFound", f"Transit gateway {tgw} does not exist.")
    if str(p.get("Type", "ipsec.1")) != "ipsec.1":
        raise _err("InvalidParameterValue", "Value for parameter type is invalid. Only ipsec.1 is supported.")
    cid = V._rid("vcn", 17)
    bag(m, "vpn_concentrators")[cid] = {"id": cid, "tgw": tgw, "state": "available", "tags": tag_of(p, "vpn-concentrator")}
    return V._envelope("CreateVpnConcentrator", xml(_vc_xml(m["vpn_concentrators"][cid]), "vpnConcentrator"))


def _vc_describe(store, p):
    m = _V()._model(store); vc = bag(m, "vpn_concentrators")
    want = ids(p, "VpnConcentratorId")
    for i in want:
        if i not in vc:
            raise _err("InvalidVpnConcentratorID.NotFound", f"The VPN concentrator ID '{i}' does not exist")
    return _V()._envelope("DescribeVpnConcentrators", xml([_vc_xml(vc[i]) for i in (want or vc)], "vpnConcentratorSet"))


def _vc_delete(store, p):
    m = _V()._model(store); vc = bag(m, "vpn_concentrators"); i = str(p.get("VpnConcentratorId", ""))
    if i not in vc:
        raise _err("InvalidVpnConcentratorID.NotFound", f"The VPN concentrator ID '{i}' does not exist")
    vc.pop(i)
    return _V()._envelope("DeleteVpnConcentrator", "<return>true</return>")


# ── VPC CIDR associations (secondary IPv4 / Amazon-provided IPv6) ─────────────────────
# Validated like EC2: /16-/28, RFC1918 / 100.64/10 only (primary-range class rules), no overlap with any
# CIDR of the VPC or a peered/routed VPC range already used by this VPC, max 5 secondary, disassociation
# blocked while a subnet lives in the block; local routes follow in every route table of the VPC, and
# netsim treats the secondary block as part of the VPC network.
def cidr_assoc_xml(v):
    items = [{"associationId": "vpc-cidr-assoc-primary-" + v["id"][4:], "cidrBlock": v["cidr"], "cidrBlockState": {"state": "associated"}}]
    items += [{"associationId": a["id"], "cidrBlock": a["cidr"], "cidrBlockState": {"state": "associated"}} for a in v.get("cidr_assocs", [])]
    out = f"<cidrBlockAssociationSet>{xml(items)}</cidrBlockAssociationSet>"
    v6 = v.get("ipv6_assocs", [])
    if v6:
        out += "<ipv6CidrBlockAssociationSet>" + xml([{"associationId": a["id"], "ipv6CidrBlock": a["cidr"], "ipv6CidrBlockState": {"state": "associated"},
                                                         "networkBorderGroup": "us-east-1", "ipv6Pool": "Amazon"} for a in v6]) + "</ipv6CidrBlockAssociationSet>"
    return out


def _need_vpc(m, vid):
    v = m["vpcs"].get(vid)
    if not v:
        raise _err("InvalidVpcID.NotFound", f"The vpc ID '{vid}' does not exist")
    return v


def _vpc_assoc(store, p):
    V = _V(); m = V._model(store); v = _need_vpc(m, str(p.get("VpcId", "")))
    if boolp(p, "AmazonProvidedIpv6CidrBlock") or p.get("Ipv6CidrBlock"):
        if v.get("ipv6_assocs"):
            raise _err("CidrConflict", "The VPC already has an IPv6 CIDR block.")
        aid = V._rid("vpc-cidr-assoc", 17)
        n = abs(hash(v["id"])) % 0xFF
        v6 = str(p.get("Ipv6CidrBlock") or f"2600:1f18:{n:02x}ab:cd00::/56")
        v.setdefault("ipv6_assocs", []).append({"id": aid, "cidr": v6})
        return V._envelope("AssociateVpcCidrBlock", xml({"vpcId": v["id"], "ipv6CidrBlockAssociation": {"associationId": aid, "ipv6CidrBlock": v6, "ipv6CidrBlockState": {"state": "associated"}}}))
    net = cidr4(p.get("CidrBlock", ""), "cidrBlock")
    if not (16 <= net.prefixlen <= 28):
        raise _err("InvalidVpc.Range", f"The CIDR '{net}' is invalid: block size must be between /16 and /28.")
    if not any(net.subnet_of(r) for r in (ipaddress.ip_network("10.0.0.0/8"), ipaddress.ip_network("172.16.0.0/12"),
                                          ipaddress.ip_network("192.168.0.0/16"), ipaddress.ip_network("100.64.0.0/10"))):
        raise _err("InvalidVpc.Range", f"The CIDR '{net}' is not in a permitted private range (10/8, 172.16/12, 192.168/16, 100.64/10).")
    existing = [ipaddress.ip_network(v["cidr"])] + [ipaddress.ip_network(a["cidr"]) for a in v.get("cidr_assocs", [])]
    if any(net.overlaps(x) for x in existing):
        raise _err("CidrConflict", f"The CIDR '{net}' conflicts with another CIDR of {v['id']}.")
    if len(v.get("cidr_assocs", [])) >= 5:
        raise _err("CidrLimitExceeded", "A VPC can have at most 5 secondary IPv4 CIDR blocks.")
    for pc in m.get("peering_connections", {}).values():
        if v["id"] in (pc["requester_vpc_id"], pc["accepter_vpc_id"]) and pc.get("status") in ("active", "pending-acceptance"):
            other = m["vpcs"].get(pc["accepter_vpc_id"] if pc["requester_vpc_id"] == v["id"] else pc["requester_vpc_id"])
            if other and net.overlaps(ipaddress.ip_network(other["cidr"])):
                raise _err("CidrConflict", f"The CIDR '{net}' overlaps peer VPC {other['id']} ({other['cidr']}).")
    aid = V._rid("vpc-cidr-assoc", 17)
    v.setdefault("cidr_assocs", []).append({"id": aid, "cidr": str(net)})
    v["secondary_cidrs"] = [a["cidr"] for a in v["cidr_assocs"]]
    for rt in m["route_tables"].values():
        if rt["vpc_id"] == v["id"]:
            rt["routes"].append({"dest": str(net), "target": "local"})
    return V._envelope("AssociateVpcCidrBlock", xml({"vpcId": v["id"], "cidrBlockAssociation": {"associationId": aid, "cidrBlock": str(net), "cidrBlockState": {"state": "associated"}}}))


def _vpc_disassoc(store, p):
    V = _V(); m = V._model(store); aid = str(p.get("AssociationId", ""))
    for v in m["vpcs"].values():
        a = next((x for x in v.get("cidr_assocs", []) if x["id"] == aid), None)
        if a:
            net = ipaddress.ip_network(a["cidr"])
            if any(sn["vpc_id"] == v["id"] and ipaddress.ip_network(sn["cidr"]).subnet_of(net) for sn in m["subnets"].values()):
                raise _err("OperationNotPermitted", f"The CIDR {a['cidr']} has subnets; delete them before disassociating.")
            v["cidr_assocs"].remove(a)
            v["secondary_cidrs"] = [x["cidr"] for x in v["cidr_assocs"]]
            for rt in m["route_tables"].values():
                if rt["vpc_id"] == v["id"]:
                    rt["routes"] = [r for r in rt["routes"] if not (r["dest"] == a["cidr"] and r["target"] == "local")]
            return V._envelope("DisassociateVpcCidrBlock", xml({"vpcId": v["id"], "cidrBlockAssociation": {"associationId": aid, "cidrBlock": a["cidr"], "cidrBlockState": {"state": "disassociating"}}}))
        a6 = next((x for x in v.get("ipv6_assocs", []) if x["id"] == aid), None)
        if a6:
            v["ipv6_assocs"].remove(a6)
            return V._envelope("DisassociateVpcCidrBlock", xml({"vpcId": v["id"], "ipv6CidrBlockAssociation": {"associationId": aid, "ipv6CidrBlock": a6["cidr"], "ipv6CidrBlockState": {"state": "disassociating"}}}))
    if aid.startswith("vpc-cidr-assoc-primary-"):
        raise _err("OperationNotPermitted", "The primary CIDR block cannot be disassociated.")
    raise _err("InvalidVpcCidrBlockAssociationID.NotFound", f"The association ID '{aid}' does not exist")


# ── route-table edge associations (internet / virtual private gateway) ────────────────────
def edge_assoc_xml(rt):
    return "".join(f"<item><routeTableAssociationId>{a['id']}</routeTableAssociationId><routeTableId>{rt['id']}</routeTableId>"
                   f"<gatewayId>{a['gateway']}</gatewayId><main>false</main><associationState><state>associated</state></associationState></item>"
                   for a in rt.get("edge_assocs", []))


def associate_edge(m, rt, gw):
    V = _V()
    if gw.startswith("igw-"):
        g = m["igws"].get(gw)
        ok = bool(g) and (g.get("vpc_id") == rt["vpc_id"] or m["vpcs"].get(rt["vpc_id"], {}).get("igw") == gw)
        if not g:
            raise _err("InvalidInternetGatewayID.NotFound", f"The internetGateway ID '{gw}' does not exist")
    elif gw.startswith("vgw-"):
        g = m.get("vgws", {}).get(gw)
        if not g:
            raise _err("InvalidVpnGatewayID.NotFound", f"The virtual private gateway ID '{gw}' does not exist")
        ok = rt["vpc_id"] in g["vpcs"]
    else:
        raise _err("InvalidParameterValue", f"Value ({gw}) for parameter gatewayId is invalid; only igw- and vgw- can be edge-associated.")
    if not ok:
        raise _err("InvalidParameterValue", f"{gw} is not attached to {rt['vpc_id']}.")
    for r in m["route_tables"].values():
        if any(a["gateway"] == gw for a in r.get("edge_assocs", [])):
            raise _err("Resource.AlreadyAssociated", f"{gw} is already associated with route table {r['id']}.")
    aid = V._rid("rtbassoc", 17)
    rt.setdefault("edge_assocs", []).append({"id": aid, "gateway": gw})
    return V._envelope("AssociateRouteTable", xml({"associationId": aid, "associationState": {"state": "associated"}}))


def disassociate_edge(m, aid):
    for rt in m["route_tables"].values():
        a = next((x for x in rt.get("edge_assocs", []) if x["id"] == aid), None)
        if a:
            rt["edge_assocs"].remove(a)
            return _V()._envelope("DisassociateRouteTable", "<return>true</return>")
    return None


OPS = dict(CVPN_OPS)
OPS.update({"AssociateVpcCidrBlock": _vpc_assoc, "DisassociateVpcCidrBlock": _vpc_disassoc})
OPS.update({"CreateVpnConcentrator": _vc_create, "DescribeVpnConcentrators": _vc_describe, "DeleteVpnConcentrator": _vc_delete})
