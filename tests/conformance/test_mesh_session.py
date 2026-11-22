"""Mesh ROLE server-side enforcement: portal-signed session token (Ed25519 v2, pinned keys; HMAC v1 retired, finding F2),
Pro = primary_cloud only, Max = all, everything refused after session_end, fail-closed without a token. Role is opt-in
(VYOMI_ROLE=mesh). Tokens are signed with the public test vector (tests/mesh_testkey.py), trusted in this process only."""
import os
import sys
import tempfile
import time as _t

_tmp = tempfile.mkdtemp(prefix="mesh-session-")
os.environ.setdefault("CLOUDLEARN_STATE_DIR", _tmp)
os.environ.setdefault("CLOUDLEARN_STATE_FILE", os.path.join(_tmp, "state.sqlite3"))
os.environ["VYOMI_MESH_MODE"] = "1"
KEY = "test-session-key-0123456789"

from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402
from core import mesh_session as S  # noqa: E402
from core import app_context as ctx  # noqa: E402
from tests import mesh_testkey as testkey  # noqa: E402

testkey.trust(S)

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' - ' + str(detail)[:300] if detail and not ok else ''}")


ctx._tier_cache.update({"tier": "max", "verified_at": _t.time(), "ttl": 10 ** 9})
ctx.STATE["license_claims"] = {"tier": "max"}
c = TestClient(server.app, base_url="http://127.0.0.1:9000")
c.__enter__()
from core import gcp_project  # noqa: E402
GP = gcp_project.project_id()
SUB = "00000000-0000-0000-0000-cloudlearn01"
AWSH = {"content-type": "application/x-www-form-urlencoded",
        "authorization": "AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/20260101/us-east-1/ec2/aws4_request, SignedHeaders=host, Signature=00"}


def aws(h=None):
    return c.post("/", headers={**AWSH, **(h or {})}, content="Action=DescribeInstances&Version=2016-11-15")


def gcp(h=None):
    return c.get(f"/compute/v1/projects/{GP}/zones/us-central1-a/instances", headers=h or {})


def azure(h=None):
    return c.get(f"/subscriptions/{SUB}/providers/Microsoft.Compute/virtualMachines?api-version=2023-09-01", headers=h or {})


def code(r):
    try:
        return (r.json().get("error") or {}).get("code")
    except Exception:
        return None


def tok(tier, primary="", ends_in=3600, forged=False, **kw):
    mint = testkey.forged if forged else testkey.mint
    return mint("acct-1", tier, _t.time() + ends_in, primary_cloud=primary, session_id="s1", **kw)


# ---- the verifier itself
now = _t.time()
cl = S.verify(tok("pro", "aws"), key=KEY)
check("verify: valid token returns claims", cl["tier"] == "pro" and cl["primary_cloud"] == "aws" and cl["sub"] == "acct-1")
for name, t, kw, want in [
    ("tampered payload", tok("pro", "aws").split(".")[0] + "." + tok("max", "").split(".")[1] + "." + tok("pro", "aws").split(".")[2], {}, "MeshSessionBadSignature"),
    ("wrong key", tok("pro", "aws", forged=True), {}, "MeshSessionBadSignature"),
    ("v1 (HMAC) token, even with the right key", S.mint("acct-1", "max", _t.time() + 3600, key=KEY), {}, "MeshSessionV1Retired"),
    ("garbage", "not-a-token", {}, "MeshSessionMalformed"),
    ("expired", tok("pro", "aws", ends_in=-5), {}, "MeshSessionExpired"),
    ("free tier not eligible", tok("free"), {}, "MeshTierNotEligible"),
]:
    try:
        S.verify(t, key=KEY, **kw)
        check(f"verify rejects {name}", False)
    except S.SessionError as e:
        check(f"verify rejects {name}", e.code == want, e.code)
check("verify: a v2 token needs no shared key", S.verify(tok("pro", "aws"), key="")["tier"] == "pro")
try:
    S.verify(S.mint("acct-1", "pro", _t.time() + 3600, key="any"), key="")
    check("verify: a v1 token without a key is refused", False)
except S.SessionError as e:
    check("verify: a v1 token without a key is refused", e.code == "MeshSessionV1Retired", e.code)
check("verify: the session end is evaluated at the supplied clock", (lambda: [S.verify(tok("pro", "aws", ends_in=10), key=KEY, now=now + 5), True][1])())
try:
    S.verify(tok("pro", "aws", ends_in=10), key=KEY, now=now + 11)
    check("verify: now >= session_end is expired", False)
except S.SessionError as e:
    check("verify: now >= session_end is expired", e.code == "MeshSessionExpired")

# ---- role off: untouched (existing behaviour)
os.environ.pop("VYOMI_ROLE", None)
os.environ.pop("VYOMI_MESH_SESSION_TOKEN", None)
check("role not mesh: no token needed", code(gcp()) not in ("MeshSessionRequired",) and gcp().status_code != 401)

# ---- role on
os.environ["VYOMI_ROLE"] = "mesh"
os.environ["VYOMI_MESH_SESSION_KEY"] = KEY
S.reset_for_tests()
r = gcp()
check("mesh role, no token: refused 401 MeshSessionRequired", r.status_code == 401 and code(r) == "MeshSessionRequired", f"{r.status_code} {r.text[:150]}")
check("mesh role, no token: /healthz also refused (fail closed)", c.get("/healthz").status_code == 401)

os.environ["VYOMI_MESH_SESSION_TOKEN"] = tok("pro", "aws")
S.reset_for_tests()
check("Pro primary=aws: AWS served", code(aws()) not in ("tier_provider_locked", "MeshSessionRequired") and aws().status_code != 401)
r = gcp()
check("Pro primary=aws: GCP refused tier_provider_locked 403", r.status_code == 403 and code(r) == "tier_provider_locked", f"{r.status_code} {r.text[:150]}")
r = azure()
check("Pro primary=aws: Azure refused", r.status_code == 403 and code(r) == "tier_provider_locked", f"{r.status_code} {r.text[:150]}")
check("/healthz served while the session is valid", c.get("/healthz").status_code == 200)

# a forged header token cannot widen the session (bad signature) ...
r = gcp({S.HEADER: tok("max", "", forged=True)})
check("forged header token rejected (bad signature)", r.status_code == 401 and code(r) == "MeshSessionBadSignature", f"{r.status_code} {r.text[:150]}")
# ... but a genuine header token is honoured over the env one
S.reset_for_tests()
r = gcp({S.HEADER: tok("max", "")})
check("genuine Max header token: GCP served", r.status_code != 401 and code(r) != "tier_provider_locked", f"{r.status_code} {r.text[:150]}")

# Pro with no cloud chosen: first use pins
os.environ["VYOMI_MESH_SESSION_TOKEN"] = tok("pro", "")
S.reset_for_tests()
for _t_ in (ctx.tenants_state().get("tenants") or {}).values():      # the app mirrors the session tier now, so forget the earlier aws pin
    _t_.pop("primary_cloud", None)
check("Pro unset: first cloud (GCP) allowed", gcp().status_code != 403)
r = aws()
check("Pro unset: then AWS locked", r.status_code == 403 and code(r) == "tier_provider_locked", f"{r.status_code} {r.text[:150]}")

# Max: all three
os.environ["VYOMI_MESH_SESSION_TOKEN"] = tok("max", "")
S.reset_for_tests()
check("Max: AWS", code(aws()) != "tier_provider_locked" and aws().status_code != 401)
check("Max: GCP", code(gcp()) != "tier_provider_locked" and gcp().status_code != 401)
check("Max: Azure", code(azure()) != "tier_provider_locked" and azure().status_code != 401)

# session_end: everything refused afterwards, and it latches
os.environ["VYOMI_MESH_SESSION_TOKEN"] = tok("max", "", ends_in=2)
S.reset_for_tests()
check("before session_end: served", gcp().status_code != 401)
_t.sleep(2.2)
for nm, fn in (("GCP", gcp), ("AWS", aws), ("Azure", azure)):
    r = fn()
    check(f"after session_end: {nm} refused 410", r.status_code == 410 and code(r) == "MeshSessionExpired", f"{r.status_code} {r.text[:120]}")
r = c.get("/healthz")
check("after session_end: /healthz refused too", r.status_code == 410, r.status_code)
os.environ["VYOMI_MESH_SESSION_TOKEN"] = tok("max", "", ends_in=3600)       # a fresh token does not revive an ended process session
check("ended session stays ended (latched) even if a new token appears", gcp().status_code == 410)
S.reset_for_tests()
check("(new session after restart) fresh token works again", gcp().status_code != 410)

# no shared key at all (what a v2 Mesh gets): the v2 token is still enough; no token is still nothing
os.environ.pop("VYOMI_MESH_SESSION_KEY")
check("mesh role without a key: v2 token still served (no shared key needed)", gcp().status_code not in (401, 410, 503))
os.environ.pop("VYOMI_MESH_SESSION_TOKEN")
S.reset_for_tests()
r = gcp()
check("mesh role without a token: refused (fail closed)", r.status_code == 401 and code(r) == "MeshSessionRequired", f"{r.status_code} {r.text[:100]}")
os.environ["VYOMI_MESH_SESSION_TOKEN"] = S.mint("acct-1", "max", _t.time() + 3600, key=KEY)     # F2: a self-minted v1 token
os.environ["VYOMI_MESH_SESSION_KEY"] = KEY
S.reset_for_tests()
r = gcp()
check("mesh role, self-minted v1 token + its key: refused (F2)", r.status_code == 401 and code(r) == "MeshSessionV1Retired", f"{r.status_code} {r.text[:100]}")

os.environ.pop("VYOMI_ROLE", None)
print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
