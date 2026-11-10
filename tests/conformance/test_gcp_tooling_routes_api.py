"""GCP tooling routes (/api/providers/gcp/{gcloud,gcutil,sdk/<lang>,.../snippet,.../resolve})."""
import os
import sys

import requests

BASE = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000")
failed = False


def check(name, ok):
    global failed
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    failed = failed or not ok


def get(path):
    r = requests.get(f"{BASE}{path}", timeout=30)
    return r.status_code, (r.json() if r.status_code == 200 else {})


def post(path, body):
    r = requests.post(f"{BASE}{path}", json=body, timeout=30)
    return r.status_code, (r.json() if r.status_code == 200 else {})


def main():
    for tool in ("gcloud", "gcutil"):
        s, b = get(f"/api/providers/gcp/{tool}")
        check(f"{tool} info", s == 200 and b.get("provider") == "gcp" and b.get("tool") == tool and bool(b.get("help")))
    sdk = {
        "java": "setHost",
        "go": "option.WithEndpoint",
        "python": "STORAGE_EMULATOR_HOST",
        "nodejs": "apiEndpoint",
    }
    for lang, marker in sdk.items():
        s, b = get(f"/api/providers/gcp/sdk/{lang}")
        check(f"{lang} info", s == 200 and b.get("provider") == "gcp" and bool(b.get("dependency")))
        s, b = get(f"/api/providers/gcp/sdk/{lang}/snippet")
        snip = b.get("snippet", "")
        check(f"{lang} snippet has endpoint and {marker}",
              s == 200 and b.get("language") == lang and marker in snip and b.get("endpoint", "x") in snip)
    s, b = post("/api/providers/gcp/gcloud/resolve", {"command": "gcloud compute instances list"})
    check("gcloud resolve compute instances list",
          s == 200 and b.get("service") == "compute" and b.get("operation") == "instances.list" and b.get("route", "").startswith("GET "))
    s, b = post("/api/providers/gcp/gcutil/resolve", {"command": "gcutil listinstances"})
    check("gcutil resolve returns gcutil tool", s == 200 and b.get("tool") == "gcutil" and b.get("command") == "gcutil listinstances")
    s, b = post("/api/providers/gcp/gcutil/resolve", {"command": "gcloud compute instances list"})
    check("gcutil resolve rejects non-gcutil command", s == 200 and not b.get("route") and "gcutil" in b.get("notes", ""))
    sys.exit(1 if failed else 0)


main()
