"""VPC core: network ACL lifecycle (Create/Describe/Delete + routing set) — the engine
behind boto3 ec2.create_network_acl / describe_network_acls / delete_network_acl."""
import re
import types
from pathlib import Path

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
    vpc = re.search(r"<vpcId>(vpc-\w+)</vpcId>", body(call(Action="CreateVpc", CidrBlock="10.5.0.0/16"))).group(1)
    acl = re.search(r"<networkAclId>(acl-\w+)</networkAclId>", body(call(Action="CreateNetworkAcl", VpcId=vpc))).group(1)
    call(Action="CreateNetworkAclEntry", NetworkAclId=acl, RuleNumber="100", Protocol="6", RuleAction="allow", CidrBlock="10.0.0.0/8")
    d = body(call(Action="DescribeNetworkAcls"))
    _check("DescribeNetworkAcls lists the ACL with vpc + entry", acl in d and vpc in d and "<ruleNumber>100</ruleNumber>" in d)
    _check("DescribeNetworkAcls filters by id", call(Action="DescribeNetworkAcls", **{"NetworkAclId.1": "acl-nope"}).status >= 400)
    r = call(Action="DeleteNetworkAcl", NetworkAclId=acl)
    _check("DeleteNetworkAcl ok", r.status == 200)
    _check("DeleteNetworkAcl removes it", acl not in body(call(Action="DescribeNetworkAcls")))
    r = call(Action="DeleteNetworkAcl", NetworkAclId=acl)
    _check("DeleteNetworkAcl again → NotFound", r.status >= 400 and "InvalidNetworkAclID.NotFound" in body(r))
    src = (Path(__file__).resolve().parents[2] / "server.py").read_text()
    blk = src[src.index("_EC2_VPC_ACTIONS = {"):][:900]
    _check("server routes NACL actions to the VPC engine",
           all(a in blk for a in ("CreateNetworkAcl", "DescribeNetworkAcls", "DeleteNetworkAcl")))


if __name__ == "__main__":
    run()
