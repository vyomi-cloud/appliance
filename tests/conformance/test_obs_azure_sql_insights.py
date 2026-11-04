"""Azure SQL Query Performance Insight / overview / audit from MEASURED statement timings. Hermetic."""
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
call("PUT", "/servers/srv"); call("PUT", "/servers/srv/databases/db1")
st, empty = call("GET", "/servers/srv/databases/db1/queryinsights")
ck("idle database: empty views", st == 200 and empty["overview"]["statements"] == 0 and empty["topQueries"] == [] and empty["audit"] == [] and empty["timeline"] == [])
ck("unknown db 404", call("GET", "/servers/srv/databases/nope/queryinsights")[0] == 404)
q = lambda sql: call("POST", "/servers/srv/databases/db1/query", {"sql": sql})
q("CREATE TABLE t(id INTEGER, v TEXT)")
for i in range(5):
    q(f"INSERT INTO t VALUES ({i}, 'x{i}')")
for i in range(3):
    q(f"SELECT * FROM t WHERE id = {i}")
ck("bad sql is 400", q("SELEC nonsense")[0] == 400)
st, d = call("GET", "/servers/srv/databases/db1/queryinsights")
ck("overview counts measured statements", d["overview"]["statements"] == 10 and d["overview"]["failed"] == 1)
ck("literals normalised -> 5 inserts are one query", any(t["executions"] == 5 and "INSERT" in t["queryText"] for t in d["topQueries"]))
ck("selects grouped", any(t["executions"] == 3 for t in d["topQueries"]))
ck("top sorted by total duration", [t["totalMs"] for t in d["topQueries"]] == sorted((t["totalMs"] for t in d["topQueries"]), reverse=True))
ck("timeline buckets", sum(b["count"] for b in d["timeline"]) == 10)
ck("audit has failure with message", any((not a["succeeded"]) and a["errorMessage"] for a in d["audit"]))
ck("size from engine", d["overview"]["sizeBytes"] > 0)
print("FAILED:", F) if F else print("ALL PASS")
raise SystemExit(1 if F else 0)
