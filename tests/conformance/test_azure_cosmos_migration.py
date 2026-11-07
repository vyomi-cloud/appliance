"""Cosmos Data Migration: real container->container / JSON->container copy through the data-plane write path.
Run: PYTHONPATH=. python tests/conformance/test_azure_cosmos_migration.py"""
import json
from core import azure_cosmos_core as cc


def check(n, c):
    if not c:
        raise AssertionError(n)
    print("  ok ", n)


st = cc.CosmosStore()
def d(m, p, b=None, h=None):
    return cc.dispatch(st, m, p, {}, h or {}, json.dumps(b).encode() if b is not None else b"")
def j(r): return json.loads(r.body)

d("POST", "/dbs", {"id": "db"}); d("POST", "/dbs/db/colls", {"id": "src", "partitionKey": {"paths": ["/id"]}})
for i in range(5):
    d("POST", "/dbs/db/colls/src/docs", {"id": str(i), "n": i, "name": f"u{i}"})
mig = lambda **s: d("POST", "/vyomi/migrations", s)
r = mig(source={"type": "container", "database": "db", "container": "src"}, target={"database": "db", "container": "dst", "partitionKeyPath": "/n"})
b = j(r)
check("copies all rows, creates target", r.status == 200 and b["status"] == "Succeeded" and b["migrated"] == 5 and b.get("createdTarget"))
docs = j(d("GET", "/dbs/db/colls/dst/docs"))["Documents"]
check("rows really exist in target with regenerated system props", len(docs) == 5 and all(x["_rid"] and x["name"] for x in docs))
check("target keeps requested partition key", j(d("GET", "/dbs/db/colls/dst"))["partitionKey"]["paths"] == ["/n"])
check("change feed of target sees migrated rows", len(j(d("GET", "/dbs/db/colls/dst/docs", None, {"a-im": "Incremental feed"}))["Documents"]) == 5)
b = j(mig(source={"type": "container", "database": "db", "container": "src"}, target={"database": "db", "container": "dst"}, conflict="skip"))
check("skip leaves existing", b["skipped"] == 5 and b["migrated"] == 0)
b = j(mig(source={"type": "container", "database": "db", "container": "src"}, target={"database": "db", "container": "dst"}, conflict="fail"))
check("fail stops at first conflict", b["status"] == "Failed" and b["failed"] == 1)
b = j(mig(source={"type": "container", "database": "db", "container": "src", "query": "SELECT * FROM c WHERE c.n >= 3"},
          target={"database": "db", "container": "q"}, mapping={"rename": {"name": "label"}, "drop": ["n"], "set": {"mig": True}}))
qd = j(d("GET", "/dbs/db/colls/q/docs"))["Documents"]
check("query filter + mapping applied", b["migrated"] == 2 and all("label" in x and "n" not in x and x["mig"] is True for x in qd))
b = j(mig(source={"type": "container", "database": "db", "container": "src"}, target={"database": "db", "container": "nope"}, dryRun=True))
check("dry run counts, writes nothing", b["migrated"] == 5 and "nope" not in st.colls["db"])
b = j(mig(source={"type": "json", "data": '[{"id":"a","v":1},{"id":"b","v":2},{"v":3}]'}, target={"database": "db", "container": "imp"}))
check("JSON import: 2 ok, id-less row reported", b["migrated"] == 2 and b["failed"] == 1 and b["status"] == "CompletedWithErrors")
check("bad source 400", mig(source={"database": "db", "container": "ghost"}, target={"database": "db", "container": "x"}).status == 400)
check("same container rejected", mig(source={"database": "db", "container": "src"}, target={"database": "db", "container": "src"}).status == 400)
check("history lists real jobs", len(j(d("GET", "/vyomi/migrations"))["migrations"]) >= 4)
print("PASS")
