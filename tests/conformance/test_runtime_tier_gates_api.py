"""Tier-gated runtime routes on the default (Free) appliance: audit sinks, notification channels,
cross-tenant RBAC grants. Every method/path must refuse with the structured upgrade payload, never
a 5xx or a silent success, and tenant switch/delete must 404 on unknown tenants
(/api/runtime/audit-sinks*, /api/runtime/notification-channels*, /api/runtime/xt-rbac/grants*,
/api/tenants/{tid}/switch, DELETE /api/tenants/{tid}).

Tenant caps keep Free at one tenant, so an Enterprise tenant cannot be minted over the API; the
unlocked create/list/delete logic is covered in test_runtime_tier_features_core.py."""
import os
import sys
import uuid

import requests

BASE = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000")
failed = False


def check(name, ok, extra=""):
    global failed
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{'' if ok else ' ' + str(extra)}")
    failed = failed or not ok


def J(r):
    try:
        return r.json()
    except Exception:
        return {}


def main():
    tag = uuid.uuid4().hex[:6]
    tier = J(requests.get(BASE + "/api/tenants/active", timeout=60)).get("tenant", {}).get("license_tier", "free")
    if tier != "free":
        # A licensed appliance unlocks these; the gate assertions only apply to Free.
        print(f"[PASS] appliance tier is {tier}: gate assertions not applicable")
        return
    cases = [
        ("GET", "/api/runtime/audit-sinks", None, "audit_export_sinks"),
        ("POST", "/api/runtime/audit-sinks", {"kind": "file", "path": "/tmp/x"}, "audit_export_sinks"),
        ("DELETE", f"/api/runtime/audit-sinks/asink-{tag}", None, "audit_export_sinks"),
        ("GET", "/api/runtime/notification-channels", None, "notifications"),
        ("POST", "/api/runtime/notification-channels", {"kind": "webhook", "url": "http://127.0.0.1:9/h"}, "notifications"),
        ("DELETE", f"/api/runtime/notification-channels/nch-{tag}", None, "notifications"),
        ("POST", f"/api/runtime/notification-channels/nch-{tag}/test", None, "notifications"),
        ("GET", "/api/runtime/xt-rbac/grants", None, "cross_tenant_rbac"),
        ("POST", "/api/runtime/xt-rbac/grants", {"grantee_tenant": "x", "role": "viewer"}, "cross_tenant_rbac"),
        ("DELETE", f"/api/runtime/xt-rbac/grants/xtg-{tag}", None, "cross_tenant_rbac"),
    ]
    for method, path, body, feature in cases:
        r = requests.request(method, BASE + path, json=body, timeout=60)
        d = J(r).get("detail") or {}
        check(f"free tier: {method} {path} is locked", r.status_code == 403 and d.get("code") == "tier_feature_locked"
              and d.get("feature") == feature and d.get("upgrade_to") and d.get("active_tier") == "free", f"{r.status_code} {r.text[:160]}")

    r = requests.post(f"{BASE}/api/tenants/nope-{tag}/switch", timeout=60)
    check("switch to unknown tenant is 404", r.status_code == 404, r.status_code)
    r = requests.delete(f"{BASE}/api/tenants/nope-{tag}", timeout=60)
    check("delete unknown tenant is 404", r.status_code == 404, r.status_code)
    r = requests.delete(f"{BASE}/api/tenants/default", timeout=60)
    check("default tenant cannot be deleted", r.status_code == 400, r.status_code)
    r = requests.post(BASE + "/api/tenants", json={"name": f"cm-extra-{tag}"}, timeout=60)
    d = J(r).get("detail") or {}
    check("second tenant refused by the Free tenant cap", r.status_code == 403 and d.get("code") == "tier_max_tenants"
          and d.get("limit") == 1, f"{r.status_code} {r.text[:160]}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
