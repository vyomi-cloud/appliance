# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Azure Resource health + Advisor (Nano / dev_server / unified-ingress core, pure Python).

Two real ARM surfaces, derived from the resources the ARM store actually holds (no fabricated
incident feed):

* ``Microsoft.ResourceHealth/availabilityStatuses`` — ``GET {scope}/providers/Microsoft.ResourceHealth/
  availabilityStatuses[/current]`` at resource, resource-group or subscription scope. The state is
  computed from the resource's own record: provisioningState Failed -> Unavailable (Unplanned);
  a stopped / deallocated VM or a stopped AKS cluster -> Unavailable (UserInitiated); anything
  else -> Available. There is no real Azure platform behind Vyomi to emit platform outages.
* ``Microsoft.Advisor/recommendations`` — ``GET /subscriptions/{sub}/providers/Microsoft.Advisor/
  recommendations[?$filter=Category eq 'Security']``, plus ``/suppressions`` (snooze / dismiss),
  from a small deterministic rule set evaluated over each resource's stored configuration.

Each function returns ``{"status": int, "body": dict | None}``.
"""
from __future__ import annotations

import datetime
import hashlib

HEALTH_API = "2022-10-01"
ADVISOR_API = "2023-01-01"
SUPPRESSION_TYPE = "microsoft.advisor/suppressions"


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _err(status, code, msg):
    return {"status": status, "body": {"error": {"code": code, "message": msg}}}


def find_health_marker(chain):
    """Index of ``providers/Microsoft.ResourceHealth/availabilityStatuses`` re-entering a resource chain."""
    for i in range(len(chain) - 2):
        if (chain[i].lower() == "providers" and chain[i + 1].lower() == "microsoft.resourcehealth"
                and chain[i + 2].lower() == "availabilitystatuses"):
            return i
    return None


# ── Resource health ──────────────────────────────────────────────────────────────────────
_SKIP = ("microsoft.resources/", "microsoft.authorization", "microsoft.security", "microsoft.insights", SUPPRESSION_TYPE)


def _status_for(rec: dict) -> dict:
    props = rec.get("properties") or {}
    rtype = str(rec.get("_type", ""))
    prov = str(props.get("provisioningState") or "Succeeded")
    power = str(props.get("powerState") or "")
    if isinstance(props.get("powerState"), dict):
        power = str(props["powerState"].get("code") or "")
    state, reason, title, summary = "Available", "", "Available", "There aren't any known Azure platform problems affecting this resource."
    if prov.lower() == "failed":
        state, reason, title = "Unavailable", "Unplanned", "Unavailable"
        summary = "The resource's last provisioning operation failed."
    elif rtype.lower() == "microsoft.compute/virtualmachines" and power.lower() in ("powerstate/stopped", "powerstate/deallocated", "powerstate/deallocating", "stopped"):
        state, reason, title = "Unavailable", "UserInitiated", "Unavailable"
        summary = "The virtual machine is stopped or deallocated (a user-initiated operation)."
    elif rtype.lower() == "microsoft.containerservice/managedclusters" and power.lower() == "stopped":
        state, reason, title = "Unavailable", "UserInitiated", "Unavailable"
        summary = "The cluster is stopped (a user-initiated operation)."
    elif prov.lower() in ("creating", "updating", "deleting", "accepted"):
        state, reason, title = "Unknown", "", "Unknown"
        summary = f"The resource is {prov.lower()}; its health will be reported once the operation completes."
    rid = rec.get("id") or ""
    return {
        "id": f"{rid}/providers/Microsoft.ResourceHealth/availabilityStatuses/current", "name": "current",
        "type": "Microsoft.ResourceHealth/AvailabilityStatuses", "location": rec.get("location", ""),
        "properties": {"availabilityState": state, "title": title, "summary": summary,
                       "detailedStatus": summary, "reasonType": reason, "category": "Unplanned" if reason == "Unplanned" else ("Planned" if reason else ""),
                       "context": "Platform" if reason != "UserInitiated" else "Customer initiated",
                       "occurredTime": _now(), "reportedTime": _now(), "resourceId": rid, "resourceType": rec.get("type") or rtype}}


def health(state: dict, sub: str, scope_rid: str | None, current_only: bool) -> dict:
    """``scope_rid`` = a resource id (-> its current status), a resource-group id, or None (subscription)."""
    scope = (scope_rid or "").lower()
    if scope and current_only:
        rec = state.get(scope)
        if not isinstance(rec, dict):
            return _err(404, "ResourceNotFound", f"Resource '{scope_rid}' was not found.")
        return {"status": 200, "body": _status_for({**{k: v for k, v in rec.items() if not k.startswith("_")}, "_type": rec.get("_type")})}
    rg_scope = scope if scope.count("/") == 4 and "/resourcegroups/" in scope else ""
    out = []
    for r in state.values():
        if not isinstance(r, dict) or r.get("_sub") != sub:
            continue
        t = str(r.get("_type", "")).lower()
        if "/" not in t or t.startswith(_SKIP):
            continue
        rid = str(r.get("id") or "")
        if rg_scope and not rid.lower().startswith(rg_scope + "/"):
            continue
        out.append(_status_for({**{k: v for k, v in r.items() if not k.startswith("_")}, "_type": r.get("_type")}))
    out.sort(key=lambda s: s["id"].lower())
    return {"status": 200, "body": {"value": out}}


# ── Advisor ──────────────────────────────────────────────────────────────────────────────
def _nsg_open_admin(props) -> bool:
    for rule in props.get("securityRules") or []:
        p = rule.get("properties", rule)
        if str(p.get("access", "")).lower() != "allow" or str(p.get("direction", "")).lower() != "inbound":
            continue
        src = str(p.get("sourceAddressPrefix") or "")
        if src not in ("*", "Internet", "0.0.0.0/0"):
            continue
        ports = [str(p.get("destinationPortRange") or "")] + [str(x) for x in p.get("destinationPortRanges") or []]
        if any(x in ("*", "22", "3389") for x in ports):
            return True
    return False


# (rule id, type, category, impact, problem, solution, predicate(props))
RULES = [
    ("kv-soft-delete", "microsoft.keyvault/vaults", "Security", "High", "Soft delete should be enabled on key vaults", "Enable soft delete so deleted keys, secrets and certificates can be recovered.", lambda p: p.get("enableSoftDelete") is False),
    ("kv-purge-protection", "microsoft.keyvault/vaults", "Security", "Medium", "Purge protection should be enabled on key vaults", "Enable purge protection to stop deleted vaults and objects from being purged before retention ends.", lambda p: p.get("enablePurgeProtection") is False),
    ("st-secure-transfer", "microsoft.storage/storageaccounts", "Security", "High", "Secure transfer to storage accounts should be enabled", "Require HTTPS (supportsHttpsTrafficOnly) for requests to the account.", lambda p: p.get("supportsHttpsTrafficOnly") is False),
    ("st-public-blob", "microsoft.storage/storageaccounts", "Security", "Medium", "Storage account public access should be disallowed", "Set allowBlobPublicAccess to false unless anonymous container access is required.", lambda p: p.get("allowBlobPublicAccess") is True),
    ("st-tls", "microsoft.storage/storageaccounts", "Security", "Medium", "Storage accounts should use TLS 1.2 or later", "Raise minimumTlsVersion to TLS1_2.", lambda p: str(p.get("minimumTlsVersion") or "TLS1_2") in ("TLS1_0", "TLS1_1")),
    ("sql-tls", "microsoft.sql/servers", "Security", "Medium", "SQL servers should require TLS 1.2 or later", "Raise minimalTlsVersion to 1.2.", lambda p: str(p.get("minimalTlsVersion") or "1.2") in ("1.0", "1.1")),
    ("nsg-admin-ports", "microsoft.network/networksecuritygroups", "Security", "High", "Management ports should be closed to the internet", "Restrict inbound SSH (22) / RDP (3389) to known source addresses instead of Any/Internet.", _nsg_open_admin),
    ("web-https-only", "microsoft.web/sites", "Security", "Medium", "Web apps should only be accessible over HTTPS", "Turn on HTTPS Only for the app.", lambda p: p.get("httpsOnly") is False),
    ("acr-admin-user", "microsoft.containerregistry/registries", "Security", "Medium", "Container registry admin account should be disabled", "Disable the admin user and authenticate with Entra ID / tokens.", lambda p: p.get("adminUserEnabled") is True),
]


def _rec_id(sub, rule_id, rid):
    return hashlib.sha1(f"{rule_id}|{rid}".lower().encode()).hexdigest()[:32]


def _suppressions(state, sub):
    return {r["_rec"]: r for r in state.values() if isinstance(r, dict) and str(r.get("_type", "")).lower() == SUPPRESSION_TYPE and r.get("_sub") == sub}


def recommendations(state: dict, sub: str, query: dict | None = None) -> dict:
    flt = str((query or {}).get("$filter") or "")
    import re
    cat = re.search(r"Category\s+eq\s+'([^']*)'", flt, re.I)
    rgf = re.search(r"ResourceGroup\s+eq\s+'([^']*)'", flt, re.I)
    sup = _suppressions(state, sub)
    out = []
    for r in state.values():
        if not isinstance(r, dict) or r.get("_sub") != sub:
            continue
        t = str(r.get("_type", "")).lower()
        # kind=functionapp rows share microsoft.web/sites: Advisor treats them as sites as well
        for rule_id, rtype, category, impact, problem, solution, pred in RULES:
            if t != rtype:
                continue
            props = r.get("properties") or {}
            try:
                hit = bool(pred(props))
            except Exception:
                hit = False
            if not hit:
                continue
            rid = str(r.get("id") or "")
            rec_id = _rec_id(sub, rule_id, rid)
            if rgf and str(r.get("_rg") or "").lower() != rgf.group(1).lower():
                continue
            if cat and category.lower() != cat.group(1).lower():
                continue
            s = sup.get(rec_id)
            out.append({
                "id": f"{rid}/providers/Microsoft.Advisor/recommendations/{rec_id}", "name": rec_id,
                "type": "Microsoft.Advisor/recommendations",
                "properties": {"category": category, "impact": impact, "impactedField": r.get("_type"), "impactedValue": r.get("name"),
                               "lastUpdated": _now(), "recommendationTypeId": rule_id,
                               "shortDescription": {"problem": problem, "solution": solution},
                               "resourceMetadata": {"resourceId": rid},
                               "suppressionIds": [s["name"]] if s else []}})
    out.sort(key=lambda x: (x["properties"]["impact"] != "High", x["properties"]["impact"] != "Medium", x["id"].lower()))
    return {"status": 200, "body": {"value": out}}


def suppress(state: dict, sub: str, rec_id: str, name: str, method: str, payload: dict | None) -> dict:
    key = f"/subscriptions/{sub}/providers/microsoft.advisor/suppressions/{rec_id}/{name}".lower()
    if method == "DELETE":
        state.pop(key, None)
        return {"status": 204, "body": None}
    if method in ("PUT", "POST"):
        ttl = str(((payload or {}).get("properties") or {}).get("ttl") or "-1")
        rec = {"id": key, "name": name, "type": "Microsoft.Advisor/suppressions", "properties": {"suppressionId": name, "ttl": ttl},
               "_type": SUPPRESSION_TYPE, "_sub": sub, "_rec": rec_id}
        state[key] = rec
        return {"status": 200, "body": {k: v for k, v in rec.items() if not k.startswith("_")}}
    if method == "GET":
        rec = state.get(key)
        return {"status": 200, "body": {k: v for k, v in rec.items() if not k.startswith("_")}} if rec else _err(404, "ResourceNotFound", "Suppression not found.")
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")
