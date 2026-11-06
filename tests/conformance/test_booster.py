"""Booster pack phase 1 (appliance side): headless guard, pairing, 70% cap, origin/host/rate limits.
Run: PYTHONPATH=. python tests/conformance/test_booster.py   (in-process; exits non-zero on failure)"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
os.environ.setdefault("CLOUDLEARN_STATE_DIR", tempfile.mkdtemp(prefix="booster-test-"))
os.environ["VYOMI_HOST_MEM_MB"] = "10000"

from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402
from core import booster as B  # noqa: E402
from core import app_context as ctx  # noqa: E402

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' - ' + str(detail)[:300] if detail and not ok else ''}")


def set_tier(tier, **claims):
    ctx.STATE["license_claims"] = dict(tier=tier, **claims) if tier else {}
    ctx._tier_cache.update({"tier": tier or "", "verified_at": time.time()})


c = TestClient(server.app, base_url="http://127.0.0.1:9000")
ORIGIN = {"origin": "https://vyomi.cloud"}

# ---- mode defaults
os.environ.pop("VYOMI_BOOSTER", None)
set_tier("free")
check("free tier: not booster mode", not B.booster_mode())
check("free tier: /ui not the booster 404", "BoosterHeadless" not in c.get("/ui").text)
set_tier("pro")
check("pro tier: booster mode default on", B.booster_mode())
set_tier("max")
check("max tier: booster mode default on", B.booster_mode())
os.environ["VYOMI_BOOSTER"] = "0"
check("VYOMI_BOOSTER=0 opts out", not B.booster_mode())
os.environ.pop("VYOMI_BOOSTER")

# ---- headless
set_tier("pro", sub="acct-1")
for p in ("/ui", "/ui/x", "/v4/aws/", "/console/aws", "/clouds", "/product", "/pricing", "/assets/x.js", "/aws", "/_wire/ui"):
    r = c.get(p)
    check(f"headless 404 JSON {p}", r.status_code == 404 and r.json()["error"]["code"] == "BoosterHeadless"
          and "vyomi.cloud/nano" in r.json()["error"]["nano_ui"], (r.status_code, r.text[:100]))
r = c.get("/", headers={"accept": "text/html"})
check("headless 404 for browser GET /", r.status_code == 404)
check("/healthz kept", c.get("/healthz").status_code == 200)
r = c.get("/_wire/healthz")
check("/_wire APIs kept", r.status_code == 200, r.status_code)
r = c.get("/", headers={"authorization": "AWS4-HMAC-SHA256 Credential=x", "x-amz-date": "20260101T000000Z"})
check("SDK ListBuckets on / not blocked", "BoosterHeadless" not in r.text)
set_tier("pro", sub="acct-1", sub_expires_at="2020-01-01T00:00:00Z")
check("expired Pro stays headless (locked, no UI regrowth)", c.get("/ui").status_code == 404)
_r = c.get("/booster/status")
check("expired status.locked", _r.status_code == 200 and _r.json().get("locked") is True, _r.text)
set_tier("pro", sub="acct-1", trial=True,
         sub_expires_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 5 * 86400 + 600)))

# ---- status
s = c.get("/booster/status").json()
check("status fields", all(k in s for k in ("version", "tier", "trial_days_left", "hostname", "resources", "health", "booster_id"))
      and s["tier"] == "pro" and s["trial"] and s["trial_days_left"] in (5, 6), s)
res = s["resources"]
check("cap = 70% of 10000 MB, 50/50 split", res["memory_cap_mb"] <= 7000 and res["memory_split_mb"]["compute"] == res["memory_cap_mb"] // 2, res)

# ---- guards
r = c.get("/booster/status", headers={"host": "evil.example.com"})
check("bad Host rejected (DNS rebinding)", r.status_code == 421)
r = c.get("/booster/status", headers={"origin": "https://evil.example.com"})
check("bad Origin rejected", r.status_code == 403)
r = c.get("/booster/status", headers=ORIGIN)
check("vyomi.cloud origin allowed + CORS + PNA", r.status_code == 200 and r.headers.get("access-control-allow-origin") == "https://vyomi.cloud"
      and r.headers.get("access-control-allow-private-network") == "true")
r = c.options("/booster/pair/complete", headers={**ORIGIN, "access-control-request-method": "POST"})
check("preflight ok", r.status_code == 204)
check("loopback origin allowed", B.origin_allowed("http://localhost:3000") and B.origin_allowed("http://127.0.0.1:8099"))
check("host allow-list", B.host_allowed("abc.local.vyomi.cloud:9000") and not B.host_allowed("x.com"))

# ---- pairing
r = c.post("/booster/pair/start", headers=ORIGIN)
check("browser cannot mint pair code", r.status_code == 403)
code = c.post("/booster/pair/start").json()["code"]
check("pair code shape", len(code) == 9 and code[4] == "-", code)
r = c.post("/booster/pair/complete", json={"code": "ZZZZ-ZZZZ", "account_id": "acct-1"}, headers=ORIGIN)
check("wrong code rejected", r.status_code == 400)
r = c.post("/booster/pair/complete", json={"code": code, "account_id": "someone-else"}, headers=ORIGIN)
check("account mismatch vs licence rejected", r.status_code == 403 and r.json()["error"]["code"] == "account_mismatch", r.text)
r = c.post("/booster/pair/complete", json={"code": code, "account_id": "acct-1"}, headers=ORIGIN)
tok = r.json().get("token", "")
check("pair complete returns token", r.status_code == 200 and tok.count(".") == 2, r.text)
check("code is single use", c.post("/booster/pair/complete", json={"code": code, "account_id": "acct-1"}).status_code == 400)
w = c.get("/booster/whoami", headers={"authorization": "Bearer " + tok}).json()
check("token bound to account + booster id + tier", w.get("account") == "acct-1" and w.get("booster_id") == s["booster_id"] and w.get("tier") == "pro", w)
check("tampered token rejected", c.get("/booster/whoami", headers={"authorization": "Bearer " + tok[:-3] + "AAA"}).status_code == 401)
try:
    B.verify_token(B.mint_token("a", "pro", ttl=-5))
    exp_ok = False
except ValueError as e:
    exp_ok = str(e) == "token_expired"
check("expired token rejected (verify)", exp_ok)
code = c.post("/booster/pair/start").json()["code"]
for _ in range(B.MAX_CODE_ATTEMPTS + 1):
    r = c.post("/booster/pair/complete", json={"code": "AAAA-AAAA", "account_id": "acct-1"})
check("brute force locks the code", r.status_code == 429 and
      c.post("/booster/pair/complete", json={"code": code, "account_id": "acct-1"}).status_code == 400)
set_tier("free")
c.post("/booster/pair/start")
r = c.post("/booster/pair/complete", json={"code": "AAAA-AAAA", "account_id": "x"})
check("free tier not entitled to pair", r.status_code == 403 and r.json()["error"]["code"] == "not_entitled")

# ---- /_wire token + CORS
set_tier("pro", sub="acct-1")
code = c.post("/booster/pair/start").json()["code"]
pr = c.post("/booster/pair/complete", json={"code": code, "account_id": "acct-1"}, headers=ORIGIN).json()
check("pair complete returns relay_url/local_url keys", "relay_url" in pr and "local_url" in pr, pr)
check("status has locked + trial_days_left", {"locked", "trial_days_left"} <= set(c.get("/booster/status").json()))
hdr = {**ORIGIN, "x-vyomi-booster-token": pr["token"], "authorization": "AWS4-HMAC-SHA256 Credential=x"}
r = c.get("/_wire/healthz", headers=hdr)
check("/_wire accepts booster token + CORS", r.status_code == 200 and r.headers.get("access-control-allow-origin") == "https://vyomi.cloud", (r.status_code, dict(r.headers)))
r = c.get("/_wire/healthz", headers={**hdr, "x-vyomi-booster-token": "bad.bad.bad"})
check("/_wire rejects bad token", r.status_code == 401)
r = c.options("/_wire/s3", headers={**ORIGIN, "access-control-request-method": "PUT",
              "access-control-request-headers": "x-vyomi-booster-token,authorization"})
check("/_wire preflight allows token header + PNA", r.status_code == 204 and "x-vyomi-booster-token" in r.headers.get("access-control-allow-headers", "")
      and r.headers.get("access-control-allow-private-network") == "true", (r.status_code, dict(r.headers)))

# ---- rate limit
B._RL.clear()
codes = [c.get("/booster/status").status_code for _ in range(B.RATE_LIMIT_PER_MIN + 3)]
check("rate limit kicks in", 429 in codes and codes[0] == 200)
B._RL.clear()

# ---- capacity
set_tier("max", sub="acct-1")
cap = B.resource_budget()["memory_split_mb"]["compute"]
B.can_allocate("compute", cap)                      # exactly the share: fine
for cloud, code_, st in (("aws", "InsufficientInstanceCapacity", 500), ("gcp", "ZONE_RESOURCE_POOL_EXHAUSTED", 503),
                         ("azure", "AllocationFailed", 409)):
    try:
        B.can_allocate("compute", cap + 1, cloud=cloud)
        got = None
    except B.BoosterCapacityError as e:
        got = (e.code, e.status)
    check(f"can_allocate raises {code_}", got == (code_, st), got)
B.allocate("compute", "i-1", cap - 100)
try:
    B.allocate("compute", "i-2", 200)
    ok = False
except B.BoosterCapacityError:
    ok = True
check("allocate ledger enforces cap; usage reported", ok and B.usage()["compute"] == cap - 100)
B.release("compute", "i-1")
B.allocate("compute", "i-2", 200)
check("release frees capacity", B.usage()["compute"] == 200)
B.release("compute", "i-2")
try:
    B.can_allocate("ai", B.resource_budget()["memory_split_mb"]["ai"] + 1)
    ai_ok = False
except B.BoosterCapacityError:
    ai_ok = True
check("AI share capped independently", ai_ok)
B.can_allocate("compute", 10**9, enforce=False)
os.environ["VYOMI_BOOSTER"] = "0"
B.can_allocate("compute", 10**9)
check("no-op when booster mode off", True)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
