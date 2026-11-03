"""AWS-09 RDS sweep — IAM role association (Add/RemoveRoleToDBInstance), DescribeAccountAttributes (service quotas + live usage).
Via AwsWireRouter. Run: PYTHONPATH=. python3 tests/conformance/test_rds_sweep_core.py
"""
import json
import re
from urllib.parse import urlencode

from core.aws_wire_router import AwsWireRouter


def _auth(svc):
    return f"AWS4-HMAC-SHA256 Credential=T/20261030/us-east-1/{svc}/aws4_request, SignedHeaders=host, Signature=0"


def q(r, svc, action, params=None, version="2014-10-31"):
    body = urlencode({"Action": action, "Version": version, **(params or {})}).encode()
    out = r.handle("POST", "/", {}, {"authorization": _auth(svc), "content-type": "application/x-www-form-urlencoded"}, body)
    return out["status"], out["body"].decode()


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def main():
    r = AwsWireRouter()
    st, _ = q(r, "rds", "CreateDBInstance", {"DBInstanceIdentifier": "app-db", "Engine": "postgres", "DBInstanceClass": "db.t3.micro", "MasterUsername": "u", "MasterUserPassword": "pw12345678", "AllocatedStorage": "30"})
    _check("fixture DB instance", st == 200)
    trust = json.dumps({"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {"Service": "rds.amazonaws.com"}, "Action": "sts:AssumeRole"}]})
    q(r, "iam", "CreateRole", {"RoleName": "rds-s3", "AssumeRolePolicyDocument": trust}, "2010-05-08")
    q(r, "iam", "CreateRole", {"RoleName": "wrong-trust", "AssumeRolePolicyDocument": trust.replace("rds.amazonaws.com", "ec2.amazonaws.com")}, "2010-05-08")
    arn = "arn:aws:iam::123456789012:role/rds-s3"
    st, x = q(r, "rds", "AddRoleToDBInstance", {"DBInstanceIdentifier": "app-db", "RoleArn": "arn:aws:iam::123456789012:role/ghost", "FeatureName": "s3Import"})
    _check("a non-existent role is rejected", st == 400)
    st, x = q(r, "rds", "AddRoleToDBInstance", {"DBInstanceIdentifier": "app-db", "RoleArn": "arn:aws:iam::123456789012:role/wrong-trust", "FeatureName": "s3Import"})
    _check("a role not trusting rds.amazonaws.com is rejected", st == 400 and "rds.amazonaws.com" in x)
    st, x = q(r, "rds", "AddRoleToDBInstance", {"DBInstanceIdentifier": "app-db", "RoleArn": arn, "FeatureName": "Lambda"})
    _check("a feature the engine doesn't support is rejected", st == 400)
    st, x = q(r, "rds", "AddRoleToDBInstance", {"DBInstanceIdentifier": "app-db", "RoleArn": arn, "FeatureName": "s3Import"})
    _check("AddRoleToDBInstance", st == 200)
    st, x = q(r, "rds", "AddRoleToDBInstance", {"DBInstanceIdentifier": "app-db", "RoleArn": arn, "FeatureName": "s3Import"})
    _check("duplicate association -> DBInstanceRoleAlreadyExists", st == 400 and "DBInstanceRoleAlreadyExists" in x)
    st, x = q(r, "rds", "DescribeDBInstances", {"DBInstanceIdentifier": "app-db"})
    _check("DescribeDBInstances returns AssociatedRoles", f"<RoleArn>{arn}</RoleArn>" in x and "<FeatureName>s3Import</FeatureName>" in x and "<Status>ACTIVE</Status>" in x)
    st, x = q(r, "rds", "DescribeAccountAttributes")
    quota = dict(re.findall(r"<AccountQuotaName>(\w+)</AccountQuotaName><Used>(\d+)</Used>", x))
    _check("DescribeAccountAttributes reports live usage (1 instance, 30 GB, 1 role)", quota["DBInstances"] == "1" and quota["AllocatedStorage"] == "30" and quota["DBInstanceRoles"] == "1")
    _check("DescribeAccountAttributes reports the real default quotas", "<AccountQuotaName>DBInstances</AccountQuotaName><Used>1</Used><Max>40</Max>" in x and "<Max>100000</Max>" in x)
    st, x = q(r, "rds", "RemoveRoleFromDBInstance", {"DBInstanceIdentifier": "app-db", "RoleArn": arn, "FeatureName": "s3Import"})
    st2, y = q(r, "rds", "DescribeDBInstances", {"DBInstanceIdentifier": "app-db"})
    _check("RemoveRoleFromDBInstance", st == 200 and arn not in y)
    st, x = q(r, "rds", "RemoveRoleFromDBInstance", {"DBInstanceIdentifier": "app-db", "RoleArn": arn, "FeatureName": "s3Import"})
    _check("removing an unassociated role -> DBInstanceRoleNotFound", st == 404 and "DBInstanceRoleNotFound" in x)
    print("RDS sweep: all checks passed")


if __name__ == "__main__":
    main()
