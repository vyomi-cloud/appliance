"""Tier-feature implementation: cross_tenant_rbac (Enterprise tier).

Lets an Enterprise tenant grant scoped roles to OTHER tenants in the same
deployment. The X-CloudLearn-Acting-As-Tenant header then lets a user
operate on the granted tenant's resources without switching their license.

State:
  STATE["xt_rbac_grants"] = [
    {
      id, grantor_tenant, grantee_tenant,
      role: "viewer" | "operator" | "admin",
      services: ["*"] | ["s3", "ec2", ...],
      created_at, expires_at | null
    },
    ...
  ]

Role capabilities:
  viewer    — GET requests only
  operator  — GET + POST/PUT (no DELETE)
  admin     — everything

Resolution flow (called by the middleware):
  1. Request arrives at /api/... with X-CloudLearn-Acting-As-Tenant: T2
  2. Active user belongs to tenant T1
  3. cross_tenant_rbac.check(T1, T2, method, service) → allow|deny
  4. If allow → swap active tenant to T2 for the duration of this request
  5. Audit log the cross-tenant access
"""
from __future__ import annotations

import time
import uuid
from typing import Any


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())


_ROLE_HIERARCHY = {
    "viewer":    {"GET", "HEAD", "OPTIONS"},
    "operator":  {"GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH"},
    "admin":     {"GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE"},
}


def _grants(state: dict) -> list[dict]:
    return state.setdefault("xt_rbac_grants", [])


def list_grants(state: dict, tenant_id: str | None = None) -> list[dict]:
    """List all grants. If tenant_id is given, returns only grants where this
    tenant is grantor OR grantee."""
    grants = _grants(state)
    if tenant_id:
        return [g for g in grants if g.get("grantor_tenant") == tenant_id
                                  or g.get("grantee_tenant") == tenant_id]
    return list(grants)


def create_grant(state: dict, grantor_tenant: str, spec: dict) -> dict:
    """Grant `grantee_tenant` a `role` over `grantor_tenant`'s resources.
    Spec: { grantee_tenant, role, services?, expires_at? }"""
    grantee = str(spec.get("grantee_tenant") or "").strip()
    role = str(spec.get("role") or "viewer").strip().lower()
    if not grantee:
        raise ValueError("grantee_tenant required")
    if grantee == grantor_tenant:
        raise ValueError("cannot grant to self")
    if role not in _ROLE_HIERARCHY:
        raise ValueError(f"role must be one of {sorted(_ROLE_HIERARCHY)}")
    services = spec.get("services") or ["*"]
    if not isinstance(services, list):
        services = [str(services)]
    grant = {
        "id": "xtg-" + uuid.uuid4().hex[:10],
        "grantor_tenant": grantor_tenant,
        "grantee_tenant": grantee,
        "role": role,
        "services": services,
        "created_at": _now_iso(),
        "expires_at": str(spec.get("expires_at") or "") or None,
        "use_count": 0,
        "last_used_at": None,
    }
    _grants(state).append(grant)
    return grant


def delete_grant(state: dict, grant_id: str, requestor_tenant: str) -> bool:
    """Only the grantor can revoke their own grant."""
    grants = _grants(state)
    before = len(grants)
    state["xt_rbac_grants"] = [
        g for g in grants
        if not (g.get("id") == grant_id and g.get("grantor_tenant") == requestor_tenant)
    ]
    return len(state["xt_rbac_grants"]) < before


def check(state: dict, grantee_tenant: str, target_tenant: str,
          method: str, service: str = "") -> dict:
    """Can `grantee_tenant` access `target_tenant`'s resources at `method`
    on `service`? Returns {ok, grant_id?, role?, reason?}."""
    if not grantee_tenant or not target_tenant:
        return {"ok": False, "reason": "missing tenant"}
    if grantee_tenant == target_tenant:
        return {"ok": True, "reason": "same tenant"}
    method = method.upper()
    now_iso = _now_iso()
    for g in _grants(state):
        if g.get("grantor_tenant") != target_tenant:
            continue
        if g.get("grantee_tenant") != grantee_tenant:
            continue
        expires = g.get("expires_at")
        if expires and expires < now_iso:
            continue
        role = g.get("role", "viewer")
        allowed_methods = _ROLE_HIERARCHY.get(role, set())
        if method not in allowed_methods:
            continue
        services = g.get("services") or ["*"]
        if "*" not in services and service and service not in services:
            continue
        # Match! Record the use.
        g["use_count"] = int(g.get("use_count") or 0) + 1
        g["last_used_at"] = now_iso
        return {"ok": True, "grant_id": g["id"], "role": role}
    return {
        "ok": False,
        "reason": f"no grant from {target_tenant} to {grantee_tenant} for {method} {service}",
    }
