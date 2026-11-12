"""RDS ManageMasterUserPassword -> a real Secrets Manager secret OWNED by RDS (OwningService=rds), through the wire router.

Run: PYTHONPATH=. ../s3_simulator/.venv/bin/python tests/conformance/test_rds_managed_master_secret_core.py
"""
import json
import re
from urllib.parse import urlencode

from core.aws_wire_router import AwsWireRouter

r = AwsWireRouter()
AUTH = "AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/{}/aws4_request, SignedHeaders=host, Signature=0"


def _check(name, cond, detail=""):
    if not cond:
        raise AssertionError(f"{name} {detail}")
    print(f"  ok  {name}")


def rds(action, **p):
    out = r.handle("POST", "/", {}, {"content-type": "application/x-www-form-urlencoded", "authorization": AUTH.format("rds")},
                   urlencode({"Action": action, "Version": "2014-10-31", **p}).encode())
    return out["status"], out["body"].decode()


def sm(op, body):
    out = r.handle("POST", "/", {}, {"x-amz-target": "secretsmanager." + op, "content-type": "application/x-amz-json-1.1", "authorization": AUTH.format("secretsmanager")},
                   json.dumps(body).encode())
    return out["status"], json.loads(out["body"] or b"{}")


def main():
    s, b = rds("CreateDBInstance", DBInstanceIdentifier="mdb", Engine="postgres", MasterUsername="app", ManageMasterUserPassword="true", MasterUserPassword="x")
    _check("password + ManageMasterUserPassword together is rejected", s == 400 and "InvalidParameterCombination" in b, b[:200])
    s, b = rds("CreateDBInstance", DBInstanceIdentifier="mdb", Engine="postgres", MasterUsername="app", ManageMasterUserPassword="true")
    _check("create ok with MasterUserSecret", s == 200 and "<MasterUserSecret>" in b, b[:300])
    arn = re.search(r"<SecretArn>(.*?)</SecretArn>", b).group(1)
    name = arn.split(":secret:")[1]
    _check("secret is named rds!db-...", name.startswith("rds!db-"), name)
    s, d = sm("DescribeSecret", {"SecretId": arn})
    _check("DescribeSecret shows OwningService=rds", s == 200 and d.get("OwningService") == "rds", d)
    s, v = sm("GetSecretValue", {"SecretId": arn})
    doc = json.loads(v["SecretString"])
    _check("secret holds the real credential for the instance", doc["username"] == "app" and doc["dbInstanceIdentifier"] == "mdb" and len(doc["password"]) >= 16)
    s, e = sm("PutSecretValue", {"SecretId": arn, "SecretString": "{}"})
    _check("user PutSecretValue is rejected", s == 400 and e["__type"] == "InvalidRequestException" and "managed by the service rds" in e["message"], e)
    s, e = sm("DeleteSecret", {"SecretId": arn})
    _check("user DeleteSecret is rejected", s == 400, e)
    s, _ = sm("RotateSecret", {"SecretId": arn})
    s2, v2 = sm("GetSecretValue", {"SecretId": arn})
    doc2 = json.loads(v2["SecretString"])
    _check("RotateSecret really changes the password", doc2["password"] != doc["password"] and doc2["username"] == "app")
    _check("the instance picked up the new master password", r.rds.get_instance("mdb")["master_user_password"] == doc2["password"])
    s, b = rds("ModifyDBInstance", DBInstanceIdentifier="mdb", RotateMasterUserPassword="true", ApplyImmediately="true")
    _, v3 = sm("GetSecretValue", {"SecretId": arn})
    _check("ModifyDBInstance RotateMasterUserPassword rotates again", json.loads(v3["SecretString"])["password"] != doc2["password"])
    s, b = rds("ModifyDBInstance", DBInstanceIdentifier="mdb", ManageMasterUserPassword="false")
    s, e = sm("DescribeSecret", {"SecretId": arn})
    _check("turning management off removes the secret", s == 400 and e["__type"] == "ResourceNotFoundException", e)
    rds("ModifyDBInstance", DBInstanceIdentifier="mdb", ManageMasterUserPassword="true")
    s, b = rds("DeleteDBInstance", DBInstanceIdentifier="mdb", SkipFinalSnapshot="true")
    s, e = sm("DescribeSecret", {"SecretId": arn})
    _check("deleting the instance deletes its managed secret", s == 400, e)


if __name__ == "__main__":
    main()
    print("RESULT: PASS")
