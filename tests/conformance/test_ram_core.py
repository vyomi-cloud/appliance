"""AWS RAM (Resource Access Manager) conformance — scoped to subnet/security-group
sharing (gap-sweep queue items aws.vpc.resource-sharing / aws.vpc.security-group-sharing).
Proves the real object model: shares, resource/principal associations, validation
(only subnet/security-group ARNs that actually exist), and the owner-side enforcement
vpc_core.py performs before deleting a shared resource. Host + Pyodide.
"""
import types

try:
    from core import ram_core as ram
    from core import vpc_core as vpc
except ImportError:  # pragma: no cover - Pyodide flat layout
    import ram_core as ram  # type: ignore
    import vpc_core as vpc  # type: ignore


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def run():
    vpc_store = types.SimpleNamespace()
    ram_store = types.SimpleNamespace()
    vpc_store.ram_store = ram_store
    ram_store.vpc_store = vpc_store

    def vcall(action, **params):
        params["Action"] = action
        r = vpc.dispatch(vpc_store, params)
        if r.status != 200:
            raise AssertionError((action, r.body))
        return r.body

    import re

    def xid(body, tag):
        return re.search(f"<{tag}>(.*?)</{tag}>", body).group(1)

    def rcall(action, body, expect_ok=True):
        r = ram.dispatch(ram_store, f"AWSRAMFrontendService.{action}", body, vpc_store=vpc_store)
        if expect_ok and r.status != 200:
            raise AssertionError((action, r.body))
        return r

    vpc_id = xid(vcall("CreateVpc", CidrBlock="10.50.0.0/16"), "vpcId")
    subnet_id = xid(vcall("CreateSubnet", VpcId=vpc_id, CidrBlock="10.50.1.0/24"), "subnetId")
    sg_id = xid(vcall("CreateSecurityGroup", VpcId=vpc_id, GroupName="ram-test"), "groupId")
    subnet_arn = f"arn:aws:ec2:us-east-1:123456789012:subnet/{subnet_id}"
    sg_arn = f"arn:aws:ec2:us-east-1:123456789012:security-group/{sg_id}"

    bad = rcall("AssociateResourceShare", {"resourceShareArn": "arn:aws:ram:us-east-1:123456789012:resource-share/rs-nope", "resourceArns": [subnet_arn]}, expect_ok=False)
    _check("associating into an unknown share fails", bad.status == 400 and bad.body["__type"] == "UnknownResourceException")

    r = rcall("CreateResourceShare", {"name": "uic-share", "resourceArns": [subnet_arn, sg_arn], "principals": ["999999999999"]})
    share_arn = r.body["resourceShare"]["resourceShareArn"]
    _check("resource share created with both associations", r.body["resourceShare"]["status"] == "ACTIVE")

    shares = rcall("GetResourceShares", {}).body["resourceShares"]
    _check("GetResourceShares lists it", any(s["resourceShareArn"] == share_arn for s in shares))

    assocs = rcall("GetResourceShareAssociations", {"associationType": "RESOURCE", "resourceShareArns": [share_arn]}).body["resourceShareAssociations"]
    _check("both resources are ASSOCIATED", {a["resourceArn"] for a in assocs} == {subnet_arn, sg_arn} and all(a["status"] == "ASSOCIATED" for a in assocs))

    bad_type = rcall("AssociateResourceShare", {"resourceShareArn": share_arn, "resourceArns": ["arn:aws:ec2:us-east-1:123456789012:instance/i-doesnotexist"]}, expect_ok=False)
    _check("sharing an unsupported resource type fails", bad_type.status == 400 and "UnknownResourceException" == bad_type.body["__type"])

    del_subnet = vpc.dispatch(vpc_store, {"Action": "DeleteSubnet", "SubnetId": subnet_id})
    _check("owner-side enforcement: cannot delete a subnet with an ACTIVE share association", del_subnet.status != 200 and "DependencyViolation" in del_subnet.body)
    del_sg = vpc.dispatch(vpc_store, {"Action": "DeleteSecurityGroup", "GroupId": sg_id})
    _check("owner-side enforcement: cannot delete a security group with an ACTIVE share association", del_sg.status != 200 and "DependencyViolation" in del_sg.body)

    rcall("DisassociateResourceShare", {"resourceShareArn": share_arn, "resourceArns": [subnet_arn, sg_arn]})
    _check("subnet now deletes once disassociated", vpc.dispatch(vpc_store, {"Action": "DeleteSubnet", "SubnetId": subnet_id}).status == 200)
    _check("security group now deletes once disassociated", vpc.dispatch(vpc_store, {"Action": "DeleteSecurityGroup", "GroupId": sg_id}).status == 200)

    rcall("DeleteResourceShare", {"resourceShareArn": share_arn})
    _check("resource share gone after delete", not any(s["resourceShareArn"] == share_arn for s in rcall("GetResourceShares", {}).body["resourceShares"]))

    print("\nAWS RAM (subnet/security-group sharing) conformance: ALL GREEN")


if __name__ == "__main__":
    run()
