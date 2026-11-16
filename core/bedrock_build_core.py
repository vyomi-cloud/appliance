"""Bedrock "Build / Assess / Configure" control plane (lane uiaws): Prompt Management, Flows, model Evaluations, invocation logging,
prompt optimization and foundation-model availability, all on REAL wire shapes (signing name ``bedrock``).

  bedrock-agent          : CreatePrompt/Get/List/Update/Delete + CreatePromptVersion, CreateFlow/Get/List/Update/Delete/Prepare,
                           CreateFlowVersion/ListFlowVersions, CreateFlowAlias/ListFlowAliases/DeleteFlowAlias
  bedrock-agent-runtime  : InvokeFlow (eventstream: flowOutputEvent + flowCompletionEvent), OptimizePrompt (eventstream)
  bedrock                : CreateEvaluationJob/Get/List/Stop, Put/Get/DeleteModelInvocationLoggingConfiguration,
                           GetFoundationModelAvailability

THUMB RULE note: no OSS library implements these control planes (moto has no bedrock-agent prompts/flows/evaluations), so the stores are
thin dict records in the persisted account bag; every *behaviour* runs on existing engines: model calls go through the local-LLM seam
(core/llm_core), guardrail lexicon through core/bedrock_guardrails_core, objects through core/s3_object_core, logs through core/logs_core.

HONEST SCOPE
  - Flows: node types Input, Output, Prompt (inline or a managed promptArn), Condition (``name == "x"``, ``!=``, ``contains``, ``true``),
    Collector, Iterator-less. LambdaFunction / KnowledgeBase / Agent / Lex / Storage / Retrieval nodes are rejected at Prepare time.
  - Evaluations: automated model evaluation only, custom prompt dataset (JSONL prompt/referenceResponse/category), <=25 records,
    metrics Builtin.Accuracy (token F1 vs the reference), Builtin.Robustness (token F1 between the answer to the prompt and to a
    case/whitespace-perturbed prompt), Builtin.Toxicity (share of answers hitting the guardrail content lexicon). These are simple OSS-style
    metrics, NOT the managed service's BERTScore / real-world-knowledge scorers. Human, RAG and LLM-as-a-judge jobs are rejected.
  - Invocation logging: configuration is stored; S3 delivery (gzip JSON, real object layout) and CloudWatch Logs delivery happen on each
    successful InvokeModel/Converse. Image/video/embedding delivery flags are stored but those payloads are not produced.
  - Model availability: every served model is AVAILABLE (the local model needs no agreement); there is no entitlement workflow.
  - OptimizePrompt: a meta-prompt run by the local model; quality is that of the local model.
"""
from __future__ import annotations

import base64
import gzip
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
_BOUND = [None]       # object store (account bag + S3)
_LOGS = [None]        # CloudWatch Logs store (optional)
_MEM: dict = {}       # fallback when no store is bound (tests, bare calls)
_PATHS = re.compile(r"^/(prompts?|flows?|evaluation-jobs?|logging/modelinvocations|foundation-model-availability|optimize-prompt)(/|$)")


class BErr(Exception):
    def __init__(self, code, msg, status):
        super().__init__(msg)
        self.code, self.msg, self.status = code, msg, status


def bind(store, logs=None):
    if store is not None and hasattr(store, "account"):
        _BOUND[0] = store
    if logs is not None:
        _LOGS[0] = logs


def _st() -> dict:
    s = _BOUND[0]
    d = s.account.setdefault("bedrock_build", {}) if s is not None else _MEM
    for k in ("prompts", "flows", "evals"):
        d.setdefault(k, {})
    return d


def _persist():
    s = _BOUND[0]
    try:
        if s is not None and hasattr(s, "persist"):
            s.persist()
    except Exception:  # noqa: BLE001 - best effort write-through
        pass


def _j(status, doc):
    return {"status": status, "headers": {"content-type": "application/json"}, "body": json.dumps(doc).encode()}


def _err(e):
    return {"status": e.status, "headers": {"content-type": "application/json", "x-amzn-errortype": e.code}, "body": json.dumps({"message": e.msg}).encode()}


def _bad(m):
    return BErr("ValidationException", m, 400)


def _nf(m):
    return BErr("ResourceNotFoundException", m, 404)


def _iso(t=None):
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(t if t is not None else time.time()))


def _page(items, query, key):
    try:
        mx = int(query.get("maxResults") or 100)
        off = int(query.get("nextToken") or 0)
    except ValueError:
        raise _bad("Invalid maxResults/nextToken")
    out = {key: items[off:off + mx]}
    if off + mx < len(items):
        out["nextToken"] = str(off + mx)
    return out


def _llm():
    try:
        from core import llm_core as m
    except ImportError:
        import llm_core as m  # type: ignore
    return m


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


def _pub(d):
    return {k: v for k, v in d.items() if not k.startswith("_")}


_NAME = re.compile(r"^([0-9a-zA-Z][_-]?){1,100}$")


# ───────────────────────── Prompt Management ─────────────────────────
def _prompt_vars(variants):
    for v in variants:
        t = (v.get("templateConfiguration") or {}).get("text") or {}
        if v.get("templateType", "TEXT") != "TEXT":
            raise _bad("Only TEXT prompt variants are supported (chat variants are not simulated)")
        names = set(re.findall(r"\{\{\s*([A-Za-z0-9_-]+)\s*\}\}", t.get("text", "")))
        declared = {x.get("name") for x in t.get("inputVariables", [])}
        if names - declared:
            t["inputVariables"] = [{"name": n} for n in sorted(names)]
        if v.get("modelId") and am._resolve_model(v["modelId"]) is None:
            raise _bad(f"Variant {v.get('name')}: the provided model identifier is invalid.")
    return variants


def _prompt_view(pr, version="DRAFT"):
    src = pr if version == "DRAFT" else pr["_versions"][version]
    out = {k: src[k] for k in ("name", "description", "defaultVariant", "variants") if k in src}
    out.update({"id": pr["id"], "arn": pr["arn"] if version == "DRAFT" else f"{pr['arn']}:{version}", "version": version,
                "createdAt": pr["createdAt"], "updatedAt": src.get("updatedAt", pr["updatedAt"])})
    return out


def _prompt_core(pr_in, existing=None):
    if not pr_in.get("name") or not _NAME.match(pr_in["name"]):
        raise _bad("1 validation error detected: Value at 'name' failed to satisfy constraint: Member must satisfy regular expression pattern: ^([0-9a-zA-Z][_-]?){1,100}$")
    variants = _prompt_vars(pr_in.get("variants") or [])
    dv = pr_in.get("defaultVariant")
    if dv and dv not in [v.get("name") for v in variants]:
        raise _bad("defaultVariant must name one of the variants")
    return {"name": pr_in["name"], "description": pr_in.get("description"), "defaultVariant": dv, "variants": variants}


def _find_prompt(ident):
    ident = unquote(ident)
    ver = None
    m = re.match(r"^arn:aws[a-z-]*:bedrock:[^:]*:[0-9]*:prompt/([A-Z0-9]+)(?::(\d+))?$", ident)
    if m:
        ident, ver = m.group(1), m.group(2)
    pr = _st()["prompts"].get(ident)
    if not pr:
        raise _nf(f"Prompt {ident} not found")
    return pr, ver


def render_prompt(pr, ver, variant=None, values=None):
    """Prompt text + model for a managed prompt (used by the Flow Prompt node and tests)."""
    src = pr if not ver or ver == "DRAFT" else pr["_versions"].get(ver)
    if src is None:
        raise _nf(f"Prompt {pr['id']} version {ver} not found")
    vs = src["variants"]
    v = next((x for x in vs if x["name"] == (variant or src.get("defaultVariant"))), vs[0] if vs else None)
    if not v:
        raise _bad("The prompt has no variants")
    text = ((v.get("templateConfiguration") or {}).get("text") or {}).get("text", "")
    for k, val in (values or {}).items():
        text = re.sub(r"\{\{\s*" + re.escape(k) + r"\s*\}\}", lambda _m, val=val: str(val), text)
    return text, v


def _prompts(method, path, query, p):
    P = _st()["prompts"]
    if path == "/prompts":
        if method == "POST":
            core = _prompt_core(p)
            pid = uuid.uuid4().hex[:10].upper()
            now = _iso()
            pr = {"id": pid, "arn": f"arn:aws:bedrock:{_REG}:{_ACCT}:prompt/{pid}", **core, "createdAt": now, "updatedAt": now, "_versions": {}, "_tags": p.get("tags") or {}}
            P[pid] = pr
            _persist()
            return _j(201, _prompt_view(pr))
        if method == "GET":
            ident = query.get("promptIdentifier")
            items = []
            for pr in P.values():
                if ident and pr["id"] != unquote(ident).split("/")[-1].split(":")[0]:
                    continue
                items.append(pr)
            rows = []
            for pr in sorted(items, key=lambda x: x["createdAt"], reverse=True):
                rows.append({k: v for k, v in _prompt_view(pr).items() if k in ("id", "arn", "name", "description", "version", "createdAt", "updatedAt")})
                if ident:
                    rows += [{k: v for k, v in _prompt_view(pr, ver).items() if k in ("id", "arn", "name", "description", "version", "createdAt", "updatedAt")} for ver in pr["_versions"]]
            return _j(200, _page(rows, query, "promptSummaries"))
    m = re.match(r"^/prompts/([^/]+)(/versions)?$", path)
    if m:
        pr, _ = _find_prompt(m.group(1))
        if m.group(2):
            if method != "POST":
                raise BErr("UnknownOperationException", f"Unsupported operation: {method} {path}", 404)
            v = str(len(pr["_versions"]) + 1)
            pr["_versions"][v] = json.loads(json.dumps({k: pr[k] for k in ("name", "description", "defaultVariant", "variants")}))
            pr["_versions"][v]["updatedAt"] = _iso()
            _persist()
            return _j(201, _prompt_view(pr, v))
        if method == "GET":
            ver = query.get("promptVersion") or "DRAFT"
            if ver != "DRAFT" and ver not in pr["_versions"]:
                raise _nf(f"Prompt {pr['id']} version {ver} not found")
            return _j(200, _prompt_view(pr, ver))
        if method == "PUT":
            core = _prompt_core(p)
            pr.update(core)
            pr["updatedAt"] = _iso()
            _persist()
            return _j(200, _prompt_view(pr))
        if method == "DELETE":
            ver = query.get("promptVersion")
            if ver:
                if ver not in pr["_versions"]:
                    raise _nf(f"Prompt {pr['id']} version {ver} not found")
                del pr["_versions"][ver]
            else:
                del P[pr["id"]]
            _persist()
            return _j(202, {"id": pr["id"], **({"version": ver} if ver else {})})
    raise BErr("UnknownOperationException", f"Unsupported operation: {method} {path}", 404)


# ───────────────────────── Flows ─────────────────────────
_NODE_OK = {"Input", "Output", "Prompt", "Condition", "Collector"}


def _validate_flow(defn):
    nodes = (defn or {}).get("nodes") or []
    names = [n.get("name") for n in nodes]
    if len(set(names)) != len(names):
        raise _bad("Node names must be unique")
    if sum(1 for n in nodes if n.get("type") == "Input") != 1:
        raise _bad("A flow must have exactly one Input node")
    if not any(n.get("type") == "Output" for n in nodes):
        raise _bad("A flow must have at least one Output node")
    for n in nodes:
        if n.get("type") not in _NODE_OK:
            raise BErr("ValidationException", f"Node {n.get('name')}: node type {n.get('type')} is not supported by the Vyomi flow runner (supported: {', '.join(sorted(_NODE_OK))})", 400)
    for c in (defn or {}).get("connections") or []:
        if c.get("source") not in names or c.get("target") not in names:
            raise _bad(f"Connection {c.get('name')} references an unknown node")
    return defn


def _flow_view(f, version="DRAFT"):
    src = f if version == "DRAFT" else f["_versions"][version]
    out = {"id": f["id"], "arn": f["arn"] if version == "DRAFT" else f"{f['arn']}:{version}", "name": f["name"], "description": f.get("description"),
           "executionRoleArn": f["executionRoleArn"], "status": "NotPrepared" if version == "DRAFT" and not f.get("_prepared") else "Prepared",
           "createdAt": f["createdAt"], "updatedAt": f["updatedAt"], "version": version, "definition": src["definition"]}
    return {k: v for k, v in out.items() if v is not None}


def _find_flow(ident):
    ident = unquote(ident)
    m = re.match(r"^arn:aws[a-z-]*:bedrock:[^:]*:[0-9]*:flow/([A-Z0-9]+)", ident)
    ident = m.group(1) if m else ident
    f = _st()["flows"].get(ident)
    if not f:
        raise _nf(f"Flow {ident} not found")
    return f


def _flows(method, path, query, p):
    F = _st()["flows"]
    if path == "/flows":
        if method == "POST":
            if not p.get("name") or not _NAME.match(p["name"]):
                raise _bad("1 validation error detected: Value at 'name' failed to satisfy constraint: Member must satisfy regular expression pattern: ^([0-9a-zA-Z][_-]?){1,100}$")
            if not p.get("executionRoleArn"):
                raise _bad("1 validation error detected: Value null at 'executionRoleArn' failed to satisfy constraint: Member must not be null")
            if p.get("definition"):
                _validate_flow(p["definition"])
            fid = uuid.uuid4().hex[:10].upper()
            now = _iso()
            F[fid] = {"id": fid, "arn": f"arn:aws:bedrock:{_REG}:{_ACCT}:flow/{fid}", "name": p["name"], "description": p.get("description"), "executionRoleArn": p["executionRoleArn"],
                      "definition": p.get("definition") or {"nodes": [], "connections": []}, "createdAt": now, "updatedAt": now, "_versions": {}, "_aliases": {}, "_prepared": False}
            _persist()
            return _j(201, _flow_view(F[fid]))
        if method == "GET":
            rows = [{k: v for k, v in _flow_view(f).items() if k in ("id", "arn", "name", "description", "status", "createdAt", "updatedAt", "version")} for f in sorted(F.values(), key=lambda x: x["createdAt"], reverse=True)]
            return _j(200, _page(rows, query, "flowSummaries"))
    m = re.match(r"^/flows/([^/]+)(?:/(versions|aliases)(?:/([^/]+))?)?$", path)
    if m:
        f = _find_flow(m.group(1))
        sub, sid = m.group(2), m.group(3)
        if not sub:
            if method == "GET":
                return _j(200, _flow_view(f))
            if method == "PUT":
                if p.get("name"):
                    f["name"] = p["name"]
                for k in ("description", "executionRoleArn"):
                    if k in p:
                        f[k] = p[k]
                if "definition" in p:
                    _validate_flow(p["definition"])
                    f["definition"] = p["definition"]
                    f["_prepared"] = False
                f["updatedAt"] = _iso()
                _persist()
                return _j(200, _flow_view(f))
            if method == "POST":    # PrepareFlow
                _validate_flow(f["definition"])
                f["_prepared"] = True
                _persist()
                return _j(202, {"id": f["id"], "status": "Prepared", "version": "DRAFT"})
            if method == "DELETE":
                del F[f["id"]]
                _persist()
                return _j(202, {"id": f["id"]})
        if sub == "versions":
            if method == "POST" and not sid:
                _validate_flow(f["definition"])
                v = str(len(f["_versions"]) + 1)
                f["_versions"][v] = {"definition": json.loads(json.dumps(f["definition"]))}
                _persist()
                return _j(201, _flow_view(f, v))
            if method == "GET" and not sid:
                rows = [{"id": f["id"], "arn": f"{f['arn']}:{v}", "status": "Prepared", "createdAt": f["updatedAt"], "version": v} for v in f["_versions"]]
                return _j(200, _page(rows, query, "flowVersionSummaries"))
            if method == "GET" and sid in f["_versions"]:
                return _j(200, _flow_view(f, sid))
        if sub == "aliases":
            A = f["_aliases"]
            if method == "POST" and not sid:
                for k in ("name", "routingConfiguration"):
                    if not p.get(k):
                        raise _bad(f"1 validation error detected: Value null at '{k}' failed to satisfy constraint: Member must not be null")
                ver = p["routingConfiguration"][0].get("flowVersion")
                if ver not in f["_versions"]:
                    raise _nf(f"Flow {f['id']} version {ver} not found")
                aid = uuid.uuid4().hex[:10].upper()
                now = _iso()
                A[aid] = {"id": aid, "arn": f"{f['arn']}/alias/{aid}", "flowId": f["id"], "name": p["name"], "description": p.get("description"),
                          "routingConfiguration": p["routingConfiguration"], "createdAt": now, "updatedAt": now}
                _persist()
                return _j(201, {k: v for k, v in A[aid].items() if v is not None})
            if method == "GET" and not sid:
                return _j(200, _page([{k: v for k, v in a.items() if v is not None} for a in A.values()], query, "flowAliasSummaries"))
            if sid and (sid in A) and method == "GET":
                return _j(200, A[sid])
            if sid and method == "DELETE":
                if sid not in A:
                    raise _nf(f"Alias {sid} not found")
                del A[sid]
                _persist()
                return _j(200, {"flowId": f["id"], "id": sid})
    m = re.match(r"^/flows/([^/]+)/aliases/([^/]+)$", path)
    if m and method == "POST":
        return _invoke_flow(m.group(1), m.group(2), p)
    raise BErr("UnknownOperationException", f"Unsupported operation: {method} {path}", 404)


def _frame(kind, payload):
    return am.eventstream_frame(kind, payload)


def _cond_true(expr, vals):
    expr = (expr or "").strip()
    if expr in ("", "true", "default"):
        return True
    m = re.match(r'^(\w+)\s*(==|!=|contains)\s*"(.*)"$', expr) or re.match(r"^(\w+)\s*(==|!=|contains)\s*'(.*)'$", expr)
    if not m:
        raise _bad(f"Unsupported condition expression {expr!r}: use  name == \"x\", name != \"x\", name contains \"x\" or true")
    a = str(vals.get(m.group(1), ""))
    return a == m.group(3) if m.group(2) == "==" else a != m.group(3) if m.group(2) == "!=" else m.group(3) in a


def run_flow(defn, inputs, max_steps=50):
    """Execute a flow definition. Returns [(nodeName, document)]; Prompt nodes call the local model."""
    nodes = {n["name"]: n for n in defn.get("nodes") or []}
    conns = defn.get("connections") or []
    start = next(n for n in nodes.values() if n["type"] == "Input")
    outs = []
    pending = [(start["name"], {"document": (inputs[0].get("content") or {}).get("document") if inputs else ""})]
    steps = 0
    while pending:
        steps += 1
        if steps > max_steps:
            raise _bad("Flow exceeded the maximum number of node executions (50)")
        name, vals = pending.pop(0)
        n = nodes[name]
        t = n["type"]
        produced = {}      # output name -> value
        fired = None       # for Condition nodes: names of satisfied conditions
        if t == "Input":
            produced = {"document": vals.get("document")}
        elif t == "Output":
            outs.append((name, vals.get("document")))
            continue
        elif t == "Collector":
            produced = {"collectedOutput": vals.get("input", vals.get("document"))}
        elif t == "Condition":
            fired = [c["name"] for c in (n.get("configuration") or {}).get("condition", {}).get("conditions", []) if _cond_true(c.get("expression"), vals)][:1]
            produced = dict(vals)
        elif t == "Prompt":
            cfg = (n.get("configuration") or {}).get("prompt", {}).get("sourceConfiguration", {})
            if "resource" in cfg:
                pr, ver = _find_prompt(cfg["resource"]["promptArn"])
                text, v = render_prompt(pr, ver, None, vals)
                mid = v.get("modelId")
            else:
                inl = cfg.get("inline") or {}
                text = ((inl.get("templateConfiguration") or {}).get("text") or {}).get("text", "")
                for k, val in vals.items():
                    text = re.sub(r"\{\{\s*" + re.escape(k) + r"\s*\}\}", lambda _m, val=val: str(val), text)
                mid = inl.get("modelId")
            if not mid or am._resolve_model(mid) is None:
                raise _bad(f"Node {name}: a valid modelId is required")
            produced = {"modelCompletion": _llm().chat([{"role": "user", "content": text}], max_tokens=256)["text"]}
        for c in conns:
            if c["source"] != name:
                continue
            if c.get("type") == "Conditional":
                if fired is not None and (c.get("configuration") or {}).get("conditional", {}).get("condition") in fired:
                    pending.append((c["target"], dict(produced)))
                continue
            d = (c.get("configuration") or {}).get("data") or {}
            if d.get("sourceOutput") in produced:
                pending.append((c["target"], {d.get("targetInput", "document"): produced[d["sourceOutput"]]}))
    return outs


def _invoke_flow(fid, alias, p):
    f = _find_flow(fid)
    aid = unquote(alias).split("/")[-1]
    if aid == "TSTALIASID":     # the console's built-in test alias runs the prepared DRAFT
        if not f.get("_prepared"):
            raise BErr("ConflictException", "The flow must be prepared before it can be tested.", 409)
        defn = f["definition"]
    else:
        a = f["_aliases"].get(aid)
        if not a:
            raise _nf(f"Flow alias {alias} not found")
        defn = f["_versions"][a["routingConfiguration"][0]["flowVersion"]]["definition"]
    if not p.get("inputs"):
        raise _bad("1 validation error detected: Value null at 'inputs' failed to satisfy constraint: Member must not be null")
    try:
        outs = run_flow(defn, p["inputs"])
    except _llm().LlmUnavailable:
        return _err(BErr("DependencyFailedException", "No local LLM backend is available on this substrate.", 424))
    frames = [_frame("flowOutputEvent", {"nodeName": n, "nodeType": "OutputFlowNode", "content": {"document": d}}) for n, d in outs]
    frames.append(_frame("flowCompletionEvent", {"completionReason": "SUCCESS"}))
    return {"status": 200, "headers": {"content-type": "application/vnd.amazon.eventstream", "x-amz-bedrock-flow-execution-id": uuid.uuid4().hex}, "body": b"".join(frames)}


# ───────────────────────── Evaluations ─────────────────────────
_METRICS = ("Builtin.Accuracy", "Builtin.Robustness", "Builtin.Toxicity")


def _toks(s):
    return re.findall(r"[a-z0-9]+", str(s).lower())


def f1(a, b):
    """Token-overlap F1 (SQuAD-style)."""
    ta, tb = _toks(a), _toks(b)
    if not ta or not tb:
        return float(ta == tb)
    from collections import Counter
    common = sum((Counter(ta) & Counter(tb)).values())
    if not common:
        return 0.0
    pr, rc = common / len(ta), common / len(tb)
    return 2 * pr * rc / (pr + rc)


def _toxic(text):
    try:
        from core import bedrock_guardrails_core as g
    except ImportError:
        import bedrock_guardrails_core as g  # type: ignore
    t = text.lower()
    return any(w in t for k in ("HATE", "INSULTS", "SEXUAL", "VIOLENCE") for w in g._CONTENT[k]) or any(w in _toks(t) for w in g._PROFANITY)


def _eval_view(j):
    return {k: v for k, v in j.items() if not k.startswith("_")}


def _run_eval(s3, job):
    llm = _llm()
    s3c = _s3()
    try:
        if s3 is None:
            raise RuntimeError("no object store bound")
        cfgs = job["evaluationConfig"]["automated"]["datasetMetricConfigs"]
        model = job["inferenceConfig"]["models"][0]["bedrockModel"]
        mid = model["modelIdentifier"]
        params = model.get("inferenceParams")
        try:
            params = json.loads(params) if isinstance(params, str) else (params or {})
        except ValueError:
            params = {}
        ob, op = _split_uri(job["outputDataConfig"]["s3Uri"])
        pre = f"{op.rstrip('/') + '/' if op else ''}{job['_id']}/"
        report = {"jobId": job["_id"], "model": mid, "scorer": "vyomi-oss-simple-metrics (token F1 / perturbation consistency / guardrail lexicon)", "datasets": []}
        for dc in cfgs:
            if job["status"] == "Stopping":
                break
            ib, ik = _split_uri(dc["dataset"]["datasetLocation"]["s3Uri"])
            g = s3c.get_object(s3, ib, ik, {}, {})
            if g.status != 200:
                raise RuntimeError(f"Cannot read dataset s3://{ib}/{ik}")
            rows, scores = [], {m: [] for m in dc["metricNames"]}
            for line in [x for x in g.body.decode("utf-8", "replace").splitlines() if x.strip()][:25]:
                rec = json.loads(line)
                prompt = rec.get("prompt")
                if not prompt:
                    raise RuntimeError("Dataset record is missing 'prompt'")
                mt = int(params.get("maxTokens") or params.get("max_tokens") or 192)
                ans = llm.chat([{"role": "user", "content": prompt}], max_tokens=mt, temperature=float(params.get("temperature", 0.0)))["text"]
                row = {"prompt": prompt, "category": rec.get("category"), "referenceResponse": rec.get("referenceResponse"), "modelResponse": ans, "scores": {}}
                for m in dc["metricNames"]:
                    if m == "Builtin.Accuracy":
                        v = f1(ans, rec["referenceResponse"]) if rec.get("referenceResponse") is not None else None
                    elif m == "Builtin.Robustness":
                        alt = llm.chat([{"role": "user", "content": "  " + prompt.upper().replace(" ", "  ")}], max_tokens=mt, temperature=0.0)["text"]
                        v = f1(ans, alt)
                    else:
                        v = 1.0 if _toxic(ans) else 0.0
                    if v is not None:
                        row["scores"][m] = round(v, 4)
                        scores[m].append(v)
                rows.append(row)
            key = f"{pre}{dc['dataset']['name']}.jsonl"
            s3c.put_object(s3, ob, key, "\n".join(json.dumps(r) for r in rows).encode(), {"content-type": "application/json"})
            report["datasets"].append({"name": dc["dataset"]["name"], "taskType": dc.get("taskType"), "records": len(rows), "output": f"s3://{ob}/{key}",
                                       "metrics": {m: (round(sum(v) / len(v), 4) if v else None) for m, v in scores.items()}})
        s3c.put_object(s3, ob, f"{pre}report.json", json.dumps(report).encode(), {"content-type": "application/json"})
        job["_report"] = report
        job["status"] = "Stopped" if job["status"] == "Stopping" else "Completed"
    except llm.LlmUnavailable:
        job["status"] = "Failed"
        job["failureMessages"] = ["No local LLM backend is available on this substrate."]
    except Exception as e:  # noqa: BLE001
        job["status"] = "Failed"
        job["failureMessages"] = [str(e)]
    job["lastModifiedTime"] = _iso()


def _evals(s3, method, path, query, p):
    E = _st()["evals"]
    if path == "/evaluation-jobs" and method == "POST":
        for k in ("jobName", "roleArn", "evaluationConfig", "inferenceConfig", "outputDataConfig"):
            if not p.get(k):
                raise _bad(f"1 validation error detected: Value null at '{k}' failed to satisfy constraint: Member must not be null")
        if (p.get("applicationType") or "ModelEvaluation") != "ModelEvaluation" or not (p["evaluationConfig"].get("automated")):
            raise _bad("Only automated model evaluation jobs are supported (human, RAG and LLM-as-a-judge evaluations are not simulated)")
        dcs = p["evaluationConfig"]["automated"].get("datasetMetricConfigs") or []
        if not dcs:
            raise _bad("evaluationConfig.automated.datasetMetricConfigs must have at least one dataset")
        tasks = ("Summarization", "Classification", "QuestionAndAnswer", "Generation", "Custom")
        for dc in dcs:
            if dc.get("taskType") not in tasks:
                raise _bad(f"taskType must be one of {', '.join(tasks)}")
            bad = [m for m in dc.get("metricNames") or [] if m not in _METRICS]
            if bad or not dc.get("metricNames"):
                raise _bad(f"Unsupported metric {bad or ''}: supported metrics are {', '.join(_METRICS)}")
            if not ((dc.get("dataset") or {}).get("datasetLocation") or {}).get("s3Uri") or not dc["dataset"].get("name"):
                raise _bad("dataset.name and dataset.datasetLocation.s3Uri are required")
        ms = (p["inferenceConfig"].get("models") or [])
        if len(ms) != 1 or not (ms[0].get("bedrockModel") or {}).get("modelIdentifier"):
            raise _bad("inferenceConfig.models must hold exactly one bedrockModel with a modelIdentifier")
        if am._resolve_model(ms[0]["bedrockModel"]["modelIdentifier"]) is None:
            raise _bad("The provided model identifier is invalid.")
        _split_uri(p["outputDataConfig"].get("s3Uri"))
        # Deterministic id: on Nano the async LLM front door replays the whole request per model call (llm_core.NeedAsync), so the job
        # is only stored once it has finished and a replay must derive the same id (a random one would leak partial S3 outputs).
        import hashlib
        jid = hashlib.sha1(json.dumps(p, sort_keys=True).encode()).hexdigest()[:12]
        while jid in E:
            jid = hashlib.sha1((jid + "x").encode()).hexdigest()[:12]
        now = _iso()
        job = {"_id": jid, "jobArn": f"arn:aws:bedrock:{_REG}:{_ACCT}:evaluation-job/{jid}", "jobName": p["jobName"], "status": "InProgress", "jobType": "Automated",
               "applicationType": "ModelEvaluation", "roleArn": p["roleArn"], "evaluationConfig": p["evaluationConfig"], "inferenceConfig": p["inferenceConfig"],
               "outputDataConfig": p["outputDataConfig"], "creationTime": now, "lastModifiedTime": now, **({"jobDescription": p["jobDescription"]} if p.get("jobDescription") else {})}
        _run_eval(s3, job)
        E[jid] = job
        _persist()
        return _j(202, {"jobArn": job["jobArn"]})
    if path == "/evaluation-jobs" and method == "GET":
        items = list(E.values())
        if query.get("statusEquals"):
            items = [x for x in items if x["status"] == query["statusEquals"]]
        if query.get("nameContains"):
            items = [x for x in items if query["nameContains"] in x["jobName"]]
        items.sort(key=lambda x: x["creationTime"], reverse=(query.get("sortOrder") or "Descending") == "Descending")
        rows = [{"jobArn": x["jobArn"], "jobName": x["jobName"], "status": x["status"], "creationTime": x["creationTime"], "jobType": x["jobType"], "applicationType": x["applicationType"],
                 "evaluationTaskTypes": [d["taskType"] for d in x["evaluationConfig"]["automated"]["datasetMetricConfigs"]],
                 "modelIdentifiers": [m["bedrockModel"]["modelIdentifier"] for m in x["inferenceConfig"]["models"]]} for x in items]
        return _j(200, _page(rows, query, "jobSummaries"))
    m = re.match(r"^/evaluation-jobs?/(.+?)(/stop)?$", path)
    if m:
        jid = re.sub(r"^arn:.*/", "", unquote(m.group(1)))
        job = E.get(jid)
        if not job:
            raise _nf(f"Evaluation job {jid} not found.")
        if m.group(2) and method == "POST":
            if job["status"] in ("Completed", "Failed", "Stopped"):
                raise BErr("ConflictException", f"Job is already in terminal state {job['status']}.", 409)
            job["status"] = "Stopped"
            return _j(200, {})
        if method == "GET" and not m.group(2):
            out = _eval_view(job)
            if job.get("_report"):
                out["vyomiReport"] = job["_report"]
            return _j(200, out)
        if method == "DELETE":
            del E[jid]
            _persist()
            return _j(202, {})
    raise BErr("UnknownOperationException", f"Unsupported operation: {method} {path}", 404)


# ───────────────────────── invocation logging ─────────────────────────
def _logging(method, path, query, p):
    d = _st()
    if method == "PUT":
        c = p.get("loggingConfig")
        if not isinstance(c, dict):
            raise _bad("1 validation error detected: Value null at 'loggingConfig' failed to satisfy constraint: Member must not be null")
        if not c.get("s3Config") and not c.get("cloudWatchConfig"):
            raise _bad("loggingConfig needs an s3Config and/or a cloudWatchConfig destination")
        if c.get("s3Config") and not c["s3Config"].get("bucketName"):
            raise _bad("s3Config.bucketName is required")
        if c.get("cloudWatchConfig") and (not c["cloudWatchConfig"].get("logGroupName") or not c["cloudWatchConfig"].get("roleArn")):
            raise _bad("cloudWatchConfig.logGroupName and roleArn are required")
        d["logging"] = c
        _persist()
        return _j(200, {})
    if method == "GET":
        return _j(200, {"loggingConfig": d["logging"]} if d.get("logging") else {})
    if method == "DELETE":
        d.pop("logging", None)
        _persist()
        return _j(200, {})
    raise BErr("UnknownOperationException", f"Unsupported operation: {method} {path}", 404)


def log_invocation(op, model_id, req_body, resp_body, status=200):
    """Called by the router after a successful InvokeModel/Converse: deliver the configured model-invocation log record."""
    c = _st().get("logging")
    if not c or status != 200 or not c.get("textDataDeliveryEnabled", True):
        return
    try:
        def js(b):
            try:
                return json.loads(b) if b else None
            except ValueError:
                return None
        now = time.time()
        rid = str(uuid.uuid4())
        rec = {"schemaType": "ModelInvocationLog", "schemaVersion": "1.0", "timestamp": _iso(now), "accountId": _ACCT, "identity": {"arn": f"arn:aws:iam::{_ACCT}:user/vyomi"},
               "region": _REG, "requestId": rid, "operation": op, "modelId": model_id,
               "input": {"inputContentType": "application/json", "inputBodyJson": js(req_body)}, "output": {"outputContentType": "application/json", "outputBodyJson": js(resp_body)}}
        s3c = c.get("s3Config")
        if s3c and _BOUND[0] is not None:
            tt = time.gmtime(now)
            pre = (s3c.get("keyPrefix") or "").strip("/")
            key = f"{pre + '/' if pre else ''}AWSLogs/{_ACCT}/BedrockModelInvocationLogs/{_REG}/{tt.tm_year:04d}/{tt.tm_mon:02d}/{tt.tm_mday:02d}/{tt.tm_hour:02d}/{int(now * 1000)}-{rid[:8]}.json.gz"
            _s3().put_object(_BOUND[0], s3c["bucketName"], key, gzip.compress(json.dumps(rec).encode()), {"content-type": "application/json", "content-encoding": "gzip"})
        cw = c.get("cloudWatchConfig")
        if cw and _LOGS[0] is not None:
            try:
                from core import logs_core
            except ImportError:
                import logs_core  # type: ignore
            ls, g, st = _LOGS[0], cw["logGroupName"], "aws/bedrock/modelinvocations"
            if g not in ls.log_groups:
                logs_core._create_log_group(ls, {"logGroupName": g})
            if st not in ls.log_groups[g]["streams"]:
                logs_core._create_log_stream(ls, {"logGroupName": g, "logStreamName": st})
            logs_core._put_log_events(ls, {"logGroupName": g, "logStreamName": st, "logEvents": [{"timestamp": int(now * 1000), "message": json.dumps(rec)}]})
    except Exception:  # noqa: BLE001 - delivery is best effort and must never fail the model call
        pass


# ───────────────────────── model availability + optimize ─────────────────────────
def _availability(mid):
    if am._resolve_model(mid) is None:
        raise _nf("Could not resolve the foundation model from the provided model identifier.")
    return {"modelId": mid, "agreementAvailability": {"status": "NOT_AVAILABLE"} if False else {"status": "AVAILABLE"}, "authorizationStatus": "AUTHORIZED",
            "entitlementAvailability": "AVAILABLE", "regionAvailability": "AVAILABLE"}


def _optimize(p):
    t = ((p.get("input") or {}).get("textPrompt") or {}).get("text")
    mid = p.get("targetModelId")
    if not t or not mid:
        raise _bad("input.textPrompt.text and targetModelId are required")
    if am._resolve_model(mid) is None:
        raise _bad("The provided model identifier is invalid.")
    llm = _llm()
    meta = ("Rewrite the following prompt so that a language model follows it more reliably: state the role and the task, name the output format, "
            "keep every {{variable}} placeholder unchanged, add no new facts. Reply with the rewritten prompt only.\n\nPROMPT:\n" + t)
    try:
        out = llm.chat([{"role": "user", "content": meta}], max_tokens=400, temperature=0.2)["text"].strip()
    except llm.LlmUnavailable:
        return _err(BErr("DependencyFailedException", "No local LLM backend is available on this substrate.", 424))
    frames = [_frame("analyzePromptEvent", {"message": "Analysed the prompt with the local model (a meta-prompt rewrite, not Bedrock's managed optimizer)."}),
              _frame("optimizedPromptEvent", {"optimizedPrompt": {"textPrompt": {"text": out}}})]
    return {"status": 200, "headers": {"content-type": "application/vnd.amazon.eventstream"}, "body": b"".join(frames)}


# ───────────────────────── dispatch ─────────────────────────
def handles(path: str) -> bool:
    return bool(_PATHS.match(re.sub(r"/{2,}", "/", "/" + path.strip("/")).lower()))


def dispatch(s3, method, path, query, body):
    method = method.upper()
    path = re.sub(r"/{2,}", "/", "/" + path.strip("/"))
    query = query or {}
    bind(s3)
    try:
        try:
            p = json.loads(body) if body else {}
            if not isinstance(p, dict):
                raise ValueError
        except ValueError:
            raise _bad("Malformed JSON")
        if path.startswith("/prompt"):
            return _prompts(method, path, query, p)
        if path.startswith("/flow"):
            return _flows(method, path, query, p)
        if path.startswith("/evaluation-job"):
            return _evals(s3, method, path, query, p)
        if path == "/logging/modelinvocations":
            return _logging(method, path, query, p)
        if path == "/optimize-prompt" and method == "POST":
            return _optimize(p)
        m = re.match(r"^/foundation-model-availability/(.+)$", path)
        if m and method == "GET":
            return _j(200, _availability(unquote(m.group(1))))
        raise BErr("UnknownOperationException", f"Unsupported operation: {method} {path}", 404)
    except BErr as e:
        return _err(e)
