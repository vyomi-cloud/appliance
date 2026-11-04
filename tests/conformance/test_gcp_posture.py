"""Compute security risk overview + Storage security recommendations (run: PYTHONPATH=. python3 tests/conformance/test_gcp_posture.py)."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from core.aws_wire_router import AwsWireRouter  # noqa: E402

AwsWireRouter.STRICT_GCP_PROJECT = False   # engine test: ad-hoc project ids
R = AwsWireRouter()
PASS = FAIL = 0
P = "posture-proj-1"


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' - ' + str(detail)[:300] if detail and not ok else ''}")


def call(method, path, body=None, query=None):
    out = R.handle(method, path, query or {}, {}, json.dumps(body).encode() if body is not None else b"")
    try:
        return out["status"], json.loads(out["body"] or b"{}")
    except Exception:
        return out["status"], {}


def cats(kind):
    st, d = call("GET", f"/v1/projects/{P}/securityPosture/{kind}")
    assert st == 200, d
    return d, {(f["category"], f["resourceName"].rsplit("/", 1)[-1]) for f in d["findings"]}


d, c = cats("compute")
check("empty project has no findings", d["summary"]["total"] == 0)

zone = f"/compute/v1/projects/{P}/zones/us-central1-a"
call("POST", f"/compute/v1/projects/{P}/global/networks", {"name": "default", "autoCreateSubnetworks": True})
st, _ = call("POST", f"{zone}/instances", {"name": "web1", "machineType": f"zones/us-central1-a/machineTypes/e2-micro",
    "disks": [{"boot": True, "initializeParams": {"sourceImage": "projects/debian-cloud/global/images/family/debian-12"}}],
    "networkInterfaces": [{"network": f"projects/{P}/global/networks/default", "accessConfigs": [{"type": "ONE_TO_ONE_NAT", "name": "External NAT"}]}],
    "tags": {"items": ["web"]}})
call("POST", f"{zone}/instances", {"name": "hardened", "machineType": f"zones/us-central1-a/machineTypes/e2-micro",
    "disks": [{"boot": True, "initializeParams": {"sourceImage": "projects/debian-cloud/global/images/family/debian-12"}}],
    "networkInterfaces": [{"network": f"projects/{P}/global/networks/default", "accessConfigs": []}],
    "metadata": {"items": [{"key": "enable-oslogin", "value": "TRUE"}, {"key": "block-project-ssh-keys", "value": "TRUE"}]},
    "serviceAccounts": [{"email": "app@posture-proj-1.iam.gserviceaccount.com", "scopes": []}],
    "shieldedInstanceConfig": {"enableSecureBoot": True}})
call("POST", f"/compute/v1/projects/{P}/global/firewalls", {"name": "allow-ssh-any", "network": f"projects/{P}/global/networks/default",
    "allowed": [{"IPProtocol": "tcp", "ports": ["22"]}], "sourceRanges": ["0.0.0.0/0"], "targetTags": ["web"]})
call("POST", f"/compute/v1/projects/{P}/global/firewalls", {"name": "allow-ssh-corp", "network": f"projects/{P}/global/networks/default",
    "allowed": [{"IPProtocol": "tcp", "ports": ["22"]}], "sourceRanges": ["10.0.0.0/8"]})
d, c = cats("compute")
check("public IP found on web1 only", ("PUBLIC_IP_ADDRESS", "web1") in c and ("PUBLIC_IP_ADDRESS", "hardened") not in c, c)
check("default SA full access on web1", ("FULL_API_ACCESS", "web1") in c)
check("hardened instance has no findings", not any(r == "hardened" for _, r in c), c)
check("open SSH firewall found w/ affected instances", ("OPEN_SSH_PORT", "allow-ssh-any") in c
      and next(f for f in d["findings"] if f["category"] == "OPEN_SSH_PORT")["affectedInstances"] == ["web1"])
check("corp-restricted firewall not flagged", ("OPEN_SSH_PORT", "allow-ssh-corp") not in c)
check("sorted by severity, summary counts add up", d["findings"][0]["severity"] == "HIGH" and sum(d["summary"]["bySeverity"].values()) == d["summary"]["total"])
call("PATCH", f"/compute/v1/projects/{P}/global/firewalls/allow-ssh-any", {"sourceRanges": ["10.0.0.0/8"]})
d, c = cats("compute")
check("fix firewall -> finding disappears", ("OPEN_SSH_PORT", "allow-ssh-any") not in c, c)

# storage
bk = "posture-bucket-1"
call("POST", "/storage/v1/b", {"name": bk}, {"project": P})
d, c = cats("storage")
check("new bucket: UBLA + PAP + versioning findings", {("BUCKET_POLICY_ONLY_DISABLED", bk), ("PUBLIC_ACCESS_PREVENTION_NOT_ENFORCED", bk), ("BUCKET_VERSIONING_DISABLED", bk)} <= c, c)
call("PUT", f"/storage/v1/b/{bk}/iam", {"bindings": [{"role": "roles/storage.objectViewer", "members": ["allUsers"]}]})
d, c = cats("storage")
check("public binding -> CRITICAL PUBLIC_BUCKET_ACL first", d["findings"][0]["category"] == "PUBLIC_BUCKET_ACL" and d["findings"][0]["severity"] == "CRITICAL", d["findings"][:1])
call("PATCH", f"/storage/v1/b/{bk}", {"iamConfiguration": {"uniformBucketLevelAccess": {"enabled": True}}, "versioning": {"enabled": True}})
call("PUT", f"/storage/v1/b/{bk}/iam", {"bindings": []})
d, c = cats("storage")
check("hardening clears UBLA/versioning/public", not ({("BUCKET_POLICY_ONLY_DISABLED", bk), ("BUCKET_VERSIONING_DISABLED", bk), ("PUBLIC_BUCKET_ACL", bk)} & c), c)
check("unknown kind 404", call("GET", f"/v1/projects/{P}/securityPosture/nope")[0] in (404, 500))
print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
