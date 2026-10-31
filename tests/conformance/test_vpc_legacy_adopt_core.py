"""Upgrade path: the pre-v4 offline VPC store (server.py `vpc_state`, exact record shapes of its
create handlers) is adopted into core/vpc_core once per space, IDs preserved, idempotent —
host + Pyodide (pure dict code).

    PYTHONPATH=. python3 tests/conformance/test_vpc_legacy_adopt_core.py
"""
import copy
import re
import types

try:
    from core import vpc_core as vpc
except ImportError:  # pragma: no cover - Pyodide flat layout
    import vpc_core as vpc  # type: ignore


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def legacy_state():
    """Records exactly as the pre-v4 handlers (api_vpc_create & co.) write them."""
    t = "2026-01-01T00:00:00Z"
    return {
        "vpcs": {"vpc-legacy01": {"vpc_id": "vpc-legacy01", "name": "prod", "cidr_block": "10.60.0.0/16", "tenancy": "default",
                                  "tags": [{"key": "Name", "value": "prod"}, {"key": "env", "value": "p"}], "created": t,
                                  "state": "available", "dhcp_options_id": "dopt-legacy01", "main_route_table_id": "rtb-main01",
                                  "default_security_group_id": "sg-default01", "internet_gateway_id": "igw-legacy01"}},
        "route_tables": {
            "rtb-main01": {"route_table_id": "rtb-main01", "vpc_id": "vpc-legacy01", "name": "prod-main", "is_main": True,
                           "routes": [{"destination": "10.60.0.0/16", "target_type": "local", "target_id": "vpc-legacy01"}],
                           "subnet_ids": ["subnet-priv01"], "tags": []},
            "rtb-pub01": {"route_table_id": "rtb-pub01", "vpc_id": "vpc-legacy01", "name": "pub", "is_main": False,
                          "routes": [{"destination": "10.60.0.0/16", "target_type": "local", "target_id": "vpc-legacy01"},
                                     {"destination": "0.0.0.0/0", "target_type": "internet-gateway", "target_id": "igw-legacy01"}],
                          "subnet_ids": ["subnet-pub01"], "tags": [{"key": "Name", "value": "public"}]}},
        "subnets": {
            "subnet-pub01": {"subnet_id": "subnet-pub01", "vpc_id": "vpc-legacy01", "cidr_block": "10.60.1.0/24",
                             "availability_zone": "us-east-1a", "name": "pub", "route_table_id": "rtb-pub01", "tags": []},
            "subnet-priv01": {"subnet_id": "subnet-priv01", "vpc_id": "vpc-legacy01", "cidr_block": "10.60.2.0/24",
                              "availability_zone": "us-east-1b", "name": "priv", "route_table_id": "rtb-main01",
                              "tags": [{"key": "tier", "value": "db"}]}},
        "security_groups": {
            "sg-default01": {"security_group_id": "sg-default01", "vpc_id": "vpc-legacy01", "group_name": "default",
                             "description": "default VPC security group", "ingress": [], "is_default": True, "tags": [],
                             "egress": [{"protocol": "-1", "from_port": 0, "to_port": 0, "cidr": "0.0.0.0/0", "source_sg": ""}]},
            "sg-web01": {"security_group_id": "sg-web01", "vpc_id": "vpc-legacy01", "group_name": "web", "description": "web",
                         "ingress": [{"protocol": "tcp", "from_port": 22, "to_port": 22, "cidr": "10.60.0.0/16", "source_sg": ""}],
                         "egress": [{"protocol": "-1", "from_port": 0, "to_port": 0, "cidr": "0.0.0.0/0", "source_sg": ""}],
                         "is_default": False, "tags": []},
            "sg-db01": {"security_group_id": "sg-db01", "vpc_id": "vpc-legacy01", "group_name": "db", "description": "db",
                        # pre-v4 stored its 0.0.0.0/0 default next to a source SG
                        "ingress": [{"protocol": "tcp", "from_port": 5432, "to_port": 5432, "cidr": "0.0.0.0/0", "source_sg": "sg-web01"}],
                        "egress": [], "is_default": False, "tags": []}},
        "internet_gateways": {"igw-legacy01": {"internet_gateway_id": "igw-legacy01", "name": "igw", "attached_vpc_id": "vpc-legacy01",
                                               "tags": [{"key": "Name", "value": "main-igw"}]}},
    }


def run():
    legacy = legacy_state()
    ss = {"vpc": legacy}
    m = vpc.adopt_legacy_slot(ss)
    s = types.SimpleNamespace(_vpc_model=m)

    def call(p, status=200):
        r = vpc.dispatch(s, p)
        if r.status != status:
            raise AssertionError((p.get("Action"), r.status, r.body))
        return r.body

    _check("adoption counts", m["_adopted_counts"] == {"vpcs": 1, "subnets": 2, "security_groups": 3, "route_tables": 2,
                                                       "routes": 1, "internet_gateways": 1})
    v = call({"Action": "DescribeVpcs"})
    _check("VPC id + CIDR preserved", "<vpcId>vpc-legacy01</vpcId>" in v and "<cidrBlock>10.60.0.0/16</cidrBlock>" in v)
    _check("VPC tags preserved", "<key>env</key>" in v and "<value>prod</value>" in v)
    sn = call({"Action": "DescribeSubnets"})
    _check("subnets keep ids / cidr / az / route table", all(x in sn for x in (
        "<subnetId>subnet-pub01</subnetId>", "<cidrBlock>10.60.2.0/24</cidrBlock>", "us-east-1b",
        "<routeTableId>rtb-pub01</routeTableId>")))
    rt = call({"Action": "DescribeRouteTables"})
    _check("route tables keep ids, main flag, routes and associations",
           "rtb-main01" in rt and "<gatewayId>igw-legacy01</gatewayId>" in rt and "<subnetId>subnet-pub01</subnetId>" in rt
           and "rtbassoc-main-vpc-legacy01" in rt)
    sg = call({"Action": "DescribeSecurityGroups"})
    _check("SGs keep ids / names / rules", all(x in sg for x in ("sg-web01", "<groupName>db</groupName>", "<fromPort>22</fromPort>",
                                                                 "<cidrIp>10.60.0.0/16</cidrIp>", "<groupId>sg-web01</groupId>")))
    _check("SG-referencing rule did NOT become 0.0.0.0/0",
           m["sgs"]["sg-db01"]["ingress"][0]["cidrs"] == [] and m["sgs"]["sg-db01"]["ingress"][0]["sgs"] == ["sg-web01"])
    ig = call({"Action": "DescribeInternetGateways"})
    _check("IGW attachment preserved", "igw-legacy01" in ig and "vpc-legacy01" in ig and m["vpcs"]["vpc-legacy01"]["igw"] == "igw-legacy01")
    _check("default SG recognised as the VPC default", m["sgs"]["sg-default01"]["is_default"])

    # create / modify keep working on adopted objects
    new_sn = re.search(r"<subnetId>(.*?)</", call({"Action": "CreateSubnet", "VpcId": "vpc-legacy01", "CidrBlock": "10.60.3.0/24"})).group(1)
    _check("new subnet in an adopted VPC uses the adopted main route table", m["subnets"][new_sn]["route_table"] == "rtb-main01")
    call({"Action": "AuthorizeSecurityGroupIngress", "GroupId": "sg-web01", "IpPermissions.1.IpProtocol": "tcp",
          "IpPermissions.1.FromPort": "443", "IpPermissions.1.ToPort": "443", "IpPermissions.1.IpRanges.1.CidrIp": "0.0.0.0/0"})
    call({"Action": "CreateRoute", "RouteTableId": "rtb-main01", "DestinationCidrBlock": "192.168.0.0/16", "GatewayId": "igw-legacy01"})
    acl = re.search(r"<networkAclId>(.*?)</", call({"Action": "CreateNetworkAcl", "VpcId": "vpc-legacy01"})).group(1)
    call({"Action": "AssociateNetworkAcl", "NetworkAclId": acl, "SubnetId": new_sn})
    i = re.search(r"<instanceId>(.*?)</", call({"Action": "RunInstances", "SubnetId": "subnet-pub01", "SecurityGroupId.1": "sg-web01",
                                                "MinCount": "1", "MaxCount": "1"})).group(1)
    _check("launch into an adopted subnet gets an in-subnet IP", m["instances"][i]["private_ip"].startswith("10.60.1."))
    r = vpc.analyze_reachability(s, {"instance_id": i}, {"ip": "10.60.2.9", "security_group_ids": ["sg-db01"]}, 5432)
    _check("netsim evaluates adopted SG references (web → db:5432)", r["reachable"])
    _check("RouteAlreadyExists still enforced on adopted tables",
           "RouteAlreadyExists" in call({"Action": "CreateRoute", "RouteTableId": "rtb-pub01", "DestinationCidrBlock": "0.0.0.0/0",
                                         "GatewayId": "igw-legacy01"}, 400))

    # idempotency
    before = copy.deepcopy(m)
    _check("slot adoption runs once (marker)", vpc.adopt_legacy_slot(ss) is m and m == before)
    m2, counts = vpc.adopt_legacy(m, legacy)               # forced re-run, ignoring the marker
    _check("forced re-adopt adds nothing", sum(counts.values()) == 0 and len(m2["route_tables"]) == len(before["route_tables"])
           and len(m2["nacls"]) == len(before["nacls"]))
    _check("deleted-after-upgrade objects are not resurrected by the marker path",
           vpc.adopt_legacy_slot({"vpc": legacy, "ec2_vpc_core": {**copy.deepcopy(before), "vpcs": {}}})["vpcs"] == {})
    mirror = {"vpcs": {"vpc-core9": {"vpc_id": "vpc-core9", "cidr_block": "10.9.0.0/16", "_engine": "vpc_core"}}}
    _check("our own mirror records are never adopted", vpc.adopt_legacy(None, mirror)[1]["vpcs"] == 0)
    _check("empty legacy store: no model invented", vpc.adopt_legacy_slot({"vpc": {"vpcs": {}}}) is None)
    print("\nVPC legacy adoption conformance: ALL GREEN")


if __name__ == "__main__":
    run()
    print("RESULT: PASS")
