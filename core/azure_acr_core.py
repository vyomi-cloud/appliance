"""Azure Container Registry — repository data-plane core, substrate-independent (the Azure
analogue of core/gcp_artifactregistry_core.py). Speaks two REAL wires against the registry's
own data-plane host (`{registry}.azurecr.io`, routed here by path since it carries no SigV4):

  - the OCI / Docker Registry HTTP API V2 push half (what `docker push` / `oras push` / `crane
    push` send): PUT the manifest directly — no blob-layer bookkeeping, same simplification the
    AWS lens makes elsewhere (the layers themselves are never fetched by anything in Vyomi).
        GET    /v2/                              ping
        PUT    /v2/{repo}/manifests/{ref}         push (ref: tag or "sha256:...")
        GET    /v2/{repo}/manifests/{ref}         pull
        DELETE /v2/{repo}/manifests/{digest}      delete manifest (+ its tags)
        GET    /v2/{repo}/tags/list               list tags
        GET    /v2/_catalog                       list repositories
  - the ACR REST "data-plane" extension API (what `az acr repository ...`, the portal's
    Repositories blade, and the `azure-containerregistry` SDK read/delete):
        GET/DELETE /acr/v1/{repo}
        GET        /acr/v1/{repo}/_tags[/{tag}]       + DELETE .../_tags/{tag}
        GET        /acr/v1/{repo}/_manifests[/{digest}] + DELETE .../_manifests/{digest}
        GET        /acr/v1/_catalog

NO fastapi / azure-sdk / socket / subprocess imports → loads under Pyodide. One registry's
repositories live in a single flat AcrRegistryStore (Vyomi's data planes are process-global, the
same simplification Key Vault's keys/secrets stores make — not tied to a single registry login
server).  Errors use the Docker Distribution error envelope `{"errors":[{"code","message"}]}`,
which real `az acr` / the SDK also surface.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import unquote


@dataclass
class Response:
    status: int = 200
    headers: dict = field(default_factory=dict)
    body: bytes = b""
    media_type: str | None = "application/json"


class AcrRegistryStore:
    """repos[name] = {"tags": {tag: {digest,createdTime,lastUpdateTime}},
                       "manifests": {digest: {mediaType,size,body,createdTime,lastUpdateTime,tags:[...]}},
                       "createdTime", "lastUpdateTime"}"""

    def __init__(self):
        self.repos: dict = {}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _json(status: int, obj: dict) -> Response:
    return Response(status=status, body=json.dumps(obj).encode())


def _err(status: int, code: str, message: str) -> Response:
    return Response(status=status, body=json.dumps({"errors": [{"code": code, "message": message}]}).encode())


# ── repo model ──────────────────────────────────────────────────────────────
def _get_or_create_repo(store: AcrRegistryStore, name: str) -> dict:
    return store.repos.setdefault(name, {"tags": {}, "manifests": {}, "createdTime": _now(), "lastUpdateTime": _now()})


def _push_manifest(store: AcrRegistryStore, repo_name: str, reference: str, body: bytes, content_type: str) -> str:
    digest = "sha256:" + hashlib.sha256(body).hexdigest()
    repo = _get_or_create_repo(store, repo_name)
    now = _now()
    man = repo["manifests"].setdefault(digest, {"mediaType": content_type, "size": len(body), "body": body,
                                                 "createdTime": now, "tags": []})
    man["lastUpdateTime"] = now
    if not reference.startswith("sha256:"):
        tag = reference
        prev = repo["tags"].get(tag)
        old_digest = prev["digest"] if prev else None
        if old_digest and old_digest != digest and old_digest in repo["manifests"]:
            repo["manifests"][old_digest]["tags"] = [t for t in repo["manifests"][old_digest]["tags"] if t != tag]
        repo["tags"][tag] = {"digest": digest, "createdTime": prev["createdTime"] if prev else now, "lastUpdateTime": now}
        if tag not in man["tags"]:
            man["tags"].append(tag)
    repo["lastUpdateTime"] = now
    return digest


def _get_manifest(store: AcrRegistryStore, repo_name: str, reference: str):
    repo = store.repos.get(repo_name)
    if not repo:
        return None
    digest = reference if reference.startswith("sha256:") else (repo["tags"].get(reference) or {}).get("digest")
    if not digest:
        return None
    man = repo["manifests"].get(digest)
    return (man, digest) if man else None


def _drop_repo_if_empty(store: AcrRegistryStore, repo_name: str, repo: dict) -> None:
    if not repo["manifests"] and not repo["tags"]:
        store.repos.pop(repo_name, None)


def _delete_manifest(store: AcrRegistryStore, repo_name: str, digest: str) -> bool:
    repo = store.repos.get(repo_name)
    if not repo or digest not in repo["manifests"]:
        return False
    for t in repo["manifests"][digest].get("tags", []):
        repo["tags"].pop(t, None)
    del repo["manifests"][digest]
    _drop_repo_if_empty(store, repo_name, repo)
    return True


def _delete_tag(store: AcrRegistryStore, repo_name: str, tag: str) -> bool:
    repo = store.repos.get(repo_name)
    if not repo or tag not in repo["tags"]:
        return False
    digest = repo["tags"].pop(tag)["digest"]
    man = repo["manifests"].get(digest)
    if man:
        man["tags"] = [t for t in man["tags"] if t != tag]
    _drop_repo_if_empty(store, repo_name, repo)
    return True


def _delete_repo(store: AcrRegistryStore, repo_name: str) -> bool:
    return store.repos.pop(repo_name, None) is not None


def _repo_attrs(name: str, repo: dict) -> dict:
    return {"registry": "", "imageName": name, "createdTime": repo["createdTime"], "lastUpdateTime": repo["lastUpdateTime"],
            "manifestCount": len(repo["manifests"]), "tagCount": len(repo["tags"])}


def _tag_attrs(name: str, t: dict) -> dict:
    return {"name": name, "digest": t["digest"], "createdTime": t["createdTime"], "lastUpdateTime": t["lastUpdateTime"]}


def _manifest_attrs(digest: str, m: dict) -> dict:
    return {"digest": digest, "mediaType": m["mediaType"], "size": m["size"], "createdTime": m["createdTime"],
            "lastUpdateTime": m["lastUpdateTime"], "tags": list(m.get("tags", []))}


def _split_acr_v1(rest: list[str]):
    """{repo...}[/_tags|_manifests[/{item}]] -> (repo, "tags"|"manifests"|None, item|None)."""
    for i, s in enumerate(rest):
        if i > 0 and s in ("_tags", "_manifests"):
            repo = "/".join(rest[:i])
            kind = "tags" if s == "_tags" else "manifests"
            item = "/".join(rest[i + 1:]) if len(rest) > i + 1 else None
            return repo, kind, item
    return ("/".join(rest) if rest else None), None, None


# ── dispatch ──────────────────────────────────────────────────────────────
def dispatch(store: AcrRegistryStore, method: str, path: str,
             query: dict | None = None, headers: dict | None = None, body: bytes = b"") -> Response:
    query = query or {}
    method = method.upper()
    lheaders = {(k or "").lower(): v for k, v in (headers or {}).items()}
    body = bytes(body or b"")
    p = path.split("?", 1)[0]
    segs = [unquote(s) for s in p.split("/") if s != ""]
    if not segs:
        return _err(404, "NOT_FOUND", f"Unknown path: {path}")

    if segs[0] == "v2":
        rest = segs[1:]
        if not rest:
            return _json(200, {})
        if rest == ["_catalog"]:
            names = sorted(store.repos.keys())
            n = query.get("n")
            if n:
                names = names[:int(n)]
            return _json(200, {"repositories": names})
        if len(rest) >= 2 and rest[-2] == "tags" and rest[-1] == "list":
            if method != "GET":
                return _err(405, "UNSUPPORTED", "Method not allowed.")
            repo_name = "/".join(rest[:-2])
            repo = store.repos.get(repo_name)
            if not repo:
                return _err(404, "NAME_UNKNOWN", f"repository name not known to registry: {repo_name}")
            return _json(200, {"name": repo_name, "tags": sorted(repo["tags"].keys())})
        if len(rest) >= 2 and rest[-2] == "manifests":
            repo_name, reference = "/".join(rest[:-2]), rest[-1]
            if method == "PUT":
                ct = lheaders.get("content-type") or "application/vnd.docker.distribution.manifest.v2+json"
                digest = _push_manifest(store, repo_name, reference, body, ct)
                return Response(status=201, headers={"docker-content-digest": digest})
            if method == "GET":
                found = _get_manifest(store, repo_name, reference)
                if not found:
                    return _err(404, "MANIFEST_UNKNOWN", f"manifest unknown: {reference}")
                man, digest = found
                return Response(status=200, headers={"docker-content-digest": digest, "content-type": man["mediaType"]},
                                 body=man.get("body", b"{}"))
            if method == "DELETE":
                if reference.startswith("sha256:") and _delete_manifest(store, repo_name, reference):
                    return Response(status=202)
                return _err(404, "MANIFEST_UNKNOWN", f"manifest unknown: {reference}")
            return _err(405, "UNSUPPORTED", "Method not allowed.")
        return _err(404, "NOT_FOUND", f"Unknown path: {path}")

    if segs[0] == "acr" and len(segs) > 1 and segs[1] == "v1":
        rest = segs[2:]
        if rest == ["_catalog"]:
            return _json(200, {"repositories": sorted(store.repos.keys())})
        repo_name, kind, item = _split_acr_v1(rest)
        if repo_name is None:
            return _err(404, "NOT_FOUND", f"Unknown path: {path}")
        repo = store.repos.get(repo_name)
        if kind is None:
            if method == "GET":
                if not repo:
                    return _err(404, "NAME_UNKNOWN", f"repository name not known to registry: {repo_name}")
                return _json(200, _repo_attrs(repo_name, repo))
            if method == "DELETE":
                if not _delete_repo(store, repo_name):
                    return _err(404, "NAME_UNKNOWN", f"repository name not known to registry: {repo_name}")
                return _json(200, {"status": "Success"})
            return _err(405, "UNSUPPORTED", "Method not allowed.")
        if not repo:
            return _err(404, "NAME_UNKNOWN", f"repository name not known to registry: {repo_name}")
        if kind == "tags":
            if item is None:
                if method != "GET":
                    return _err(405, "UNSUPPORTED", "Method not allowed.")
                tags = [_tag_attrs(t, repo["tags"][t]) for t in sorted(repo["tags"])]
                return _json(200, {"registry": "", "imageName": repo_name, "tags": tags})
            if method == "GET":
                t = repo["tags"].get(item)
                if not t:
                    return _err(404, "TAG_UNKNOWN", f"tag unknown: {item}")
                return _json(200, {"registry": "", "imageName": repo_name, "tag": _tag_attrs(item, t)})
            if method == "DELETE":
                if not _delete_tag(store, repo_name, item):
                    return _err(404, "TAG_UNKNOWN", f"tag unknown: {item}")
                return _json(200, {})
            return _err(405, "UNSUPPORTED", "Method not allowed.")
        if kind == "manifests":
            if item is None:
                if method != "GET":
                    return _err(405, "UNSUPPORTED", "Method not allowed.")
                mans = [_manifest_attrs(d, repo["manifests"][d]) for d in sorted(repo["manifests"])]
                return _json(200, {"registry": "", "imageName": repo_name, "manifests": mans})
            if method == "GET":
                m = repo["manifests"].get(item)
                if not m:
                    return _err(404, "MANIFEST_UNKNOWN", f"manifest unknown: {item}")
                return _json(200, _manifest_attrs(item, m))
            if method == "DELETE":
                if not _delete_manifest(store, repo_name, item):
                    return _err(404, "MANIFEST_UNKNOWN", f"manifest unknown: {item}")
                return _json(200, {})
            return _err(405, "UNSUPPORTED", "Method not allowed.")
    return _err(404, "NOT_FOUND", f"Unknown path: {path}")
