"""Per-simulator trial + marketplace rules.  Run:  PYTHONPATH=. <python> tests/test_marketplace_trials.py
Part 1: pure rules (core/sim_marketplace.py). Part 2: HTTP routes on an isolated state file."""
import os, sys, tempfile
from datetime import timedelta

_tmp = tempfile.mkdtemp(prefix="mkt-test-")
os.environ["CLOUDLEARN_STATE_FILE"] = os.path.join(_tmp, "state.sqlite3")
os.environ["CLOUDLEARN_LEGACY_STATE_FILE"] = os.path.join(_tmp, "legacy.json")
os.environ.pop("CODESPACE_NAME", None)

from core import sim_marketplace as mk

fails = []
def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond: fails.append(name)

now = mk.now_utc()
FAKE = [{"id": "aws", "name": "AWS", "free_tier": True}, {"id": "fake", "name": "Fake", "free_tier": False}]

# ---- entitlement
check("max covers all", all(mk.licensed_tier(c, "max", "") == "max" for c in ("aws", "gcp", "azure")))
check("pro covers only its cloud", mk.licensed_tier("gcp", "pro", "gcp") == "pro" and mk.licensed_tier("aws", "pro", "gcp") is None)
check("pro with no primary cloud covers nothing", mk.licensed_tier("aws", "pro", "") is None)
check("free/nano are not licences", mk.licensed_tier("aws", "free", "") is None and mk.licensed_tier("aws", "nano", "") is None)

# ---- offers / ladder
o = mk.offers_for("gcp", None)
check("unlicensed: one a-la-carte offer, $21 month-to-month, simulator checkout", len(o) == 1 and o[0]["price_usd"] == 21 and "product=simulator&simulator=gcp" in o[0]["url"])
check("covered simulator has no offer", mk.offers_for("gcp", "pro") == [] and mk.offers_for("gcp", "max") == [])
check("ladder order Pro < individual < Max", mk.PLANS["pro"]["price_usd"] < mk.SIMULATORS[0]["price_usd"] < mk.PLANS["max"]["price_usd"])
check("owned simulator behaves as Pro on that cloud only", mk.licensed_tier("gcp", "free", "", ["gcp"]) == "pro" and mk.licensed_tier("aws", "free", "", ["gcp"]) is None)
check("plan beats owned", mk.licensed_tier("gcp", "max", "", ["gcp"]) == "max")
ls = mk.licence_summary("pro", "gcp", ["aws"])
check("licence strip: Pro names its cloud", ls["tier"] == "pro" and "Google Cloud" in ls["detail"] and ls["owned"] == ["aws"])

# ---- AI stack add-on
ai1 = mk.ai_stack_cards(["aws"], ["aws", "gcp"])
check("AI stack: $12 per cloud, $19 all clouds", [(c["id"], c["price_usd"]) for c in ai1] == [("aws", 12), ("gcp", 12), ("azure", 12)])
check("AI single: only the bought cloud is enabled; needs the simulator in Spaces", [c["enabled"] for c in ai1] == [True, False, False] and ai1[2]["requires_simulator"] and not ai1[1]["requires_simulator"])
ai2 = mk.ai_stack_cards("all", ["aws"])
check("AI all-clouds licence enables every card", all(c["enabled"] for c in ai2) and all(c["url"] == "" for c in ai2))
check("AI checkout url", "product=ai_stack&scope=gcp" in ai1[1]["url"])

# ---- add-on enforcement (tier gate)
from core import tier_policy as tp
check("AI services are closed on Free", tp.check_service("free", "bedrock", request_cloud="aws")["ok"] is False)
check("AI services are closed even on Max without the AI stack", tp.check_service("max", "bedrock", request_cloud="aws")["code"] == "ai_stack_required")
check("AI stack for aws opens AI on aws only", tp.check_service("free", "bedrock", request_cloud="aws", ai_clouds={"aws"})["ok"] and not tp.check_service("free", "vertexai", request_cloud="gcp", ai_clouds={"aws"})["ok"])
check("AI stack does NOT unlock non-AI services (RDS stays Pro-locked on Free)", tp.check_service("free", "dynamodb", request_cloud="aws", ai_clouds={"aws"})["ok"] is False)
check("AI stack does not change what Free already gets (it adds nothing to compute)", tp.check_service("free", "ec2", request_cloud="aws", ai_clouds={"aws"}) == tp.check_service("free", "ec2", request_cloud="aws"))
check("owned Full Cloud stack opens every non-AI service on that cloud", tp.check_service("free", "dynamodb", request_cloud="aws", owned_clouds={"aws"})["ok"])
check("owned stack on aws does not open gcp services or AI", tp.check_service("free", "firestore", request_cloud="gcp", owned_clouds={"aws"})["ok"] is False and tp.check_service("free", "bedrock", request_cloud="aws", owned_clouds={"aws"})["ok"] is False)
own, ai = mk.entitlements_from_claims({"simulators": ["aws", "bogus"], "ai_stack": ["gcp"]})
check("claims -> entitlements", own == {"aws"} and ai == {"gcp"})
check("ai_stack 'all' -> every cloud", mk.entitlements_from_claims({"ai_stack": "all"})[1] == {"aws", "gcp", "azure"})

# ---- start / countdown
sp = {"space_id": "s1", "provider": "aws"}
check("no trial -> free", mk.effective(sp, None, now)["tier"] == "free")
check("start_trial starts", mk.start_trial(sp, "pro", now) is True)
check("trial is 14 days", mk.parse_iso(sp["trial_ends_at"]) - mk.parse_iso(sp["trial_started_at"]) == timedelta(days=14))
e = mk.effective(sp, None, now + timedelta(days=3))
check("active trial -> pro, 11 days left", e["tier"] == "pro" and e["source"] == "trial" and e["trial"]["days_left"] == 11)
check("trial is never restarted", mk.start_trial(sp, "max", now + timedelta(days=1)) is False and sp["trial_tier"] == "pro")
e = mk.effective(sp, None, now + timedelta(days=15))
check("exhausted trial falls back to Free", e["tier"] == "free" and e["trial"]["state"] == "ended")
check("licence wins over trial", mk.effective(sp, "max", now)["tier"] == "max" and mk.effective(sp, "max", now)["source"] == "license")
sp2 = {}; mk.start_trial(sp2, "bogus", now)
check("unknown trial tier -> pro", sp2["trial_tier"] == "pro")

# ---- sweep: free_tier simulators keep the space, no-free-tier ones are removed
state = {}
spaces = {"a": {"space_id": "a", "provider": "aws"}, "f": {"space_id": "f", "provider": "fake"}}
mk.start_trial(spaces["a"], "pro", now); mk.start_trial(spaces["f"], "pro", now)
check("nothing removed while trials active", mk.sweep_expired(state, spaces, {}, FAKE, now + timedelta(days=5)) == [])
rm = mk.sweep_expired(state, spaces, {}, FAKE, now + timedelta(days=15))
check("no-free-tier space removed after trial", [r["space_id"] for r in rm] == ["f"] and "f" not in spaces)
check("free-tier space kept (back to Free)", "a" in spaces)
check("ended simulator recorded", "fake" in mk.ended_map(state))
sim_fake = mk.get_simulator("fake", FAKE)
c = mk.card_state(sim_fake, None, None, mk.ended_map(state), now)
check("card shows trial_ended and cannot be re-added", c["trial_ended"] and not c["can_add"])
c = mk.card_state(sim_fake, None, "max", mk.ended_map(state), now)
check("licence re-enables a trial-ended simulator", c["can_add"] and not c["trial_ended"])
spaces["f2"] = {"space_id": "f2", "provider": "fake"}; mk.start_trial(spaces["f2"], "pro", now)
check("licensed no-free-tier space is NOT removed", mk.sweep_expired({}, spaces, {"fake": "max"}, FAKE, now + timedelta(days=30)) == [])
check("registry drives the list", [s["id"] for s in mk.SIMULATORS] == ["aws", "gcp", "azure"] and all(s["free_tier"] for s in mk.SIMULATORS))

# ---- HTTP routes (isolated state)
from fastapi.testclient import TestClient
import server  # must import
from core import app_context as ctx
cl = TestClient(server.app)
r = cl.get("/api/marketplace/simulators"); check("GET simulators 200", r.status_code == 200)
ids = [s["id"] for s in r.json()["simulators"]]; check("lists exactly the registry", ids == ["aws", "gcp", "azure"])
for s in ctx.PLATFORM.list_spaces():   # clean slate
    ctx.PLATFORM.delete_space(s["space_id"])
r1 = cl.post("/api/marketplace/simulators/gcp/add").json(); r2 = cl.post("/api/marketplace/simulators/gcp/add").json()
check("add is idempotent (one space per cloud)", r1["created"] and not r2["created"] and r1["space_id"] == r2["space_id"])
cl.post("/api/marketplace/simulators/aws/add"); cl.post("/api/marketplace/simulators/azure/add")
lst = cl.get("/api/spaces").json()["spaces"]
check("3 spaces, all Free, no trial", len([s for s in lst if s["provider"] in ("aws", "gcp", "azure")]) >= 3 and all(s["tier"] == "free" for s in lst if s.get("tier")))
sid = r1["space_id"]
t = cl.post(f"/api/spaces/{sid}/trial/start", json={"tier": "pro"}).json()
check("trial/start via HTTP", t["started"] and t["tier"] == "pro" and t["trial"]["days_left"] == 14)
g = [s for s in cl.get("/api/spaces").json()["spaces"] if s["space_id"] == sid][0]
check("space listing shows pro trial", g["tier"] == "pro" and g["tier_source"] == "trial")
card = [s for s in cl.get("/api/marketplace/simulators").json()["simulators"] if s["id"] == "gcp"][0]
check("marketplace card has no countdown fields", "trial" not in card and "days_left" not in card and not card["licensed"])
# expire it: back to Free, space kept
ctx.STATE["spaces"]["spaces"][sid]["trial_ends_at"] = mk.iso(mk.now_utc() - timedelta(seconds=5))
g = [s for s in cl.get("/api/spaces").json()["spaces"] if s["space_id"] == sid][0]
check("HTTP: exhausted trial -> Free, space kept", g["tier"] == "free" and g["trial"]["state"] == "ended")
check("HTTP: second trial refused (started=false)", cl.post(f"/api/spaces/{sid}/trial/start", json={}).json()["started"] is False)
# no-free-tier path through the real routes with a fake simulator
mk.SIMULATORS.append({"id": "fakecloud", "name": "Fake", "free_tier": False})
from core import vyomi_platform
fid = "fake-space-1"
ctx.STATE["spaces"]["spaces"][fid] = {"space_id": fid, "provider": "fakecloud", "name": "Fake", "tenant_id": ctx.active_tenant_id(),
    "trial_started_at": "2020-01-01T00:00:00Z", "trial_ends_at": "2020-01-15T00:00:00Z", "trial_tier": "pro"}
check("listing sweeps exhausted no-free-tier space", fid not in [s["space_id"] for s in cl.get("/api/spaces").json()["spaces"]] and fid not in ctx.STATE["spaces"]["spaces"])
card = [s for s in cl.get("/api/marketplace/simulators").json()["simulators"] if s["id"] == "fakecloud"][0]
check("card: Trial ended + cannot add", card["trial_ended"] and not card["can_add"])
r = cl.post("/api/marketplace/simulators/fakecloud/add"); check("re-add refused 403 trial_ended", r.status_code == 403 and r.json()["detail"]["code"] == "trial_ended")
mk.SIMULATORS.pop()
# sandbox signal
os.environ["CODESPACE_NAME"] = "x"; check("profile.sandbox true in Codespaces", cl.get("/api/runtime/profile").json()["sandbox"] is True)
del os.environ["CODESPACE_NAME"]; check("profile.sandbox false offline", cl.get("/api/runtime/profile").json()["sandbox"] is False)

print("\n%d failed" % len(fails)); sys.exit(1 if fails else 0)
