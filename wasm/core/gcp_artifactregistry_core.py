"""GCP Artifact Registry core — substrate-independent. Speaks the native
**Artifact Registry REST API v1** (`/v1/projects/{p}/locations/{l}/repositories...`)
so `google-cloud-artifact-registry` (Python/Java/Go) and `gcloud artifacts` work
unchanged against it (point the client's endpoint at the core's endpoint).

NO fastapi / google-cloud / socket / subprocess imports → loads under Pyodide, and
the very same file runs in the offline appliance and in Nano.

Resources (the Discovery doc `artifactregistry/v1`):
  projects.locations                       list · get
  projects.locations.operations            get                       (long-running ops)
  repositories                             create · get · list · patch · delete
                                           getIamPolicy · setIamPolicy · testIamPermissions
  repositories.packages                    list · get · patch · delete
  repositories.packages.versions           list · get · delete · batchDelete
  repositories.packages.tags               create · list · get · patch · delete
  repositories.dockerImages                list · get
  repositories.files                       list · get · delete

create/delete of a repository return a long-running Operation (already `done`)
exactly like the real API, so the SDKs' `.result()` / `wait` work. Errors use the
native {"error":{"code","message","status"}} body.

The control plane is complete; the data plane (what a `docker push` creates —
packages, versions, tags, files) is fed through `ingest_image()` / `ingest_package()`
(the hook the registry data plane, the console "Push sample image" action and the
tests use), since the real API has no upload method.

State persists through a `KvStore`-style seam: `ArtifactRegistryStore` keeps plain
JSON-safe dicts (so nano_persist and the offline space slot can snapshot them).
"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

FORMATS = ("DOCKER", "MAVEN", "NPM", "PYTHON", "APT", "YUM", "KFP", "GO", "GENERIC", "GOOGET")
MODES = ("STANDARD_REPOSITORY", "VIRTUAL_REPOSITORY", "REMOTE_REPOSITORY")
# Proto enum numbers: the Go/Java REST clients send `$alt=json;enum-encoding=int`.
_FORMAT_NUM = {1: "DOCKER", 2: "MAVEN", 3: "NPM", 5: "APT", 6: "YUM", 7: "GOOGET", 8: "PYTHON",
               9: "KFP", 10: "GO", 11: "GENERIC"}
_MODE_NUM = {0: "MODE_UNSPECIFIED", 1: "STANDARD_REPOSITORY", 2: "VIRTUAL_REPOSITORY", 3: "REMOTE_REPOSITORY"}
LOCATIONS = ("us-central1", "us-east1", "us-east4", "us-west1", "us-west2", "europe-west1",
             "europe-west2", "europe-west4", "asia-east1", "asia-northeast1", "asia-southeast1",
             "us", "europe", "asia")
_TYPE = "type.googleapis.com/google.devtools.artifactregistry.v1."
# Real repository ids: 1-63 chars, lowercase letters / digits / hyphens, start with a letter.
_ID_OK = set("abcdefghijklmnopqrstuvwxyz0123456789-")


@dataclass
class GcpResponse:
    status: int = 200
    headers: dict = field(default_factory=dict)
    body: bytes = b""
    media_type: str | None = "application/json"


class ArtifactRegistryStore:
    """Plain, JSON-safe state: repositories (with their packages) and operations."""

    def __init__(self) -> None:
        self.repos: dict[str, dict] = {}
        self.operations: dict[str, dict] = {}
        self.iam: dict[str, dict] = {}

    def persist(self) -> None:
        """Hook: the offline appliance flushes the space slot, Nano snapshots to IDB."""


# ── primitives ────────────────────────────────────────────────────────────
def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _json(status: int, obj: dict) -> GcpResponse:
    return GcpResponse(status=status, body=json.dumps(obj).encode())


_STATUS_TOKEN = {400: "INVALID_ARGUMENT", 403: "PERMISSION_DENIED", 404: "NOT_FOUND",
                 409: "ALREADY_EXISTS", 412: "FAILED_PRECONDITION", 500: "INTERNAL"}


def _err(status: int, message: str, token: str | None = None) -> GcpResponse:
    return _json(status, {"error": {"code": status, "message": message,
                                    "status": token or _STATUS_TOKEN.get(status, "UNKNOWN")}})


def _repo_name(project: str, loc: str, repo: str) -> str:
    return f"projects/{project}/locations/{loc}/repositories/{repo}"


def _page(items: list, query: dict) -> tuple[list, str]:
    """Offset pagination with the real pageSize / pageToken / nextPageToken contract."""
    try:
        size = int(query.get("pageSize") or 0) or 1000
    except (TypeError, ValueError):
        size = 1000
    try:
        start = int(query.get("pageToken") or 0)
    except (TypeError, ValueError):
        start = 0
    chunk = items[start:start + size]
    return chunk, (str(start + size) if start + size < len(items) else "")


def _with_page(key: str, items: list, query: dict) -> dict:
    chunk, nxt = _page(items, query)
    out = {key: chunk}
    if nxt:
        out["nextPageToken"] = nxt
    return out


# Offline data plane (the shared registry container); None → control plane only (Nano).
DATA_PLANE: dict = {"host": None, "port": 5000}


def configure_data_plane(host, port=5000):
    DATA_PLANE["host"], DATA_PLANE["port"] = (host or None), int(port or 5000)


def ingest_registry_images(store: ArtifactRegistryStore, project: str, images: list) -> int:
    """Fold what a real `docker push` left in the registry into the engine.
    Each item: {"path": "{repo}/{image...}", "tag", "digest", "size"} (registry path minus the
    project segment). Docker repositories only; unknown repositories and known tags are skipped.
    Returns the number of versions/tags newly recorded."""
    n = 0
    for im in images:
        repo_id, _, image = str(im.get("path", "")).partition("/")
        if not image:
            continue
        full = next((k for k, r in store.repos.items()
                     if k.startswith(f"projects/{project}/locations/") and k.rsplit("/", 1)[-1] == repo_id
                     and r.get("format") == "DOCKER"), None)
        if full is None:
            continue
        pkg = store.repos[full]["packages"].get(_pkg_key(image))
        ver = ((pkg or {}).get("versions") or {}).get(im["digest"])
        if ver is not None and any(t["name"].rsplit("/", 1)[-1] == im["tag"] for t in ver["_tags"]):
            continue
        ingest_package(store, full, image, im["digest"], int(im.get("size") or 0), [im["tag"]])
        n += 1
    return n



# ── views ─────────────────────────────────────────────────────────────────
def _size(repo: dict) -> int:
    return sum(int(v.get("sizeBytes", 0)) for p in repo["packages"].values() for v in p["versions"].values())


def _repo_view(repo: dict) -> dict:
    out = {k: repo[k] for k in ("name", "format", "description", "createTime", "updateTime", "mode",
                                "sizeBytes") if k in repo}
    out["sizeBytes"] = str(_size(repo))
    for k in ("labels", "kmsKeyName", "dockerConfig", "mavenConfig", "cleanupPolicies",
              "cleanupPolicyDryRun", "vulnerabilityScanningConfig", "remoteRepositoryConfig",
              "virtualRepositoryConfig", "disallowUnspecifiedMode"):
        if repo.get(k) not in (None, "", {}, []):
            out[k] = repo[k]
    out["satisfiesPzi"] = True
    return out


def _pkg_view(p: dict) -> dict:
    return {k: p[k] for k in ("name", "displayName", "createTime", "updateTime") if k in p}


def _ver_view(v: dict, with_tags: bool = False) -> dict:
    out = {k: v[k] for k in ("name", "description", "createTime", "updateTime") if k in v}
    out["relatedTags"] = [{"name": t["name"], "version": t["version"]} for t in v.get("_tags", [])]
    if v.get("metadata"):
        out["metadata"] = v["metadata"]
    return out


def _image_view(project: str, loc: str, repo: str, pkg: dict, ver: dict) -> dict:
    digest = ver["name"].rsplit("/", 1)[-1]
    pname = pkg["displayName"]
    return {
        "name": f"{_repo_name(project, loc, repo)}/dockerImages/{pname}@{digest}",
        "uri": f"{loc}-docker.pkg.dev/{project}/{repo}/{pname}@{digest}",
        "tags": [t["name"].rsplit("/", 1)[-1] for t in ver.get("_tags", [])],
        "imageSizeBytes": str(ver.get("sizeBytes", 0)),
        "uploadTime": ver["createTime"],
        "mediaType": "application/vnd.docker.distribution.manifest.v2+json",
        "buildTime": ver["createTime"],
        "updateTime": ver["updateTime"],
    }


def _tag_view(t: dict) -> dict:
    return {"name": t["name"], "version": t["version"]}


# ── long-running operations ───────────────────────────────────────────────
def _operation(store: ArtifactRegistryStore, project: str, loc: str, rtype: str, response: dict | None) -> dict:
    op = {"name": f"projects/{project}/locations/{loc}/operations/{uuid.uuid4().hex}", "done": True,
          "metadata": {"@type": _TYPE + "OperationMetadata"},
          "response": {"@type": (_TYPE + rtype) if rtype != "Empty" else "type.googleapis.com/google.protobuf.Empty",
                       **(response or {})}}
    store.operations[op["name"]] = op
    return op


# ── repositories ──────────────────────────────────────────────────────────
_MUTABLE = ("description", "labels", "kmsKeyName", "dockerConfig", "mavenConfig", "cleanupPolicies",
            "cleanupPolicyDryRun", "vulnerabilityScanningConfig", "remoteRepositoryConfig",
            "virtualRepositoryConfig", "disallowUnspecifiedMode")


def _create_repo(store, project, loc, query, body) -> GcpResponse:
    rid = query.get("repositoryId") or query.get("repository_id") or ""
    if not rid:
        return _err(400, "repositoryId is required (query parameter).")
    if not (1 <= len(rid) <= 63) or not rid[0].isalpha() or not set(rid) <= _ID_OK or rid.endswith("-"):
        return _err(400, f"Invalid repository ID \"{rid}\": must be 1-63 lowercase letters, digits or hyphens, "
                         "starting with a letter.")
    fmt = body.get("format") or "FORMAT_UNSPECIFIED"
    if isinstance(fmt, int):
        fmt = _FORMAT_NUM.get(fmt, "FORMAT_UNSPECIFIED")
    if fmt not in FORMATS:
        return _err(400, "Invalid repository format: a valid format is required "
                         f"({', '.join(FORMATS)}).")
    mode = body.get("mode") or "STANDARD_REPOSITORY"
    if isinstance(mode, int):
        mode = _MODE_NUM.get(mode, "")
    if mode == "MODE_UNSPECIFIED":
        mode = "STANDARD_REPOSITORY"
    if mode not in MODES:
        return _err(400, f"Invalid repository mode \"{mode}\".")
    name = _repo_name(project, loc, rid)
    if name in store.repos:
        return _err(409, f"the repository already exists: {name}")
    now = _now()
    repo = {"name": name, "format": fmt, "mode": mode, "createTime": now, "updateTime": now,
            "description": body.get("description", ""), "labels": body.get("labels") or {},
            "packages": {}}
    for k in _MUTABLE[2:]:
        if body.get(k) is not None:
            repo[k] = body[k]
    if fmt == "DOCKER":
        repo.setdefault("dockerConfig", {"immutableTags": False})
    store.repos[name] = repo
    store.persist()
    return _json(200, _operation(store, project, loc, "Repository", _repo_view(repo)))


def _get_repo(store, name) -> GcpResponse:
    repo = store.repos.get(name)
    if repo is None:
        return _err(404, f"Repository \"{name}\" not found.")
    return _json(200, _repo_view(repo))


def _list_repos(store, project, loc, query) -> GcpResponse:
    prefix = f"projects/{project}/locations/{loc}/repositories/"
    repos = [_repo_view(r) for n, r in sorted(store.repos.items()) if n.startswith(prefix)]
    return _json(200, _with_page("repositories", repos, query))


def _patch_repo(store, name, query, body) -> GcpResponse:
    repo = store.repos.get(name)
    if repo is None:
        return _err(404, f"Repository \"{name}\" not found.")
    mask = [m.strip() for m in (query.get("updateMask") or "").split(",") if m.strip()]
    fields = [m.split(".")[0] for m in mask] if mask else [k for k in _MUTABLE if k in body]
    for f in fields:
        if f not in _MUTABLE:
            return _err(400, f"Invalid field mask path: \"{f}\" is not an updatable field of Repository.")
        if f in body:
            repo[f] = body[f]
        else:
            repo.pop(f, None)
    repo["updateTime"] = _now()
    store.persist()
    return _json(200, _repo_view(repo))


def _delete_repo(store, project, loc, name) -> GcpResponse:
    if name not in store.repos:
        return _err(404, f"Repository \"{name}\" not found.")
    del store.repos[name]
    store.iam.pop(name, None)
    store.persist()
    return _json(200, _operation(store, project, loc, "Empty", None))


# ── IAM ───────────────────────────────────────────────────────────────────
def _etag(policy: dict) -> str:
    return hashlib.sha1(json.dumps(policy.get("bindings", []), sort_keys=True).encode()).hexdigest()[:8]


def _iam(store, method, name, verb, body) -> GcpResponse:
    if name not in store.repos:
        return _err(404, f"Repository \"{name}\" not found.")
    if verb == "getIamPolicy":
        pol = store.iam.get(name) or {"version": 1, "etag": "ACAB"}
        return _json(200, pol)
    if verb == "setIamPolicy":
        pol = dict(body.get("policy") or {})
        pol.setdefault("bindings", [])
        pol["version"] = pol.get("version") or 1
        pol["etag"] = _etag(pol)
        store.iam[name] = pol
        store.persist()
        return _json(200, pol)
    return _json(200, {"permissions": list(body.get("permissions") or [])})   # testIamPermissions


# ── data plane hook: what a push creates ──────────────────────────────────
def _pkg_key(display: str) -> str:
    return display.replace("/", "%2F")


def ingest_package(store: ArtifactRegistryStore, repo_name: str, package: str, version: str,
                   size_bytes: int = 0, tags: list | None = None, files: list | None = None) -> dict:
    """Record a package version (and tags) in a repository — the data-plane hook.
    `version` is the version id (a sha256 digest for Docker). Returns the version."""
    repo = store.repos.get(repo_name)
    if repo is None:
        raise KeyError(repo_name)
    now = _now()
    pkey = _pkg_key(package)
    pkg = repo["packages"].setdefault(pkey, {
        "name": f"{repo_name}/packages/{pkey}", "displayName": package,
        "createTime": now, "updateTime": now, "versions": {}, "tags": {}})
    pkg["updateTime"] = now
    ver = pkg["versions"].get(version)
    if ver is None:
        ver = pkg["versions"][version] = {
            "name": f"{pkg['name']}/versions/{version}", "createTime": now, "updateTime": now,
            "sizeBytes": int(size_bytes), "_tags": [],
            "files": {}}
    for fname in (files or [f"{package}/{version}"]):
        fid = fname.replace("/", "%2F")
        ver["files"][fid] = {"name": f"{repo_name}/files/{fid}", "sizeBytes": str(int(size_bytes)),
                             "createTime": now, "updateTime": now,
                             "hashes": [{"type": "SHA256", "value": hashlib.sha256(fname.encode()).hexdigest()}],
                             "owner": pkg["name"]}
    for t in tags or []:
        _set_tag(pkg, t, ver)
    repo["updateTime"] = now
    store.persist()
    return ver


def ingest_image(store: ArtifactRegistryStore, repo_name: str, image: str = "sample-app",
                 tag: str = "latest", size_bytes: int = 5 * 1024 * 1024) -> dict:
    """A `docker push {loc}-docker.pkg.dev/{p}/{repo}/{image}:{tag}` as the engine sees it."""
    digest = "sha256:" + hashlib.sha256(f"{repo_name}/{image}:{tag}:{_now()}".encode()).hexdigest()
    return ingest_package(store, repo_name, image, digest, size_bytes, [tag])


def _set_tag(pkg: dict, tag_id: str, ver: dict) -> dict:
    # A tag points at exactly one version of the package.
    for v in pkg["versions"].values():
        v["_tags"] = [t for t in v.get("_tags", []) if not t["name"].endswith(f"/tags/{tag_id}")]
    t = {"name": f"{pkg['name']}/tags/{tag_id}", "version": ver["name"]}
    ver.setdefault("_tags", []).append(t)
    pkg["tags"][tag_id] = t
    return t


def _find(store, repo_name, pkey=None):
    repo = store.repos.get(repo_name)
    if repo is None:
        return None, None, _err(404, f"Repository \"{repo_name}\" not found.")
    if pkey is None:
        return repo, None, None
    pkg = repo["packages"].get(pkey)
    if pkg is None:
        return repo, None, _err(404, f"Package \"{repo_name}/packages/{pkey}\" not found.")
    return repo, pkg, None


# ── packages / versions / tags ────────────────────────────────────────────
def _packages(store, method, repo_name, rest, query, body) -> GcpResponse:
    """rest = segments after .../packages"""
    repo, pkg, err = _find(store, repo_name, rest[0] if rest else None)
    if err:
        return err
    if not rest:
        if method != "GET":
            return _err(400, f"Unsupported method {method} on packages collection.")
        items = [_pkg_view(p) for _, p in sorted(repo["packages"].items())]
        return _json(200, _with_page("packages", items, query))
    pkey = rest[0]
    if len(rest) == 1:
        if method == "GET":
            return _json(200, _pkg_view(pkg))
        if method == "DELETE":
            del repo["packages"][pkey]
            store.persist()
            return _json(200, _operation(store, *_pl(repo_name), "Empty", None))
        if method == "PATCH":
            return _json(200, _pkg_view(pkg))    # packages have no mutable fields in v1
    if rest[1] == "versions":
        return _versions(store, method, repo_name, repo, pkg, rest[2:], query, body)
    if rest[1] == "tags":
        return _tags(store, method, pkg, rest[2:], query, body)
    return _err(404, "Unknown path.")


def _pl(repo_name: str):
    p = repo_name.split("/")
    return p[1], p[3]


def _versions(store, method, repo_name, repo, pkg, rest, query, body) -> GcpResponse:
    if not rest:
        if method == "GET":
            items = [_ver_view(v) for _, v in sorted(pkg["versions"].items())]
            return _json(200, _with_page("versions", items, query))
        return _err(400, f"Unsupported method {method} on versions collection.")
    if rest[0] == "batchDelete" and method == "POST":
        for vn in body.get("names") or []:
            vid = vn.rsplit("/", 1)[-1]
            if vid not in pkg["versions"]:
                return _err(404, f"Version \"{vn}\" not found.")
        for vn in body.get("names") or []:
            _drop_version(pkg, vn.rsplit("/", 1)[-1])
        store.persist()
        return _json(200, _operation(store, *_pl(repo_name), "Empty", None))
    vid = rest[0]
    ver = pkg["versions"].get(vid)
    if ver is None:
        return _err(404, f"Version \"{pkg['name']}/versions/{vid}\" not found.")
    if method == "GET":
        return _json(200, _ver_view(ver))
    if method == "DELETE":
        _drop_version(pkg, vid)
        store.persist()
        return _json(200, _operation(store, *_pl(repo_name), "Empty", None))
    return _err(400, f"Unsupported method {method} on version.")


def _drop_version(pkg: dict, vid: str) -> None:
    ver = pkg["versions"].pop(vid, None)
    for t in (ver or {}).get("_tags", []):
        pkg["tags"].pop(t["name"].rsplit("/", 1)[-1], None)


def _tags(store, method, pkg, rest, query, body) -> GcpResponse:
    if not rest:
        if method == "GET":
            return _json(200, _with_page("tags", [_tag_view(t) for _, t in sorted(pkg["tags"].items())], query))
        if method == "POST":
            tid = query.get("tagId") or query.get("tag_id") or ""
            if not tid:
                return _err(400, "tagId is required (query parameter).")
            if tid in pkg["tags"]:
                return _err(409, f"Tag \"{pkg['name']}/tags/{tid}\" already exists.")
            ver = _tag_target(pkg, body)
            if ver is None:
                return _err(404, f"Version \"{body.get('version', '')}\" not found.")
            t = _set_tag(pkg, tid, ver)
            store.persist()
            return _json(200, _tag_view(t))
        return _err(400, f"Unsupported method {method} on tags collection.")
    tid = rest[0]
    t = pkg["tags"].get(tid)
    if t is None:
        return _err(404, f"Tag \"{pkg['name']}/tags/{tid}\" not found.")
    if method == "GET":
        return _json(200, _tag_view(t))
    if method == "DELETE":
        for v in pkg["versions"].values():
            v["_tags"] = [x for x in v.get("_tags", []) if x["name"] != t["name"]]
        del pkg["tags"][tid]
        store.persist()
        return _json(200, {})
    if method == "PATCH":
        ver = _tag_target(pkg, body)
        if ver is None:
            return _err(404, f"Version \"{body.get('version', '')}\" not found.")
        return _json(200, _tag_view(_set_tag(pkg, tid, ver)))
    return _err(400, f"Unsupported method {method} on tag.")


def _tag_target(pkg: dict, body: dict):
    vid = (body.get("version") or "").rsplit("/", 1)[-1]
    return pkg["versions"].get(vid)


# ── docker images / files ─────────────────────────────────────────────────
def _images(store, method, repo_name, rest, query) -> GcpResponse:
    repo, _, err = _find(store, repo_name)
    if err:
        return err
    project, loc = _pl(repo_name)
    rid = repo_name.rsplit("/", 1)[-1]
    images = [_image_view(project, loc, rid, p, v)
              for _, p in sorted(repo["packages"].items()) for _, v in sorted(p["versions"].items())] \
        if repo["format"] == "DOCKER" else []
    if not rest:
        return _json(200, _with_page("dockerImages", images, query))
    want = "/".join(rest)
    from urllib.parse import unquote
    want = unquote(want)
    for im in images:
        if im["name"].rsplit("/dockerImages/", 1)[-1] == want:
            return _json(200, im)
    return _err(404, f"DockerImage \"{repo_name}/dockerImages/{want}\" not found.")


def _files(store, method, repo_name, rest, query) -> GcpResponse:
    repo, _, err = _find(store, repo_name)
    if err:
        return err
    files = {f["name"].rsplit("/", 1)[-1]: (p, v, f) for p in repo["packages"].values()
             for v in p["versions"].values() for f in v["files"].values()}
    if not rest:
        flt = query.get("filter") or ""
        items = [{k: f[k] for k in ("name", "sizeBytes", "hashes", "createTime", "updateTime", "owner")}
                 for _, (_, _, f) in sorted(files.items())]
        if flt.startswith("owner="):
            owner = flt[len("owner="):].strip('"')
            items = [f for f in items if f["owner"] == owner]
        return _json(200, _with_page("files", items, query))
    fid = rest[0]
    hit = files.get(fid)
    if hit is None:
        return _err(404, f"File \"{repo_name}/files/{fid}\" not found.")
    p, v, f = hit
    if method == "DELETE":
        v["files"].pop(fid, None)
        store.persist()
        return _json(200, _operation(store, *_pl(repo_name), "Empty", None))
    return _json(200, {k: f[k] for k in ("name", "sizeBytes", "hashes", "createTime", "updateTime", "owner")})


# ── locations / operations ────────────────────────────────────────────────
def _location(project: str, loc: str) -> dict:
    return {"name": f"projects/{project}/locations/{loc}", "locationId": loc,
            "displayName": loc, "labels": {"cloud.googleapis.com/region": loc}}


# ── console (UI) facade — flat rows, the same engine ──────────────────────
def console_row(repo: dict) -> dict:
    """A flat console row: every grid column is filled."""
    parts = repo["name"].split("/")
    return {
        "name": parts[-1], "resourceName": repo["name"], "location": parts[3],
        "format": repo["format"], "mode": repo["mode"].replace("_REPOSITORY", "").title(),
        "description": repo.get("description") or "No description",
        "encryption": "Customer-managed" if repo.get("kmsKeyName") else "Google-managed",
        "created": repo["createTime"], "updated": repo["updateTime"],
        "size": _human(_size(repo)), "sizeBytes": _size(repo),
        "labels": repo.get("labels") or {},
        "packages": len(repo["packages"]),
        "artifacts": sum(len(p["versions"]) for p in repo["packages"].values()),
        "state": "ACTIVE",
    }


def _human(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    for unit in ("KB", "MB", "GB"):
        n /= 1024
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}"
    return f"{n} B"


def console_list(store: ArtifactRegistryStore) -> list:
    return [console_row(r) for _, r in sorted(store.repos.items())]


def console_create(store: ArtifactRegistryStore, project: str, body: dict) -> dict:
    name = str(body.get("name") or "").strip()
    loc = str(body.get("location") or body.get("__region__") or "us-central1")
    r = dispatch(store, "POST", f"/v1/projects/{project}/locations/{loc}/repositories",
                 {"repositoryId": name}, {}, json.dumps({
                     "format": body.get("format") or "DOCKER",
                     "mode": body.get("mode") or "STANDARD_REPOSITORY",
                     "description": body.get("description") or "",
                     "labels": body.get("labels") or {}}).encode())
    if r.status >= 300:
        err = json.loads(r.body)["error"]
        return {"ok": False, "code": "AlreadyExists" if r.status == 409 else "InvalidArgument",
                "name": name, "message": err["message"]}
    return {"ok": True, **console_row(store.repos[_repo_name(project, loc, name)])}


def console_find(store: ArtifactRegistryStore, name: str):
    for n, r in store.repos.items():
        if n.rsplit("/", 1)[-1] == name or n == name:
            return n, r
    return None, None


def console_update(store: ArtifactRegistryStore, name: str, body: dict) -> dict:
    """Console Labels edit → repositories.patch (updateMask=labels)."""
    full, repo = console_find(store, name)
    if repo is None:
        return {"ok": False, "code": "NotFound", "name": name}
    labels = body.get("labels") or {}
    repo["labels"] = {str(k): str(v) for k, v in labels.items()} if isinstance(labels, dict) else {}
    repo["updateTime"] = _now()
    store.persist()
    return {"ok": True, **console_row(repo)}


def console_delete(store: ArtifactRegistryStore, name: str) -> dict:
    full, _ = console_find(store, name)
    if full is None:
        return {"ok": False, "code": "NotFound", "name": name}
    store.repos.pop(full)
    store.iam.pop(full, None)
    store.persist()
    return {"ok": True, "code": None, "name": name}


def console_children(store: ArtifactRegistryStore, name: str, kind: str) -> list:
    """Rows for the detail tabs: kind in packages | versions | tags | images."""
    full, repo = console_find(store, name)
    if repo is None:
        return []
    project, loc = _pl(full)
    rid = full.rsplit("/", 1)[-1]
    out = []
    for p in sorted(repo["packages"].values(), key=lambda x: x["name"]):
        if kind == "packages":
            out.append({"name": p["displayName"], "versions": len(p["versions"]), "tags": len(p["tags"]),
                        "created": p["createTime"], "updated": p["updateTime"]})
        for v in sorted(p["versions"].values(), key=lambda x: x["name"]):
            if kind == "versions":
                out.append({"name": v["name"].rsplit("/", 1)[-1], "package": p["displayName"],
                            "tags": ", ".join(t["name"].rsplit("/", 1)[-1] for t in v["_tags"]) or "none",
                            "size": _human(int(v.get("sizeBytes", 0))), "created": v["createTime"]})
            if kind == "images" and repo["format"] == "DOCKER":
                im = _image_view(project, loc, rid, p, v)
                out.append({"name": p["displayName"], "digest": v["name"].rsplit("/", 1)[-1],
                            "tags": ", ".join(im["tags"]) or "none", "uri": im["uri"],
                            "size": _human(int(v.get("sizeBytes", 0))), "uploaded": im["uploadTime"]})
        if kind == "tags":
            for t in p["tags"].values():
                out.append({"name": t["name"].rsplit("/", 1)[-1], "package": p["displayName"],
                            "version": t["version"].rsplit("/", 1)[-1]})
    return out


def console_push_sample(store: ArtifactRegistryStore, name: str, body: dict | None = None) -> dict:
    full, repo = console_find(store, name)
    if repo is None:
        return {"ok": False, "code": "NotFound", "name": name}
    body = body or {}
    if repo["format"] == "DOCKER":
        ver = ingest_image(store, full, str(body.get("image") or "sample-app"), str(body.get("tag") or "latest"))
    else:
        ver = ingest_package(store, full, str(body.get("image") or "sample-package"),
                             str(body.get("tag") or "1.0.0"), 1024 * 1024, [])
    return {"ok": True, "name": name, "version": ver["name"]}


_VERBS = ("getIamPolicy", "setIamPolicy", "testIamPermissions", "batchDelete")


# ── dispatch ──────────────────────────────────────────────────────────────
def dispatch(store: ArtifactRegistryStore, method: str, path: str,
             query: dict | None = None, headers: dict | None = None,
             body: bytes = b"") -> GcpResponse:
    query = query or {}
    method = method.upper()
    for k, v in (headers or {}).items():     # Java's HttpURLConnection has no PATCH: gax overrides POST
        if k.lower() == "x-http-method-override" and v:
            method = str(v).upper()
    try:
        payload = json.loads(body.decode("utf-8")) if body else {}
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    p = path.split("?", 1)[0]
    for pre in ("/v1beta2", "/v1"):
        if p.startswith(pre + "/") or p == pre:
            p = p[len(pre):]
            break
    p = p.strip("/")
    verb = ""
    if ":" in p and p.rsplit(":", 1)[1] in _VERBS:    # docker digests (sha256:…) contain ':' too
        p, verb = p.rsplit(":", 1)
    segs = [s for s in p.split("/") if s]
    if verb == "batchDelete":
        segs.append("batchDelete")

    # projects/{p}/locations[/{l}[/operations/{id}|/repositories...]]
    if len(segs) < 2 or segs[0] != "projects":
        return _err(404, f"Unknown path: {path}")
    project = segs[1]
    if len(segs) == 2:
        return _err(404, f"Unknown path: {path}")
    if segs[2] != "locations":
        return _err(404, f"Unknown path: {path}")
    if len(segs) == 3:
        if method == "GET":
            locs = [_location(project, l) for l in LOCATIONS]
            return _json(200, _with_page("locations", locs, query))
        return _err(400, f"Unsupported method {method} on locations.")
    loc = segs[3]
    if len(segs) == 4:
        return _json(200, _location(project, loc)) if method == "GET" else _err(400, "Unsupported method.")
    kind = segs[4]
    if kind == "operations":
        if len(segs) == 6 and method == "GET":
            op = store.operations.get("/".join(segs[:6]))
            return _json(200, op) if op else _err(404, f"Operation \"{'/'.join(segs[:6])}\" not found.")
        return _err(404, f"Unknown path: {path}")
    if kind != "repositories":
        return _err(404, f"Unknown path: {path}")
    if len(segs) == 5:
        if method == "POST":
            return _create_repo(store, project, loc, query, payload)
        if method == "GET":
            return _list_repos(store, project, loc, query)
        return _err(400, f"Unsupported method {method} on repositories.")
    rname = _repo_name(project, loc, segs[5])
    rest = segs[6:]
    if not rest:
        if verb in ("getIamPolicy", "setIamPolicy", "testIamPermissions"):
            return _iam(store, method, rname, verb, payload)
        if method == "GET":
            return _get_repo(store, rname)
        if method == "PATCH":
            return _patch_repo(store, rname, query, payload)
        if method == "DELETE":
            return _delete_repo(store, project, loc, rname)
        return _err(400, f"Unsupported method {method} on repository.")
    if rest[0] == "packages":
        return _packages(store, method, rname, rest[1:], query, payload)
    if rest[0] == "dockerImages":
        return _images(store, method, rname, rest[1:], query)
    if rest[0] == "files":
        return _files(store, method, rname, rest[1:], query)
    return _err(404, f"Unknown path: {path}")
