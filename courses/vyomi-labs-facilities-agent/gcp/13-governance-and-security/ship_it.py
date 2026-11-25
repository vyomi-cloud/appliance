import json
import time

import gcp

TF = """
resource "google_storage_bucket" "docs" {
  name     = "facilities-ship-docs"
  location = "US"
}
resource "google_pubsub_topic" "approvals" {
  name = "facilities-ship-approvals"
}
"""
s = gcp.authed_session()
base = f"{gcp.ENDPOINT}/v1/{gcp.PARENT}/deployments"
dep = f"{gcp.PARENT}/deployments/facilities-ship"
s.delete(f"{gcp.ENDPOINT}/v1/{dep}")
time.sleep(1)
r = s.post(base + "?deploymentId=facilities-ship", json={
    "terraformBlueprint": {"vyomiFiles": {"main.tf": TF}},
    "serviceAccount": f"projects/{gcp.PROJECT}/serviceAccounts/infra-manager@{gcp.PROJECT}.iam.gserviceaccount.com"})
assert r.status_code == 200, r.text[:300]
op = r.json()
for _ in range(60):
    if op.get("done"):
        break
    time.sleep(0.5)
    op = s.get(f"{gcp.ENDPOINT}/v1/{op['name']}").json()
assert op.get("done") and not op.get("error"), op
d = s.get(f"{gcp.ENDPOINT}/v1/{dep}").json()
print("deployment state:", d.get("state"))
assert d.get("state") == "ACTIVE", d
rev = d["latestRevision"]
res = s.get(f"{gcp.ENDPOINT}/v1/{rev}/resources").json().get("resources", [])
types = sorted(x["terraformInfo"]["type"] for x in res)
print("resources applied:", types)
assert types == ["google_pubsub_topic", "google_storage_bucket"]
print("ship it verified: Infrastructure Manager applied", len(res), "resources; review them, then point gcsSource at the same files on real Google Cloud")
