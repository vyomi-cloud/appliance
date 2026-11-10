"""Read-only platform routes: catalog, packs, host cpu/sizing, instances catalog, budgets,
tenants (+active), shared mode/whoami, install-id, bundles, terraform status, and the
tier-gated terraform-deploy-targets / ci pipelines (200 or the tier-locked message)."""
import os
import sys

import requests

BASE = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000")
failed = False


def check(name, ok, extra=""):
    global failed
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{'' if ok else ' ' + str(extra)[:300]}")
    failed = failed or not ok


def get(path):
    r = requests.get(BASE + path, timeout=60)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, None


def shape(path, keys, gated=False):
    s, b = get(path)
    locked = gated and s == 403 and isinstance(b, dict) and b.get("detail", {}).get("code") == "tier_feature_locked"
    ok = locked or (s == 200 and isinstance(b, dict) and all(k in b for k in keys))
    check(f"GET {path} -> 200 with {list(keys)}" + (" (or tier-locked)" if gated else ""), ok, (s, b))
    return b if s == 200 else None


shape("/api/catalog", ["amis"])
p = shape("/api/packs", ["packs"])
if p:
    check("packs entries have id/provider/state", all({"id", "provider", "state"} <= set(x) for x in p["packs"]), p["packs"][:1])
shape("/api/host/cpu", ["cpu_percent", "cpu_count"])
shape("/api/host/sizing", ["cpu_count", "memory_bytes", "disk_total_bytes"])
c = shape("/api/instances/catalog", ["provider", "count", "instances"])
if c:
    check("instances catalog count matches list", c["count"] == len(c["instances"]) > 0, c["count"])
    check("each instance has name/vcpu/ram_mb", all({"name", "vcpu", "ram_mb"} <= set(i) for i in c["instances"]))
shape("/api/runtime/budgets", ["budgets", "count"])
t = shape("/api/tenants", ["active_tenant_id", "tenants"])
a = shape("/api/tenants/active", ["tenant_id", "tenant"])
if t and a:
    check("active tenant is listed in /api/tenants", a["tenant_id"] in {x["tenant_id"] for x in t["tenants"]}, (a, t))
shape("/api/shared/mode", ["enabled", "source"])
shape("/api/shared/whoami", ["shared_enabled"])
i = shape("/api/runtime/install-id", ["install_id"])
if i:
    check("install-id is stable across calls", get("/api/runtime/install-id")[1] == i)
shape("/api/runtime/bundles", ["bundles"])
shape("/api/terraform/status", ["provider", "summary"])
shape("/api/runtime/terraform-deploy-targets", [], gated=True)
shape("/api/runtime/ci/pipelines", [], gated=True)

sys.exit(1 if failed else 0)
