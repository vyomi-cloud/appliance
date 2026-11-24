# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""EC2 network resources: VPC, subnets, internet gateway, route tables (+ associations), security groups."""
from __future__ import annotations

from core.tf_export import hcl
from core.tf_export.core import Ctx, exporter, slug, tags_of


def _name_hint(tags: dict, ident: str, fallback: str = "") -> str:
    """Terraform name: the Name tag, else a stable descriptive fallback (never a generated id, so two exports of the same stack match)."""
    return tags.get("Name") or fallback or ident


@exporter(10, "vpc")
def export_vpcs(ctx: Ctx) -> None:
    ec2 = ctx.c["ec2"]
    for v in ec2.describe_vpcs().get("Vpcs", []):
        vid = v["VpcId"]
        if v.get("IsDefault"):
            ctx.data.append(("aws_vpc", "default", {"default": True}))
            ctx.alias("aws_vpc", vid, "data.aws_vpc.default")
            ctx.skip("aws_vpc", vid, "default VPC (referenced as a data source)")
            continue
        tags = tags_of(v.get("Tags"))
        attrs = {"cidr_block": v["CidrBlock"], "tags": tags or None}
        if v.get("InstanceTenancy") not in (None, "default"):
            attrs["instance_tenancy"] = v["InstanceTenancy"]
        for attr, tf in (("enableDnsSupport", "enable_dns_support"), ("enableDnsHostnames", "enable_dns_hostnames")):
            try:
                attrs[tf] = ec2.describe_vpc_attribute(VpcId=vid, Attribute=attr)[attr[0].upper() + attr[1:]]["Value"]
            except Exception:  # noqa: BLE001 - the provider default applies
                pass
        ctx.add("aws_vpc", vid, _name_hint(tags, vid, f"vpc_{v['CidrBlock']}"), attrs, file="network.tf")


@exporter(11, "subnet")
def export_subnets(ctx: Ctx) -> None:
    for s in ctx.c["ec2"].describe_subnets().get("Subnets", []):
        sid = s["SubnetId"]
        if s.get("DefaultForAz"):
            ctx.skip("aws_subnet", sid, "default subnet")
            continue
        tags = tags_of(s.get("Tags"))
        attrs = {"vpc_id": ctx.ref("aws_vpc", s["VpcId"]), "cidr_block": s["CidrBlock"],
                 "availability_zone": s.get("AvailabilityZone"),
                 "map_public_ip_on_launch": True if s.get("MapPublicIpOnLaunch") else None, "tags": tags or None}
        ctx.add("aws_subnet", sid, _name_hint(tags, sid, f"subnet_{s['CidrBlock']}"), attrs, file="network.tf")


@exporter(12, "internet-gateway")
def export_igws(ctx: Ctx) -> None:
    for g in ctx.c["ec2"].describe_internet_gateways().get("InternetGateways", []):
        gid = g["InternetGatewayId"]
        att = [a["VpcId"] for a in g.get("Attachments", []) if a.get("VpcId")]
        if not att or ctx.addr.get(("aws_vpc", att[0]), "").startswith("data."):
            ctx.skip("aws_internet_gateway", gid, "default VPC's gateway" if att else "detached")
            continue
        tags = tags_of(g.get("Tags"))
        ctx.add("aws_internet_gateway", gid, _name_hint(tags, gid, "igw_" + ctx.addr[("aws_vpc", att[0])].split(".", 1)[1]), {"vpc_id": ctx.ref("aws_vpc", att[0]), "tags": tags or None},
                file="network.tf")


@exporter(13, "route-table")
def export_route_tables(ctx: Ctx) -> None:
    for rt in ctx.c["ec2"].describe_route_tables().get("RouteTables", []):
        rid = rt["RouteTableId"]
        assoc = rt.get("Associations", [])
        if any(a.get("Main") for a in assoc) or ctx.addr.get(("aws_vpc", rt["VpcId"]), "").startswith("data."):
            ctx.skip("aws_route_table", rid, "main route table (implicit)")
            continue
        tags = tags_of(rt.get("Tags"))
        routes = []
        for r in rt.get("Routes", []):
            if r.get("GatewayId") == "local" or r.get("Origin") == "CreateRouteTable":
                continue
            b = {"cidr_block": r.get("DestinationCidrBlock"), "ipv6_cidr_block": r.get("DestinationIpv6CidrBlock")}
            if r.get("GatewayId"):
                b["gateway_id"] = ctx.ref("aws_internet_gateway", r["GatewayId"])
            if r.get("NatGatewayId"):
                b["nat_gateway_id"] = r["NatGatewayId"]
            routes.append(("route", {k: v for k, v in b.items() if v is not None}))
        addr = ctx.add("aws_route_table", rid, _name_hint(tags, rid, "rt_" + ctx.addr[("aws_vpc", rt["VpcId"])].split(".", 1)[1]),
                       {"vpc_id": ctx.ref("aws_vpc", rt["VpcId"]), "tags": tags or None}, routes, file="network.tf")
        for a in assoc:
            if a.get("SubnetId"):
                ctx.add("aws_route_table_association", a["RouteTableAssociationId"],
                        f"{addr.split('.', 1)[1]}_{ctx.addr[('aws_subnet', a['SubnetId'])].split('.', 1)[1]}",
                        {"subnet_id": ctx.ref("aws_subnet", a["SubnetId"]), "route_table_id": hcl.Ref(f"{addr}.id")}, file="network.tf")


def _perm_blocks(ctx: Ctx, perms) -> list[tuple[str, dict]]:
    out = []
    for p in perms or []:
        b = {"from_port": p.get("FromPort", 0), "to_port": p.get("ToPort", 0), "protocol": p.get("IpProtocol", "-1"),
             "cidr_blocks": [r["CidrIp"] for r in p.get("IpRanges", [])] or None,
             "ipv6_cidr_blocks": [r["CidrIpv6"] for r in p.get("Ipv6Ranges", [])] or None,
             "security_groups": [ctx.ref("aws_security_group", g["GroupId"]) for g in p.get("UserIdGroupPairs", [])] or None,
             "description": next((r["Description"] for r in p.get("IpRanges", []) if r.get("Description")), None)}
        out.append({k: v for k, v in b.items() if v is not None})
    return out


@exporter(14, "security-group")
def export_security_groups(ctx: Ctx) -> None:
    groups = ctx.c["ec2"].describe_security_groups().get("SecurityGroups", [])
    keep = []
    for g in groups:
        if g["GroupName"] == "default" or ctx.addr.get(("aws_vpc", g.get("VpcId", "")), "").startswith("data."):
            ctx.skip("aws_security_group", g["GroupId"], "default security group / default VPC")
            continue
        keep.append(g)
        ctx.reserve("aws_security_group", g["GroupId"], _name_hint(tags_of(g.get("Tags")), g["GroupName"]))
    for g in keep:
        tags = tags_of(g.get("Tags"))
        attrs = {"name": g["GroupName"], "description": g.get("Description") or "Managed by Terraform",
                 "vpc_id": ctx.ref("aws_vpc", g.get("VpcId", "")), "tags": tags or None}
        blocks = [("ingress", b) for b in _perm_blocks(ctx, g.get("IpPermissions"))]
        blocks += [("egress", b) for b in _perm_blocks(ctx, g.get("IpPermissionsEgress"))]
        ctx.add("aws_security_group", g["GroupId"], _name_hint(tags, g["GroupName"]), attrs, blocks, file="network.tf")
