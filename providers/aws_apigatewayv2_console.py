"""Console REST for API Gateway V2 (HTTP/WebSocket APIs) — the offline appliance's
`/api/apigatewayv2/...` surface the AWS console catalog drives. Thin adapter over
core/apigatewayv2_core.py on the SAME shared store the native `/v2/...` wire uses, so
an API created in the console is visible to the SDK/CLI and vice-versa."""
from __future__ import annotations

import json

from fastapi import HTTPException, Request

from core import apigatewayv2_core as core


api_view = core.console_view


def _call(method, path, body=None, query=None):
    r = core.dispatch(core.shared_store(), method, path, query or {}, {},
                      json.dumps(body).encode() if body is not None else b"")
    out = json.loads(r.body) if r.body else {}
    if r.status >= 400:
        raise HTTPException(r.status, detail=f"{r.headers.get('x-amzn-ErrorType', 'Error')}: {out.get('message', '')}")
    return out


def register(app, on_change=None):
    """`on_change(action, api_dict_or_id)` lets the host sync CloudSim events/usage."""
    def changed(action, payload):
        if on_change:
            try:
                on_change(action, payload)
            except Exception:
                pass

    @app.get("/api/apigatewayv2/apis")
    def list_apis():
        apis = sorted((api_view(a) for a in core.shared_store().apis.values()), key=lambda a: (a["created"], a["name"]))
        return {"apis": apis, "count": len(apis)}

    @app.post("/api/apigatewayv2/apis")
    async def create_api(request: Request):
        b = await request.json()
        name = str(b.get("name") or "").strip()
        if not name:
            raise HTTPException(400, detail="BadRequestException: name is required")
        body = {"name": name, "protocolType": str(b.get("protocol_type") or b.get("protocolType") or "HTTP").upper()}
        if b.get("description"):
            body["description"] = b["description"]
        if body["protocolType"] == "WEBSOCKET":
            body["routeSelectionExpression"] = b.get("route_selection_expression") or "$request.body.action"
        elif b.get("target"):
            body["target"] = b["target"]
        out = _call("POST", "/v2/apis", body)
        api = core.shared_store().apis[out["apiId"]]
        changed("create", api)
        return api_view(api)

    @app.get("/api/apigatewayv2/apis/{api_id}")
    def get_api(api_id: str):
        api = core.shared_store().apis.get(api_id)
        if not api:
            raise HTTPException(404, detail="NotFoundException: Invalid API identifier specified " + api_id)
        return api_view(api)

    @app.patch("/api/apigatewayv2/apis/{api_id}")
    async def patch_api(api_id: str, request: Request):
        b = await request.json()
        api = core.shared_store().apis.get(api_id)
        if not api:
            raise HTTPException(404, detail="NotFoundException: Invalid API identifier specified " + api_id)
        if isinstance(b.get("tags"), dict):
            api["tags"] = {str(k): str(v) for k, v in b["tags"].items()}
        if b.get("description") is not None:
            api["description"] = b["description"]
        if b.get("name"):
            api["name"] = b["name"]
        return api_view(api)

    @app.delete("/api/apigatewayv2/apis/{api_id}")
    def delete_api(api_id: str):
        _call("DELETE", f"/v2/apis/{api_id}")
        changed("delete", api_id)
        return {"message": "API deleted", "api_id": api_id}

    def _sub(kind):
        @app.get(f"/api/apigatewayv2/apis/{{api_id}}/{kind}", name=f"apigwv2_{kind}")
        def lst(api_id: str):
            return _call("GET", f"/v2/apis/{api_id}/{kind}")
        return lst

    for kind in ("routes", "integrations", "stages", "deployments", "authorizers", "models"):
        _sub(kind)

    @app.get("/api/apigatewayv2/domains")
    def list_domains():
        return _call("GET", "/v2/domainnames")

    @app.get("/api/apigatewayv2/vpc-links")
    def list_vpclinks():
        return _call("GET", "/v2/vpclinks")
