"""Redshift clusters + a real SQL engine behind the Redshift Data API, through the wire router.

Run: PYTHONPATH=. ../s3_simulator/.venv/bin/python tests/conformance/test_redshift_cluster_core.py
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


def rs(action, **p):
    out = r.handle("POST", "/", {}, {"content-type": "application/x-www-form-urlencoded", "authorization": AUTH.format("redshift")},
                   urlencode({"Action": action, "Version": "2012-12-01", **p}).encode())
    return out["status"], out["body"].decode()


def rsd(op, body):
    out = r.handle("POST", "/", {}, {"x-amz-target": "RedshiftData." + op, "content-type": "application/x-amz-json-1.1", "authorization": AUTH.format("redshift-data")},
                   json.dumps(body).encode())
    return out["status"], json.loads(out["body"] or b"{}")


def sm(op, body):
    out = r.handle("POST", "/", {}, {"x-amz-target": "secretsmanager." + op, "content-type": "application/x-amz-json-1.1", "authorization": AUTH.format("secretsmanager")},
                   json.dumps(body).encode())
    return out["status"], json.loads(out["body"] or b"{}")


def sql(cid, q):
    s, b = rsd("ExecuteStatement", {"ClusterIdentifier": cid, "Database": "dev", "Sql": q})
    d = rsd("DescribeStatement", {"Id": b["Id"]})[1]
    return d, (rsd("GetStatementResult", {"Id": b["Id"]})[1] if d["Status"] == "FINISHED" and d.get("HasResultSet") else None)


def main():
    s, b = rs("CreateCluster", ClusterIdentifier="Bad_ID", NodeType="dc2.large", MasterUsername="admin", MasterUserPassword="Passw0rdX")
    _check("bad identifier rejected", s == 400 and "InvalidParameterValue" in b)
    s, b = rs("CreateCluster", ClusterIdentifier="wh1", NodeType="dc2.large", MasterUsername="admin", MasterUserPassword="weak")
    _check("weak password rejected", s == 400)
    s, b = rs("CreateCluster", ClusterIdentifier="wh1", NodeType="dc2.large", MasterUsername="admin", MasterUserPassword="Passw0rdX", DBName="sales")
    _check("CreateCluster ok with endpoint", s == 200 and "<Port>5439</Port>" in b and "wh1.vyomi" in b, b[:200])
    _check("duplicate rejected", rs("CreateCluster", ClusterIdentifier="wh1", NodeType="dc2.large", MasterUsername="a", MasterUserPassword="Passw0rdX")[0] == 400)
    _check("DescribeClusters lists it", "<ClusterIdentifier>wh1</ClusterIdentifier>" in rs("DescribeClusters")[1])

    d, res = sql("wh1", "CREATE TABLE orders (id INTEGER, amt REAL, region TEXT)")
    _check("DDL runs", d["Status"] == "FINISHED", d)
    d, _ = sql("wh1", "INSERT INTO orders VALUES (1, 10.5, 'east'), (2, 20, 'west'), (3, 5, 'east')")
    _check("INSERT runs, reports rows", d["Status"] == "FINISHED" and d["ResultRows"] == 3, d)
    d, res = sql("wh1", "SELECT region, SUM(amt) AS total FROM public.orders GROUP BY region ORDER BY region")
    rows = [[c.get("stringValue", c.get("doubleValue", c.get("longValue"))) for c in row] for row in res["Records"]]
    _check("aggregate query returns real results", rows == [["east", 15.5], ["west", 20.0]], rows)
    d, _ = sql("wh1", "SELECT * FROM nope")
    _check("SQL errors fail the statement", d["Status"] == "FAILED" and "no such table" in d["Error"], d)
    _check("ListTables sees the table", [t["name"] for t in rsd("ListTables", {"ClusterIdentifier": "wh1", "Database": "dev"})[1]["Tables"]] == ["orders"])

    # reboot rebuilds the engine from the persisted statement log
    rs("RebootCluster", ClusterIdentifier="wh1")
    d, res = sql("wh1", "SELECT COUNT(*) FROM orders")
    _check("data survives an engine rebuild", res["Records"][0][0]["longValue"] == 3, res)

    # managed master password -> redshift-owned secret
    s, b = rs("CreateCluster", ClusterIdentifier="wh2", NodeType="ra3.xlplus", MasterUsername="admin", ManageMasterPassword="true")
    arn = re.search(r"<MasterPasswordSecretArn>(.*?)<", b).group(1)
    s, d = sm("DescribeSecret", {"SecretId": arn})
    _check("managed password secret is owned by redshift", d.get("OwningService") == "redshift", d)
    cred = json.loads(sm("GetSecretValue", {"SecretId": arn})[1]["SecretString"])
    _check("secret has cluster connection details", cred["engine"] == "redshift" and cred["dbClusterIdentifier"] == "wh2" and cred["port"] == 5439, cred)
    sm("RotateSecret", {"SecretId": arn})
    cred2 = json.loads(sm("GetSecretValue", {"SecretId": arn})[1]["SecretString"])
    _check("rotation changes the cluster's master password", cred2["password"] != cred["password"])
    rs("DeleteCluster", ClusterIdentifier="wh2")
    _check("deleting the cluster deletes its managed secret", sm("DescribeSecret", {"SecretId": arn})[0] == 400)
    _check("delete works", rs("DeleteCluster", ClusterIdentifier="wh1")[0] == 200 and rs("DescribeClusters", ClusterIdentifier="wh1")[0] == 404)


if __name__ == "__main__":
    main()
    print("RESULT: PASS")
