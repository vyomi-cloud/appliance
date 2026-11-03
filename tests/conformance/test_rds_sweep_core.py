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
    # ── RDS Proxy: auth/VPC/endpoint + targets (what the Lambda "RDS databases" helper drives)
    st, x = q(r, "rds", "CreateDBProxy", {"DBProxyName": "px", "EngineFamily": "MYSQL", "RoleArn": "arn:aws:iam::123456789012:role/rds-s3",
                                             "VpcSubnetIds.member.1": "subnet-a", "VpcSecurityGroupIds.member.1": "sg-1",
                                             "Auth.member.1.AuthScheme": "SECRETS", "Auth.member.1.SecretArn": "arn:aws:secretsmanager:us-east-1:123456789012:secret:db"})
    _check("CreateDBProxy with one subnet is rejected (needs two)", st == 400)
    st, x = q(r, "rds", "CreateDBProxy", {"DBProxyName": "px", "EngineFamily": "POSTGRESQL", "RoleArn": "arn:aws:iam::123456789012:role/rds-s3",
                                             "VpcSubnetIds.member.1": "subnet-a", "VpcSubnetIds.member.2": "subnet-b", "VpcSecurityGroupIds.member.1": "sg-1",
                                             "Auth.member.1.AuthScheme": "SECRETS", "Auth.member.1.SecretArn": "arn:aws:secretsmanager:us-east-1:123456789012:secret:db"})
    _check("CreateDBProxy stores VPC, auth and an endpoint", st == 200 and "<Endpoint>px.proxy" in x and "<member>subnet-b</member>" in x and "<SecretArn>arn:aws:secretsmanager" in x)
    st, x = q(r, "rds", "RegisterDBProxyTargets", {"DBProxyName": "px", "DBInstanceIdentifiers.member.1": "app-db"})
    _check("RegisterDBProxyTargets registers a matching-engine instance", st == 200 and "<RdsResourceId>app-db</RdsResourceId>" in x and "AVAILABLE" in x)
    st, x = q(r, "rds", "RegisterDBProxyTargets", {"DBProxyName": "px", "DBInstanceIdentifiers.member.1": "app-db"})
    _check("registering the same target twice is rejected", st == 400)
    st, x = q(r, "rds", "CreateDBProxy", {"DBProxyName": "pxm", "EngineFamily": "MYSQL"})
    st, x = q(r, "rds", "RegisterDBProxyTargets", {"DBProxyName": "pxm", "DBInstanceIdentifiers.member.1": "app-db"})
    _check("an engine-family mismatch is rejected", st == 400)
    st, x = q(r, "rds", "DescribeDBProxyTargets", {"DBProxyName": "px"})
    _check("DescribeDBProxyTargets", "<RdsResourceId>app-db</RdsResourceId>" in x)
    st, x = q(r, "rds", "DeregisterDBProxyTargets", {"DBProxyName": "px", "DBInstanceIdentifiers.member.1": "app-db"})
    st2, y = q(r, "rds", "DescribeDBProxyTargets", {"DBProxyName": "px"})
    _check("DeregisterDBProxyTargets", st == 200 and "app-db" not in y)
    print("RDS sweep: all checks passed")


if __name__ == "__main__":
    main()
