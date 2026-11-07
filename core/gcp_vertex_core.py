"""GCP Vertex AI resource core — substrate-independent. Speaks the native **Vertex AI REST API**
(`aiplatform.googleapis.com` v1/v1beta1: `/v1/projects/{p}/locations/{l}/{collection}...`) and the
Workbench Instances API (`notebooks.googleapis.com` v2) so `google-cloud-aiplatform`,
`gcloud ai ...` and the console all work unchanged against it.

NO fastapi / google-cloud / socket / subprocess imports -> loads under Pyodide, so the SAME file
runs offline and in Nano. Gemini / embedding inference stays in core/ai_models_core (local-LLM
seam); this module is the control plane around it.

Collections (all really stored, listable, creatable, deletable):
  endpoints (+deployModel/undeployModel), models (+upload/copy), datasets, trainingPipelines,
  customJobs, hyperparameterTuningJobs, batchPredictionJobs, pipelineJobs, tuningJobs,
  notebookRuntimeTemplates, notebookRuntimes, indexes (+upsertDatapoints/removeDatapoints),
  indexEndpoints (+deployIndex/undeployIndex/findNeighbors — brute-force vector search over
  the stored datapoints), featureOnlineStores/featureViews, featureGroups/features,
  tensorboards/experiments/runs, metadataStores/{contexts,artifacts,executions},
  Workbench instances (+start/stop), Model Garden publisher-model catalog.

Honest limits: jobs advance PENDING -> RUNNING -> SUCCEEDED on a clock and do not run user
containers; custom-model endpoint `:predict` answers 501 UNIMPLEMENTED (only Gemini /
embedding publisher models are served, by core/ai_models_core).
"""
from __future__ import annotations

import json
import math
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

LOCATIONS = ["us-central1", "us-east1", "us-east4", "us-west1", "us-west4", "europe-west1", "europe-west2", "europe-west4",
             "asia-east1", "asia-northeast1", "asia-south1", "asia-southeast1", "australia-southeast1"]

# collection -> spec. kind: LRO create ("op") or direct resource ("direct"); job: lifecycle family.
SPEC = {
    "endpoints": {"id": "endpointId", "create": "op", "name_required": True, "type": "Endpoint"},
    "models": {"id": "modelId", "create": "op", "name_required": True, "type": "Model"},
    "datasets": {"id": "datasetId", "create": "op", "name_required": True, "type": "Dataset"},
    "trainingPipelines": {"id": "trainingPipelineId", "create": "direct", "job": "PIPELINE_STATE_", "type": "TrainingPipeline"},
    "customJobs": {"id": "customJobId", "create": "direct", "job": "JOB_STATE_", "type": "CustomJob"},
    "hyperparameterTuningJobs": {"id": "hyperparameterTuningJobId", "create": "direct", "job": "JOB_STATE_", "type": "HyperparameterTuningJob"},
    "batchPredictionJobs": {"id": "batchPredictionJobId", "create": "direct", "job": "JOB_STATE_", "type": "BatchPredictionJob"},
    "pipelineJobs": {"id": "pipelineJobId", "create": "direct", "job": "PIPELINE_STATE_", "type": "PipelineJob"},
    "tuningJobs": {"id": "tuningJobId", "create": "direct", "job": "JOB_STATE_", "type": "TuningJob"},
    "notebookRuntimeTemplates": {"id": "notebookRuntimeTemplateId", "create": "op", "name_required": True, "type": "NotebookRuntimeTemplate"},
    "notebookRuntimes": {"id": "notebookRuntimeId", "create": "op", "name_required": True, "type": "NotebookRuntime"},
    "indexes": {"id": "indexId", "create": "op", "name_required": True, "type": "Index"},
    "indexEndpoints": {"id": "indexEndpointId", "create": "op", "name_required": True, "type": "IndexEndpoint"},
    "featureOnlineStores": {"id": "featureOnlineStoreId", "create": "op", "type": "FeatureOnlineStore"},
    "featureViews": {"id": "featureViewId", "create": "op", "parent": "featureOnlineStores", "type": "FeatureView"},
    "featureGroups": {"id": "featureGroupId", "create": "op", "type": "FeatureGroup"},
    "features": {"id": "featureId", "create": "op", "parent": "featureGroups", "type": "Feature"},
    "tensorboards": {"id": "tensorboardId", "create": "op", "name_required": True, "type": "Tensorboard"},
    "experiments": {"id": "tensorboardExperimentId", "create": "direct", "parent": "tensorboards", "type": "TensorboardExperiment"},
    "runs": {"id": "tensorboardRunId", "create": "direct", "parent": "experiments", "type": "TensorboardRun"},
    "metadataStores": {"id": "metadataStoreId", "create": "op", "type": "MetadataStore"},
    "contexts": {"id": "contextId", "create": "direct", "parent": "metadataStores", "type": "Context"},
    "artifacts": {"id": "artifactId", "create": "direct", "parent": "metadataStores", "type": "Artifact"},
    "executions": {"id": "executionId", "create": "direct", "parent": "metadataStores", "type": "Execution"},
    "instances": {"id": "instanceId", "create": "op", "type": "Instance", "notebooks": True},   # Workbench (notebooks v2)
}
# collection-level custom verbs  e.g. POST .../models:upload
COLL_VERBS = {"models": {"upload", "copy"}, "datasets": set()}
# resource-level custom verbs
ITEM_VERBS = {
    "endpoints": {"deployModel", "undeployModel", "predict", "rawPredict", "mutateDeployedModel"},
    "trainingPipelines": {"cancel"}, "customJobs": {"cancel"}, "hyperparameterTuningJobs": {"cancel"},
    "batchPredictionJobs": {"cancel"}, "pipelineJobs": {"cancel"}, "tuningJobs": {"cancel"},
    "notebookRuntimes": {"start", "stop", "upgrade"}, "instances": {"start", "stop", "reset"},
    "indexes": {"upsertDatapoints", "removeDatapoints"},
    "indexEndpoints": {"deployIndex", "undeployIndex", "findNeighbors", "readIndexDatapoints"},
    "models": {"copy"},
}
NO_DISPLAY = {"featureOnlineStores", "featureViews", "featureGroups", "features", "metadataStores", "instances", "experiments", "runs"}

try:
    from core import ai_model_catalog as CAT
except ImportError:  # Pyodide flat layout
    import ai_model_catalog as CAT  # type: ignore

# Model Garden = the ten booster-mesh open models (core/ai_model_catalog.py), nothing else. (publisher, id, oss category, stage, title,
# description, actions); every one is served (generate / embed) once its booster runner is up.
PUBLISHER_MODELS = [(m["publisher"], m["id"], "GOOGLE_OWNED_OSS" if m["vendor"] == "Google" else "THIRD_PARTY_OWNED_OSS", "GA", m["name"], m["blurb"],
                     ["embed"] if m["kind"] == "embed" else ["generate"]) for m in CAT.MODELS]


@dataclass
class VertexStore:
    """Public dict attrs only -> persisted/synced by core/nano_persist."""
    res: dict = field(default_factory=dict)       # full resource name -> record
    ops: dict = field(default_factory=dict)       # operation name -> operation
    vectors: dict = field(default_factory=dict)   # index name -> {datapointId: {"v": [..], "restricts": [..]}}
    meta: dict = field(default_factory=dict)      # {"seq": n}


_SHARED: VertexStore | None = None


def shared_store() -> VertexStore:
    global _SHARED
    if _SHARED is None:
        _SHARED = VertexStore()
    return _SHARED


class _R:
    def __init__(self, status, body):
        self.status, self.body, self.headers, self.media_type = status, body, {}, "application/json"


def _j(status, obj):
    return _R(status, json.dumps(obj).encode())


def _err(status, gstatus, msg):
    return _j(status, {"error": {"code": status, "message": msg, "status": gstatus}})


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _next(store):
    n = int(store.meta.get("seq", 0)) + 1
    store.meta["seq"] = n
    return n


def _numeric_id(store):
    return str(7000000000000000000 + _next(store) * 7919)


def _api(coll):
    return "notebooks" if SPEC[coll].get("notebooks") else "aiplatform"


# ── path parsing ────────────────────────────────────────────────────────────
_ROOT = re.compile(r"^/(v1|v1beta1|v2)/projects/([^/]+)/locations/([^/]+)/(.+)$")


def handles(path):
    m = _ROOT.match(path.split("?", 1)[0])
    if not m:
        return bool(re.match(r"^/v1(beta1)?/publishers(/|$)", path))
    ver, _p, loc, rest = m.groups()
    seg = rest.split("/")
    first = seg[0].split(":")[0]
    if first == "operations" and len(seg) == 2:
        return seg[1].startswith("vtx-")
    if len(seg) >= 3 and seg[-2] == "operations":
        return seg[-1].startswith("vtx-") and first in SPEC
    if ver == "v2":
        return first == "instances" and (loc == "-" or bool(re.search(r"-[a-z]$", loc)))
    return first in SPEC and not SPEC[first].get("notebooks")


def _parse(rest):
    """-> (chain [(coll,id|None)...], verb|None) or None"""
    verb = None
    if ":" in rest.split("/")[-1]:
        head, verb = rest.rsplit(":", 1)
        rest = head
    seg = [s for s in rest.split("/") if s]
    chain, i = [], 0
    while i < len(seg):
        if seg[i] not in SPEC:
            return None
        chain.append((seg[i], seg[i + 1] if i + 1 < len(seg) else None))
        i += 2
    return chain, verb


def _full(project, loc, chain):
    return f"projects/{project}/locations/{loc}/" + "/".join(f"{c}/{i}" for c, i in chain if i)


def _expect_parent(chain):
    for k, (c, _i) in enumerate(chain):
        par = SPEC[c].get("parent")
        if par and (k == 0 or chain[k - 1][0] != par):
            return False
    return True


# ── operations ──────────────────────────────────────────────────────────────
def _op(store, project, loc, coll, resp, verb="Create", empty=False, rname=None):
    """Real Vertex LROs are scoped to the resource they act on: <resource>/operations/<id> (gcloud parses that shape)."""
    scope = rname if (rname and not SPEC[coll].get("notebooks")) else f"projects/{project}/locations/{loc}"   # notebooks v2 ops are location-scoped
    name = f"{scope}/operations/vtx-{_next(store):016x}"
    t = _now()
    api = _api(coll)
    pkg = "google.cloud.aiplatform.v1" if api == "aiplatform" else "google.cloud.notebooks.v2"
    op = {"name": name,
          "metadata": {"@type": f"type.googleapis.com/{pkg}.{verb}{SPEC[coll]['type']}OperationMetadata",
                       "genericMetadata": {"createTime": t, "updateTime": t}},
          "done": True}
    if empty:
        op["response"] = {"@type": "type.googleapis.com/google.protobuf.Empty"}
    else:
        op["response"] = {"@type": f"type.googleapis.com/{pkg}.{SPEC[coll]['type']}", **resp}
    store.ops[name] = op
    return op


# ── job lifecycle (lazy, clock based) ──────────────────────────────────────
def _advance(store, rec, coll):
    pre = SPEC[coll].get("job")
    if not pre:
        return
    st = rec.get("state", "")
    if st.endswith(("SUCCEEDED", "CANCELLED", "FAILED")):
        return
    age = time.time() - rec.get("_t0", time.time())
    if age < 2:
        new = pre + "PENDING"
    elif age < 5:
        new = pre + "RUNNING"
    else:
        new = pre + "SUCCEEDED"
    if new != st:
        rec["state"] = new
        t = _now()
        if new.endswith("RUNNING"):
            rec["startTime"] = t
        if new.endswith("SUCCEEDED"):
            rec.setdefault("startTime", t)
            rec["endTime"] = t
            _on_success(store, rec, coll)
        rec["updateTime"] = t


def _on_success(store, rec, coll):
    project, loc = rec["name"].split("/")[1], rec["name"].split("/")[3]
    if coll == "trainingPipelines" and rec.get("modelToUpload") and not rec.get("_model"):
        mid = _numeric_id(store)
        mname = f"projects/{project}/locations/{loc}/models/{mid}"
        m = dict(rec["modelToUpload"])
        m.update(name=mname, createTime=_now(), updateTime=_now(), versionId="1", trainingPipeline=rec["name"])
        m.setdefault("displayName", rec.get("displayName", "model"))
        store.res[mname] = m
        rec["modelToUpload"]["name"] = mname
        rec["_model"] = mname
    if coll == "batchPredictionJobs":
        out = (rec.get("outputConfig") or {}).get("gcsDestination", {}).get("outputUriPrefix")
        if out:
            rec["outputInfo"] = {"gcsOutputDirectory": out.rstrip("/") + "/prediction-" + rec["name"].rsplit("/", 1)[-1]}
        rec["completionStats"] = {"successfulCount": "1", "failedCount": "0"}


def _public(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


# ── vector search ──────────────────────────────────────────────────────────
def _dist(kind, a, b):
    if kind == "DOT_PRODUCT_DISTANCE":
        return sum(x * y for x, y in zip(a, b))
    if kind == "SQUARED_L2_DISTANCE":
        return sum((x - y) ** 2 for x, y in zip(a, b))
    if kind == "L1_DISTANCE":
        return sum(abs(x - y) for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)) or 1.0, math.sqrt(sum(y * y for y in b)) or 1.0
    return 1.0 - sum(x * y for x, y in zip(a, b)) / (na * nb)


def _index_cfg(idx):
    c = ((idx.get("metadata") or {}).get("config") or {})
    return int(c.get("dimensions") or 0), c.get("distanceMeasureType", "COSINE_DISTANCE")


def _find_neighbors(store, ep, body):
    deployed = {d.get("id"): d for d in ep.get("deployedIndexes", [])}
    d = deployed.get(body.get("deployedIndexId"))
    if not d:
        return _err(404, "NOT_FOUND", f"Deployed index {body.get('deployedIndexId')} not found on this index endpoint.")
    idx = store.res.get(d["index"])
    dims, kind = _index_cfg(idx or {})
    pts = store.vectors.get(d["index"], {})
    out = []
    for q in body.get("queries") or []:
        dp = q.get("datapoint") or {}
        qv = dp.get("featureVector") or []
        if dims and len(qv) != dims:
            return _err(400, "INVALID_ARGUMENT", f"Query vector has {len(qv)} dimensions, index expects {dims}.")
        n = int(q.get("neighborCount") or 10)
        scored = [(_dist(kind, qv, p["v"]), pid) for pid, p in pts.items()]
        scored.sort(key=lambda x: -x[0] if kind == "DOT_PRODUCT_DISTANCE" else x[0])
        out.append({"id": dp.get("datapointId", ""), "neighbors": [
            {"datapoint": {"datapointId": pid, "crowdingTag": {"crowdingAttribute": "0"}}, "distance": s} for s, pid in scored[:n]]})
    return _j(200, {"nearestNeighbors": out})


# ── dispatch ───────────────────────────────────────────────────────────────
def dispatch(store, method, path, query=None, headers=None, body=b""):
    query = query or {}
    method = method.upper()
    for k, v in (headers or {}).items():
        if k.lower() == "x-http-method-override" and method == "POST" and v:
            method = str(v).upper()
    path = path.split("?", 1)[0]
    try:
        payload = json.loads(body.decode("utf-8")) if body else {}
        if not isinstance(payload, dict):
            raise ValueError
    except Exception:
        return _err(400, "INVALID_ARGUMENT", "Invalid JSON payload received.")

    mg = re.match(r"^/(v1|v1beta1)/publishers(?:/([^/]+)(?:/models(?:/([^/:]+))?)?)?$", path)
    if mg:
        return _model_garden(method, mg.group(2), mg.group(3), query)

    m = _ROOT.match(path)
    if not m:
        return _err(404, "NOT_FOUND", f"Unsupported Vertex AI operation: {method} {path}")
    ver, project, loc, rest = m.groups()

    mo = re.match(r"^(?:.+/)?operations/(vtx-[0-9a-f]{16})$", rest)
    if mo:
        name = f"projects/{project}/locations/{loc}/{rest}"
        op = store.ops.get(name)
        if not op:
            return _err(404, "NOT_FOUND", f"Operation {name} not found.")
        return _j(200, op) if method == "GET" else _err(405, "INVALID_ARGUMENT", "Unsupported operation method.")

    parsed = _parse(rest)
    if not parsed or not parsed[0] or not _expect_parent(parsed[0]):
        return _err(404, "NOT_FOUND", f"Unsupported Vertex AI operation: {method} {path}")
    chain, verb = parsed
    coll, rid = chain[-1]
    spec = SPEC[coll]
    if (ver == "v2") != bool(spec.get("notebooks")):
        return _err(404, "NOT_FOUND", f"Unsupported Vertex AI operation: {method} {path}")
    # parents must exist
    for k in range(len(chain) - 1):
        pn = _full(project, loc, chain[: k + 1])
        if pn not in store.res and not (chain[k][0] == "metadataStores" and chain[k][1] == "default"):
            return _err(404, "NOT_FOUND", f"{chain[k][0][:-1] if chain[k][0].endswith('s') else chain[k][0]} {pn} not found.")
    parent_prefix = _full(project, loc, chain[:-1]) + "/" if len(chain) > 1 else f"projects/{project}/locations/{loc}/"

    # ----- collection level
    if rid is None:
        if verb:
            if verb not in COLL_VERBS.get(coll, set()):
                return _err(404, "NOT_FOUND", f"Method {verb} is not supported on {coll}.")
            if coll == "models" and verb == "upload":
                model = payload.get("model") or {}
                return _create(store, project, loc, chain, model, {"modelId": payload.get("modelId") or ""}, verb="Upload")
            return _err(501, "UNIMPLEMENTED", f"{coll}:{verb} is not simulated.")
        if method == "GET":
            return _list(store, project, loc, coll, parent_prefix, query)
        if method == "POST":
            return _create(store, project, loc, chain, payload, query)
        return _err(405, "INVALID_ARGUMENT", "Unsupported method.")

    full = _full(project, loc, chain)
    rec = store.res.get(full)
    if rec is None and coll == "metadataStores" and rid == "default":
        rec = _ensure_default_store(store, project, loc)
    # ----- resource level
    if verb:
        if verb not in ITEM_VERBS.get(coll, set()):
            return _err(404, "NOT_FOUND", f"Method {verb} is not supported on {coll}.")
        if rec is None:
            return _err(404, "NOT_FOUND", f"{spec['type']} {full} not found.")
        return _verb(store, project, loc, coll, full, rec, verb, payload)
    if method == "GET":
        if rec is None:
            return _err(404, "NOT_FOUND", f"The {spec['type']} {full} is not found.")
        _advance(store, rec, coll)
        return _j(200, _public(rec))
    if method == "DELETE":
        if rec is None:
            return _err(404, "NOT_FOUND", f"The {spec['type']} {full} is not found.")
        for k in [k for k in store.res if k.startswith(full + "/")]:   # cascade children
            store.res.pop(k, None)
        store.res.pop(full, None)
        store.vectors.pop(full, None)
        if coll == "models":
            for ep in store.res.values():
                if "deployedModels" in ep and "/endpoints/" in ep.get("name", ""):
                    ep["deployedModels"] = [d for d in ep["deployedModels"] if d.get("model") != full]
        return _j(200, _op(store, project, loc, coll, {}, verb="Delete", empty=True, rname=full))
    if method == "PATCH":
        if rec is None:
            return _err(404, "NOT_FOUND", f"The {spec['type']} {full} is not found.")
        mask = [x for x in (query.get("updateMask") or "").split(",") if x]
        for k, v in payload.items():
            if k in ("name", "createTime") or (mask and k not in mask):
                continue
            rec[k] = v
        rec["updateTime"] = _now()
        return _j(200, _public(rec))
    return _err(405, "INVALID_ARGUMENT", "Unsupported method.")


def _ensure_default_store(store, project, loc):
    name = f"projects/{project}/locations/{loc}/metadataStores/default"
    if name not in store.res:
        t = _now()
        store.res[name] = {"name": name, "createTime": t, "updateTime": t, "description": "Default metadata store", "state": {}}
    return store.res[name]


def _validate(coll, body, rid):
    spec = SPEC[coll]
    if spec.get("name_required") and not body.get("displayName"):
        return "displayName: must not be empty."
    if coll in ("trainingPipelines", "customJobs", "batchPredictionJobs", "hyperparameterTuningJobs", "pipelineJobs", "tuningJobs") and not body.get("displayName") and coll != "tuningJobs":
        return "displayName: must not be empty."
    if coll == "indexes":
        dims, _k = _index_cfg(body)
        if dims <= 0:
            return "metadata.config.dimensions: must be a positive integer."
    if coll == "customJobs" and not (body.get("jobSpec") or {}).get("workerPoolSpecs"):
        return "jobSpec.workerPoolSpecs: at least one worker pool spec is required."
    if rid and not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9_\-.]{0,127}$", rid):
        return f"{SPEC[coll]['id']}: invalid id '{rid}'."
    return None


def _create(store, project, loc, chain, body, query, verb="Create"):
    coll = chain[-1][0]
    spec = SPEC[coll]
    rid = query.get(spec["id"]) or body.pop(spec["id"], None) or ""
    msg = _validate(coll, body, rid)
    if msg:
        return _err(400, "INVALID_ARGUMENT", msg)
    if not rid:
        rid = _numeric_id(store)
    full = _full(project, loc, chain[:-1] + [(coll, rid)])
    if chain[0][0] == "metadataStores" and chain[0][1] == "default":
        _ensure_default_store(store, project, loc)
    if full in store.res:
        return _err(409, "ALREADY_EXISTS", f"{spec['type']} {full} already exists.")
    t = _now()
    rec = dict(body)
    rec.update(name=full, createTime=t, updateTime=t)
    if spec.get("job"):
        rec["state"] = spec["job"] + "PENDING"
        rec["_t0"] = time.time()
        rec.pop("startTime", None)
    elif coll == "endpoints":
        rec.setdefault("deployedModels", [])
        rec.setdefault("trafficSplit", {})
        rec["etag"] = "AMEu" + rid[-8:]
    elif coll == "models":
        rec.setdefault("versionId", "1")
        rec.setdefault("supportedDeploymentResourcesTypes", ["DEDICATED_RESOURCES"])
        rec.setdefault("deployedModels", [])
        rec["versionCreateTime"] = t
        rec["versionUpdateTime"] = t
    elif coll == "datasets":
        rec.setdefault("metadataSchemaUri", "gs://google-cloud-aiplatform/schema/dataset/metadata/image_1.0.0.yaml")
        rec.setdefault("metadata", {})
        rec["dataItemCount"] = "0"
    elif coll == "indexes":
        rec.setdefault("indexUpdateMethod", "STREAM_UPDATE")
        rec["indexStats"] = {"vectorsCount": "0", "shardsCount": 1}
        store.vectors[full] = {}
    elif coll == "indexEndpoints":
        rec.setdefault("deployedIndexes", [])
    elif coll == "notebookRuntimes":
        rec.update(runtimeState="RUNNING", healthState="HEALTHY", isUpgradable=False, notebookRuntimeType="USER_DEFINED")
    elif coll == "instances":
        rec.update(state="ACTIVE", healthState="HEALTHY", creator="vyomi-user@example.com", proxyUri=f"{rid}-{project}.notebooks.googleusercontent.com")
    elif coll == "tensorboards":
        rec["blobStoragePathPrefix"] = f"gs://{project}-tensorboard/{rid}"
    elif coll == "metadataStores":
        rec.setdefault("state", {})
    elif coll == "contexts":
        rec.setdefault("schemaTitle", "system.Experiment")
        rec.setdefault("schemaVersion", "0.0.1")
    elif coll == "artifacts":
        rec.setdefault("schemaTitle", "system.Artifact")
        rec["state"] = rec.get("state") or "LIVE"
    elif coll == "executions":
        rec.setdefault("schemaTitle", "system.ContainerExecution")
        rec["state"] = rec.get("state") or "COMPLETE"
    store.res[full] = rec
    out = _public(rec)
    if spec["create"] == "direct":
        return _j(200, out)
    return _j(200, _op(store, project, loc, coll, out, verb=verb, rname=full))


def _list(store, project, loc, coll, parent_prefix, query):
    pfx = parent_prefix + coll + "/"
    anyloc = loc == "-" and len(parent_prefix.split("/")) == 5   # projects/p/locations/- : aggregate every location
    items = []
    if coll == "metadataStores":
        _ensure_default_store(store, project, loc)
    for k, rec in sorted(store.res.items()):
        if anyloc:
            seg = k.split("/")
            if len(seg) != 6 or seg[0] != "projects" or seg[1] != project or seg[4] != coll:
                continue
        elif not k.startswith(pfx) or "/" in k[len(pfx):]:
            continue
        _advance(store, rec, coll)
        items.append(rec)
    flt = query.get("filter") or ""
    mt = re.search(r'display_name\s*=\s*"?([^"]*)"?', flt) or re.search(r'displayName\s*=\s*"?([^"]*)"?', flt)
    if mt:
        items = [r for r in items if r.get("displayName") == mt.group(1)]
    mt = re.search(r'schema_title\s*=\s*"?([\w.]+)"?', flt)
    if mt:
        items = [r for r in items if r.get("schemaTitle") == mt.group(1)]
    mt = re.search(r'state\s*=\s*"?(\w+)"?', flt)
    if mt:
        items = [r for r in items if r.get("state") == mt.group(1)]
    try:
        size = int(query.get("pageSize") or query.get("pageSize".lower()) or 0)
    except ValueError:
        size = 0
    start = int(query.get("pageToken") or 0) if str(query.get("pageToken") or "0").isdigit() else 0
    nxt = ""
    if size and len(items) > start + size:
        nxt = str(start + size)
    items = items[start:start + size] if size else items[start:]
    key = {"instances": "instances", "indexes": "indexes", "experiments": "tensorboardExperiments", "runs": "tensorboardRuns",
           "tensorboards": "tensorboards"}.get(coll, coll)
    out = {key: [_public(r) for r in items]}
    if nxt:
        out["nextPageToken"] = nxt
    return _j(200, out)


def _verb(store, project, loc, coll, full, rec, verb, p):
    t = _now()
    if verb == "cancel":
        _advance(store, rec, coll)
        if rec["state"].endswith(("SUCCEEDED", "CANCELLED", "FAILED")):
            return _err(400, "FAILED_PRECONDITION", f"{coll[:-1]} is already in a terminal state ({rec['state']}).")
        rec["state"] = SPEC[coll]["job"] + "CANCELLED"
        rec["endTime"] = rec["updateTime"] = t
        return _j(200, {})
    if verb in ("start", "stop", "reset", "upgrade"):
        if coll == "instances":
            rec["state"] = "STOPPED" if verb == "stop" else "ACTIVE"
        elif coll == "notebookRuntimes":
            rec["runtimeState"] = "STOPPED" if verb == "stop" else "RUNNING"
        rec["updateTime"] = t
        return _j(200, _op(store, project, loc, coll, _public(rec), verb={"start": "Start", "stop": "Stop", "reset": "Reset", "upgrade": "Upgrade"}[verb], rname=full))
    if coll == "endpoints":
        if verb == "deployModel":
            dm = dict(p.get("deployedModel") or {})
            mname = dm.get("model", "").split("@")[0]
            if mname not in store.res or not mname.startswith(f"projects/{project}/locations/{loc}/models/"):
                return _err(404, "NOT_FOUND", f"Model {mname or '(empty)'} not found.")
            dm["id"] = dm.get("id") or str(_next(store) + 1000000000)
            dm.setdefault("displayName", store.res[mname].get("displayName"))
            dm["createTime"] = t
            rec["deployedModels"].append(dm)
            ts = dict(p.get("trafficSplit") or {})
            if not ts:
                ts = {"0": 100} if len(rec["deployedModels"]) == 1 else dict(rec.get("trafficSplit") or {})
            ts = {(dm["id"] if k == "0" else k): v for k, v in ts.items()}
            rec["trafficSplit"] = ts
            store.res[mname].setdefault("deployedModels", []).append({"endpoint": full, "deployedModelId": dm["id"]})
            rec["updateTime"] = t
            return _j(200, _op(store, project, loc, coll, {"deployedModel": dm}, verb="DeployModel", rname=full))
        if verb == "undeployModel":
            did = p.get("deployedModelId")
            keep = [d for d in rec["deployedModels"] if d["id"] != did]
            if len(keep) == len(rec["deployedModels"]):
                return _err(404, "NOT_FOUND", f"Deployed model {did} not found on {full}.")
            gone = [d for d in rec["deployedModels"] if d["id"] == did][0]
            rec["deployedModels"] = keep
            rec["trafficSplit"] = {k: v for k, v in (rec.get("trafficSplit") or {}).items() if k != did}
            mrec = store.res.get(gone.get("model", "").split("@")[0])
            if mrec:
                mrec["deployedModels"] = [d for d in mrec.get("deployedModels", []) if d.get("deployedModelId") != did]
            rec["updateTime"] = t
            return _j(200, _op(store, project, loc, coll, {}, verb="UndeployModel", rname=full))
        if verb in ("predict", "rawPredict"):
            if not rec.get("deployedModels"):
                return _err(400, "FAILED_PRECONDITION", "Endpoint has no deployed model.")
            return _err(501, "UNIMPLEMENTED", "Custom-model serving is not simulated: Vyomi serves Gemini and embedding publisher models only.")
        return _err(501, "UNIMPLEMENTED", f"endpoints:{verb} is not simulated.")
    if coll == "indexes":
        pts = store.vectors.setdefault(full, {})
        dims, _k = _index_cfg(rec)
        if verb == "upsertDatapoints":
            dps = p.get("datapoints") or []
            for d in dps:
                v = d.get("featureVector") or []
                if not d.get("datapointId") or (dims and len(v) != dims):
                    return _err(400, "INVALID_ARGUMENT", f"Datapoint '{d.get('datapointId')}' needs an id and a {dims}-dimension featureVector.")
            for d in dps:
                pts[d["datapointId"]] = {"v": d["featureVector"], "restricts": d.get("restricts", [])}
        else:
            for pid in p.get("datapointIds") or []:
                pts.pop(pid, None)
        rec["indexStats"] = {"vectorsCount": str(len(pts)), "shardsCount": 1}
        rec["updateTime"] = t
        return _j(200, {})
    if coll == "indexEndpoints":
        if verb == "deployIndex":
            di = dict(p.get("deployedIndex") or {})
            if di.get("index") not in store.res or "/indexes/" not in di.get("index", ""):
                return _err(404, "NOT_FOUND", f"Index {di.get('index') or '(empty)'} not found.")
            if not di.get("id"):
                return _err(400, "INVALID_ARGUMENT", "deployedIndex.id is required.")
            if any(x["id"] == di["id"] for x in rec["deployedIndexes"]):
                return _err(409, "ALREADY_EXISTS", f"Deployed index {di['id']} already exists.")
            di["createTime"] = t
            rec["deployedIndexes"].append(di)
            store.res[di["index"]].setdefault("deployedIndexes", []).append({"indexEndpoint": full, "deployedIndexId": di["id"]})
            rec["updateTime"] = t
            return _j(200, _op(store, project, loc, coll, {"deployedIndex": di}, verb="DeployIndex", rname=full))
        if verb == "undeployIndex":
            did = p.get("deployedIndexId")
            gone = [d for d in rec["deployedIndexes"] if d["id"] == did]
            if not gone:
                return _err(404, "NOT_FOUND", f"Deployed index {did} not found.")
            rec["deployedIndexes"] = [d for d in rec["deployedIndexes"] if d["id"] != did]
            ix = store.res.get(gone[0]["index"])
            if ix:
                ix["deployedIndexes"] = [d for d in ix.get("deployedIndexes", []) if d.get("deployedIndexId") != did]
            return _j(200, _op(store, project, loc, coll, {}, verb="UndeployIndex", rname=full))
        if verb == "findNeighbors":
            return _find_neighbors(store, rec, p)
        if verb == "readIndexDatapoints":
            d = {x["id"]: x for x in rec.get("deployedIndexes", [])}.get(p.get("deployedIndexId"))
            pts = store.vectors.get(d["index"], {}) if d else {}
            return _j(200, {"datapoints": [{"datapointId": i, "featureVector": pts[i]["v"]} for i in p.get("ids") or [] if i in pts]})
    if coll == "models" and verb == "copy":
        return _err(501, "UNIMPLEMENTED", "models:copy is not simulated.")
    return _err(501, "UNIMPLEMENTED", f"{coll}:{verb} is not simulated.")


# ── Model Garden ───────────────────────────────────────────────────────────
def _pm(pub, mid, oss, stage, title, desc, acts):
    actions = {}
    if "generate" in acts or "embed" in acts:
        actions["openGenerationAiStudio"] = {"referenceUri": f"#/vertex-ai/studio"}
    if "deploy" in acts:
        actions["deploy"] = {"modelDisplayName": mid, "containerSpec": {"imageUri": f"us-docker.pkg.dev/vertex-ai/vertex-vision-model-garden-dockers/{mid}"}}
    return {"name": f"publishers/{pub}/models/{mid}", "versionId": "default", "openSourceCategory": oss,
            "launchStage": stage, "versionState": "VERSION_STATE_STABLE", "supportedActions": actions,
            "publisherModelTemplate": f"projects/{{project}}/locations/{{location}}/publishers/{pub}/models/{mid}@default",
            "displayName": title, "description": desc, "servedByVyomi": bool({"generate", "embed"} & set(acts)),
            "vyomiAvailability": CAT.availability(mid)}


def _model_garden(method, pub, mid, query):
    if method != "GET":
        return _err(405, "INVALID_ARGUMENT", "Unsupported method.")
    items = [_pm(*m) for m in PUBLISHER_MODELS]
    if mid:
        for it in items:
            if it["name"] == f"publishers/{pub}/models/{mid}":
                return _j(200, it)
        return _err(404, "NOT_FOUND", f"Publisher model publishers/{pub}/models/{mid} not found.")
    if pub and pub not in ("*", "-"):
        items = [i for i in items if i["name"].startswith(f"publishers/{pub}/")]
    flt = (query.get("filter") or "").lower()
    if flt:
        items = [i for i in items if flt in (i["displayName"] + i["description"] + i["name"]).lower()]
    return _j(200, {"publisherModels": items})
