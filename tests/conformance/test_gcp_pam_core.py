"""Unit tests for core/gcp_pam_core.py (run: PYTHONPATH=. python3 tests/conformance/test_gcp_pam_core.py)."""
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from core import gcp_iam_core as gcp_iam  # noqa: E402
from core import gcp_pam_core as pam  # noqa: E402
from core.iam_store import InMemoryIamStore  # noqa: E402

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' — ' + str(detail) if detail and not ok else ''}")


def call(st, method, path, body=None, query=None):
    r = pam.dispatch(st, method, path, query or {}, {}, json.dumps(body).encode() if body is not None else b"")
    return r.status, json.loads(r.body or b"{}")


st = pam.PamStore()
project, loc = "demo-proj", "global"
base = f"/v1/projects/{project}/locations/{loc}/entitlements"

s, e = call(st, "POST", base, {
    "maxRequestDuration": "7200s",
    "eligibleUsers": [{"principals": ["user:alice@example.com"]}],
    "approvalWorkflow": {"manualApprovals": {"steps": [{"approvers": [{"principals": ["user:boss@example.com"]}]}]}},
}, query={"entitlementId": "break-glass"})
check("create entitlement 200", s == 200 and e["state"] == "AVAILABLE" and e["name"].endswith("/entitlements/break-glass"), e)

s, dup = call(st, "POST", base, {}, query={"entitlementId": "break-glass"})
check("duplicate entitlement 409", s == 409)

s, lst = call(st, "GET", base)
check("list has break-glass", s == 200 and "break-glass" in [x["name"].rsplit("/", 1)[-1] for x in lst["entitlements"]])

s, got = call(st, "GET", base + "/break-glass")
check("get entitlement 200", s == 200 and got["maxRequestDuration"] == "7200s")

s, missing = call(st, "GET", base + "/nope")
check("get missing -> 404", s == 404)

s, _ = call(st, "DELETE", base + "/break-glass")
check("delete entitlement 200", s == 200)

s, lst2 = call(st, "GET", base)
check("deleted entitlement dropped", lst2["entitlements"] == [])

# ── Grants workflow: request -> approve/deny/revoke, with real IAM bindings ──
iam_store = InMemoryIamStore()
project_resource = f"projects/{project}"


def iam_call(method, path, body=None):
    r = gcp_iam.dispatch(iam_store, method, path, {}, {}, json.dumps(body).encode() if body is not None else b"")
    return r.status, json.loads(r.body or b"{}")


def grant_fn(resource, role, member):
    gcp_iam.grant_member(iam_store, resource, role, member)


def revoke_fn(resource, role, member):
    gcp_iam.revoke_member(iam_store, resource, role, member)


def pam_call(method, path, body=None):
    r = pam.dispatch(st, method, path, {}, {}, json.dumps(body).encode() if body is not None else b"",
                      grant_fn=grant_fn, revoke_fn=revoke_fn)
    return r.status, json.loads(r.body or b"{}")


def bound_members(role):
    _, pol = iam_call("POST", f"/v1/{project_resource}:getIamPolicy", {})
    for b in pol.get("bindings", []):
        if b.get("role") == role:
            return b.get("members", [])
    return []


# auto-approved entitlement (no approval steps) -> grant activates immediately
s, auto_ent = call(st, "POST", base, {
    "maxRequestDuration": "7200s",
    "privilegedAccess": {"gcpIamAccess": {"roleBindings": [{"role": "roles/viewer"}]}},
}, query={"entitlementId": "auto-ent"})
check("create auto-approve entitlement 200", s == 200)

s, g = pam_call("POST", base + "/auto-ent/grants", {"requester": "user:alice@example.com", "requestedDuration": "3600s"})
check("auto-approved grant activates immediately", s == 200 and g["state"] == "ACTIVATED", g)
check("activation applied a real IAM binding", "user:alice@example.com" in bound_members("roles/viewer"))

s, _ = pam_call("POST", g["name"] + ":revoke", {})
check("revoke an active grant 200", s == 200)
check("revoke removed the IAM binding", "user:alice@example.com" not in bound_members("roles/viewer"))

s, re_revoke = pam_call("POST", g["name"] + ":revoke", {})
check("revoking an already-ended grant 400", s == 400)

# entitlement with an approval step -> grant stays pending until approved/denied
s, approval_ent = call(st, "POST", base, {
    "maxRequestDuration": "60s",
    "privilegedAccess": {"gcpIamAccess": {"roleBindings": [{"role": "roles/editor"}]}},
    "approvalWorkflow": {"manualApprovals": {"steps": [{"approvers": [{"principals": ["user:boss@example.com"]}]}]}},
}, query={"entitlementId": "approval-ent"})
check("create approval-required entitlement 200", s == 200)

s, g2 = pam_call("POST", base + "/approval-ent/grants", {"requester": "user:bob@example.com", "requestedDuration": "1s"})
check("grant awaits approval when entitlement requires it", s == 200 and g2["state"] == "APPROVAL_AWAITED", g2)
check("no binding applied before approval", "user:bob@example.com" not in bound_members("roles/editor"))

s, _ = pam_call("POST", g2["name"] + ":approve", {"approver": "user:boss@example.com"})
check("approve activates the grant", s == 200)
check("approval applied a real IAM binding", "user:bob@example.com" in bound_members("roles/editor"))

time.sleep(1.2)
s, swept = pam_call("GET", g2["name"])
check("grant lazily expires after requestedDuration", s == 200 and swept["state"] == "EXPIRED", swept)
check("expiry removed the IAM binding", "user:bob@example.com" not in bound_members("roles/editor"))

s, g3 = pam_call("POST", base + "/approval-ent/grants", {"requester": "user:carol@example.com"})
check("second grant also awaits approval", s == 200 and g3["state"] == "APPROVAL_AWAITED")
s, denied = pam_call("POST", g3["name"] + ":deny", {"approver": "user:boss@example.com"})
check("deny a pending grant 200", s == 200 and denied["state"] == "DENIED", denied)
s, _ = pam_call("POST", g3["name"] + ":approve", {})
check("cannot approve an already-denied grant", s == 400)

s, grants = pam_call("GET", base + "/approval-ent/grants")
check("list grants for an entitlement", s == 200 and {g["name"] for g in grants["grants"]} == {g2["name"], g3["name"]})

s, missing = pam_call("GET", base + "/approval-ent/grants/nope")
check("get missing grant -> 404", s == 404)

# Settings — notification channels + require-justification are ENFORCED, not stored-only.
settings_path = f"/v1/projects/{project}/locations/{loc}/settings"
s, defaults = call(st, "GET", settings_path)
check("get settings 200 with defaults auto-created", s == 200 and defaults["notificationChannels"] == [] and defaults["requireJustification"] is False, defaults)
s, patched = call(st, "PATCH", settings_path, {"notificationChannels": ["secops@example.com"], "requireJustification": True})
check("patch settings 200", s == 200 and patched["notificationChannels"] == ["secops@example.com"] and patched["requireJustification"] is True, patched)
s, roundtrip = call(st, "GET", settings_path)
check("settings round-trip", roundtrip == patched)

s, auto_ent = call(st, "POST", base, {"maxRequestDuration": "3600s"}, query={"entitlementId": "auto-settings-test"})
check("auto entitlement for settings test", s == 200)
s, no_just = call(st, "POST", auto_ent["name"] + "/grants", {"requester": "user:x@example.com"})
check("requireJustification rejects a grant with no justification -> 400", s == 400 and "justification" in no_just["error"]["message"], no_just)
s, with_just = call(st, "POST", auto_ent["name"] + "/grants",
                    {"requester": "user:x@example.com", "justification": {"unstructuredJustification": "need prod access"}})
check("requireJustification accepts a grant WITH a justification", s == 200 and with_just["state"] == "ACTIVATED", with_just)

s, notifs = call(st, "GET", f"/v1/projects/{project}/locations/{loc}/notifications")
check("notifications recorded for the configured channel on REQUESTED + ACTIVATED", s == 200
      and sum(1 for n in notifs["notifications"] if n["grant"] == with_just["name"]) == 2
      and all(n["channels"] == ["secops@example.com"] for n in notifs["notifications"] if n["grant"] == with_just["name"]), notifs)

s, _ = call(st, "PATCH", settings_path, {"notificationChannels": []})
s, no_chan_ent = call(st, "POST", base, {"maxRequestDuration": "3600s"}, query={"entitlementId": "no-channel-test"})
s, g_no_chan = call(st, "POST", no_chan_ent["name"] + "/grants",
                    {"requester": "user:y@example.com", "justification": {"unstructuredJustification": "n/a"}})
s, notifs2 = call(st, "GET", f"/v1/projects/{project}/locations/{loc}/notifications")
check("no notification channels configured -> nothing recorded for that grant",
      all(n["grant"] != g_no_chan["name"] for n in notifs2["notifications"]))

print(f"{PASS} passed, {FAIL} failed")


def test_all_checks_pass():
    assert FAIL == 0


if __name__ == "__main__":
    sys.exit(1 if FAIL else 0)
