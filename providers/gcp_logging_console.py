"""Cloud Logging on the offline appliance: the native `google-cloud-logging` /
`gcloud logging` REST wire (`/v2/entries:write|list`, `/v2/projects/{p}/logs|sinks|metrics|
exclusions|locations/{l}/buckets...`) and the console REST (`/api/gcp/logging/...`) the GCP
console catalog drives. Both are thin adapters over core/gcp_logging_core.py on the SAME
shared store, so a sink created in the console is visible to the SDK/CLI and vice-versa.

The console lists log sinks (the routing rules); the Logs Explorer data (entries.list) is
served by the same wire."""
from __future__ import annotations

import json

from fastapi import HTTPException, Request, Response

from core import gcp_logging_core as core

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
        parts = path.strip("/").split("/")[1:]   # drop the v2 prefix: projects/{p}/sinks[/{id}]
        if r.status == 200 and len(parts) >= 3 and parts[0] == "projects" and parts[2] == "sinks":
            if request.method == "POST" and len(parts) == 3:
                rec = store().sinks.get(f"projects/{parts[1]}/sinks/{json.loads(body).get('name', '')}")
                if rec:
                    changed("create", core.sink_console_view(parts[1], rec))
            elif request.method == "DELETE" and len(parts) == 4:
                changed("delete", parts[3])
        return Response(content=r.body, status_code=r.status, media_type=r.media_type)

    methods = ["GET", "POST", "PUT", "PATCH", "DELETE"]
    for pre in ("/v2", "/v2beta1"):
        for pat in ("/entries:write", "/entries:list", "/monitoredResourceDescriptors", "/projects/{project}/locations",
                    "/projects/{project}/logs", "/projects/{project}/logs/{log:path}",
                    "/projects/{project}/sinks", "/projects/{project}/sinks/{sink}",
                    "/projects/{project}/metrics", "/projects/{project}/metrics/{metric}",
                    "/projects/{project}/exclusions", "/projects/{project}/exclusions/{excl}",
                    "/projects/{project}/locations/{loc}/buckets", "/projects/{project}/locations/{loc}/buckets/{bucket}",
                    "/projects/{project}/locations/{loc}/buckets/{bucket}/views"):
            app.add_api_route(pre + pat, native, methods=methods, include_in_schema=False)

    # ── console REST ──────────────────────────────────────────────────────
    # The provider-alias middleware rewrites /api/gcp/<x> → /api/<x>, so the console's
    # /api/gcp/logging/sinks lands on these.
    def find(name):
        for n in store().sinks:
            if n.rsplit("/", 1)[-1] == name:
                return n.split("/")[1], name
        raise HTTPException(404, detail=f"Sink {name} not found.")

    @app.get("/api/logging/sinks")
    async def list_sinks():
        items = core.list_all(store())
        return {"items": items, "count": len(items)}

    @app.post("/api/logging/sinks")
    async def create_sink(request: Request):
        form = await request.json()
        form = dict(form, project=DEFAULT_PROJECT)
        sink = core.sink_from_form(form)
        r = call("POST", f"/v2/projects/{DEFAULT_PROJECT}/sinks", {"uniqueWriterIdentity": "true"}, json.dumps(sink).encode())
        if r.status >= 300:
            raise _http_error(r)
        v = core.sink_console_view(DEFAULT_PROJECT, store().sinks[f"projects/{DEFAULT_PROJECT}/sinks/{sink['name']}"])
        changed("create", v)
        return v

    @app.get("/api/logging/sinks/{name}")
    async def get_sink(name: str):
        p, s = find(name)
        return core.sink_console_view(p, store().sinks[f"projects/{p}/sinks/{s}"])

    @app.delete("/api/logging/sinks/{name}")
    async def delete_sink(name: str):
        p, s = find(name)
        r = call("DELETE", f"/v2/projects/{p}/sinks/{s}")
        if r.status >= 300:
            raise _http_error(r)
        changed("delete", s)
        return {"message": "Sink deleted", "name": s}

    @app.post("/api/sub/logging/{action}/{name}")
    async def sink_action(action: str, name: str):
        if action not in ("enable", "disable"):
            raise HTTPException(404, detail=f"Unknown action {action}")
        p, s = find(name)
        r = call("PATCH", f"/v2/projects/{p}/sinks/{s}", {"updateMask": "disabled"},
                 json.dumps({"disabled": action == "disable"}).encode())
        if r.status >= 300:
            raise _http_error(r)
        return core.sink_console_view(p, store().sinks[f"projects/{p}/sinks/{s}"])
