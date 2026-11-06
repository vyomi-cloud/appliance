"""AWS ECR — console REST + native-wire front door, served by core/ecr_core.py.

The engine (`core/ecr_core.py`) is substrate-free and is the API: the same file
runs here and in Nano. This module only binds it to the appliance:

  * state — an `EcrStore` bound to the active space's `service_states["ecr"]`
    dict, so repositories/images persist with the space (and feed the
    cost-savings collector in server.py);
  * wire — `wire(request)` serves the native JSON protocol (X-Amz-Target
    AmazonEC2ContainerRegistry_V20150921.*) that unmodified AWS SDKs / `aws ecr`
    send to the endpoint root;
  * console — /api/aws/ecr/repositories[/{name}[/images]] for the catalog-driven
    /console/aws UI;
  * data plane — when `VYOMI_ECR_REGISTRY_URL` points at the shared CNCF
    `registry:2` container, repositoryUri / proxyEndpoint use its host so
    `docker push` works against it, and images pushed that way are mirrored
    into the engine (and deleted from the registry when deleted here).
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from core import app_context as ctx
from core import ecr_core

PLATFORM = ctx.PLATFORM
_FALLBACK_STATE: dict = {}
_MANIFEST_ACCEPT = ", ".join([
    "application/vnd.docker.distribution.manifest.v2+json",
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.oci.image.index.v1+json",
])


_PROBE: dict = {"at": 0.0, "up": False}


def _registry_url() -> str:
    """The backing registry, or "" when none is configured or reachable (the
    registry only runs in the `full` profile; probed at most every 5 s)."""
    url = os.environ.get("VYOMI_ECR_REGISTRY_URL", "").rstrip("/")
    if not url:
        return ""
    now = time.time()
    if now - _PROBE["at"] > 5:
        _PROBE["at"] = now
        try:
            with urllib.request.urlopen(url + "/v2/", timeout=1):
                _PROBE["up"] = True
        except urllib.error.HTTPError:
            _PROBE["up"] = True       # any HTTP answer (e.g. 401) means it is up
        except Exception:
            _PROBE["up"] = False
    return url if _PROBE["up"] else ""


def _registry_host() -> str:
    """Host the *client* pushes to (VYOMI_ECR_REGISTRY_HOST, default the URL's host)."""
    url = _registry_url()
    return (os.environ.get("VYOMI_ECR_REGISTRY_HOST") or urlparse(url).netloc) if url else ""


def _state() -> dict:
    spaces_state = PLATFORM.kernel.state.setdefault("spaces", {"spaces": {}, "active_space_id": "", "settings": {}})
    active_id = spaces_state.get("active_space_id", "")
    if not active_id:
        return _FALLBACK_STATE
    space = spaces_state.setdefault("spaces", {}).setdefault(active_id, {})
    return space.setdefault("service_states", {}).setdefault("ecr", {})


class _SpaceEcrStore(ecr_core.EcrStore):
    """EcrStore whose persist() hook writes the platform state."""

    def persist(self) -> None:
        try:
            ctx.persist_state()
        except Exception:
            pass


def store() -> ecr_core.EcrStore:
    s = _SpaceEcrStore(_state())
    s.registry_host = _registry_host()
    return s


# ── real registry mirror (best effort; never breaks the API) ───────────────
def _reg(path: str, method: str = "GET", headers: dict | None = None):
    req = urllib.request.Request(_registry_url() + path, method=method, headers=headers or {})
    with urllib.request.urlopen(req, timeout=3) as r:
        return r.status, dict(r.headers), r.read()


def sync_from_registry(s: ecr_core.EcrStore) -> None:
    """Mirror images `docker push`ed to the backing registry into the engine."""
    if not _registry_url():
        return
    changed = False
    for repo in list(s.repositories):
        try:
            _, _, raw = _reg(f"/v2/{repo}/tags/list")
            tags = json.loads(raw).get("tags") or []
        except Exception:
            continue
        imgs = s.images.setdefault(repo, [])
        seen: set[str] = set()
        for tag in tags:
            try:
                _, h, raw = _reg(f"/v2/{repo}/manifests/{tag}", headers={"Accept": _MANIFEST_ACCEPT})
                digest = h.get("Docker-Content-Digest") or h.get("docker-content-digest")
                man = json.loads(raw)
            except Exception:
                continue
            if not digest:
                continue
            seen.add(digest)
            img = next((i for i in imgs if i["digest"] == digest), None)
            if img is None:
                _, _, size = ecr_core._manifest_refs(man)
                img = {"digest": digest, "manifest": raw.decode(), "tags": [], "size": size,
                       "mediaType": man.get("mediaType") or ecr_core.DEFAULT_MANIFEST_MT,
                       "pushedAt": ecr_core._now(), "lastPull": None, "scan": None, "source": "registry"}
                if s.repositories[repo]["scanOnPush"]:
                    ecr_core._scan(img)
                imgs.append(img)
                changed = True
            if tag not in img["tags"]:
                for other in imgs:
                    if other is not img and tag in other["tags"]:
                        other["tags"].remove(tag)
                img["tags"].append(tag)
                changed = True
        for img in [i for i in imgs if i.get("source") == "registry" and i["digest"] not in seen]:
            imgs.remove(img)
            changed = True
    if changed:
        s.persist()


def _delete_from_registry(repo: str, digests: list[str]) -> None:
    if not _registry_url():
        return
    for d in digests:
        try:
            _reg(f"/v2/{repo}/manifests/{d}", method="DELETE")
        except Exception:
            pass


# ── native wire ────────────────────────────────────────────────────────────
async def wire(request: Request) -> Response:
    """Serve one native ECR JSON-protocol request (called from the root dispatcher)."""
    target = request.headers.get("x-amz-target", "")
    try:
        payload = json.loads((await request.body()) or b"{}")
    except Exception:
        payload = {}
    s = store()
    op = target.rsplit(".", 1)[-1]
    if op in ("ListImages", "DescribeImages", "BatchGetImage", "DescribeRepositories", "DescribeImageScanFindings", "StartImageScan"):
        sync_from_registry(s)
    repo = payload.get("repositoryName", "") if isinstance(payload, dict) else ""
    pre: list[str] = []
    if op == "BatchDeleteImage" and isinstance(payload, dict):
        pre = _digests_for(s, payload)
    elif op == "DeleteRepository":
        pre = [i["digest"] for i in s.images.get(repo, []) if i.get("source") == "registry"]
    r = ecr_core.dispatch(s, target, payload)
    if op == "BatchDeleteImage" and r.status < 400:
        gone = {i["imageDigest"] for i in r.body.get("imageIds", [])}
        _delete_from_registry(repo, [d for d in pre if d in gone])
    elif op == "DeleteRepository" and r.status < 400:
        _delete_from_registry(repo, pre)
    return Response(content=json.dumps(r.body), status_code=r.status, media_type="application/x-amz-json-1.1")


def _digests_for(s: ecr_core.EcrStore, payload: dict) -> list[str]:
    out = []
    for iid in payload.get("imageIds") or []:
        img = ecr_core._find_image(s, payload.get("repositoryName", ""), iid)
        if img is not None and img.get("source") == "registry":
            out.append(img["digest"])
    return out


# ── console REST ───────────────────────────────────────────────────────────
def _status(res: dict, ok_status: int = 200) -> JSONResponse:
    if res.get("ok") is False:
        code = res.get("code") or "Error"
        return JSONResponse(res, status_code=404 if code == "RepositoryNotFoundException" else
                            409 if code in ("RepositoryAlreadyExistsException", "RepositoryNotEmptyException") else 400)
    return JSONResponse(res, status_code=ok_status)


def register(app: FastAPI) -> None:
    @app.get("/api/aws/ecr/repositories")
    def api_ecr_list():
        s = store()
        sync_from_registry(s)
        return ecr_core.console_list(s)

    @app.post("/api/aws/ecr/repositories")
    async def api_ecr_create(request: Request):
        try:
            body = await request.json()
        except Exception:
            body = {}
        res = ecr_core.console_create(store(), body if isinstance(body, dict) else {})
        if res.get("ok"):
            ctx.record_usage("aws.ecr.create_repository", {"name": res["name"]})
        return _status(res, 201)

    @app.get("/api/aws/ecr/repositories/{name:path}/images")
    def api_ecr_images(name: str):
        s = store()
        sync_from_registry(s)
        return _status(ecr_core.console_images(s, name))

    @app.get("/api/aws/ecr/repositories/{name:path}")
    def api_ecr_get(name: str):
        s = store()
        sync_from_registry(s)
        return _status(ecr_core.console_get(s, name))

    @app.api_route("/api/aws/ecr/repositories/{name:path}", methods=["PATCH", "PUT"])
    async def api_ecr_update(name: str, request: Request):
        try:
            body = await request.json()
        except Exception:
            body = {}
        return _status(ecr_core.console_update(store(), name, body if isinstance(body, dict) else {}))

    @app.delete("/api/aws/ecr/repositories/{name:path}")
    def api_ecr_delete(name: str):
        s = store()
        digests = [i["digest"] for i in s.images.get(name, []) if i.get("source") == "registry"]
        res = ecr_core.console_delete(s, name)
        if res.get("ok"):
            _delete_from_registry(name, digests)
            ctx.record_usage("aws.ecr.delete_repository", {"name": name})
        return _status(res)
