"""Site-to-Site VPN + route propagation for the EC2/VPC core (merged into vpc_core._OPS).

Real state, no fake greens: customer gateways, virtual private gateways (attach/detach to one
VPC), VPN connections (static routes / BGP flag, two tunnels with generated outside IPs + pre-shared
keys + tunnel options, ModifyVpnTunnelOptions), and VGW route propagation: enabling propagation on a
route table copies the VPN connections' static routes into the table as `propagated` routes (shown in
the Routes tab, followed on later VPN-route/attach/detach changes and honoured by core/netsim: traffic
to a propagated prefix leaves the VPC through the VGW to the VPN connection).

Honest limits: there is no IKE/IPsec peer, so tunnel telemetry reports DOWN ("no customer gateway
device negotiating"); BGP-learned prefixes need a peer, so a BGP connection propagates nothing.
"""
from __future__ import annotations

import ipaddress
import random
import re
import secrets

_ASN_RE = re.compile(r"^\d+$")


def _V():
    from core import vpc_core
    return vpc_core


def _bag(m):
    return (m.setdefault("customer_gateways", {}), m.setdefault("vgws", {}), m.setdefault("vpn_connections", {}))


def _x(tag, v):
    return f"<{tag}>{_V()._xml_escape(str(v))}</{tag}>"


def _ids(params, prefix):
    return [v for k, v in params.items() if k.startswith(prefix + ".")]


def _err(code, msg):
    return _V().VpcError(code, msg)


# ── customer gateways ────────────────────────────────────────────────────
def _cgw_xml(c):
    return ("<item>" + _x("customerGatewayId", c["id"]) + _x("state", c["state"]) + _x("type", "ipsec.1")
            + _x("ipAddress", c["ip"]) + _x("bgpAsn", c["asn"]) + (_x("deviceName", c["device"]) if c.get("device") else "")
            + _V()._tags_xml(c.get("tags", {})) + "</item>")


def _create_cgw(store, p):
    V = _V(); m = V._model(store); cgws, _, _ = _bag(m)
    ip = str(p.get("IpAddress") or p.get("PublicIp") or "")
    try:
        ipaddress.IPv4Address(ip)
    except ValueError:
        raise _err("InvalidParameterValue", f"Value ({ip}) for parameter ipAddress is invalid.")
    if str(p.get("Type", "ipsec.1")) != "ipsec.1":
        raise _err("InvalidParameterValue", "Value for parameter type is invalid. Only ipsec.1 is supported.")
    asn = str(p.get("BgpAsn") or p.get("BgpAsnExtended") or "65000")
    if not _ASN_RE.match(asn) or not (1 <= int(asn) <= 4294967295):
        raise _err("InvalidParameterValue", f"Value ({asn}) for parameter bgpAsn is invalid.")
    cid = V._rid("cgw", 17)
    cgws[cid] = {"id": cid, "ip": ip, "asn": asn, "device": str(p.get("DeviceName", "")), "state": "available",
                 "tags": V._parse_tag_specifications(p).get("customer-gateway", {})}
    return V._envelope("CreateCustomerGateway", "<customerGateway>" + _cgw_xml(cgws[cid])[6:-7] + "</customerGateway>")


def _describe_cgws(store, p):
    V = _V(); cgws = _bag(V._model(store))[0]
    ids = _ids(p, "CustomerGatewayId")
    for i in ids:
        if i not in cgws:
            raise _err("InvalidCustomerGatewayID.NotFound", f"The customer gateway ID '{i}' does not exist")
    rows = [cgws[i] for i in ids] if ids else list(cgws.values())
    return V._envelope("DescribeCustomerGateways", "<customerGatewaySet>" + "".join(_cgw_xml(c) for c in rows) + "</customerGatewaySet>")


def _delete_cgw(store, p):
    V = _V(); m = V._model(store); cgws, _, vpns = _bag(m)
    cid = str(p.get("CustomerGatewayId", ""))
    if cid not in cgws:
        raise _err("InvalidCustomerGatewayID.NotFound", f"The customer gateway ID '{cid}' does not exist")
    if any(c["cgw"] == cid and c["state"] != "deleted" for c in vpns.values()):
        raise _err("IncorrectState", f"The customer gateway {cid} is in use by a VPN connection.")
    cgws.pop(cid)
    return V._envelope("DeleteCustomerGateway", "<return>true</return>")


# ── virtual private gateways ─────────────────────────────────────────────
def _vgw_xml(g):
    att = "".join("<item>" + _x("vpcId", v) + _x("state", "attached") + "</item>" for v in g["vpcs"])
    return ("<item>" + _x("vpnGatewayId", g["id"]) + _x("state", g["state"]) + _x("type", "ipsec.1")
            + (_x("availabilityZone", g["az"]) if g.get("az") else "") + f"<attachments>{att}</attachments>"
            + _x("amazonSideAsn", g["asn"]) + _V()._tags_xml(g.get("tags", {})) + "</item>")


def _need_vgw(m, gid):
    g = _bag(m)[1].get(gid)
    if not g:
        raise _err("InvalidVpnGatewayID.NotFound", f"The virtual private gateway ID '{gid}' does not exist")
    return g


def _create_vgw(store, p):
    V = _V(); m = V._model(store); _, vgws, _ = _bag(m)
    if str(p.get("Type", "ipsec.1")) != "ipsec.1":
        raise _err("InvalidParameterValue", "Value for parameter type is invalid. Only ipsec.1 is supported.")
    asn = str(p.get("AmazonSideAsn") or "64512")
    ok = _ASN_RE.match(asn) and (64512 <= int(asn) <= 65534 or 4200000000 <= int(asn) <= 4294967294)
    if not ok:
        raise _err("InvalidParameterValue", f"Value ({asn}) for parameter amazonSideAsn is invalid. Must be 64512-65534 or 4200000000-4294967294.")
    gid = V._rid("vgw", 17)
    vgws[gid] = {"id": gid, "asn": asn, "az": str(p.get("AvailabilityZone", "")), "state": "available", "vpcs": [],
                 "tags": V._parse_tag_specifications(p).get("vpn-gateway", {})}
    return V._envelope("CreateVpnGateway", "<vpnGateway>" + _vgw_xml(vgws[gid])[6:-7] + "</vpnGateway>")


def _describe_vgws(store, p):
    V = _V(); vgws = _bag(V._model(store))[1]
    ids = _ids(p, "VpnGatewayId")
    for i in ids:
        if i not in vgws:
            raise _err("InvalidVpnGatewayID.NotFound", f"The virtual private gateway ID '{i}' does not exist")
    rows = [vgws[i] for i in ids] if ids else [g for g in vgws.values() if g["state"] != "deleted"]
    return V._envelope("DescribeVpnGateways", "<vpnGatewaySet>" + "".join(_vgw_xml(g) for g in rows) + "</vpnGatewaySet>")


def _attach_vgw(store, p):
    V = _V(); m = V._model(store); g = _need_vgw(m, str(p.get("VpnGatewayId", "")))
    vpc = str(p.get("VpcId", ""))
    if vpc not in m["vpcs"]:
        raise _err("InvalidVpcID.NotFound", f"The vpc ID '{vpc}' does not exist")
    if g["vpcs"]:
        raise _err("VpnGatewayAttachmentLimitExceeded", f"{g['id']} is already attached to a VPC.")
    if any(vpc in x["vpcs"] for x in _bag(m)[1].values()):
        raise _err("InvalidParameterValue", f"VPC {vpc} already has a virtual private gateway attached.")
    g["vpcs"].append(vpc)
    resync_propagation(m)
    return V._envelope("AttachVpnGateway", "<attachment>" + _x("vpcId", vpc) + _x("state", "attached") + "</attachment>")


def _detach_vgw(store, p):
    V = _V(); m = V._model(store); g = _need_vgw(m, str(p.get("VpnGatewayId", "")))
    vpc = str(p.get("VpcId", ""))
    if vpc not in g["vpcs"]:
        raise _err("InvalidVpnGatewayAttachment.NotFound", f"The attachment of {g['id']} to {vpc} does not exist")
    g["vpcs"].remove(vpc)
    for rt in m["route_tables"].values():
        if rt["vpc_id"] == vpc and g["id"] in rt.get("propagating_vgws", []):
            rt["propagating_vgws"].remove(g["id"])
    resync_propagation(m)
    return V._envelope("DetachVpnGateway", "<return>true</return>")


def _delete_vgw(store, p):
    V = _V(); m = V._model(store); g = _need_vgw(m, str(p.get("VpnGatewayId", "")))
    if g["vpcs"]:
        raise _err("IncorrectState", f"{g['id']} is attached to a VPC; detach it first.")
    if any(c["vgw"] == g["id"] and c["state"] != "deleted" for c in _bag(m)[2].values()):
        raise _err("IncorrectState", f"{g['id']} is in use by a VPN connection.")
    _bag(m)[1].pop(g["id"])
    return V._envelope("DeleteVpnGateway", "<return>true</return>")


# ── VPN connections ──────────────────────────────────────────────────────
_TUNNEL_DEFAULTS = {"phase1_lifetime": 28800, "phase2_lifetime": 3600, "rekey_margin": 540, "rekey_fuzz": 100,
                    "replay_window": 1024, "dpd_timeout": 30, "dpd_action": "clear", "startup_action": "add",
                    "ike": ["ikev1", "ikev2"]}
_PSK_RE = re.compile(r"^[A-Za-z0-9._]{8,64}$")


def _inside_cidr(i):
    return f"169.254.{10 + 4 * i}.0/30"


def _tunnel_opts_from(p, base=None):
    t = dict(base or {})
    for k, key in (("PreSharedKey", "psk"), ("Phase1LifetimeSeconds", "phase1_lifetime"), ("Phase2LifetimeSeconds", "phase2_lifetime"),
                   ("RekeyMarginTimeSeconds", "rekey_margin"), ("RekeyFuzzPercentage", "rekey_fuzz"),
                   ("ReplayWindowSize", "replay_window"), ("DPDTimeoutSeconds", "dpd_timeout"),
                   ("DPDTimeoutAction", "dpd_action"), ("StartupAction", "startup_action"), ("TunnelInsideCidr", "inside_cidr")):
        if k in p:
            t[key] = p[k]
    ver = sorted(v for kk, v in p.items() if kk.startswith("IKEVersions.") and kk.endswith(".Value"))
    if ver:
        t["ike"] = [v.lower() for v in ver]
    if "psk" in t and not _PSK_RE.match(str(t["psk"])) or str(t.get("psk", "x")).startswith("0"):
        raise _err("InvalidParameterValue", "PreSharedKey must be 8-64 characters of alphanumerics, '.' and '_' and not start with zero.")
    for key, lo, hi in (("phase1_lifetime", 900, 28800), ("phase2_lifetime", 900, 3600), ("dpd_timeout", 30, 2**31)):
        if key in t:
            try:
                ok = lo <= int(t[key]) <= hi
            except (TypeError, ValueError):
                ok = False
            if not ok:
                raise _err("InvalidParameterValue", f"Value ({t[key]}) for tunnel option {key} is out of range [{lo}, {hi}].")
            t[key] = int(t[key])
    if t.get("dpd_action", "clear") not in ("clear", "none", "restart") or t.get("startup_action", "add") not in ("add", "start"):
        raise _err("InvalidParameterValue", "Invalid DPDTimeoutAction or StartupAction.")
    return t


def _vpn_xml(c, m):
    tun = "".join("<item>" + _x("outsideIpAddress", t["outside_ip"]) + _x("tunnelInsideCidr", t["inside_cidr"])
                  + _x("preSharedKey", t["psk"]) + _x("phase1LifetimeSeconds", t["phase1_lifetime"])
                  + _x("phase2LifetimeSeconds", t["phase2_lifetime"]) + _x("rekeyMarginTimeSeconds", t["rekey_margin"])
                  + _x("rekeyFuzzPercentage", t["rekey_fuzz"]) + _x("replayWindowSize", t["replay_window"])
                  + _x("dpdTimeoutSeconds", t["dpd_timeout"]) + _x("dpdTimeoutAction", t["dpd_action"])
                  + _x("startupAction", t["startup_action"])
                  + "<ikeVersionSet>" + "".join(f"<item><value>{v}</value></item>" for v in t["ike"]) + "</ikeVersionSet></item>"
                  for t in c["tunnels"])
    routes = "".join("<item>" + _x("destinationCidrBlock", r) + _x("source", "Static") + _x("state", "available") + "</item>" for r in c["routes"])
    tele = "".join("<item>" + _x("outsideIpAddress", t["outside_ip"]) + _x("status", t["status"]) + _x("lastStatusChange", c["created"])
                   + _x("statusMessage", t["status_message"]) + _x("acceptedRouteCount", 0) + "</item>" for t in c["tunnels"])
    return ("<item>" + _x("vpnConnectionId", c["id"]) + _x("state", c["state"]) + _x("customerGatewayId", c["cgw"])
            + _x("type", "ipsec.1") + _x("category", "VPN") + (_x("vpnGatewayId", c["vgw"]) if c["vgw"] else "")
            + (_x("transitGatewayId", c["tgw"]) if c.get("tgw") else "")
            + "<options>" + _x("staticRoutesOnly", "true" if c["static_only"] else "false") + _x("enableAcceleration", "false")
            + _x("localIpv4NetworkCidr", c.get("local_cidr", "0.0.0.0/0")) + _x("remoteIpv4NetworkCidr", c.get("remote_cidr", "0.0.0.0/0"))
            + _x("tunnelInsideIpVersion", "ipv4") + f"<tunnelOptions>{tun}</tunnelOptions></options>"
            + f"<routes>{routes}</routes><vgwTelemetry>{tele}</vgwTelemetry>" + _V()._tags_xml(c.get("tags", {})) + "</item>")


def _need_vpn(m, vid):
    c = _bag(m)[2].get(vid)
    if not c or c["state"] == "deleted":
        raise _err("InvalidVpnConnectionID.NotFound", f"The vpnConnection ID '{vid}' does not exist")
    return c


def _create_vpn(store, p):
    V = _V(); m = V._model(store); cgws, vgws, vpns = _bag(m)
    cgw = str(p.get("CustomerGatewayId", ""))
    if cgw not in cgws:
        raise _err("InvalidCustomerGatewayID.NotFound", f"The customer gateway ID '{cgw}' does not exist")
    vgw = str(p.get("VpnGatewayId", "")); tgw = str(p.get("TransitGatewayId", ""))
    if bool(vgw) == bool(tgw):
        raise _err("InvalidParameterCombination", "Specify exactly one of VpnGatewayId or TransitGatewayId.")
    if vgw:
        _need_vgw(m, vgw)
    elif tgw not in m.setdefault("tgws", {}):
        raise _err("InvalidTransitGatewayID.NotFound", f"Transit gateway {tgw} does not exist.")
    static_only = str(p.get("Options.StaticRoutesOnly", "false")).lower() == "true"
    tun_in = {}
    for k, v in p.items():
        mm = re.match(r"Options\.TunnelOptions\.(\d+)\.(.+)$", k)
        if mm:
            tun_in.setdefault(int(mm.group(1)), {})[mm.group(2)] = v
    rng = random.Random(secrets.token_hex(4))
    tunnels = []
    for i in range(2):
        t = _tunnel_opts_from(tun_in.get(i + 1, {}), _TUNNEL_DEFAULTS)
        t.setdefault("psk", secrets.token_urlsafe(18).replace("-", "a").replace("_", "b")[:32])
        if t["psk"][0] == "0":
            t["psk"] = "a" + t["psk"][1:]
        t.setdefault("inside_cidr", _inside_cidr(i))
        t["outside_ip"] = f"{rng.randint(3, 52)}.{rng.randint(1, 250)}.{rng.randint(1, 250)}.{rng.randint(1, 250)}"
        t["status"] = "DOWN"
        t["status_message"] = "no customer gateway device is negotiating IKE (the simulator has no IPsec peer)"
        tunnels.append(t)
    vid = V._rid("vpn", 17)
    vpns[vid] = {"id": vid, "cgw": cgw, "vgw": vgw, "tgw": tgw, "static_only": static_only, "state": "available", "routes": [],
                 "tunnels": tunnels, "created": V._now(), "local_cidr": str(p.get("Options.LocalIpv4NetworkCidr", "0.0.0.0/0")),
                 "remote_cidr": str(p.get("Options.RemoteIpv4NetworkCidr", "0.0.0.0/0")),
                 "tags": V._parse_tag_specifications(p).get("vpn-connection", {})}
    return V._envelope("CreateVpnConnection", "<vpnConnection>" + _vpn_xml(vpns[vid], m)[6:-7] + "</vpnConnection>")


def _describe_vpns(store, p):
    V = _V(); m = V._model(store); vpns = _bag(m)[2]
    ids = _ids(p, "VpnConnectionId")
    rows = [_need_vpn(m, i) for i in ids] if ids else [c for c in vpns.values() if c["state"] != "deleted"]
    return V._envelope("DescribeVpnConnections", "<vpnConnectionSet>" + "".join(_vpn_xml(c, m) for c in rows) + "</vpnConnectionSet>")


def _delete_vpn(store, p):
    V = _V(); m = V._model(store); c = _need_vpn(m, str(p.get("VpnConnectionId", "")))
    c["state"] = "deleted"
    _bag(m)[2].pop(c["id"])
    resync_propagation(m)
    return V._envelope("DeleteVpnConnection", "<return>true</return>")


def _cidr_ok(s):
    try:
        ipaddress.IPv4Network(s, strict=True)
        return True
    except ValueError:
        return False


def _create_vpn_route(store, p):
    V = _V(); m = V._model(store); c = _need_vpn(m, str(p.get("VpnConnectionId", "")))
    cidr = str(p.get("DestinationCidrBlock", ""))
    if not _cidr_ok(cidr):
        raise _err("InvalidParameterValue", f"Value ({cidr}) for parameter destinationCidrBlock is invalid.")
    if not c["static_only"]:
        raise _err("InvalidParameterValue", "Static routes can only be added to a VPN connection that uses static routing.")
    if cidr in c["routes"]:
        raise _err("InvalidRoute.Duplicate", f"The route {cidr} already exists on {c['id']}.")
    c["routes"].append(cidr)
    resync_propagation(m)
    return V._envelope("CreateVpnConnectionRoute", "<return>true</return>")


def _delete_vpn_route(store, p):
    V = _V(); m = V._model(store); c = _need_vpn(m, str(p.get("VpnConnectionId", "")))
    cidr = str(p.get("DestinationCidrBlock", ""))
    if cidr not in c["routes"]:
        raise _err("InvalidRoute.NotFound", f"The route {cidr} does not exist on {c['id']}.")
    c["routes"].remove(cidr)
    resync_propagation(m)
    return V._envelope("DeleteVpnConnectionRoute", "<return>true</return>")


def _modify_vpn_tunnel(store, p):
    V = _V(); m = V._model(store); c = _need_vpn(m, str(p.get("VpnConnectionId", "")))
    ip = str(p.get("VpnTunnelOutsideIpAddress", ""))
    t = next((t for t in c["tunnels"] if t["outside_ip"] == ip), None)
    if t is None:
        raise _err("InvalidParameterValue", f"{ip} is not a tunnel outside IP address of {c['id']}.")
    opts = {}
    for k, v in p.items():
        if k.startswith("TunnelOptions."):
            opts[k[len("TunnelOptions."):]] = v
    t.update(_tunnel_opts_from(opts, t))
    return V._envelope("ModifyVpnTunnelOptions", "<vpnConnection>" + _vpn_xml(c, m)[6:-7] + "</vpnConnection>")


def _modify_vpn_options(store, p):
    V = _V(); m = V._model(store); c = _need_vpn(m, str(p.get("VpnConnectionId", "")))
    if "LocalIpv4NetworkCidr" in p:
        c["local_cidr"] = str(p["LocalIpv4NetworkCidr"])
    if "RemoteIpv4NetworkCidr" in p:
        c["remote_cidr"] = str(p["RemoteIpv4NetworkCidr"])
    return V._envelope("ModifyVpnConnectionOptions", "<vpnConnection>" + _vpn_xml(c, m)[6:-7] + "</vpnConnection>")


# ── VGW route propagation ────────────────────────────────────────────────
def resync_propagation(m):
    """Recompute `propagated` routes of every route table from its propagating VGWs."""
    vgws, vpns = m.get("vgws", {}), m.get("vpn_connections", {})
    for rt in m.get("route_tables", {}).values():
        prop, seen = [], {r["dest"] for r in rt.get("routes", [])}
        for gid in rt.get("propagating_vgws", []):
            g = vgws.get(gid)
            if not g or rt["vpc_id"] not in g["vpcs"]:
                continue
            for c in vpns.values():
                if c["vgw"] == gid and c["state"] == "available":
                    for cidr in c["routes"]:
                        if cidr not in seen:
                            seen.add(cidr)
                            prop.append({"dest": cidr, "target": gid, "state": "active", "propagated": True, "vpn": c["id"]})
        if prop or "propagated" in rt:
            rt["propagated"] = prop


def _enable_prop(store, p):
    V = _V(); m = V._model(store); g = _need_vgw(m, str(p.get("GatewayId", "")))
    rt = m["route_tables"].get(str(p.get("RouteTableId", "")))
    if rt is None:
        raise _err("InvalidRouteTableID.NotFound", f"The routeTable ID '{p.get('RouteTableId')}' does not exist")
    if rt["vpc_id"] not in g["vpcs"]:
        raise _err("InvalidParameterValue", f"{g['id']} is not attached to {rt['vpc_id']}.")
    lst = rt.setdefault("propagating_vgws", [])
    if g["id"] in lst:
        raise _err("Gateway.Propagation.Duplicate", f"Route propagation from {g['id']} to {rt['id']} is already enabled.")
    lst.append(g["id"])
    resync_propagation(m)
    return V._envelope("EnableVgwRoutePropagation", "<return>true</return>")


def _disable_prop(store, p):
    V = _V(); m = V._model(store); _need_vgw(m, str(p.get("GatewayId", "")))
    rt = m["route_tables"].get(str(p.get("RouteTableId", "")))
    if rt is None:
        raise _err("InvalidRouteTableID.NotFound", f"The routeTable ID '{p.get('RouteTableId')}' does not exist")
    if str(p.get("GatewayId")) not in rt.get("propagating_vgws", []):
        raise _err("InvalidParameterValue", f"Route propagation from {p.get('GatewayId')} to {rt['id']} is not enabled.")
    rt["propagating_vgws"].remove(str(p["GatewayId"]))
    resync_propagation(m)
    return V._envelope("DisableVgwRoutePropagation", "<return>true</return>")


OPS = {
    "CreateCustomerGateway": _create_cgw, "DescribeCustomerGateways": _describe_cgws, "DeleteCustomerGateway": _delete_cgw,
    "CreateVpnGateway": _create_vgw, "DescribeVpnGateways": _describe_vgws, "AttachVpnGateway": _attach_vgw,
    "DetachVpnGateway": _detach_vgw, "DeleteVpnGateway": _delete_vgw,
    "CreateVpnConnection": _create_vpn, "DescribeVpnConnections": _describe_vpns, "DeleteVpnConnection": _delete_vpn,
    "CreateVpnConnectionRoute": _create_vpn_route, "DeleteVpnConnectionRoute": _delete_vpn_route,
    "ModifyVpnTunnelOptions": _modify_vpn_tunnel, "ModifyVpnConnectionOptions": _modify_vpn_options,
    "EnableVgwRoutePropagation": _enable_prop, "DisableVgwRoutePropagation": _disable_prop,
}
