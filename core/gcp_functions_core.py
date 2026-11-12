"""Google Cloud Functions REST API, v2 (cloudfunctions.googleapis.com/v2) and v1 -- substrate-independent, pure Python.

What `gcloud functions ...` and google-cloud-functions / googleapiclient speak:
  v2  functions create / get / list / patch / delete, generateUploadUrl, generateDownloadUrl, getIamPolicy /
      setIamPolicy / testIamPermissions, the *FunctionUpgrade* verbs, locations.runtimes
  v1  functions create / get / list / patch / delete, call, generateUploadUrl, generateDownloadUrl, IAM, operations.get

Real engine state, no canned bodies:
  * a function IS a Cloud Run service (the way gen2 functions are): created in the Run store, listed by Run, its revisions /
    IAM invoker policy / Eventarc triggers / request metrics / logs are Run's own (core/gcp_run_core);
  * source is a real zip: generateUploadUrl hands out a URL on this very endpoint, the PUT lands in the simulator's GCS
    (bucket gcf-v2-sources-{number}-{region}), create/patch reads it back from GCS, validates the entry point and stores
    the module text on the service so the function RUNS (functions_framework / flask shims, core/gcp_console_tabs sandbox);
  * `:call`, the function's HTTPS URL (/gcf/{project}/{location}/{function}) and Eventarc deliveries all execute the same
    source and feed Cloud Logging + Cloud Monitoring through the Run observability seam.
Honest limits: Python and JavaScript sources run (single entry module; other runtimes are stored and validated only);
no Cloud Build/Artifact Registry image is produced; function-level IAM is the Run invoker policy.
"""
from __future__ import annotations

import base64
import io
import json
import re
import time
import zipfile
from datetime import datetime, timezone

from core import gcp_run_core as R

_ANN = "vyomi.dev/function-"
_RUNTIMES = ("python313", "python312", "python311", "python310", "python39", "nodejs22", "nodejs20", "nodejs18",
             "go123", "go122", "java21", "java17", "ruby33", "php83", "dotnet8")
_MEM = {"128M": 128, "256M": 256, "512M": 512, "1G": 1024, "2G": 2048, "4G": 4096, "8G": 8192, "16G": 16384, "32G": 32768}


class Resp:
    def __init__(self, status, obj, media="application/json"):
        self.status, self.headers, self.media_type = status, {}, media
        self.body = obj if isinstance(obj, (bytes, bytearray)) else json.dumps(obj).encode()


class _E(Exception):
    def __init__(self, status, code, msg):
        self.status, self.code, self.msg = status, code, msg


def _err(status, code, msg):
    return Resp(status, {"error": {"code": status, "message": msg, "status": code}})


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _bag(bag):
    b = bag.setdefault("gcp_functions", {})
    b.setdefault("fns", {})       # service full name -> function meta
    b.setdefault("ops", {})       # v1 operation name -> operation
    b.setdefault("seq", 0)
    return b


_V2 = re.compile(r"^/v2/projects/([^/]+)/locations/([^/]+)/(functions|runtimes)(?:/([^/:]+))?(?::([A-Za-z]+))?$")
_V1 = re.compile(r"^/v1/projects/([^/]+)/locations/([^/]+)/functions(?:/([^/:]+))?(?::([A-Za-z]+))?$")
_V1OP = re.compile(r"^/v1/operations(?:/(fn-[0-9a-f]+))?$")
_UPLOAD = re.compile(r"^/gcf-upload/([^/]+)/(.+)$")
_HTTP = re.compile(r"^/gcf/([^/]+)/([^/]+)/([^/]+)(/.*)?$")


def handles(path):
    p = path.split("?", 1)[0]
    return bool(_V2.match(p) or _V1.match(p) or _V1OP.match(p) or _UPLOAD.match(p))


# ── Run-store helpers ───────────────────────────────────────────────────────────────────
def _full(project, location, fid):
    return R.service_name(project, location, fid)


def _svc(ctx, project, location, fid):
    full = _full(project, location, fid)
    return full, ctx["run"].services.get(full)


def _meta(ctx, full):
    return _bag(ctx["bag"])["fns"].get(full)


def _name_ok(fid):
    if not re.match(r"^[a-z]([-a-z0-9]{0,61}[a-z0-9])?$", fid or ""):
        raise _E(400, "INVALID_ARGUMENT", "Invalid function name '%s': lowercase letters, digits and hyphens, starting with a letter (max 63)." % fid)


def _gcs(ctx, method, path, query=None, body=b"", headers=None):
    r = ctx["gcs_mod"].dispatch(ctx["gcs"], method, path, query or {}, headers or {}, body)
    return r


def _staging_bucket(ctx, project, region):
    b = "gcf-v2-sources-%s-%s" % (R.project_number(project), region)
    if not ctx["gcs"].bucket_exists(b):
        _gcs(ctx, "POST", "/storage/v1/b", {"project": project}, json.dumps({"name": b, "location": region.upper()}).encode())
    return b


def _read_source(ctx, bucket, obj):
    r = _gcs(ctx, "GET", "/storage/v1/b/%s/o/%s" % (bucket, obj.replace("/", "%2F")), {"alt": "media"})
    if r.status != 200:
        raise _E(400, "INVALID_ARGUMENT", "Could not read the function source gs://%s/%s (HTTP %s). Upload it to the URL from generateUploadUrl first." % (bucket, obj, r.status))
    return r.body


def _unzip(blob, runtime, entry):
    try:
        z = zipfile.ZipFile(io.BytesIO(blob))
    except Exception:
        raise _E(400, "INVALID_ARGUMENT", "The function source is not a valid zip archive.")
    names = z.namelist()
    want = ("main.py",) if runtime.startswith("python") else ("index.js", "function.js", "index.mjs") if runtime.startswith("nodejs") else ()
    pick = next((n for n in want if n in names), None)
    if want and pick is None:
        raise _E(400, "FAILED_PRECONDITION", "Build failed: the %s runtime needs %s at the root of the source archive." % (runtime, " or ".join(want)))
    return z.read(pick).decode("utf-8", "replace") if pick else ""


def _check_code(runtime, entry, code):
    from core import gcp_console_tabs as T
    try:
        T.validate_source(runtime, code, entry)
    except T.TabError as e:
        raise _E(400, "FAILED_PRECONDITION" if "Build" in str(e) or "entry point" in str(e) else "INVALID_ARGUMENT", str(e))


# ── building / viewing a function ───────────────────────────────────────────────────────
def _source_code(ctx, project, bs, runtime, entry):
    ss = (bs.get("source") or {}).get("storageSource") or {}
    inline = bs.get("_inlineCode")
    if inline is not None:
        return inline, ss
    if ss.get("bucket") and ss.get("object"):
        return _unzip(_read_source(ctx, ss["bucket"], ss["object"]), runtime, entry), ss
    if (bs.get("source") or {}).get("repoSource"):
        return "", ss
    raise _E(400, "INVALID_ARGUMENT", "buildConfig.source is required (storageSource or repoSource).")


def _env_clean(env, what):
    if env is None:
        return {}
    if not isinstance(env, dict):
        raise _E(400, "INVALID_ARGUMENT", "%s must be a map of string to string." % what)
    out = {}
    for k, v in env.items():
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", str(k)):
            raise _E(400, "INVALID_ARGUMENT", "Invalid environment variable name '%s'." % k)
        out[str(k)] = str(v)
    return out


def _timeout(v, gen):
    try:
        s = int(str(v).rstrip("s") or 60)
    except ValueError:
        raise _E(400, "INVALID_ARGUMENT", "Invalid timeout '%s'." % v)
    top = 3600 if gen == 2 else 540
    if not 1 <= s <= top:
        raise _E(400, "INVALID_ARGUMENT", "timeout must be between 1 and %d seconds for a gen%d function." % (top, gen))
    return s


def _v2_to_meta(ctx, project, location, fid, body, gen=2, prior=None):
    """Validated, normalised function record from a v2 Function body (or a v1 body converted to it)."""
    bc = dict((prior or {}).get("buildConfig") or {}, **(body.get("buildConfig") or {}))
    sc = dict((prior or {}).get("serviceConfig") or {}, **(body.get("serviceConfig") or {}))
    runtime, entry = bc.get("runtime") or "", bc.get("entryPoint") or ""
    if runtime not in _RUNTIMES:
        raise _E(400, "INVALID_ARGUMENT", "Invalid runtime '%s'. Supported: %s." % (runtime, ", ".join(_RUNTIMES)))
    if not entry:
        raise _E(400, "INVALID_ARGUMENT", "buildConfig.entryPoint is required.")
    code, ss = _source_code(ctx, project, bc, runtime, entry)
    if code or runtime.startswith(("python", "nodejs")):
        _check_code(runtime, entry, code)
    mem = str(sc.get("availableMemory") or "256M")
    if mem not in _MEM:
        raise _E(400, "INVALID_ARGUMENT", "Invalid availableMemory '%s'. Use one of %s." % (mem, ", ".join(_MEM)))
    mn, mx = int(sc.get("minInstanceCount") or 0), int(sc.get("maxInstanceCount") or 100)
    if mn < 0 or mx < 1 or mn > mx:
        raise _E(400, "INVALID_ARGUMENT", "minInstanceCount must be between 0 and maxInstanceCount.")
    ing = sc.get("ingressSettings") or "ALLOW_ALL"
    if ing not in ("ALLOW_ALL", "ALLOW_INTERNAL_ONLY", "ALLOW_INTERNAL_AND_GCLB"):
        raise _E(400, "INVALID_ARGUMENT", "Invalid ingressSettings '%s'." % ing)
    et = body.get("eventTrigger", (prior or {}).get("eventTrigger"))
    if et:
        if not et.get("eventType"):
            raise _E(400, "INVALID_ARGUMENT", "eventTrigger.eventType is required.")
        if et["eventType"] == "google.cloud.pubsub.topic.v1.messagePublished" and not et.get("pubsubTopic"):
            raise _E(400, "INVALID_ARGUMENT", "eventTrigger.pubsubTopic is required for Pub/Sub triggers.")
    now = _now()
    return {"gen": gen, "id": fid, "project": project, "location": location,
            "description": body.get("description", (prior or {}).get("description", "")),
            "labels": body.get("labels", (prior or {}).get("labels", {})) or {},
            "buildConfig": {"runtime": runtime, "entryPoint": entry, "source": {"storageSource": ss} if ss else bc.get("source", {}),
                            "environmentVariables": _env_clean(bc.get("environmentVariables"), "buildConfig.environmentVariables"),
                            "dockerRepository": bc.get("dockerRepository", ""), "workerPool": bc.get("workerPool", ""),
                            "automaticUpdatePolicy": bc.get("automaticUpdatePolicy", {})},
            "serviceConfig": {"timeoutSeconds": _timeout(sc.get("timeoutSeconds", 60), gen), "availableMemory": mem,
                              "availableCpu": str(sc.get("availableCpu") or ("0.1666" if mem == "256M" else "1")),
                              "environmentVariables": _env_clean(sc.get("environmentVariables"), "serviceConfig.environmentVariables"),
                              "maxInstanceCount": mx, "minInstanceCount": mn, "ingressSettings": ing,
                              "maxInstanceRequestConcurrency": int(sc.get("maxInstanceRequestConcurrency") or 1),
                              "serviceAccountEmail": sc.get("serviceAccountEmail") or "%s-compute@developer.gserviceaccount.com" % R.project_number(project),
                              "allTrafficOnLatestRevision": sc.get("allTrafficOnLatestRevision", True),
                              "vpcConnector": sc.get("vpcConnector", ""), "vpcConnectorEgressSettings": sc.get("vpcConnectorEgressSettings", "PRIVATE_RANGES_ONLY")},
            "eventTrigger": et, "code": code,
            "createTime": (prior or {}).get("createTime", now), "updateTime": now,
            "versionId": str(int((prior or {}).get("versionId", 0)) + 1)}


def _annotations(m):
    bc = m["buildConfig"]
    return {_ANN + "runtime": bc["runtime"], _ANN + "entry-point": bc["entryPoint"], _ANN + "source": m["code"],
            _ANN + "gen": str(m["gen"])}


def _url(ctx, m):
    return "%s/gcf/%s/%s/%s" % (ctx.get("base", ""), m["project"], m["location"], m["id"])


def _view_v2(ctx, m, svc=None):
    sc = dict(m["serviceConfig"])
    full = _full(m["project"], m["location"], m["id"])
    svc = svc or ctx["run"].services.get(full) or {}
    sc.update({"service": full, "uri": _url(ctx, m) if not ctx.get("base") else _url(ctx, m),
               "revision": (svc.get("latestReadyRevision") or "").rsplit("/", 1)[-1]})
    out = {"name": "projects/%s/locations/%s/functions/%s" % (m["project"], m["location"], m["id"]),
           "description": m["description"], "buildConfig": dict(m["buildConfig"], build="projects/%s/locations/%s/builds/%s" % (R.project_number(m["project"]), m["location"], m["versionId"].zfill(8))),
           "serviceConfig": sc, "state": "ACTIVE" if svc else "DELETING", "updateTime": m["updateTime"],
           "labels": m["labels"], "environment": "GEN_%d" % m["gen"], "url": sc["uri"], "createTime": m["createTime"]}
    if m.get("eventTrigger"):
        et = dict(m["eventTrigger"])
        et.setdefault("trigger", "projects/%s/locations/%s/triggers/%s-%s" % (m["project"], et.get("triggerRegion") or m["location"], m["id"], m["versionId"]))
        et.setdefault("triggerRegion", m["location"])
        et.setdefault("retryPolicy", "RETRY_POLICY_DO_NOT_RETRY")
        et.setdefault("serviceAccountEmail", sc["serviceAccountEmail"])
        out["eventTrigger"] = et
    return out


def _view_v1(ctx, m, svc=None):
    sc, bc = m["serviceConfig"], m["buildConfig"]
    full = _full(m["project"], m["location"], m["id"])
    svc = svc or ctx["run"].services.get(full) or {}
    ss = (bc.get("source") or {}).get("storageSource") or {}
    out = {"name": "projects/%s/locations/%s/functions/%s" % (m["project"], m["location"], m["id"]), "description": m["description"],
           "status": "ACTIVE" if svc else "DELETE_IN_PROGRESS", "entryPoint": bc["entryPoint"], "runtime": bc["runtime"],
           "timeout": "%ds" % sc["timeoutSeconds"], "availableMemoryMb": _MEM.get(sc["availableMemory"], 256),
           "serviceAccountEmail": sc["serviceAccountEmail"], "updateTime": m["updateTime"], "versionId": m["versionId"],
           "labels": m["labels"], "environmentVariables": sc["environmentVariables"], "buildEnvironmentVariables": bc["environmentVariables"],
           "maxInstances": sc["maxInstanceCount"], "minInstances": sc["minInstanceCount"], "ingressSettings": sc["ingressSettings"],
           "buildId": m["versionId"].zfill(8), "buildName": "projects/%s/locations/global/builds/%s" % (R.project_number(m["project"]), m["versionId"].zfill(8)),
           "sourceToken": base64.b64encode(("%s/%s" % (ss.get("bucket", ""), ss.get("object", ""))).encode()).decode()}
    if ss:
        out["sourceArchiveUrl"] = "gs://%s/%s" % (ss.get("bucket", ""), ss.get("object", ""))
    if sc.get("vpcConnector"):
        out["vpcConnector"] = sc["vpcConnector"]
    if m.get("eventTrigger"):
        et = m["eventTrigger"]
        out["eventTrigger"] = {"eventType": et["eventType"], "resource": et.get("resource") or et.get("pubsubTopic", ""), "service": et.get("service", "pubsub.googleapis.com"),
                               "failurePolicy": et.get("failurePolicy", {})}
    else:
        out["httpsTrigger"] = {"url": _url(ctx, m), "securityLevel": "SECURE_ALWAYS"}
    return out


def _view(ctx, m, v):
    return _view_v1(ctx, m) if v == 1 else _view_v2(ctx, m)


def _eventarc(ctx, m, create):
    """Pub/Sub / Cloud Storage event triggers are real Run (Eventarc) triggers on the function's service."""
    et = m.get("eventTrigger")
    run, full = ctx["run"], _full(m["project"], m["location"], m["id"])
    for tn in [t for t, tr in run.triggers.items() if t.startswith(full + "/triggers/")]:
        del run.triggers[tn]
    if not et or not create:
        return
    filters = [{"attribute": "type", "value": et["eventType"]}] + [f for f in (et.get("eventFilters") or []) if f.get("attribute") != "type"]
    payload = {"eventFilters": filters, "serviceAccount": et.get("serviceAccountEmail", ""), "pubsubTopic": et.get("pubsubTopic", "")}
    try:
        R.create_trigger(run, m["project"], m["location"], m["id"], {"triggerId": "%s-%s" % (m["id"], m["versionId"])}, payload, topic_exists=ctx.get("topic_exists"))
    except R._E as e:
        raise _E(e.status, e.gcp_status, e.message)


def _lro(ctx, m, view, v, kind):
    """A completed LRO. v2 operations live in Run's operations store (so /v2/.../operations/{id} resolves); v1 ones in ours."""
    if v == 2:
        op = R._operation(ctx["run"], m["project"], m["location"], "service", {"name": view["name"]})
        op["metadata"] = {"@type": "type.googleapis.com/google.cloud.functions.v2.OperationMetadata", "createTime": _now(), "endTime": _now(),
                          "target": view["name"], "verb": kind, "cancelRequested": False, "apiVersion": "v2", "requestResource": {"@type": "type.googleapis.com/google.cloud.functions.v2.Function", **view},
                          "stages": []}
        op["response"] = dict(view, **{"@type": "type.googleapis.com/google.cloud.functions.v2.Function"}) if kind != "delete" else {"@type": "type.googleapis.com/google.protobuf.Empty"}
        return op
    b = _bag(ctx["bag"])
    b["seq"] += 1
    name = "operations/fn-%012x" % (0x5c0000000000 + b["seq"])
    op = {"name": name, "metadata": {"@type": "type.googleapis.com/google.cloud.functions.v1.OperationMetadataV1", "target": view["name"], "type": kind.upper(),
                                      "request": {"@type": "type.googleapis.com/google.cloud.functions.v1.CloudFunction", **view}, "versionId": m["versionId"], "updateTime": _now(),
                                      "buildId": m["versionId"].zfill(8)},
          "done": True,
          "response": dict(view, **{"@type": "type.googleapis.com/google.cloud.functions.v1.CloudFunction"}) if kind != "delete" else {"@type": "type.googleapis.com/google.protobuf.Empty"}}
    b["ops"][name] = op
    return op


# ── CRUD ────────────────────────────────────────────────────────────────────────────────
def _v1_to_v2_body(ctx, project, location, body, prior=None):
    """A v1 CloudFunction body, expressed as the v2 Function the engine stores."""
    out = {"description": body.get("description", ""), "labels": body.get("labels") or {}}
    bc = {"runtime": body.get("runtime"), "entryPoint": body.get("entryPoint") or "", "environmentVariables": body.get("buildEnvironmentVariables")}
    url = body.get("sourceUploadUrl") or ""
    m = re.search(r"/gcf-upload/([^/?]+)/([^?]+)", url)
    if m:
        bc["source"] = {"storageSource": {"bucket": m.group(1), "object": m.group(2)}}
    elif body.get("sourceArchiveUrl", "").startswith("gs://"):
        bkt, _, obj = body["sourceArchiveUrl"][5:].partition("/")
        bc["source"] = {"storageSource": {"bucket": bkt, "object": obj}}
    elif body.get("sourceRepository"):
        bc["source"] = {"repoSource": {"projectId": project, "branchName": "main"}}
    sc = {}
    if "timeout" in body:
        sc["timeoutSeconds"] = body["timeout"]
    if "availableMemoryMb" in body:
        mb = int(body["availableMemoryMb"])
        sc["availableMemory"] = next((k for k, v in _MEM.items() if v == mb), None) or "%dM" % mb
    for a, b in (("environmentVariables", "environmentVariables"), ("maxInstances", "maxInstanceCount"), ("minInstances", "minInstanceCount"),
                 ("ingressSettings", "ingressSettings"), ("serviceAccountEmail", "serviceAccountEmail"), ("vpcConnector", "vpcConnector")):
        if a in body:
            sc[b] = body[a]
    out["buildConfig"] = {k: v for k, v in bc.items() if v is not None}
    out["serviceConfig"] = sc
    et = body.get("eventTrigger")
    if et:
        res = et.get("resource", "")
        t = et.get("eventType", "")
        mapped = {"google.pubsub.topic.publish": "google.cloud.pubsub.topic.v1.messagePublished",
                  "google.storage.object.finalize": "google.cloud.storage.object.v1.finalized",
                  "google.storage.object.delete": "google.cloud.storage.object.v1.deleted"}.get(t, t)
        e2 = {"eventType": mapped, "resource": res, "service": et.get("service", ""), "failurePolicy": et.get("failurePolicy", {})}
        if mapped.startswith("google.cloud.pubsub"):
            e2["pubsubTopic"] = res
        elif mapped.startswith("google.cloud.storage"):
            e2["eventFilters"] = [{"attribute": "bucket", "value": res.rsplit("/", 1)[-1]}]
        out["eventTrigger"] = e2
    return out


def _create(ctx, v, project, location, q, body):
    R._check_location(location) if hasattr(R, "_check_location") else None
    if v == 1:
        nm = (body.get("name") or "")
        fid = nm.rsplit("/", 1)[-1]
        if nm and nm != "projects/%s/locations/%s/functions/%s" % (project, location, fid):
            raise _E(400, "INVALID_ARGUMENT", "Function name must be projects/%s/locations/%s/functions/{name}." % (project, location))
        body = _v1_to_v2_body(ctx, project, location, body)
        gen = 1
    else:
        fid = q.get("functionId") or ""
        gen = 2 if (body.get("environment") or "GEN_2") == "GEN_2" else 1
    _name_ok(fid)
    full, svc = _svc(ctx, project, location, fid)
    if svc is not None:
        raise _E(409, "ALREADY_EXISTS", "Function %s in region %s in project %s already exists" % (fid, location, project))
    m = _v2_to_meta(ctx, project, location, fid, body, gen)
    try:
        R.create_service(ctx["run"], project, location, {"serviceId": fid}, {
            "template": {"containers": [{"image": R._pseudo_image(m["buildConfig"]["runtime"], m["buildConfig"]["entryPoint"], m["code"])}],
                         "timeout": "%ds" % m["serviceConfig"]["timeoutSeconds"],
                         "scaling": {"minInstanceCount": m["serviceConfig"]["minInstanceCount"], "maxInstanceCount": m["serviceConfig"]["maxInstanceCount"]}},
            "annotations": _annotations(m), "labels": dict(m["labels"], **{"goog-managed-by": "cloudfunctions"}),
            "ingress": {"ALLOW_ALL": "INGRESS_TRAFFIC_ALL", "ALLOW_INTERNAL_ONLY": "INGRESS_TRAFFIC_INTERNAL_ONLY",
                        "ALLOW_INTERNAL_AND_GCLB": "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"}[m["serviceConfig"]["ingressSettings"]]})
    except R._E as e:
        raise _E(e.status, e.gcp_status, e.message)
    _bag(ctx["bag"])["fns"][full] = m
    try:
        _eventarc(ctx, m, True)
    except _E:
        R.delete_service(ctx["run"], project, location, fid, {})
        _bag(ctx["bag"])["fns"].pop(full, None)
        raise
    if (body.get("iamPolicyPublic")):
        pass
    return _lro(ctx, m, _view(ctx, m, v), v, "create")


def _update(ctx, v, project, location, fid, q, body):
    full, svc = _svc(ctx, project, location, fid)
    m = _meta(ctx, full)
    if svc is None or m is None:
        raise _E(404, "NOT_FOUND", "Function %s in region %s in project %s does not exist" % (fid, location, project))
    if v == 1:
        body = _v1_to_v2_body(ctx, project, location, body, m)
        mask = [x for x in (q.get("updateMask") or "").split(",") if x]
        keep = {"description": "description", "labels": "labels", "runtime": "buildConfig", "entryPoint": "buildConfig", "timeout": "serviceConfig",
                "availableMemoryMb": "serviceConfig", "environmentVariables": "serviceConfig", "sourceUploadUrl": "buildConfig",
                "sourceArchiveUrl": "buildConfig", "eventTrigger": "eventTrigger", "maxInstances": "serviceConfig", "minInstances": "serviceConfig",
                "ingressSettings": "serviceConfig", "serviceAccountEmail": "serviceConfig", "buildEnvironmentVariables": "buildConfig", "vpcConnector": "serviceConfig"}
        if mask:
            body = {k: v_ for k, v_ in body.items() if k in {keep.get(x, x) for x in mask}}
    else:
        mask = [x for x in (q.get("updateMask") or "").split(",") if x]
        if mask:
            body = {k: v_ for k, v_ in body.items() if k in {x.split(".")[0] for x in mask}}
    m2 = _v2_to_meta(ctx, project, location, fid, body, m["gen"], prior=m)
    patch = {"annotations": _annotations(m2), "labels": dict(m2["labels"], **{"goog-managed-by": "cloudfunctions"}),
             "template": {"containers": [{"image": R._pseudo_image(m2["buildConfig"]["runtime"], m2["buildConfig"]["entryPoint"], m2["code"])}],
                          "timeout": "%ds" % m2["serviceConfig"]["timeoutSeconds"],
                          "scaling": {"minInstanceCount": m2["serviceConfig"]["minInstanceCount"], "maxInstanceCount": m2["serviceConfig"]["maxInstanceCount"]}}}
    try:
        R.update_service(ctx["run"], project, location, fid, {"updateMask": "annotations,labels,template"}, patch)
    except R._E as e:
        raise _E(e.status, e.gcp_status, e.message)
    _bag(ctx["bag"])["fns"][full] = m2
    if "eventTrigger" in body:
        _eventarc(ctx, m2, True)
    return _lro(ctx, m2, _view(ctx, m2, v), v, "update")


def _delete(ctx, v, project, location, fid):
    full, svc = _svc(ctx, project, location, fid)
    m = _meta(ctx, full)
    if svc is None or m is None:
        raise _E(404, "NOT_FOUND", "Function %s in region %s in project %s does not exist" % (fid, location, project))
    view = _view(ctx, m, v)
    _eventarc(ctx, m, False)
    R.delete_service(ctx["run"], project, location, fid, {})
    _bag(ctx["bag"])["fns"].pop(full, None)
    return _lro(ctx, m, view, v, "delete")


def _list(ctx, v, project, location, q):
    pre = "projects/%s/locations/" % project
    fns = [m for k, m in sorted(_bag(ctx["bag"])["fns"].items())
           if k.startswith(pre) and (location in ("-", m["location"])) and (v == 2 or True) and ctx["run"].services.get(k)]
    if v == 1:
        fns = [m for m in fns if m["gen"] == 1] if q.get("filter") == "gen1" else fns
    size = int(q.get("pageSize") or 0) or len(fns) or 1
    start = int(q.get("pageToken") or 0)
    chunk = fns[start:start + size]
    out = {"functions": [_view(ctx, m, v) for m in chunk]}
    if start + size < len(fns):
        out["nextPageToken"] = str(start + size)
    if v == 2:
        out["unreachable"] = []
    return out


# ── upload / download / call / iam ──────────────────────────────────────────────────────
def _upload_url(ctx, project, location, body):
    b = _staging_bucket(ctx, project, location)
    obj = "%s/function-source.zip" % ("up-%012x" % (int(time.time() * 1000) & 0xffffffffffff))
    b_ = _bag(ctx["bag"])
    b_["seq"] += 1
    obj = "%s-%d/function-source.zip" % (R._h("up", project, location, str(b_["seq"]))[:12], b_["seq"])
    return {"uploadUrl": "%s/gcf-upload/%s/%s" % (ctx.get("base", ""), b, obj), "storageSource": {"bucket": b, "object": obj, "generation": "1"}}


def _download_url(ctx, project, location, fid):
    full, svc = _svc(ctx, project, location, fid)
    m = _meta(ctx, full)
    if svc is None or m is None:
        raise _E(404, "NOT_FOUND", "Function %s does not exist" % fid)
    ss = (m["buildConfig"].get("source") or {}).get("storageSource") or {}
    if not ss.get("bucket"):
        raise _E(400, "FAILED_PRECONDITION", "The function has no stored source archive.")
    return {"downloadUrl": "%s/storage/v1/b/%s/o/%s?alt=media" % (ctx.get("base", ""), ss["bucket"], ss["object"].replace("/", "%2F"))}


def _execute(ctx, m, mode, payload, headers=None, method="POST", path="/", query=""):
    """Run the function's real source. mode 'http' -> Flask-like request; 'event' -> handler(event)."""
    from core import gcp_console_tabs as T
    env = dict(m["serviceConfig"]["environmentVariables"])
    env.update({"FUNCTION_TARGET": m["buildConfig"]["entryPoint"], "K_SERVICE": m["id"], "GCP_PROJECT": m["project"]})
    runtime = m["buildConfig"]["runtime"]
    t0 = time.perf_counter()
    if not runtime.startswith("python"):
        out = {"ok": None, "status": 202, "body": b"", "logs": "", "error": "%s functions are stored and validated but not executed here (Python only)" % runtime}
    elif mode == "http":
        out = T.run_http_function(m["code"], m["buildConfig"]["entryPoint"], {"method": method, "path": path, "query": query, "headers": headers or {}, "body": payload or b""}, "gcp", env)
    else:
        r = T.run_python_function(m["code"], m["buildConfig"]["entryPoint"], payload, env)
        out = {"ok": r["status"] == "SUCCESS", "status": 200 if r["status"] == "SUCCESS" else 500, "result": r.get("result"), "logs": r.get("logs", ""),
               "error": r.get("error", "")}
    ms = (time.perf_counter() - t0) * 1000
    full, svc = _svc(ctx, m["project"], m["location"], m["id"])
    if svc is not None:
        svc["_requestCount"] = svc.get("_requestCount", 0) + 1
        svc["_lastInvokeTime"] = _now()
        try:
            R._record_observability(ctx["run"], m["project"], m["location"], m["id"], (svc.get("latestReadyRevision") or "").rsplit("/", 1)[-1],
                                    svc, {"ok": out.get("ok") is not False and out.get("status", 200) < 500, "error": out.get("error", "")}, ms)
        except Exception:
            pass
    return out


def _call(ctx, project, location, fid, body):
    full, svc = _svc(ctx, project, location, fid)
    m = _meta(ctx, full)
    if svc is None or m is None:
        raise _E(404, "NOT_FOUND", "Function %s in region %s in project %s does not exist" % (fid, location, project))
    data = body.get("data", "")
    eid = R._h("exec", full, str(time.time()))[:12]
    if not m.get("eventTrigger"):   # an HTTP function: `call` POSTs the data to it
        out = _execute(ctx, m, "http", data.encode() if isinstance(data, str) else json.dumps(data).encode(),
                       {"content-type": "application/json"})
        res = out.get("body", b"")
        res = res.decode("utf-8", "replace") if isinstance(res, (bytes, bytearray)) else str(res)
    else:
        try:
            ev = json.loads(data) if isinstance(data, str) and data.strip() else (data or {})
        except ValueError:
            raise _E(400, "INVALID_ARGUMENT", "The call data must be valid JSON for an event-triggered function.")
        out = _execute(ctx, m, "event", ev)
        res = json.dumps(out.get("result")) if out.get("result") is not None else ""
    r = {"executionId": eid, "result": res}
    if out.get("ok") is False or out.get("status", 200) >= 500:
        r["error"] = (out.get("error") or res or "Function execution failed")[:1000]
        r.pop("result", None)
    return r


def _policy(ctx, project, location, fid, verb, body):
    full, svc = _svc(ctx, project, location, fid)
    if svc is None or _meta(ctx, full) is None:
        raise _E(404, "NOT_FOUND", "Function %s does not exist" % fid)
    # the function's IAM policy IS the Run service's: role names are translated both ways
    run = ctx["run"]
    if verb == "getIamPolicy":
        pol = R.get_iam_policy(run, full, {})
        return {**pol, "bindings": [dict(b, role="roles/cloudfunctions.invoker" if b.get("role") == "roles/run.invoker" else b.get("role")) for b in pol.get("bindings") or []]}
    if verb == "setIamPolicy":
        pol = dict(body.get("policy") or {})
        pol["bindings"] = [dict(b, role="roles/run.invoker" if b.get("role") == "roles/cloudfunctions.invoker" else b.get("role")) for b in pol.get("bindings") or []]
        out = R.set_iam_policy(run, full, {"policy": pol})
        return {**out, "bindings": [dict(b, role="roles/cloudfunctions.invoker" if b.get("role") == "roles/run.invoker" else b.get("role")) for b in out.get("bindings") or []]}
    perms = body.get("permissions") or []
    return {"permissions": [x for x in perms if x.startswith("cloudfunctions.")]}


_UPGRADE = ("abortFunctionUpgrade", "commitFunctionUpgrade", "commitFunctionUpgradeAsGen2", "redirectFunctionUpgradeTraffic",
            "rollbackFunctionUpgradeTraffic", "setupFunctionUpgradeConfig")


def _upgrade(ctx, project, location, fid, verb, body):
    """Gen1 -> gen2 upgrade state machine over the stored function: setup -> redirect -> commit (or rollback / abort)."""
    full, svc = _svc(ctx, project, location, fid)
    m = _meta(ctx, full)
    if svc is None or m is None:
        raise _E(404, "NOT_FOUND", "Function %s does not exist" % fid)
    st = m.setdefault("upgradeState", "UPGRADE_STATE_UNSPECIFIED")
    if verb == "setupFunctionUpgradeConfig":
        if m["gen"] != 1:
            raise _E(400, "FAILED_PRECONDITION", "Only 1st gen functions can be upgraded.")
        m["upgradeState"] = "SETUP_FUNCTION_UPGRADE_CONFIG_SUCCESSFUL"
    elif verb == "redirectFunctionUpgradeTraffic":
        if m["upgradeState"] != "SETUP_FUNCTION_UPGRADE_CONFIG_SUCCESSFUL":
            raise _E(400, "FAILED_PRECONDITION", "Run setupFunctionUpgradeConfig first.")
        m["upgradeState"] = "REDIRECT_FUNCTION_UPGRADE_TRAFFIC_SUCCESSFUL"
    elif verb == "rollbackFunctionUpgradeTraffic":
        if m["upgradeState"] != "REDIRECT_FUNCTION_UPGRADE_TRAFFIC_SUCCESSFUL":
            raise _E(400, "FAILED_PRECONDITION", "Traffic has not been redirected.")
        m["upgradeState"] = "ROLLBACK_FUNCTION_UPGRADE_TRAFFIC_SUCCESSFUL"
    elif verb in ("commitFunctionUpgrade", "commitFunctionUpgradeAsGen2"):
        if m["upgradeState"] not in ("REDIRECT_FUNCTION_UPGRADE_TRAFFIC_SUCCESSFUL",) and verb == "commitFunctionUpgrade":
            raise _E(400, "FAILED_PRECONDITION", "Traffic must be redirected before committing the upgrade.")
        m["gen"], m["upgradeState"] = 2, "COMMIT_FUNCTION_UPGRADE_SUCCESSFUL"
        svc["annotations"][_ANN + "gen"] = "2"
    elif verb == "abortFunctionUpgrade":
        m["upgradeState"] = "ABORT_FUNCTION_UPGRADE_SUCCESSFUL"
    m["updateTime"] = _now()
    view = _view_v2(ctx, m)
    view["upgradeInfo"] = {"upgradeState": m["upgradeState"]}
    return _lro(ctx, m, view, 2, "update")


# ── dispatch ────────────────────────────────────────────────────────────────────────────
def dispatch(bag, method, path, query, headers, body, ctx):
    """ctx: run (RunStore), gcs + gcs_mod, topic_exists, base (scheme://host of this endpoint)."""
    ctx = dict(ctx, bag=bag)
    p = path.split("?", 1)[0]
    method = method.upper()
    q = query or {}
    m = _UPLOAD.match(p)
    if m:   # the signed-URL stand-in: PUT of the zip -> the simulator's GCS
        if method not in ("PUT", "POST"):
            return _err(405, "UNIMPLEMENTED", "Method not allowed")
        if not ctx["gcs"].bucket_exists(m.group(1)):
            return _err(404, "NOT_FOUND", "Upload bucket %s does not exist" % m.group(1))
        r = _gcs(ctx, "POST", "/upload/storage/v1/b/%s/o" % m.group(1), {"uploadType": "media", "name": m.group(2)}, bytes(body),
                 {"content-type": "application/zip"})
        return Resp(200 if r.status < 300 else r.status, b"" if r.status < 300 else r.body, "text/plain")
    try:
        data = json.loads(body.decode("utf-8")) if body else {}
    except ValueError:
        return _err(400, "INVALID_ARGUMENT", "Invalid JSON payload received.")
    if not isinstance(data, dict):
        data = {}
    try:
        m = _V1OP.match(p)
        if m:
            ops = _bag(bag)["ops"]
            if m.group(1):
                op = ops.get("operations/" + m.group(1))
                if not op:
                    raise _E(404, "NOT_FOUND", "Operation operations/%s not found" % m.group(1))
                return Resp(200, op)
            return Resp(200, {"operations": list(ops.values())})
        m = _V2.match(p)
        if m:
            project, location, kind, fid, verb = m.groups()
            if kind == "runtimes":
                return Resp(200, {"runtimes": [{"name": r, "displayName": r, "stage": "GA" if not r.endswith(("313", "22", "123", "21", "dotnet8")) else "BETA",
                                                "environment": "GEN_2"} for r in _RUNTIMES]}) if method == "GET" else _err(405, "UNIMPLEMENTED", "Method not allowed")
            return Resp(200, _route(ctx, 2, method, project, location, fid, verb, q, data))
        m = _V1.match(p)
        if m:
            project, location, fid, verb = m.groups()
            return Resp(200, _route(ctx, 1, method, project, location, fid, verb, q, data))
    except _E as e:
        return _err(e.status, e.code, e.msg)
    except R._E as e:
        return _err(e.status, e.gcp_status, e.message)
    return _err(404, "NOT_FOUND", "Unknown path: %s" % path)


def _route(ctx, v, method, project, location, fid, verb, q, body):
    if fid is None:
        if verb == "generateUploadUrl" and method == "POST":
            return _upload_url(ctx, project, location, body)
        if method == "POST" and not verb:
            return _create(ctx, v, project, location, q, body)
        if method == "GET" and not verb:
            return _list(ctx, v, project, location, q)
        raise _E(405, "UNIMPLEMENTED", "Method not allowed")
    if verb in ("getIamPolicy", "setIamPolicy", "testIamPermissions"):
        return _policy(ctx, project, location, fid, verb, body)
    if verb == "generateDownloadUrl" and method == "POST":
        return _download_url(ctx, project, location, fid)
    if verb == "call" and v == 1 and method == "POST":
        return _call(ctx, project, location, fid, body)
    if verb in _UPGRADE and v == 2 and method == "POST":
        return _upgrade(ctx, project, location, fid, verb, body)
    if verb:
        raise _E(404, "NOT_FOUND", "Unknown method :%s" % verb)
    if method == "GET":
        full, svc = _svc(ctx, project, location, fid)
        m = _meta(ctx, full)
        if svc is None or m is None:
            raise _E(404, "NOT_FOUND", "Function %s in region %s in project %s does not exist" % (fid, location, project))
        return _view(ctx, m, v)
    if method == "PATCH":
        return _update(ctx, v, project, location, fid, q, body)
    if method == "DELETE":
        return _delete(ctx, v, project, location, fid)
    raise _E(405, "UNIMPLEMENTED", "Method not allowed")


def http_trigger(bag, method, path, query_string, headers, body, ctx):
    """/gcf/{project}/{location}/{function}[/rest]: the function's HTTPS URL. Returns a Resp, or None if it is not one of ours."""
    m = _HTTP.match(path.split("?", 1)[0])
    if not m:
        return None
    ctx = dict(ctx, bag=bag)
    project, location, fid, rest = m.groups()
    full, svc = _svc(ctx, project, location, fid)
    fm = _meta(ctx, full)
    if fm is None or svc is None:
        return None
    if fm["serviceConfig"]["ingressSettings"] == "ALLOW_INTERNAL_ONLY":
        return Resp(403, b"Error: Forbidden", "text/plain")
    try:
        R._check_invoker(ctx["run"], full, headers)   # the function's IAM policy decides who may call it
    except R._E as e:
        return Resp(e.status, ("Error: Forbidden\nYour client does not have permission to get URL %s from this server." % (rest or "/")).encode(), "text/html")
    out = _execute(ctx, fm, "http", body or b"", headers, method, rest or "/", query_string or "")
    if out.get("ok") is None:
        return Resp(501, out.get("error", "").encode(), "text/plain")
    ct = next((v for k, v in (out.get("headers") or {}).items() if k.lower() == "content-type"), "text/html")
    r = Resp(int(out.get("status", 200)), out.get("body", b""), ct)
    r.headers = {k: str(v) for k, v in (out.get("headers") or {}).items() if k.lower() not in ("content-type", "content-length")}
    return r
