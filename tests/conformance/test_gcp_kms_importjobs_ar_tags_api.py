"""Cloud KMS importJobs create/get/list plus Artifact Registry tag create/get/list/patch/delete
over the offline REST surface (covers ImportJobCreate/List/View/Route, TagTarget, TagView)."""
import os
import sys
import time
import uuid

import requests

BASE = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000")
try:
    PROJECT = requests.get(f"{BASE}/api/gcp/catalog", timeout=60).json()["project"]
except Exception:
    PROJECT = "vyomi-project"
failed = False


def check(name, ok, extra=""):
    global failed
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{'' if ok else ' :: ' + str(extra)}")
    failed = failed or not ok


tag = uuid.uuid4().hex[:6]
LOC = f"{BASE}/v1/projects/{PROJECT}/locations/us-central1"

# ---- KMS import jobs ----
ring = f"{LOC}/keyRings/ij-{tag}"
r = requests.post(f"{LOC}/keyRings?keyRingId=ij-{tag}", timeout=60)
check("create key ring", r.status_code == 200, r.text[:160])
ijs = f"{ring}/importJobs"
r = requests.post(f"{ijs}?importJobId=job1", json={"importMethod": "RSA_OAEP_3072_SHA1_AES_256", "protectionLevel": "SOFTWARE"}, timeout=60)
check("create import job", r.status_code == 200 and r.json()["name"].endswith("/importJobs/job1"), r.text[:200])
r = requests.post(f"{ijs}?importJobId=job1", json={"importMethod": "RSA_OAEP_3072_SHA1_AES_256", "protectionLevel": "SOFTWARE"}, timeout=60)
check("duplicate import job -> 409", r.status_code == 409, r.text[:160])
r = requests.post(f"{ijs}?importJobId=bad", json={"importMethod": "NOPE"}, timeout=60)
check("bad importMethod -> 400", r.status_code == 400, r.text[:160])
for _ in range(20):  # key generation completes asynchronously
    g = requests.get(f"{ijs}/job1", timeout=60)
    if g.json().get("state") == "ACTIVE":
        break
    time.sleep(0.5)
j = g.json()
check("get import job reaches ACTIVE with public key", g.status_code == 200 and j.get("state") == "ACTIVE"
      and "BEGIN PUBLIC KEY" in j.get("publicKey", {}).get("pem", "") and j.get("expireTime"), str(j)[:200])
r = requests.get(ijs, timeout=60)
check("list import jobs", r.status_code == 200 and [x["name"] for x in r.json().get("importJobs", [])] == [j["name"]], r.text[:200])
check("get unknown import job -> 404", requests.get(f"{ijs}/ghost", timeout=60).status_code == 404)

# ---- Artifact Registry tags ----
repo = f"tg-{tag}"
r = requests.post(f"{LOC}/repositories?repositoryId={repo}", json={"format": "DOCKER"}, timeout=60)
check("create repository", r.status_code == 200, r.text[:160])
r = requests.post(f"{BASE}/api/gcp/sub/artifactregistry/pushSample/{repo}", json={}, timeout=60)
ver = r.json().get("version", "")
check("push sample version", r.status_code == 200 and ver, r.text[:200])
pkg = f"{BASE}/v1/{ver.split('/versions/')[0]}"
r = requests.post(f"{pkg}/tags?tagId=stable", json={"version": ver}, timeout=60)
check("create tag points at version", r.status_code == 200 and r.json().get("version") == ver
      and r.json()["name"].endswith("/tags/stable"), r.text[:200])
r = requests.post(f"{pkg}/tags?tagId=bad", json={"version": ver + "-missing"}, timeout=60)
check("tag on missing version -> 404", r.status_code == 404, r.text[:160])
r = requests.post(f"{pkg}/tags?tagId=stable", json={"version": ver}, timeout=60)
check("duplicate tag -> 409", r.status_code == 409, r.text[:160])
r = requests.get(f"{pkg}/tags/stable", timeout=60)
check("get tag", r.status_code == 200 and r.json().get("version") == ver, r.text[:200])
r = requests.get(f"{pkg}/tags", timeout=60)
check("list tags contains it", any(t["name"].endswith("/tags/stable") for t in r.json().get("tags", [])), r.text[:200])
r = requests.patch(f"{pkg}/tags/stable", json={"version": ver}, timeout=60)
check("patch tag", r.status_code == 200 and r.json().get("version") == ver, r.text[:200])
r = requests.delete(f"{pkg}/tags/stable", timeout=60)
check("delete tag", r.status_code == 200, r.text[:160])
check("get deleted tag -> 404", requests.get(f"{pkg}/tags/stable", timeout=60).status_code == 404)
requests.delete(f"{LOC}/repositories/{repo}", timeout=60)
sys.exit(1 if failed else 0)
