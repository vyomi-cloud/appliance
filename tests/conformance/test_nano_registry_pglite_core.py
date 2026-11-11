"""nano_registry builds RDS / Cloud SQL stores with the engine the boot asked for, so cached references stay live.

Regression: nano-boot swapped registry['rds'] to PGlite AFTER aws_core_adapter had imported the registry (RDB = _R["rds"]), leaving the
console writing to a dead InMemorySqlStore that was never snapshotted (databases vanished on reload).
Run on host: PYTHONPATH=.:wasm/core python3 tests/conformance/test_nano_registry_pglite_core.py
"""
try:
    from core import nano_registry as reg
    from core import nano_persist as P
except ImportError:  # pragma: no cover - Pyodide flat layout
    import nano_registry as reg  # type: ignore
    import nano_persist as P  # type: ignore


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"[PASS] {name}")


def run():
    reg._REG = None
    reg.USE_PGLITE = False
    r = reg.get()
    _check("default registry uses the sqlite store", type(r["rds"]).__name__ == "InMemorySqlStore")

    reg._REG = None
    reg.USE_PGLITE = True
    try:
        r = reg.get()
        _check("USE_PGLITE builds PGliteSqlStore for rds", type(r["rds"]).__name__ == "PGliteSqlStore")
        _check("USE_PGLITE builds PGliteSqlStore for gcp_sql", type(r["gcp_sql"]).__name__ == "PGliteSqlStore")
        cached = r["rds"]                                   # what an adapter caches at import
        _check("cross-store links point at the live rds store", r["rds"].cw_store is r["cw"] and r["az_arm"].sql_store is cached)
        _check("the store an adapter cached is the store persistence snapshots", reg.get()["rds"] is cached)
        from core import rds_core as rc
        rc.dispatch(cached, dict(Action="CreateDBInstance", DBInstanceIdentifier="pg1", DBInstanceClass="db.t3.micro", Engine="postgres",
                                 MasterUsername="u", MasterUserPassword="password123", AllocatedStorage=20))
        snap = P.capture_registry()
        _check("snapshot of the registry contains the database created through the cached store", "pg1" in snap["rds"]["state"]["db_instances"])
    finally:
        reg._REG = None
        reg.USE_PGLITE = False
    print("NANO REGISTRY PGLITE OK")


if __name__ == "__main__":
    run()
