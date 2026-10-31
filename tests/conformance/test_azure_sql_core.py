"""Azure SQL data-plane conformance (v2.6.0) — the RDS/Cloud SQL peer.

Server/database management + REAL SQL (CREATE/INSERT/SELECT) on the SqlStore seam
(sqlite in Nano; Postgres behind the seam in Pro/Max). Runs on host + Pyodide.
"""
import json

try:
    from core.sql_store import InMemorySqlStore
    from core import azure_sql_core as az
except ImportError:  # pragma: no cover - Pyodide flat layout
    from sql_store import InMemorySqlStore  # type: ignore
    import azure_sql_core as az  # type: ignore


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def run(store=None):
    s = store or InMemorySqlStore()

    def call(m, p, b=b""):
        return az.dispatch(s, m, p, {}, {}, b if isinstance(b, bytes) else json.dumps(b).encode())

    _check("create server 201", call("PUT", "/servers/mysrv").status == 201)
    _check("create database 201", call("PUT", "/servers/mysrv/databases/appdb").status == 201)

    _check("CREATE TABLE ok",
           call("POST", "/servers/mysrv/databases/appdb/query",
                {"sql": "CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)"}).status == 200)
    call("POST", "/servers/mysrv/databases/appdb/query",
         {"sql": "INSERT INTO t (name) VALUES (?)", "params": ["alice"]})
    call("POST", "/servers/mysrv/databases/appdb/query",
         {"sql": "INSERT INTO t (name) VALUES (?)", "params": ["bob"]})
    r = json.loads(call("POST", "/servers/mysrv/databases/appdb/query",
                        {"sql": "SELECT id, name FROM t ORDER BY id"}).body)
    _check("real SQL SELECT returns rows",
           r["columns"] == ["id", "name"] and r["rowCount"] == 2 and r["rows"] == [[1, "alice"], [2, "bob"]])

    lst = json.loads(call("GET", "/servers/mysrv/databases").body)
    _check("list databases", [d["name"] for d in lst["value"]] == ["appdb"])

    # ── ARM-config enforcement (publicNetworkAccess / maxSizeBytes) ────────────────────
    def wire(m, p, b=b"", arm_state=None):
        return az.dispatch(s, m, p, {}, {}, b if isinstance(b, bytes) else json.dumps(b).encode(),
                           arm_state=arm_state)

    arm_disabled = {
        "/subscriptions/x/resourcegroups/rg/providers/microsoft.sql/servers/mysrv": {
            "id": "/subscriptions/x/resourceGroups/rg/providers/Microsoft.Sql/servers/mysrv",
            "_type": "Microsoft.Sql/servers", "properties": {"publicNetworkAccess": "Disabled"}},
    }
    r = wire("POST", "/servers/mysrv/databases/appdb/query", {"sql": "SELECT 1"}, arm_state=arm_disabled)
    _check("publicNetworkAccess=Disabled blocks the query data plane", r.status == 403)
    r = wire("POST", "/servers/mysrv/databases/appdb/query", {"sql": "SELECT 1"})
    _check("publicNetworkAccess absent (Enabled) allows the query data plane", r.status == 200)

    arm_tiny = {
        "/subscriptions/x/resourcegroups/rg/providers/microsoft.sql/servers/mysrv/databases/appdb": {
            "id": "/subscriptions/x/resourceGroups/rg/providers/Microsoft.Sql/servers/mysrv/databases/appdb",
            "_type": "Microsoft.Sql/servers/databases", "properties": {"maxSizeBytes": 1}},
    }
    r = wire("POST", "/servers/mysrv/databases/appdb/query",
             {"sql": "INSERT INTO t (name) VALUES ('tiny-cap')"}, arm_state=arm_tiny)
    _check("maxSizeBytes quota blocks further writes (Error 40544)",
           r.status == 400 and json.loads(r.body)["error"]["code"] == "DatabaseSizeQuotaExceeded")
    r = wire("POST", "/servers/mysrv/databases/appdb/query", {"sql": "SELECT 1"}, arm_state=arm_tiny)
    _check("maxSizeBytes quota does not block reads", r.status == 200)

    # ── Performance recommendations (real EXPLAIN QUERY PLAN, not a guess) ─────────────
    call("POST", "/servers/mysrv/databases/appdb/query", {"sql": "CREATE TABLE people (id INTEGER PRIMARY KEY, email TEXT)"})
    for i in range(50):
        call("POST", "/servers/mysrv/databases/appdb/query", {"sql": "INSERT INTO people (email) VALUES (?)", "params": [f"p{i}@x.com"]})
    for _ in range(4):
        call("POST", "/servers/mysrv/databases/appdb/query", {"sql": "SELECT * FROM people WHERE email = 'p1@x.com'"})
    recs = json.loads(call("GET", "/servers/mysrv/databases/appdb/recommendations").body)["value"]
    _check("a CREATE_INDEX recommendation is proposed for a scanned WHERE-equality column",
           any(r["table"] == "people" and r["column"] == "email" for r in recs))

    rec_id = next(r["id"] for r in recs if r["table"] == "people" and r["column"] == "email")
    apply_resp = call("POST", f"/servers/mysrv/databases/appdb/recommendations/{rec_id}/apply")
    _check("applying the recommendation succeeds", apply_resp.status == 200)
    idx = json.loads(call("POST", "/servers/mysrv/databases/appdb/query",
                          {"sql": "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='people'"}).body)
    _check("applying the recommendation actually creates the index", len(idx["rows"]) == 1)
    recs_after = json.loads(call("GET", "/servers/mysrv/databases/appdb/recommendations").body)["value"]
    _check("an applied recommendation is not proposed again",
           not any(r["id"] == rec_id for r in recs_after))

    # ── Automatic tuning: CREATE INDEX = On applies new recommendations without an apply call ──
    call("POST", "/servers/mysrv/databases/appdb/query", {"sql": "CREATE TABLE orders (id INTEGER PRIMARY KEY, status TEXT)"})
    for i in range(50):
        call("POST", "/servers/mysrv/databases/appdb/query", {"sql": "INSERT INTO orders (status) VALUES (?)", "params": ["open"]})
    arm_autotune = {
        "/subscriptions/x/resourcegroups/rg/providers/microsoft.sql/servers/mysrv/databases/appdb": {
            "id": "/subscriptions/x/resourceGroups/rg/providers/Microsoft.Sql/servers/mysrv/databases/appdb",
            "_type": "Microsoft.Sql/servers/databases",
            "properties": {"automaticTuning": {"options": {"createIndex": {"desiredState": "On"}}}}},
    }
    for _ in range(4):
        wire("POST", "/servers/mysrv/databases/appdb/query",
             {"sql": "SELECT * FROM orders WHERE status = 'open'"}, arm_state=arm_autotune)
    idx2 = json.loads(call("POST", "/servers/mysrv/databases/appdb/query",
                           {"sql": "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='orders'"}).body)
    _check("automatic tuning (CREATE INDEX=On) applies the index with no explicit apply call",
           len(idx2["rows"]) == 1)

    _check("delete database 200", call("DELETE", "/servers/mysrv/databases/appdb").status == 200)
    _check("query after delete → 400",
           call("POST", "/servers/mysrv/databases/appdb/query", {"sql": "SELECT 1"}).status == 400)

    print("\nAzure SQL data-plane conformance: ALL GREEN")
    return s


if __name__ == "__main__":
    run()
