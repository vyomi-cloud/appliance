"""RDS Data API core conformance — `boto3.client('rds-data')` over HTTP.

Proves the rest-json Data API wire (Execute / BatchExecute / transactions, AWS-typed
field values, named `:params`) maps faithfully onto the SqlStore data plane. Same
file, two engines behind ONE seam:

  - sqlite3 default — async contract green on host CPython AND Pyodide (run()).
  - PGlite (real Postgres) — run_pglite(), on the Pyodide+PGlite validator.

This is the relational path that survives the HTTP relay (no Postgres-wire TCP), so
an unmodified external app validates its SQL against the in-browser sim.

Run on host:           python3 tests/conformance/test_rds_data_core.py
Run in Pyodide+PGlite: harness awaits run_pglite()
"""
import asyncio
import json

try:
    from core.sql_store import InMemorySqlStore, PGliteSqlStore
    from core import rds_data_core as data
except ImportError:  # pragma: no cover - Pyodide flat layout
    from sql_store import InMemorySqlStore, PGliteSqlStore  # type: ignore
    import rds_data_core as data  # type: ignore

ARN = "arn:aws:rds:us-east-1:123456789012:cluster:appdb"


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def _available(store, db_id="appdb"):
    store.put_instance(db_id, {"db_instance_identifier": db_id,
                               "db_instance_status": "available", "engine": "postgres"})


async def _exec(store, sql, parameters=None, meta=False):
    body = {"resourceArn": ARN, "database": "appdb", "sql": sql}
    if parameters is not None:
        body["parameters"] = parameters
    if meta:
        body["includeResultMetadata"] = True
    return await data.dispatch(store, "/Execute", body)


async def run_contract(store):
    _available(store)

    # missing instance → BadRequestException 400
    miss = await data.dispatch(store, "/Execute",
        {"resourceArn": "arn:aws:rds:us-east-1:123456789012:cluster:ghost", "sql": "SELECT 1"})
    _check("missing instance → 400 BadRequestException",
           miss.status == 400 and miss.headers.get("x-amzn-errortype") == "BadRequestException")

    _check("create table → 200", (await _exec(store, "CREATE TABLE app (id INTEGER, name TEXT, active BOOLEAN)")).status == 200)

    # parameterized INSERT with AWS-typed named params; DML → numberOfRecordsUpdated
    ins = await _exec(store, "INSERT INTO app (id, name, active) VALUES (:id, :name, :active)",
        [{"name": "id", "value": {"longValue": 1}},
         {"name": "name", "value": {"stringValue": "alice"}},
         {"name": "active", "value": {"booleanValue": True}}])
    _check("insert → numberOfRecordsUpdated 1", ins.body.get("numberOfRecordsUpdated") == 1)
    await _exec(store, "INSERT INTO app (id, name, active) VALUES (:id, :name, :active)",
        [{"name": "id", "value": {"longValue": 2}},
         {"name": "name", "value": {"stringValue": "bob"}},
         {"name": "active", "value": {"booleanValue": False}}])

    # SELECT with metadata → columnMetadata + typed records
    sel = await _exec(store, "SELECT id, name FROM app WHERE id = :id ORDER BY id",
                      [{"name": "id", "value": {"longValue": 1}}], meta=True)
    _check("select columnMetadata names", [c["name"] for c in sel.body["columnMetadata"]] == ["id", "name"])
    _check("select records typed (longValue + stringValue)",
           sel.body["records"] == [[{"longValue": 1}, {"stringValue": "alice"}]])
    _check("select numberOfRecordsUpdated is 0", sel.body["numberOfRecordsUpdated"] == 0)

    # NULL round-trips as isNull
    await _exec(store, "INSERT INTO app (id, name, active) VALUES (:id, :name, :active)",
        [{"name": "id", "value": {"longValue": 3}},
         {"name": "name", "value": {"isNull": True}},
         {"name": "active", "value": {"booleanValue": True}}])
    nullsel = await _exec(store, "SELECT name FROM app WHERE id = :id", [{"name": "id", "value": {"longValue": 3}}])
    _check("NULL comes back as isNull", nullsel.body["records"] == [[{"isNull": True}]])

    # BatchExecuteStatement → one updateResult per parameter set
    batch = await data.dispatch(store, "/BatchExecute", {"resourceArn": ARN,
        "sql": "INSERT INTO app (id, name) VALUES (:id, :name)",
        "parameterSets": [
            [{"name": "id", "value": {"longValue": 10}}, {"name": "name", "value": {"stringValue": "x"}}],
            [{"name": "id", "value": {"longValue": 11}}, {"name": "name", "value": {"stringValue": "y"}}]]})
    _check("batch → 2 updateResults", len(batch.body["updateResults"]) == 2)
    cnt = await _exec(store, "SELECT count(*) FROM app")
    _check("batch rows landed (5 total)", int(cnt.body["records"][0][0]["longValue"]) == 5)

    # SQL error → BadRequestException 400
    err = await _exec(store, "SELECT * FROM nope_no_table")
    _check("bad SQL → 400 BadRequestException",
           err.status == 400 and err.headers.get("x-amzn-errortype") == "BadRequestException")

    # transaction ops are accepted with valid shapes (autocommit; see module docs)
    begin = await data.dispatch(store, "/BeginTransaction", {"resourceArn": ARN})
    _check("BeginTransaction → transactionId", "transactionId" in begin.body)
    commit = await data.dispatch(store, "/CommitTransaction", {"transactionId": begin.body["transactionId"]})
    _check("CommitTransaction → status", commit.body.get("transactionStatus") == "Transaction Committed")


async def run_pglite():
    store = PGliteSqlStore()
    await run_contract(store)
    # prove the engine really is Postgres (named :params rewritten to $N under the hood)
    _available(store, "pg")
    arn2 = "arn:aws:rds:us-east-1:123456789012:cluster:pg"
    v = await data.dispatch(store, "/Execute", {"resourceArn": arn2, "sql": "SELECT version()"})
    _check("engine is genuine PostgreSQL", "PostgreSQL" in v.body["records"][0][0]["stringValue"])
    print("\nRESULT: PASS — RDS Data API conforms on PGlite (real Postgres) via the SqlStore seam.")
    return 0


async def run_sqlite():
    await run_contract(InMemorySqlStore())
    print("\nRESULT: PASS — RDS Data API conforms on the sqlite3 engine.")
    return 0


def run() -> int:
    return asyncio.run(run_sqlite())


if __name__ == "__main__":
    raise SystemExit(run())
