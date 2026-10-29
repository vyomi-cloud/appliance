"""An Eventarc trigger created with only a name (the console form default) must come back with
every grid column (Event provider, Destination, Region, State) filled — never '-'/blank."""
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
    name = "trg-" + uuid.uuid4().hex[:8]
    r = requests.post(f"{BASE}/api/gcp/extras/eventarc/triggers", json={"name": name}, timeout=30)
    check("create trigger", r.status_code < 300)
    rows = requests.get(f"{BASE}/api/gcp/extras/eventarc/triggers", timeout=30).json()["items"]
    row = next((t for t in rows if t["name"] == name), {})
    for col in ("event_provider", "destination", "region", "state"):
        v = str(row.get(col) or "")
        check(f"{col} filled ({v})", v not in ("", "-", "—", "None", "null"))
    check("state is ACTIVE", row.get("state") == "ACTIVE")
    requests.delete(f"{BASE}/api/gcp/extras/eventarc/triggers/{name}", timeout=30)
    sys.exit(1 if failed else 0)


main()
