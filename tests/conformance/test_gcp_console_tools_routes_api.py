#!/usr/bin/env python3
"""GCP console/tooling route coverage: /api/gcp/console/{summary,enforcement},
/api/providers/gcp/{gcloud,gcutil,sdk/<lang>[/snippet]} and gcloud/gcutil resolve."""
import json, os, sys, urllib.request, urllib.error

BASE = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000").rstrip("/")
fails = 0


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, None


def check(name, ok):
    global fails
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    fails += 0 if ok else 1


s, b = call("GET", "/api/gcp/console/summary")
check("console summary has services map", s == 200 and isinstance(b.get("services"), dict) and "gcp-compute" in b["services"])
s, b = call("GET", "/api/gcp/console/enforcement")
check("enforcement GET shape", s == 200 and {"iam", "vpc"} <= set(b))
s, b2 = call("POST", "/api/gcp/console/enforcement", {"iam": b["iam"], "vpc": b["vpc"]})
check("enforcement POST round-trips", s == 200 and b2["iam"] == b["iam"] and b2["vpc"] == b["vpc"])
for tool in ("gcloud", "gcutil"):
    s, b = call("GET", f"/api/providers/gcp/{tool}")
    check(f"{tool} info", s == 200 and b.get("provider") == "gcp" and b.get("tool") == tool)
    s, b = call("POST", f"/api/providers/gcp/{tool}/resolve", {"command": f"{tool} compute instances list"})
    check(f"{tool} resolve echoes command", s == 200 and b.get("provider") == "gcp" and "command" in b)
for lang in ("java", "go", "python", "nodejs"):
    s, b = call("GET", f"/api/providers/gcp/sdk/{lang}")
    check(f"sdk {lang} info", s == 200 and b.get("provider") == "gcp" and b.get("endpoint"))
    s, b = call("GET", f"/api/providers/gcp/sdk/{lang}/snippet")
    check(f"sdk {lang} snippet", s == 200 and b.get("language") == lang and b.get("snippet"))
s, _ = call("GET", "/api/gcp/extras-config/not-a-stub")
check("extras-config unknown stub is 404", s == 404)
sys.exit(1 if fails else 0)
