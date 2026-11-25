"""Substrate-neutral implementation of the /api/iam/<cloud>/... routes (contract). Pure Python.

Mesh wraps `IamApi.handle` in FastAPI (routes/iam_enforcement.py); Nano calls the same method from its service worker / kernel.
Everything environment-specific is injected:
  settings_store : object with get() -> dict, put(doc) -> dict      (modes.MemorySettingsStore / HolderSettingsStore / Nano's own)
  state_fn       : (cloud) -> engine `state` dict                    (host adapters)
  catalog_fn     : (cloud, service) -> dict | None                   (reads core/iam_catalog/<cloud>/<service>.json or Nano's lazy copy)
  inventory_fn   : () -> dict | None                                 (parsed wasm/service-inventory.json; None -> `vyomi.simulated` unknown)
  audit_log      : audit.AuditLog   engines / maps : optional gate overrides
"""
from __future__ import annotations

from core.iam_engine import audit as _audit
from core.iam_engine import gate as _gate
from core.iam_engine import modes as _modes
from core.iam_engine.types import request as _request


class IamApi:
    def __init__(self, settings_store=None, state_fn=None, catalog_fn=None, inventory_fn=None,
                 audit_log=None, engines=None, maps=None, governance_fn=None, trail_fn=None, events_fn=None):
        self.store = settings_store or _modes.MemorySettingsStore()
        self.state_fn = state_fn or (lambda cloud: {})
        self.catalog_fn = catalog_fn or (lambda cloud, service: None)
        self.inventory_fn = inventory_fn or (lambda: None)
        self.log = audit_log if audit_log is not None else _audit.default_log
        self.engines, self.maps = engines, maps
        self.governance_fn = governance_fn            # (cloud, what, method, query, body) -> (status, json); default core/iam_governance.handle
        self.trail_fn = trail_fn        # () -> [CloudTrail events] (core/cloudtrail_events_core ring), AWS only; None = decisions only
        self.events_fn = events_fn      # () -> [common event records]; default: core/iam_events_core ring

    def handle(self, method, path, query=None, body=None):
        """-> (status, json-able). `path` like /api/iam/aws/enforcement."""
        parts = [p for p in str(path).split("/") if p]
        if len(parts) < 4 or parts[0] != "api" or parts[1] != "iam":
            return 404, {"error": "not found"}
        cloud, what, method, query = parts[2], parts[3], str(method).upper(), query or {}
        if cloud not in _modes.CLOUDS:
            return 404, {"error": f"unknown cloud '{cloud}'"}
        try:
            if what == "enforcement":
                if method == "GET":
                    return 200, self.store.get()
                if method == "PUT":
                    return 200, self.store.put(body)
            elif what == "audit" and method == "GET":
                return 200, {"records": self.log.list(query.get("limit", 100), cloud=cloud,
                                                      decision=query.get("decision"), principal=query.get("principal"))}
            elif what == "audit" and method == "DELETE":
                self.log.clear()
                return 200, {"cleared": True}
            elif what == "events" and method == "GET":
                return self._events(cloud, query, len(parts) > 4 and parts[4] == "export")
            elif what == "evaluate" and method == "POST":
                return self._evaluate(cloud, body)
            elif what == "catalog" and method == "GET" and len(parts) >= 5:
                return self._catalog(cloud, parts[4])
            elif what == "governance" and len(parts) >= 5:
                fn = self.governance_fn
                if fn is None:
                    from core import iam_governance as _gov
                    fn = _gov.handle
                return fn(cloud, "/".join(parts[4:]), method, query, body)
        except ValueError as exc:
            return 400, {"error": str(exc)}
        return 405 if what in ("enforcement", "audit", "evaluate", "catalog", "governance", "events") else 404, {"error": "method or route not supported"}

    _IAM_SERVICES = {"aws": ("iam", "sts", "access-analyzer", "accessanalyzer", "rolesanywhere", "organizations", "sso", "identitystore", "cognito-identity"),
                     "gcp": ("iam", "sts", "iamcredentials", "cloudresourcemanager", "cloudidentity", "orgpolicy"),
                     "azure": ("microsoft.authorization", "microsoft.managedidentity", "microsoft.aad")}

    def _events(self, cloud, query, export=False):
        """GET /api/iam/<cloud>/events[/export]: IAM management-event history in the cloud's native shape (CloudTrail event / Cloud Audit Logs
        LogEntry / Activity Log event under `native`) with a common envelope; gate denials are merged as outcome=denied. Filters: name,
        principal, resource, service, outcome, readOnly, q, start, end, scope=iam|all (default iam), source=all|events|decisions,
        includeAllowed=true, limit (<=1000, default 100), offset, format=json|csv (export)."""
        from core import iam_events_core as ev
        q = dict(query or {})
        src = str(q.get("source") or "all")
        rows = []
        if src in ("all", "events"):
            if cloud == "aws":
                try:
                    rows += [ev.normalize_cloudtrail(e) for e in (self.trail_fn() if self.trail_fn else [])]
                except Exception:
                    pass
            else:
                rows += [e for e in (self.events_fn() if self.events_fn else ev.snapshot()) if e.get("cloud") == cloud]
        if src in ("all", "decisions"):
            allowed = str(q.get("includeAllowed") or "").lower() in ("true", "1")
            for r in self.log.list(1000, cloud=cloud):
                if allowed or r.get("decision") in ("deny", "would_deny"):
                    rows.append(ev.from_decision(r))
        if str(q.get("scope") or "iam") != "all":
            keys = self._IAM_SERVICES.get(cloud, ())
            rows = [r for r in rows if str(r.get("service", "")).lower() in keys or str(r.get("name", "")).lower().split(":")[0] in keys
                    or any(str(r.get("name", "")).lower().startswith(k + "/") for k in keys)]
        try:
            limit = max(1, min(1000, int(q.get("limit", 100))))
            offset = max(0, int(q.get("offset", 0)))
        except (TypeError, ValueError):
            limit, offset = 100, 0
        page, total = ev.query(rows, q, limit if not export else 10000, 0 if export else offset)
        if export:
            if str(q.get("format") or "json").lower() == "csv":
                return 200, {"contentType": "text/csv", "filename": f"iam-events-{cloud}.csv", "body": ev.export_csv(page)}
            return 200, {"contentType": "application/json", "filename": f"iam-events-{cloud}.json", "events": page}
        for r in page:
            if "native" not in r:
                r["native"] = ev.to_gcp_audit(r) if cloud == "gcp" else ev.to_azure_activity(r) if cloud == "azure" else r.get("native")
        return 200, {"events": page, "total": total, "limit": limit, "offset": offset,
                     "truncated": total > offset + len(page)}

    def _evaluate(self, cloud, body):
        if not isinstance(body, dict) or not body.get("action"):
            return 400, {"error": "body must be a request: {principal, action, resource?, context?}"}
        try:
            engine = _gate._engine(cloud, self.engines)
        except Exception as exc:
            return 501, {"error": f"{cloud} engine not available: {exc}"}
        req = _request(cloud, body.get("principal") or {}, body["action"], body.get("resource") or "*", body.get("context"),
                       data=bool(body.get("data")))
        pr = body.get("principal") or {}
        if cloud in ("gcp", "azure") and pr.get("type") == "root":
            # Same rule as the gate (core/middleware.py): GCP/Azure have no root, the simulator's unidentified caller is the project /
            # subscription owner. Without this the effective-access view said "implicit deny" for the owner the live gate lets through.
            try:
                strict = (self.store.get() or {}).get("unknownPrincipal", "root") == "deny"
            except Exception:
                strict = False
            if not strict:
                return 200, {"allowed": True, "reason": "owner_root", "matched": []}
        try:
            return 200, engine.evaluate(req, self.state_fn(cloud))
        except Exception as exc:
            return 500, {"error": f"engine error: {exc}"}

    def _catalog(self, cloud, service):
        cat = self.catalog_fn(cloud, service)
        if cat is None:
            return 404, {"error": f"no catalog for {cloud}/{service}"}
        inv = self.inventory_fn()
        simulated = None
        if isinstance(inv, dict):
            ids = {str(s.get("id")).lower() for s in inv.get("services", []) if s.get("cloud") == cloud}
            simulated = service.lower() in ids
        return 200, dict(cat, vyomi={"simulated": simulated, "inventory": inv is not None})
