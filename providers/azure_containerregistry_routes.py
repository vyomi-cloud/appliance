"""Offline image data plane for Azure Container Registry (``{registry}.azurecr.io``).

core/azure_containerregistry_core.py owns the registry resource; this module only fronts the shared
CNCF Distribution registry container (the same backend ECR / Artifact Registry use) so ``docker push`` /
``docker pull`` / ``skopeo`` / ``crane`` work against a registry created through ARM:
``/azure-data/acr/{registry}/v2/{repo…}`` is forwarded to ``{backend}/v2/{registry}/{repo…}`` (one
namespace per registry), with ``_catalog``, ``tags/list`` and ``Location`` headers rewritten so the
namespace is invisible to the client. A request whose Host is ``{registry}.azurecr.*`` is rewritten onto the
same path by core.middleware. If the backend container is not running (Free tier), the registry keeps its
full control plane and the data plane answers 503 ``UNAVAILABLE``.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import urllib.error
import urllib.request

from fastapi import Request
from fastapi.responses import Response

from core import azure_containerregistry_core as core

METHODS = ["GET", "HEAD", "PUT", "POST", "PATCH", "DELETE"]
_FORWARD_REQ = ("content-type", "content-length", "accept", "range", "content-range", "docker-content-digest")
_FORWARD_RESP = ("content-type", "content-length", "docker-content-digest", "docker-distribution-api-version",
                 "etag", "range", "location", "accept-ranges", "content-range", "www-authenticate")


def backend_url() -> str:
    return os.environ.get("CLOUDLEARN_REGISTRY_URL", "http://vyomi-registry:5000").rstrip("/")


def _state():
    from providers import azure_services
    return azure_services._state


def _errors(status: int, code: str, message: str, headers: dict | None = None) -> Response:
    h = {"Docker-Distribution-API-Version": "registry/2.0"}
    h.update(headers or {})
    return Response(content=json.dumps({"errors": [{"code": code, "message": message, "detail": None}]}),
                    status_code=status, headers=h, media_type="application/json")


def _forward(method: str, url: str, headers: dict, body: bytes | None):
    req = urllib.request.Request(url, data=body if body else None, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def register(app) -> None:
    async def dispatch(registry: str, request: Request, rest: str = ""):
        rec = core._find_registry(_state(), registry)
        if rec is None:
            return _errors(404, "NAME_UNKNOWN", f"registry '{registry}' not found")
        mount = "/v2" if request.scope.get("azure_acr_host") else f"/azure-data/acr/{registry}/v2"
        rest = rest.lstrip("/")                                  # keep a trailing slash: blobs/uploads/ differs from blobs/uploads
        if rest == "":                                           # GET /v2/ — API version check (docker login / pull)
            return Response(content="{}", media_type="application/json",
                            headers={"Docker-Distribution-API-Version": "registry/2.0"})
        ns = registry.lower()
        path = f"/v2/{ns}/{rest}"
        if rest.startswith("_catalog"):
            path = "/v2/_catalog"
        qs = request.url.query
        headers: dict = {}
        for k, v in request.headers.items():                    # `Accept` is sent once per media type; keep them all
            if k.lower() in _FORWARD_REQ:
                headers[k] = f"{headers[k]}, {v}" if k in headers else v
        body = await request.body() if request.method in ("PUT", "POST", "PATCH") else None
        try:
            status, rh, data = await asyncio.get_running_loop().run_in_executor(
                None, _forward, request.method, backend_url() + path + (f"?{qs}" if qs else ""), headers, body)
        except Exception as e:                                   # backend container not running
            return _errors(503, "UNAVAILABLE", f"The registry data plane is not running in this tier ({e.__class__.__name__}); "
                                               "the control plane is fully available.")
        out = {k: v for k, v in rh.items() if k.lower() in _FORWARD_RESP and k.lower() != "content-length"}
        loc = next((k for k in out if k.lower() == "location"), None)
        if loc:
            v = re.sub(r"^https?://[^/]+", "", out[loc])         # the backend's own origin is meaningless to the client
            out[loc] = v.replace(f"/v2/{ns}/", mount + "/", 1)
        if rest.startswith("_catalog") and status == 200:
            try:
                repos = [r[len(ns) + 1:] for r in json.loads(data).get("repositories", []) if r.startswith(ns + "/")]
                data = json.dumps({"repositories": repos}).encode()
            except ValueError:
                pass
        elif rest.endswith("/tags/list") and status == 200:
            try:
                j = json.loads(data)
                if str(j.get("name", "")).startswith(ns + "/"):
                    j["name"] = j["name"][len(ns) + 1:]
                data = json.dumps(j).encode()
            except ValueError:
                pass
        elif status >= 400 and data:
            pass
        return Response(content=b"" if request.method == "HEAD" else data, status_code=status, headers=out)

    app.add_api_route("/azure-data/acr/{registry}/v2", dispatch, methods=METHODS, include_in_schema=False)
    app.add_api_route("/azure-data/acr/{registry}/v2/{rest:path}", dispatch, methods=METHODS, include_in_schema=False)
