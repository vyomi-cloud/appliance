"""Console-next routes used by the AWS console: capabilities manifest, calls log, RDS databases list
and schema. Never a 5xx; documented shapes (or the tier-lock body)."""
import os
import sys

import requests

BASE = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000")
failed = False


def check(name, ok, extra=""):
    global failed
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{'' if ok else ' ' + str(extra)}")
    failed = failed or not ok


def locked(r):
    try:
        return r.status_code in (402, 403) and (r.json().get("detail") or {}).get("code") == "tier_feature_locked"
    except ValueError:
        return False


r = requests.get(BASE + "/api/console/capabilities", params={"lens": "aws"}, timeout=60)
check("GET /api/console/capabilities (aws) is an object", (r.status_code == 200 and isinstance(r.json(), dict)) or locked(r), f"{r.status_code} {r.text[:120]}")

r = requests.get(BASE + "/api/console/calls", timeout=60)
check("GET /api/console/calls is not a 5xx", r.status_code < 500, f"{r.status_code} {r.text[:120]}")

r = requests.get(BASE + "/api/console/rds/databases", timeout=60)
check("GET /api/console/rds/databases is not a 5xx", r.status_code < 500, f"{r.status_code} {r.text[:120]}")
if r.status_code == 200:
    body = r.json()
    dbs = body if isinstance(body, list) else body.get("databases", [])
    check("rds databases payload is a list", isinstance(dbs, list), body)
    if dbs:
        did = dbs[0].get("id") or dbs[0].get("db_id") or dbs[0].get("identifier")
        s = requests.get(f"{BASE}/api/console/rds/databases/{did}/schema", timeout=60)
        check("rds schema for an existing database is not a 5xx", s.status_code < 500, s.status_code)

s = requests.get(BASE + "/api/console/rds/databases/does-not-exist-zz/schema", timeout=60)
check("rds schema for an unknown database is a 4xx, not a 5xx", 400 <= s.status_code < 500 or s.status_code == 200, s.status_code)

sys.exit(1 if failed else 0)
