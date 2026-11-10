"""Cloud SQL sql.projects.instances.reconcileNetworking (sqladmin v1beta4): POST returns an Operation; 404 on a missing instance."""
import os
import sys
import time

import requests

BASE = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000")
P = os.environ.get("PROJECT", "vyomi-project")
failed = False


def check(name, ok, detail=""):
    global failed
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + ("" if ok else f" :: {detail}"))
    failed = failed or not ok


def main():
    name = f"recon-{int(time.time()) % 1000000}"
    root = f"{BASE}/sql/v1beta4/projects/{P}/instances"
    r = requests.post(root, json={"name": name, "databaseVersion": "POSTGRES_15", "region": "us-central1",
                                  "settings": {"tier": "db-custom-1-3840"}}, timeout=60)
    check("insert instance", r.status_code == 200, r.text[:200])
    r = requests.post(f"{root}/{name}/reconcileNetworking", json={}, timeout=60)
    b = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    check("reconcileNetworking returns RECONCILE_NETWORKING operation",
          r.status_code == 200 and b.get("operationType") == "RECONCILE_NETWORKING" and b.get("kind") == "sql#operation", r.text[:200])
    r = requests.post(f"{root}/no-such-{name}/reconcileNetworking", json={}, timeout=60)
    check("reconcileNetworking on missing instance -> 404", r.status_code == 404, r.status_code)
    requests.delete(f"{root}/{name}", timeout=60)
    sys.exit(1 if failed else 0)


main()
