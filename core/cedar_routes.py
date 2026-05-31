"""Cedar-backed IAM endpoints + evaluation probe.

Provider-native CRUD for IAM policies is already shipped per-provider in their
respective extras CRUD. This module adds:

  POST /api/iam/policies                 — replace the active space's policy set
  POST /api/iam/evaluate                  — probe: is X allowed to do Y on Z?
  POST /v1/iamPolicies/{p}:setIamPolicy   — GCP-style upsert (shim → Cedar)
  PUT  /Microsoft.Authorization/...       — Azure-style role assignment (shim)

The evaluate endpoint is what callers (and conformance) use to verify that a
specific principal/action/resource triple is allowed. Real enforcement is done
by ``server.py`` middleware (P1 follow-up — out of MVP scope).
"""
from __future__ import annotations

from fastapi import FastAPI, Request

from . import cedar_engine as ce


def _active_space_id() -> str:
    try:
        from server import PLATFORM
        spaces_state = PLATFORM.kernel.state.setdefault(
            "spaces", {"spaces": {}, "active_space_id": "", "settings": {}}
        )
        return spaces_state.get("active_space_id", "default")
    except Exception:
        return "default"


def register(app: FastAPI) -> None:
    @app.post("/api/iam/policies", include_in_schema=False)
    async def set_policies(request: Request):
        """Replace the active space's Cedar policy set.

        Body: ``{"policies": "<cedar policyset string>"}`` OR
              ``{"aws": [<iam-policy-doc>, ...]}`` (auto-compiles)
              ``{"gcp": [<binding>, ...]}``
              ``{"azure": [<assignment>, ...]}``
        """
        body = await request.json()
        space = _active_space_id()
        ce.clear_policies(space)
        if "policies" in body:
            ce.set_policies(space, body["policies"])
        if "aws" in body:
            for doc in body["aws"]:
                principal = doc.get("__principal__", 'User::"*"')
                ce.add_policy(space, ce.aws_iam_json_to_cedar(doc, principal_arn=principal))
        if "gcp" in body:
            for binding in body["gcp"]:
                ce.add_policy(space, ce.gcp_binding_to_cedar(binding))
        if "azure" in body:
            for assignment in body["azure"]:
                ce.add_policy(space, ce.azure_rbac_to_cedar(assignment))
        return {
            "space_id": space,
            "available": ce.available(),
            "policyset": ce.get_policies(space),
        }

    @app.get("/api/iam/policies", include_in_schema=False)
    async def get_policies():
        space = _active_space_id()
        return {
            "space_id": space,
            "available": ce.available(),
            "policyset": ce.get_policies(space),
        }

    @app.post("/api/iam/evaluate", include_in_schema=False)
    async def evaluate(request: Request):
        """Probe the policy set.

        Body: ``{"principal": "User::\\"alice\\"", "action": "Action::\\"s3:GetObject\\"",
                 "resource": "Resource::\\"arn:aws:s3:::bucket/key\\"",
                 "context": {}}``
        """
        body = await request.json()
        space = _active_space_id()
        allowed, reason = ce.evaluate(
            space,
            body.get("principal", 'User::"*"'),
            body.get("action", 'Action::"*"'),
            body.get("resource", 'Resource::"*"'),
            context=body.get("context") or {},
        )
        return {"allowed": allowed, "reason": reason, "space_id": space}
