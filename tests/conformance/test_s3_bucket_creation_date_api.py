"""The S3 buckets grid column 'Creation date' reads `creation_date`; the list API must fill it."""
import os
import sys
import uuid

import requests

BASE = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000")
failed = False


def check(name, ok):
    global failed
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    failed = failed or not ok


def main():
    name = "cdate-" + uuid.uuid4().hex[:8]
    r = requests.post(f"{BASE}/api/s3/buckets/{name}", timeout=30)
    check("create bucket", r.status_code < 300)
    rows = requests.get(f"{BASE}/api/s3/buckets", timeout=30).json()["buckets"]
    row = next((b for b in rows if b["name"] == name), {})
    check("list row has creation_date", bool(row.get("creation_date")))
    check("creation_date matches created", row.get("creation_date") == row.get("created"))
    requests.delete(f"{BASE}/api/s3/buckets/{name}", timeout=30)
    sys.exit(1 if failed else 0)


main()
