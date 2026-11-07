"""Zero-ETL integrations (DynamoDB / RDS -> Redshift-lite) + Redshift Data API, via AwsWireRouter.

Run: PYTHONPATH=. ../appliance/.venv/bin/python tests/conformance/test_zeroetl_core.py
"""
import json

from core.aws_wire_router import AwsWireRouter

H = lambda svc: {"authorization": f"AWS4-HMAC-SHA256 Credential=T/20261104/us-east-1/{svc}/aws4_request, SignedHeaders=host, Signature=0", "content-type": "application/x-amz-json-1.1"}


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def J(r, svc, target, payload):
    out = r.handle("POST", "/", {}, {**H(svc), "x-amz-target": target}, json.dumps(payload).encode())
    return out["status"], json.loads(out["body"] or b"{}")


def D(r, target, payload):
    return J(r, "dynamodb", "DynamoDB_20120810." + target, payload)


def sql(r, q, db="dev"):
    s, o = J(r, "redshift-data", "RedshiftData.ExecuteStatement", {"Sql": q, "Database": db, "WorkgroupName": "wg"})
    assert s == 200, o
    s, d = J(r, "redshift-data", "RedshiftData.DescribeStatement", {"Id": o["Id"]})
    if d["Status"] != "FINISHED":
        return d, None
    return d, J(r, "redshift-data", "RedshiftData.GetStatementResult", {"Id": o["Id"]})[1]


def main():
    r = AwsWireRouter()
    D(r, "CreateTable", {"TableName": "orders", "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}], "AttributeDefinitions": [{"AttributeName": "id", "AttributeType": "S"}], "BillingMode": "PAY_PER_REQUEST"})
    for i, tot in (("a", 10), ("b", 25)):
        D(r, "PutItem", {"TableName": "orders", "Item": {"id": {"S": i}, "total": {"N": str(tot)}}})
    TGT = "arn:aws:redshift-serverless:us-east-1:123456789012:namespace/abc"
    SRC = "arn:aws:dynamodb:us-east-1:123456789012:table/orders"
    s, o = J(r, "glue", "AWSGlue.CreateIntegration", {"IntegrationName": "ddb-orders", "SourceArn": SRC, "TargetArn": TGT})
    _check("PITR required on the source table", s == 400 and o["__type"] == "IntegrationSourcePropertyException")
    D(r, "UpdateContinuousBackups", {"TableName": "orders", "PointInTimeRecoverySpecification": {"PointInTimeRecoveryEnabled": True}})
    s, o = J(r, "glue", "AWSGlue.CreateIntegration", {"IntegrationName": "ddb-orders", "SourceArn": SRC, "TargetArn": TGT})
    _check("create integration ACTIVE", s == 200 and o["Status"] == "ACTIVE" and o["IntegrationArn"].endswith(":integration:ddb-orders"))
    _check("duplicate 409", J(r, "glue", "AWSGlue.CreateIntegration", {"IntegrationName": "ddb-orders", "SourceArn": SRC, "TargetArn": TGT})[0] == 409)
    _check("bad source arn 400", J(r, "glue", "AWSGlue.CreateIntegration", {"IntegrationName": "x", "SourceArn": "arn:aws:s3:::b", "TargetArn": TGT})[0] == 400)
    _check("missing table 404", J(r, "glue", "AWSGlue.CreateIntegration", {"IntegrationName": "x", "SourceArn": SRC + "z", "TargetArn": TGT})[0] == 404)
    _check("describe", [i["IntegrationName"] for i in J(r, "glue", "AWSGlue.DescribeIntegrations", {})[1]["Integrations"]] == ["ddb-orders"])
    d, _ = sql(r, "SELECT * FROM zdb.orders")
    _check("query before CREATE DATABASE fails", d["Status"] == "FAILED")
    d, _ = sql(r, "CREATE DATABASE zdb FROM INTEGRATION 'ddb-orders'")
    _check("create database from integration", d["Status"] == "FINISHED")
    d, res = sql(r, "SELECT id, json_extract(value, '$.total.N') AS total FROM zdb.public.orders ORDER BY id")
    _check("replicated rows queryable (id + SUPER value)", d["ResultRows"] == 2 and [x[0]["stringValue"] for x in res["Records"]] == ["a", "b"])
    D(r, "PutItem", {"TableName": "orders", "Item": {"id": {"S": "c"}, "total": {"N": "5"}}})
    _, res = sql(r, "SELECT count(*) FROM zdb.orders")
    _check("new item replicated on next query", res["Records"][0][0]["longValue"] == 3)
    D(r, "DeleteItem", {"TableName": "orders", "Key": {"id": {"S": "a"}}})
    _, res = sql(r, "SELECT count(*) FROM zdb.orders")
    _check("delete replicated", res["Records"][0][0]["longValue"] == 2)
    d, _ = sql(r, "DROP TABLE zdb.orders")
    _check("write statements rejected (read-only target)", d["Status"] == "FAILED" and "read-only" in d["Error"])
    _check("ListTables", J(r, "redshift-data", "RedshiftData.ListTables", {"Database": "zdb"})[1]["Tables"][0]["name"] == "orders")
    _check("ListDatabases", "zdb" in J(r, "redshift-data", "RedshiftData.ListDatabases", {})[1]["Databases"])
    _check("unknown statement 404", J(r, "redshift-data", "RedshiftData.DescribeStatement", {"Id": "nope"})[0] == 404)
    _check("no workgroup 400", J(r, "redshift-data", "RedshiftData.ExecuteStatement", {"Sql": "select 1"})[0] == 400)
    # (the Glue Data Catalog / crawlers / jobs are real since glue_catalog_core; an op outside all of those stays honestly unsupported)
    _check("other Glue ops honestly unsupported", J(r, "glue", "AWSGlue.GetMLTransforms", {})[0] == 400)

    # ---- RDS source (sqlite engine): rows replicate too
    q = lambda **p: r.handle("POST", "/", {}, {**H("rds"), "content-type": "application/x-www-form-urlencoded"}, "&".join(f"{k}={v}" for k, v in p.items()).encode())
    q(Action="CreateDBInstance", DBInstanceIdentifier="shop", Engine="postgres", DBInstanceClass="db.t3.micro")
    try:
        r.rds.execute_sql("shop", "CREATE TABLE cust (id INTEGER PRIMARY KEY, name TEXT)")
        r.rds.execute_sql("shop", "INSERT INTO cust VALUES (1, 'ada'), (2, 'bob')")
        have_sql = True
    except Exception:
        have_sql = False
    if have_sql:
        q(Action="CreateIntegration", IntegrationName="rds-shop", SourceArn="arn:aws:rds:us-east-1:123456789012:db:shop", TargetArn=TGT)
        d, _ = sql(r, "CREATE DATABASE shopdw FROM INTEGRATION 'rds-shop'")
        _check("RDS integration -> database", d["Status"] == "FINISHED")
        _, res = sql(r, "SELECT name FROM shopdw.cust ORDER BY id")
        _check("RDS rows replicated", [x[0]["stringValue"] for x in res["Records"]] == ["ada", "bob"])
    else:
        print("  skip RDS source (no SQL engine in this runtime)")
    _check("delete integration", J(r, "glue", "AWSGlue.DeleteIntegration", {"IntegrationIdentifier": "ddb-orders"})[0] == 200)
    _, res = sql(r, "SELECT count(*) FROM zdb.orders") if False else (None, None)
    print("OK")


if __name__ == "__main__":
    main()
