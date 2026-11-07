"""Booster ROLE tier: the headless booster has no licence JWT, so the session token's tier must become the appliance tier
(otherwise tier_policy answers as Free and 403s every Pro/Max service - found booting the booster locally)."""
import os
import sys
import tempfile
import time as _t

_tmp = tempfile.mkdtemp(prefix="booster-session-tier-")
os.environ.setdefault("CLOUDLEARN_STATE_DIR", _tmp)
os.environ.setdefault("CLOUDLEARN_STATE_FILE", os.path.join(_tmp, "state.sqlite3"))
os.environ["VYOMI_ROLE"] = "booster"
os.environ["VYOMI_BOOSTER_SESSION_KEY"] = KEY = "test-session-key-tier-0123456789"
os.environ["VYOMI_BOOSTER_SESSION_TOKEN"] = ""

from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402
from core import booster_session as S  # noqa: E402
from core import app_context as ctx  # noqa: E402

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' - ' + str(detail)[:300] if detail and not ok else ''}")


os.environ["VYOMI_BOOSTER_SESSION_TOKEN"] = S.mint("acct", "max", _t.time() + 3600, key=KEY)
c = TestClient(server.app, base_url="http://127.0.0.1:9000")
c.__enter__()
ctx.STATE.setdefault("license", {})["tier"] = "free"     # what an un-licensed booster has

check("effective_tier() reads the verified token", S.effective_tier() == "max", S.effective_tier())
r = c.get("/healthz")
check("/healthz reports the session tier", r.status_code == 200 and r.json().get("tier") == "max", r.text)
ddb = c.post("/", headers={"x-amz-target": "DynamoDB_20120810.ListTables", "content-type": "application/x-amz-json-1.0",
                           "authorization": "AWS4-HMAC-SHA256 Credential=test/20260101/us-east-1/dynamodb/aws4_request, SignedHeaders=host, Signature=00"},
             content="{}")
check("Max session: DynamoDB (Max-only service) is not tier-locked", ddb.status_code == 200 and "tier_service_locked" not in ddb.text, ddb.text)
check("licence state mirrors the session tier", ctx.STATE["license"]["tier"] == "max", ctx.STATE["license"])

os.environ["VYOMI_BOOSTER_SESSION_TOKEN"] = S.mint("acct", "pro", _t.time() + 3600, primary_cloud="aws", key=KEY)
check("Pro token -> effective tier pro", S.effective_tier() == "pro", S.effective_tier())
os.environ["VYOMI_BOOSTER_SESSION_TOKEN"] = "garbage"
check("bad token -> no effective tier (fails closed in middleware)", S.effective_tier() is None)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
