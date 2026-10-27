"""GET /api/ec2/instances/{id} returns the instance (the console's detail view calls it)."""
import os
import sys

import requests

BASE = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000")
failed = False


def check(name, ok):
    global failed
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    failed = failed or not ok


def main():
    lst = requests.get(f"{BASE}/api/ec2/instances", timeout=30).json()["instances"]
    if not lst:
        r = requests.post(f"{BASE}/api/ec2/instances?auto_start=false", json={"name": "detail-probe"}, timeout=60)
        check("create instance", r.status_code < 300)
        lst = requests.get(f"{BASE}/api/ec2/instances", timeout=30).json()["instances"]
    iid = lst[0]["instance_id"]
    r = requests.get(f"{BASE}/api/ec2/instances/{iid}", timeout=30)
    check("detail returns 200", r.status_code == 200)
    check("detail has matching instance_id", r.status_code == 200 and r.json().get("instance_id") == iid)
    r = requests.get(f"{BASE}/api/ec2/instances/i-doesnotexist", timeout=30)
    check("unknown instance returns 404", r.status_code == 404)
    sys.exit(1 if failed else 0)


main()
