"""Security Hub + GuardDuty over the real AwsWireRouter: findings derive from the simulated resources the SAME router serves.
Run: PYTHONPATH=. <venv python> tests/conformance/test_secscan_wire.py"""
import json
import sys

from core.aws_wire_router import AwsWireRouter

ok = 0


def check(c, m):
    global ok
    if not c:
        print("FAIL:", m)
        sys.exit(1)
    ok += 1


r = AwsWireRouter()


def auth(svc, akid="AKIAEXAMPLE"):
    return {"authorization": f"AWS4-HMAC-SHA256 Credential={akid}/20261104/us-east-1/{svc}/aws4_request, SignedHeaders=host, Signature=x"}


def call(svc, method, path, body=None, query=None, headers=None):
    b = json.dumps(body).encode() if isinstance(body, dict) else (body or b"")
    out = r.handle(method, path, query or {}, {**auth(svc), **(headers or {})}, b)
    try:
        return out["status"], json.loads(out["body"] or b"{}")
    except ValueError:
        return out["status"], out["body"]


st, d = call("securityhub", "POST", "/findings", {})
check(st == 401 and d["Code"] == "InvalidAccessException", f"not subscribed: {st} {d}")
check(call("securityhub", "POST", "/accounts", {})[0] == 200, "EnableSecurityHub")

# real resources through the same router: a public bucket, a world-open SSH security group, a public instance
check(r.handle("PUT", "/leaky", {}, auth("s3"), b"")["status"] == 200, "create bucket")
pol = json.dumps({"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": "*", "Action": "s3:GetObject", "Resource": "arn:aws:s3:::leaky/*"}]})
put = r.handle("PUT", "/leaky", {"policy": ""}, auth("s3"), pol.encode())
print("put policy status", put["status"])
if put["status"] >= 300:   # Block Public Access defaults may refuse a public policy, like real S3: lift it first
    r.handle("DELETE", "/leaky", {"publicAccessBlock": ""}, auth("s3"), b"")
    put = r.handle("PUT", "/leaky", {"policy": ""}, auth("s3"), pol.encode())
check(put["status"] < 300, "public policy accepted")

st, d = call("securityhub", "POST", "/findings", {"Filters": {"ResourceId": [{"Value": "arn:aws:s3:::leaky", "Comparison": "EQUALS"}]}})
ctl = {f["ProductFields"]["ControlId"] for f in d["Findings"]}
check(st == 200 and "S3.2" in ctl, f"S3.2 for the public bucket: {ctl}")
check(all(f["ProductArn"].endswith("/aws/securityhub") for f in d["Findings"] if f["ProductFields"]["ControlId"].startswith("S3")), "ProductArn")
st, d = call("securityhub", "POST", "/findings", {"Filters": {"ResourceId": [{"Value": "arn:aws:s3:::leaky", "Comparison": "EQUALS"}]}})
fid = [f for f in d["Findings"] if f["ProductFields"]["ControlId"] == "S3.2"][0]["Id"]

# remediate: delete the policy -> S3.2 disappears (derived live, not stored)
r.handle("DELETE", "/leaky", {"policy": ""}, auth("s3"), b"")
st, d = call("securityhub", "POST", "/findings", {"Filters": {"ResourceId": [{"Value": "arn:aws:s3:::leaky", "Comparison": "EQUALS"}]}})
check("S3.2" not in {f["ProductFields"]["ControlId"] for f in d["Findings"]}, "S3.2 gone after remediation")

# runtime detector: the public policy + a CloudTrail stop were recorded in the audit feed
check(any("storage-public" in e["tags"] for e in r.secscan_bag()["secscan"]["audit"]), "audit feed saw the public policy")
st, d = call("guardduty", "POST", "/detector", {"Enable": True})
did = d["DetectorId"]
st, d = call("guardduty", "POST", f"/detector/{did}/findings", {})
st, g = call("guardduty", "POST", f"/detector/{did}/findings/get", {"FindingIds": d["FindingIds"]})
types = {f["Type"] for f in g["Findings"]}
check("Policy:S3/BucketAnonymousAccessGranted" in types, f"GuardDuty saw the bucket policy: {types}")
st, d = call("guardduty", "GET", "/detector")
check(d["DetectorIds"] == [did], "ListDetectors")
print(f"OK {ok} checks")
