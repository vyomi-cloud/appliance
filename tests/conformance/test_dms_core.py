"""AWS DMS between two simulator RDS instances: endpoints resolve to real instances, full-load copies rows, CDC-lite applies changes.

Run: PYTHONPATH=. ../appliance/.venv/bin/python tests/conformance/test_dms_core.py
"""
import json
import sys

from core.aws_wire_router import AwsWireRouter

DMS = "AWS4-HMAC-SHA256 Credential=T/20261104/us-east-1/dms/aws4_request, SignedHeaders=host, Signature=0"
RDS = "AWS4-HMAC-SHA256 Credential=T/20261104/us-east-1/rds/aws4_request, SignedHeaders=host, Signature=0"
PASS = FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name} {extra}")


r = AwsWireRouter()


def dms(action, payload):
    o = r.handle("POST", "/", {}, {"authorization": DMS, "x-amz-target": f"AmazonDMSv20160101.{action}", "content-type": "application/x-amz-json-1.1"},
                 json.dumps(payload).encode())
    return o["status"], json.loads(o["body"])


for n in ("src-db", "tgt-db"):
    o = r.handle("POST", "/", {}, {"authorization": RDS, "content-type": "application/x-www-form-urlencoded"},
                 f"Action=CreateDBInstance&DBInstanceIdentifier={n}&DBInstanceClass=db.t3.micro&Engine=postgres&MasterUsername=admin&MasterUserPassword=secret123&AllocatedStorage=20&Version=2014-10-31".encode())
    assert o["status"] == 200, o
sql = r.rds.execute_sql
sql("src-db", "CREATE TABLE orders (id INTEGER PRIMARY KEY, item TEXT, qty INTEGER)")
sql("src-db", "CREATE TABLE audit (id INTEGER PRIMARY KEY, msg TEXT)")
for i in range(5):
    sql("src-db", "INSERT INTO orders VALUES (?, ?, ?)", [i, f"item{i}", i * 2])
sql("src-db", "INSERT INTO audit VALUES (1, 'x')")

s, o = dms("CreateReplicationInstance", {"ReplicationInstanceIdentifier": "ri1", "ReplicationInstanceClass": "dms.t3.micro"})
ri = o["ReplicationInstance"]["ReplicationInstanceArn"]
check("CreateReplicationInstance", s == 200 and ri.startswith("arn:aws:dms:") and o["ReplicationInstance"]["ReplicationInstanceStatus"] == "available")
check("duplicate -> ResourceAlreadyExistsFault", dms("CreateReplicationInstance", {"ReplicationInstanceIdentifier": "ri1", "ReplicationInstanceClass": "dms.t3.micro"})[1]["__type"] == "ResourceAlreadyExistsFault")
check("bad class rejected", dms("CreateReplicationInstance", {"ReplicationInstanceIdentifier": "ri2", "ReplicationInstanceClass": "t3.micro"})[0] == 400)

ep = lambda ident, typ, host: dms("CreateEndpoint", {"EndpointIdentifier": ident, "EndpointType": typ, "EngineName": "postgres", "ServerName": host,
                                                    "Port": 5432, "DatabaseName": "app", "Username": "admin", "Password": "secret123"})
s, o = ep("src", "source", "src-db.nano-rds.local")
src = o["Endpoint"]["EndpointArn"]
tgt = ep("tgt", "target", "tgt-db.nano-rds.local")[1]["Endpoint"]["EndpointArn"]
ghost = ep("ghost", "target", "nope.example.com")[1]["Endpoint"]["EndpointArn"]
check("endpoint created without a password echo", s == 200 and "Password" not in o["Endpoint"])
check("missing DatabaseName for SQL engine", dms("CreateEndpoint", {"EndpointIdentifier": "bad", "EndpointType": "source", "EngineName": "postgres", "ServerName": "x", "Port": 1, "Username": "u"})[0] == 400)
check("TestConnection successful", dms("TestConnection", {"ReplicationInstanceArn": ri, "EndpointArn": src})[1]["Connection"]["Status"] == "successful")
dms("TestConnection", {"ReplicationInstanceArn": ri, "EndpointArn": tgt})
c = dms("TestConnection", {"ReplicationInstanceArn": ri, "EndpointArn": ghost})[1]["Connection"]
check("TestConnection to unresolvable host fails", c["Status"] == "failed" and "Cannot resolve host" in c["LastFailureMessage"])
check("DescribeConnections", len(dms("DescribeConnections", {})[1]["Connections"]) == 3)

maps = json.dumps({"rules": [{"rule-type": "selection", "rule-id": "1", "rule-name": "1", "object-locator": {"schema-name": "%", "table-name": "orders"}, "rule-action": "include"}]})
mk = lambda ident, typ, t=tgt, s_=src, m=maps: dms("CreateReplicationTask", {"ReplicationTaskIdentifier": ident, "SourceEndpointArn": s_, "TargetEndpointArn": t,
                                                                              "ReplicationInstanceArn": ri, "MigrationType": typ, "TableMappings": m})
check("task to untested endpoint refused", mk("t0", "full-load", t=ghost)[1]["__type"] == "InvalidResourceStateFault")
check("swapped source/target refused", mk("t0", "full-load", t=src, s_=tgt)[0] == 400)
check("bad TableMappings refused", mk("t0", "full-load", m="{}")[0] == 400)
check("bad MigrationType refused", mk("t0", "bogus")[0] == 400)
s, o = mk("t-full", "full-load")
task = o["ReplicationTask"]["ReplicationTaskArn"]
check("CreateReplicationTask -> ready", s == 200 and o["ReplicationTask"]["Status"] == "ready")
s, o = dms("StartReplicationTask", {"ReplicationTaskArn": task, "StartReplicationTaskType": "start-replication"})
check("full-load finishes -> stopped", o["ReplicationTask"]["Status"] == "stopped" and o["ReplicationTask"]["StopReason"] == "Stop Reason FULL_LOAD_ONLY_FINISHED", o)
rows = sql("tgt-db", "SELECT id, item, qty FROM orders ORDER BY id")["rows"]
check("rows really copied to the target instance", len(rows) == 5 and rows[3] == [3, "item3", 6], rows)
check("unselected table not copied", "audit" not in [x[0] for x in sql("tgt-db", "SELECT name FROM sqlite_master WHERE type='table'")["rows"]])
st = dms("DescribeTableStatistics", {"ReplicationTaskArn": task})[1]["TableStatistics"]
check("table statistics", st[0]["TableName"] == "orders" and st[0]["FullLoadRows"] == 5 and st[0]["TableState"] == "Table completed")
check("delete endpoint in use refused", dms("DeleteEndpoint", {"EndpointArn": src})[1]["__type"] == "InvalidResourceStateFault")

# CDC-lite
s, o = mk("t-cdc", "full-load-and-cdc")
cdc = o["ReplicationTask"]["ReplicationTaskArn"]
sql("tgt-db", "DELETE FROM orders")
o = dms("StartReplicationTask", {"ReplicationTaskArn": cdc, "StartReplicationTaskType": "start-replication"})[1]
check("cdc task running", o["ReplicationTask"]["Status"] == "running")
sql("src-db", "INSERT INTO orders VALUES (10, 'new', 1)")
sql("src-db", "UPDATE orders SET qty = 99 WHERE id = 1")
sql("src-db", "DELETE FROM orders WHERE id = 0")
dms("DescribeReplicationTasks", {})
st = dms("DescribeTableStatistics", {"ReplicationTaskArn": cdc})[1]["TableStatistics"][0]
trows = sql("tgt-db", "SELECT id, qty FROM orders ORDER BY id")["rows"]
check("CDC-lite applied insert/update/delete", st["Inserts"] == 1 and st["Updates"] == 1 and st["Deletes"] == 1 and [10, 1] in trows and [1, 99] in trows and all(x[0] != 0 for x in trows), (st, trows))
check("delete running task refused", dms("DeleteReplicationTask", {"ReplicationTaskArn": cdc})[1]["__type"] == "InvalidResourceStateFault")
check("stop task", dms("StopReplicationTask", {"ReplicationTaskArn": cdc})[1]["ReplicationTask"]["Status"] == "stopped")
check("stop stopped task refused", dms("StopReplicationTask", {"ReplicationTaskArn": cdc})[0] == 400)
check("delete tasks", dms("DeleteReplicationTask", {"ReplicationTaskArn": cdc})[0] == 200 and dms("DeleteReplicationTask", {"ReplicationTaskArn": task})[0] == 200)
check("delete instance + endpoints after tasks", dms("DeleteReplicationInstance", {"ReplicationInstanceArn": ri})[0] == 200 and dms("DeleteEndpoint", {"EndpointArn": src})[0] == 200)
check("describe filters", dms("DescribeEndpoints", {"Filters": [{"Name": "endpoint-type", "Values": ["target"]}]})[1]["Endpoints"][0]["EndpointType"] == "target")

print(f"{PASS} passed, {FAIL} failed")


def test_all_checks_pass():
    assert FAIL == 0


if __name__ == "__main__":
    sys.exit(1 if FAIL else 0)
