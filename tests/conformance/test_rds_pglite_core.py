"""RDS async data-plane + PGlite engine conformance.

Two things are proven here, both behind the SAME SqlStore seam and the SAME
`rds_core.aexecute_sql` data-plane entry:

  1. The ASYNC data-plane contract ({ok, columns, rows, rowcount}, instance-state
     gating) is identical to the sync one — proven on the sqlite3 default engine,
     green on host CPython AND Pyodide (run() below, via asyncio).

  2. The PGlite engine (Postgres compiled to WASM) is a faithful drop-in that
     gives REAL Postgres the sqlite default cannot: `$1` placeholders, SERIAL,
     RETURNING, ILIKE, `version()` = PostgreSQL. Proven where PGlite exists — the
     Pyodide+PGlite validator and the browser (run_pglite()).

So an unmodified psycopg2 / Postgres-SQL app validates against the in-browser sim
with genuine Postgres semantics, not a sqlite approximation.

Run on host:            python3 tests/conformance/test_rds_pglite_core.py
Run in Pyodide+PGlite:  harness awaits run_pglite() (globalThis.__nano_pglite_new shim)
"""
import asyncio

try:
    from core.sql_store import InMemorySqlStore, PGliteSqlStore
    from core import rds_core as rds
except ImportError:  # pragma: no cover - Pyodide flat layout
    from sql_store import InMemorySqlStore, PGliteSqlStore  # type: ignore
    import rds_core as rds  # type: ignore


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def _available(store, db_id):
    """Seed an available instance directly (control-plane status semantics are
    covered by test_rds_core.py; here we isolate the async data plane)."""
    store.put_instance(db_id, {"db_instance_identifier": db_id,
                               "db_instance_status": "available", "engine": "postgres"})


async def run_contract(store, ph):
    """Engine-agnostic async data-plane contract. `ph(i)` yields the i-th bind
    placeholder ('?' for sqlite, '$i' for Postgres) — the dialect seam."""
    _available(store, "appdb")

    # gating: SQL against a missing / non-available instance is rejected
    miss = await rds.aexecute_sql(store, "ghost", "SELECT 1")
    _check("async data-plane: missing instance rejected", miss["ok"] is False and miss["code"] == "DBInstanceNotFound")

    r = await rds.aexecute_sql(store, "appdb", "CREATE TABLE app (id INTEGER, name TEXT)")
    _check("create table ok", r["ok"] is True)

    ins = await rds.aexecute_sql(store, "appdb",
        f"INSERT INTO app (id, name) VALUES ({ph(1)}, {ph(2)})", [1, "alice"])
    _check("parameterized insert ok + rowcount 1", ins["ok"] and ins["rowcount"] == 1)
    await rds.aexecute_sql(store, "appdb",
        f"INSERT INTO app (id, name) VALUES ({ph(1)}, {ph(2)})", [2, "bob"])

    sel = await rds.aexecute_sql(store, "appdb",
        f"SELECT id, name FROM app WHERE id = {ph(1)} ORDER BY id", [1])
    _check("select columns", sel["columns"] == ["id", "name"])
    _check("select row round-trips (typed)", sel["rows"] == [[1, "alice"]])

    cnt = await rds.aexecute_sql(store, "appdb", "SELECT count(*) AS n FROM app")
    _check("aggregate sees both rows", int(cnt["rows"][0][0]) == 2)


async def run_pglite():
    """PGlite engine: the contract PLUS real-Postgres features sqlite can't match."""
    store = PGliteSqlStore()
    await run_contract(store, lambda i: f"${i}")

    _available(store, "pgapp")
    # SERIAL + RETURNING — Postgres identity + returning clause
    await rds.aexecute_sql(store, "pgapp",
        "CREATE TABLE users (id SERIAL PRIMARY KEY, email TEXT)")
    ret = await rds.aexecute_sql(store, "pgapp",
        "INSERT INTO users (email) VALUES ($1) RETURNING id", ["a@x.io"])
    _check("postgres SERIAL+RETURNING yields id=1", ret["rows"] == [[1]])
    await rds.aexecute_sql(store, "pgapp", "INSERT INTO users (email) VALUES ($1)", ["BOB@X.io"])
    # ILIKE — Postgres case-insensitive match (not in sqlite)
    il = await rds.aexecute_sql(store, "pgapp",
        "SELECT email FROM users WHERE email ILIKE $1 ORDER BY id", ["bob@%"])
    _check("postgres ILIKE matches case-insensitively", il["rows"] == [["BOB@X.io"]])
    # it really is Postgres
    ver = await rds.aexecute_sql(store, "pgapp", "SELECT version()")
    _check("engine is genuine PostgreSQL", "PostgreSQL" in ver["rows"][0][0])

    print("\nRESULT: PASS — RDS PGlite engine conforms (real Postgres) behind the SqlStore seam.")
    return 0


async def run_sqlite():
    """Default engine — proves the async path + contract on host AND Pyodide."""
    await run_contract(InMemorySqlStore(), lambda i: "?")
    print("\nRESULT: PASS — RDS async data-plane contract holds on the sqlite3 engine.")
    return 0


def run() -> int:
    return asyncio.run(run_sqlite())


if __name__ == "__main__":
    raise SystemExit(run())
