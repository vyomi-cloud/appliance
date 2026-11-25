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
                 audit_log=None, engines=None, maps=None):
        self.store = settings_store or _modes.MemorySettingsStore()
        self.state_fn = state_fn or (lambda cloud: {})
        self.catalog_fn = catalog_fn or (lambda cloud, service: None)
        self.inventory_fn = inventory_fn or (lambda: None)
        self.log = audit_log if audit_log is not None else _audit.default_log
        self.engines, self.maps = engines, maps

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
            elif what == "evaluate" and method == "POST":
                return self._evaluate(cloud, body)
            elif what == "catalog" and method == "GET" and len(parts) >= 5:
                return self._catalog(cloud, parts[4])
        except ValueError as exc:
            return 400, {"error": str(exc)}
        return 405 if what in ("enforcement", "audit", "evaluate", "catalog") else 404, {"error": "method or route not supported"}

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
