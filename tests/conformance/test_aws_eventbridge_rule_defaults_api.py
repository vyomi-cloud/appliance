"""An EventBridge rule created from the console form (name only, or with a target) must come back
with Status and Targets filled the way the real API reports them: ENABLED and the attached
target count -- never '-'/blank."""
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
    url = f"{BASE}/api/aws/extras/eventbridge/rules"
    a, b = "rule-" + uuid.uuid4().hex[:8], "rule-" + uuid.uuid4().hex[:8]
    check("create rule (defaults)", requests.post(url, json={"name": a}, timeout=30).status_code < 300)
    check("create rule (with target)", requests.post(
        url, json={"name": b, "target_arn": "arn:aws:lambda:us-east-1:123456789012:function:f"}, timeout=30).status_code < 300)
    rows = {r["name"]: r for r in requests.get(url, timeout=30).json()["items"]}
    for n in (a, b):
        for col in ("event_bus_name", "rule_type", "state", "target_count"):
            v = str(rows.get(n, {}).get(col, ""))
            check(f"{n[:9]} {col} filled ({v})", v not in ("", "-", "—", "None", "null"))
        check(f"{n[:9]} state is ENABLED", rows.get(n, {}).get("state") == "ENABLED")
    check("target_count 0 without target", rows.get(a, {}).get("target_count") == 0)
    check("target_count 1 with target", rows.get(b, {}).get("target_count") == 1)
    for n in (a, b):
        requests.delete(f"{url}/{n}", timeout=30)
    sys.exit(1 if failed else 0)


main()
