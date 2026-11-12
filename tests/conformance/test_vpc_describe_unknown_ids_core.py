"""VPC core: describing an unknown ID is an error with the real AWS code, never an empty list.

Real EC2 answers DescribeVpcs/Subnets/RouteTables/InternetGateways/NatGateways/VpcEndpoints with a
`<Kind>.NotFound` error when any requested id does not exist (boto3 callers rely on the exception, e.g.
"describe after delete must raise InvalidRouteTableID.NotFound").
"""
import re
import types

try:
    from core import vpc_core as v
except ImportError:  # pragma: no cover
    import vpc_core as v  # type: ignore


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"[PASS] {name}")


def run():
    s = types.SimpleNamespace()
    call = lambda **p: v.dispatch(s, p)  # noqa: E731
    body = lambda r: r.body.decode() if isinstance(r.body, bytes) else r.body  # noqa: E731
    vpc = re.search(r"<vpcId>(vpc-\w+)</vpcId>", body(call(Action="CreateVpc", CidrBlock="10.9.0.0/16"))).group(1)
    rt = re.search(r"<routeTableId>(rtb-\w+)</routeTableId>", body(call(Action="CreateRouteTable", VpcId=vpc))).group(1)

    cases = [
        ("DescribeVpcs", "VpcId.1", "vpc-00000000deadbeef", "InvalidVpcID.NotFound"),
        ("DescribeSubnets", "SubnetId.1", "subnet-00000000deadbeef", "InvalidSubnetID.NotFound"),
        ("DescribeRouteTables", "RouteTableId.1", "rtb-00000000deadbeef", "InvalidRouteTableID.NotFound"),
        ("DescribeInternetGateways", "InternetGatewayId.1", "igw-00000000deadbeef", "InvalidInternetGatewayID.NotFound"),
        ("DescribeNatGateways", "NatGatewayId.1", "nat-00000000deadbeef", "NatGatewayNotFound"),
        ("DescribeVpcEndpoints", "VpcEndpointId.1", "vpce-00000000deadbeef", "InvalidVpcEndpointId.NotFound"),
        ("DescribeInstances", "InstanceId.1", "i-00000000deadbeef", "InvalidInstanceID.NotFound"),
        ("DescribeImages", "ImageId.1", "ami-00000000deadbeef", "InvalidAMIID.NotFound"),
        ("DescribeVolumes", "VolumeId.1", "vol-00000000deadbeef", "InvalidVolume.NotFound"),
        ("DescribeSnapshots", "SnapshotId.1", "snap-00000000deadbeef", "InvalidSnapshot.NotFound"),
        ("DescribeKeyPairs", "KeyName.1", "no-such-key", "InvalidKeyPair.NotFound"),
        ("DescribeAddresses", "AllocationId.1", "eipalloc-00000000deadbeef", "InvalidAllocationID.NotFound"),
        ("DescribeAddresses", "PublicIp.1", "203.0.113.250", "InvalidAddress.NotFound"),
    ]
    for action, key, bogus, code in cases:
        r = call(Action=action, **{key: bogus})
        _check(f"{action} unknown id -> {code}", r.status >= 400 and code in body(r))

    r = call(Action="DescribeVpcs", **{"VpcId.1": vpc})
    _check("DescribeVpcs known id still works", r.status == 200 and vpc in body(r))
    r = call(Action="DescribeRouteTables", **{"RouteTableId.1": rt})
    _check("DescribeRouteTables known id still works", r.status == 200 and rt in body(r))
    r = call(Action="DescribeRouteTables", **{"RouteTableId.1": rt, "RouteTableId.2": "rtb-00000000deadbeef"})
    _check("one unknown id in a list fails the whole call", r.status >= 400 and "InvalidRouteTableID.NotFound" in body(r))
    _check("DescribeRouteTables with no ids still lists", call(Action="DescribeRouteTables").status == 200)
    call(Action="DeleteRouteTable", RouteTableId=rt)
    r = call(Action="DescribeRouteTables", **{"RouteTableId.1": rt})
    _check("describe after DeleteRouteTable -> InvalidRouteTableID.NotFound", r.status >= 400 and "InvalidRouteTableID.NotFound" in body(r))
    print("VPC UNKNOWN IDS OK")


if __name__ == "__main__":
    run()
