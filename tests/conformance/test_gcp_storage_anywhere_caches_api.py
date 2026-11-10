"""GCS storage.anywhereCaches.{insert,get,list,pause,resume,disable} (storage/v1): lifecycle + errors."""
import os
import sys
import time

import requests

BASE = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000")
failed = False


def check(name, ok, detail=""):
    global failed
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + ("" if ok else f" :: {detail}"))
    failed = failed or not ok


def main():
    b = f"anywhere-{int(time.time()) % 1000000}"
    r = requests.post(f"{BASE}/api/gcp/storage/v1/b", json={"name": b}, timeout=30)
    check("create bucket", r.status_code == 200, r.text[:200])
    root = f"{BASE}/api/gcp/storage/v1/b/{b}/anywhereCaches"
    r = requests.post(root, json={"zone": "us-central1-a", "ttl": "3600s"}, timeout=30)
    check("insert returns operation", r.status_code == 200 and r.json().get("done") is True, r.text[:200])
    r = requests.get(f"{root}/us-central1-a", timeout=30)
    j = r.json()
    check("get -> running, populated", r.status_code == 200 and j.get("state") == "running" and j.get("ttl") == "3600s"
          and j.get("anywhereCacheId") == "us-central1-a" and j.get("createTime"), r.text[:200])
    r = requests.post(f"{root}/us-central1-a/pause", json={}, timeout=30)
    check("pause -> paused", r.status_code == 200 and r.json().get("state") == "paused", r.text[:200])
    r = requests.post(f"{root}/us-central1-a/pause", json={}, timeout=30)
    check("pause twice -> 400", r.status_code == 400, r.status_code)
    r = requests.post(f"{root}/us-central1-a/resume", json={}, timeout=30)
    check("resume -> running", r.status_code == 200 and r.json().get("state") == "running", r.text[:200])
    r = requests.get(root, timeout=30)
    check("list has 1", r.status_code == 200 and len(r.json().get("items", [])) == 1, r.text[:200])
    r = requests.post(f"{root}/us-central1-a/disable", json={}, timeout=30)
    check("disable -> disabled", r.status_code == 200 and r.json().get("state") == "disabled", r.text[:200])
    r = requests.post(f"{root}/nope/pause", json={}, timeout=30)
    check("pause missing -> 404", r.status_code == 404, r.status_code)
    requests.delete(f"{BASE}/api/gcp/storage/v1/b/{b}", timeout=30)
    sys.exit(1 if failed else 0)


main()
