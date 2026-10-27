"""An instance launched with default values (default VPC/subnet) gets a public IPv4 + DNS, like real EC2."""
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
    r = requests.post(f"{BASE}/api/ec2/instances?auto_start=false", json={"name": "public-ip-probe"}, timeout=60)
    check("create instance with defaults", r.status_code < 300)
    inst = r.json().get("instance", r.json()) if r.status_code < 300 else {}
    iid = inst.get("instance_id", "")
    full = requests.get(f"{BASE}/api/ec2/instances/{iid}", timeout=30).json() if iid else {}
    full = full.get("instance", full)
    ip = full.get("public_ip") or ""
    check("default launch has a public IPv4", bool(ip))
    check("default launch has a public DNS name", ip != "" and ip.replace(".", "-") in (full.get("public_dns") or ""))
    if iid:
        requests.delete(f"{BASE}/api/ec2/instances/{iid}", timeout=30)
    sys.exit(1 if failed else 0)


main()
