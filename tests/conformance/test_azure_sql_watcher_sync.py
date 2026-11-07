"""Azure SQL database watcher + Data Sync against the real SQL engine. Run: PYTHONPATH=. python tests/conformance/test_azure_sql_watcher_sync.py"""
import json
from core.sql_store import InMemorySqlStore
from core import azure_sql_core as az

F = []
def ck(n, c):
    print(("PASS " if c else "FAIL ") + n)
    if not c: F.append(n)

s = InMemorySqlStore()
def call(m, p, b=None):
    r = az.dispatch(s, m, p, {}, {}, json.dumps(b).encode() if b is not None else b"")
    return r.status, (json.loads(r.body) if getattr(r, "body", None) else {})
for d in ("hub", "member"):
    call("PUT", "/servers/srv"); call("PUT", f"/servers/srv/databases/{d}")
q = lambda d, sql: call("POST", f"/servers/srv/databases/{d}/query", {"sql": sql})
q("hub", "CREATE TABLE people(id INTEGER PRIMARY KEY, name TEXT, city TEXT)")
for i in range(1, 6):
    q("hub", f"INSERT INTO people VALUES ({i}, 'p{i}', 'c{i}')")

# watcher
st, smp = call("POST", "/servers/srv/databases/hub/watcher/collect")
ck("sample has real table row counts", st == 200 and smp["tables"] == [{"name": "people", "rows": 5}] and smp["totalRows"] == 5 and smp["sizeBytes"] > 0)
for i in range(6, 20):
    q("hub", f"INSERT INTO people VALUES ({i}, 'p{i}', 'c{i}')")
q("hub", "SELEC bad")
st, smp2 = call("POST", "/servers/srv/databases/hub/watcher/collect")
ck("second sample reflects growth + failure", smp2["totalRows"] == 19 and smp2["failed"] >= 1)
st, w = call("GET", "/servers/srv/databases/hub/watcher")
ck("series + alerts computed", w["sampleCount"] == 2 and any("failed" in a["message"] for a in w["alerts"]) and any("grew" in a["message"] for a in w["alerts"]))
ck("watcher unknown db 404", call("GET", "/servers/srv/databases/zzz/watcher")[0] == 404)

# sync
st, r = call("POST", "/servers/srv/databases/hub/sync", {"memberDatabase": "member"})
ck("first sync creates table + inserts all rows", st == 200 and r["tables"][0]["created"] and r["tables"][0]["inserted"] == 19)
ck("rows really in member", q("member", "SELECT COUNT(*) FROM people")[1]["rows"][0][0] == 19)
q("hub", "UPDATE people SET city='NEW' WHERE id=1"); q("hub", "DELETE FROM people WHERE id=2")
st, r = call("POST", "/servers/srv/databases/hub/sync", {"memberDatabase": "member"})
t = r["tables"][0]
ck("incremental: 1 update, no delete by default", t["updated"] == 1 and t["inserted"] == 0 and t["deleted"] == 0)
ck("update landed", q("member", "SELECT city FROM people WHERE id=1")[1]["rows"][0][0] == "NEW")
q("member", "UPDATE people SET city='LOCAL' WHERE id=3")
st, r = call("POST", "/servers/srv/databases/hub/sync", {"memberDatabase": "member", "conflict": "skip"})
ck("skip keeps the member's divergent row", r["tables"][0]["skipped"] == 1 and q("member", "SELECT city FROM people WHERE id=3")[1]["rows"][0][0] == "LOCAL")
st, r = call("POST", "/servers/srv/databases/hub/sync", {"memberDatabase": "member", "deleteMissing": True})
ck("hub-wins overwrites + deleteMissing removes", r["tables"][0]["deleted"] == 1 and q("member", "SELECT COUNT(*) FROM people")[1]["rows"][0][0] == 18
   and q("member", "SELECT city FROM people WHERE id=3")[1]["rows"][0][0] == "c3")
ck("history kept", len(call("GET", "/servers/srv/databases/hub/sync")[1]["syncs"]) == 4)
ck("same db rejected", call("POST", "/servers/srv/databases/hub/sync", {"memberDatabase": "hub"})[0] == 400)
ck("missing member 404", call("POST", "/servers/srv/databases/hub/sync", {"memberDatabase": "nope"})[0] == 404)
ck("bad table reported", call("POST", "/servers/srv/databases/hub/sync", {"memberDatabase": "member", "tables": ["ghost"]})[1]["status"] == "CompletedWithErrors")
ck("bad conflict 400", call("POST", "/servers/srv/databases/hub/sync", {"memberDatabase": "member", "conflict": "x"})[0] == 400)
print("FAILED:", F) if F else print("ALL PASS")
raise SystemExit(1 if F else 0)
