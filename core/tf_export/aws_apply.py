"""Appliers for the AWS resource types the exporter writes: each creates the object through the simulator's own native AWS API (the
calls Terraform's provider makes) and finds an existing one by its natural key, so applying twice changes nothing."""
from __future__ import annotations

import json

from core.tf_export.apply import applier, data_source
from core.tf_export.core import tags_of


# ----------------------------------------------------------------------------------------------------------------- helpers
def code(exc: Exception) -> str:
    return str(((getattr(exc, "response", None) or {}).get("Error") or {}).get("Code") or "")


def _missing(exc: Exception, *codes: str) -> bool:
    c = code(exc)
    return c in codes or any(x in c for x in ("NotFound", "NoSuch", "DoesNotExist"))


def _tagspec(rtype: str, tags: dict) -> list:
    return [{"ResourceType": rtype, "Tags": [{"Key": k, "Value": v} for k, v in tags.items()]}] if tags else []


def _tag_list(tags: dict) -> list:
    return [{"Key": k, "Value": v} for k, v in tags.items()]


def _same_tags(have: list | None, want: dict) -> bool:
    return tags_of(have) == want


def _doc(v):
    if isinstance(v, str):
        try:
            return json.loads(v)
        except ValueError:
            return v
    return v


def _claim(c, ident: str) -> bool:
    if ident in c.claimed:
        return False
    c.claimed.add(ident)
    return True


def _opt(d: dict, **kw) -> dict:
    d.update({k: v for k, v in kw.items() if v is not None})
    return d


def _paged(fn, key, **kw):
    out, marker = [], None
    while True:
        r = fn(**kw, **({"Marker": marker} if marker else {}))
        out += r.get(key, [])
        if not r.get("IsTruncated"):
            return out
        marker = r.get("Marker")


# ------------------------------------------------------------------------------------------------------------ data sources
@data_source("aws_caller_identity")
def _d_identity(c, a):
    return {"account_id": c.account, "arn": f"arn:aws:iam::{c.account}:root", "user_id": c.account, "id": c.account}


@data_source("aws_region")
def _d_region(c, a):
    return {"name": c.region, "id": c.region, "description": c.region}


@data_source("aws_partition")
def _d_partition(c, a):
    return {"partition": "aws", "dns_suffix": "amazonaws.com", "id": "aws"}


@data_source("aws_availability_zones")
def _d_azs(c, a):
    zs = c.ec2.describe_availability_zones().get("AvailabilityZones", [])
    return {"names": [z["ZoneName"] for z in zs], "zone_ids": [z.get("ZoneId", "") for z in zs], "id": c.region}


@data_source("aws_vpc")
def _d_vpc(c, a):
    for v in c.ec2.describe_vpcs().get("Vpcs", []):
        if a.get("id") and v["VpcId"] != a["id"]:
            continue
        if a.get("default") and not v.get("IsDefault"):
            continue
        if a.get("cidr_block") and v["CidrBlock"] != a["cidr_block"]:
            continue
        if a.get("tags") and not all(tags_of(v.get("Tags")).get(k) == x for k, x in a["tags"].items()):
            continue
        return {"id": v["VpcId"], "cidr_block": v["CidrBlock"], "arn": f"arn:aws:ec2:{c.region}:{c.account}:vpc/{v['VpcId']}",
                "default": bool(v.get("IsDefault")), "tags": tags_of(v.get("Tags"))}
    raise LookupError("no matching VPC for data.aws_vpc")


@data_source("aws_subnets")
def _d_subnets(c, a):
    ids = [s["SubnetId"] for s in c.ec2.describe_subnets().get("Subnets", [])]
    return {"ids": ids, "id": c.region}


# -------------------------------------------------------------------------------------------------------------------- EC2
@applier("aws_vpc")
class Vpc:
    def find(self, c, a):
        for v in c.ec2.describe_vpcs().get("Vpcs", []):
            if v.get("IsDefault") or v["CidrBlock"] != a.get("cidr_block") or not _same_tags(v.get("Tags"), a.tags):
                continue
            if _claim(c, v["VpcId"]):
                return self._out(c, v)
        return None

    def _out(self, c, v):
        return {"id": v["VpcId"], "arn": f"arn:aws:ec2:{c.region}:{c.account}:vpc/{v['VpcId']}", "cidr_block": v["CidrBlock"], "owner_id": c.account}

    def create(self, c, a):
        v = c.ec2.create_vpc(**_opt({"CidrBlock": a.get("cidr_block"), "TagSpecifications": _tagspec("vpc", a.tags)},
                                    InstanceTenancy=a.get("instance_tenancy")))["Vpc"]
        for tf, attr in (("enable_dns_support", "EnableDnsSupport"), ("enable_dns_hostnames", "EnableDnsHostnames")):
            if a.attrs.get(tf) is not None:
                c.ec2.modify_vpc_attribute(VpcId=v["VpcId"], **{attr: {"Value": bool(a.attrs[tf])}})
        c.claimed.add(v["VpcId"])
        return self._out(c, v)

    def delete(self, c, out):
        c.ec2.delete_vpc(VpcId=out["id"])


@applier("aws_subnet")
class Subnet:
    def find(self, c, a):
        for s in c.ec2.describe_subnets().get("Subnets", []):
            if s["VpcId"] == a.get("vpc_id") and s["CidrBlock"] == a.get("cidr_block") and _claim(c, s["SubnetId"]):
                return self._out(c, s)
        return None

    def _out(self, c, s):
        return {"id": s["SubnetId"], "arn": f"arn:aws:ec2:{c.region}:{c.account}:subnet/{s['SubnetId']}", "vpc_id": s["VpcId"],
                "cidr_block": s["CidrBlock"], "availability_zone": s.get("AvailabilityZone", "")}

    def create(self, c, a):
        s = c.ec2.create_subnet(**_opt({"VpcId": a.get("vpc_id"), "CidrBlock": a.get("cidr_block"),
                                        "TagSpecifications": _tagspec("subnet", a.tags)}, AvailabilityZone=a.get("availability_zone")))["Subnet"]
        if a.attrs.get("map_public_ip_on_launch"):
            c.ec2.modify_subnet_attribute(SubnetId=s["SubnetId"], MapPublicIpOnLaunch={"Value": True})
        c.claimed.add(s["SubnetId"])
        return self._out(c, s)

    def delete(self, c, out):
        c.ec2.delete_subnet(SubnetId=out["id"])


@applier("aws_internet_gateway")
class Igw:
    def find(self, c, a):
        for g in c.ec2.describe_internet_gateways().get("InternetGateways", []):
            if any(x.get("VpcId") == a.get("vpc_id") for x in g.get("Attachments", [])) and _claim(c, g["InternetGatewayId"]):
                return {"id": g["InternetGatewayId"], "vpc_id": a.get("vpc_id"), "arn": f"arn:aws:ec2:{c.region}:{c.account}:internet-gateway/{g['InternetGatewayId']}"}
        return None

    def create(self, c, a):
        g = c.ec2.create_internet_gateway(TagSpecifications=_tagspec("internet-gateway", a.tags))["InternetGateway"]
        c.ec2.attach_internet_gateway(InternetGatewayId=g["InternetGatewayId"], VpcId=a.get("vpc_id"))
        c.claimed.add(g["InternetGatewayId"])
        return {"id": g["InternetGatewayId"], "vpc_id": a.get("vpc_id"), "arn": f"arn:aws:ec2:{c.region}:{c.account}:internet-gateway/{g['InternetGatewayId']}"}

    def delete(self, c, out):
        try:
            c.ec2.detach_internet_gateway(InternetGatewayId=out["id"], VpcId=out["vpc_id"])
        except Exception as exc:  # noqa: BLE001 - already detached
            if not _missing(exc, "Gateway.NotAttached"):
                raise
        c.ec2.delete_internet_gateway(InternetGatewayId=out["id"])


_ROUTE_KEYS = {"gateway_id": "GatewayId", "nat_gateway_id": "NatGatewayId", "instance_id": "InstanceId", "vpc_endpoint_id": "VpcEndpointId",
               "transit_gateway_id": "TransitGatewayId", "network_interface_id": "NetworkInterfaceId",
               "vpc_peering_connection_id": "VpcPeeringConnectionId", "egress_only_gateway_id": "EgressOnlyInternetGatewayId"}


@applier("aws_route_table")
class RouteTable:
    def find(self, c, a):
        for rt in c.ec2.describe_route_tables().get("RouteTables", []):
            if rt["VpcId"] != a.get("vpc_id") or any(x.get("Main") for x in rt.get("Associations", [])):
                continue
            if _same_tags(rt.get("Tags"), a.tags) and _claim(c, rt["RouteTableId"]):
                return {"id": rt["RouteTableId"], "vpc_id": rt["VpcId"], "arn": f"arn:aws:ec2:{c.region}:{c.account}:route-table/{rt['RouteTableId']}"}
        return None

    def create(self, c, a):
        rt = c.ec2.create_route_table(VpcId=a.get("vpc_id"), TagSpecifications=_tagspec("route-table", a.tags))["RouteTable"]
        rid = rt["RouteTableId"]
        for _t, b, _k in a.blocks_of("route"):
            kw = _opt({"RouteTableId": rid}, DestinationCidrBlock=b.get("cidr_block"), DestinationIpv6CidrBlock=b.get("ipv6_cidr_block"))
            for tf, aws in _ROUTE_KEYS.items():
                if b.get(tf):
                    kw[aws] = b[tf]
            c.ec2.create_route(**kw)
        c.claimed.add(rid)
        return {"id": rid, "vpc_id": a.get("vpc_id"), "arn": f"arn:aws:ec2:{c.region}:{c.account}:route-table/{rid}"}

    def delete(self, c, out):
        c.ec2.delete_route_table(RouteTableId=out["id"])


@applier("aws_route_table_association")
class RouteTableAssociation:
    def find(self, c, a):
        for rt in c.ec2.describe_route_tables(RouteTableIds=[a.get("route_table_id")]).get("RouteTables", []):
            for x in rt.get("Associations", []):
                if x.get("SubnetId") == a.get("subnet_id"):
                    return {"id": x["RouteTableAssociationId"]}
        return None

    def create(self, c, a):
        r = c.ec2.associate_route_table(RouteTableId=a.get("route_table_id"), SubnetId=a.get("subnet_id"))
        return {"id": r["AssociationId"]}

    def delete(self, c, out):
        c.ec2.disassociate_route_table(AssociationId=out["id"])


def _perm(a, b, own_id=None):
    p = {"IpProtocol": str(b.get("protocol", "-1")), "FromPort": int(b.get("from_port", 0)), "ToPort": int(b.get("to_port", 0))}
    if p["IpProtocol"] == "all":
        p["IpProtocol"] = "-1"
    desc = b.get("description")
    if b.get("cidr_blocks"):
        p["IpRanges"] = [_opt({"CidrIp": x}, Description=desc) for x in b["cidr_blocks"]]
    if b.get("ipv6_cidr_blocks"):
        p["Ipv6Ranges"] = [_opt({"CidrIpv6": x}, Description=desc) for x in b["ipv6_cidr_blocks"]]
    groups = list(b.get("security_groups") or []) + ([own_id] if b.get("self") and own_id else [])
    if groups:
        p["UserIdGroupPairs"] = [{"GroupId": g} for g in groups]
    return p


@applier("aws_security_group")
class SecurityGroup:
    def find(self, c, a):
        for g in c.ec2.describe_security_groups().get("SecurityGroups", []):
            if g["GroupName"] == a.get("name") and g.get("VpcId") == a.get("vpc_id") and _claim(c, g["GroupId"]):
                return self._out(c, g)
        return None

    def _out(self, c, g):
        return {"id": g["GroupId"], "name": g["GroupName"], "vpc_id": g.get("VpcId", ""),
                "arn": f"arn:aws:ec2:{c.region}:{c.account}:security-group/{g['GroupId']}", "owner_id": c.account}

    def create(self, c, a):
        r = c.ec2.create_security_group(**_opt({"GroupName": a.get("name"), "Description": a.get("description", "Managed by Terraform"),
                                                "TagSpecifications": _tagspec("security-group", a.tags)}, VpcId=a.get("vpc_id")))
        gid = r["GroupId"]
        c.claimed.add(gid)
        g = c.ec2.describe_security_groups(GroupIds=[gid])["SecurityGroups"][0]
        if g.get("IpPermissionsEgress"):  # Terraform manages egress fully: drop the implicit allow-all first
            c.ec2.revoke_security_group_egress(GroupId=gid, IpPermissions=g["IpPermissionsEgress"])
        for kind, fn in (("ingress", c.ec2.authorize_security_group_ingress), ("egress", c.ec2.authorize_security_group_egress)):
            perms = [_perm(a, a.subst(b[1], id=gid), gid) for b in a.blocks_of(kind)]
            for p in perms:
                fn(GroupId=gid, IpPermissions=[p])
        return self._out(c, g)

    def delete(self, c, out):
        c.ec2.delete_security_group(GroupId=out["id"])


# --------------------------------------------------------------------------------------------------------------------- IAM
@applier("aws_iam_policy")
class IamPolicy:
    def find(self, c, a):
        path = a.get("path", "/")
        for p in _paged(c.iam.list_policies, "Policies", Scope="Local"):
            if p["PolicyName"] == a.get("name") and p.get("Path", "/") == path:
                return {"id": p["Arn"], "arn": p["Arn"], "name": p["PolicyName"]}
        return None

    def create(self, c, a):
        p = c.iam.create_policy(**_opt({"PolicyName": a.get("name"), "PolicyDocument": a.get("policy")}, Path=a.get("path"),
                                       Description=a.get("description")))["Policy"]
        return {"id": p["Arn"], "arn": p["Arn"], "name": p["PolicyName"]}

    def delete(self, c, out):
        for v in c.iam.list_policy_versions(PolicyArn=out["arn"]).get("Versions", []):
            if not v.get("IsDefaultVersion"):
                c.iam.delete_policy_version(PolicyArn=out["arn"], VersionId=v["VersionId"])
        c.iam.delete_policy(PolicyArn=out["arn"])


@applier("aws_iam_role")
class IamRole:
    def _out(self, r):
        return {"id": r["RoleName"], "arn": r["Arn"], "name": r["RoleName"], "unique_id": r.get("RoleId", "")}

    def find(self, c, a):
        try:
            return self._out(c.iam.get_role(RoleName=a.get("name"))["Role"])
        except Exception as exc:  # noqa: BLE001
            if _missing(exc):
                return None
            raise

    def create(self, c, a):
        r = c.iam.create_role(**_opt({"RoleName": a.get("name"), "AssumeRolePolicyDocument": a.get("assume_role_policy")},
                                     Path=a.get("path"), Description=a.get("description"),
                                     MaxSessionDuration=a.get("max_session_duration"),
                                     Tags=_tag_list(a.tags) or None))["Role"]
        return self._out(r)

    def delete(self, c, out):
        for p in _paged(c.iam.list_attached_role_policies, "AttachedPolicies", RoleName=out["name"]):
            c.iam.detach_role_policy(RoleName=out["name"], PolicyArn=p["PolicyArn"])
        for n in _paged(c.iam.list_role_policies, "PolicyNames", RoleName=out["name"]):
            c.iam.delete_role_policy(RoleName=out["name"], PolicyName=n)
        c.iam.delete_role(RoleName=out["name"])


@applier("aws_iam_role_policy")
class IamRolePolicy:
    def find(self, c, a):
        try:
            cur = c.iam.get_role_policy(RoleName=a.get("role"), PolicyName=a.get("name"))["PolicyDocument"]
        except Exception as exc:  # noqa: BLE001
            if _missing(exc):
                return None
            raise
        import urllib.parse
        cur = json.loads(urllib.parse.unquote(cur)) if isinstance(cur, str) else cur
        return {"id": f"{a.get('role')}:{a.get('name')}", "role": a.get("role"), "name": a.get("name")} if cur == _doc(a.get("policy")) else None

    def create(self, c, a):
        c.iam.put_role_policy(RoleName=a.get("role"), PolicyName=a.get("name"), PolicyDocument=a.get("policy"))
        return {"id": f"{a.get('role')}:{a.get('name')}", "role": a.get("role"), "name": a.get("name")}

    def delete(self, c, out):
        c.iam.delete_role_policy(RoleName=out["role"], PolicyName=out["name"])


@applier("aws_iam_role_policy_attachment")
class IamRoleAttach:
    def find(self, c, a):
        try:
            for p in _paged(c.iam.list_attached_role_policies, "AttachedPolicies", RoleName=a.get("role")):
                if p["PolicyArn"] == a.get("policy_arn"):
                    return {"id": f"{a.get('role')}/{a.get('policy_arn')}", "role": a.get("role"), "policy_arn": a.get("policy_arn")}
        except Exception as exc:  # noqa: BLE001
            if not _missing(exc):
                raise
        return None

    def create(self, c, a):
        c.iam.attach_role_policy(RoleName=a.get("role"), PolicyArn=a.get("policy_arn"))
        return {"id": f"{a.get('role')}/{a.get('policy_arn')}", "role": a.get("role"), "policy_arn": a.get("policy_arn")}

    def delete(self, c, out):
        c.iam.detach_role_policy(RoleName=out["role"], PolicyArn=out["policy_arn"])


# ------------------------------------------------------------------------------------------------------------------ Lambda
def _fn_out(c, f):
    arn = f["FunctionArn"]
    return {"id": f["FunctionName"], "arn": arn, "function_name": f["FunctionName"], "qualified_arn": arn, "version": str(f.get("Version", "$LATEST")),
            "invoke_arn": f"arn:aws:apigateway:{c.region}:lambda:path/2015-03-31/functions/{arn}/invocations"}


@applier("aws_lambda_function")
class LambdaFunction:
    def find(self, c, a):
        try:
            return _fn_out(c, c.lambda_.get_function(FunctionName=a.get("function_name"))["Configuration"])
        except Exception as exc:  # noqa: BLE001
            if _missing(exc, "ResourceNotFoundException"):
                return None
            raise

    def create(self, c, a):
        if not a.get("filename"):
            raise ValueError("only filename = \"...zip\" deployment packages are supported (not s3_bucket / image_uri yet)")
        env = next((b[1].get("variables") for b in a.blocks_of("environment")), None)
        kw = _opt({"FunctionName": a.get("function_name"), "Role": a.get("role"), "Code": {"ZipFile": c.file_bytes(a.get("filename"))}},
                  Runtime=a.get("runtime"), Handler=a.get("handler"), Description=a.get("description"), MemorySize=a.get("memory_size"),
                  Timeout=a.get("timeout"), Architectures=a.get("architectures"), Layers=a.get("layers"),
                  Environment={"Variables": {k: str(v) for k, v in env.items()}} if env else None, Tags=a.tags or None)
        return _fn_out(c, c.lambda_.create_function(**kw))

    def delete(self, c, out):
        c.lambda_.delete_function(FunctionName=out["function_name"])


@applier("aws_lambda_permission")
class LambdaPermission:
    def find(self, c, a):
        try:
            pol = json.loads(c.lambda_.get_policy(FunctionName=a.get("function_name"))["Policy"])
        except Exception as exc:  # noqa: BLE001
            if _missing(exc, "ResourceNotFoundException"):
                return None
            raise
        if any(s.get("Sid") == a.get("statement_id") for s in pol.get("Statement", [])):
            return {"id": a.get("statement_id"), "function_name": a.get("function_name"), "statement_id": a.get("statement_id")}
        return None

    def create(self, c, a):
        c.lambda_.add_permission(**_opt({"FunctionName": a.get("function_name"), "StatementId": a.get("statement_id"),
                                         "Action": a.get("action"), "Principal": a.get("principal")}, SourceArn=a.get("source_arn")))
        return {"id": a.get("statement_id"), "function_name": a.get("function_name"), "statement_id": a.get("statement_id")}

    def delete(self, c, out):
        c.lambda_.remove_permission(FunctionName=out["function_name"], StatementId=out["statement_id"])


# ---------------------------------------------------------------------------------------------------------------- API Gateway
@applier("aws_api_gateway_rest_api")
class RestApi:
    def _out(self, c, api):
        root = next((r["id"] for r in c.apigateway.get_resources(restApiId=api["id"], limit=500).get("items", []) if r.get("path") == "/"), "")
        return {"id": api["id"], "name": api["name"], "root_resource_id": root,
                "execution_arn": f"arn:aws:execute-api:{c.region}:{c.account}:{api['id']}", "arn": f"arn:aws:apigateway:{c.region}::/restapis/{api['id']}"}

    def find(self, c, a):
        for api in c.apigateway.get_rest_apis(limit=500).get("items", []):
            if api["name"] == a.get("name") and _claim(c, api["id"]):
                return self._out(c, api)
        return None

    def create(self, c, a):
        api = c.apigateway.create_rest_api(**_opt({"name": a.get("name")}, description=a.get("description"), tags=a.tags or None))
        c.claimed.add(api["id"])
        return self._out(c, api)

    def delete(self, c, out):
        c.apigateway.delete_rest_api(restApiId=out["id"])


@applier("aws_api_gateway_resource")
class ApiResource:
    def find(self, c, a):
        for r in c.apigateway.get_resources(restApiId=a.get("rest_api_id"), limit=500).get("items", []):
            if r.get("parentId") == a.get("parent_id") and r.get("pathPart") == a.get("path_part"):
                return {"id": r["id"], "path": r["path"], "rest_api_id": a.get("rest_api_id")}
        return None

    def create(self, c, a):
        r = c.apigateway.create_resource(restApiId=a.get("rest_api_id"), parentId=a.get("parent_id"), pathPart=a.get("path_part"))
        return {"id": r["id"], "path": r["path"], "rest_api_id": a.get("rest_api_id")}

    def delete(self, c, out):
        c.apigateway.delete_resource(restApiId=out["rest_api_id"], resourceId=out["id"])


@applier("aws_api_gateway_method")
class ApiMethod:
    def _out(self, a):
        return {"id": f"agm-{a.get('rest_api_id')}-{a.get('resource_id')}-{a.get('http_method')}", "rest_api_id": a.get("rest_api_id"),
                "resource_id": a.get("resource_id"), "http_method": a.get("http_method")}

    def find(self, c, a):
        try:
            c.apigateway.get_method(restApiId=a.get("rest_api_id"), resourceId=a.get("resource_id"), httpMethod=a.get("http_method"))
            return self._out(a)
        except Exception as exc:  # noqa: BLE001
            if _missing(exc, "NotFoundException"):
                return None
            raise

    def create(self, c, a):
        c.apigateway.put_method(**_opt({"restApiId": a.get("rest_api_id"), "resourceId": a.get("resource_id"), "httpMethod": a.get("http_method"),
                                        "authorizationType": a.get("authorization", "NONE")}, apiKeyRequired=a.attrs.get("api_key_required"),
                                       requestParameters={k: bool(v) for k, v in (a.attrs.get("request_parameters") or {}).items()} or None))
        return self._out(a)

    def delete(self, c, out):
        c.apigateway.delete_method(restApiId=out["rest_api_id"], resourceId=out["resource_id"], httpMethod=out["http_method"])


@applier("aws_api_gateway_integration")
class ApiIntegration:
    def _out(self, a):
        return {"id": f"agi-{a.get('rest_api_id')}-{a.get('resource_id')}-{a.get('http_method')}", "rest_api_id": a.get("rest_api_id"),
                "resource_id": a.get("resource_id"), "http_method": a.get("http_method")}

    def find(self, c, a):
        try:
            c.apigateway.get_integration(restApiId=a.get("rest_api_id"), resourceId=a.get("resource_id"), httpMethod=a.get("http_method"))
            return self._out(a)
        except Exception as exc:  # noqa: BLE001
            if _missing(exc, "NotFoundException"):
                return None
            raise

    def create(self, c, a):
        c.apigateway.put_integration(**_opt({"restApiId": a.get("rest_api_id"), "resourceId": a.get("resource_id"),
                                             "httpMethod": a.get("http_method"), "type": a.get("type")},
                                            integrationHttpMethod=a.get("integration_http_method"), uri=a.get("uri"),
                                            passthroughBehavior=a.get("passthrough_behavior"),
                                            requestTemplates=a.attrs.get("request_templates") or None,
                                            timeoutInMillis=a.get("timeout_milliseconds")))
        return self._out(a)

    def delete(self, c, out):
        c.apigateway.delete_integration(restApiId=out["rest_api_id"], resourceId=out["resource_id"], httpMethod=out["http_method"])


@applier("aws_api_gateway_deployment")
class ApiDeployment:
    def find(self, c, a):
        for d in c.apigateway.get_deployments(restApiId=a.get("rest_api_id")).get("items", []):
            if (d.get("description") or None) == (a.get("description") or None) and _claim(c, d["id"]):
                return {"id": d["id"], "rest_api_id": a.get("rest_api_id")}
        return None

    def create(self, c, a):
        d = c.apigateway.create_deployment(**_opt({"restApiId": a.get("rest_api_id")}, description=a.get("description")))
        c.claimed.add(d["id"])
        return {"id": d["id"], "rest_api_id": a.get("rest_api_id")}

    def delete(self, c, out):
        c.apigateway.delete_deployment(restApiId=out["rest_api_id"], deploymentId=out["id"])


@applier("aws_api_gateway_stage")
class ApiStage:
    def _out(self, c, a):
        return {"id": f"ags-{a.get('rest_api_id')}-{a.get('stage_name')}", "rest_api_id": a.get("rest_api_id"), "stage_name": a.get("stage_name"),
                "invoke_url": f"https://{a.get('rest_api_id')}.execute-api.{c.region}.amazonaws.com/{a.get('stage_name')}",
                "execution_arn": f"arn:aws:execute-api:{c.region}:{c.account}:{a.get('rest_api_id')}/{a.get('stage_name')}"}

    def find(self, c, a):
        try:
            c.apigateway.get_stage(restApiId=a.get("rest_api_id"), stageName=a.get("stage_name"))
            return self._out(c, a)
        except Exception as exc:  # noqa: BLE001
            if _missing(exc, "NotFoundException"):
                return None
            raise

    def create(self, c, a):
        c.apigateway.create_stage(**_opt({"restApiId": a.get("rest_api_id"), "stageName": a.get("stage_name"),
                                          "deploymentId": a.get("deployment_id")}, description=a.get("description"),
                                         variables=a.attrs.get("variables") or None, tracingEnabled=a.attrs.get("xray_tracing_enabled"),
                                         tags=a.tags or None))
        return self._out(c, a)

    def delete(self, c, out):
        c.apigateway.delete_stage(restApiId=out["rest_api_id"], stageName=out["stage_name"])


# -------------------------------------------------------------------------------------------------------------------- RDS
@applier("aws_db_subnet_group")
class DbSubnetGroup:
    def find(self, c, a):
        try:
            g = c.rds.describe_db_subnet_groups(DBSubnetGroupName=a.get("name"))["DBSubnetGroups"][0]
        except Exception as exc:  # noqa: BLE001
            if _missing(exc, "DBSubnetGroupNotFoundFault", "DBSubnetGroupNotFound"):
                return None
            raise
        return {"id": g["DBSubnetGroupName"], "name": g["DBSubnetGroupName"], "arn": g.get("DBSubnetGroupArn", "")}

    def create(self, c, a):
        g = c.rds.create_db_subnet_group(**_opt({"DBSubnetGroupName": a.get("name"), "SubnetIds": list(a.get("subnet_ids", [])),
                                                 "DBSubnetGroupDescription": a.get("description") or "Managed by Terraform"}))["DBSubnetGroup"]
        return {"id": g["DBSubnetGroupName"], "name": g["DBSubnetGroupName"], "arn": g.get("DBSubnetGroupArn", "")}

    def delete(self, c, out):
        c.rds.delete_db_subnet_group(DBSubnetGroupName=out["name"])


@applier("aws_db_instance")
class DbInstance:
    def _out(self, d):
        ep = d.get("Endpoint") or {}
        return {"id": d["DBInstanceIdentifier"], "identifier": d["DBInstanceIdentifier"], "arn": d.get("DBInstanceArn", ""),
                "address": ep.get("Address", ""), "port": ep.get("Port", 0), "endpoint": f"{ep.get('Address', '')}:{ep.get('Port', '')}"}

    def find(self, c, a):
        try:
            return self._out(c.rds.describe_db_instances(DBInstanceIdentifier=a.get("identifier"))["DBInstances"][0])
        except Exception as exc:  # noqa: BLE001
            if _missing(exc, "DBInstanceNotFound", "DBInstanceNotFoundFault"):
                return None
            raise

    def create(self, c, a):
        kw = _opt({"DBInstanceIdentifier": a.get("identifier")}, Engine=a.get("engine"), EngineVersion=a.get("engine_version"),
                  DBInstanceClass=a.get("instance_class"), AllocatedStorage=a.get("allocated_storage"), StorageType=a.get("storage_type"),
                  MasterUsername=a.get("username"), MasterUserPassword=a.get("password"), DBName=a.get("db_name"),
                  MultiAZ=a.attrs.get("multi_az"), PubliclyAccessible=a.attrs.get("publicly_accessible"),
                  StorageEncrypted=a.attrs.get("storage_encrypted"), BackupRetentionPeriod=a.attrs.get("backup_retention_period"),
                  DBSubnetGroupName=a.get("db_subnet_group_name"), VpcSecurityGroupIds=list(a.get("vpc_security_group_ids") or []) or None,
                  Tags=_tag_list(a.tags) or None)
        if kw.get("AllocatedStorage") is not None:
            kw["AllocatedStorage"] = int(kw["AllocatedStorage"])
        return self._out(c.rds.create_db_instance(**kw)["DBInstance"])

    def delete(self, c, out):
        c.rds.delete_db_instance(DBInstanceIdentifier=out["identifier"], SkipFinalSnapshot=True)


# ------------------------------------------------------------------------------------------------------------------------ S3
def _bucket_arn(n):
    return f"arn:aws:s3:::{n}"


@applier("aws_s3_bucket")
class S3Bucket:
    def _out(self, n):
        return {"id": n, "bucket": n, "arn": _bucket_arn(n), "bucket_domain_name": f"{n}.s3.amazonaws.com"}

    def find(self, c, a):
        return self._out(a.get("bucket")) if any(b["Name"] == a.get("bucket") for b in c.s3.list_buckets().get("Buckets", [])) else None

    def create(self, c, a):
        kw = {"Bucket": a.get("bucket")}
        if c.region != "us-east-1":
            kw["CreateBucketConfiguration"] = {"LocationConstraint": c.region}
        c.s3.create_bucket(**kw)
        if a.tags:
            c.s3.put_bucket_tagging(Bucket=a.get("bucket"), Tagging={"TagSet": _tag_list(a.tags)})
        return self._out(a.get("bucket"))

    def delete(self, c, out):
        c.s3.delete_bucket(Bucket=out["bucket"])


@applier("aws_s3_bucket_versioning")
class S3Versioning:
    def _want(self, a):
        return next((b[1].get("status") for b in a.blocks_of("versioning_configuration")), "Enabled")

    def find(self, c, a):
        cur = c.s3.get_bucket_versioning(Bucket=a.get("bucket")).get("Status")
        return {"id": a.get("bucket"), "bucket": a.get("bucket")} if cur == self._want(a) else None

    def create(self, c, a):
        c.s3.put_bucket_versioning(Bucket=a.get("bucket"), VersioningConfiguration={"Status": self._want(a)})
        return {"id": a.get("bucket"), "bucket": a.get("bucket")}

    def delete(self, c, out):
        pass  # versioning can only be suspended, and goes away with its bucket


@applier("aws_s3_bucket_public_access_block")
class S3PublicAccessBlock:
    KEYS = (("block_public_acls", "BlockPublicAcls"), ("block_public_policy", "BlockPublicPolicy"),
            ("ignore_public_acls", "IgnorePublicAcls"), ("restrict_public_buckets", "RestrictPublicBuckets"))

    def find(self, c, a):
        try:
            cur = c.s3.get_public_access_block(Bucket=a.get("bucket"))["PublicAccessBlockConfiguration"]
        except Exception as exc:  # noqa: BLE001
            if _missing(exc):
                return None
            raise
        return {"id": a.get("bucket"), "bucket": a.get("bucket")} if all(bool(cur.get(aws)) == bool(a.attrs.get(tf)) for tf, aws in self.KEYS) else None

    def create(self, c, a):
        c.s3.put_public_access_block(Bucket=a.get("bucket"), PublicAccessBlockConfiguration={aws: bool(a.attrs.get(tf)) for tf, aws in self.KEYS})
        return {"id": a.get("bucket"), "bucket": a.get("bucket")}

    def delete(self, c, out):
        c.s3.delete_public_access_block(Bucket=out["bucket"])


@applier("aws_s3_bucket_server_side_encryption_configuration")
class S3Encryption:
    def _rule(self, a):
        rules = []
        for _t, _b, kids in a.blocks_of("rule"):
            for t2, d, _k2 in kids:
                if t2 == "apply_server_side_encryption_by_default":
                    rules.append({"ApplyServerSideEncryptionByDefault": _opt({"SSEAlgorithm": d.get("sse_algorithm")},
                                                                             KMSMasterKeyID=d.get("kms_master_key_id"))})
        return rules

    def find(self, c, a):
        try:
            cur = c.s3.get_bucket_encryption(Bucket=a.get("bucket"))["ServerSideEncryptionConfiguration"]["Rules"]
        except Exception as exc:  # noqa: BLE001
            if _missing(exc):
                return None
            raise
        norm = lambda rs: [(r["ApplyServerSideEncryptionByDefault"].get("SSEAlgorithm"), r["ApplyServerSideEncryptionByDefault"].get("KMSMasterKeyID")) for r in rs]  # noqa: E731
        return {"id": a.get("bucket"), "bucket": a.get("bucket")} if norm(cur) == norm(self._rule(a)) else None

    def create(self, c, a):
        c.s3.put_bucket_encryption(Bucket=a.get("bucket"), ServerSideEncryptionConfiguration={"Rules": self._rule(a)})
        return {"id": a.get("bucket"), "bucket": a.get("bucket")}

    def delete(self, c, out):
        c.s3.delete_bucket_encryption(Bucket=out["bucket"])


@applier("aws_s3_bucket_policy")
class S3Policy:
    def find(self, c, a):
        try:
            cur = json.loads(c.s3.get_bucket_policy(Bucket=a.get("bucket"))["Policy"])
        except Exception as exc:  # noqa: BLE001
            if _missing(exc):
                return None
            raise
        return {"id": a.get("bucket"), "bucket": a.get("bucket")} if cur == _doc(a.get("policy")) else None

    def create(self, c, a):
        c.s3.put_bucket_policy(Bucket=a.get("bucket"), Policy=a.get("policy"))
        return {"id": a.get("bucket"), "bucket": a.get("bucket")}

    def delete(self, c, out):
        c.s3.delete_bucket_policy(Bucket=out["bucket"])


# ---------------------------------------------------------------------------------------------------------- logs / secrets
@applier("aws_cloudwatch_log_group")
class LogGroup:
    def _out(self, c, n):
        return {"id": n, "name": n, "arn": f"arn:aws:logs:{c.region}:{c.account}:log-group:{n}"}

    def find(self, c, a):
        n = a.get("name")
        return self._out(c, n) if any(g["logGroupName"] == n for g in c.logs.describe_log_groups(logGroupNamePrefix=n).get("logGroups", [])) else None

    def create(self, c, a):
        c.logs.create_log_group(**_opt({"logGroupName": a.get("name")}, tags=a.tags or None))
        if a.get("retention_in_days"):
            c.logs.put_retention_policy(logGroupName=a.get("name"), retentionInDays=int(a.get("retention_in_days")))
        return self._out(c, a.get("name"))

    def delete(self, c, out):
        c.logs.delete_log_group(logGroupName=out["name"])


@applier("aws_secretsmanager_secret")
class Secret:
    def _out(self, s):
        return {"id": s["ARN"], "arn": s["ARN"], "name": s["Name"]}

    def find(self, c, a):
        try:
            return self._out(c.secretsmanager.describe_secret(SecretId=a.get("name")))
        except Exception as exc:  # noqa: BLE001
            if _missing(exc, "ResourceNotFoundException"):
                return None
            raise

    def create(self, c, a):
        r = c.secretsmanager.create_secret(**_opt({"Name": a.get("name")}, Description=a.get("description"), Tags=_tag_list(a.tags) or None))
        return {"id": r["ARN"], "arn": r["ARN"], "name": r["Name"]}

    def delete(self, c, out):
        c.secretsmanager.delete_secret(SecretId=out["id"], ForceDeleteWithoutRecovery=True)


@applier("aws_secretsmanager_secret_version")
class SecretVersion:
    def find(self, c, a):
        try:
            cur = c.secretsmanager.get_secret_value(SecretId=a.get("secret_id"))
        except Exception as exc:  # noqa: BLE001
            if _missing(exc, "ResourceNotFoundException"):
                return None
            raise
        return {"id": f"{a.get('secret_id')}|{cur.get('VersionId', '')}", "secret_id": a.get("secret_id"), "version_id": cur.get("VersionId", "")} \
            if cur.get("SecretString") == a.get("secret_string") else None

    def create(self, c, a):
        r = c.secretsmanager.put_secret_value(SecretId=a.get("secret_id"), SecretString=a.get("secret_string", ""))
        return {"id": f"{a.get('secret_id')}|{r.get('VersionId', '')}", "secret_id": a.get("secret_id"), "version_id": r.get("VersionId", "")}

    def delete(self, c, out):
        pass  # the value goes away with its secret
