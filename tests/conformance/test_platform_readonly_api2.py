"""More read-only platform routes: runtime profile/update-check, audit-chain verify,
license revocation status, disk-cleanup suggestions, shared usage, and the tier-gated
config surfaces (audit sinks, notification channels, custom domain, branding, SSO,
cross-tenant RBAC grants, helm, cloud shell): 200 with the right shape, or the
tier-locked 403 (never a 5xx)."""
import os
import sys

import requests

BASE = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000")
failed = False


def check(name, ok, extra=""):
    global failed
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{'' if ok else ' ' + str(extra)[:300]}")
    failed = failed or not ok


def shape(path, keys, gated=False):
    r = requests.get(BASE + path, timeout=60)
    try:
        b = r.json()
    except Exception:
        b = None
    locked = gated and r.status_code == 403 and isinstance(b, dict) and b.get("detail", {}).get("code") == "tier_feature_locked"
    ok = locked or (r.status_code == 200 and isinstance(b, dict) and all(k in b for k in keys))
    check(f"GET {path} -> 200 with {list(keys)}" + (" (or tier-locked)" if gated else ""), ok, (r.status_code, b))
    return b if r.status_code == 200 else None


p = shape("/api/runtime/profile", ["profile", "restricted", "allowed_clouds"])
if p:
    check("profile allowed_clouds is a non-empty list", isinstance(p["allowed_clouds"], list) and p["allowed_clouds"], p)
u = shape("/api/runtime/update-check", ["current", "latest", "update_available"])
if u:
    check("update-check current version is non-empty", bool(u["current"]), u)
v = shape("/api/security/audit-verify", ["chain_valid", "broken_at_id", "reason"])
if v:
    check("audit chain verifies", v["chain_valid"] is True, v)
shape("/api/license/revocation-status", ["revoked_jtis_count"])
d = shape("/api/runtime/disk-cleanup/suggestions", ["sampled_at", "breakdown", "orphans", "suggestions"])
if d:
    check("suggestions is a list", isinstance(d["suggestions"], list), d)
us = shape("/api/shared/usage", ["ok", "shared_enabled", "usage"])
for path in ("/api/runtime/audit-sinks", "/api/runtime/notification-channels", "/api/runtime/custom-domain",
             "/api/runtime/branding", "/api/runtime/sso", "/api/runtime/xt-rbac/grants",
             "/api/runtime/helm", "/api/runtime/cloud-shell"):
    shape(path, [], gated=True)

sys.exit(1 if failed else 0)
