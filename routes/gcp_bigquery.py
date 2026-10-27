"""GCP BigQuery — console routes + native v2 wire for the offline appliance.

The engine is core/gcp_bigquery_core.py (shared with Nano). Its state lives in the
active space's `service_states["gcp_bigquery"]` slot, so datasets, tables and jobs
survive restarts like every other space-scoped resource. Served here:
  * the native REST wire `/bigquery/v2/projects/{p}/...` that google-cloud-bigquery
    (Java/Go/Python) and `bq` speak;
  * the console routes `/api/gcp/bigquery/datasets...` and the detail tabs'
    `/api/gcp/sub/bigquery/{op}/{name}`.
"""
from __future__ import annotations

import json

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from core import app_context as ctx
from core import gcp_bigquery_core as bq

PLATFORM = ctx.PLATFORM


def _slot() -> dict | None:
    spaces_state = PLATFORM.kernel.state.setdefault("spaces", {"spaces": {}, "active_space_id": "", "settings": {}})
    active_id = spaces_state.get("active_space_id", "")
    if not active_id:
        return None
    space = spaces_state.setdefault("spaces", {}).setdefault(active_id, {})
    # The cloudsim inventory may have created an empty `gcp_bigquery` dict before the first write.
    slot = space.setdefault("service_states", {}).setdefault("gcp_bigquery", {})
    for k in ("datasets", "jobs", "iam"):
        slot.setdefault(k, {})
    return slot


class SpaceBqStore(bq.BigQueryStore):
    """BigQueryStore whose dicts are the active space's persisted slot."""

    def __init__(self) -> None:           # no super().__init__: the dicts are properties
        self._fallback = {"datasets": {}, "jobs": {}, "iam": {}}

    def _s(self) -> dict:
        s = _slot()
        return self._fallback if s is None else s

    @property
    def datasets(self) -> dict:
        return self._s()["datasets"]

    @datasets.setter
    def datasets(self, v: dict) -> None:
        self._s()["datasets"] = v

    @property
    def jobs(self) -> dict:
        return self._s()["jobs"]

    @property
    def iam(self) -> dict:
        return self._s()["iam"]

    def persist(self) -> None:
        if _slot() is not None:
            ctx.persist_state()


_STORE = SpaceBqStore()


def get_store() -> SpaceBqStore:
    return _STORE


def _project() -> str:
    space = PLATFORM.get_active_space() or {}
    return str(space.get("active_account") or "cloudlearn")


def _record(op: str, name: str = "") -> None:
    """Mutations feed the cloudsim inventory so the space's resource count and the
    cost-savings metrics follow datasets as they are created / changed / deleted."""
    ctx.record_usage("bigquery." + op, {"name": name, "resource_id": name})


def register(app: FastAPI) -> None:
    async def _wire(request: Request):
        body = await request.body()
        r = bq.dispatch(_STORE, request.method, request.url.path, dict(request.query_params),
                        {k.lower(): v for k, v in request.headers.items()}, body)
        if request.method != "GET" and r.status < 300:
            segs = [s for s in request.url.path.split("/") if s]
            kind = segs[segs.index("projects") + 2] if "projects" in segs and len(segs) > segs.index("projects") + 2 else "op"
            _record(f"{request.method.lower()}_{kind}", "/".join(segs[segs.index("projects") + 1:]) if "projects" in segs else "")
        return Response(content=r.body, status_code=r.status, media_type=r.media_type)

    methods = ["GET", "POST", "PATCH", "PUT", "DELETE"]
    app.add_route("/bigquery/v2/projects", _wire, methods=["GET"])
    app.add_route("/bigquery/v2/projects/{rest:path}", _wire, methods=methods)
    app.add_route("/upload/bigquery/v2/projects/{rest:path}", _wire, methods=["POST", "PUT"])

    async def _json(request: Request) -> dict:
        try:
            b = await request.json()
        except Exception:
            b = {}
        return b if isinstance(b, dict) else {}

    @app.get("/api/gcp/bigquery/datasets")
    def api_bq_list():
        return {"ok": True, "items": bq.console_list(_STORE)}

    @app.post("/api/gcp/bigquery/datasets")
    async def api_bq_create(request: Request):
        out = bq.console_create(_STORE, _project(), await _json(request))
        if out.get("ok"):
            _record("create_dataset", out["name"])
        return JSONResponse(out, status_code=200 if out.get("ok") else (409 if out.get("code") == "AlreadyExists" else 400))

    @app.get("/api/gcp/bigquery/datasets/{name}")
    def api_bq_get(name: str):
        _, ds = bq.console_find(_STORE, name)
        if ds is None:
            return JSONResponse({"ok": False, "code": "NotFound", "name": name}, status_code=404)
        return {"ok": True, **bq.console_row(ds)}

    @app.put("/api/gcp/bigquery/datasets/{name}")
    @app.patch("/api/gcp/bigquery/datasets/{name}")
    async def api_bq_update(name: str, request: Request):
        key, ds = bq.console_find(_STORE, name)
        if ds is None:
            return JSONResponse({"ok": False, "code": "NotFound", "name": name}, status_code=404)
        body = await _json(request)
        patch = {k: body[k] for k in ("description", "labels") if k in body}
        r = bq.dispatch(_STORE, "PATCH", f"/bigquery/v2/projects/{ds['project']}/datasets/{ds['id']}", {}, {},
                        json.dumps(patch).encode())
        return JSONResponse({"ok": r.status < 300, **bq.console_row(_STORE.datasets[key])},
                            status_code=200 if r.status < 300 else 400)

    @app.delete("/api/gcp/bigquery/datasets/{name}")
    def api_bq_delete(name: str):
        out = bq.console_delete(_STORE, name)
        if out.get("ok"):
            _record("delete_dataset", name)
        return JSONResponse(out, status_code=200 if out.get("ok") else 404)

    @app.get("/api/gcp/sub/bigquery/{op}/{name}")
    @app.post("/api/gcp/sub/bigquery/{op}/{name}")
    async def api_bq_sub(op: str, name: str, request: Request):
        if op in ("listTables", "listJobs", "listRoutines"):
            return {"ok": True, "items": bq.console_children(_STORE, name, op[4:].lower())}
        if op in ("createSampleTable", "runSampleQuery"):
            out = bq.console_sample(_STORE, name, "createTable" if op == "createSampleTable" else "runQuery")
            return JSONResponse(out, status_code=200 if out.get("ok") else 404)
        return JSONResponse({"ok": False, "code": "UnknownOperation", "name": op}, status_code=404)
