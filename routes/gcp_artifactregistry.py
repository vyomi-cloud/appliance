"""GCP Artifact Registry — console routes + native v1 wire for the offline appliance.

The engine is core/gcp_artifactregistry_core.py (shared with Nano). Its state lives in
the active space's `service_states["gcp_artifactregistry"]` slot, so repositories
survive restarts like every other space-scoped resource. Served here:
  * the native REST wire `/v1/projects/{p}/locations/{l}/repositories...` that
    google-cloud-artifact-registry (Python/Java/Go) and `gcloud artifacts` speak;
  * the console routes `/api/gcp/artifactregistry/repositories...` and the detail
    tabs' `/api/gcp/sub/artifactregistry/{op}/{name}`.
"""
from __future__ import annotations

import json
import os
import time
import urllib.request

from fastapi import FastAPI, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from core import app_context as ctx
from core import gcp_artifactregistry_core as ar

PLATFORM = ctx.PLATFORM


def _slot() -> dict | None:
    spaces_state = PLATFORM.kernel.state.setdefault("spaces", {"spaces": {}, "active_space_id": "", "settings": {}})
    active_id = spaces_state.get("active_space_id", "")
    if not active_id:
        return None
    space = spaces_state.setdefault("spaces", {}).setdefault(active_id, {})
    # The cost/inventory census may have created an empty slot first: fill in our keys.
    slot = space.setdefault("service_states", {}).setdefault("gcp_artifactregistry", {})
    for k in ("repositories", "operations", "iam"):
        slot.setdefault(k, {})
    return slot


class SpaceArStore(ar.ArtifactRegistryStore):
    """ArtifactRegistryStore whose dicts are the active space's persisted slot."""

    def __init__(self) -> None:           # no super().__init__: the dicts are properties
        self._fallback = {"repositories": {}, "operations": {}, "iam": {}}

    def _s(self) -> dict:
        s = _slot() or self._fallback
        for k in ("repositories", "operations", "iam"):
            s.setdefault(k, {})
        return s

    @property
    def repos(self) -> dict:
        return self._s()["repositories"]

    @property
    def operations(self) -> dict:
        return self._s()["operations"]

    @property
    def iam(self) -> dict:
        return self._s()["iam"]

    def persist(self) -> None:
        if _slot() is not None:
            ctx.persist_state()


_STORE = SpaceArStore()


def get_store() -> SpaceArStore:
    return _STORE


def _project() -> str:
    space = PLATFORM.get_active_space() or {}
    return str(space.get("active_account") or "cloudlearn")


_SYNC = {"at": 0.0}


def _sync_registry() -> None:
    """Best-effort, throttled: ingest `docker push`es from the shared registry container."""
    host = os.environ.get("CLOUDLEARN_REGISTRY_HOST", "").strip()
    if not host or time.time() - _SYNC["at"] < 3:
        return
    _SYNC["at"] = time.time()
    ar.configure_data_plane(host, int(os.environ.get("CLOUDLEARN_REGISTRY_PORT", "5000") or 5000))
    base = f"http://{host}:{ar.DATA_PLANE['port']}/v2"
    accept = {"Accept": "application/vnd.docker.distribution.manifest.v2+json,application/vnd.oci.image.manifest.v1+json"}

    def get(url, headers=None):
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}), timeout=2) as r:
            return r.headers, json.loads(r.read() or b"{}")

    try:
        project = _project()
        found = []
        for repo in get(base + "/_catalog?n=1000")[1].get("repositories") or []:
            proj, _, path = repo.partition("/")
            if proj != project or "/" not in path:
                continue
            for tag in get(f"{base}/{repo}/tags/list")[1].get("tags") or []:
                h, man = get(f"{base}/{repo}/manifests/{tag}", accept)
                size = sum(int(l.get("size", 0)) for l in man.get("layers", [])) + int((man.get("config") or {}).get("size", 0))
                found.append({"path": path, "tag": tag, "digest": h.get("Docker-Content-Digest", ""), "size": size})
        if ar.ingest_registry_images(_STORE, project, [f for f in found if f["digest"]]):
            _usage("registry_push", project)
    except Exception:
        pass            # registry down / not started: control plane keeps working


def _usage(op: str, name: str) -> None:
    """Mutations feed the space's activity log and cost-savings metrics (core/cost_model)."""
    try:
        ctx.record_usage(f"gcp.artifactregistry.{op}", {"resource": name})
    except Exception:
        pass


def register(app: FastAPI) -> None:
    async def _wire(request: Request):
        body = await request.body()
        if request.method == "GET":
            await run_in_threadpool(_sync_registry)
        r = ar.dispatch(_STORE, request.method, request.url.path, dict(request.query_params),
                        dict(request.headers), body)
        if r.status == 404 and "/operations/" in request.url.path:
            # The /operations/{op} path is shared with Kubernetes Engine and Memorystore LROs.
            from core import gcp_container_core as _gke, gcp_redis_core as _redis
            for other in (_gke, _redis):
                r2 = other.dispatch(other.shared_store(), "GET", request.url.path, dict(request.query_params),
                                    dict(request.headers), body)
                if r2.status == 200:
                    r = r2
                    break
        if request.method != "GET" and r.status < 300:
            _usage("wire", request.url.path)
        return Response(content=r.body, status_code=r.status, media_type=r.media_type)

    methods = ["GET", "POST", "PATCH", "DELETE"]
    app.add_route("/v1/projects/{project}/locations/{loc}/repositories", _wire, methods=methods)
    app.add_route("/v1/projects/{project}/locations/{loc}/repositories/{rest:path}", _wire, methods=methods)
    app.add_route("/v1/projects/{project}/locations/{loc}/operations/{op}", _wire, methods=["GET"])

    async def _json(request: Request) -> dict:
        try:
            b = await request.json()
        except Exception:
            b = {}
        return b if isinstance(b, dict) else {}

    @app.get("/api/gcp/artifactregistry/repositories")
    def api_ar_list():
        _sync_registry()
        return {"ok": True, "items": ar.console_list(_STORE)}

    @app.post("/api/gcp/artifactregistry/repositories")
    async def api_ar_create(request: Request):
        out = ar.console_create(_STORE, _project(), await _json(request))
        if out.get("ok"):
            _usage("create_repository", out.get("name", ""))
        return JSONResponse(out, status_code=200 if out.get("ok") else (409 if out.get("code") == "AlreadyExists" else 400))

    @app.get("/api/gcp/artifactregistry/repositories/{name}")
    def api_ar_get(name: str):
        _, repo = ar.console_find(_STORE, name)
        if repo is None:
            return JSONResponse({"ok": False, "code": "NotFound", "name": name}, status_code=404)
        return {"ok": True, **ar.console_row(repo)}

    @app.put("/api/gcp/artifactregistry/repositories/{name}")
    @app.patch("/api/gcp/artifactregistry/repositories/{name}")
    async def api_ar_update(name: str, request: Request):
        full, repo = ar.console_find(_STORE, name)
        if repo is None:
            return JSONResponse({"ok": False, "code": "NotFound", "name": name}, status_code=404)
        body = await _json(request)
        patch = {k: body[k] for k in ("description", "labels") if k in body}
        r = ar.dispatch(_STORE, "PATCH", "/v1/" + full, {"updateMask": ",".join(patch)}, {}, __import__("json").dumps(patch).encode())
        return JSONResponse({"ok": r.status < 300, **ar.console_row(_STORE.repos[full])}, status_code=200 if r.status < 300 else 400)

    @app.delete("/api/gcp/artifactregistry/repositories/{name}")
    def api_ar_delete(name: str):
        out = ar.console_delete(_STORE, name)
        if out.get("ok"):
            _usage("delete_repository", name)
        return JSONResponse(out, status_code=200 if out.get("ok") else 404)

    # /api/gcp/sub/... reaches handlers as /api/sub/... (provider-alias rewrite, like
    # every other GCP service's detail-tab actions); keep both spellings.
    @app.get("/api/gcp/sub/artifactregistry/{op}/{name}")
    @app.post("/api/gcp/sub/artifactregistry/{op}/{name}")
    @app.get("/api/sub/artifactregistry/{op}/{name}")
    @app.post("/api/sub/artifactregistry/{op}/{name}")
    async def api_ar_sub(op: str, name: str, request: Request):
        if op in ("listPackages", "listVersions", "listTags", "listImages"):
            await run_in_threadpool(_sync_registry)
            return {"ok": True, "items": ar.console_children(_STORE, name, op[4:].lower())}
        if op in ("getLabels", "setLabels"):   # the repository's Labels tab (repositories.patch labels)
            from core import gcp_console_tabs as _tabs
            full, repo = ar.console_find(_STORE, name)
            if repo is None:
                return JSONResponse({"ok": False, "code": "NotFound", "name": name}, status_code=404)
            if op == "setLabels":
                try:
                    labels = _tabs.validate_labels((await _json(request)).get("labels", {}))
                except _tabs.TabError as e:
                    return JSONResponse({"ok": False, "code": e.code, "message": e.message}, status_code=e.status)
                ar.dispatch(_STORE, "PATCH", "/v1/" + full, {"updateMask": "labels"}, {}, __import__("json").dumps({"labels": labels}).encode())
                _usage("set_labels", name)
            return {"ok": True, "item": {"name": name, "labels": dict(_STORE.repos[full].get("labels") or {})}}
        if op == "pushSample":
            out = ar.console_push_sample(_STORE, name, await _json(request))
            return JSONResponse(out, status_code=200 if out.get("ok") else 404)
        return JSONResponse({"ok": False, "code": "UnknownOperation", "name": op}, status_code=404)
