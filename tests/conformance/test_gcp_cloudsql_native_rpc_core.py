"""Cloud SQL Admin RPCs on their NATIVE paths — POST .../instances/{i}/restart and
.../restoreBackup (what gcloud and the client libraries send) — as well as the older colon
form; a backupRun carries real timestamps. Host + Pyodide."""
import json
import types

try:
    from core import gcp_cloudsql_core as sql
    from core.sql_store import SqlStore
except ImportError:  # pragma: no cover - Pyodide flat layout
    import gcp_cloudsql_core as sql  # type: ignore
    from sql_store import SqlStore  # type: ignore

B = "/sql/v1beta4/projects/p1/instances"


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def run(store=None):
    s = store or SqlStore()

    def call(m, path, body=None):
        r = sql.dispatch(s, m, path, {}, {}, json.dumps(body).encode() if body is not None else b"")
        return r.status, (json.loads(r.body) if r.body else {})

    call("POST", B, {"name": "i1", "databaseVersion": "POSTGRES_15", "region": "us-central1"})
    call("POST", f"{B}/i1/databases", {"name": "keep"})
    st, b = call("POST", f"{B}/i1/backupRuns", {"description": "d"})
    _check("backupRun has a real enqueuedTime", st == 200 and b.get("enqueuedTime", "").endswith("Z"))
    call("DELETE", f"{B}/i1/databases/keep")
    st, op = call("POST", f"{B}/i1/restoreBackup", {"restoreBackupContext": {"backupRunId": b["id"]}})
    _check("native /restoreBackup path restores", st == 200 and
           any(d["name"] == "keep" for d in call("GET", f"{B}/i1/databases")[1].get("items", [])))
    _check("native /restart path", call("POST", f"{B}/i1/restart")[0] == 200)
    _check("colon :restart still accepted", call("POST", f"{B}/i1:restart")[0] == 200)
    return s


if __name__ == "__main__":
    run()
    print("\nCloud SQL native RPC paths: ALL GREEN")
