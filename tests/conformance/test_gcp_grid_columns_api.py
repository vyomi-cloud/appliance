"""Every column the GCP console grid shows for a freshly created VPC network, Firestore database and
Cloud Function (default form values) must resolve to a real value from the list API — no blank
"-" cells. Columns come from /api/gcp/catalog, exactly as the console reads them."""
import os
import sys
import uuid

import requests

BASE = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000")
P = "vyomi-project"
failed = False


def check(name, ok, extra=""):
    global failed
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{'' if ok else ' ' + str(extra)}")
    failed = failed or not ok


def get_path(obj, path):
    for part in path.split("."):
        if not isinstance(obj, dict):
            return None
        obj = obj.get(part)
    return obj


# Columns the console derives from other API fields (decorateGcpItems in the console):
# the API resource carries the source field, not the column key.
DERIVED = {("vpc", "mode"): "autoCreateSubnetworks"}


def blank(v):
    return v is None or v == "" or v == [] or v == {}


def columns(key):
    cat = requests.get(f"{BASE}/api/gcp/catalog", timeout=60).json()
    svc = next(s for s in cat["services"] if s["key"] == key)
    return svc["columns"], svc["collection_path"].replace("{project}", P).replace("{region}", "us-central1")


def grid_row(key, name):
    cols, path = columns(key)
    data = requests.get(f"{BASE}{path}", timeout=60).json()
    items = data.get("items") or data.get("functions") or data.get("databases") or []
    row = next((i for i in items if str(i.get("name", "")).split("/")[-1] == name), None)
    check(f"{key}: created resource {name} is listed", row is not None)
    for path_, label in cols:
        if row is not None:
            src = DERIVED.get((key, path_))
            val = get_path(row, src or path_)
            ok = isinstance(val, bool) if src else not blank(val)
            check(f"{key}: column '{label}' ({src or path_}) filled", ok, val)


def main():
    tag = uuid.uuid4().hex[:6]
    net, db, fn = f"gridnet-{tag}", f"griddb-{tag}", f"gridfn-{tag}"
    r = requests.post(f"{BASE}/api/gcp/compute/v1/projects/{P}/global/networks", json={"name": net}, timeout=60)
    check("create VPC network", r.status_code < 300, r.text[:120])
    r = requests.post(f"{BASE}/api/gcp/firestore/v1/projects/{P}/databases", json={"name": db}, timeout=60)
    check("create Firestore database", r.status_code < 300, r.text[:120])
    r = requests.post(f"{BASE}/api/gcp/cloudfunctions/v2/projects/{P}/locations/us-central1/functions",
                      json={"name": fn, "runtime": "python312", "entryPoint": "hello_world"}, timeout=60)
    check("create Cloud Function", r.status_code < 300, r.text[:120])
    grid_row("vpc", net)
    grid_row("firestore", db)
    grid_row("functions", fn)
    requests.delete(f"{BASE}/api/gcp/compute/v1/projects/{P}/global/networks/{net}", timeout=60)
    requests.delete(f"{BASE}/api/gcp/firestore/v1/projects/{P}/databases/{db}", timeout=60)
    requests.delete(f"{BASE}/api/gcp/cloudfunctions/v2/projects/{P}/locations/us-central1/functions/{fn}", timeout=60)
    sys.exit(1 if failed else 0)


main()
