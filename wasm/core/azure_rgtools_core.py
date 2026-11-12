# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Resource group tools (pure Python, Nano + offline): (1) force delete of virtual machines / scale sets and (2) resource group Insights.

(1) ``DELETE /subscriptions/{s}/resourcegroups/{rg}?forceDeletionTypes=Microsoft.Compute/virtualMachines,Microsoft.Compute/virtualMachineScaleSets``
    is the real ARM parameter behind the portal's "Apply force delete for selected Virtual machines and Virtual machine scale sets". Only those two
    types are accepted (anything else is a 400). What differs in Vyomi, and is visible in the Activity log:
      * NOT forced: every running VM / scale set in the group is first taken through the graceful path -- a ``deallocate/action`` row, its
        powerState goes to ``PowerState/deallocated`` -- and only then deleted;
      * forced (the type is listed): the resource is deleted directly, with a ``Force delete ...`` delete row and no deallocate step.
    Either way every VM / scale set gets its own delete row (real ARM records per-resource deletes). Dependency-ordered teardown of the other
    resource types and a real guest shutdown are not modelled (see core/capabilities/azure/resourcegroups.json).
(2) ``GET {rg}/providers/Microsoft.Vyomi/insights`` -- the "Insights (preview)" page of a resource group, computed from the REAL records: inventory by
    type / location, tag coverage, VM power states, failed provisioning, locks, alert rules, resource health, Advisor recommendations and the group's
    Activity log (24h operation count, failures, top operations). No metrics or cost are invented.
"""
from __future__ import annotations

import datetime

VM_T = "microsoft.compute/virtualmachines"
VMSS_T = "microsoft.compute/virtualmachinescalesets"
FORCEABLE = {VM_T: "Microsoft.Compute/virtualMachines", VMSS_T: "Microsoft.Compute/virtualMachineScaleSets"}
EVENT_TYPE_HINT = "/__event__/"
RG_T = "microsoft.resources/resourcegroups"


def _err(status, code, msg):
    return {"status": status, "body": {"error": {"code": code, "message": msg}}}


def parse_force(value):
    """-> (set of lower-cased forced types, error response or None)"""
    if not value:
        return set(), None
    out = set()
    for t in str(value).split(","):
        t = t.strip()
        if not t:
            continue
        if t.lower() not in FORCEABLE:
            return set(), _err(400, "InvalidForceDeletionType",
                               f"Force deletion is not supported for resource type '{t}'. Supported: {', '.join(FORCEABLE.values())}.")
        out.add(t.lower())
    return out, None


def _in_group(rec, sub, rg):
    return isinstance(rec, dict) and rec.get("_sub") == sub and (rec.get("_rg") or "").lower() == rg.lower()


def _is_event(key):
    return EVENT_TYPE_HINT in key


def group_resources(state, sub, rg):
    return [(k, r) for k, r in state.items() if not _is_event(k) and _in_group(r, sub, rg) and (r.get("_type") or "").lower() != RG_T]


def prepare_delete(state, sub, rg, forced):
    """Called BEFORE the group's records are removed. Returns [(resource_id, operation_name, operation_text)] to record, in order."""
    rows = []
    for key, r in sorted(group_resources(state, sub, rg), key=lambda kv: kv[0]):
        t = (r.get("_type") or "").lower()
        if t not in FORCEABLE:
            continue
        rid = r.get("id") or key
        label = "Virtual Machine" if t == VM_T else "Virtual Machine Scale Set"
        prov = FORCEABLE[t]
        running = str((r.get("properties") or {}).get("powerState") or "PowerState/running").lower() not in ("powerstate/deallocated", "powerstate/stopped")
        if t in forced:
            rows.append((rid, f"{prov}/delete", f"Force delete {label}"))
        else:
            if running:
                r.setdefault("properties", {})["powerState"] = "PowerState/deallocated"
                rows.append((rid, f"{prov}/deallocate/action", f"Deallocate {label}"))
            rows.append((rid, f"{prov}/delete", f"Delete {label}"))
    return rows


# ── Insights ────────────────────────────────────────────────────────────────────────────
def _count(items, key):
    out = {}
    for it in items:
        k = key(it)
        out[k] = out.get(k, 0) + 1
    return out


def insights(state, sub, rg, health_engine=None):
    res = group_resources(state, sub, rg)
    if not res and not any(r.get("_type", "").lower() == RG_T and r.get("name", "").lower() == rg.lower() for r in state.values() if isinstance(r, dict)):
        return _err(404, "ResourceGroupNotFound", f"Resource group '{rg}' could not be found.")
    top = [(k, r) for k, r in res if "/providers/microsoft.authorization/" not in k and "/providers/microsoft.insights/diagnosticsettings/" not in k]
    types = _count(top, lambda kv: kv[1].get("type") or kv[1].get("_type"))
    locs = _count(top, lambda kv: str(kv[1].get("location") or "global").lower())
    tagged = [kv for kv in top if kv[1].get("tags")]
    untagged = [kv for kv in top if not kv[1].get("tags")]
    keys = _count([(k, v) for _, r in tagged for k, v in (r.get("tags") or {}).items()], lambda kv: kv[0])
    vms = [kv for kv in top if (kv[1].get("_type") or "").lower() == VM_T]
    vmss = [kv for kv in top if (kv[1].get("_type") or "").lower() == VMSS_T]
    power = _count(vms, lambda kv: str((kv[1].get("properties") or {}).get("powerState") or "PowerState/running").replace("PowerState/", ""))
    failed = [{"id": r.get("id"), "provisioningState": (r.get("properties") or {}).get("provisioningState")} for _, r in top
              if str((r.get("properties") or {}).get("provisioningState") or "Succeeded").lower() in ("failed", "canceled")]
    locks = [r for k, r in state.items() if isinstance(r, dict) and (r.get("_type") or "").lower() == "microsoft.authorization/locks" and k.startswith(f"/subscriptions/{sub}/resourcegroups/{rg}/".lower())]
    alert_types = ("microsoft.insights/metricalerts", "microsoft.insights/activitylogalerts", "microsoft.insights/scheduledqueryrules")
    alerts = [kv for kv in top if (kv[1].get("_type") or "").lower() in alert_types]
    out = {"resourceGroup": rg, "generatedAt": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "inventory": {"resourceCount": len(top), "byType": [{"type": t, "count": c} for t, c in sorted(types.items(), key=lambda x: (-x[1], x[0]))],
                         "byLocation": [{"location": l, "count": c} for l, c in sorted(locs.items(), key=lambda x: (-x[1], x[0]))]},
           "tags": {"tagged": len(tagged), "untagged": len(untagged), "coveragePercent": round(100 * len(tagged) / len(top)) if top else 100,
                    "untaggedResources": [kv[1].get("id") for kv in untagged[:25]],
                    "keys": [{"key": k, "count": c} for k, c in sorted(keys.items(), key=lambda x: (-x[1], x[0]))]},
           "compute": {"virtualMachines": len(vms), "powerStates": power, "scaleSets": len(vmss),
                       "scaleSetInstances": sum(int((kv[1].get("sku") or {}).get("capacity") or 0) for kv in vmss)},
           "provisioning": {"failed": failed},
           "locks": len(locks), "alertRules": len(alerts)}
    # resource health + advisor (the same engines the Health blades use)
    try:
        if health_engine is not None:
            h = health_engine.health(state, sub, f"/subscriptions/{sub}/resourceGroups/{rg}", False)
            vals = (h.get("body") or {}).get("value") or []
            states = _count(vals, lambda v: str((v.get("properties") or {}).get("availabilityState") or "Unknown"))
            out["health"] = {"statuses": states, "resources": len(vals)}
            rec = health_engine.recommendations(state, sub, {"$filter": f"ResourceGroup eq '{rg}'"})
            rv = (rec.get("body") or {}).get("value") or []
            out["advisor"] = {"total": len(rv), "byImpact": _count(rv, lambda v: str((v.get("properties") or {}).get("impact") or "Unknown")),
                              "byCategory": _count(rv, lambda v: str((v.get("properties") or {}).get("category") or "Unknown"))}
    except Exception:
        pass
    # the group's Activity log (only rows the simulator really recorded)
    now = datetime.datetime.now(datetime.timezone.utc)
    ev, fails, ops = 0, 0, {}
    pre = f"/subscriptions/{sub}/resourcegroups/{rg}/".lower()
    for k, r in state.items():
        if not _is_event(k) or not k.startswith(pre) or not isinstance(r, dict):
            continue
        try:
            ts = datetime.datetime.strptime(str(r.get("eventTimestamp"))[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=datetime.timezone.utc)
        except ValueError:
            continue
        if (now - ts).total_seconds() > 86400:
            continue
        ev += 1
        name = (r.get("operationName") or {}).get("value", "")
        ops[name] = ops.get(name, 0) + 1
        if str((r.get("status") or {}).get("value", "")).lower() == "failed":
            fails += 1
    out["activity"] = {"last24h": ev, "failed": fails, "topOperations": [{"operation": o, "count": c} for o, c in sorted(ops.items(), key=lambda x: (-x[1], x[0]))[:8]]}
    return {"status": 200, "body": out}
