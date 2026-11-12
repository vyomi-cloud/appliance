# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Vyomi GCP aggregate surfaces — substrate-independent, stdlib only.

Path family `/vyomi/gcp/{project}/...` (Vyomi's own wire; Google has no public API for these console pages):

  marketplace/products[/{id}]            GCP Marketplace catalog = Vyomi SaaS-simulator "spaces" (same catalog as the
                                         AWS Marketplace core): list/search, describe (+ subscription state)
  marketplace/subscriptions[/{id}]       POST {productId, acceptEula:true} -> subscription + a live space (endpoint, api key);
                                         GET; DELETE cancels
  hub/overview                           Cloud Hub: real resource counts per product, open incidents, recent admin activity
  privacy/overview                       Privacy & Security: data-residency constraints, audit-log config, CMEK keys, access summary
  privacy/access-log                     Access Transparency-style log derived from Admin Activity audit entries

Everything is DERIVED from live state (`inputs()` supplied by the host reads the real stores / Cloud Logging); the only
state kept here is the marketplace subscriptions (store.ext["gcp_market"]). No Google staff exist in a simulator, so the
"access log" lists privileged control-plane access recorded by the audit-log pipeline (core/gcp_audit_core.py).
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone

try:
    from core import marketplace_core as _mp
    from core.gcp_firestore_core import FirestoreResponse
except ImportError:  # pragma: no cover - Pyodide flat layout
    import marketplace_core as _mp  # type: ignore
    from gcp_firestore_core import FirestoreResponse  # type: ignore


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _err(status, gs, msg):
    return FirestoreResponse(status, {"content-type": "application/json"}, json.dumps({"error": {"code": status, "message": msg, "status": gs}}).encode())


def _json(o):
    return FirestoreResponse(200, {"content-type": "application/json"}, json.dumps(o).encode())


def is_hub_path(path: str) -> bool:
    return path.split("?", 1)[0].startswith("/vyomi/gcp/")


def _subs(store) -> dict:
    if getattr(store, "ext", None) is None:
        store.ext = {}
    return store.ext.setdefault("gcp_market", {})


def _catalog() -> list:
    out = []
    for pid, name, cat, desc, ops in _mp._SAAS:
        out.append({"id": pid, "name": name, "vendor": "Vyomi", "category": cat, "description": desc, "type": "SaaS space",
                    "pricing": "Free in Vyomi (simulated; no metering)", "operations": ops, "tier": "Simulator"})
    return out


def _space(project: str, p: dict) -> dict:
    key = hashlib.sha256(("%s:%s" % (project, p["id"])).encode()).hexdigest()[:32]
    return {"endpoint": "https://%s.spaces.vyomi.local" % p["id"], "apiKey": "vy_" + key, "operations": p["operations"]}


def dispatch(store, method: str, path: str, query=None, headers=None, body: bytes = b"", inputs=None) -> FirestoreResponse:
    query = query or {}
    method = method.upper()
    m = re.match(r"^/vyomi/gcp/([^/]+)/(marketplace|hub|privacy)/([^/]+)(?:/([^/]+))?$", path.split("?", 1)[0])
    if not m:
        return _err(404, "NOT_FOUND", "Unknown path: " + path)
    project, family, res, rid = m.groups()
    try:
        data = json.loads(body.decode() or "{}") if body else {}
        if not isinstance(data, dict):
            raise ValueError
    except Exception:
        return _err(400, "INVALID_ARGUMENT", "Request body must be a JSON object.")
    if family == "marketplace":
        cat = {p["id"]: p for p in _catalog()}
        subs = _subs(store)
        mine = {k: v for k, v in subs.items() if v["project"] == project}
        if res == "products":
            if rid:
                p = cat.get(rid)
                if not p:
                    return _err(404, "NOT_FOUND", f"Product {rid} not found.")
                sub = next((s for s in mine.values() if s["productId"] == rid and s["state"] == "ACTIVE"), None)
                return _json({**p, "subscription": sub})
            q = str(query.get("q") or query.get("filter") or "").lower()
            c = str(query.get("category") or "")
            rows = [p for p in cat.values() if (not q or q in (p["name"] + p["description"] + p["category"]).lower()) and (not c or p["category"] == c)]
            return _json({"products": rows, "categories": sorted({p["category"] for p in cat.values()}), "totalSize": len(rows)})
        if res == "subscriptions":
            if method == "POST" and not rid:
                pid = data.get("productId")
                p = cat.get(pid)
                if not p:
                    return _err(404, "NOT_FOUND", f"Product {pid} not found in the Marketplace catalog.")
                if data.get("acceptEula") is not True:
                    return _err(400, "FAILED_PRECONDITION", "You must accept the end-user license agreement (acceptEula: true) to subscribe.")
                if any(s["productId"] == pid and s["state"] == "ACTIVE" for s in mine.values()):
                    return _err(409, "ALREADY_EXISTS", f"This project is already subscribed to {p['name']}.")
                sid = "sub-" + uuid.uuid4().hex[:12]
                subs[sid] = {"name": f"projects/{project}/marketplaceSubscriptions/{sid}", "id": sid, "project": project, "productId": pid, "productName": p["name"],
                             "state": "ACTIVE", "createTime": _now(), "space": _space(project, p)}
                return _json(subs[sid])
            if method == "GET" and not rid:
                st = query.get("state")
                return _json({"subscriptions": sorted([s for s in mine.values() if not st or s["state"] == st], key=lambda s: s["createTime"], reverse=True)})
            if method == "DELETE" and rid:
                s = mine.get(rid)
                if not s or s["state"] != "ACTIVE":
                    return _err(404, "NOT_FOUND", f"Subscription {rid} not found or not active.")
                s["state"], s["endTime"] = "CANCELLED", _now()
                return _json(s)
        return _err(400, "INVALID_ARGUMENT", "Unsupported marketplace request.")
    inp = (inputs(project) if inputs else {}) or {}
    if family == "hub" and res == "overview":
        res_counts = inp.get("resources") or {}
        total = sum(res_counts.values())
        return _json({"project": project, "generateTime": _now(), "resources": [{"product": k, "count": v} for k, v in sorted(res_counts.items(), key=lambda kv: -kv[1])],
                      "totalResources": total, "openIncidents": inp.get("incidents") or [], "uptimeChecks": inp.get("uptime") or [],
                      "recentActivity": (inp.get("audit") or [])[:10], "eventarcTriggers": inp.get("eventarc", 0),
                      "marketplaceSubscriptions": len([s for s in _subs(store).values() if s["project"] == project and s["state"] == "ACTIVE"])})
    if family == "privacy" and res == "overview":
        audit = inp.get("audit") or []
        principals = sorted({e["principal"] for e in audit})
        return _json({"project": project, "generateTime": _now(),
                      "dataResidency": inp.get("locations") or {"constraint": "constraints/gcp.resourceLocations", "state": "NOT_SET", "allowedValues": []},
                      "auditLogs": inp.get("audit_config") or {"dataAccessEnabledServices": []},
                      "customerManagedKeys": inp.get("kms_keys", 0),
                      "access": {"adminActivityEntries": len(audit), "distinctPrincipals": principals,
                                 "accessTransparency": {"state": "ENABLED", "note": "Vyomi has no cloud-provider staff; the log lists privileged control-plane access derived from Admin Activity audit logs."},
                                 "accessApproval": {"state": "NOT_APPLICABLE", "note": "Access Approval gates Google staff access, which does not exist in a simulator."}}})
    if family == "privacy" and res == "access-log":
        audit = inp.get("audit") or []
        who = query.get("principal")
        rows = [e for e in audit if not who or e["principal"] == who]
        return _json({"entries": rows[: int(query.get("pageSize") or 100)], "totalSize": len(rows)})
    return _err(404, "NOT_FOUND", "Unknown path: " + path)
