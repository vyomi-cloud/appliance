"""Artifact Registry console routes (/api/gcp/artifactregistry/repositories*, detail-tab ops):
create -> get -> update -> labels -> list -> push sample -> children -> delete -> 404."""
import os
import uuid

import requests

BASE = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000")
failed = False


def check(name, ok, extra=""):
    global failed
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{'' if ok else ' :: ' + str(extra)}")
    failed = failed or not ok


def main():
    U = BASE + "/api/gcp/artifactregistry/repositories"
    S = BASE + "/api/gcp/sub/artifactregistry"
    name = "cov-" + uuid.uuid4().hex[:6]
    r = requests.post(U, json={"name": name, "format": "DOCKER", "location": "us-central1"}, timeout=30)
    check("create repository", r.status_code == 200 and r.json().get("ok"), r.text[:200])
    r = requests.post(U, json={"name": name, "format": "DOCKER", "location": "us-central1"}, timeout=30)
    check("duplicate create is 409", r.status_code == 409, r.text[:200])
    r = requests.get(f"{U}/{name}", timeout=30)
    check("get repository", r.status_code == 200 and r.json().get("ok"), r.text[:200])
    r = requests.patch(f"{U}/{name}", json={"description": "edited"}, timeout=30)
    check("patch description", r.status_code == 200 and r.json().get("description") == "edited", r.text[:200])
    r = requests.get(f"{U}/{name}", timeout=30)
    check("description persisted", r.json().get("description") == "edited", r.text[:200])
    r = requests.post(f"{S}/setLabels/{name}", json={"labels": {"team": "a"}}, timeout=30)
    check("setLabels", r.status_code == 200 and r.json()["item"]["labels"].get("team") == "a", r.text[:200])
    r = requests.get(f"{S}/getLabels/{name}", timeout=30)
    check("getLabels returns saved", r.json()["item"]["labels"].get("team") == "a", r.text[:200])
    r = requests.get(U, timeout=30)
    check("list contains repository", any(name in str(i.get("name", "")) for i in r.json().get("items", [])), r.text[:200])
    r = requests.post(f"{S}/pushSample/{name}", json={}, timeout=30)
    check("pushSample", r.status_code == 200 and r.json().get("ok"), r.text[:200])
    for op in ("listPackages", "listVersions", "listTags", "listImages"):
        r = requests.get(f"{S}/{op}/{name}", timeout=30)
        check(f"{op} ok", r.status_code == 200 and r.json().get("ok"), r.text[:200])
    r = requests.get(f"{S}/bogusOp/{name}", timeout=30)
    check("unknown op is 404", r.status_code == 404, r.text[:200])
    r = requests.delete(f"{U}/{name}", timeout=30)
    check("delete repository", r.status_code == 200, r.text[:200])
    r = requests.get(f"{U}/{name}", timeout=30)
    check("get after delete is 404", r.status_code == 404, r.text[:200])
    raise SystemExit(1 if failed else 0)


main()
