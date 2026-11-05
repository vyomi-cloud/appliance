"""IAM Role manager (Vyomi-only ListRoleInventory / DeleteUnusedRoles + RoleLastUsed) conformance.
Run: PYTHONPATH=. python tests/conformance/test_iam_role_manager.py"""
import json
import re
from datetime import datetime, timedelta, timezone

try:
    from core.iam_store import InMemoryIamStore
    from core import iam_core as iam
except ImportError:  # pragma: no cover
    from iam_store import InMemoryIamStore  # type: ignore
    import iam_core as iam  # type: ignore


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def call(st, **p):
    r = iam.dispatch(st, p)
    return r.status, r.body


TRUST = json.dumps({"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"}, "Action": "sts:AssumeRole"}]})
POL = json.dumps({"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "s3:*", "Resource": "*"}]})


def member(xml, name):
    for m in re.findall(r"<member>(.*?)</member>(?=<member>|</Roles>)", xml, re.S):
        if f"<RoleName>{name}</RoleName>" in m:
            return m
    raise AssertionError("no " + name)


def main():
    st = InMemoryIamStore()
    for n in ("old-unused", "fresh", "in-profile", "has-fn", "active"):
        s, b = call(st, Action="CreateRole", RoleName=n, AssumeRolePolicyDocument=TRUST)
        _check(f"create {n}", s == 200 and "<RoleLastUsed/>" in b)
    s, b = call(st, Action="CreatePolicy", PolicyName="p1", PolicyDocument=POL)
    parn = re.search(r"<Arn>(.*?)</Arn>", b).group(1)
    call(st, Action="AttachRolePolicy", RoleName="old-unused", PolicyArn=parn)
    call(st, Action="PutRolePolicy", RoleName="old-unused", PolicyName="inl", PolicyDocument=POL)
    # age two roles beyond the window
    old = (datetime.now(timezone.utc) - timedelta(days=200)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    for n in ("old-unused", "in-profile", "has-fn"):
        st.roles[n]["created"] = old
    call(st, Action="CreateInstanceProfile", InstanceProfileName="ip1")
    call(st, Action="AddRoleToInstanceProfile", InstanceProfileName="ip1", RoleName="in-profile")
    st.role_usage_probe = lambda r: [{"Type": "LambdaFunction", "Id": "fn1"}] if r["role_name"] == "has-fn" else []
    _check("record_role_use unknown role", iam.record_role_use(st, "arn:aws:iam::1:role/nope", "lambda") is False)
    _check("record_role_use", iam.record_role_use(st, st.roles["active"]["arn"], "lambda", "Invoke"))
    s, b = call(st, Action="GetRole", RoleName="active")
    _check("GetRole RoleLastUsed", "<RoleLastUsed><LastUsedDate>" in b)

    s, b = call(st, Action="ListRoleInventory")
    _check("inventory 200", s == 200)
    m = member(b, "old-unused")
    _check("never-used old role flagged", "<Status>NeverUsed</Status>" in m and "<Deletable>true</Deletable>" in m)
    _check("policy counts", "<AttachedPolicyCount>1</AttachedPolicyCount>" in m and "<InlinePolicyCount>1</InlinePolicyCount>" in m)
    _check("trust principals", "<member>Service:lambda.amazonaws.com</member>" in m)
    _check("fresh is New+protected", "<Status>New</Status>" in member(b, "fresh") and "<Deletable>false</Deletable>" in member(b, "fresh"))
    _check("active protected", "<Status>Active</Status>" in member(b, "active") and "<LastUsedService>lambda</LastUsedService>" in member(b, "active"))
    _check("instance profile dependency", "InstanceProfile</Type><Id>ip1" in member(b, "in-profile") and "<Deletable>false</Deletable>" in member(b, "in-profile"))
    _check("probe dependency", "LambdaFunction</Type><Id>fn1" in member(b, "has-fn"))
    s, b = call(st, Action="ListRoleInventory", UnusedDays="0")
    _check("UnusedDays validated", s == 400 and "ValidationError" in b)
    # Active role becomes Unused once its last use ages out
    st.roles["active"]["role_last_used"]["time"] = old
    s, b = call(st, Action="ListRoleInventory")
    _check("aged last-used -> Unused", "<Status>Unused</Status>" in member(b, "active"))

    s, b = call(st, Action="DeleteUnusedRoles", **{"RoleNames.member.1": "old-unused", "RoleNames.member.2": "fresh",
                                                    "RoleNames.member.3": "in-profile", "RoleNames.member.4": "ghost"})
    _check("delete results", s == 200 and "<Result>Deleted</Result><RoleName>old-unused" in b and "<Result>NotFound</Result><RoleName>ghost" in b)
    _check("blocked roles skipped", b.count("<Result>Skipped</Result>") == 2 and "newer than the unused-days window" in b and "referenced by InstanceProfile ip1" in b)
    _check("deleted role gone, others kept", "old-unused" not in st.roles and "fresh" in st.roles and "in-profile" in st.roles)
    s, b = call(st, Action="DeleteUnusedRoles")
    _check("RoleNames required", s == 400)
    # service-linked roles are never deleted
    call(st, Action="CreateRole", RoleName="slr", Path="/aws-service-role/x.amazonaws.com/", AssumeRolePolicyDocument=TRUST)
    st.roles["slr"]["created"] = old
    s, b = call(st, Action="DeleteUnusedRoles", **{"RoleNames.member.1": "slr"})
    _check("service-linked role refused", "service-linked role" in b and "slr" in st.roles)
    # trust-policy edit + attach/detach are the stock IAM actions
    s, b = call(st, Action="UpdateAssumeRolePolicy", RoleName="fresh", PolicyDocument=TRUST.replace("lambda", "ec2"))
    _check("trust edit", s == 200 and "ec2.amazonaws.com" in json.dumps(st.roles["fresh"]["assume_role_policy_document"]))
    print("iam role manager: ALL PASS")


if __name__ == "__main__":
    main()
