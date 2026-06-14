"""GCP rail extras and API Gateway — stub-driven CRUD for GCP services without
dedicated backends, plus minimal API Gateway handlers.

Extracted from server.py — contains the /api/gcp/extras/*,
/api/gcp/extras-config/*, and /api/gcp/apigateway/* route handlers plus
supporting helpers.
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import FastAPI, HTTPException, Request

from core import app_context as ctx

# Aliases
PLATFORM = ctx.PLATFORM
_now = ctx.now
_persist_state = ctx.persist_state


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _gcp_extras_state(stub_key: str) -> dict:
    spaces_state = PLATFORM.kernel.state.setdefault("spaces", {"spaces": {}, "active_space_id": "", "settings": {}})
    active_id = spaces_state.get("active_space_id", "")
    if not active_id:
        return {"items": {}, "seeded": False}
    space = spaces_state.setdefault("spaces", {}).setdefault(active_id, {})
    services = space.setdefault("service_states", {})
    extras = services.setdefault("gcp_extras", {})
    slot = extras.setdefault(stub_key, {"items": {}, "seeded": False})
    if not isinstance(slot, dict):
        slot = {"items": {}, "seeded": False}; extras[stub_key] = slot
    slot.setdefault("items", {})
    return slot


def _gcp_extras_seed_if_needed(stub_key: str) -> None:
    from core.gcp_rail_extras import EXTRAS
    schema = EXTRAS.get(stub_key)
    if not schema:
        return
    slot = _gcp_extras_state(stub_key)
    if slot.get("seeded"):
        return
    for s in schema.get("seed") or []:
        name = s.get("name") or s.get("id") or s.get("key_id") or s.get("trigger_id")
        if not name:
            import secrets as _sec
            name = "item-" + _sec.token_hex(3)
        slot["items"][name] = dict(s)
    slot["seeded"] = True


def _gcp_apigateway_state(project: str, kind: str) -> dict:
    """kind in {apis, configs, gateways, operations}. Per-space state."""
    spaces_state = PLATFORM.kernel.state.setdefault(
        "spaces", {"spaces": {}, "active_space_id": "", "settings": {}}
    )
    active_id = spaces_state.get("active_space_id", "")
    space = spaces_state.setdefault("spaces", {}).setdefault(active_id, {})
    svc_states = space.setdefault("service_states", {})
    ag = svc_states.setdefault("apigateway", {})
    proj = ag.setdefault(project, {})
    return proj.setdefault(kind, {})


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------

def register(app: FastAPI) -> None:
    """Mount all /api/gcp/extras/*, /api/gcp/extras-config/*,
    and /api/gcp/apigateway/* routes."""

    # ── GCP extras CRUD ────────────────────────────────────────────────────

    @app.get("/api/gcp/extras/{stub_path:path}", include_in_schema=False)
    def api_gcp_extras_get(stub_path: str):
        from core.gcp_rail_extras import EXTRAS
        schema = EXTRAS.get(stub_path)
        # If stub_path doesn't match a known stub, try peeling off a trailing
        # /{name} segment — the catalog's resource_path is `.../<stub>/{name}`
        # and a console GET to that URL should return the single item.
        if not schema and "/" in stub_path:
            parent, _, name = stub_path.rpartition("/")
            schema_parent = EXTRAS.get(parent)
            if schema_parent and schema_parent.get("category") != "config":
                _gcp_extras_seed_if_needed(parent)
                slot = _gcp_extras_state(parent)
                item = slot["items"].get(name)
                if item is not None:
                    return item
                raise HTTPException(status_code=404, detail=f"Not found: {parent}/{name}")
        if not schema:
            raise HTTPException(status_code=404, detail=f"Unknown GCP stub: {stub_path}")
        _gcp_extras_seed_if_needed(stub_path)
        slot = _gcp_extras_state(stub_path)
        return {"items": list(slot["items"].values()), "derived": False,
                "schema": {"category": schema.get("category"), "columns": schema.get("columns")}}

    @app.post("/api/gcp/extras/{stub_path:path}", include_in_schema=False)
    def api_gcp_extras_create(stub_path: str, payload: dict[str, Any] | None = None):
        from core.gcp_rail_extras import EXTRAS
        import secrets as _sec
        schema = EXTRAS.get(stub_path)
        if not schema:
            raise HTTPException(status_code=404, detail=f"Unknown GCP stub: {stub_path}")
        payload = dict(payload or {})
        name = payload.get("name") or payload.get("id")
        if not name:
            prefix = stub_path.split("/")[-1].split("-")[0][:3]
            name = f"{prefix}-{_sec.token_hex(4)}"
        payload["name"] = name
        payload.setdefault("created", _now())
        for col_path, _ in (schema.get("columns") or []):
            if "." not in col_path and col_path not in payload:
                payload[col_path] = payload.get(col_path, "\u2014")
        slot = _gcp_extras_state(stub_path)
        slot["items"][name] = payload
        slot["seeded"] = True
        _persist_state()
        return payload

    @app.delete("/api/gcp/extras/{stub_path:path}", include_in_schema=False)
    def api_gcp_extras_delete_one(stub_path: str):
        from core.gcp_rail_extras import EXTRAS
        parts = stub_path.rsplit("/", 1)
        if len(parts) != 2:
            raise HTTPException(status_code=400, detail="Expected /api/gcp/extras/<service>/<stub>/<name>")
        key, name = parts
        if key not in EXTRAS:
            raise HTTPException(status_code=404, detail=f"Unknown GCP stub: {key}")
        slot = _gcp_extras_state(key)
        slot["items"].pop(name, None)
        _persist_state()
        return {"deleted": True, "name": name}

    @app.get("/api/gcp/extras-config/{stub_path:path}", include_in_schema=False)
    def api_gcp_extras_config_get(stub_path: str):
        from core.gcp_rail_extras import EXTRAS
        schema = EXTRAS.get(stub_path)
        if not schema or schema.get("category") != "config":
            raise HTTPException(status_code=404, detail=f"Not a GCP config stub: {stub_path}")
        slot = _gcp_extras_state(stub_path)
        if not slot.get("seeded"):
            slot["items"] = dict(schema.get("defaults") or {})
            slot["seeded"] = True
        return {"values": slot["items"], "schema": {"fields": schema.get("fields"), "defaults": schema.get("defaults")}}

    @app.put("/api/gcp/extras-config/{stub_path:path}", include_in_schema=False)
    def api_gcp_extras_config_put(stub_path: str, payload: dict[str, Any] | None = None):
        from core.gcp_rail_extras import EXTRAS
        schema = EXTRAS.get(stub_path)
        if not schema or schema.get("category") != "config":
            raise HTTPException(status_code=404, detail=f"Not a GCP config stub: {stub_path}")
        slot = _gcp_extras_state(stub_path)
        slot["items"] = dict(payload or {})
        slot["seeded"] = True
        _persist_state()
        return {"values": slot["items"]}

    # ── GCP API Gateway ────────────────────────────────────────────────────

    @app.get("/api/gcp/apigateway/v1/projects/{project}/locations/global/apis", include_in_schema=False)
    def gcp_apigateway_list_apis(project: str):
        apis = _gcp_apigateway_state(project, "apis")
        return {
            "apis": [
                {
                    "name": f"projects/{project}/locations/global/apis/{name}",
                    "displayName": rec.get("displayName", name),
                    "createTime": rec.get("createTime", ""),
                    "state": rec.get("state", "ACTIVE"),
                    "managedService": rec.get("managedService", f"{name}.apigateway.{project}.cloud.goog"),
                    "labels": rec.get("labels", {}),
                }
                for name, rec in apis.items()
            ],
        }

    @app.post("/api/gcp/apigateway/v1/projects/{project}/locations/global/apis", include_in_schema=False)
    async def gcp_apigateway_create_api(project: str, request: Request):
        api_id = request.query_params.get("apiId", "")
        body = await request.json() if (await request.body()) else {}
        name = api_id or body.get("name") or f"api-{uuid.uuid4().hex[:6]}"
        rec = {
            "displayName": body.get("displayName", name),
            "createTime": _now(),
            "state": "ACTIVE",
            "managedService": f"{name}.apigateway.{project}.cloud.goog",
            "labels": body.get("labels", {}),
        }
        _gcp_apigateway_state(project, "apis")[name] = rec
        _persist_state()
        return {
            "name": f"projects/{project}/locations/global/operations/op-{uuid.uuid4().hex[:8]}",
            "metadata": {"@type": "type.googleapis.com/google.cloud.apigateway.v1.OperationMetadata",
                         "target": f"projects/{project}/locations/global/apis/{name}"},
            "done": True,
            "response": {"@type": "type.googleapis.com/google.cloud.apigateway.v1.Api",
                         "name": f"projects/{project}/locations/global/apis/{name}", **rec},
        }

    @app.get("/api/gcp/apigateway/v1/projects/{project}/locations/global/apis/{name}", include_in_schema=False)
    def gcp_apigateway_get_api(project: str, name: str):
        apis = _gcp_apigateway_state(project, "apis")
        if name not in apis:
            raise HTTPException(404, detail=f"API '{name}' not found")
        rec = apis[name]
        return {
            "name": f"projects/{project}/locations/global/apis/{name}",
            "displayName": rec.get("displayName", name),
            "createTime": rec.get("createTime", ""),
            "state": rec.get("state", "ACTIVE"),
            "managedService": rec.get("managedService", f"{name}.apigateway.{project}.cloud.goog"),
            "labels": rec.get("labels", {}),
        }

    @app.delete("/api/gcp/apigateway/v1/projects/{project}/locations/global/apis/{name}", include_in_schema=False)
    def gcp_apigateway_delete_api(project: str, name: str):
        apis = _gcp_apigateway_state(project, "apis")
        apis.pop(name, None)
        _persist_state()
        return {"name": f"projects/{project}/locations/global/operations/op-{uuid.uuid4().hex[:8]}",
                "done": True}

    @app.get("/api/gcp/apigateway/v1/projects/{project}/locations/global/apis/{api}/configs", include_in_schema=False)
    def gcp_apigateway_list_configs(project: str, api: str):
        configs = _gcp_apigateway_state(project, "configs").get(api, {})
        return {"apiConfigs": [
            {"name": f"projects/{project}/locations/global/apis/{api}/configs/{c}",
             "displayName": rec.get("displayName", c),
             "createTime": rec.get("createTime", ""), "state": rec.get("state", "ACTIVE")}
            for c, rec in configs.items()
        ]}

    @app.get("/api/gcp/apigateway/v1/projects/{project}/locations/global/gateways", include_in_schema=False)
    def gcp_apigateway_list_gateways(project: str):
        gws = _gcp_apigateway_state(project, "gateways")
        return {"gateways": [
            {"name": f"projects/{project}/locations/global/gateways/{name}",
             "displayName": rec.get("displayName", name),
             "apiConfig": rec.get("apiConfig", ""),
             "createTime": rec.get("createTime", ""), "state": rec.get("state", "ACTIVE"),
             "defaultHostname": f"{name}-{uuid.uuid4().hex[:8]}.uc.gateway.dev"}
            for name, rec in gws.items()
        ]}
