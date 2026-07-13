"""Phase 2 — the RDS/Cloud SQL data plane on a REAL Postgres backend.

Proves the SqlStore seam runs the cores' data plane against a live PostgreSQL
server, durable across a fresh store instance. Host-only (needs psycopg2 + a
running Postgres); not part of the WASM bundle.

Run:  <venv-with-psycopg2>/python tests/conformance/test_postgres_backed_store.py
"""
from core.postgres_backed_store import PostgresBackedSqlStore

DSN = "host=localhost port=35432 user=postgres password=cloudlearn dbname=postgres"
DBID = "v24pgtest"


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def run() -> int:
    PostgresBackedSqlStore(DSN).drop_schema(DBID)   # clean slate

    a = PostgresBackedSqlStore(DSN)
    a.execute_sql(DBID, "CREATE TABLE app (id SERIAL PRIMARY KEY, name TEXT, n INT)")
    r = a.execute_sql(DBID, "INSERT INTO app (name, n) VALUES (%s, %s) RETURNING id", ["alice", 42])
    _check("postgres RETURNING works (real pg dialect)", r["rows"][0][0] == 1)

    # fresh store — must see the committed row from a NEW connection to real pg
    b = PostgresBackedSqlStore(DSN)
    sel = b.execute_sql(DBID, "SELECT name, n FROM app WHERE n = %s", [42])
    _check("row survives a fresh backed store (real Postgres persisted it)",
           sel["rows"] == [["alice", 42]])
    _check("columns reflect the real pg result", sel["columns"] == ["name", "n"])

    # a genuinely-Postgres feature the sqlite default can't do: ILIKE
    il = b.execute_sql(DBID, "SELECT name FROM app WHERE name ILIKE %s", ["ALI%"])
    _check("Postgres ILIKE (dialect fidelity beyond sqlite)", il["rows"] == [["alice"]])

    PostgresBackedSqlStore(DSN).drop_schema(DBID)   # cleanup
    print("\nPHASE 2: ALL GREEN — RDS/Cloud SQL data plane runs on a REAL Postgres backend "
          "(RETURNING/SERIAL/ILIKE, fresh-store durable)")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
