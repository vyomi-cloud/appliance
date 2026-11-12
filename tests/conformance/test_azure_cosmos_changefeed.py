"""Cosmos DB change feed (A-IM: Incremental feed, _lsn continuation) + Azure Functions cosmosDBTrigger.
Run: PYTHONPATH=. python tests/conformance/test_azure_cosmos_changefeed.py"""
import json
from core import azure_cosmos_core as cc
from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as SUB
AzureArm.STRICT_SUBSCRIPTION = False


def check(n, c):
    if not c:
        raise AssertionError(n)
    print("  ok ", n)


a = AzureArm()
RG = f"/subscriptions/{SUB}/resourceGroups/rg"
a.handle("PUT", RG, {"api-version": "2021-04-01"}, {"location": "eastus"})
W = {"api-version": "2023-12-01"}
acct = RG + "/providers/Microsoft.DocumentDB/databaseAccounts/cfacct"
a.handle("PUT", acct, {"api-version": "2024-05-15"}, {"location": "eastus", "kind": "GlobalDocumentDB", "properties": {}})
app = RG + "/providers/Microsoft.Web/sites/cfapp"
a.handle("PUT", app, W, {"location": "eastus", "kind": "functionapp,linux", "properties": {"reserved": True}})
a.handle("PUT", app + "/config/appsettings", W, {"properties": {"COSMOS_CONN": "AccountEndpoint=https://cfacct.documents.azure.com:443/;AccountKey=abc;"}})
CODE = "def main(req):\n    docs = req['body']['documents']\n    if any(d.get('boom') for d in docs):\n        raise ValueError('boom')\n    return {'n': len(docs)}\n"
def fn(name, db, cont, conn="COSMOS_CONN", extra=None):
    b = {"type": "cosmosDBTrigger", "direction": "in", "name": "documents", "databaseName": db, "containerName": cont, "connection": conn}
    b.update(extra or {})
    r = a.handle("PUT", f"{app}/functions/{name}", W, {"properties": {"config": {"bindings": [b]}, "files": {"__init__.py": CODE}}})
    assert r["status"] in (200, 201), r
fn("onItems", "db", "items")
fn("otherContainer", "db", "other")
fn("otherAccount", "db", "items", conn="NOPE")
st = cc.CosmosStore()
def d(m, p, b=None, h=None):
    return cc.dispatch(st, m, p, {}, dict(h or {}, **{"x-vyomi-account": "cfacct"}), json.dumps(b).encode() if b is not None else b"", arm_state=a.state)
d("POST", "/dbs", {"id": "db"}); d("POST", "/dbs/db/colls", {"id": "items", "partitionKey": {"paths": ["/id"]}})
d("POST", "/dbs/db/colls", {"id": "other", "partitionKey": {"paths": ["/id"]}})
site = next(r for r in a.state.values() if isinstance(r, dict) and r.get("name") == "cfapp" and "_functions" in r)
log = lambda: [(e["function"], e["status"]) for e in site.get("_invocationlog", [])]

# change feed
r1 = d("POST", "/dbs/db/colls/items/docs", {"id": "1", "v": 1}); check("create ok", r1.status == 201)
d("POST", "/dbs/db/colls/items/docs", {"id": "2", "v": 2})
cf = lambda tok=None, **h: d("GET", "/dbs/db/colls/items/docs", None, dict({"a-im": "Incremental feed"}, **({"if-none-match": tok} if tok else {}), **h))
f1 = cf(); b1 = json.loads(f1.body)
check("feed from start returns both docs in order", f1.status == 200 and [x["id"] for x in b1["Documents"]] == ["1", "2"])
tok = f1.headers["etag"]
check("no change -> 304 with same continuation", cf(tok).status == 304)
d("PUT", "/dbs/db/colls/items/docs/1", {"id": "1", "v": 11})
f2 = cf(tok); check("update surfaces once", f2.status == 200 and [x["id"] for x in json.loads(f2.body)["Documents"]] == ["1"])
check("unchanged doc 2 not re-delivered", cf(f2.headers["etag"]).status == 304)
check("bad continuation 400", cf("abc").status == 400)
check("max item count", len(json.loads(cf(None, **{"x-ms-max-item-count": "1"}).body)["Documents"]) == 1)

# trigger
check("function ran per write (3 writes) only for the matching container+account", log() == [("onItems", 200)] * 3)
d("POST", "/dbs/db/colls/other/docs", {"id": "x"})
check("other container triggers its own function", log()[-1] == ("otherContainer", 200))
d("POST", "/dbs/db/colls/items/docs", {"id": "3", "boom": True})
check("handler error recorded, write still succeeds", log()[-1] == ("onItems", 500) and d("GET", "/dbs/db/colls/items/docs/3").status == 200)
n = len(log())
a.handle("PUT", f"{app}/functions/onItems", W, {"properties": {"isDisabled": True, "config": {"bindings": [{"type": "cosmosDBTrigger", "direction": "in", "name": "documents", "databaseName": "db", "containerName": "items", "connection": "COSMOS_CONN"}]}, "files": {"__init__.py": CODE}}})
d("POST", "/dbs/db/colls/items/docs", {"id": "4"})
check("disabled function does not run", len(log()) == n)
a.handle("POST", app + "/stop", W, None)
d("POST", "/dbs/db/colls/other/docs", {"id": "y"})
check("stopped app does not run triggers", len(log()) == n)
check("queries do not trigger", d("POST", "/dbs/db/colls/other/docs", {"query": "select * from c"}, {"x-ms-documentdb-isquery": "true"}).status == 200 and len(log()) == n)
print("ALL OK")
