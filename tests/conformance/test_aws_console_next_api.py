"""AWS console-next routes (/api/console/*): capabilities, the RDS sql-console data plane
(databases, execute, schema) and the glass-box call log the console reads. Plain HTTP against
the same paths the widgets call."""
import os
import sys

import requests

BASE = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000")
failed = False


def check(name, ok, extra=""):
    global failed
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{'' if ok else ' ' + str(extra)[:300]}")
    failed = failed or not ok


def call(method, path, **kw):
    r = requests.request(method, BASE + path, timeout=60, **kw)
    try:
        body = r.json()
    except Exception:
        body = {}
    return r.status_code, body


s, b = call("GET", "/api/console/capabilities?lens=aws")
check("capabilities: aws lens with widget modes", s == 200 and b.get("lens") == "aws" and "sql-console" in b.get("widgets", {}), b)

s, b = call("GET", "/api/console/rds/databases")
dbs = b.get("databases", [])
check("rds: databases listed with engine/status", s == 200 and dbs and all(d.get("db_instance_identifier") and d.get("engine") and d.get("status") for d in dbs), b)
db = b.get("default") or (dbs[0]["db_instance_identifier"] if dbs else "")

s, b = call("POST", "/api/console/rds/execute", json={"db": db, "sql": "select 1 as x"})
check("rds: execute select returns columns and rows", s == 200 and b.get("ok") and b.get("columns") == ["x"] and b.get("rows") == [[1]], b)
s, b = call("POST", "/api/console/rds/execute", json={"db": db, "sql": "  "})
check("rds: execute without sql is a 400", s == 400, b)

s, b = call("GET", f"/api/console/rds/databases/{db}/schema")
check("rds: schema returns the instance and its tables", s == 200 and b.get("db_instance_identifier") == db and isinstance(b.get("tables"), list), b)

s, b = call("GET", "/api/console/calls?limit=5")
calls = b.get("calls", [])
check("calls: glass-box log records the console calls", s == 200 and any(c.get("service") == "rds" for c in calls), b)

s, b = call("GET", "/api/console/conformance")
check("conformance: rollup with per-service signals", s == 200 and b.get("rollup", {}).get("services") and "s3" in b.get("services", {}), b)

sys.exit(1 if failed else 0)
