"""v4 C0d — Firestore + Compute Engine on the offline appliance, ONE engine.

Native wire, served by the shared cores (the ones Nano and dev_server use) over the
appliance's space-scoped, persisted state (core/appliance_stores.py):

  * Firestore — /v1/projects/{p}/databases… (documents, :runQuery, :commit, :batchGet,
    the Admin plane: databases, indexes, fields, backups…) → core/gcp_firestore_core.py.
  * Compute Engine — /compute/v1|beta/projects/{p}/… routed by path exactly like
    core/aws_wire_router._gcp_service: networks / subnetworks / firewalls / routes /
    addresses → core/gcp_compute_core.py, everything else (instances, disks, images,
    snapshots, templates, groups, health checks, zones, machine types, operations…) →
    core/gcp_compute_instances_core.py.

Classic console paths are aliases onto the SAME stores (their pre-v4 JSON shapes kept
where a console depends on them): /firestore/v1/…, /api/gcp/firestore/v1/…,
/api/gcp/dynamodb/tables/…, /api/gcp/compute/v1/…, /api/gcp/vpc/….

Real VM lifecycle. A Compute instance on the offline appliance may be backed by a real
guest — a Docker / LXD / Multipass container that the pre-v4 handler launched
(server._gcp_compute_create_instance_instance + _queue_runtime_start_for_store). That
stays exactly as it was: the core holds the control-plane record (what every API and
console reads), and the pre-v4 runtime record in gcp_compute_state["instances"] — linked
from the core record by `_runtimeId` — is created, started, stopped, reset and terminated
here, through the same server.py functions the pre-v4 routes called (incl. the host
budget / disk / tier gates on insert). Console exec, connect-info, VPC firewall
enforcement and the host-resource meters keep reading that runtime record.

Opt-out: VYOMI_UNIFIED_INGRESS_SERVICES without gcp_firestore / gcp_compute (or
VYOMI_LEGACY_WIRE=1) leaves every path on the pre-v4 handlers.
"""
from __future__ import annotations

import json
import logging
from urllib.parse import unquote

from fastapi import Request, Response

from core import wire_ingress as _wi

_log = logging.getLogger("vyomi.engine")
_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"]


# ── helpers ──────────────────────────────────────────────────────────────────
def _raw_path(request: Request) -> str:
    raw = request.scope.get("raw_path")
    p = raw.decode("utf-8", "replace") if isinstance(raw, (bytes, bytearray)) and raw else \
        (request.scope.get("path") or request.url.path)
    p = p.split("?", 1)[0]
    if p.startswith("/_wire/"):        # the /_wire middleware rewrites `path`, not `raw_path`
        p = p[len("/_wire"):]
    return p


def _query(request: Request) -> dict:
    """Query params; a repeated key (updateMask.fieldPaths=a&…=b) keeps every value."""
    out: dict = {}
    for k, v in request.query_params.multi_items():
        if k in out:
            out[k] = (out[k] if isinstance(out[k], list) else [out[k]]) + [v]
        else:
            out[k] = v
    return out


def _resp(out: dict) -> Response:
    return _wi.to_response(out)


def _json_out(status: int, obj) -> dict:
    return {"status": status, "headers": {"content-type": "application/json"},
            "body": json.dumps(obj).encode()}


def _load(body: bytes):
    try:
        d = json.loads(body or b"{}")
    except Exception:
        return None
    return d


_GSTATUS = {400: "INVALID_ARGUMENT", 401: "UNAUTHENTICATED", 403: "PERMISSION_DENIED", 404: "NOT_FOUND",
            409: "ALREADY_EXISTS", 429: "RESOURCE_EXHAUSTED", 503: "UNAVAILABLE", 507: "RESOURCE_EXHAUSTED"}


def _gerr(status: int, message: str) -> dict:
    return _json_out(status, {"error": {"code": status, "message": message,
                                        "status": _GSTATUS.get(status, "FAILED_PRECONDITION")}})


def _default_project(request: Request | None = None) -> str:
    from core.app_context import gcp_project_name
    return gcp_project_name(request.query_params.get("project") if request is not None else None)


# ── Firestore ────────────────────────────────────────────────────────────────
def _is_typed(v) -> bool:
    return isinstance(v, dict) and len(v) == 1 and next(iter(v)).endswith("Value")


def _typed_fields(fields) -> dict:
    """Classic consoles may send plain JSON values; the pre-v4 handler typed them."""
    if not isinstance(fields, dict):
        return {}
    if all(_is_typed(v) for v in fields.values()):
        return fields
    import server
    return {k: (v if _is_typed(v) else server._gcp_firestore_value_from_json(v)) for k, v in fields.items()}


def _fs(method: str, path: str, query: dict | None = None, body: bytes = b"") -> dict:
    return _wi.dispatch_service("gcp_firestore", method, path, query or {},
                                {"content-type": "application/json"}, body)


def _fs_classic(method: str, native: str, query: dict, body: bytes) -> dict:
    """The pre-v4 console contract on /firestore/v1 + /api/gcp/firestore/v1 (and the
    /api/gcp/dynamodb/* aliases): body `name` as the database / document id, plain JSON
    field values, PATCH replaces the document, a root `…/documents` list of every
    document, `kind`/`nextPageToken` on lists, `{done,name}` on database delete."""
    segs = [unquote(s) for s in native.strip("/").split("/")]   # v1 projects p databases [d [documents …]]
    if len(segs) < 4 or segs[1] != "projects" or segs[3] != "databases":
        return _fs(method, native, query, body)
    project = segs[2]
    data = _load(body) if body else {}
    data = data if isinstance(data, dict) else {}
    if len(segs) == 4:                                       # …/databases
        if method == "POST" and not query.get("databaseId"):
            dbid = str(data.get("databaseId") or data.get("name") or "").rsplit("/", 1)[-1].strip()
            if not dbid:
                return _gerr(400, "database_id is required (query.databaseId or body.name)")
            query = dict(query, databaseId=dbid)
        out = _fs(method, native, query, body)
        if method == "GET" and out["status"] == 200:
            d = _load(out["body"]) or {}
            d.setdefault("databases", [])
            out = _json_out(200, d)
        return out
    dbid = segs[4]
    if len(segs) == 5 and method == "DELETE":
        out = _fs(method, native, query, body)
        return _json_out(200, {"done": True, "name": f"projects/{project}/databases/{dbid}"}) \
            if out["status"] == 200 else out
    if len(segs) >= 6 and segs[5].startswith("documents"):
        rest = "/".join(segs[6:])
        if segs[5] == "documents" and not rest and method == "GET":   # root list: every document
            from core import appliance_stores as aps
            from core import gcp_firestore_core as fc
            st = aps.gcp_firestore_store()
            st.adopt(project)
            base = f"projects/{project}/databases/{dbid}/documents"
            pre = f"{dbid}/"
            want = query.get("collectionId")
            docs = []
            for key in sorted(k for k in list(st.documents) if k.startswith(pre)):
                rel = key[len(pre):]
                if want and rel.rsplit("/", 2)[-2] != want:
                    continue
                docs.append(fc._doc_view(base, rel, st.documents[key]))
            return _json_out(200, {"documents": docs, "nextPageToken": "", "kind": "firestore#documents"})
        depth = len([s for s in rest.split("/") if s])
        if method == "POST" and depth % 2 == 1 and ":" not in rest:   # create document
            if not query.get("documentId") and (data.get("name") or data.get("documentId")):
                query = dict(query, documentId=str(data.get("documentId") or data.get("name")).rsplit("/", 1)[-1])
            body = json.dumps({"fields": _typed_fields(data.get("fields") or {})}).encode()
        elif method in ("PATCH", "PUT") and depth % 2 == 0 and depth:  # replace (pre-v4 + real-GCP semantics)
            fields = _typed_fields(data.get("fields") or {})
            body = json.dumps({"fields": fields}).encode()
            if "updateMask.fieldPaths" not in query:
                cur = _load(_fs("GET", native)["body"]) or {}
                keys = list(dict.fromkeys(list((cur.get("fields") or {}).keys()) + list(fields.keys())))
                query = dict(query, **{"updateMask.fieldPaths": [f"`{k}`" if "." in k else k for k in keys] or [""]})
        out = _fs(method, native, query, body)
        if method == "GET" and out["status"] == 200 and depth % 2 == 1:
            d = _load(out["body"]) or {}
            d.setdefault("documents", [])
            d.update(nextPageToken="", kind="firestore#documents")
            out = _json_out(200, d)
        return out
    if len(segs) >= 7 and segs[5] == "collectionGroups" and segs[-1] == "indexes" and method == "GET":
        out = _fs(method, native, query, body)
        d = (_load(out["body"]) or {}) if out["status"] == 200 else {}
        d.setdefault("indexes", [])
        d["kind"] = "firestore#indexList"
        return _json_out(200, d)
    return _fs(method, native, query, body)


async def _firestore_native(request: Request):
    return _resp(_fs(request.method, _raw_path(request), _query(request), await request.body()))


async def _firestore_classic(request: Request):
    path = _raw_path(request)
    native = path[len("/api/gcp/firestore"):] if path.startswith("/api/gcp/") else path[len("/firestore"):]
    return _resp(_fs_classic(request.method, native, _query(request), await request.body()))


async def _gcp_dynamodb_alias(request: Request):
    """/api/gcp/dynamodb/tables[/{collection}/items[/{id}]|/{collection}/query] — the pre-v4
    Firestore-as-tables alias (project / database from the query string)."""
    from urllib.parse import quote
    q = _query(request)
    project = _default_project(request)
    dbid = str(q.pop("database", "") or "(default)")
    q.pop("project", None)
    tail = [unquote(s) for s in _raw_path(request)[len("/api/gcp/dynamodb/tables"):].strip("/").split("/") if s]
    base = f"/v1/projects/{quote(project)}/databases/{quote(dbid)}/documents"
    body = await request.body()
    method = request.method
    if not tail:
        native = base
    elif len(tail) >= 2 and tail[1] == "items":
        native = base + "/" + "/".join(quote(t, safe="") for t in [tail[0]] + tail[2:3])
        method = "PATCH" if method == "PUT" else method
    elif len(tail) == 2 and tail[1] == "query":
        d = _load(body) or {}
        sq = d.setdefault("structuredQuery", {}) if isinstance(d, dict) else {}
        sq["from"] = [{"collectionId": tail[0]}]
        native, body, method = base + ":runQuery", json.dumps(d).encode(), "POST"
    else:
        return _resp(_gerr(404, "Unknown path"))
    return _resp(_fs_classic(method, native, q, body))


# ── Compute Engine ───────────────────────────────────────────────────────────
def _instance_target(method: str, native: str):
    """(project, zone, name, verb) for an instance call (verb "insert" for POST
    …/instances), else None. Accepts `/{name}/{verb}` and `/{name}:{verb}`."""
    segs = [s for s in native.split("?", 1)[0].strip("/").split("/") if s]
    if len(segs) < 7 or segs[0] != "compute" or segs[2] != "projects" or segs[4] != "zones" \
            or segs[6] != "instances":
        return None
    project, zone, rest = segs[3], segs[5], segs[7:]
    if not rest:
        return (project, zone, "", "insert") if method == "POST" else None
    name, verb = rest[0], ""
    if ":" in name:
        name, verb = name.split(":", 1)
    if len(rest) == 2 and not verb:
        verb = rest[1]
    if len(rest) > 2:
        return None
    if not verb:
        verb = {"DELETE": "delete"}.get(method, "")
    return (project, zone, name, verb) if verb else None


_LIVE_BACKENDS = ("docker", "lxd", "multipass")


def _runtime_live(rec: dict) -> bool:
    return str(rec.get("runtime_backend") or "").lower() in _LIVE_BACKENDS and rec.get("launch_status") != "error"


def _runtime_store():
    from core.app_context import gcp_compute_state
    return gcp_compute_state.setdefault("instances", {})


def _http_error(exc) -> dict:
    return _gerr(int(getattr(exc, "status_code", 500) or 500), str(getattr(exc, "detail", exc)))


def _insert_gates(payload: dict):
    """The host-budget / disk / tier gates the pre-v4 insert enforced (HTTPException)."""
    import server as s
    mt = str(payload.get("machineType") or "").rsplit("/", 1)[-1]
    boot = next((d for d in (payload.get("disks") or []) if isinstance(d, dict) and d.get("boot")),
                (payload.get("disks") or [{}])[0] if payload.get("disks") else {})
    size = (boot.get("initializeParams") or {}).get("diskSizeGb") if isinstance(boot, dict) else None
    s._check_budget_for_launch(mt, "gcp")
    s._disk_preflight(int(size or 10))
    s._enforce_quantity_cap("vm")
    s._enforce_size_cap("vm", "gcp", mt)


def _runtime_create(project: str, zone: str, payload: dict) -> str:
    """Create + launch the instance's real runtime exactly like the pre-v4 insert did."""
    import server as s
    disks = payload.get("disks") or []
    boot = next((d for d in disks if isinstance(d, dict) and d.get("boot")), disks[0] if disks else {}) or {}
    init = boot.get("initializeParams") or {}
    md = {str(i.get("key")): i.get("value", "") for i in ((payload.get("metadata") or {}).get("items") or [])
          if isinstance(i, dict) and i.get("key")}
    legacy = {
        "name": payload.get("name") or "gcp-instance",
        "machineType": str(payload.get("machineType") or "e2-medium").rsplit("/", 1)[-1],
        "sourceImage": str(init.get("sourceImage") or "sim-ubuntu-22.04").rsplit("/", 1)[-1],
        "bootDiskSizeGb": int(init.get("diskSizeGb") or 10),
        "bootDiskType": str(init.get("diskType") or "pd-balanced").rsplit("/", 1)[-1],
        "labels": payload.get("labels") or {},
        "tags": {"items": list((payload.get("tags") or {}).get("items") or [])},
        "startupScript": str(md.get("startup-script") or ""),
        "runtimeBackend": str(md.get("vyomi-runtime-backend") or ""),
        "assignExternalIp": any((ni or {}).get("accessConfigs") for ni in (payload.get("networkInterfaces") or [{}])),
    }
    req = s.GCPComputeInstanceRequest(**legacy)
    rec = s._gcp_compute_create_instance_instance(project, zone, req.model_dump() if hasattr(req, "model_dump") else req.dict())
    rec["metadata_items"] = md
    bundle = s._cloudsim_runtime_bundle("gcp_compute")
    rec["runtime_bundle_id"], rec["runtime_bundle_name"], rec["runtime_bundle_kind"] = (
        bundle.get("id", ""), bundle.get("name", ""), bundle.get("kind", ""))
    _runtime_store()[rec["instance_id"]] = rec
    s._cloudsim_sync_gcp_compute_resource(rec, "upsert")
    s._gcp_compute_queue_runtime_start(rec["instance_id"])
    s._record_usage("gcp.compute.create_instance", rec)
    return rec["instance_id"]


def _runtime_apply(verb: str, rec: dict, project: str, zone: str, payload: dict) -> None:
    """Drive the real runtime for a lifecycle verb (raises HTTPException on a failure of
    a live backend, so the caller can roll the control plane back)."""
    import server as s
    iid = str(rec.get("instance_id") or "")
    if verb in ("start", "resume"):
        rec["state"], rec["launch_status"] = "pending", "starting"
        s._gcp_compute_queue_runtime_start(iid)
    elif verb in ("stop", "suspend"):
        if _runtime_live(rec):
            s._stop_runtime_process(rec)
        rec["state"], rec["stopped_at"], rec["launch_status"] = "stopped", s._now(), "ready"
    elif verb == "reset":
        if _runtime_live(rec):
            if rec.get("state") == "running":
                s._reboot_runtime_process(rec)
            else:
                s._start_runtime_process(rec)
                rec["state"] = "running"
            rec["launch_status"] = "ready"
    elif verb == "delete":
        backend = str(rec.get("runtime_backend") or "").lower()
        if rec.get("launch_status") == "error" and not str(rec.get("container_id") or "").strip():
            s._terminate_simulated_instance(rec)
        elif backend == "docker":
            s._terminate_docker_instance(rec)
        elif backend == "multipass":
            s._terminate_multipass_instance(rec)
        elif backend == "lxd":
            s._terminate_lxd_instance(rec)
        else:
            s._terminate_simulated_instance(rec)
    elif verb == "setLabels":
        rec["labels"] = {str(k): str(v) for k, v in (payload.get("labels") or {}).items()}
    elif verb == "setTags":
        rec["tags"] = [str(t) for t in (payload.get("items") or []) if str(t).strip()]
    elif verb == "setMetadata":
        rec["metadata_items"] = {str(i.get("key")): i.get("value", "") for i in (payload.get("items") or [])
                                 if isinstance(i, dict) and i.get("key")}
    else:
        return
    if verb in ("start", "stop", "reset", "delete", "suspend", "resume"):
        s._cloudsim_sync_gcp_compute_resource(rec, "delete" if verb == "delete" else "upsert")
        s._record_usage(f"gcp.compute.{verb}_instance", {"instance_id": iid, "project": project, "zone": zone})


def compute(method: str, native: str, query: dict, body: bytes, classic: bool = False) -> dict:
    """Serve one Compute Engine call on the cores, keeping an instance's real runtime in
    step (see the module docstring)."""
    from fastapi import HTTPException
    from core import appliance_stores as aps
    target = _instance_target(method, native)
    payload = _load(body) if body else {}
    payload = payload if isinstance(payload, dict) else {}
    if target and target[3] == "insert":
        if classic and not payload.get("disks"):
            # pre-v4 console contract: {name, machineType} — the handler made the boot disk
            payload["disks"] = [{"boot": True, "autoDelete": True, "initializeParams": {
                "diskSizeGb": str(payload.get("bootDiskSizeGb") or 10),
                "sourceImage": payload.get("sourceImage") or None}}]
            body = json.dumps(payload).encode()
        if payload.get("name"):
            st = aps.gcp_compute_vm_store()
            full = "projects/%s/zones/%s/instances/%s" % (target[0], target[1], payload["name"])
            if full not in st.instances:
                try:
                    _insert_gates(payload)
                except HTTPException as exc:
                    return _http_error(exc)
    rec = prev = None
    full = ""
    if target and target[3] != "insert":
        project, zone, name, verb = target
        st = aps.gcp_compute_vm_store()
        st.adopt(project)
        full = "projects/%s/zones/%s/instances/%s" % (project, zone, name)
        core_rec = st.instances.get(full) or {}
        prev = core_rec.get("status")
        rid = core_rec.get("_runtimeId")
        rec = _runtime_store().get(rid) if rid else None
    out = _wi.dispatch_service("gcp_compute", method, native, query, {"content-type": "application/json"}, body)
    if method != "GET" and out["status"] < 300:
        try:                         # enforced VPC networking (core/netsim) — a no-op unless enabled
            from core.netsim import wiring as _nsw
            _nsw.schedule_apply(f"gcp {method} {native.split('?')[0][-60:]}")
        except Exception:
            pass
    if not target or out["status"] != 200:
        return out
    project, zone, name, verb = target
    try:
        if verb == "insert":
            st = aps.gcp_compute_vm_store()
            full = "projects/%s/zones/%s/instances/%s" % (project, zone, payload.get("name"))
            if full in st.instances and not st.instances[full].get("_runtimeId"):
                st.instances[full]["_runtimeId"] = _runtime_create(project, zone, payload)
        elif isinstance(rec, dict):
            try:
                _runtime_apply(verb, rec, project, zone, payload)
            except HTTPException as exc:
                st = aps.gcp_compute_vm_store()
                if prev and full in st.instances:          # the guest did not follow: roll back
                    st.instances[full]["status"] = prev
                return _http_error(exc)
            if verb == "delete":
                _runtime_store().pop(str(rec.get("instance_id") or ""), None)
    except Exception as exc:   # the control-plane call succeeded; never fail it over the runtime
        _log.warning("compute engine: runtime %s for %s skipped: %s", verb, name, exc)
    return out


async def _compute_native(request: Request):
    return _resp(compute(request.method, _raw_path(request), _query(request), await request.body()))


async def _compute_classic(request: Request):
    native = _raw_path(request)[len("/api/gcp"):]
    return _resp(compute(request.method, native, _query(request), await request.body(), classic=True))


_VPC_ALIASES = {"networks": "networks", "vpcs": "networks", "subnetworks": "subnetworks",
                "subnets": "subnetworks", "firewalls": "firewalls", "security-groups": "firewalls",
                "routes": "routes"}


async def _vpc_alias(request: Request):
    """/api/gcp/vpc/{networks|vpcs|subnetworks|subnets|firewalls|security-groups|routes}[/{name}]
    — the pre-v4 short aliases (project / region from the query string)."""
    from urllib.parse import quote
    parts = [s for s in _raw_path(request)[len("/api/gcp/vpc/"):].split("/") if s]
    kind = _VPC_ALIASES.get(parts[0]) if parts else None
    if not kind or len(parts) > 2:
        return _resp(_gerr(404, "Unknown path"))
    project = quote(_default_project(request))
    q = _query(request)
    region = str(q.pop("region", "") or "us-central1")
    q.pop("project", None)
    scope = f"regions/{quote(region)}" if kind == "subnetworks" else "global"
    native = f"/compute/v1/projects/{project}/{scope}/{kind}" + (f"/{parts[1]}" if len(parts) == 2 else "")
    return _resp(compute(request.method, native, q, await request.body(), classic=True))


# ── registration ─────────────────────────────────────────────────────────────
def register(app) -> list:
    """Mount the unified routes (call BEFORE the provider routes so these win).
    Returns the unified services it mounted."""
    mounted = []
    if _wi.is_unified("gcp_firestore"):
        for v in ("/v1", "/v1beta1"):
            app.add_route(v + "/projects/{project}/databases", _firestore_native, methods=_METHODS)
            app.add_route(v + "/projects/{project}/databases/{rest:path}", _firestore_native, methods=_METHODS)
            app.add_route(v + "/projects/{project}/locations/{loc}/backups", _firestore_native, methods=_METHODS)
            app.add_route(v + "/projects/{project}/locations/{loc}/backups/{rest:path}", _firestore_native, methods=_METHODS)
        for pre in ("/firestore/v1", "/api/gcp/firestore/v1"):
            app.add_route(pre + "/{rest:path}", _firestore_classic, methods=_METHODS)
        app.add_route("/api/gcp/dynamodb/tables", _gcp_dynamodb_alias, methods=_METHODS)
        app.add_route("/api/gcp/dynamodb/tables/{rest:path}", _gcp_dynamodb_alias, methods=_METHODS)
        mounted.append("gcp_firestore")
    if _wi.is_unified("gcp_compute"):
        for v in ("v1", "beta"):
            app.add_route(f"/compute/{v}/{{rest:path}}", _compute_native, methods=_METHODS)
            app.add_route(f"/api/gcp/compute/{v}/{{rest:path}}", _compute_classic, methods=_METHODS)
        app.add_route("/api/gcp/vpc/{rest:path}", _vpc_alias, methods=_METHODS)
        # Network Intelligence Center Connectivity Tests (networkmanagement v1) — the VPC core answers
        # them with the shared netsim evaluator (same engine as Nano)
        app.add_route("/v1/projects/{project}/locations/global/connectivityTests", _compute_native, methods=_METHODS)
        app.add_route("/v1/projects/{project}/locations/global/connectivityTests/{rest:path}", _compute_native, methods=_METHODS)
        # Internal Range Allocator (networkconnectivity) + Serverless VPC Access connectors (vpcaccess):
        # REST families outside /compute/ that the same VPC core serves
        for fam in ("internalRanges", "connectors"):
            app.add_route(f"/v1/projects/{{project}}/locations/{{location}}/{fam}", _compute_native, methods=_METHODS)
            app.add_route(f"/v1/projects/{{project}}/locations/{{location}}/{fam}/{{rest:path}}", _compute_native, methods=_METHODS)
        mounted.append("gcp_compute")
    return mounted


# ── readers for the console summary / inventory / VPC enforcement ────────────
def _space_slot(space: dict | None, key: str) -> dict:
    ss = (space or {}).get("service_states") or {}
    v = ss.get(f"gcp_{key}") if isinstance(ss, dict) else None
    return v if isinstance(v, dict) else {}


def inventory(space: dict | None) -> dict:
    """{(service, kind): {name: createTime}} of the core-held resources of `space`."""
    fs = _space_slot(space, "gcp_firestore_engine")
    vpc = _space_slot(space, "gcp_compute_vpc")
    vm = _space_slot(space, "gcp_compute_vm")
    out: dict = {}
    if _wi.is_unified("gcp_firestore"):
        out[("firestore", "database")] = {k: (v or {}).get("createTime", "") for k, v in (fs.get("databases") or {}).items()}
    if _wi.is_unified("gcp_compute"):
        for kind, coll in (("network", "networks"), ("subnetwork", "subnetworks"), ("firewall", "firewalls"),
                           ("route", "routes"), ("address", "addresses")):
            out[("vpc", kind)] = {k: (v or {}).get("creationTimestamp", "") for k, v in (vpc.get(coll) or {}).items()}
        for kind, coll in (("disk", "disks"), ("image", "images"), ("snapshot", "snapshots")):
            out[("compute", kind)] = {k: (v or {}).get("creationTimestamp", "") for k, v in (vm.get(coll) or {}).items()}
    return out


def summary_counts(target_project: str = "") -> dict:
    """Overrides for /api/gcp/console/summary: gcp-compute (instances), gcp-vpc (networks),
    gcp-firestore (root collections) read from the cores' state."""
    from core import appliance_stores as aps
    out = {}
    pre = f"projects/{target_project}/" if target_project else "projects/"
    if _wi.is_unified("gcp_compute"):
        out["gcp-compute"] = sum(1 for k in aps.gcp_compute_vm_store().instances if k.startswith(pre))
        out["gcp-vpc"] = sum(1 for k in aps.gcp_compute_vpc_store().networks
                             if not target_project or k.startswith(target_project + "/"))
    if _wi.is_unified("gcp_firestore"):
        out["gcp-firestore"] = len({k.split("/", 2)[1] for k in aps.gcp_firestore_store().documents if k.count("/") >= 2})
    return out


def firewall_rules() -> list | None:
    """The firewall rules (Compute v1 views) VPC enforcement applies, or None when the
    pre-v4 gcp_vpc_state is still authoritative."""
    if not _wi.is_unified("gcp_compute"):
        return None
    from core import appliance_stores as aps
    from core import gcp_compute_core as gcc
    return [gcc._firewall_view(r) for r in aps.gcp_compute_vpc_store().firewalls.values() if isinstance(r, dict)]
