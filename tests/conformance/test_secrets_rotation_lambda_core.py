"""AWS-08 Secrets Manager rotation function — RotateSecret really invokes the Lambda rotation function through
createSecret/setSecret/testSecret/finishSecret and promotes the new version. Via AwsWireRouter (Nano entry).
Run: PYTHONPATH=. python3 tests/conformance/test_secrets_rotation_lambda_core.py
"""
import json

from core.aws_wire_router import AwsWireRouter


def _auth(svc):
    return f"AWS4-HMAC-SHA256 Credential=T/20261030/us-east-1/{svc}/aws4_request, SignedHeaders=host, Signature=0"


def sm(r, action, p=None):
    out = r.handle("POST", "/", {}, {"authorization": _auth("secretsmanager"), "x-amz-target": f"secretsmanager.{action}",
                                      "content-type": "application/x-amz-json-1.1"}, json.dumps(p or {}).encode())
    return out["status"], (json.loads(out["body"]) if out["body"] else {})


def lam(r, method, path, body=None):
    out = r.handle(method, path, {}, {"authorization": _auth("lambda"), "content-type": "application/json"}, json.dumps(body).encode() if body is not None else b"")
    return out["status"], (json.loads(out["body"]) if out["body"] else {})


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


SRC = '''
import json
def handler(event, context):
    step = event["Step"]
    if step == "createSecret":
        return {"SecretString": json.dumps({"password": "rotated-" + event["ClientRequestToken"][:6]})}
    if step == "testSecret" and event.get("fail"):
        raise ValueError("boom")
    return None
'''
BAD = SRC.replace('if step == "testSecret" and event.get("fail")', 'if step == "testSecret"')


def mkfn(r, name, src, perm=True):
    st, _ = lam(r, "POST", "/2015-03-31/functions", {"FunctionName": name, "Runtime": "python3.12", "Handler": "index.handler",
                                                      "Role": "arn:aws:iam::123456789012:role/x", "Code": {"Source": src}})
    assert st in (200, 201), st
    if perm:
        st, _ = lam(r, "POST", f"/2015-03-31/functions/{name}/policy", {"StatementId": "sm", "Action": "lambda:InvokeFunction", "Principal": "secretsmanager.amazonaws.com"})
        assert st in (200, 201), st
    return f"arn:aws:lambda:us-east-1:123456789012:function:{name}"


def main():
    r = AwsWireRouter()
    good = mkfn(r, "rot-good", SRC)
    nop = mkfn(r, "rot-noperm", SRC, perm=False)
    bad = mkfn(r, "rot-bad", BAD)
    st, c = sm(r, "CreateSecret", {"Name": "db", "SecretString": json.dumps({"password": "initial"})})
    old_v = sm(r, "GetSecretValue", {"SecretId": "db"})[1]["VersionId"]
    st, o = sm(r, "RotateSecret", {"SecretId": "db", "RotationLambdaARN": "arn:aws:lambda:us-east-1:123456789012:function:missing", "RotateImmediately": True})
    _check("a missing rotation function is rejected", st == 400 and "not found" in json.dumps(o).lower())
    st, o = sm(r, "RotateSecret", {"SecretId": "db", "RotationLambdaARN": nop})
    _check("a function without the secretsmanager invoke permission is rejected", st == 400 and "secretsmanager.amazonaws.com" in json.dumps(o))
    st, o = sm(r, "RotateSecret", {"SecretId": "db", "RotationLambdaARN": bad})
    _check("a rotation function failing at testSecret fails the rotation", st == 400 and "testSecret" in json.dumps(o))
    cur = sm(r, "GetSecretValue", {"SecretId": "db"})[1]
    _check("a failed rotation leaves the current value untouched", json.loads(cur["SecretString"])["password"] == "initial" and cur["VersionId"] == old_v)
    st, ids = sm(r, "ListSecretVersionIds", {"SecretId": "db", "IncludeDeprecated": True})
    _check("the abandoned AWSPENDING version is left behind (like real rotation)", any("AWSPENDING" in v.get("VersionStages", []) for v in ids["Versions"]))
    st, o = sm(r, "RotateSecret", {"SecretId": "db", "RotationLambdaARN": good, "RotationRules": {"AutomaticallyAfterDays": 1}})
    _check("RotateSecret with a good function succeeds", st == 200 and o.get("VersionId"))
    cur = sm(r, "GetSecretValue", {"SecretId": "db"})[1]
    _check("the function generated the new AWSCURRENT value", json.loads(cur["SecretString"])["password"].startswith("rotated-") and cur["VersionId"] == o["VersionId"])
    prev = sm(r, "GetSecretValue", {"SecretId": "db", "VersionStage": "AWSPREVIOUS"})[1]
    _check("the old value became AWSPREVIOUS", json.loads(prev["SecretString"])["password"] == "initial")
    st, d = sm(r, "DescribeSecret", {"SecretId": "db"})
    _check("DescribeSecret reports RotationLambdaARN + LastRotatedDate", d["RotationLambdaARN"] == good and d.get("LastRotatedDate"))
    # UpdateSecretVersionStage (what a real rotation function calls in finishSecret)
    st, p = sm(r, "PutSecretValue", {"SecretId": "db", "SecretString": "x", "VersionStages": ["AWSPENDING"]})
    st, _ = sm(r, "UpdateSecretVersionStage", {"SecretId": "db", "VersionStage": "AWSCURRENT", "MoveToVersionId": p["VersionId"], "RemoveFromVersionId": o["VersionId"]})
    cur = sm(r, "GetSecretValue", {"SecretId": "db"})[1]
    _check("UpdateSecretVersionStage moves AWSCURRENT", st == 200 and cur["VersionId"] == p["VersionId"])
    st, _ = sm(r, "UpdateSecretVersionStage", {"SecretId": "db", "VersionStage": "AWSCURRENT", "MoveToVersionId": "nope"})
    _check("UpdateSecretVersionStage rejects an unknown version", st == 400)
    print("Secrets rotation sweep: all checks passed")


if __name__ == "__main__":
    main()
