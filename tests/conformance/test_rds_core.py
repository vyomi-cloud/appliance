"""RDS core conformance — the acceptance gate for the WASM extraction.

This SAME test runs on two substrates and must be green on both:
  - host CPython (proxy for the Pro/Max appliance handler)
  - Pyodide / WASM (the Nano substrate)

It asserts the NATIVE AWS RDS wire semantics — the Query protocol (form-encoded
Action) with XML responses (<CreateDBInstanceResult><DBInstance>...), endpoint
address/port, lifecycle status transitions, snapshots, <ErrorResponse> with
<Code> — AND the REAL SQL data plane (CREATE TABLE / INSERT / SELECT actually
run, via the SqlStore's sqlite3 engine). No network, no fastapi/boto3/psycopg2.

Pyodide note: sqlite3 is a loadable package there — the harness calls
pyodide.loadPackage("sqlite3") before importing this. On host it's stdlib.

Run on host:    python3 tests/conformance/test_rds_core.py
Run in Pyodide: loaded by wasm/ harness (same file).
"""

# Allow running both as a repo script (host) and from a flat FS (Pyodide).
try:
    from core.sql_store import InMemorySqlStore
    from core import rds_core as rds
except ImportError:  # pragma: no cover - Pyodide flat layout
    from sql_store import InMemorySqlStore  # type: ignore
    import rds_core as rds  # type: ignore


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def run() -> int:
    st = InMemorySqlStore()

    # 1. CreateDBInstance -> XML result with DBInstance + endpoint
    r = rds.dispatch(st, {"Action": "CreateDBInstance", "DBInstanceIdentifier": "appdb",
                          "Engine": "postgres", "MasterUsername": "appuser",
                          "MasterUserPassword": "s3cret", "AllocatedStorage": "20"})
    _check("create 200", r.status == 200)
    xml = r.body
    _check("create CreateDBInstanceResult", "<CreateDBInstanceResult>" in xml)
    _check("create DBInstanceIdentifier", "<DBInstanceIdentifier>appdb</DBInstanceIdentifier>" in xml)
    _check("create status available", "<DBInstanceStatus>available</DBInstanceStatus>" in xml)
    _check("create endpoint address", "<Address>appdb.nano-rds.local</Address>" in xml)
    _check("create endpoint port 5432", "<Port>5432</Port>" in xml)
    _check("create engine postgres", "<Engine>postgres</Engine>" in xml)

    # 2. CreateDBInstance again -> DBInstanceAlreadyExists XML error
    dup = rds.dispatch(st, {"Action": "CreateDBInstance", "DBInstanceIdentifier": "appdb"})
    _check("duplicate 400", dup.status == 400)
    _check("duplicate ErrorResponse", "<ErrorResponse" in dup.body)
    _check("duplicate code DBInstanceAlreadyExists", "<Code>DBInstanceAlreadyExists</Code>" in dup.body)

    # 3. DescribeDBInstances -> lists the instance
    d = rds.dispatch(st, {"Action": "DescribeDBInstances"})
    _check("describe lists appdb", "<DBInstanceIdentifier>appdb</DBInstanceIdentifier>" in d.body)
    _check("describe wraps DBInstances", "<DBInstances>" in d.body)

    # 4. mysql engine maps to port 3306
    rds.dispatch(st, {"Action": "CreateDBInstance", "DBInstanceIdentifier": "shopdb", "Engine": "mysql"})
    one = rds.dispatch(st, {"Action": "DescribeDBInstances", "DBInstanceIdentifier": "shopdb"})
    _check("mysql endpoint port 3306", "<Port>3306</Port>" in one.body and "<Engine>mysql</Engine>" in one.body)

    # 5. REAL SQL data plane — CREATE TABLE / INSERT / SELECT actually run
    cr = rds.execute_sql(st, "appdb", "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, age INTEGER)")
    _check("create table ok", cr["ok"] is True)
    ins = rds.execute_sql(st, "appdb", "INSERT INTO users (name, age) VALUES (?, ?)", ["Ada", 36])
    _check("insert ok rowcount 1", ins["ok"] and ins["rowcount"] == 1)
    rds.execute_sql(st, "appdb", "INSERT INTO users (name, age) VALUES (?, ?)", ["Bob", 41])
    sel = rds.execute_sql(st, "appdb", "SELECT name, age FROM users ORDER BY age")
    _check("select columns", sel["columns"] == ["name", "age"])
    _check("select rows round-trip", sel["rows"] == [["Ada", 36], ["Bob", 41]])
    agg = rds.execute_sql(st, "appdb", "SELECT COUNT(*) AS n, AVG(age) AS avg_age FROM users")
    _check("aggregate query works", agg["rows"][0][0] == 2 and abs(agg["rows"][0][1] - 38.5) < 1e-9)

    # 5b. data plane is isolated per instance (shopdb has no users table)
    miss = rds.execute_sql(st, "shopdb", "SELECT * FROM users")
    _check("per-instance isolation (no shared table)", miss["ok"] is False and miss["code"] == "SQLError")

    # 5c. SQL on a missing / stopped instance is rejected
    nf = rds.execute_sql(st, "ghostdb", "SELECT 1")
    _check("sql on missing instance DBInstanceNotFound", nf["ok"] is False and nf["code"] == "DBInstanceNotFound")
    rds.dispatch(st, {"Action": "StopDBInstance", "DBInstanceIdentifier": "shopdb"})
    stopped = rds.execute_sql(st, "shopdb", "SELECT 1")
    _check("sql on stopped instance rejected", stopped["ok"] is False and stopped["code"] == "InvalidDBInstanceState")

    # 6. Lifecycle: StartDBInstance brings shopdb back, SQL works again
    rds.dispatch(st, {"Action": "StartDBInstance", "DBInstanceIdentifier": "shopdb"})
    back = rds.execute_sql(st, "shopdb", "SELECT 1 AS one")
    _check("start re-enables SQL", back["ok"] and back["rows"] == [[1]])

    # 7. ModifyDBInstance changes the class
    mod = rds.dispatch(st, {"Action": "ModifyDBInstance", "DBInstanceIdentifier": "appdb",
                            "DBInstanceClass": "db.r6g.large"})
    _check("modify applied", "<DBInstanceClass>db.r6g.large</DBInstanceClass>" in mod.body)

    # 8. Snapshots
    snap = rds.dispatch(st, {"Action": "CreateDBSnapshot", "DBInstanceIdentifier": "appdb",
                             "DBSnapshotIdentifier": "appdb-snap-1"})
    _check("snapshot created", "<DBSnapshotIdentifier>appdb-snap-1</DBSnapshotIdentifier>" in snap.body)
    ds = rds.dispatch(st, {"Action": "DescribeDBSnapshots", "DBInstanceIdentifier": "appdb"})
    _check("describe snapshots lists it", "<DBSnapshotIdentifier>appdb-snap-1</DBSnapshotIdentifier>" in ds.body)

    # 9. DeleteDBInstance -> status deleting; then describe 404s
    dl = rds.dispatch(st, {"Action": "DeleteDBInstance", "DBInstanceIdentifier": "appdb"})
    _check("delete status deleting", "<DBInstanceStatus>deleting</DBInstanceStatus>" in dl.body)
    gone = rds.dispatch(st, {"Action": "DescribeDBInstances", "DBInstanceIdentifier": "appdb"})
    _check("describe deleted 404 DBInstanceNotFound", gone.status == 404 and "<Code>DBInstanceNotFound</Code>" in gone.body)

    # 10. Unknown / missing action
    unk = rds.dispatch(st, {"Action": "Frobnicate"})
    _check("unknown action InvalidAction", "<Code>InvalidAction</Code>" in unk.body)
    noact = rds.dispatch(st, {})
    _check("missing action MissingAction", "<Code>MissingAction</Code>" in noact.body)

    print("\nRESULT: PASS — RDS core conforms (native Query-protocol wire + real SQL) on this substrate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
