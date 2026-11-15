# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Bedrock control plane, thin metadata adapters for the console's Infer + Tune pages (lane bedrockui-b).

Operations (REAL wire shapes, signing name ``bedrock``): ListInferenceProfiles / GetInferenceProfile / CreateInferenceProfile /
DeleteInferenceProfile, CreateModelInvocationJob / GetModelInvocationJob / ListModelInvocationJobs / StopModelInvocationJob,
CreateProvisionedModelThroughput / Get / List / Update / DeleteProvisionedModelThroughput, CreateModelCustomizationJob / Get / List /
Stop, ListCustomModels / GetCustomModel / DeleteCustomModel, CreatePromptRouter / Get / List / DeletePromptRouter (+ the two default
routers), Create/Get/List/Update/DeleteMarketplaceModelEndpoint + Register/Deregister.

HONEST SCOPE (no hand-built backend beyond metadata):
  - inference profiles: system-defined profiles are generated from the model aliases of core/ai_models_core (us/eu/apac); application
    profiles are records that Converse/InvokeModel resolve to their source model (``app_profile_model``).
  - batch inference: runs for real over the local-LLM seam (core/llm_core): reads the S3 JSONL input (``recordId`` + ``modelInput``),
    answers each record (max 25) and writes ``<output>/<jobId>/<input>.out`` + ``manifest.json.out``. No LLM backend => job Failed.
  - provisioned throughput: metadata only (InService immediately; no capacity is reserved, nothing is billed).
  - model customization: METADATA ONLY, no training happens. The job completes with a custom-model record so the console/SDK
    lifecycle works; the custom model is not a different network (invocation resolves to the base model's local alias).
  - marketplace endpoints: metadata only (no SageMaker endpoint is created).
State is process-local (module dicts).
"""
from __future__ import annotations

import json
import re
import time
import uuid
from urllib.parse import unquote

try:
    from core import ai_models_core as am
except ImportError:  # Pyodide flat layout
    import ai_models_core as am  # type: ignore

_ACCT, _REG = "123456789012", "us-east-1"
_APP: dict[str, dict] = {}      # application inference profiles
_BATCH: dict[str, dict] = {}
_PT: dict[str, dict] = {}
_JOBS: dict[str, dict] = {}     # model customization jobs
_CUSTOM: dict[str, dict] = {}
_ROUTERS: dict[str, dict] = {}
_MKT: dict[str, dict] = {}

_REGIONS = {
    "us": ["us-east-1", "us-east-2", "us-west-2"],
    "eu": ["eu-north-1", "eu-west-3", "eu-south-1", "eu-south-2", "eu-west-1", "eu-central-1"],
    "apac": ["ap-northeast-1", "ap-northeast-2", "ap-south-1", "ap-southeast-1", "ap-southeast-2"],
}
_NO_PROFILE = ("amazon.titan", "cohere", "meta.llama3-2-3b")
_PATHS = re.compile(r"^/(inference-profiles?|model-invocation-jobs?|provisioned-model-throughputs?|model-customization-jobs?|custom-models?|prompt-routers?|marketplace-model)(/|$)")


class CErr(Exception):
    def __init__(self, code, msg, status):
        super().__init__(msg)
        self.code, self.msg, self.status = code, msg, status


def _j(status, doc):
    return {"status": status, "headers": {"content-type": "application/json"}, "body": json.dumps(doc).encode()}


def _err(e):
    return {"status": e.status, "headers": {"content-type": "application/json", "x-amzn-errortype": e.code}, "body": json.dumps({"message": e.msg}).encode()}


def _bad(msg):
    return CErr("ValidationException", msg, 400)


def _nf(msg):
    return CErr("ResourceNotFoundException", msg, 404)


def _iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(t))


def _fm(mid):
    return f"arn:aws:bedrock:{_REG}::foundation-model/{mid}"


def _page(items, query, key):
    """maxResults/nextToken paging (token = numeric offset)."""
    try:
        mx = int(query.get("maxResults") or 100)
        off = int(query.get("nextToken") or 0)
    except ValueError:
        raise _bad("Invalid maxResults/nextToken")
    out = {key: items[off:off + mx]}
    if off + mx < len(items):
        out["nextToken"] = str(off + mx)
    return out


def _sort(items, query, field):
    rev = (query.get("sortOrder") or "Descending") == "Descending"
    return sorted(items, key=lambda x: x.get(field, 0) if not isinstance(x.get(field), str) else x[field], reverse=rev)


# ───────────── inference profiles ─────────────
def _sys_profiles():
    out = []
    for a in am.BEDROCK_ALIASES:
        if "EMBEDDING" in a[4] or a[0].startswith(_NO_PROFILE):
            continue
        for pre, regs in _REGIONS.items():
            out.append({
                "inferenceProfileName": f"{pre.upper()} {a[1]} {a[2]}" if a[1] != "Amazon" else f"{pre.upper()} {a[1]} {a[2]}",
                "description": f"Routes requests to {a[1]} {a[2]} in {', '.join(regs[:-1])} and {regs[-1]}. (Vyomi alias: answered by the local model)",
                "createdAt": "2024-08-01T00:00:00Z", "updatedAt": "2024-08-01T00:00:00Z",
                "inferenceProfileArn": f"arn:aws:bedrock:{_REG}:{_ACCT}:inference-profile/{pre}.{a[0]}",
                "models": [{"modelArn": f"arn:aws:bedrock:{r}::foundation-model/{a[0]}"} for r in regs],
                "inferenceProfileId": f"{pre}.{a[0]}", "status": "ACTIVE", "type": "SYSTEM_DEFINED"})
    return out


def _prof_view(p):
    return {k: v for k, v in p.items() if k != "tags"}


def _find_profile(ident):
    ident = unquote(ident)
    pid = re.sub(r"^arn:aws[a-z-]*:bedrock:[^:]*:[0-9]*:(application-)?inference-profile/", "", ident)
    if pid in _APP:
        return _APP[pid]
    for p in _sys_profiles():
        if p["inferenceProfileId"] == pid:
            return p
    raise _nf("Could not find the inference profile from the provided identifier.")


def _inference_profiles(method, path, query, p):
    if path == "/inference-profiles" and method == "GET":
        te = query.get("type") or query.get("typeEquals")
        if te and te not in ("SYSTEM_DEFINED", "APPLICATION"):
            raise _bad(f"1 validation error detected: Value '{te}' at 'typeEquals' failed to satisfy constraint: Member must satisfy enum value set: [SYSTEM_DEFINED, APPLICATION]")
        items = []
        if te in (None, "SYSTEM_DEFINED"):
            items += _sys_profiles()
        if te in (None, "APPLICATION"):
            items += [_prof_view(x) for x in _APP.values()]
        return _j(200, _page(items, query, "inferenceProfileSummaries"))
    if path == "/inference-profiles" and method == "POST":
        name = p.get("inferenceProfileName")
        if not isinstance(name, str) or not re.match(r"^([0-9a-zA-Z][ _-]?)+$", name) or len(name) > 64:
            raise _bad("1 validation error detected: Value at 'inferenceProfileName' failed to satisfy constraint: Member must satisfy regular expression pattern: ^([0-9a-zA-Z][ _-]?)+$")
        src = ((p.get("modelSource") or {}).get("copyFrom"))
        if not src:
            raise _bad("modelSource.copyFrom is required")
        if any(x["inferenceProfileName"] == name for x in _APP.values()):
            raise CErr("ConflictException", f"An inference profile with the name {name} already exists.", 409)
        base = re.sub(r"^arn:aws[a-z-]*:bedrock:[^:]*:[0-9]*:(foundation-model|inference-profile)/", "", src)
        if am._resolve_model(base) is None:
            raise _nf("The provided model identifier is invalid.")
        try:
            models = _find_profile(src)["models"]
        except CErr:
            models = [{"modelArn": _fm(base)}]
        pid = uuid.uuid4().hex[:12]
        now = _iso(time.time())
        _APP[pid] = {"inferenceProfileName": name, "description": p.get("description", ""), "createdAt": now, "updatedAt": now,
                     "inferenceProfileArn": f"arn:aws:bedrock:{_REG}:{_ACCT}:application-inference-profile/{pid}",
                     "models": models, "inferenceProfileId": pid, "status": "ACTIVE", "type": "APPLICATION",
                     "tags": p.get("tags") or [], "_source": base}
        return _j(201, {"inferenceProfileArn": _APP[pid]["inferenceProfileArn"], "status": "ACTIVE"})
    m = re.match(r"^/inference-profiles/(.+)$", path)
    if m and method == "GET":
        return _j(200, _prof_view(_find_profile(m.group(1))) | {})
    if m and method == "DELETE":
        pid = re.sub(r"^arn:.*/", "", unquote(m.group(1)))
        if pid not in _APP:
            raise _nf("Could not find the application inference profile.")
        del _APP[pid]
        return _j(200, {})
    raise CErr("UnknownOperationException", f"Unsupported Bedrock operation: {method} {path}", 404)


def app_profile_model(mid):
    """Resolve an application-inference-profile id/ARN or a prompt-router ARN to a model id (used by Converse/InvokeModel)."""
    ident = unquote(mid or "")
    m = re.match(r"^arn:aws[a-z-]*:bedrock:[^:]*:[0-9]*:application-inference-profile/(.+)$", ident)
    if m and m.group(1) in _APP:
        return _APP[m.group(1)]["_source"]
    m = re.match(r"^arn:aws[a-z-]*:bedrock:[^:]*:[0-9]*:(default-)?prompt-router/(.+)$", ident)
    if m:
        r = _all_routers().get(ident)
        if r:
            return re.sub(r"^arn:.*foundation-model/", "", r["models"][-1]["modelArn"])
    return None


# ───────────── batch inference ─────────────
_JOB_STATES = ("Submitted", "InProgress", "Completed", "Failed", "Stopping", "Stopped")


def _s3():
    try:
        from core import s3_object_core as m
    except ImportError:
        import s3_object_core as m  # type: ignore
    return m


def _split_uri(uri):
    m = re.match(r"^s3://([^/]+)/?(.*)$", uri or "")
    if not m:
        raise _bad("S3 URI must be of the form s3://bucket/prefix")
    return m.group(1), m.group(2)


def _record_text(mi):
    if not isinstance(mi, dict):
        return str(mi)
    if "prompt" in mi:
        return str(mi["prompt"])
    if "inputText" in mi:
        return str(mi["inputText"])
    ms = mi.get("messages") or []
    if ms:
        c = ms[-1].get("content")
        if isinstance(c, str):
            return c
        return " ".join(b.get("text", "") for b in (c or []) if isinstance(b, dict))
    return json.dumps(mi)


def _run_batch(s3, job):
    """Run the job over the local-LLM seam (synchronous; <=25 records)."""
    try:
        from core import llm_core as llm
    except ImportError:
        import llm_core as llm  # type: ignore
    s3c = _s3()
    ib, ip = _split_uri(job["inputDataConfig"]["s3InputDataConfig"]["s3Uri"])
    ob, op = _split_uri(job["outputDataConfig"]["s3OutputDataConfig"]["s3Uri"])
    try:
        if s3 is None:
            raise RuntimeError("no object store bound")
        r = s3c.list_objects_v2(s3, ib, {"list-type": "2", "prefix": ip, "max-keys": "1000"})
        keys = re.findall(rb"<Key>([^<]+)</Key>", r.body) if r.status == 200 else []
        keys = [k.decode() for k in keys if k.decode().endswith((".jsonl", ".json")) or k.decode() == ip]
        if not keys:
            raise RuntimeError(f"No JSONL input found under s3://{ib}/{ip}")
        total = ok = bad = 0
        for key in keys:
            g = s3c.get_object(s3, ib, key, {}, {})
            if g.status != 200:
                raise RuntimeError(f"Cannot read s3://{ib}/{key}")
            out = []
            for line in g.body.decode("utf-8", "replace").splitlines():
                if not line.strip() or total >= 25:
                    continue
                total += 1
                try:
                    rec = json.loads(line)
                    txt = _record_text(rec.get("modelInput"))
                    res = llm.chat([{"role": "user", "content": txt}], max_tokens=256)
                    out.append({"recordId": rec.get("recordId"), "modelInput": rec.get("modelInput"),
                                "modelOutput": {"content": [{"type": "text", "text": res["text"]}], "stop_reason": "end_turn",
                                                "usage": {"input_tokens": res.get("input_tokens", 0), "output_tokens": res.get("output_tokens", 0)}}})
                    ok += 1
                except llm.LlmUnavailable:
                    raise
                except Exception as e:  # noqa: BLE001 - a bad record is reported per record, as the service does
                    out.append({"recordId": (rec or {}).get("recordId") if isinstance(locals().get("rec"), dict) else None, "error": {"errorCode": 400, "errorMessage": str(e)}})
                    bad += 1
            okey = f"{op.rstrip('/') + '/' if op else ''}{job['_id']}/{key.rsplit('/', 1)[-1]}.out"
            s3c.put_object(s3, ob, okey, "\n".join(json.dumps(x) for x in out).encode(), {"content-type": "application/json"})
        mf = {"totalRecordCount": total, "processedRecordCount": ok + bad, "successRecordCount": ok, "errorRecordCount": bad, "inputTokenCount": 0, "outputTokenCount": 0}
        s3c.put_object(s3, ob, f"{op.rstrip('/') + '/' if op else ''}{job['_id']}/manifest.json.out", json.dumps(mf).encode(), {"content-type": "application/json"})
        job["status"] = "Completed"
    except Exception as e:  # noqa: BLE001
        job["status"] = "Failed"
        job["message"] = ("No local LLM backend is available on this substrate." if e.__class__.__name__ == "LlmUnavailable" else str(e))
    job["endTime"] = job["lastModifiedTime"] = _iso(time.time())


def _batch_view(j):
    return {k: v for k, v in j.items() if not k.startswith("_")}


def _batch(s3, method, path, query, p):
    if path == "/model-invocation-job" and method == "POST":
        for k in ("jobName", "roleArn", "modelId", "inputDataConfig", "outputDataConfig"):
            if not p.get(k):
                raise _bad(f"1 validation error detected: Value null at '{k}' failed to satisfy constraint: Member must not be null")
        if not (p["inputDataConfig"].get("s3InputDataConfig") or {}).get("s3Uri") or not (p["outputDataConfig"].get("s3OutputDataConfig") or {}).get("s3Uri"):
            raise _bad("inputDataConfig.s3InputDataConfig.s3Uri and outputDataConfig.s3OutputDataConfig.s3Uri are required")
        if am._resolve_model(p["modelId"]) is None:
            raise _bad("The provided model identifier is invalid.")
        jid = uuid.uuid4().hex[:12]
        now = _iso(time.time())
        job = {"_id": jid, "jobArn": f"arn:aws:bedrock:{_REG}:{_ACCT}:model-invocation-job/{jid}", "jobName": p["jobName"], "modelId": p["modelId"],
               "roleArn": p["roleArn"], "status": "InProgress", "submitTime": now, "lastModifiedTime": now,
               "inputDataConfig": p["inputDataConfig"], "outputDataConfig": p["outputDataConfig"],
               "timeoutDurationInHours": p.get("timeoutDurationInHours", 24), "_tags": p.get("tags") or []}
        _BATCH[jid] = job
        _run_batch(s3, job)
        return _j(200, {"jobArn": job["jobArn"]})
    if path == "/model-invocation-jobs" and method == "GET":
        items = list(_BATCH.values())
        if query.get("statusEquals"):
            items = [x for x in items if x["status"] == query["statusEquals"]]
        if query.get("nameContains"):
            items = [x for x in items if query["nameContains"] in x["jobName"]]
        items = _sort(items, query, "submitTime")
        return _j(200, _page([_batch_view(x) for x in items], query, "invocationJobSummaries"))
    m = re.match(r"^/model-invocation-job/(.+?)(/stop)?$", path)
    if m:
        jid = re.sub(r"^arn:.*/", "", unquote(m.group(1)))
        job = _BATCH.get(jid)
        if not job:
            raise _nf(f"Model invocation job {jid} not found.")
        if m.group(2) and method == "POST":
            if job["status"] in ("Completed", "Failed", "Stopped"):
                raise CErr("ConflictException", f"Job is already in terminal state {job['status']}.", 409)
            job["status"] = "Stopped"
            return _j(200, {})
        if method == "GET" and not m.group(2):
            return _j(200, _batch_view(job))
    raise CErr("UnknownOperationException", f"Unsupported Bedrock operation: {method} {path}", 404)


# ───────────── provisioned throughput ─────────────
def _pt_view(x):
    return {k: v for k, v in x.items() if not k.startswith("_")}


def _pt(method, path, query, p):
    if path == "/provisioned-model-throughput" and method == "POST":
        name, mid, units = p.get("provisionedModelName"), p.get("modelId"), p.get("modelUnits")
        if not name or not mid or not isinstance(units, int) or units < 1:
            raise _bad("provisionedModelName, modelId and modelUnits (>=1) are required")
        if any(x["provisionedModelName"] == name for x in _PT.values()):
            raise CErr("ConflictException", f"Provisioned model with name {name} already exists.", 409)
        cm = re.match(r"^arn:aws[a-z-]*:bedrock:[^:]*:[0-9]*:custom-model/(.+)$", mid)
        if cm:
            if cm.group(1) not in _CUSTOM:
                raise _nf("The custom model could not be found.")
            fm = _CUSTOM[cm.group(1)]["baseModelArn"]
        else:
            fm = mid if mid.startswith("arn:") else _fm(mid)
            if am._resolve_model(re.sub(r"^arn:.*foundation-model/", "", fm)) is None:
                raise _bad("The provided model identifier is invalid.")
        pid = uuid.uuid4().hex[:12]
        now = time.time()
        dur = p.get("commitmentDuration")
        exp = None
        if dur:
            months = {"OneMonth": 1, "SixMonths": 6}.get(dur)
            if not months:
                raise _bad("commitmentDuration must be OneMonth or SixMonths")
            exp = _iso(now + months * 30 * 86400)
        arn = f"arn:aws:bedrock:{_REG}:{_ACCT}:provisioned-model/{pid}"
        rec = {"provisionedModelName": name, "provisionedModelArn": arn, "modelArn": mid if mid.startswith("arn:") else _fm(mid), "desiredModelArn": mid if mid.startswith("arn:") else _fm(mid),
               "foundationModelArn": fm, "modelUnits": units, "desiredModelUnits": units, "status": "InService",
               "creationTime": _iso(now), "lastModifiedTime": _iso(now), "_id": pid}
        if dur:
            rec["commitmentDuration"] = dur
            rec["commitmentExpirationTime"] = exp
        _PT[pid] = rec
        return _j(201, {"provisionedModelArn": arn})
    if path == "/provisioned-model-throughputs" and method == "GET":
        items = list(_PT.values())
        if query.get("statusEquals"):
            items = [x for x in items if x["status"] == query["statusEquals"]]
        if query.get("nameContains"):
            items = [x for x in items if query["nameContains"] in x["provisionedModelName"]]
        items = _sort(items, query, "creationTime")
        return _j(200, _page([_pt_view(x) for x in items], query, "provisionedModelSummaries"))
    m = re.match(r"^/provisioned-model-throughput/(.+)$", path)
    if m:
        ident = unquote(m.group(1))
        rec = _PT.get(re.sub(r"^arn:.*/", "", ident)) or next((x for x in _PT.values() if x["provisionedModelName"] == ident), None)
        if not rec:
            raise _nf("Could not find the provisioned throughput.")
        if method == "GET":
            return _j(200, _pt_view(rec))
        if method == "PATCH":
            if p.get("desiredProvisionedModelName"):
                rec["provisionedModelName"] = p["desiredProvisionedModelName"]
            rec["lastModifiedTime"] = _iso(time.time())
            return _j(200, {})
        if method == "DELETE":
            del _PT[rec["_id"]]
            return _j(200, {})
    raise CErr("UnknownOperationException", f"Unsupported Bedrock operation: {method} {path}", 404)


# ───────────── model customization + custom models ─────────────
def _tick_jobs():
    """Metadata-only lifecycle: InProgress -> Completed 2 s after submit, producing the custom-model record. No training runs."""
    now = time.time()
    for j in _JOBS.values():
        if j["status"] == "InProgress" and now - j["_t"] >= 2:
            j["status"] = "Completed"
            j["endTime"] = j["lastModifiedTime"] = _iso(now)
            cid = j["_cid"]
            arn = f"arn:aws:bedrock:{_REG}:{_ACCT}:custom-model/{cid}"
            j["outputModelArn"], j["outputModelName"] = arn, j["_cname"]
            _CUSTOM[cid] = {"modelArn": arn, "modelName": j["_cname"], "creationTime": _iso(now), "baseModelArn": j["baseModelArn"],
                            "baseModelName": re.sub(r"^arn:.*foundation-model/", "", j["baseModelArn"]), "customizationType": j["customizationType"],
                            "ownerAccountId": _ACCT, "modelStatus": "Active", "jobArn": j["jobArn"], "jobName": j["jobName"],
                            "hyperParameters": j.get("hyperParameters", {}), "trainingDataConfig": j.get("trainingDataConfig"), "outputDataConfig": j.get("outputDataConfig")}


def _job_summary(j):
    d = {"jobArn": j["jobArn"], "baseModelArn": j["baseModelArn"], "jobName": j["jobName"], "status": j["status"], "lastModifiedTime": j["lastModifiedTime"],
         "creationTime": j["creationTime"], "customModelName": j["_cname"], "customizationType": j["customizationType"]}
    if j.get("endTime"):
        d["endTime"] = j["endTime"]
    if j.get("outputModelArn"):
        d["customModelArn"] = j["outputModelArn"]
    return d


def _job_get(j):
    d = _job_summary(j) | {"outputModelName": j["_cname"], "roleArn": j["roleArn"], "hyperParameters": j.get("hyperParameters", {}),
                           "trainingDataConfig": j.get("trainingDataConfig"), "outputDataConfig": j.get("outputDataConfig"),
                           "trainingMetrics": {}, "validationMetrics": [],
                           "vyomiNote": "Metadata only: Vyomi does not train; the job completes with a custom-model record."}
    if j.get("outputModelArn"):
        d["outputModelArn"] = j["outputModelArn"]
    return d


def _custom(method, path, query, p):
    _tick_jobs()
    if path == "/model-customization-jobs" and method == "POST":
        for k in ("jobName", "customModelName", "roleArn", "baseModelIdentifier", "trainingDataConfig", "outputDataConfig"):
            if not p.get(k):
                raise _bad(f"1 validation error detected: Value null at '{k}' failed to satisfy constraint: Member must not be null")
        base = p["baseModelIdentifier"]
        bid = re.sub(r"^arn:.*foundation-model/", "", base)
        if am._resolve_model(bid) is None:
            raise _bad("The provided base model identifier is invalid.")
        if any(x["jobName"] == p["jobName"] for x in _JOBS.values()):
            raise CErr("ConflictException", f"Job {p['jobName']} already exists.", 409)
        jid, cid = uuid.uuid4().hex[:12], uuid.uuid4().hex[:12]
        now = _iso(time.time())
        j = {"jobArn": f"arn:aws:bedrock:{_REG}:{_ACCT}:model-customization-job/{jid}", "jobName": p["jobName"], "status": "InProgress",
             "baseModelArn": base if base.startswith("arn:") else _fm(base), "creationTime": now, "lastModifiedTime": now, "roleArn": p["roleArn"],
             "customizationType": p.get("customizationType", "FINE_TUNING"), "hyperParameters": p.get("hyperParameters", {}),
             "trainingDataConfig": p["trainingDataConfig"], "outputDataConfig": p["outputDataConfig"], "_t": time.time(), "_cid": cid, "_cname": p["customModelName"], "_id": jid}
        _JOBS[jid] = j
        return _j(201, {"jobArn": j["jobArn"]})
    if path == "/model-customization-jobs" and method == "GET":
        items = list(_JOBS.values())
        if query.get("statusEquals"):
            items = [x for x in items if x["status"] == query["statusEquals"]]
        if query.get("nameContains"):
            items = [x for x in items if query["nameContains"] in x["jobName"]]
        items = _sort(items, query, "creationTime")
        return _j(200, _page([_job_summary(x) for x in items], query, "modelCustomizationJobSummaries"))
    m = re.match(r"^/model-customization-jobs/(.+?)(/stop)?$", path)
    if m:
        ident = unquote(m.group(1))
        j = _JOBS.get(re.sub(r"^arn:.*/", "", ident)) or next((x for x in _JOBS.values() if x["jobName"] == ident), None)
        if not j:
            raise _nf("Could not find the model customization job.")
        if m.group(2) and method == "POST":
            if j["status"] != "InProgress":
                raise CErr("ConflictException", f"Job is in state {j['status']} and cannot be stopped.", 409)
            j["status"] = "Stopped"
            j["lastModifiedTime"] = _iso(time.time())
            return _j(200, {})
        if method == "GET" and not m.group(2):
            return _j(200, _job_get(j))
    if path == "/custom-models" and method == "GET":
        items = list(_CUSTOM.values())
        if query.get("nameContains"):
            items = [x for x in items if query["nameContains"] in x["modelName"]]
        items = _sort(items, query, "creationTime")
        return _j(200, _page([{k: v for k, v in x.items() if k in ("modelArn", "modelName", "creationTime", "baseModelArn", "baseModelName", "customizationType", "ownerAccountId", "modelStatus")} for x in items], query, "modelSummaries"))
    m = re.match(r"^/custom-models?/(.+)$", path)
    if m:
        ident = unquote(m.group(1))
        c = _CUSTOM.get(re.sub(r"^arn:.*/", "", ident)) or next((x for x in _CUSTOM.values() if x["modelName"] == ident), None)
        if not c:
            raise _nf("Could not find the custom model.")
        if method == "GET":
            return _j(200, {k: v for k, v in c.items() if k != "modelStatus"})
        if method == "DELETE":
            if any(x["foundationModelArn"] == c["baseModelArn"] and x["modelArn"] == c["modelArn"] for x in _PT.values()):
                raise CErr("ConflictException", "The custom model is in use by a provisioned throughput.", 409)
            del _CUSTOM[re.sub(r"^arn:.*/", "", c["modelArn"])]
            return _j(200, {})
    raise CErr("UnknownOperationException", f"Unsupported Bedrock operation: {method} {path}", 404)


# ───────────── prompt routers ─────────────
def _default_routers():
    def mk(arn_tail, name, ids, desc):
        return {"promptRouterName": name, "routingCriteria": {"responseQualityDifference": 0.0}, "description": desc, "createdAt": "2024-11-01T00:00:00Z",
                "updatedAt": "2024-11-01T00:00:00Z", "promptRouterArn": f"arn:aws:bedrock:{_REG}:{_ACCT}:default-prompt-router/{arn_tail}",
                "models": [{"modelArn": f"arn:aws:bedrock:{_REG}:{_ACCT}:inference-profile/us.{i}"} for i in ids],
                "fallbackModel": {"modelArn": f"arn:aws:bedrock:{_REG}:{_ACCT}:inference-profile/us.{ids[-1]}"}, "status": "AVAILABLE", "type": "default"}
    return [mk("amazon.nova:1", "Nova Prompt Router", ["amazon.nova-lite-v1:0", "amazon.nova-pro-v1:0"], "Routes requests between Nova Lite and Nova Pro"),
            mk("anthropic.claude:1", "Anthropic Prompt Router", ["anthropic.claude-3-haiku-20240307-v1:0", "anthropic.claude-3-5-sonnet-20241022-v2:0"],
               "Routes requests between Claude 3 Haiku and Claude 3.5 Sonnet")]


def _all_routers():
    d = {r["promptRouterArn"]: r for r in _default_routers()}
    d.update({r["promptRouterArn"]: r for r in _ROUTERS.values()})
    return d


def _routers(method, path, query, p):
    if path == "/prompt-routers" and method == "POST":
        name = p.get("promptRouterName")
        ms = p.get("models") or []
        if not name or len(ms) != 2:
            raise _bad("promptRouterName and exactly two models are required")
        rc = p.get("routingCriteria") or {}
        q = rc.get("responseQualityDifference")
        if not isinstance(q, (int, float)) or not 0 <= q <= 1:
            raise _bad("routingCriteria.responseQualityDifference must be between 0 and 1")
        fb = p.get("fallbackModel") or {}
        if not fb.get("modelArn"):
            raise _bad("fallbackModel is required")
        if any(r["promptRouterName"] == name for r in _ROUTERS.values()):
            raise CErr("ConflictException", f"A prompt router named {name} already exists.", 409)
        rid = uuid.uuid4().hex[:10]
        now = _iso(time.time())
        arn = f"arn:aws:bedrock:{_REG}:{_ACCT}:prompt-router/{rid}"
        _ROUTERS[rid] = {"promptRouterName": name, "routingCriteria": {"responseQualityDifference": float(q)}, "description": p.get("description", ""), "createdAt": now,
                         "updatedAt": now, "promptRouterArn": arn, "models": ms, "fallbackModel": fb, "status": "AVAILABLE", "type": "custom"}
        return _j(200, {"promptRouterArn": arn})
    if path == "/prompt-routers" and method == "GET":
        ty = query.get("type")
        items = list(_all_routers().values())
        if ty:
            if ty not in ("custom", "default"):
                raise _bad("type must be custom or default")
            items = [x for x in items if x["type"] == ty]
        return _j(200, _page(items, query, "promptRouterSummaries"))
    m = re.match(r"^/prompt-routers/(.+)$", path)
    if m:
        arn = unquote(m.group(1))
        r = _all_routers().get(arn)
        if not r:
            raise _nf("Could not find the prompt router.")
        if method == "GET":
            return _j(200, r)
        if method == "DELETE":
            if r["type"] == "default":
                raise _bad("Default prompt routers cannot be deleted.")
            del _ROUTERS[arn.rsplit("/", 1)[-1]]
            return _j(200, {})
    raise CErr("UnknownOperationException", f"Unsupported Bedrock operation: {method} {path}", 404)


# ───────────── marketplace endpoints ─────────────
def _mkt_view(x, full=False):
    d = {k: v for k, v in x.items() if not k.startswith("_")}
    if not full:
        d = {k: d[k] for k in ("endpointArn", "modelSourceIdentifier", "status", "statusMessage", "createdAt", "updatedAt") if k in d}
    return d


def _mkt(method, path, query, p):
    if path == "/marketplace-model/endpoints" and method == "POST":
        src = p.get("modelSourceIdentifier")
        sm = (p.get("endpointConfig") or {}).get("sageMaker")
        if not src or not sm or not p.get("endpointName"):
            raise _bad("modelSourceIdentifier, endpointName and endpointConfig.sageMaker are required")
        if not p.get("acceptEula"):
            raise _bad("acceptEula must be true to deploy a marketplace model")
        arn = f"arn:aws:sagemaker:{_REG}:{_ACCT}:endpoint/{p['endpointName']}"
        if arn in _MKT:
            raise CErr("ConflictException", f"Endpoint {p['endpointName']} already exists.", 409)
        now = _iso(time.time())
        _MKT[arn] = {"endpointArn": arn, "modelSourceIdentifier": src, "status": "Registered", "statusMessage": "Metadata only: no SageMaker endpoint is provisioned by Vyomi.",
                     "createdAt": now, "updatedAt": now, "endpointConfig": p["endpointConfig"], "endpointStatus": "InService", "endpointStatusMessage": "In service (simulated)"}
        return _j(200, {"marketplaceModelEndpoint": _mkt_view(_MKT[arn], True)})
    if path == "/marketplace-model/endpoints" and method == "GET":
        items = list(_MKT.values())
        if query.get("modelSourceEquals"):
            items = [x for x in items if x["modelSourceIdentifier"] == query["modelSourceEquals"]]
        return _j(200, _page([_mkt_view(x) for x in items], query, "marketplaceModelEndpoints"))
    m = re.match(r"^/marketplace-model/endpoints/(.+?)(/registration)?$", path)
    if m:
        ident = unquote(m.group(1))
        arn = ident if ident.startswith("arn:") else f"arn:aws:sagemaker:{_REG}:{_ACCT}:endpoint/{ident}"
        if m.group(2) and method == "POST" and arn not in _MKT:      # RegisterMarketplaceModelEndpoint adopts an existing endpoint
            src = p.get("modelSourceIdentifier")
            if not src:
                raise _bad("modelSourceIdentifier is required")
            now = _iso(time.time())
            _MKT[arn] = {"endpointArn": arn, "modelSourceIdentifier": src, "status": "Registered", "statusMessage": "Registered (metadata only)",
                         "createdAt": now, "updatedAt": now, "endpointStatus": "InService", "endpointStatusMessage": "In service (simulated)"}
            return _j(200, {"marketplaceModelEndpoint": _mkt_view(_MKT[arn], True)})
        e = _MKT.get(arn)
        if not e:
            raise _nf("Could not find the marketplace model endpoint.")
        if m.group(2):
            if method == "POST":
                return _j(200, {"marketplaceModelEndpoint": _mkt_view(e, True)})
            if method == "DELETE":
                e["status"] = "Incompatible" if False else "NotRegistered"
                return _j(200, {})
        if method == "GET":
            return _j(200, {"marketplaceModelEndpoint": _mkt_view(e, True)})
        if method == "PATCH":
            e["endpointConfig"] = p.get("endpointConfig") or e.get("endpointConfig")
            e["updatedAt"] = _iso(time.time())
            return _j(200, {"marketplaceModelEndpoint": _mkt_view(e, True)})
        if method == "DELETE":
            del _MKT[arn]
            return _j(200, {})
    raise CErr("UnknownOperationException", f"Unsupported Bedrock operation: {method} {path}", 404)


# ───────────── dispatch ─────────────
def handles(path: str) -> bool:
    return bool(_PATHS.match(re.sub(r"/{2,}", "/", "/" + path.strip("/")).lower()))


def dispatch(s3, method, path, query, body):
    method = method.upper()
    path = re.sub(r"/{2,}", "/", "/" + path.strip("/"))
    query = query or {}
    try:
        p = json.loads(body) if body else {}
        if not isinstance(p, dict):
            raise ValueError
    except ValueError:
        return _err(_bad("Malformed JSON"))
    try:
        if path.startswith("/inference-profile"):
            return _inference_profiles(method, path, query, p)
        if path.startswith("/model-invocation-job"):
            return _batch(s3, method, path, query, p)
        if path.startswith("/provisioned-model-throughput"):
            return _pt(method, path, query, p)
        if path.startswith(("/model-customization-job", "/custom-model")):
            return _custom(method, path, query, p)
        if path.startswith("/prompt-router"):
            return _routers(method, path, query, p)
        return _mkt(method, path, query, p)
    except CErr as e:
        return _err(e)
