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

    _check("delete database 200", call("DELETE", "/servers/mysrv/databases/appdb").status == 200)
    _check("query after delete → 400",
           call("POST", "/servers/mysrv/databases/appdb/query", {"sql": "SELECT 1"}).status == 400)

    print("\nAzure SQL data-plane conformance: ALL GREEN")
    return s


if __name__ == "__main__":
    run()
