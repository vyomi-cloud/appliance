"""GCP tooling routes (/api/providers/gcp/{gcloud,gcutil,sdk/<lang>,.../snippet,.../resolve}) return endpoint-pointed info."""
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
        check(f"{tool} info returns provider gcp and tool {tool}", s == 200 and b.get("provider") == "gcp" and b.get("tool") == tool and bool(b.get("endpoint")))
    paths = {  # literal route paths (the route-coverage scanner matches literals)
        "java": ("/api/providers/gcp/sdk/java", "/api/providers/gcp/sdk/java/snippet"),
        "go": ("/api/providers/gcp/sdk/go", "/api/providers/gcp/sdk/go/snippet"),
        "python": ("/api/providers/gcp/sdk/python", "/api/providers/gcp/sdk/python/snippet"),
        "nodejs": ("/api/providers/gcp/sdk/nodejs", "/api/providers/gcp/sdk/nodejs/snippet"),
    }
    markers = {"java": "StorageOptions", "go": "storage.NewClient", "python": "STORAGE_EMULATOR_HOST", "nodejs": "@google-cloud/storage"}
    for lang, marker in markers.items():
        s1, body = get(paths[lang][0])
        s2, snip = get(paths[lang][1])
        check(f"{lang} info returns provider gcp", s1 == 200 and body.get("provider") == "gcp" and bool(body.get("endpoint")))
        check(f"{lang} snippet contains endpoint and {marker}",
              s2 == 200 and snip.get("language") == lang and marker in snip.get("snippet", "") and snip.get("endpoint", "") in snip.get("snippet", ""))
    s, b = post("/api/providers/gcp/gcloud/resolve", {"command": "gcloud pubsub topics list"})
    check("gcloud resolve maps pubsub topics list", s == 200 and b.get("service") == "pubsub" and b.get("operation") == "topics.list")
    s, b = post("/api/providers/gcp/gcutil/resolve", {"command": "gcutil listinstances"})
    check("gcutil resolve answers 200 with provider gcp", s == 200 and b.get("provider") == "gcp")
    sys.exit(1 if failed else 0)


main()
