"""GCP project identity — every GCP space is ONE project, like real GCP.

A project has a project ID (lowercase, 6-30 chars, starts with a letter, e.g.
`vyomi-project`) and a project number. The number is the space's
`active_account` (123456789012 by default), so everything stored under it before
projects had an ID stays reachable — real GCP APIs take either the ID or the
number for the same project.

One seam normalizes every GCP request to the project ID before any handler runs
(`normalize_request`, called from core/middleware.py): the `projects/{p}` path
segment, the `?project=` / `?parent=` query params, and `projects/{p}/...`
references inside JSON bodies. The number — and the ids earlier releases used
(`cloudlearn`, `demo`, `gcp-dev`; their data is migrated by `migrate_state` /
`migrate_backends`) — resolve to the ID. Any other project gets the error the
real API returns for a project that doesn't exist.

Cloud Resource Manager (`gcloud projects list/describe`) serves the same project:
see routes/gcp_resourcemanager.py.
"""
from __future__ import annotations

import hashlib
import re
import threading
import time

DEFAULT_PROJECT_ID = "vyomi-project"
DEFAULT_PROJECT_NUMBER = "123456789012"
# Nano has one in-browser substrate, so one fixed project (its catalog project).
NANO_PROJECT = {"projectId": "nano-project", "projectNumber": DEFAULT_PROJECT_NUMBER,
                "name": "Nano GCP", "createTime": ""}
# Project ids earlier releases used or defaulted to (console "cloudlearn",
# Nano/expansion consoles "demo", the CLI suites + SDK snippets "gcp-dev").
LEGACY_PROJECT_IDS = ("cloudlearn", "demo", "gcp-dev")
# `projects/-` (any project) and `projects/_` (GCS global namespace).
_WILDCARDS = ("-", "_")

_ID_RE = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
_PATH_PROJECT_RE = re.compile(r"(/projects/)([^/:?]+)")
_STORAGE_PREFIXES = ("/storage/", "/upload/storage/", "/download/storage/", "/api/gcp/storage/")


def valid_project_id(value: str) -> bool:
    return bool(_ID_RE.match(str(value or "")))


def _ctx():
    # The appliance's state (spaces, tenants). Imported lazily: the pure helpers
    # below (normalize / resolve / Resource Manager views) also run in Nano.
    from core import app_context
    return app_context


# ── the space ↔ project mapping ─────────────────────────────────────────────

def _spaces() -> dict:
    return _ctx().spaces_state().get("spaces", {})


def gcp_space() -> dict:
    """The live GCP space GCP requests read and write — the same space the
    space-scoped state proxies resolve: the active space when it is a GCP space
    of the active tenant, else the tenant's first GCP space."""
    ss = _ctx().spaces_state()
    tid = _ctx().active_tenant_id()
    spaces = ss.get("spaces", {})
    active = spaces.get(ss.get("active_space_id", "")) or {}

    def _mine(s):
        return (isinstance(s, dict) and str(s.get("provider") or "aws").lower() == "gcp"
                and (s.get("tenant_id") or _ctx().DEFAULT_TENANT_ID) == tid)

    if _mine(active):
        return active
    for s in spaces.values():
        if _mine(s):
            return s
    return {}


def _project_number_for(space: dict) -> str:
    acct = str(space.get("active_account") or "").strip()
    if acct.isdigit():
        return acct
    digest = int(hashlib.sha1(str(space.get("space_id") or space.get("name") or "").encode()).hexdigest(), 16)
    return str(100000000000 + digest % 900000000000)


def _project_id_for(space: dict) -> str:
    taken = {str(s.get("gcp_project_id")) for s in _spaces().values()
             if isinstance(s, dict) and s is not space and s.get("gcp_project_id")}
    candidates = [DEFAULT_PROJECT_ID]
    slug = re.sub(r"[^a-z0-9-]+", "-", str(space.get("name") or "").lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    if slug and not slug[0].isalpha():
        slug = "p-" + slug
    slug = slug[:30].rstrip("-")
    if valid_project_id(slug):
        candidates.append(slug)
    candidates += [f"{DEFAULT_PROJECT_ID}-{n}" for n in range(2, 100)]
    return next(c for c in candidates if c not in taken)


def ensure_identity(space: dict) -> tuple[str, str]:
    """(project_id, project_number) of a GCP space, assigned once and stored on
    the space (`gcp_project_id` / `gcp_project_number`) so they stay stable."""
    if not isinstance(space, dict) or not space:
        return DEFAULT_PROJECT_ID, DEFAULT_PROJECT_NUMBER
    pid, num = space.get("gcp_project_id"), space.get("gcp_project_number")
    if not (pid and valid_project_id(pid)):
        pid = space["gcp_project_id"] = _project_id_for(space)
    if not (num and str(num).isdigit()):
        num = space["gcp_project_number"] = _project_number_for(space)
    return str(pid), str(num)


def current() -> dict:
    """The GCP space's project as {projectId, projectNumber, name, createTime}."""
    space = gcp_space()
    pid, num = ensure_identity(space)
    return {"projectId": pid, "projectNumber": num,
            "name": str(space.get("name") or pid) if space else pid,
            "createTime": str(space.get("created_at") or "") if space else ""}


def resolve(value, proj: dict | None = None) -> str:
    """The project ID for a project ID / number / legacy id of `proj` (default:
    the GCP space's project), '' if unknown. Empty → the project."""
    v = str(value or "").strip()
    if v.startswith("projects/"):
        v = v[len("projects/"):].split("/", 1)[0]
    proj = proj or current()
    if not v or v in (proj["projectId"], proj["projectNumber"]) or v in LEGACY_PROJECT_IDS:
        return proj["projectId"]
    return ""


def project_id() -> str:
    return current()["projectId"]


# ── request normalization (the one seam) ────────────────────────────────────

def _is_public_image_project(path: str) -> bool:
    # gcloud/terraform read public images from Google's image projects
    # (debian-cloud, ubuntu-os-cloud, cos-cloud, ...).
    return bool(re.search(r"/compute/v1/projects/[^/]+/global/images", path))


def unknown_project_error(path: str, method: str, project: str) -> tuple[int, dict]:
    """What the real API returns for a project that doesn't exist (or that the
    caller can't see — GCP doesn't tell the two apart)."""
    p = project
    if path.startswith(("/compute/", "/api/gcp/compute/")):
        msg = f"The resource 'projects/{p}' was not found"
        return 404, {"error": {"code": 404, "message": msg,
                               "errors": [{"message": msg, "domain": "global", "reason": "notFound"}]}}
    if path.startswith(_STORAGE_PREFIXES):
        msg = ("The caller does not have storage.buckets.list access to the Google Cloud project. "
               "Permission 'storage.buckets.list' denied on resource (or it may not exist).")
        return 403, {"error": {"code": 403, "message": msg,
                               "errors": [{"message": msg, "domain": "global", "reason": "forbidden"}]}}
    if re.search(r"/(topics|subscriptions|snapshots|schemas)(/|$|:)", path) or path.startswith(("/pubsub/", "/api/gcp/pubsub/")):
        return 404, {"error": {"code": 404, "status": "NOT_FOUND", "message": (
            f"Requested project not found or user does not have access to it (project={p}). "
            "Make sure to specify the unique project identifier and not the Google Cloud Console display name.")}}
    if re.match(r"^/v[13]/projects/[^/]+$", path):
        return 403, {"error": {"code": 403, "status": "PERMISSION_DENIED",
                               "message": "The caller does not have permission"}}
    if "/secrets" in path:
        verb = {"GET": "list" if path.rstrip("/").endswith("/secrets") else "get",
                "POST": "create", "DELETE": "delete"}.get(method, "update")
        return 403, {"error": {"code": 403, "status": "PERMISSION_DENIED", "message": (
            f"Permission 'secretmanager.secrets.{verb}' denied for resource 'projects/{p}' (or it may not exist).")}}
    return 403, {"error": {"code": 403, "status": "PERMISSION_DENIED",
                           "message": f"Permission denied on resource project {p}.",
                           "details": [{"@type": "type.googleapis.com/google.rpc.ErrorInfo",
                                        "reason": "CONSUMER_INVALID", "domain": "googleapis.com",
                                        "metadata": {"consumer": f"projects/{p}"}}]}}


def _old_ids(proj: dict) -> list[str]:
    return [x for x in (proj["projectNumber"], *LEGACY_PROJECT_IDS) if x and x != proj["projectId"]]


def _alt(old) -> str:
    return "|".join(re.escape(x) for x in sorted(old, key=len, reverse=True))


def _swap_refs(text: str, alt: str, pid: str) -> str:
    """`projects/{old}` → `projects/{pid}`, and service-account emails
    `{sa}@{old}.iam.gserviceaccount.com` → `{sa}@{pid}.iam.gserviceaccount.com`."""
    if "projects/" in text:
        text = re.sub(r"(projects/)(%s)(?=[/\"':]|$)" % alt, lambda m: m.group(1) + pid, text)
    if ".iam.gserviceaccount.com" in text:
        text = re.sub(r"(@|%%40)(%s)(?=\.iam\.gserviceaccount\.com)" % alt, lambda m: m.group(1) + pid, text)
    return text


def rewrite_body(body: bytes, proj: dict | None = None) -> bytes:
    """`projects/{number|legacy id}` references, service-account emails and
    "project"/"projectId" fields inside a JSON body → the project ID."""
    proj = proj or current()
    try:
        text = body.decode("utf-8")
    except Exception:
        return body
    alt = _alt(_old_ids(proj))
    if not alt or not re.search(alt, text):
        return body
    pid = proj["projectId"]
    out = _swap_refs(text, alt, pid)
    out = re.sub(r"(\"project(?:Id)?\"\s*:\s*\")(%s)(\")" % alt, lambda m: m.group(1) + pid + m.group(3), out)
    return out.encode("utf-8") if out != text else body


def normalize_request(path: str, query, method: str, proj: dict | None = None):
    """Map a GCP request's project onto the project ID.

    `query` is the raw query string or a dict of params (returned the same way).
    Returns (path, query, None) with the project rewritten, or
    (path, query, (status, error_body)) for an unknown project."""
    from urllib.parse import parse_qsl, urlencode
    proj = proj or current()
    if not path.startswith(_STORAGE_PREFIXES):
        m = _PATH_PROJECT_RE.search(path)
        if m and m.group(2) not in _WILDCARDS and not _is_public_image_project(path):
            got = resolve(m.group(2), proj)
            if not got:
                return path, query, unknown_project_error(path, method, m.group(2))
            if got != m.group(2):
                path = path[:m.start(2)] + got + path[m.end(2):]
            if ".iam.gserviceaccount.com" in path:
                path = _swap_refs(path, _alt(_old_ids(proj)), proj["projectId"])
    as_dict = isinstance(query, dict)
    pairs = list(query.items()) if as_dict else parse_qsl(query or "", keep_blank_values=True)
    changed = False
    for i, (k, v) in enumerate(pairs):
        v = str(v)
        if k == "project" and v:
            got = resolve(v, proj)
            if not got:
                return path, query, unknown_project_error(path, method, v)
            if got != v:
                pairs[i], changed = (k, got), True
        elif k == "parent" and v.startswith("projects/"):
            cur = v[len("projects/"):].split("/", 1)[0]
            got = resolve(cur, proj) if cur not in _WILDCARDS else cur
            if got and got != cur:
                pairs[i], changed = (k, "projects/" + got + v[len("projects/") + len(cur):]), True
    if changed:
        query = dict(pairs) if as_dict else urlencode(pairs)
    return path, query, None


# ── Cloud Resource Manager views of the project ─────────────────────────────

def crm_v1(p: dict) -> dict:
    out = {"projectNumber": p["projectNumber"], "projectId": p["projectId"],
           "lifecycleState": "ACTIVE", "name": p["name"]}
    if p.get("createTime"):
        out["createTime"] = p["createTime"]
    return out


def crm_v3(p: dict) -> dict:
    out = {"name": f"projects/{p['projectNumber']}", "projectId": p["projectId"],
           "state": "ACTIVE", "displayName": p["name"], "etag": f"W/\"{p['projectNumber']}\""}
    if p.get("createTime"):
        out["createTime"] = out["updateTime"] = p["createTime"]
    return out


def crm_matches(p: dict, flt: str) -> bool:
    """The filter terms gcloud / the client libraries send: lifecycleState / state,
    id / projectId, name / displayName (exact or `*` wildcard), projectNumber."""
    for key, val in re.findall(r"([A-Za-z.]+)\s*[:=]\s*\"?([^\s\"]+)\"?", flt or ""):
        key, val = key.lower(), val.strip()
        have = {"lifecyclestate": "ACTIVE", "state": "ACTIVE", "id": p["projectId"],
                "projectid": p["projectId"], "name": p["name"], "displayname": p["name"],
                "projectnumber": p["projectNumber"]}.get(key)
        if have is None:
            continue
        if not re.fullmatch(re.escape(val).replace(r"\*", ".*"), have, re.I):
            return False
    return True


CRM_PATH_RE = re.compile(r"^/v[13]/projects(:search|/[^/:]+)?$")


def crm_dispatch(method: str, path: str, query: dict, proj: dict | None = None) -> tuple[int, dict]:
    """Cloud Resource Manager v1 / v3 reads of the project: GET /v1/projects,
    /v1/projects/{p}, /v3/projects/{p}, /v3/projects?parent=, /v3/projects:search.
    {p} may be the project ID or number."""
    proj = proj or current()
    query = query or {}
    if method != "GET":
        return 405, {"error": {"code": 405, "status": "UNIMPLEMENTED", "message": "Method not allowed"}}
    v1 = path.startswith("/v1/")
    tail = path.split("/projects", 1)[1]
    if tail.startswith("/"):
        if resolve(tail[1:], proj) != proj["projectId"]:
            return 403, {"error": {"code": 403, "status": "PERMISSION_DENIED",
                                   "message": "The caller does not have permission"}}
        return 200, crm_v1(proj) if v1 else crm_v3(proj)
    if v1:
        return 200, {"projects": [crm_v1(proj)] if crm_matches(proj, query.get("filter", "")) else []}
    if tail == ":search":
        return 200, {"projects": [crm_v3(proj)] if crm_matches(proj, query.get("query", "")) else []}
    if not query.get("parent"):
        return 400, {"error": {"code": 400, "status": "INVALID_ARGUMENT",
                               "message": "Request contains an invalid argument.",
                               "details": [{"@type": "type.googleapis.com/google.rpc.BadRequest",
                                            "fieldViolations": [{"field": "parent",
                                                                 "description": "parent is required"}]}]}}
    # The project has no organization or folder above it.
    return 200, {"projects": []}


# ── migration of data created under the number / legacy ids ─────────────────

def rewrite_tree(node, old: set, pid: str):
    """Rewrite a JSON-safe tree: dict keys and string values carrying
    `projects/{old}` or `@{old}.iam.gserviceaccount.com`, and
    "project"/"projectId" fields equal to an old id."""
    alt = _alt(old)

    def fix_str(s):
        return _swap_refs(s, alt, pid)

    def walk(x):
        if isinstance(x, dict):
            for k in list(x.keys()):
                v = x[k]
                if k in ("project", "projectId") and isinstance(v, str) and v in old:
                    v = pid
                else:
                    v = walk(v)
                nk = fix_str(k) if isinstance(k, str) else k
                if nk != k:
                    del x[k]
                    x.setdefault(nk, v)
                else:
                    x[k] = v
            return x
        if isinstance(x, list):
            for i, v in enumerate(x):
                x[i] = walk(v)
            return x
        if isinstance(x, str):
            return fix_str(x)
        return x

    return walk(node)


def _merge_project_keys(by_project: dict, old: set, pid: str) -> None:
    """{old_id: {...}} entries of a per-project map folded into {pid: {...}}."""
    for o in [k for k in by_project if k in old]:
        val = by_project.pop(o)
        cur = by_project.get(pid)
        if not isinstance(cur, dict) or not isinstance(val, dict):
            by_project.setdefault(pid, val)
            continue
        for k, v in val.items():
            if k == "bindings" and isinstance(v, list) and isinstance(cur.get(k), list):
                cur[k] += [b for b in v if b not in cur[k]]
            elif isinstance(v, dict) and isinstance(cur.get(k), dict):
                for kk, vv in v.items():
                    cur[k].setdefault(kk, vv)
            else:
                cur.setdefault(k, v)


def migrate_state() -> int:
    """Give every GCP space its project ID + number and move its stored GCP
    resources from the number / legacy ids onto the ID. Idempotent (marker on
    the space). Returns how many spaces were migrated."""
    n = 0
    # The default GCP space first, so it is the one that gets `vyomi-project`.
    for space in sorted(_spaces().values(), key=lambda s: not (isinstance(s, dict) and s.get("space_id") == "space-gcp-default")):
        if not (isinstance(space, dict) and str(space.get("provider") or "").lower() == "gcp"):
            continue
        pid, num = ensure_identity(space)
        if space.get("gcp_project_migrated"):
            continue
        old = {num, *LEGACY_PROJECT_IDS} - {pid}
        states = space.get("service_states") or {}
        # Maps keyed by the bare project id: IAM's per-project collections and
        # the console API Gateway's service_states["apigateway"][project].
        iam = states.get("gcp_iam") if isinstance(states.get("gcp_iam"), dict) else {}
        for coll in [iam.get(c) for c in _ctx()._GCP_IAM_NESTED_COLLECTIONS] + [states.get("apigateway")]:
            if isinstance(coll, dict):
                _merge_project_keys(coll, old, pid)
        for key, svc_state in states.items():
            if (str(key).startswith("gcp_") or key == "apigateway") and isinstance(svc_state, (dict, list)):
                rewrite_tree(svc_state, old, pid)
        space["gcp_project_migrated"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        n += 1
    return n


def _default_target() -> dict:
    """The project the shared emulators' old-id data moves into: the default
    tenant's GCP space (the emulators are appliance-wide, not per space)."""
    spaces = _spaces()
    sp = spaces.get("space-gcp-default")
    if not (isinstance(sp, dict) and str(sp.get("provider") or "").lower() == "gcp"):
        sp = next((s for s in spaces.values() if isinstance(s, dict)
                   and str(s.get("provider") or "").lower() == "gcp"
                   and (s.get("tenant_id") or _ctx().DEFAULT_TENANT_ID) == _ctx().DEFAULT_TENANT_ID), {})
    return sp


def migrate_pubsub(target: str, old: list[str]) -> dict:
    """Copy topics + subscriptions from old project ids onto `target` in the
    Pub/Sub emulator (copy, never delete; existing ones are left alone).
    Undelivered messages are not copied."""
    from core import gcp_pubsub_emulator as pe
    if not pe.available():
        return {"skipped": "emulator not configured"}
    from google.api_core import exceptions as gax
    topics = subs = 0
    for src in old:
        try:
            src_topics = pe.list_topics(src)
            src_subs = pe.list_subscriptions(src)
        except Exception:
            continue
        for t in src_topics:
            try:
                pe.create_topic(target, t["name"], t.get("labels") or None)
                topics += 1
            except gax.AlreadyExists:
                pass
            except Exception:
                pass
        for s in src_subs:
            name = str(s.get("name") or "").split("/")[-1]
            topic = str(s.get("topic") or "").split("/")[-1]
            if not name or not topic:
                continue
            try:
                pe.create_subscription(target, name, topic, int(s.get("ackDeadlineSeconds") or 10))
                subs += 1
            except gax.AlreadyExists:
                pass
            except Exception:
                pass
    return {"topics": topics, "subscriptions": subs}


def migrate_firestore(target: str, old: list[str], databases: list[str]) -> dict:
    """Copy every document (all collections, all depths) from old project ids
    onto `target` in the Firestore emulator; target documents that already exist
    are not overwritten."""
    from core import gcp_firestore_emulator as fe
    if not fe.available():
        return {"skipped": "emulator not configured"}
    docs = 0

    def copy_coll(src_coll, dst_client, prefix):
        nonlocal docs
        for snap in src_coll.list_documents(page_size=500):
            path = f"{prefix}{src_coll.id}/{snap.id}"
            got = snap.get()
            dst = dst_client.document(path)
            if got.exists and not dst.get().exists:
                dst.set(got.to_dict() or {})
                docs += 1
            for sub in snap.collections():
                copy_coll(sub, dst_client, path + "/")

    for db in databases or ["(default)"]:
        dst_client = fe._client(target, db)
        for src in old:
            try:
                src_client = fe._client(src, db)
                for coll in src_client.collections():
                    copy_coll(coll, dst_client, "")
            except Exception:
                continue
    return {"documents": docs}


def migrate_backends(wait_s: float = 120.0) -> dict:
    """One-time copy of the shared emulators' old-id data (Pub/Sub topics +
    subscriptions, Firestore documents) onto the default GCP project. Runs in
    a background thread at boot; the outcome is recorded in
    STATE["runtime"]["gcp_project_migration"]."""
    state = _ctx().STATE.setdefault("runtime", {})
    if (state.get("gcp_project_migration") or {}).get("done"):
        return state["gcp_project_migration"]
    space = _default_target()
    if not space:
        return {}
    pid, num = ensure_identity(space)
    old = [x for x in (num, *LEGACY_PROJECT_IDS) if x != pid]
    dbs = sorted({str(k).split("/")[-1] for k in
                  ((space.get("service_states") or {}).get("gcp_firestore") or {}).get("databases", {})} | {"(default)"})
    result: dict = {"target": pid, "from": old}
    deadline = time.time() + wait_s
    for name, fn in (("pubsub", lambda: migrate_pubsub(pid, old)),
                     ("firestore", lambda: migrate_firestore(pid, old, dbs))):
        while True:
            try:
                result[name] = fn()
                break
            except Exception as e:   # emulator still starting
                if time.time() > deadline:
                    result[name] = {"error": str(e)[:200]}
                    break
                time.sleep(5)
    result["done"] = all("error" not in (result.get(k) or {}) for k in ("pubsub", "firestore"))
    result["at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    state["gcp_project_migration"] = result
    try:
        _ctx().persist_state()
    except Exception:
        pass
    return result


def migrate_backends_async() -> None:
    threading.Thread(target=migrate_backends, daemon=True, name="gcp-project-migration").start()
