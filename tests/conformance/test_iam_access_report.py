"""IAM GenerateOrganizationsAccessReport / GetOrganizationsAccessReport (AWS-07 service access report): derived from the
recorded native-wire activity of the management account's users, scoped to an org entity and (optionally) an SCP.

    PYTHONPATH=. python3 tests/conformance/test_iam_access_report.py
"""
import json
import re

from core import iam_core as ic, organizations_core as oc
from core.iam_store import InMemoryIamStore

T = "AWSOrganizationsV20161128."


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def main():
    st = InMemoryIamStore()
    def org(a, **p):
        r = oc.dispatch(st, T + a, p)
        b = r.body
        return r.status, (json.loads(b) if isinstance(b, (str, bytes)) else b)
    iam = lambda a, **p: ic.dispatch(st, dict(p, Action=a))
    v = lambda x, t: (re.search(rf"<{t}>(.*?)</{t}>", x, re.S) or [None, ""])[1]

    s, b = org("CreateOrganization", FeatureSet="ALL")
    oid = b["Organization"]["Id"]
    root = org("ListRoots")[1]["Roots"][0]["Id"]
    mgmt = b["Organization"]["MasterAccountId"]
    ou = org("CreateOrganizationalUnit", ParentId=root, Name="eng")[1]["OrganizationalUnit"]["Id"]
    iam("CreateUser", UserName="alice")
    ic.record_activity(st, "alice", "s3", "GetObject")
    ic.record_activity(st, "alice", "dynamodb", "PutItem")
    ic.record_activity(st, "alice", "ec2", "RunInstances")
    ro = json.dumps({"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": ["s3:*", "dynamodb:*"], "Resource": "*"}]})
    pid = org("CreatePolicy", Name="data-only", Description="d", Type="SERVICE_CONTROL_POLICY", Content=ro)[1]["Policy"]["PolicySummary"]["Id"]

    def report(path, policy=None):
        p = {"EntityPath": path}
        if policy:
            p["OrganizationsPolicyId"] = policy
        g = iam("GenerateOrganizationsAccessReport", **p)
        assert g.status == 200, g.body
        r = iam("GetOrganizationsAccessReport", JobId=v(g.body, "JobId"))
        assert r.status == 200, r.body
        return r.body

    full = report(f"{oid}/{root}")
    _check("root report completes", v(full, "JobStatus") == "COMPLETED")
    ns = re.findall(r"<ServiceNamespace>(.*?)</ServiceNamespace>", full)
    _check("accessed services reported from real activity", ns == ["dynamodb", "ec2", "s3"])
    _check("not-accessed count excludes accessed ones", int(v(full, "NumberOfServicesNotAccessed")) == int(v(full, "NumberOfServicesAccessible")) - 3)
    scp = report(f"{oid}/{root}", pid)
    _check("SCP scoping drops services the SCP does not allow", re.findall(r"<ServiceNamespace>(.*?)</ServiceNamespace>", scp) == ["dynamodb", "s3"])
    _check("SCP accessible count is the allowed services", int(v(scp, "NumberOfServicesAccessible")) == 2)
    empty = report(f"{oid}/{root}/{ou}")
    _check("empty OU (no accounts) reports no activity", "<ServiceNamespace>" not in empty)
    acct = report(f"{oid}/{root}/{mgmt}")
    _check("management account path reports its activity", "<ServiceNamespace>s3</ServiceNamespace>" in acct)
    _check("bad path rejected", iam("GenerateOrganizationsAccessReport", EntityPath="nonsense").status == 400)
    _check("unknown entity 404", iam("GenerateOrganizationsAccessReport", EntityPath=f"{oid}/{root}/ou-zzzz-zzzzzzzz").status == 404)
    _check("unknown policy 404", iam("GenerateOrganizationsAccessReport", EntityPath=f"{oid}/{root}", OrganizationsPolicyId="p-nope").status == 404)
    _check("bad job 404", iam("GetOrganizationsAccessReport", JobId="x").status == 404)
    print("iam access report conformance: all checks passed")


if __name__ == "__main__":
    main()
