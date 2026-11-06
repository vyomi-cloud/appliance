"""Pro = ONE cloud (booster and offline): the first cloud a Pro licence uses becomes its primary cloud, the other two are refused
with tier_provider_locked; a Pro licence with the cloud already chosen is locked to it; Max keeps all three."""
import os
import sys
import tempfile
import time as _t

_tmp = tempfile.mkdtemp(prefix="booster-onecloud-")
os.environ.setdefault("CLOUDLEARN_STATE_DIR", _tmp)
os.environ.setdefault("CLOUDLEARN_STATE_FILE", os.path.join(_tmp, "state.sqlite3"))   # never persist a Pro tenant into the repo checkout's state file
os.environ["VYOMI_BOOSTER"] = "1"

from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402
from core import app_context as ctx  # noqa: E402

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' - ' + str(detail)[:300] if detail and not ok else ''}")


c = TestClient(server.app, base_url="http://127.0.0.1:9000")
c.__enter__()
from core import gcp_project  # noqa: E402
GP = gcp_project.project_id()
SUB = "00000000-0000-0000-0000-cloudlearn01"
H = {"content-type": "application/x-www-form-urlencoded",
     "authorization": "AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/20260101/us-east-1/ec2/aws4_request, SignedHeaders=host, Signature=00"}


def set_licence(tier, primary=""):
    ctx._tier_cache.update({"tier": tier, "verified_at": _t.time(), "ttl": 10 ** 9})
    ctx.STATE["license_claims"] = {"tier": tier, "primary_cloud": primary}
    t = ctx.tenants_state().setdefault("tenants", {}).setdefault(ctx.DEFAULT_TENANT_ID if hasattr(ctx, "DEFAULT_TENANT_ID") else "default", {})
    t.update(license_tier=tier, primary_cloud=primary)
    t.pop("primary_cloud_changed_at", None)
    return t


def aws():
    return c.post("/", headers=H, content="Action=DescribeInstances&Version=2016-11-15")


def gcp():
    return c.get(f"/compute/v1/projects/{GP}/zones/us-central1-a/instances")


def azure():
    return c.get(f"/subscriptions/{SUB}/providers/Microsoft.Compute/virtualMachines?api-version=2023-09-01")


def locked(r):
    return r.status_code == 403 and ("tier_provider_locked" in r.text or "tier_primary_cloud_unset" in r.text)


# Pro, cloud not chosen yet: first use pins it
t = set_licence("pro", "")
r = gcp()
check("Pro unset: first cloud used (GCP) is allowed", not locked(r), f"{r.status_code} {r.text[:150]}")
check("Pro unset: that cloud is now the primary", t.get("primary_cloud") == "gcp", t.get("primary_cloud"))
check("Pro: AWS now locked", locked(aws()), aws().text[:150])
check("Pro: Azure now locked", locked(azure()), azure().text[:150])
check("Pro: GCP still works", not locked(gcp()))

# Pro with the cloud chosen at signup
t = set_licence("pro", "aws")
check("Pro primary=aws: AWS works", not locked(aws()))
check("Pro primary=aws: GCP locked", locked(gcp()))
check("Pro primary=aws: Azure locked", locked(azure()))
check("Pro primary=aws stays aws", t.get("primary_cloud") == "aws")

# Max: all three
t = set_licence("max", "")
check("Max: AWS", not locked(aws()))
check("Max: GCP", not locked(gcp()))
check("Max: Azure", not locked(azure()))
check("Max: no primary pinned", not t.get("primary_cloud"))

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
