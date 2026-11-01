# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""GCP Cloud Run core — substrate-independent. Speaks the native **Cloud Run Admin API v2**
(`run.googleapis.com/v2`) so the `google-cloud-run` SDKs and `gcloud run ...` work unchanged
against it (point them at the endpoint via api_endpoint / api_endpoint_overrides).

NO fastapi / google-cloud / socket / subprocess imports → loads under Pyodide, so the SAME
file runs offline and in Nano. This is the Cloud Run *control plane*: services, revisions, jobs,
executions, tasks, IAM policies and long-running operations. Containers are not executed here;
on Pro the Docker compute backend can run them, below that the console says so.

Resources (Discovery doc `run/v2`):
    projects/{p}/locations/{l}/services/{s}
    projects/{p}/locations/{l}/services/{s}/revisions/{r}
    projects/{p}/locations/{l}/jobs/{j}
    projects/{p}/locations/{l}/jobs/{j}/executions/{e}
    projects/{p}/locations/{l}/jobs/{j}/executions/{e}/tasks/{t}
    projects/{p}/locations/{l}/operations/{op}
Methods: services.create/get/list/patch/delete/getIamPolicy/setIamPolicy/testIamPermissions,
services.revisions.get/list/delete, jobs.create/get/list/patch/delete/run/getIamPolicy/
setIamPolicy/testIamPermissions, jobs.executions.get/list/delete/cancel, executions.tasks.
get/list, operations.get/list/delete/wait. Every mutation returns a completed (`done`)
long-running Operation like a very fast real cloud; errors use the Google shape
`{"error":{"code","message","status"}}`.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

REGIONS = ["us-central1", "us-east1", "us-east4", "us-east5", "us-south1", "us-west1", "us-west2", "us-west3",
           "us-west4", "europe-west1", "europe-west2", "europe-west3", "europe-west4", "europe-west8",
           "europe-west9", "europe-north1", "europe-central2", "asia-east1", "asia-east2", "asia-northeast1",
           "asia-northeast2", "asia-south1", "asia-southeast1", "asia-southeast2", "australia-southeast1",
           "southamerica-east1", "northamerica-northeast1", "me-west1", "africa-south1"]
DEFAULT_IMAGE = "us-docker.pkg.dev/cloudrun/container/hello"
IAM_INVOKER = "roles/run.invoker"

# Proto enums are strings on the wire; the gapic REST clients (`$alt=json;enum-encoding=int`) may
# send integers, so request bodies accept both and responses always use the names.
_ENUMS = {
    "ingress": ["INGRESS_TRAFFIC_UNSPECIFIED", "INGRESS_TRAFFIC_ALL", "INGRESS_TRAFFIC_INTERNAL_ONLY",
                "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER", "INGRESS_TRAFFIC_NONE"],
    "launchStage": {0: "LAUNCH_STAGE_UNSPECIFIED", 1: "EARLY_ACCESS", 2: "ALPHA", 3: "BETA", 4: "GA",
                    5: "DEPRECATED", 6: "UNIMPLEMENTED", 7: "PRELAUNCH"},
    "executionEnvironment": ["EXECUTION_ENVIRONMENT_UNSPECIFIED", "EXECUTION_ENVIRONMENT_GEN1",
                             "EXECUTION_ENVIRONMENT_GEN2"],
    "egress": ["VPC_EGRESS_UNSPECIFIED", "ALL_TRAFFIC", "PRIVATE_RANGES_ONLY"],
}
_TRAFFIC_TYPES = ["TRAFFIC_TARGET_ALLOCATION_TYPE_UNSPECIFIED", "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST",
                  "TRAFFIC_TARGET_ALLOCATION_TYPE_REVISION"]
LATEST, REVISION = _TRAFFIC_TYPES[1], _TRAFFIC_TYPES[2]
PERMISSIONS = ["run.services.get", "run.services.list", "run.services.create", "run.services.update",
               "run.services.delete", "run.services.invoke", "run.services.getIamPolicy",
               "run.services.setIamPolicy", "run.jobs.get", "run.jobs.list", "run.jobs.create",
               "run.jobs.update", "run.jobs.delete", "run.jobs.run", "run.executions.get",
               "run.executions.list", "run.executions.delete", "run.revisions.get", "run.revisions.list",
               "run.revisions.delete", "run.operations.get", "run.operations.list", "run.operations.delete",
               "run.tasks.get", "run.tasks.list", "run.routes.invoke"]


# ── store ──────────────────────────────────────────────────────────────────
class RunStore:
    """Public dict attrs only → persisted/synced by core/nano_persist."""

    def __init__(self):
        self.services: dict = {}     # full service name -> Service resource
        self.revisions: dict = {}    # full revision name -> Revision resource
        self.jobs: dict = {}         # full job name -> Job resource
        self.executions: dict = {}   # full execution name -> Execution resource
        self.tasks: dict = {}        # full task name -> Task resource
        self.operations: dict = {}   # full operation name -> Operation resource
        self.policies: dict = {}     # full resource name -> IAM Policy
        self.worker_pools: dict = {}     # full worker pool name -> WorkerPool resource
        self.domain_mappings: dict = {}  # full domain mapping name -> DomainMapping resource
        self.event_triggers: dict = {}   # full trigger name -> Eventarc-style trigger resource
        self.seq: dict = {"op": 0, "uid": 0}


_SHARED: RunStore | None = None


def shared_store() -> RunStore:
    """The appliance-wide store: the native wire and the console REST share it."""
    global _SHARED
    if _SHARED is None:
        _SHARED = RunStore()
    return _SHARED


@dataclass
class RunResponse:
    status: int = 200
    headers: dict = field(default_factory=dict)
    body: bytes = b""
    media_type: str | None = "application/json"


class _E(Exception):
    def __init__(self, status, gcp_status, message):
        super().__init__(message)
        self.status, self.gcp_status, self.message = status, gcp_status, message


def _err(status, gcp_status, message):
    body = {"error": {"code": status, "message": message, "status": gcp_status}}
    return RunResponse(status=status, body=json.dumps(body).encode())


def _json(status, obj):
    return RunResponse(status=status, body=json.dumps(obj).encode())


def _ts():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _copy(x):
    return json.loads(json.dumps(x))


def _h(*parts):
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()


# ── names / validation ─────────────────────────────────────────────────────
_NAME = re.compile(r"^[a-z]([-a-z0-9]{0,47}[a-z0-9])?$")
_LABEL = re.compile(r"^[a-z][-_a-z0-9]{0,62}$")
_DUR = re.compile(r"^\d+(\.\d+)?s$")
_MEM = re.compile(r"^\d+(\.\d+)?(Ki|Mi|Gi|Ti|K|M|G|T|k|m)?$")
_CPU = re.compile(r"^(\d+(\.\d+)?|\d+m)$")


def project_number(project):
    """Stable 12-digit pseudo project number (real Cloud Run URLs/service accounts embed it)."""
    return str(int(_h("pn", project)[:10], 16) % 900000000000 + 100000000000)


def service_name(project, location, sid):
    return "projects/%s/locations/%s/services/%s" % (project, location, sid)


def job_name(project, location, jid):
    return "projects/%s/locations/%s/jobs/%s" % (project, location, jid)


def _check_name(kind, name):
    if not _NAME.match(name or ""):
        raise _E(400, "INVALID_ARGUMENT",
                 "Invalid %s name %r: must be 1-49 chars of lowercase letters, digits and hyphens, "
                 "start with a letter and not end with a hyphen." % (kind, name))


def _check_location(location):
    if location not in REGIONS:
        raise _E(400, "INVALID_ARGUMENT", "Location %r is not a valid Cloud Run region." % location)


def _check_map(m, what):
    if not isinstance(m, dict):
        raise _E(400, "INVALID_ARGUMENT", "Invalid %s." % what)
    if len(m) > 64:
        raise _E(400, "INVALID_ARGUMENT", "At most 64 %s are allowed." % what)
    if what == "labels":
        for k, v in m.items():
            if not _LABEL.match(str(k)) or len(str(v)) > 63:
                raise _E(400, "INVALID_ARGUMENT", "Invalid label %r: keys must match [a-z][-_a-z0-9]{0,62} "
                                                  "and values be at most 63 characters." % k)


def _enum_in(key, v):
    """Accept a proto enum as its name or its number."""
    table = _ENUMS.get(key)
    if isinstance(v, int) and table is not None:
        return table.get(v) if isinstance(table, dict) else (table[v] if 0 <= v < len(table) else v)
    return v


def _norm_enums(o):
    """Normalise integer enums inside a Service/Job request body to names."""
    if isinstance(o, list):
        return [_norm_enums(x) for x in o]
    if not isinstance(o, dict):
        return o
    out = {}
    for k, v in o.items():
        if k == "type" and isinstance(v, int) and 0 <= v < len(_TRAFFIC_TYPES):
            out[k] = _TRAFFIC_TYPES[v]
        elif k in _ENUMS:
            out[k] = _enum_in(k, v)
        else:
            out[k] = _norm_enums(v)
    return out


# ── pagination ─────────────────────────────────────────────────────────────
def _page(items, query):
    try:
        size = int(query.get("pageSize") or 0)
    except ValueError:
        raise _E(400, "INVALID_ARGUMENT", "Invalid pageSize.")
    if size < 0:
        raise _E(400, "INVALID_ARGUMENT", "pageSize must be non-negative.")
    size = size or 1000
    try:
        start = int(query.get("pageToken") or 0)
    except ValueError:
        raise _E(400, "INVALID_ARGUMENT", "Invalid pageToken.")
    chunk = items[start:start + size]
    nxt = str(start + size) if start + size < len(items) else ""
    return chunk, nxt


# ── conditions / operations ────────────────────────────────────────────────
def _conditions(now, *types):
    return [{"type": t, "state": "CONDITION_SUCCEEDED", "lastTransitionTime": now, "severity": "INFO"
             if t != "Ready" else "ERROR"} for t in types]


def _uid(store, *parts):
    store.seq["uid"] += 1
    h = _h(*parts, store.seq["uid"])
    return "%s-%s-%s-%s-%s" % (h[:8], h[8:12], h[12:16], h[16:20], h[20:32])


_TYPES = {"service": "Service", "job": "Job", "execution": "Execution", "revision": "Revision",
          "workerpool": "WorkerPool", "domainmapping": "DomainMapping"}


def _operation(store, project, location, kind, resource):
    """A completed LRO: metadata + response are the resource (Any, `@type` tagged)."""
    store.seq["op"] += 1
    oid = _uid(store, "op", project, location, store.seq["op"])
    name = "projects/%s/locations/%s/operations/%s" % (project, location, oid)
    t = "type.googleapis.com/google.cloud.run.v2.%s" % _TYPES[kind]
    meta = dict(_copy(resource), **{"@type": t})
    op = {"name": name, "metadata": meta, "done": True, "response": dict(_copy(resource), **{"@type": t})}
    store.operations[name] = op
    return op


# ── containers / templates ─────────────────────────────────────────────────
def _norm_container(c, idx, count, is_job):
    if not isinstance(c, dict) or not c.get("image"):
        raise _E(400, "INVALID_ARGUMENT", "Container image is required: template.containers[%d].image." % idx)
    c = dict(c)
    if not c.get("name"):
        base = re.sub(r"[^a-z0-9]", "", c["image"].rsplit("/", 1)[-1].split(":")[0].split("@")[0].lower())[:20]
        c["name"] = "%s-%d" % (base or "container", idx + 1)
    res = dict(c.get("resources") or {})
    lim = dict(res.get("limits") or {})
    lim.setdefault("cpu", "1000m")
    lim.setdefault("memory", "512Mi")
    if not _CPU.match(str(lim["cpu"])):
        raise _E(400, "INVALID_ARGUMENT", "Invalid CPU limit %r." % lim["cpu"])
    if not _MEM.match(str(lim["memory"])):
        raise _E(400, "INVALID_ARGUMENT", "Invalid memory limit %r." % lim["memory"])
    res["limits"] = lim
    if not is_job:
        res.setdefault("cpuIdle", True)
        res.setdefault("startupCpuBoost", False)
        if idx == 0 and not c.get("ports"):
            c["ports"] = [{"name": "http1", "containerPort": 8080}]
    c["resources"] = res
    return c


def _norm_timeout(v, default):
    v = v or default
    if not _DUR.match(str(v)):
        raise _E(400, "INVALID_ARGUMENT", "Invalid duration %r (use e.g. \"300s\")." % v)
    return str(v)


def _revision_template(project, spec, is_job):
    """Normalise a RevisionTemplate / TaskTemplate (defaults the real service reports)."""
    spec = dict(spec or {})
    cs = spec.get("containers") or []
    if not cs:
        raise _E(400, "INVALID_ARGUMENT", "template.containers must contain at least one container with an image.")
    if len(cs) > 10:
        raise _E(400, "INVALID_ARGUMENT", "A revision may have at most 10 containers.")
    spec["containers"] = [_norm_container(c, i, len(cs), is_job) for i, c in enumerate(cs)]
    spec["timeout"] = _norm_timeout(spec.get("timeout"), "600s" if is_job else "300s")
    spec.setdefault("serviceAccount", "%s-compute@developer.gserviceaccount.com" % project_number(project))
    spec.setdefault("executionEnvironment", "EXECUTION_ENVIRONMENT_GEN2")
    if is_job:
        spec.setdefault("maxRetries", 3)
    else:
        sc = dict(spec.get("scaling") or {})
        sc.setdefault("minInstanceCount", 0)
        sc.setdefault("maxInstanceCount", 100)
        if sc["minInstanceCount"] < 0 or sc["maxInstanceCount"] < 0 or \
                (sc["maxInstanceCount"] and sc["minInstanceCount"] > sc["maxInstanceCount"]):
            raise _E(400, "INVALID_ARGUMENT", "scaling.minInstanceCount must not exceed scaling.maxInstanceCount.")
        spec["scaling"] = sc
        conc = spec.get("maxInstanceRequestConcurrency", 80)
        if not isinstance(conc, int) or conc < 0 or conc > 1000:
            raise _E(400, "INVALID_ARGUMENT", "maxInstanceRequestConcurrency must be between 0 and 1000.")
        spec["maxInstanceRequestConcurrency"] = conc
    if spec.get("labels") is not None:
        _check_map(spec["labels"], "labels")
    return spec


# ── inline function source (Cloud Run functions: the "Function" deploy source) ─────────────
# Annotation keys the console's inline-editor deploy path uses to carry entry point, runtime
# and source text on the Service resource (see consoles/src/gcp/services/functions/api.js).
# A real deploy builds and runs this; Vyomi validates it parses and the entry point exists
# (same bar as a build failing on bad code) but does not build a container or execute it.
_FN_ANN_RUNTIME = "vyomi.dev/function-runtime"
_FN_ANN_ENTRY = "vyomi.dev/function-entry-point"
_FN_ANN_SOURCE = "vyomi.dev/function-source"


def _validate_function_source(annotations):
    runtime = str((annotations or {}).get(_FN_ANN_RUNTIME) or "")
    if not runtime.lower().startswith("python"):
        return   # only Python source is parsed server-side; other runtimes are stored as-is
    source = (annotations or {}).get(_FN_ANN_SOURCE) or ""
    if not source.strip():
        return
    import ast
    entry = (annotations or {}).get(_FN_ANN_ENTRY) or "handler"
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        raise _E(400, "INVALID_ARGUMENT", "Function source has a syntax error: %s" % e)
    defs = {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    if entry not in defs:
        raise _E(400, "INVALID_ARGUMENT", "Function entry point %r not found in source." % entry)


def _rev_suffix(svc_full, n):
    return "%s-%05d-%s" % (svc_full.rsplit("/", 1)[-1], n, "".join(
        "abcdefghijklmnopqrstuvwxyz"[int(c, 16) % 26] for c in _h("rev", svc_full, n)[:3]))


def _new_revision(store, svc_full, svc, now):
    t = _copy(svc["template"])
    n = svc.pop("_revSeq", 0) + 1
    svc["_revSeq"] = n
    want = t.pop("revision", "") or ""
    short = want if want else _rev_suffix(svc_full, n)
    sname = svc_full.rsplit("/", 1)[-1]
    if want and not want.startswith(sname + "-"):
        raise _E(400, "INVALID_ARGUMENT", "Revision name %r must begin with the service name %r followed by a hyphen." % (want, sname))
    parts = svc_full.split("/")
    full = "projects/%s/locations/%s/services/%s/revisions/%s" % (parts[1], parts[3], sname, short)
    if full in store.revisions:
        raise _E(409, "ALREADY_EXISTS", "Revision named %s already exists." % short)
    rev = {"name": full, "uid": _uid(store, "rev", full), "generation": "1",
           "labels": t.pop("labels", {}) or {}, "annotations": t.pop("annotations", {}) or {},
           "createTime": now, "updateTime": now, "launchStage": svc.get("launchStage", "GA"),
           "service": svc_full, "logUri": "https://console.cloud.google.com/logs/viewer?project=%s&resource=cloud_run_revision/service_name/%s/revision_name/%s" % (parts[1], sname, short),
           "observedGeneration": "1", "reconciling": False,
           "conditions": _conditions(now, "Ready", "ResourcesAvailable", "ContainerReady", "Active"),
           "etag": '"%s"' % _h("rev", full, now)[:16]}
    rev.update(t)
    store.revisions[full] = rev
    return rev


# ── services ───────────────────────────────────────────────────────────────
def _service_uri(project, location, sid):
    return "https://%s-%s.%s.run.app" % (sid, project_number(project), location)


def _traffic_check(store, svc_full, traffic):
    if not isinstance(traffic, list):
        raise _E(400, "INVALID_ARGUMENT", "Invalid traffic.")
    total = 0
    for tt in traffic:
        total += int(tt.get("percent", 0) or 0)
        if tt.get("type") == REVISION or tt.get("revision"):
            rn = "%s/revisions/%s" % (svc_full, tt.get("revision", ""))
            if rn not in store.revisions:
                raise _E(400, "INVALID_ARGUMENT", "Revision %r referenced by traffic does not exist." % tt.get("revision"))
    if traffic and total != 100:
        raise _E(400, "INVALID_ARGUMENT", "Traffic percentages must sum to 100, got %d." % total)


def _traffic_statuses(store, svc_full, svc):
    out = []
    latest = svc.get("latestReadyRevision", "")
    for tt in svc.get("traffic", []):
        st = {"type": tt.get("type", LATEST), "percent": tt.get("percent", 0)}
        if tt.get("type", LATEST) == LATEST:
            st["revision"] = latest.rsplit("/", 1)[-1]
        else:
            st["revision"] = tt.get("revision", "")
        if tt.get("tag"):
            st["tag"] = tt["tag"]
            st["uri"] = svc["uri"].replace("https://", "https://%s---" % tt["tag"], 1)
        out.append(st)
    return out


def _settle_service(store, svc_full, svc, now, new_revision):
    if new_revision:
        rev = _new_revision(store, svc_full, svc, now)
        svc["latestCreatedRevision"] = svc["latestReadyRevision"] = rev["name"]
    svc["updateTime"] = now
    svc["observedGeneration"] = svc["generation"]
    svc["reconciling"] = False
    svc["conditions"] = _conditions(now, "Ready", "RoutesReady", "ConfigurationsReady")
    svc["terminalCondition"] = svc["conditions"][0]
    svc["trafficStatuses"] = _traffic_statuses(store, svc_full, svc)
    svc["etag"] = '"%s"' % _h("svc", svc_full, svc["generation"], now)[:16]


def service_view(svc):
    return {k: _copy(v) for k, v in svc.items() if not k.startswith("_")}


def create_service(store, project, location, query, payload):
    _check_location(location)
    sid = query.get("serviceId") or ""
    if not sid:
        raise _E(400, "INVALID_ARGUMENT", "Service ID must be specified (serviceId).")
    _check_name("service", sid)
    spec = _norm_enums(payload)
    if not spec.get("template"):
        raise _E(400, "INVALID_ARGUMENT", "template is required.")
    full = service_name(project, location, sid)
    if full in store.services:
        raise _E(409, "ALREADY_EXISTS", "Resource '%s' already exists." % full)
    for k in ("labels", "annotations"):
        if spec.get(k) is not None:
            _check_map(spec[k], k)
    _validate_function_source(spec.get("annotations"))
    template = _revision_template(project, spec["template"], False)
    traffic = spec.get("traffic") or [{"type": LATEST, "percent": 100}]
    now = _ts()
    svc = {"name": full, "description": spec.get("description", ""), "uid": _uid(store, "svc", full),
           "generation": "1", "labels": spec.get("labels", {}) or {}, "annotations": spec.get("annotations", {}) or {},
           "createTime": now, "creator": "admin@vyomi.cloud", "lastModifier": "admin@vyomi.cloud",
           "client": spec.get("client", ""), "clientVersion": spec.get("clientVersion", ""),
           "ingress": spec.get("ingress") or "INGRESS_TRAFFIC_ALL", "launchStage": spec.get("launchStage") or "GA",
           "template": template, "traffic": traffic, "uri": _service_uri(project, location, sid),
           "defaultUriDisabled": bool(spec.get("defaultUriDisabled", False)), "urls": []}
    if spec.get("binaryAuthorization"):
        svc["binaryAuthorization"] = spec["binaryAuthorization"]
    if spec.get("scaling"):
        svc["scaling"] = spec["scaling"]
    svc["urls"] = [svc["uri"]]
    if query.get("validateOnly") in ("true", "True", True):
        return _operation(store, project, location, "service", service_view(svc))
    _traffic_check(store, full, traffic)
    store.services[full] = svc
    _settle_service(store, full, svc, now, True)
    return _operation(store, project, location, "service", service_view(svc))


def _get_service(store, project, location, sid):
    full = service_name(project, location, sid)
    svc = store.services.get(full)
    if not svc:
        raise _E(404, "NOT_FOUND", "Resource '%s' of kind 'SERVICE' in region '%s' in project '%s' does not exist." % (sid, location, project))
    return full, svc


_PATCHABLE = ("description", "labels", "annotations", "client", "clientVersion", "ingress", "launchStage",
              "template", "traffic", "binaryAuthorization", "scaling", "defaultUriDisabled")


def _mask_fields(query, payload):
    mask = query.get("updateMask") or ""
    if mask:
        return [m.split(".", 1)[0] for m in mask.split(",") if m]
    return [k for k in payload if k in _PATCHABLE]


def update_service(store, project, location, sid, query, payload):
    full = service_name(project, location, sid)
    svc = store.services.get(full)
    allow_missing = query.get("allowMissing") in ("true", "True", True)
    if not svc:
        if allow_missing:
            return create_service(store, project, location, {"serviceId": sid}, payload)
        _get_service(store, project, location, sid)
    spec = _norm_enums(payload)
    if spec.get("name") and spec["name"] != full:
        raise _E(400, "INVALID_ARGUMENT", "Service name in the body does not match the request path.")
    fields = _mask_fields(query, spec)
    new = _copy(service_view(svc))
    changed_template = False
    for f in fields:
        if f not in _PATCHABLE:
            raise _E(400, "INVALID_ARGUMENT", "Field %r is not updatable." % f)
        if f not in spec:
            if f in ("labels", "annotations"):
                new[f] = {}
            continue
        if f in ("labels", "annotations"):
            _check_map(spec[f], f)
        if f == "template":
            tpl = _revision_template(project, spec["template"], False)
            cur = _copy(svc["template"])
            cur.pop("revision", None)
            differs = json.dumps(cur, sort_keys=True) != json.dumps({k: v for k, v in tpl.items() if k != "revision"}, sort_keys=True)
            named = ("%s/revisions/%s" % (full, tpl["revision"])) if tpl.get("revision") else ""
            if named and named in store.revisions:   # re-sending an existing revision's name (gcloud update-traffic does)
                if differs:
                    raise _E(409, "ALREADY_EXISTS", "Revision named %s with different configuration already exists." % tpl["revision"])
            elif differs or named:
                changed_template = True
            new["template"] = tpl
        else:
            new[f] = spec[f]
    if "traffic" in fields:
        _traffic_check(store, full, new.get("traffic", []))
        if not new.get("traffic"):
            new["traffic"] = [{"type": LATEST, "percent": 100}]
    if "annotations" in fields:
        _validate_function_source(new.get("annotations"))
    if query.get("validateOnly") in ("true", "True", True):
        return _operation(store, project, location, "service", new)
    svc.update({k: new[k] for k in fields if k in new})
    if "traffic" in fields and not svc.get("traffic"):
        svc["traffic"] = new["traffic"]
    svc["generation"] = str(int(svc["generation"]) + 1)
    svc["lastModifier"] = "admin@vyomi.cloud"
    _settle_service(store, full, svc, _ts(), changed_template)
    return _operation(store, project, location, "service", service_view(svc))


def delete_service(store, project, location, sid, query):
    full, svc = _get_service(store, project, location, sid)
    etag = query.get("etag")
    if etag and etag != svc.get("etag"):
        raise _E(409, "ABORTED", "The supplied etag does not match the service's current etag.")
    view = service_view(svc)
    now = _ts()
    view["deleteTime"] = now
    view["expireTime"] = now
    if query.get("validateOnly") not in ("true", "True", True):
        del store.services[full]
        for n in [n for n in store.revisions if n.startswith(full + "/revisions/")]:
            del store.revisions[n]
        store.policies.pop(full, None)
    return _operation(store, project, location, "service", view)


# ── revisions ──────────────────────────────────────────────────────────────
def revision_view(rev):
    return _copy(rev)


def _get_revision(store, project, location, sid, rid):
    full = "%s/revisions/%s" % (service_name(project, location, sid), rid)
    rev = store.revisions.get(full)
    if not rev:
        raise _E(404, "NOT_FOUND", "Revision '%s' of service '%s' does not exist." % (rid, sid))
    return full, rev


def delete_revision(store, project, location, sid, rid, query):
    full, rev = _get_revision(store, project, location, sid, rid)
    svc = store.services.get(rev["service"])
    if svc:
        serving = {tt.get("revision") for tt in svc.get("traffic", []) if tt.get("percent")}
        latest_serves = any(tt.get("type", LATEST) == LATEST and tt.get("percent") for tt in svc.get("traffic", []))
        if rid in serving or (latest_serves and rev["name"] == svc.get("latestReadyRevision")):
            raise _E(400, "FAILED_PRECONDITION", "Revision '%s' is serving traffic and cannot be deleted." % rid)
    view = revision_view(rev)
    view["deleteTime"] = _ts()
    if query.get("validateOnly") not in ("true", "True", True):
        del store.revisions[full]
    return _operation(store, project, location, "revision", view)


# ── jobs ───────────────────────────────────────────────────────────────────
def _job_template(project, spec):
    spec = dict(spec or {})
    if not spec.get("template"):
        raise _E(400, "INVALID_ARGUMENT", "template.template is required (the task template).")
    task = _revision_template(project, spec["template"], True)
    out = {"labels": spec.get("labels", {}) or {}, "annotations": spec.get("annotations", {}) or {},
           "parallelism": spec.get("parallelism", 1), "taskCount": spec.get("taskCount", 1), "template": task}
    for k in ("parallelism", "taskCount"):
        if not isinstance(out[k], int) or out[k] < 0 or out[k] > 10000:
            raise _E(400, "INVALID_ARGUMENT", "%s must be between 0 and 10000." % k)
    if out["taskCount"] < 1:
        raise _E(400, "INVALID_ARGUMENT", "taskCount must be at least 1.")
    if out["parallelism"] > out["taskCount"]:
        out["parallelism"] = out["taskCount"]
    return out


def _settle_job(store, full, job, now):
    job["updateTime"] = now
    job["observedGeneration"] = job["generation"]
    job["reconciling"] = False
    job["conditions"] = _conditions(now, "Ready", "JobExecutionsReady")
    job["terminalCondition"] = job["conditions"][0]
    job["etag"] = '"%s"' % _h("job", full, job["generation"], now)[:16]


def job_view(job):
    return {k: _copy(v) for k, v in job.items() if not k.startswith("_")}


def create_job(store, project, location, query, payload):
    _check_location(location)
    jid = query.get("jobId") or ""
    if not jid:
        raise _E(400, "INVALID_ARGUMENT", "Job ID must be specified (jobId).")
    _check_name("job", jid)
    spec = _norm_enums(payload)
    full = job_name(project, location, jid)
    if full in store.jobs:
        raise _E(409, "ALREADY_EXISTS", "Resource '%s' already exists." % full)
    for k in ("labels", "annotations"):
        if spec.get(k) is not None:
            _check_map(spec[k], k)
    now = _ts()
    job = {"name": full, "uid": _uid(store, "job", full), "generation": "1",
           "labels": spec.get("labels", {}) or {}, "annotations": spec.get("annotations", {}) or {},
           "createTime": now, "creator": "admin@vyomi.cloud", "lastModifier": "admin@vyomi.cloud",
           "client": spec.get("client", ""), "clientVersion": spec.get("clientVersion", ""),
           "launchStage": spec.get("launchStage") or "GA", "template": _job_template(project, spec.get("template")),
           "executionCount": 0}
    if query.get("validateOnly") in ("true", "True", True):
        return _operation(store, project, location, "job", job_view(job))
    store.jobs[full] = job
    _settle_job(store, full, job, now)
    return _operation(store, project, location, "job", job_view(job))


def _get_job(store, project, location, jid):
    full = job_name(project, location, jid)
    job = store.jobs.get(full)
    if not job:
        raise _E(404, "NOT_FOUND", "Resource '%s' of kind 'JOB' in region '%s' in project '%s' does not exist." % (jid, location, project))
    return full, job


def update_job(store, project, location, jid, query, payload):
    full = job_name(project, location, jid)
    job = store.jobs.get(full)
    if not job:
        if query.get("allowMissing") in ("true", "True", True):
            return create_job(store, project, location, {"jobId": jid}, payload)
        _get_job(store, project, location, jid)
    spec = _norm_enums(payload)
    fields = _mask_fields(query, spec)
    new = job_view(job)
    for f in fields:
        if f not in ("labels", "annotations", "client", "clientVersion", "launchStage", "template"):
            raise _E(400, "INVALID_ARGUMENT", "Field %r is not updatable." % f)
        if f not in spec:
            continue
        if f in ("labels", "annotations"):
            _check_map(spec[f], f)
            new[f] = spec[f]
        elif f == "template":
            new["template"] = _job_template(project, spec["template"])
        else:
            new[f] = spec[f]
    if query.get("validateOnly") in ("true", "True", True):
        return _operation(store, project, location, "job", new)
    job.update({k: new[k] for k in fields if k in new})
    job["generation"] = str(int(job["generation"]) + 1)
    job["lastModifier"] = "admin@vyomi.cloud"
    _settle_job(store, full, job, _ts())
    return _operation(store, project, location, "job", job_view(job))


def delete_job(store, project, location, jid, query):
    full, job = _get_job(store, project, location, jid)
    etag = query.get("etag")
    if etag and etag != job.get("etag"):
        raise _E(409, "ABORTED", "The supplied etag does not match the job's current etag.")
    view = job_view(job)
    now = _ts()
    view["deleteTime"] = now
    view["expireTime"] = now
    if query.get("validateOnly") not in ("true", "True", True):
        del store.jobs[full]
        for n in [n for n in store.executions if n.startswith(full + "/executions/")]:
            del store.executions[n]
        for n in [n for n in store.tasks if n.startswith(full + "/executions/")]:
            del store.tasks[n]
        store.policies.pop(full, None)
    return _operation(store, project, location, "job", view)


# ── executions / tasks ─────────────────────────────────────────────────────
def run_job(store, project, location, jid, payload):
    full, job = _get_job(store, project, location, jid)
    ov = payload.get("overrides") or {}
    count = ov.get("taskCount") or job["template"]["taskCount"]
    if not isinstance(count, int) or count < 1:
        raise _E(400, "INVALID_ARGUMENT", "overrides.taskCount must be at least 1.")
    now = _ts()
    job["executionCount"] += 1
    n = job["executionCount"]
    eid = "%s-%s" % (jid, "".join("abcdefghijklmnopqrstuvwxyz"[int(c, 16) % 26] for c in _h("exe", full, n)[:5]))
    ename = "%s/executions/%s" % (full, eid)
    tpl = _copy(job["template"])
    tpl["taskCount"] = count
    if ov.get("timeout"):
        tpl["template"]["timeout"] = _norm_timeout(ov["timeout"], "600s")
    for i, co in enumerate(ov.get("containerOverrides") or []):
        if i < len(tpl["template"]["containers"]):
            c = tpl["template"]["containers"][i]
            if co.get("args"):
                c["args"] = co["args"]
            if co.get("env"):
                c["env"] = (c.get("env") or []) + co["env"]
            if co.get("clearArgs"):
                c.pop("args", None)
    ex = {"name": ename, "uid": _uid(store, "exe", ename), "generation": "1", "labels": tpl.get("labels", {}),
          "annotations": tpl.get("annotations", {}), "createTime": now, "startTime": now, "completionTime": now,
          "updateTime": now, "job": jid, "launchStage": job.get("launchStage", "GA"),
          "parallelism": min(tpl["parallelism"], count), "taskCount": count, "template": tpl["template"],
          "reconciling": False, "conditions": _conditions(now, "Completed", "Started", "ResourcesAvailable"),
          "observedGeneration": "1", "runningCount": 0, "succeededCount": count, "failedCount": 0,
          "cancelledCount": 0, "retriedCount": 0,
          "logUri": "https://console.cloud.google.com/logs/viewer?project=%s&resource=cloud_run_job/job_name/%s/location/%s" % (project, jid, location),
          "etag": '"%s"' % _h("exe", ename, now)[:16]}
    store.executions[ename] = ex
    for i in range(count):
        tname = "%s/tasks/%s-task%d" % (ename, eid, i)
        store.tasks[tname] = {"name": tname, "uid": _uid(store, "task", tname), "generation": "1", "createTime": now,
                              "startTime": now, "completionTime": now, "updateTime": now, "job": jid, "execution": eid,
                              "containers": [{"name": c.get("name", ""), "image": c["image"]} for c in ex["template"]["containers"]],
                              "volumes": ex["template"].get("volumes", []), "maxRetries": ex["template"]["maxRetries"],
                              "timeout": ex["template"]["timeout"], "serviceAccount": ex["template"]["serviceAccount"],
                              "executionEnvironment": ex["template"]["executionEnvironment"], "reconciling": False,
                              "conditions": _conditions(now, "Ready", "ResourcesAvailable", "Started", "Retried"),
                              "observedGeneration": "1", "index": i, "retried": 0,
                              "lastAttemptResult": {"status": {"code": 0, "message": ""}, "exitCode": 0},
                              "logUri": ex["logUri"], "etag": '"%s"' % _h("task", tname)[:16]}
    job["latestCreatedExecution"] = {"name": ename, "createTime": now, "completionTime": now}
    job["updateTime"] = now
    return _operation(store, project, location, "execution", ex)


def _get_execution(store, project, location, jid, eid):
    full = "%s/executions/%s" % (job_name(project, location, jid), eid)
    ex = store.executions.get(full)
    if not ex:
        raise _E(404, "NOT_FOUND", "Execution '%s' of job '%s' does not exist." % (eid, jid))
    return full, ex


def delete_execution(store, project, location, jid, eid, query):
    full, ex = _get_execution(store, project, location, jid, eid)
    view = _copy(ex)
    view["deleteTime"] = _ts()
    if query.get("validateOnly") not in ("true", "True", True):
        del store.executions[full]
        for n in [n for n in store.tasks if n.startswith(full + "/tasks/")]:
            del store.tasks[n]
    return _operation(store, project, location, "execution", view)


def cancel_execution(store, project, location, jid, eid):
    _, ex = _get_execution(store, project, location, jid, eid)
    raise _E(400, "FAILED_PRECONDITION", "Execution %s has already completed and cannot be cancelled." % ex["name"].rsplit("/", 1)[-1])


# ── IAM ────────────────────────────────────────────────────────────────────
def _policy(store, full):
    return store.policies.get(full) or {"version": 1, "etag": "ACAB", "bindings": []}


def get_iam_policy(store, full, query):
    return _copy(_policy(store, full))


def set_iam_policy(store, full, payload):
    pol = payload.get("policy")
    if not isinstance(pol, dict):
        raise _E(400, "INVALID_ARGUMENT", "policy must be specified.")
    cur = _policy(store, full)
    if pol.get("etag") and pol["etag"] != cur["etag"] and cur["bindings"]:
        raise _E(409, "ABORTED", "There were concurrent policy changes. Please retry the whole read-modify-write with exponential backoff.")
    bindings = []
    for b in pol.get("bindings") or []:
        if not b.get("role") or not b.get("members"):
            raise _E(400, "INVALID_ARGUMENT", "Each binding needs a role and at least one member.")
        bindings.append({"role": b["role"], "members": list(b["members"])})
    new = {"version": pol.get("version", 1) or 1, "bindings": bindings,
           "etag": "CAE=" if not bindings else base64.b64encode(bytes.fromhex(_h("pol", json.dumps(bindings, sort_keys=True))[:16])).decode()}
    store.policies[full] = new
    return _copy(new)


def public_invoker(store, full):
    return any(b["role"] == IAM_INVOKER and "allUsers" in b["members"] for b in _policy(store, full)["bindings"])


# ── console views ──────────────────────────────────────────────────────────
def console_view(store, full):
    svc = store.services[full]
    seg = full.split("/")
    tpl = svc["template"]
    c0 = tpl["containers"][0]
    lim = c0["resources"]["limits"]
    latest = (svc.get("latestReadyRevision") or "").rsplit("/", 1)[-1]
    sc = tpl["scaling"]
    revs = sorted((r for n, r in store.revisions.items() if r["service"] == full), key=lambda r: r["createTime"])
    v = service_view(svc)
    ports = c0.get("ports") or [{"containerPort": 8080}]
    v.update({
        "id": seg[5], "resourceName": full, "project": seg[1], "region": seg[3],
        "deployment": "Container",
        "image": c0["image"],
        "authentication": "Allow unauthenticated" if public_invoker(store, full) else "Require authentication",
        "ingress_text": {"INGRESS_TRAFFIC_ALL": "All", "INGRESS_TRAFFIC_INTERNAL_ONLY": "Internal",
                         "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER": "Internal and Cloud Load Balancing",
                         "INGRESS_TRAFFIC_NONE": "None"}.get(svc["ingress"], "All"),
        "last_deployed": svc["updateTime"], "deployed_by": svc["lastModifier"],
        "revision": latest, "revisions_count": len(revs), "url": svc["uri"],
        "cpu": str(lim["cpu"]), "memory": str(lim["memory"]), "port": str(ports[0]["containerPort"]),
        "instances": "%s-%s" % (sc["minInstanceCount"], sc["maxInstanceCount"] or "unlimited"),
        "concurrency": str(tpl["maxInstanceRequestConcurrency"]), "timeout": tpl["timeout"],
        "service_account": tpl["serviceAccount"],
        "exec_env": tpl["executionEnvironment"].replace("EXECUTION_ENVIRONMENT_", "").title().replace("Gen", "Gen "),
        "cpu_allocation": "CPU is only allocated during request processing" if c0["resources"]["cpuIdle"] else "CPU is always allocated",
        "traffic_text": ", ".join("%s%% → %s" % (t.get("percent", 0), "latest revision" if t.get("type", LATEST) == LATEST else t.get("revision", ""))
                                  for t in svc["traffic"]) or "None",
        "revisions_text": ", ".join(r["name"].rsplit("/", 1)[-1] for r in revs) or "None",
        "labels_text": ", ".join("%s=%s" % kv for kv in sorted((svc.get("labels") or {}).items())) or "None",
        "description_text": svc.get("description") or "No description",
        "created": svc["createTime"], "creator_text": svc["creator"],
        "data_plane": "Control plane (containers are not executed below the Pro tier)",
        "status": "Ready",
    })
    return v


def list_all(store, project=None):
    """Console grid: every service (optionally for one project)."""
    return [console_view(store, n) for n in sorted(store.services)
            if project is None or n.startswith("projects/%s/" % project)]


def view_by_name(store, full):
    return console_view(store, full)


def job_from_form(b, project="demo"):
    """Console create form (catalog createFields) → REST body + query for services.create, shared
    by the offline console REST and the Nano adapter so both consoles create identical services."""
    location = str(b.get("region") or b.get("location") or "us-central1")
    sid = str(b.get("name") or "").strip()

    def num(key, default):
        v = b.get(key)
        try:
            return int(v) if v not in (None, "") else default
        except (TypeError, ValueError):
            return -1

    container = {"image": str(b.get("image") or DEFAULT_IMAGE).strip(),
                 "ports": [{"containerPort": num("port", 8080)}],
                 "resources": {"limits": {"cpu": str(b.get("cpu") or "1"), "memory": str(b.get("memory") or "512Mi")}}}
    tpl = {"containers": [container], "scaling": {"minInstanceCount": num("minInstances", 0),
                                                  "maxInstanceCount": num("maxInstances", 100)},
           "maxInstanceRequestConcurrency": num("concurrency", 80),
           "timeout": "%ss" % num("timeoutSeconds", 300)}
    ingress = str(b.get("ingress") or "all").lower()
    body = {"template": tpl,
            "ingress": {"all": "INGRESS_TRAFFIC_ALL", "internal": "INGRESS_TRAFFIC_INTERNAL_ONLY",
                        "internal-and-cloud-load-balancing": "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"}.get(ingress, "INGRESS_TRAFFIC_ALL")}
    if b.get("description"):
        body["description"] = str(b["description"])
    if isinstance(b.get("labels"), dict) and b["labels"]:
        body["labels"] = b["labels"]
    unauth = str(b.get("allowUnauthenticated", "true")).lower() in ("true", "yes", "1", "allow unauthenticated")
    return {"parent": "projects/%s/locations/%s" % (project, location), "location": location, "serviceId": sid,
            "service": body, "allowUnauthenticated": unauth}


# ── Knative v1 façade (what `gcloud run services|revisions ...` speaks) ─────────────────────────
# gcloud's Cloud Run commands use the regional Knative-style API
#   {region}-run.googleapis.com/apis/serving.knative.dev/v1/namespaces/{project}/services[/{name}]
# rather than the v2 Admin API. It is a second view of the SAME services and revisions: the region
# comes from the Host header's `{region}-` prefix; bodies are converted to/from the v2 resources.
_KN = "apis/serving.knative.dev/v1/namespaces/"
_KN_DOM = "apis/domains.cloudrun.com/v1/namespaces/"   # `gcloud run domain-mappings ...`
_INGRESS_KN = {"all": "INGRESS_TRAFFIC_ALL", "internal": "INGRESS_TRAFFIC_INTERNAL_ONLY",
               "internal-and-cloud-load-balancing": "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER", "none": "INGRESS_TRAFFIC_NONE"}
_INGRESS_V2 = {v: k for k, v in _INGRESS_KN.items()}


def _kn_region(headers):
    for k, v in headers.items():
        if k.lower() == "host":
            m = re.match(r"^([a-z]+-[a-z]+[0-9]+)-", str(v))
            if m:
                return m.group(1)
    return "us-central1"


def _kn_conditions(conds):
    return [{"type": c["type"], "status": "True", "lastTransitionTime": c["lastTransitionTime"]} for c in conds]


def _kn_service(store, full):
    svc = store.services[full]
    parts = full.split("/")
    project, location, sid = parts[1], parts[3], parts[5]
    t = svc["template"]
    ann = dict(svc.get("annotations") or {})
    ann["run.googleapis.com/ingress"] = _INGRESS_V2.get(svc["ingress"], "all")
    ann["run.googleapis.com/urls"] = json.dumps(svc.get("urls") or [svc["uri"]])
    ann["serving.knative.dev/creator"] = svc["creator"]
    ann["serving.knative.dev/lastModifier"] = svc["lastModifier"]
    tann = {"autoscaling.knative.dev/maxScale": str(t["scaling"]["maxInstanceCount"])}
    if t["scaling"]["minInstanceCount"]:
        tann["autoscaling.knative.dev/minScale"] = str(t["scaling"]["minInstanceCount"])
    tann["run.googleapis.com/execution-environment"] = "gen2" if t["executionEnvironment"].endswith("GEN2") else "gen1"
    containers = []
    for c in t["containers"]:
        kc = {"name": c.get("name", ""), "image": c["image"], "resources": {"limits": dict(c["resources"]["limits"])}}
        for key in ("command", "args", "env", "ports"):
            if c.get(key):
                kc[key] = c[key]
        containers.append(kc)
    traffic = []
    for tt in svc["traffic"]:
        e = {"percent": tt.get("percent", 0)}
        if tt.get("type", LATEST) == LATEST:
            e["latestRevision"] = True
        else:
            e["revisionName"] = tt.get("revision", "")
        if tt.get("tag"):
            e["tag"] = tt["tag"]
        traffic.append(e)
    latest = (svc.get("latestReadyRevision") or "").rsplit("/", 1)[-1]
    return {"apiVersion": "serving.knative.dev/v1", "kind": "Service",
            "metadata": {"name": sid, "namespace": project, "uid": svc["uid"], "resourceVersion": "AAZ" + svc["generation"],
                         "generation": int(svc["generation"]), "creationTimestamp": svc["createTime"],
                         "selfLink": "/apis/serving.knative.dev/v1/namespaces/%s/services/%s" % (project, sid),
                         "labels": dict(svc.get("labels") or {}, **{"cloud.googleapis.com/location": location}),
                         "annotations": ann},
            "spec": {"template": {"metadata": {"name": latest, "annotations": tann, "labels": {}},
                                  "spec": {"containerConcurrency": t["maxInstanceRequestConcurrency"],
                                           "timeoutSeconds": int(float(t["timeout"][:-1])),
                                           "serviceAccountName": t["serviceAccount"], "containers": containers}},
                     "traffic": traffic},
            "status": {"observedGeneration": int(svc["observedGeneration"]), "conditions": _kn_conditions(svc["conditions"]),
                       "latestReadyRevisionName": latest, "latestCreatedRevisionName": latest,
                       "traffic": [dict({"revisionName": ts["revision"], "percent": ts["percent"]},
                                        **({"latestRevision": True} if ts["type"] == LATEST else {}))
                                   for ts in svc["trafficStatuses"]],
                       "url": svc["uri"], "address": {"url": svc["uri"]}}}


def _kn_to_v2(body):
    """A Knative Service body → the v2 Service fields it sets."""
    meta, spec = body.get("metadata") or {}, body.get("spec") or {}
    out = {}
    ann = dict(meta.get("annotations") or {})
    ing = ann.pop("run.googleapis.com/ingress", None)
    for k in [k for k in ann if k.startswith(("serving.knative.dev/", "run.googleapis.com/urls", "run.googleapis.com/operation-id"))]:
        ann.pop(k)
    labels = {}
    for k, v in (meta.get("labels") or {}).items():
        if k == "cloud.googleapis.com/location":
            continue
        if _LABEL.match(str(k)):
            labels[k] = v
        else:   # Knative-qualified labels (client.knative.dev/nonce, ...) aren't v2 labels; keep them as annotations
            ann[k] = v
    out["labels"], out["annotations"] = labels, ann
    if ing:
        out["ingress"] = _INGRESS_KN.get(ing, ing)
    tpl = spec.get("template") or {}
    tmeta, tspec = tpl.get("metadata") or {}, tpl.get("spec") or {}
    tann = tmeta.get("annotations") or {}
    v2t = {"containers": [dict(c) for c in tspec.get("containers") or []]}
    for c in v2t["containers"]:
        if not c.get("name"):
            c.pop("name", None)
    scaling = {}
    if "autoscaling.knative.dev/minScale" in tann:
        scaling["minInstanceCount"] = int(tann["autoscaling.knative.dev/minScale"])
    if "autoscaling.knative.dev/maxScale" in tann:
        scaling["maxInstanceCount"] = int(tann["autoscaling.knative.dev/maxScale"])
    if scaling:
        v2t["scaling"] = scaling
    if tspec.get("containerConcurrency") is not None:
        v2t["maxInstanceRequestConcurrency"] = tspec["containerConcurrency"]
    if tspec.get("timeoutSeconds"):
        v2t["timeout"] = "%ds" % tspec["timeoutSeconds"]
    if tspec.get("serviceAccountName"):
        v2t["serviceAccount"] = tspec["serviceAccountName"]
    if tann.get("run.googleapis.com/execution-environment"):
        v2t["executionEnvironment"] = "EXECUTION_ENVIRONMENT_" + tann["run.googleapis.com/execution-environment"].upper()
    if tmeta.get("name"):
        v2t["revision"] = tmeta["name"]
    tl = {k: v for k, v in (tmeta.get("labels") or {}).items() if _LABEL.match(str(k))}
    if tl:
        v2t["labels"] = tl
    out["template"] = v2t
    traffic = []
    for tt in spec.get("traffic") or []:
        e = {"percent": tt.get("percent", 0)}
        if tt.get("revisionName"):
            e.update({"type": REVISION, "revision": tt["revisionName"]})
        else:
            e["type"] = LATEST
        if tt.get("tag"):
            e["tag"] = tt["tag"]
        traffic.append(e)
    if traffic:
        out["traffic"] = traffic
    return out


def _kn_revision(store, rev):
    t = rev
    sname = rev["service"].rsplit("/", 1)[-1]
    short = rev["name"].rsplit("/", 1)[-1]
    containers = [{"name": c.get("name", ""), "image": c["image"], "resources": {"limits": dict(c["resources"]["limits"])}}
                  for c in t["containers"]]
    return {"apiVersion": "serving.knative.dev/v1", "kind": "Revision",
            "metadata": {"name": short, "namespace": rev["name"].split("/")[1], "uid": rev["uid"], "generation": 1,
                         "creationTimestamp": rev["createTime"],
                         "labels": {"serving.knative.dev/service": sname, "serving.knative.dev/configuration": sname,
                                    "cloud.googleapis.com/location": rev["name"].split("/")[3]},
                         "annotations": {"serving.knative.dev/creator": "admin@vyomi.cloud"},
                         "ownerReferences": [{"kind": "Service", "name": sname, "apiVersion": "serving.knative.dev/v1"}]},
            "spec": {"containerConcurrency": t["maxInstanceRequestConcurrency"], "timeoutSeconds": int(float(t["timeout"][:-1])),
                     "serviceAccountName": t["serviceAccount"], "containers": containers},
            "status": {"observedGeneration": 1, "conditions": _kn_conditions(rev["conditions"]), "logUrl": rev["logUri"]}}


def _kn_status(code, status, message):
    return _json(code, {"kind": "Status", "apiVersion": "v1", "metadata": {}, "status": status, "message": message, "code": code})


def _knative(store, method, ns, rest, query, headers, payload):
    region = _kn_region(headers)
    try:
        if rest[0] == "services":
            if len(rest) == 1 and method == "GET":
                names = sorted(n for n in store.services if n.startswith("projects/%s/locations/%s/services/" % (ns, region)))
                return _json(200, {"apiVersion": "serving.knative.dev/v1", "kind": "ServiceList", "metadata": {},
                                   "items": [_kn_service(store, n) for n in names]})
            if len(rest) == 1 and method == "POST":
                sid = (payload.get("metadata") or {}).get("name") or ""
                op = create_service(store, ns, region, {"serviceId": sid}, _kn_to_v2(payload))
                return _json(200, _kn_service(store, service_name(ns, region, sid)))
            if len(rest) == 2:
                full, svc = _get_service(store, ns, region, rest[1])
                if method == "GET":
                    return _json(200, _kn_service(store, full))
                if method == "PUT":
                    update_service(store, ns, region, rest[1], {}, _kn_to_v2(payload))
                    return _json(200, _kn_service(store, full))
                if method == "DELETE":
                    delete_service(store, ns, region, rest[1], {})
                    return _kn_status(200, "Success", "")
        elif rest[0] == "revisions":
            if len(rest) == 1 and method == "GET":
                want = ""
                for sel in (query.get("labelSelector") or "").split(","):
                    if sel.startswith("serving.knative.dev/service="):
                        want = sel.split("=", 1)[1]
                revs = sorted((r for r in store.revisions.values() if r["name"].startswith("projects/%s/locations/%s/" % (ns, region))
                               and (not want or r["service"].rsplit("/", 1)[-1] == want)), key=lambda r: (r["createTime"], r["name"]), reverse=True)
                return _json(200, {"apiVersion": "serving.knative.dev/v1", "kind": "RevisionList", "metadata": {},
                                   "items": [_kn_revision(store, r) for r in revs]})
            if len(rest) == 2:
                rev = next((r for r in store.revisions.values() if r["name"].startswith("projects/%s/locations/%s/" % (ns, region))
                            and r["name"].rsplit("/", 1)[-1] == rest[1]), None)
                if not rev:
                    raise _E(404, "NOT_FOUND", "Revision '%s' does not exist." % rest[1])
                if method == "GET":
                    return _json(200, _kn_revision(store, rev))
                if method == "DELETE":
                    delete_revision(store, ns, region, rev["service"].rsplit("/", 1)[-1], rest[1], {})
                    return _kn_status(200, "Success", "")
    except _E as e:
        return _err(e.status, e.gcp_status, e.message)
    return _err(404, "NOT_FOUND", "Unknown path or method: %s %s" % (method, "/".join(rest)))


# ── dispatch ───────────────────────────────────────────────────────────────
def dispatch(store, method, path, query=None, headers=None, body=b"", log_fn=None, topic_exists=None):
    return _dispatch(store, method, path, query or {}, headers or {}, body, log_fn=log_fn, topic_exists=topic_exists)


def _dispatch(store, method, path, query, headers, body, log_fn=None, topic_exists=None):
    method = method.upper()
    for k, v in headers.items():   # REST clients without PATCH/PUT tunnel them over POST
        if k.lower() == "x-http-method-override" and method == "POST" and v:
            method = str(v).upper()
    try:
        payload = json.loads(body.decode("utf-8")) if body else {}
    except Exception:
        return _err(400, "INVALID_ARGUMENT", "Invalid JSON payload received.")
    if not isinstance(payload, dict):
        payload = {}
    p = path.split("?", 1)[0]
    if p.lstrip("/").startswith(_KN):
        segs = [x for x in p.lstrip("/")[len(_KN):].split("/") if x]
        if len(segs) < 2:
            return _err(404, "NOT_FOUND", "Unknown path: %s" % path)
        return _knative(store, method, segs[0], segs[1:], query, headers, payload)
    if p.lstrip("/").startswith(_KN_DOM):
        segs = [x for x in p.lstrip("/")[len(_KN_DOM):].split("/") if x]
        if len(segs) < 2 or segs[1] != "domainmappings":
            return _err(404, "NOT_FOUND", "Unknown path: %s" % path)
        return _domain_mappings_dispatch(store, method, segs[0], _kn_region(headers), segs[2:], query, payload)
    for pre in ("/v2", "/v1"):   # /v1 only carries the v1 Admin IAM verbs on services (gcloud run)
        if p.startswith(pre + "/"):
            p = p[len(pre):]
            break
    p = p.strip("/")
    verb = ""
    if ":" in p:
        p, verb = p.rsplit(":", 1)
    segs = [s for s in p.split("/") if s]
    if len(segs) < 4 or segs[0] != "projects" or segs[2] != "locations":
        return _err(404, "NOT_FOUND", "Unknown path: %s" % path)
    project, location = segs[1], segs[3]
    rest = segs[4:]
    try:
        if not rest:
            return _err(404, "NOT_FOUND", "Unknown path: %s" % path)
        kind = rest[0]
        if path.startswith("/v1/") and kind != "services":
            return _err(404, "NOT_FOUND", "Unknown path: %s" % path)
        if kind == "services":
            return _services(store, method, project, location, rest[1:], verb, query, payload,
                             log_fn=log_fn, topic_exists=topic_exists)
        if kind == "jobs":
            return _jobs(store, method, project, location, rest[1:], verb, query, payload, log_fn=log_fn)
        if kind == "workerPools":
            return _worker_pools_dispatch(store, method, project, location, rest[1:], verb, query, payload)
        if kind == "operations":
            return _operations(store, method, project, location, rest[1:], verb, query)
        return _err(404, "NOT_FOUND", "Unknown path: %s" % path)
    except _E as e:
        return _err(e.status, e.gcp_status, e.message)


def _iam_verb(store, full, method, verb, query, payload):
    if verb == "getIamPolicy" and method in ("GET", "POST"):
        return _json(200, get_iam_policy(store, full, query))
    if verb == "setIamPolicy" and method == "POST":
        return _json(200, set_iam_policy(store, full, payload))
    if verb == "testIamPermissions" and method == "POST":
        perms = payload.get("permissions") or []
        return _json(200, {"permissions": [x for x in perms if x in PERMISSIONS]})
    return None


def _services(store, method, project, location, rest, verb, query, payload, log_fn=None, topic_exists=None):
    if not rest:
        if method == "POST" and not verb:
            op = create_service(store, project, location, query, payload)
            if log_fn and query.get("validateOnly") not in ("true", "True", True):
                sid = op["response"]["name"].rsplit("/", 1)[-1]
                image = op["response"]["template"]["containers"][0]["image"]
                log_fn("service", project, location, sid, "Service %s created (image %s)" % (sid, image))
            return _json(200, op)
        if method == "GET" and not verb:
            _check_location(location)
            names = sorted(n for n in store.services if n.startswith("projects/%s/locations/%s/services/" % (project, location)))
            chunk, nxt = _page(names, query)
            out = {"services": [service_view(store.services[n]) for n in chunk]}
            if nxt:
                out["nextPageToken"] = nxt
            return _json(200, out)
    elif len(rest) == 1:
        sid = rest[0]
        full = service_name(project, location, sid)
        if verb:
            _get_service(store, project, location, sid)
            r = _iam_verb(store, full, method, verb, query, payload)
            if r:
                if verb == "setIamPolicy" and method == "POST" and log_fn:
                    public = public_invoker(store, full)
                    log_fn("service", project, location, sid, "Authentication changed for service %s: %s"
                           % (sid, "allow unauthenticated" if public else "require authentication"))
                return r
        elif method == "GET":
            return _json(200, service_view(_get_service(store, project, location, sid)[1]))
        elif method == "PATCH":
            before_rev = (store.services.get(full) or {}).get("latestCreatedRevision")
            op = update_service(store, project, location, sid, query, payload)
            if log_fn and query.get("validateOnly") not in ("true", "True", True):
                after_rev = op["response"].get("latestCreatedRevision")
                if after_rev and after_rev != before_rev:
                    image = op["response"]["template"]["containers"][0]["image"]
                    log_fn("service", project, location, sid, "New revision deployed for service %s (image %s)" % (sid, image))
                else:
                    fields = ", ".join(_mask_fields(query, _norm_enums(payload))) or "configuration"
                    log_fn("service", project, location, sid, "Service %s updated (%s)" % (sid, fields))
            return _json(200, op)
        elif method == "DELETE":
            op = delete_service(store, project, location, sid, query)
            if log_fn and query.get("validateOnly") not in ("true", "True", True):
                log_fn("service", project, location, sid, "Service %s deleted" % sid)
            return _json(200, op)
    elif rest[1] == "revisions":
        sid = rest[0]
        if len(rest) == 2 and method == "GET" and not verb:
            _get_service(store, project, location, sid)
            full = service_name(project, location, sid)
            revs = sorted((r for r in store.revisions.values() if r["service"] == full), key=lambda r: (r["createTime"], r["name"]), reverse=True)
            chunk, nxt = _page(revs, query)
            out = {"revisions": [revision_view(r) for r in chunk]}
            if nxt:
                out["nextPageToken"] = nxt
            return _json(200, out)
        if len(rest) == 3 and not verb:
            if method == "GET":
                return _json(200, revision_view(_get_revision(store, project, location, sid, rest[2])[1]))
            if method == "DELETE":
                return _json(200, delete_revision(store, project, location, sid, rest[2], query))
    elif rest[1] == "eventarcTriggers":
        sid = rest[0]
        if len(rest) == 2 and not verb:
            if method == "GET":
                _get_service(store, project, location, sid)
                return _json(200, {"triggers": list_event_triggers(store, project, location, sid)})
            if method == "POST":
                return _json(200, create_event_trigger(store, project, location, sid, query, payload, topic_exists=topic_exists))
        if len(rest) == 3 and not verb:
            if method == "GET":
                return _json(200, trigger_view(_get_event_trigger(store, project, location, sid, rest[2])[1]))
            if method == "DELETE":
                return _json(200, delete_event_trigger(store, project, location, sid, rest[2]))
    return _err(404, "NOT_FOUND", "Unknown path or method: %s %s" % (method, "/".join(rest)))


def _jobs(store, method, project, location, rest, verb, query, payload, log_fn=None):
    if not rest:
        if method == "POST" and not verb:
            op = create_job(store, project, location, query, payload)
            if log_fn and query.get("validateOnly") not in ("true", "True", True):
                jid = op["response"]["name"].rsplit("/", 1)[-1]
                log_fn("job", project, location, jid, "Job %s created" % jid)
            return _json(200, op)
        if method == "GET" and not verb:
            _check_location(location)
            names = sorted(n for n in store.jobs if n.startswith("projects/%s/locations/%s/jobs/" % (project, location)))
            chunk, nxt = _page(names, query)
            out = {"jobs": [job_view(store.jobs[n]) for n in chunk]}
            if nxt:
                out["nextPageToken"] = nxt
            return _json(200, out)
    elif len(rest) == 1:
        jid = rest[0]
        full = job_name(project, location, jid)
        if verb == "run" and method == "POST":
            op = run_job(store, project, location, jid, payload)
            if log_fn:
                eid = op["response"]["name"].rsplit("/", 1)[-1]
                log_fn("job", project, location, jid, "Execution %s started (%d task(s))" % (eid, op["response"]["taskCount"]))
            return _json(200, op)
        if verb:
            _get_job(store, project, location, jid)
            r = _iam_verb(store, full, method, verb, query, payload)
            if r:
                return r
        elif method == "GET":
            return _json(200, job_view(_get_job(store, project, location, jid)[1]))
        elif method == "PATCH":
            op = update_job(store, project, location, jid, query, payload)
            if log_fn and query.get("validateOnly") not in ("true", "True", True):
                log_fn("job", project, location, jid, "Job %s updated" % jid)
            return _json(200, op)
        elif method == "DELETE":
            op = delete_job(store, project, location, jid, query)
            if log_fn and query.get("validateOnly") not in ("true", "True", True):
                log_fn("job", project, location, jid, "Job %s deleted" % jid)
            return _json(200, op)
    elif rest[1] == "executions":
        jid = rest[0]
        if len(rest) == 2 and method == "GET" and not verb:
            _get_job(store, project, location, jid)
            full = job_name(project, location, jid)
            exs = sorted((e for n, e in store.executions.items() if n.startswith(full + "/executions/")),
                         key=lambda e: (e["createTime"], e["name"]), reverse=True)
            chunk, nxt = _page(exs, query)
            out = {"executions": [_copy(e) for e in chunk]}
            if nxt:
                out["nextPageToken"] = nxt
            return _json(200, out)
        if len(rest) == 3:
            if verb == "cancel" and method == "POST":
                return _json(200, cancel_execution(store, project, location, jid, rest[2]))
            if not verb and method == "GET":
                return _json(200, _copy(_get_execution(store, project, location, jid, rest[2])[1]))
            if not verb and method == "DELETE":
                return _json(200, delete_execution(store, project, location, jid, rest[2], query))
        if len(rest) >= 4 and rest[3] == "tasks" and not verb and method == "GET":
            _, ex = _get_execution(store, project, location, jid, rest[2])
            if len(rest) == 4:
                prefix = ex["name"] + "/tasks/"
                ts = sorted((t for n, t in store.tasks.items() if n.startswith(prefix)), key=lambda t: t["index"])
                chunk, nxt = _page(ts, query)
                out = {"tasks": [_copy(t) for t in chunk]}
                if nxt:
                    out["nextPageToken"] = nxt
                return _json(200, out)
            t = store.tasks.get("%s/tasks/%s" % (ex["name"], rest[4]))
            if not t:
                raise _E(404, "NOT_FOUND", "Task '%s' of execution '%s' does not exist." % (rest[4], rest[2]))
            return _json(200, _copy(t))
    return _err(404, "NOT_FOUND", "Unknown path or method: %s %s" % (method, "/".join(rest)))


def worker_pool_name(project, location, wid):
    return "projects/%s/locations/%s/workerPools/%s" % (project, location, wid)


def _settle_worker_pool(store, full, wp, now):
    wp["updateTime"] = now
    wp["observedGeneration"] = wp["generation"]
    wp["reconciling"] = False
    wp["conditions"] = _conditions(now, "Ready", "ConfigurationsReady")
    wp["terminalCondition"] = wp["conditions"][0]
    wp["etag"] = '"%s"' % _h("wp", full, wp["generation"], now)[:16]


def worker_pool_view(wp):
    return {k: _copy(v) for k, v in wp.items() if not k.startswith("_")}


def create_worker_pool(store, project, location, query, payload):
    _check_location(location)
    wid = query.get("workerPoolId") or ""
    if not wid:
        raise _E(400, "INVALID_ARGUMENT", "Worker pool ID must be specified (workerPoolId).")
    _check_name("worker pool", wid)
    spec = _norm_enums(payload)
    full = worker_pool_name(project, location, wid)
    if full in store.worker_pools:
        raise _E(409, "ALREADY_EXISTS", "Resource '%s' already exists." % full)
    for k in ("labels", "annotations"):
        if spec.get(k) is not None:
            _check_map(spec[k], k)
    template = _revision_template(project, spec.get("template"), False)
    now = _ts()
    wp = {"name": full, "description": spec.get("description", ""), "uid": _uid(store, "wp", full),
          "generation": "1", "labels": spec.get("labels", {}) or {}, "annotations": spec.get("annotations", {}) or {},
          "createTime": now, "creator": "admin@vyomi.cloud", "lastModifier": "admin@vyomi.cloud",
          "client": spec.get("client", ""), "clientVersion": spec.get("clientVersion", ""),
          "launchStage": spec.get("launchStage") or "GA", "template": template, "instanceSplits": []}
    if query.get("validateOnly") in ("true", "True", True):
        return _operation(store, project, location, "workerpool", worker_pool_view(wp))
    store.worker_pools[full] = wp
    _settle_worker_pool(store, full, wp, now)
    return _operation(store, project, location, "workerpool", worker_pool_view(wp))


def _get_worker_pool(store, project, location, wid):
    full = worker_pool_name(project, location, wid)
    wp = store.worker_pools.get(full)
    if not wp:
        raise _E(404, "NOT_FOUND", "Resource '%s' of kind 'WORKER_POOL' in region '%s' in project '%s' does not exist." % (wid, location, project))
    return full, wp


def delete_worker_pool(store, project, location, wid, query):
    full, wp = _get_worker_pool(store, project, location, wid)
    view = worker_pool_view(wp)
    now = _ts()
    view["deleteTime"] = now
    view["expireTime"] = now
    if query.get("validateOnly") not in ("true", "True", True):
        del store.worker_pools[full]
        store.policies.pop(full, None)
    return _operation(store, project, location, "workerpool", view)


def worker_pool_console_view(wp):
    seg = wp["name"].split("/")
    c0 = wp["template"]["containers"][0]
    lim = c0["resources"]["limits"]
    v = worker_pool_view(wp)
    v.update({
        "id": seg[5], "resourceName": wp["name"], "project": seg[1], "region": seg[3],
        "image": c0["image"], "cpu": str(lim["cpu"]), "memory": str(lim["memory"]),
        "instances": "%s-%s" % (wp["template"]["scaling"]["minInstanceCount"], wp["template"]["scaling"]["maxInstanceCount"] or "unlimited"),
        "last_deployed": wp["updateTime"], "deployed_by": wp["lastModifier"], "created": wp["createTime"],
        "labels_text": ", ".join("%s=%s" % kv for kv in sorted((wp.get("labels") or {}).items())) or "None",
        "status": "Ready",
    })
    return v


def list_worker_pools(store, project=None):
    return [worker_pool_console_view(store.worker_pools[n]) for n in sorted(store.worker_pools)
            if project is None or n.startswith("projects/%s/" % project)]


# ── domain mappings (v1 domains.cloudrun.com) ───────────────────────────────
_DOMAIN = re.compile(r"^(\*\.)?([a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?\.)+[a-z]{2,}$")
CERT_MODES = ("AUTOMATIC", "NONE")


def domain_mapping_name(project, location, domain):
    return "projects/%s/locations/%s/domainmappings/%s" % (project, location, domain)


def _dns_records(domain, cert_mode):
    apex = domain.count(".") == 1   # "example.com" (no subdomain) needs A/AAAA, not CNAME
    if apex:
        out = [{"name": domain, "type": "A", "rrdata": ip} for ip in ("216.239.32.21", "216.239.34.21", "216.239.36.21", "216.239.38.21")]
    else:
        out = [{"name": domain, "type": "CNAME", "rrdata": "ghs.googlehosted.com."}]
    if cert_mode == "AUTOMATIC":
        out.append({"name": domain, "type": "TXT", "rrdata": '"google-site-verification=%s"' % _h("dv", domain)[:32]})
    return out


def create_domain_mapping(store, project, location, query, payload):
    _check_location(location)
    meta = (payload or {}).get("metadata") or {}
    domain = meta.get("name") or ""
    if not domain or not _DOMAIN.match(domain):
        raise _E(400, "INVALID_ARGUMENT", "Invalid domain name %r." % domain)
    full = domain_mapping_name(project, location, domain)
    if full in store.domain_mappings:
        raise _E(409, "ALREADY_EXISTS", "Resource '%s' already exists." % full)
    spec = (payload or {}).get("spec") or {}
    route = spec.get("routeName") or ""
    if not route:
        raise _E(400, "INVALID_ARGUMENT", "spec.routeName is required.")
    if route not in {n.rsplit("/", 1)[-1] for n in store.services
                      if n.startswith("projects/%s/locations/%s/services/" % (project, location))}:
        raise _E(400, "INVALID_ARGUMENT", "Service '%s' referenced by routeName does not exist." % route)
    cert_mode = spec.get("certificateMode") or "AUTOMATIC"
    if cert_mode not in CERT_MODES:
        raise _E(400, "INVALID_ARGUMENT", "Invalid certificateMode %r; valid: %s." % (cert_mode, ", ".join(CERT_MODES)))
    now = _ts()
    records = _dns_records(domain, cert_mode)
    dm = {"apiVersion": "domains.cloudrun.com/v1", "kind": "DomainMapping",
          "metadata": {"name": domain, "namespace": project, "creationTimestamp": now,
                       "labels": meta.get("labels") or {}, "annotations": meta.get("annotations") or {},
                       "uid": _uid(store, "dm", full), "generation": 1, "resourceVersion": "1"},
          "spec": {"routeName": route, "certificateMode": cert_mode, "forceOverride": bool(spec.get("forceOverride", False))},
          "status": {"resourceRecords": records, "mappedRouteName": route,
                      "conditions": [{"type": "Ready", "status": "True", "lastTransitionTime": now},
                                     {"type": "CertificateProvisioned", "status": "True" if cert_mode == "AUTOMATIC" else "Unknown",
                                      "lastTransitionTime": now}],
                      "observedGeneration": 1}}
    if query.get("validateOnly") in ("true", "True", True):
        return _operation(store, project, location, "domainmapping", _copy(dm))
    store.domain_mappings[full] = dm
    return _operation(store, project, location, "domainmapping", _copy(dm))


def _get_domain_mapping(store, project, location, domain):
    full = domain_mapping_name(project, location, domain)
    dm = store.domain_mappings.get(full)
    if not dm:
        raise _E(404, "NOT_FOUND", "Resource '%s' of kind 'DOMAIN_MAPPING' in region '%s' in project '%s' does not exist." % (domain, location, project))
    return full, dm


def delete_domain_mapping(store, project, location, domain, query):
    full, dm = _get_domain_mapping(store, project, location, domain)
    view = _copy(dm)
    if query.get("validateOnly") not in ("true", "True", True):
        del store.domain_mappings[full]
    return _operation(store, project, location, "domainmapping", view)


def domain_mapping_console_view(dm):
    v = _copy(dm)
    v.update({
        "id": dm["metadata"]["name"], "domain": dm["metadata"]["name"], "resourceName": dm["metadata"]["name"],
        "route": dm["spec"]["routeName"], "certificate": "Automatic" if dm["spec"]["certificateMode"] == "AUTOMATIC" else "None",
        "status": "Ready" if any(c["type"] == "Ready" and c["status"] == "True" for c in dm["status"]["conditions"]) else "Pending",
        "records_text": ", ".join("%s %s" % (r["type"], r["rrdata"]) for r in dm["status"]["resourceRecords"]),
        "created": dm["metadata"]["creationTimestamp"],
    })
    return v


def list_domain_mappings(store, project=None):
    return [domain_mapping_console_view(dm) for n, dm in sorted(store.domain_mappings.items())
            if project is None or n.startswith("projects/%s/" % project)]


# ── Eventarc-style triggers (services/{s}/eventarcTriggers/{t}) ─────────────────────────────
# Vyomi has no eventarc.googleapis.com. A trigger is modelled as a Cloud Run service
# sub-resource bound to a Pub/Sub topic (the real transport a Pub/Sub-type Eventarc trigger
# uses under the hood): publishing to that topic really calls invoke_service for the
# destination service (see deliver_event, wired from the Pub/Sub core's publish path in
# core/aws_wire_router.py / routes/gcp_pubsub_unified.py), and the delivery is written to
# Cloud Logging so the console's Observability tab shows it.
_TOPIC_RE = re.compile(r"^projects/[^/]+/topics/[^/]+$")


def event_trigger_name(project, location, sid, tid):
    return "%s/eventarcTriggers/%s" % (service_name(project, location, sid), tid)


def trigger_view(rec):
    return {k: _copy(v) for k, v in rec.items() if not k.startswith("_")}


def create_event_trigger(store, project, location, sid, query, payload, topic_exists=None):
    full_svc, _ = _get_service(store, project, location, sid)
    tid = str(query.get("eventarcTriggerId") or "").strip()
    if not tid:
        raise _E(400, "INVALID_ARGUMENT", "eventarcTriggerId must be specified.")
    _check_name("trigger", tid)
    full = event_trigger_name(project, location, sid, tid)
    if full in store.event_triggers:
        raise _E(409, "ALREADY_EXISTS", "Resource '%s' already exists." % full)
    topic = str(((payload or {}).get("transport") or {}).get("pubsub", {}).get("topic") or "").strip()
    if not topic:
        raise _E(400, "INVALID_ARGUMENT", "transport.pubsub.topic is required.")
    if not _TOPIC_RE.match(topic):
        raise _E(400, "INVALID_ARGUMENT", "Invalid topic resource name %r; expected projects/{p}/topics/{t}." % topic)
    if topic_exists is not None and not topic_exists(topic):
        raise _E(400, "INVALID_ARGUMENT", "Pub/Sub topic %r does not exist." % topic)
    now = _ts()
    rec = {
        "name": full, "uid": _uid(store, "trg", full), "createTime": now, "updateTime": now,
        "eventFilters": [{"attribute": "type", "value": "google.cloud.pubsub.topic.v1.messagePublished"}],
        "serviceAccount": (payload or {}).get("serviceAccount") or
                           "%s-compute@developer.gserviceaccount.com" % project_number(project),
        "destination": {"cloudRun": {"service": sid, "region": location, "path": "/"}},
        "transport": {"pubsub": {"topic": topic}},
        "labels": (payload or {}).get("labels") or {},
        "etag": '"%s"' % _h("trg", full, now)[:16],
        "_eventCount": 0, "_lastEventTime": "", "_lastError": "",
    }
    store.event_triggers[full] = rec
    return trigger_view(rec)


def list_event_triggers(store, project, location, sid):
    prefix = service_name(project, location, sid) + "/eventarcTriggers/"
    return [trigger_view(t) for n, t in sorted(store.event_triggers.items()) if n.startswith(prefix)]


def _get_event_trigger(store, project, location, sid, tid):
    full = event_trigger_name(project, location, sid, tid)
    t = store.event_triggers.get(full)
    if not t:
        raise _E(404, "NOT_FOUND", "Trigger '%s' of service '%s' does not exist." % (tid, sid))
    return full, t


def delete_event_trigger(store, project, location, sid, tid):
    full, _ = _get_event_trigger(store, project, location, sid, tid)
    del store.event_triggers[full]
    return {}


# ── invoke (data-plane-ish; used internally by deliver_event, never exposed over the wire) ──
def invoke_service(store, project, location, sid, headers=None, internal=False):
    """The one thing Vyomi can do without running the container: check the service exists
    and enforce the IAM invoker policy, exactly like the real serving path does before a
    request ever reaches a revision. Internal callers (Eventarc delivery) skip the IAM check —
    the trigger's service account is granted run.invoker automatically, as in real Eventarc."""
    full, svc = _get_service(store, project, location, sid)
    if not internal and not public_invoker(store, full):
        auth = ""
        for k, v in (headers or {}).items():
            if k.lower() == "authorization":
                auth = str(v)
                break
        if not auth.lower().startswith("bearer ") or len(auth) < 15:
            raise _E(403, "PERMISSION_DENIED",
                     "The request was not authenticated. Either allow unauthenticated invocations "
                     "or include a valid Authorization: Bearer token.")
    return full, svc


def deliver_event(store, topic_full, messages, log_fn=None):
    """A real Pub/Sub publish on `topic_full` -> deliver to every trigger bound to it (never
    raises: a delivery failure is recorded on the trigger and logged, not propagated to the
    publisher — exactly like real Eventarc, which acks the publish independently of delivery)."""
    if not messages:
        return
    for full, trg in list(store.event_triggers.items()):
        if (((trg.get("transport") or {}).get("pubsub") or {}).get("topic")) != topic_full:
            continue
        parts = full.split("/")
        project, location, sid, tid = parts[1], parts[3], parts[5], parts[7]
        try:
            invoke_service(store, project, location, sid, internal=True)
            trg["_eventCount"] = trg.get("_eventCount", 0) + len(messages)
            trg["_lastEventTime"] = _ts()
            trg["_lastError"] = ""
            if log_fn:
                log_fn("service", project, location, sid,
                       "Eventarc trigger %s delivered %d event(s) from %s" % (tid, len(messages), topic_full))
        except _E as e:
            trg["_lastError"] = e.message
            if log_fn:
                log_fn("service", project, location, sid,
                       "Eventarc trigger %s failed to deliver from %s: %s" % (tid, topic_full, e.message), "ERROR")
        except Exception as e:   # noqa: BLE001 — never let a bad trigger break the publish call
            trg["_lastError"] = str(e)


def _worker_pools_dispatch(store, method, project, location, rest, verb, query, payload):
    if not rest:
        if method == "POST" and not verb:
            return _json(200, create_worker_pool(store, project, location, query, payload))
        if method == "GET" and not verb:
            _check_location(location)
            names = sorted(n for n in store.worker_pools if n.startswith("projects/%s/locations/%s/workerPools/" % (project, location)))
            chunk, nxt = _page(names, query)
            out = {"workerPools": [worker_pool_view(store.worker_pools[n]) for n in chunk]}
            if nxt:
                out["nextPageToken"] = nxt
            return _json(200, out)
    elif len(rest) == 1:
        wid = rest[0]
        full = worker_pool_name(project, location, wid)
        if verb:
            _get_worker_pool(store, project, location, wid)
            r = _iam_verb(store, full, method, verb, query, payload)
            if r:
                return r
        elif method == "GET":
            return _json(200, worker_pool_view(_get_worker_pool(store, project, location, wid)[1]))
        elif method == "DELETE":
            return _json(200, delete_worker_pool(store, project, location, wid, query))
    return _err(404, "NOT_FOUND", "Unknown path or method: %s %s" % (method, "/".join(rest)))


def _domain_mappings_dispatch(store, method, project, location, rest, query, payload):
    try:
        if not rest:
            if method == "POST":
                return _json(200, create_domain_mapping(store, project, location, query, payload))
            if method == "GET":
                _check_location(location)
                names = sorted(n for n in store.domain_mappings if n.startswith("projects/%s/locations/%s/domainmappings/" % (project, location)))
                chunk, nxt = _page(names, query)
                out = {"items": [_copy(store.domain_mappings[n]) for n in chunk]}
                if nxt:
                    out["nextPageToken"] = nxt
                return _json(200, out)
        elif len(rest) == 1:
            domain = rest[0]
            if method == "GET":
                return _json(200, _copy(_get_domain_mapping(store, project, location, domain)[1]))
            if method == "DELETE":
                return _json(200, delete_domain_mapping(store, project, location, domain, query))
    except _E as e:
        return _err(e.status, e.gcp_status, e.message)
    return _err(404, "NOT_FOUND", "Unknown path or method: %s %s" % (method, "/".join(rest)))


def _operations(store, method, project, location, rest, verb, query):
    prefix = "projects/%s/locations/%s/operations/" % (project, location)
    if not rest and method == "GET" and not verb:
        ops = [o for n, o in sorted(store.operations.items()) if n.startswith(prefix)]
        chunk, nxt = _page(ops, query)
        out = {"operations": _copy(chunk)}
        if nxt:
            out["nextPageToken"] = nxt
        return _json(200, out)
    if len(rest) == 1:
        name = prefix + rest[0]
        op = store.operations.get(name)
        if verb == "wait" and method == "POST":
            if not op:
                raise _E(404, "NOT_FOUND", "Operation %s not found." % name)
            return _json(200, _copy(op))
        if not verb and method == "GET":
            if not op:
                raise _E(404, "NOT_FOUND", "Operation %s not found." % name)
            return _json(200, _copy(op))
        if not verb and method == "DELETE":
            if not op:
                raise _E(404, "NOT_FOUND", "Operation %s not found." % name)
            del store.operations[name]
            return _json(200, {})
    return _err(404, "NOT_FOUND", "Unknown operations path: %s" % "/".join(rest))
