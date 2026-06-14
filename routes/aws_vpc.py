"""AWS VPC, subnet, security group, route table, IGW CRUD.

Extracted from server.py — contains both the REST API route handlers and
the underlying helper / business-logic functions, including the EC2 XML
query handler for VPC actions.
"""
from __future__ import annotations

import copy
import hashlib
import secrets
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response

from core import app_context as ctx
from core.models import (
    InternetGatewayRequest,
    RouteTableRequest,
    SecurityGroupRequest,
    SubnetAssociationRequest,
    SubnetRequest,
    VpcRequest,
)

# ---------------------------------------------------------------------------
# Lazy back-reference to server.py
# ---------------------------------------------------------------------------


def _srv():
    import server as _s
    return _s


# ---------------------------------------------------------------------------
# State access
# ---------------------------------------------------------------------------

vpc_state = ctx.vpc_state
ec2_state = ctx.ec2_state

# ---------------------------------------------------------------------------
# Helper proxies — delegate to server.py for internal functions
# ---------------------------------------------------------------------------


def _vpc_associate_subnet_to_route_table(rt_id: str, subnet_id: str) -> str:
    return _srv()._vpc_associate_subnet_to_route_table(rt_id, subnet_id)


def _vpc_attach_internet_gateway_record(igw_id: str, vpc_id: str) -> dict:
    return _srv()._vpc_attach_internet_gateway_record(igw_id, vpc_id)


# ---------------------------------------------------------------------------
# Console REST API route handlers
# ---------------------------------------------------------------------------


def api_vpc_list_vpcs():
    vpcs = []
    igws_state = vpc_state.setdefault("internet_gateways", {})
    for vpc in vpc_state["vpcs"].values():
        vpc_id = vpc["vpc_id"]
        subnets = [s for s in vpc_state["subnets"].values() if s.get("vpc_id") == vpc_id]
        route_tables = [r for r in vpc_state["route_tables"].values() if r.get("vpc_id") == vpc_id]
        security_groups = [g for g in vpc_state["security_groups"].values() if g.get("vpc_id") == vpc_id]
        internet_gateways = [g for g in igws_state.values() if g.get("attached_vpc_id") == vpc_id]
        vpcs.append({
            **vpc,
            "subnet_count": len(subnets),
            "route_table_count": len(route_tables),
            "security_group_count": len(security_groups),
            "internet_gateway_count": len(internet_gateways),
            "availability_zones": sorted({s.get("availability_zone", "") for s in subnets if s.get("availability_zone")}),
        })
    return {"vpcs": vpcs, "count": len(vpc_state["vpcs"])}


def api_vpc_get(vpc_id: str):
    """GET /api/vpc/vpcs/{vpc_id} — return a single VPC with its
    aggregate counts. Mirrors the entry in api_vpc_list_vpcs.
    """
    vpc = vpc_state["vpcs"].get(vpc_id)
    if not vpc:
        raise HTTPException(404, detail="NoSuchVpc")
    igws_state = vpc_state.setdefault("internet_gateways", {})
    subnets = [s for s in vpc_state["subnets"].values() if s.get("vpc_id") == vpc_id]
    route_tables = [r for r in vpc_state["route_tables"].values() if r.get("vpc_id") == vpc_id]
    security_groups = [g for g in vpc_state["security_groups"].values() if g.get("vpc_id") == vpc_id]
    internet_gateways = [g for g in igws_state.values() if g.get("attached_vpc_id") == vpc_id]
    return {
        **vpc,
        "subnet_count": len(subnets),
        "route_table_count": len(route_tables),
        "security_group_count": len(security_groups),
        "internet_gateway_count": len(internet_gateways),
        "availability_zones": sorted({s.get("availability_zone", "") for s in subnets if s.get("availability_zone")}),
    }


def api_vpc_create(req: VpcRequest):
    vpc_id = ctx.id_gen("vpc")
    default_rt_id = ctx.id_gen("rtb")
    default_sg_id = ctx.id_gen("sg")
    vpc = {
        "vpc_id": vpc_id,
        "name": req.name,
        "cidr_block": req.cidr_block,
        "encryption_controls": req.encryption_controls,
        "tenancy": req.tenancy,
        "ipv6_mode": req.ipv6_mode,
        "tags": req.tags or [],
        "created": ctx.now(),
        "state": "available",
        "dhcp_options_id": f"dopt-{vpc_id.replace('vpc-', '')[:8] or secrets.token_hex(4)}",
        "main_route_table_id": default_rt_id,
        "default_security_group_id": default_sg_id,
        "internet_gateway_id": "",
    }
    vpc_state["vpcs"][vpc_id] = vpc
    vpc_state["route_tables"][default_rt_id] = {
        "route_table_id": default_rt_id,
        "vpc_id": vpc_id,
        "name": f"{req.name}-main" if req.name else default_rt_id,
        "routes": [{"destination": vpc["cidr_block"], "target_type": "local", "target_id": vpc_id, "type": "CreateRouteTable", "created": ctx.now()}],
        "subnet_ids": [],
        "is_main": True,
        "created": ctx.now(),
        "tags": [],
    }
    vpc_state["security_groups"][default_sg_id] = {
        "security_group_id": default_sg_id,
        "vpc_id": vpc_id,
        "group_name": "default",
        "description": "default VPC security group",
        "ingress": [],
        "egress": [{"protocol": "-1", "from_port": 0, "to_port": 0, "cidr": "0.0.0.0/0", "source_sg": "", "description": "allow all outbound traffic", "created": ctx.now()}],
        "is_default": True,
        "created": ctx.now(),
        "tags": [],
    }
    ctx.record_usage("vpc.create_vpc", vpc)
    return vpc


def api_vpc_delete(vpc_id: str, force: bool = False):
    vpc = vpc_state["vpcs"].get(vpc_id)
    if not vpc:
        raise HTTPException(404, detail="NoSuchVpc")
    instances = [i for i in ec2_state["instances"].values() if i.get("vpc_id") == vpc_id and i.get("state") not in {"terminated"}]
    if instances and not force:
        raise HTTPException(409, detail="VpcHasActiveInstances")
    if force:
        for inst in instances:
            inst["state"] = "terminated"
            inst["terminated_at"] = ctx.now()
            inst["updated"] = ctx.now()
            ctx.record_usage("vpc.delete.terminate_instance", {"vpc_id": vpc_id, "instance_id": inst.get("instance_id")})
    for subnet_id, subnet in list(vpc_state["subnets"].items()):
        if subnet.get("vpc_id") == vpc_id:
            rt_id = subnet.get("route_table_id")
            if rt_id and rt_id in vpc_state["route_tables"]:
                rt = vpc_state["route_tables"][rt_id]
                rt["subnet_ids"] = [sid for sid in rt.get("subnet_ids", []) if sid != subnet_id]
            del vpc_state["subnets"][subnet_id]
    for rt_id, rt in list(vpc_state["route_tables"].items()):
        if rt.get("vpc_id") == vpc_id:
            del vpc_state["route_tables"][rt_id]
    for sg_id, sg in list(vpc_state["security_groups"].items()):
        if sg.get("vpc_id") == vpc_id:
            del vpc_state["security_groups"][sg_id]
    for igw_id, igw in list(vpc_state["internet_gateways"].items()):
        if igw.get("attached_vpc_id") == vpc_id:
            del vpc_state["internet_gateways"][igw_id]
    del vpc_state["vpcs"][vpc_id]
    ctx.record_usage("vpc.delete_vpc", {"vpc_id": vpc_id, "force": force})
    return {"deleted": True, "vpc_id": vpc_id}


def api_vpc_create_subnet(req: SubnetRequest):
    if req.vpc_id not in vpc_state["vpcs"]:
        raise HTTPException(404, detail="NoSuchVpc")
    subnet_id = ctx.id_gen("subnet")
    main_rt_id = vpc_state["vpcs"][req.vpc_id].get("main_route_table_id", "")
    subnet = {
        "subnet_id": subnet_id,
        "vpc_id": req.vpc_id,
        "cidr_block": req.cidr_block,
        "availability_zone": req.availability_zone,
        "name": req.name or subnet_id,
        "route_table_id": main_rt_id,
        "created": ctx.now(),
        "tags": req.tags or [],
    }
    vpc_state["subnets"][subnet_id] = subnet
    if main_rt_id and main_rt_id in vpc_state["route_tables"]:
        _vpc_associate_subnet_to_route_table(main_rt_id, subnet_id)
    ctx.record_usage("vpc.create_subnet", subnet)
    return subnet


def api_vpc_create_security_group(req: SecurityGroupRequest):
    if req.vpc_id not in vpc_state["vpcs"]:
        raise HTTPException(404, detail="NoSuchVpc")
    sg_id = ctx.id_gen("sg")
    sg = {"security_group_id": sg_id, "vpc_id": req.vpc_id, "group_name": req.group_name, "description": req.description, "ingress": [], "egress": [{"protocol": "-1", "from_port": 0, "to_port": 0, "cidr": "0.0.0.0/0", "source_sg": "", "description": "allow all outbound traffic", "created": ctx.now()}], "is_default": False, "created": ctx.now(), "tags": req.tags or []}
    vpc_state["security_groups"][sg_id] = sg
    ctx.record_usage("vpc.create_security_group", sg)
    return sg


def api_vpc_add_ingress(sg_id: str, payload: dict[str, Any]):
    sg = vpc_state["security_groups"].get(sg_id)
    if not sg:
        raise HTTPException(404, detail="NoSuchSecurityGroup")
    rule = {"protocol": payload.get("protocol", "tcp"), "from_port": payload.get("from_port", 0), "to_port": payload.get("to_port", 65535), "cidr": payload.get("cidr", "0.0.0.0/0"), "source_sg": payload.get("source_sg", ""), "description": payload.get("description", ""), "created": ctx.now()}
    sg.setdefault("ingress", []).append(rule)
    ctx.record_usage("vpc.add_ingress", {"sg_id": sg_id, "rule": rule})
    return sg


def api_vpc_list_subnets():
    return {"subnets": list(vpc_state["subnets"].values()), "count": len(vpc_state["subnets"])}


def api_vpc_list_security_groups():
    return {"security_groups": list(vpc_state["security_groups"].values()), "count": len(vpc_state["security_groups"])}


def api_vpc_list_route_tables():
    return {"route_tables": list(vpc_state["route_tables"].values()), "count": len(vpc_state["route_tables"])}


def api_vpc_create_route_table(req: RouteTableRequest):
    if req.vpc_id not in vpc_state["vpcs"]:
        raise HTTPException(404, detail="NoSuchVpc")
    rt_id = ctx.id_gen("rtb")
    rt = {
        "route_table_id": rt_id,
        "vpc_id": req.vpc_id,
        "name": req.name or rt_id,
        "routes": [{"destination": vpc_state["vpcs"][req.vpc_id].get("cidr_block", "10.0.0.0/16"), "target_type": "local", "target_id": req.vpc_id, "type": "CreateRouteTable", "created": ctx.now()}],
        "subnet_ids": [],
        "is_main": False,
        "created": ctx.now(),
        "tags": req.tags or [],
    }
    vpc_state["route_tables"][rt_id] = rt
    ctx.record_usage("vpc.create_route_table", rt)
    return rt


def api_vpc_list_internet_gateways():
    # Defensive: spaces created before internet_gateways was added to the
    # default state schema don't have this key. Don't 500 — initialize lazily.
    igws = vpc_state.setdefault("internet_gateways", {})
    return {"internet_gateways": list(igws.values()), "count": len(igws)}


def api_vpc_create_internet_gateway(req: InternetGatewayRequest):
    igw_id = ctx.id_gen("igw")
    igw = {"internet_gateway_id": igw_id, "name": req.name or igw_id, "attached_vpc_id": "", "created": ctx.now(), "tags": req.tags or []}
    vpc_state.setdefault("internet_gateways", {})[igw_id] = igw
    ctx.record_usage("vpc.create_internet_gateway", igw)
    return igw


def api_vpc_attach_internet_gateway(igw_id: str, payload: dict[str, Any]):
    vpc_id = payload.get("vpc_id", "")
    igw = _vpc_attach_internet_gateway_record(igw_id, vpc_id)
    ctx.record_usage("vpc.attach_internet_gateway", {"igw_id": igw_id, "vpc_id": vpc_id})
    return igw


def api_vpc_add_route(rt_id: str, payload: dict[str, Any]):
    rt = vpc_state["route_tables"].get(rt_id)
    if not rt:
        raise HTTPException(404, detail="NoSuchRouteTable")
    route = {
        "destination": payload.get("destination_cidr", "0.0.0.0/0"),
        "target_type": payload.get("target_type", "internet-gateway"),
        "target_id": payload.get("target_id", ""),
        "type": "CreateRoute",
        "created": ctx.now(),
    }
    rt.setdefault("routes", []).append(route)
    ctx.record_usage("vpc.add_route", {"route_table_id": rt_id, "route": route})
    return rt


def api_vpc_associate_subnet(rt_id: str, req: SubnetAssociationRequest):
    _vpc_associate_subnet_to_route_table(rt_id, req.subnet_id)
    ctx.record_usage("vpc.associate_subnet", {"route_table_id": rt_id, "subnet_id": req.subnet_id})
    return vpc_state["route_tables"][rt_id]


def api_vpc_resources(vpc_id: str):
    if vpc_id not in vpc_state["vpcs"]:
        raise HTTPException(404, detail="NoSuchVpc")
    subnets = [s for s in vpc_state["subnets"].values() if s.get("vpc_id") == vpc_id]
    route_tables = [r for r in vpc_state["route_tables"].values() if r.get("vpc_id") == vpc_id]
    security_groups = [g for g in vpc_state["security_groups"].values() if g.get("vpc_id") == vpc_id]
    internet_gateways = [g for g in vpc_state.setdefault("internet_gateways", {}).values() if g.get("attached_vpc_id") == vpc_id]
    instances = [i for i in ec2_state["instances"].values() if i.get("vpc_id") == vpc_id]
    return {
        "vpc": vpc_state["vpcs"][vpc_id],
        "subnets": subnets,
        "route_tables": route_tables,
        "security_groups": security_groups,
        "internet_gateways": internet_gateways,
        "instances": instances,
        "counts": {
            "subnets": len(subnets),
            "route_tables": len(route_tables),
            "security_groups": len(security_groups),
            "internet_gateways": len(internet_gateways),
            "instances": len(instances),
        },
    }


# ---------------------------------------------------------------------------
# Query-protocol handler (EC2 XML)
# ---------------------------------------------------------------------------

async def api_vpc_query(request: Request):
    return await _srv().api_vpc_query(request)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def register(app: FastAPI) -> None:
    """Register VPC routes on the FastAPI app.

    NOTE: VPC routes are currently registered via providers/aws_routes.py
    using the dynamic _proxy/_add_route mechanism.  This register() function
    is provided for future use when the migration is complete.
    """
    pass  # Routes registered via providers/aws_routes.py spec table
