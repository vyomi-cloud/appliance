"""Cloud Run on the offline appliance: the native `google-cloud-run` / `gcloud run` REST wire
(`/v2/projects/{p}/locations/{l}/services|jobs|operations...`) and the console REST
(`/api/gcp/run/...`) the GCP console catalog drives. Both are thin adapters over
core/gcp_run_core.py on the SAME shared store, so a service created in the console is
visible to the SDK/CLI and vice-versa.

Control plane only: containers are not executed by this service (Pro's Docker compute backend
is the opt-in data plane)."""
from __future__ import annotations

import json

from fastapi import HTTPException, Request, Response

from core import gcp_run_core as core

DEFAULT_PROJECT = "demo"


def _http_error(r):
    try:
        msg = json.loads(r.body)["error"]["message"]
    except Exception:
        msg = "error"
    return HTTPException(r.status, detail=msg)


def register(app, on_change=None):
    """`on_change(action, console_view_or_name)` lets the host sync CloudSim events/usage."""
    store = core.shared_store

    def changed(action, payload):
        if on_change:
            try:
                on_change(action, payload)
            except Exception:
                pass

    def call(method, path, query=None, body=b"", headers=None):
        return core.dispatch(store(), method, path, query or {}, headers or {}, body)

    # ── native wire ───────────────────────────────────────────────────────
    async def native(request: Request):
        body = await request.body()
        path = request.url.path
        r = call(request.method, path, dict(request.query_params), body, dict(request.headers))
        if r.status == 200:
            parts = path.strip("/").split("/")          # v2/projects/p/locations/l/services/<id>[...]
            if len(parts) >= 6 and parts[5] == "services":
                if request.method == "POST" and len(parts) == 6:
                    f = core.service_name(parts[2], parts[4], request.query_params.get("serviceId", ""))
                    if f in store().services:
                        changed("create", core.view_by_name(store(), f))
                elif request.method == "DELETE" and len(parts) == 7:
                    changed("delete", parts[6].split(":")[0])
        return Response(content=r.body, status_code=r.status, media_type=r.media_type)

    async def native_kn(request: Request):
        body = await request.body()
        r = call(request.method, request.url.path, dict(request.query_params), body, dict(request.headers))
        if r.status == 200 and request.method in ("POST", "PUT", "DELETE") and "/services" in request.url.path:
            segs = request.url.path.split("/services", 1)[1].strip("/").split("/")
            try:
                if request.method == "POST" and not segs[0]:
                    ns = request.url.path.split("/namespaces/")[1].split("/")[0]
                    reg = core._kn_region(dict(request.headers))
                    changed("create", core.view_by_name(store(), core.service_name(ns, reg, json.loads(body)["metadata"]["name"])))
                elif request.method == "DELETE" and segs[0]:
                    changed("delete", segs[0])
            except Exception:
                pass
        return Response(content=r.body, status_code=r.status, media_type=r.media_type)

    methods = ["GET", "POST", "PUT", "PATCH", "DELETE"]
    # gcloud run: the regional Knative-style API + the v1 Admin IAM verbs on services
    for tail in ("/services", "/services/{name}", "/revisions", "/revisions/{name}"):
        app.add_api_route("/apis/serving.knative.dev/v1/namespaces/{ns}" + tail, native_kn, methods=methods, include_in_schema=False)
    app.add_api_route("/v1/projects/{project}/locations/{loc}/services/{service}", native_kn, methods=methods, include_in_schema=False)
    base = "/v2/projects/{project}/locations/{loc}"
    for tail in ("/services", "/services/{service}", "/services/{service}/revisions",
                 "/services/{service}/revisions/{revision}", "/jobs", "/jobs/{job}", "/jobs/{job}/executions",
                 "/jobs/{job}/executions/{execution}", "/jobs/{job}/executions/{execution}/tasks",
                 "/jobs/{job}/executions/{execution}/tasks/{task}", "/operations", "/operations/{op}"):
        app.add_api_route(base + tail, native, methods=methods, include_in_schema=False)

    # ── console REST ──────────────────────────────────────────────────────
    # The provider-alias middleware rewrites /api/gcp/<x> → /api/<x>, so the console's
    # /api/gcp/run/services lands on these.
    def find(name):
        for n in store().services:
            if n.rsplit("/", 1)[-1] == name or n == name:
                return n
        raise HTTPException(404, detail=f"Service {name} not found.")

    def loc(full):
        p = full.split("/")
        return p[1], p[3], p[5]

    @app.get("/api/run/services")
    async def list_services():
        items = core.list_all(store())
        return {"items": items, "count": len(items)}

    @app.post("/api/run/services")
    async def create_service(request: Request):
        form = await request.json()
        req = core.job_from_form(form, DEFAULT_PROJECT)
        r = call("POST", f"/v2/{req['parent']}/services", {"serviceId": req["serviceId"]}, json.dumps(req["service"]).encode())
        if r.status >= 300:
            raise _http_error(r)
        full = core.service_name(DEFAULT_PROJECT, req["location"], req["serviceId"])
        if req["allowUnauthenticated"]:
            call("POST", f"/v2/{full}:setIamPolicy", body=json.dumps(
                {"policy": {"bindings": [{"role": core.IAM_INVOKER, "members": ["allUsers"]}]}}).encode())
        v = core.view_by_name(store(), full)
        changed("create", v)
        return v

    @app.get("/api/run/services/{name}")
    async def get_service(name: str):
        return core.view_by_name(store(), find(name))

    @app.delete("/api/run/services/{name}")
    async def delete_service(name: str):
        p, l, s = loc(find(name))
        r = call("DELETE", f"/v2/projects/{p}/locations/{l}/services/{s}")
        if r.status >= 300:
            raise _http_error(r)
        changed("delete", s)
        return {"message": "Service deleted", "name": s}

    @app.post("/api/sub/run/{action}/{name}")
    async def service_action(action: str, name: str, request: Request):
        full = find(name)
        p, l, s = loc(full)
        try:
            b = await request.json()
        except Exception:
            b = {}
        cur = store().services[full]
        if action == "deploy":
            tpl = json.loads(json.dumps(cur["template"]))
            tpl.pop("revision", None)
            tpl["containers"][0]["image"] = b.get("image") or tpl["containers"][0]["image"]
            r = call("PATCH", f"/v2/{full}", {"updateMask": "template"}, json.dumps({"template": tpl}).encode())
        elif action == "invoker":
            members = ["allUsers"] if b.get("allow", True) else []
            pol = {"policy": {"bindings": [{"role": core.IAM_INVOKER, "members": members}] if members else []}}
            r = call("POST", f"/v2/{full}:setIamPolicy", body=json.dumps(pol).encode())
        else:
            raise HTTPException(404, detail=f"Unknown action {action}")
        if r.status >= 300:
            raise _http_error(r)
        return core.view_by_name(store(), full)
