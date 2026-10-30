"""Unit tests for core/gcp_pam_core.py (run: PYTHONPATH=. python3 tests/conformance/test_gcp_pam_core.py)."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from core import gcp_pam_core as pam  # noqa: E402

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

print(f"{PASS} passed, {FAIL} failed")


def test_all_checks_pass():
    assert FAIL == 0


if __name__ == "__main__":
    sys.exit(1 if FAIL else 0)
