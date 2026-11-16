# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Bedrock AgentCore Evaluations: evaluator registry (control plane) + the Evaluate data-plane call.

Control plane (signing name bedrock-agentcore): CreateEvaluator / GetEvaluator / ListEvaluators / UpdateEvaluator / DeleteEvaluator
(POST /evaluators/create, GET|PUT|DELETE /evaluators/{id}, POST /evaluators). Data plane: Evaluate (POST /evaluations/evaluate/{id}).

Scoring is thin glue over what already exists, no evaluation framework is vendored:
  * deterministic metrics - token-F1 + embedding cosine (core/llm_core.embed, feature-hash fallback when no model is up) against
    expectedResponse, assertion coverage, tool-trajectory exact/in-order/any-order match, tool-call error rate;
  * LLM-as-judge - custom `llmAsAJudge` evaluators and the judge-style built-ins call core/llm_core.chat with the evaluator
    instructions + rating scale and a JSON answer; when no local model is up the result falls back to the deterministic metric and
    says so in `explanation` (never a fabricated judge verdict).
Agent runs are read from `evaluationInput.sessionSpans` (OTel GenAI spans: the same documents AgentCore Observability stores).
Declared limits: StartBatchEvaluation / online evaluation configs are not implemented; ragas/deepeval are not used (they pull
heavy dependencies), the lexical + embedding + judge path above covers the golden-set use case.
"""
from __future__ import annotations

import json
import re
import secrets
import time
import urllib.parse

_REGION, _ACCT = "us-east-1", "000000000000"
BUILTINS = {
    "Builtin.Correctness": ("TRACE", "reference"), "Builtin.Faithfulness": ("TRACE", "judge"),
    "Builtin.Helpfulness": ("TRACE", "judge"), "Builtin.ResponseRelevance": ("TRACE", "relevance"),
    "Builtin.Conciseness": ("TRACE", "concise"), "Builtin.Coherence": ("TRACE", "judge"),
    "Builtin.Harmfulness": ("TRACE", "judge"), "Builtin.GoalSuccessRate": ("SESSION", "assertions"),
    "Builtin.ToolSelectionAccuracy": ("TOOL_CALL", "toolsel"), "Builtin.ToolParameterAccuracy": ("TOOL_CALL", "toolsel"),
    "Builtin.TrajectoryExactOrderMatch": ("SESSION", "traj_exact"), "Builtin.TrajectoryInOrderMatch": ("SESSION", "traj_inorder"),
    "Builtin.TrajectoryAnyOrderMatch": ("SESSION", "traj_any"),
}


class _Err(Exception):
    def __init__(self, status, code, msg):
        self.status, self.code, self.msg = status, code, msg


def handles(path: str) -> bool:
    return path.startswith("/evaluators") or path.startswith("/evaluations/evaluate/")


def _j(status, doc):
    return {"status": status, "headers": {"content-type": "application/json"}, "body": json.dumps(doc).encode()}


def _state(s3) -> dict:
    return s3.account.setdefault("agentcore_evaluators", {})


def _ts():
    return time.time()


def _arn(eid):
    return f"arn:aws:bedrock-agentcore:{'' if eid.startswith('Builtin.') else _REGION}:{'' if eid.startswith('Builtin.') else _ACCT}:evaluator/{eid}"


def _summary(e):
    return {k: e[k] for k in ("evaluatorArn", "evaluatorId", "evaluatorName", "description", "evaluatorType", "level", "status",
                              "createdAt", "updatedAt", "lockedForModification") if k in e}


def _builtin_doc(eid):
    lvl, _k = BUILTINS[eid]
    return {"evaluatorArn": _arn(eid), "evaluatorId": eid, "evaluatorName": eid, "description": f"Built-in evaluator {eid}",
            "evaluatorType": "Builtin", "level": lvl, "status": "ACTIVE", "createdAt": 1735689600.0, "updatedAt": 1735689600.0,
            "lockedForModification": True}


def _find(st, eid):
    if eid in BUILTINS:
        return _builtin_doc(eid)
    for e in st.values():
        if e["evaluatorId"] == eid or e["evaluatorName"] == eid:
            return e
    raise _Err(404, "ResourceNotFoundException", f"Evaluator {eid} not found.")


# ── control plane ───────────────────────────────────────────────────────────
def _create(st, p):
    name, cfg, level = p.get("evaluatorName"), p.get("evaluatorConfig"), p.get("level")
    if not name or not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_]{0,47}", str(name)):
        raise _Err(400, "ValidationException", "evaluatorName must match [a-zA-Z][a-zA-Z0-9_]{0,47}")
    if level not in ("TOOL_CALL", "TRACE", "SESSION"):
        raise _Err(400, "ValidationException", "level must be one of TOOL_CALL, TRACE, SESSION")
    if not isinstance(cfg, dict) or not (cfg.get("llmAsAJudge") or cfg.get("codeBased")):
        raise _Err(400, "ValidationException", "evaluatorConfig needs llmAsAJudge or codeBased")
    if any(e["evaluatorName"] == name for e in st.values()):
        raise _Err(409, "ConflictException", f"Evaluator {name} already exists.")
    eid = f"{name}-{secrets.token_hex(5)}"
    now = _ts()
    e = {"evaluatorArn": _arn(eid), "evaluatorId": eid, "evaluatorName": name, "description": p.get("description", ""),
         "evaluatorConfig": cfg, "level": level, "evaluatorType": "CodeBased" if cfg.get("codeBased") else "Custom",
         "status": "ACTIVE", "createdAt": now, "updatedAt": now, "lockedForModification": False}
    if p.get("kmsKeyArn"):
        e["kmsKeyArn"] = p["kmsKeyArn"]
    st[eid] = e
    return _j(202, {"evaluatorArn": e["evaluatorArn"], "evaluatorId": eid, "createdAt": now, "status": "ACTIVE"})


def _control(st, method, segs, query, p):
    if method == "POST" and segs == ["evaluators", "create"]:
        return _create(st, p)
    if method == "POST" and segs == ["evaluators"]:
        items = [_summary(_builtin_doc(b)) for b in BUILTINS] + [_summary(e) for e in st.values()]
        mx = int(p.get("maxResults") or 50)
        start = int(p.get("nextToken") or 0)
        out = {"evaluators": items[start:start + mx]}
        if start + mx < len(items):
            out["nextToken"] = str(start + mx)
        return _j(200, out)
    if len(segs) == 2:
        e = _find(st, segs[1])
        if method == "GET":
            return _j(200, e)
        if e.get("lockedForModification"):
            raise _Err(400, "ValidationException", "Built-in evaluators cannot be modified.")
        if method == "DELETE":
            st.pop(e["evaluatorId"], None)
            return _j(202, {"evaluatorArn": e["evaluatorArn"], "evaluatorId": e["evaluatorId"], "status": "DELETING"})
        if method == "PUT":
            for k in ("description", "evaluatorConfig", "level", "kmsKeyArn"):
                if k in p:
                    e[k] = p[k]
            e["updatedAt"] = _ts()
            return _j(202, {"evaluatorArn": e["evaluatorArn"], "evaluatorId": e["evaluatorId"], "updatedAt": e["updatedAt"], "status": "ACTIVE"})
    raise _Err(404, "ResourceNotFoundException", "Unknown evaluators operation")


# ── span extraction ─────────────────────────────────────────────────────────
def _attrs(sp):
    a = sp.get("attributes")
    if isinstance(a, dict):
        return a
    out = {}
    for x in a or []:
        v = x.get("value") or {}
        for k in ("stringValue", "intValue", "doubleValue", "boolValue"):
            if k in v:
                out[x.get("key", "")] = v[k]
    return out


def _text(v):
    if isinstance(v, str):
        try:
            j = json.loads(v)
            if isinstance(j, (dict, list)):
                return _text(j)
        except ValueError:
            return v
        return v
    if isinstance(v, dict):
        for k in ("text", "content", "message", "output", "completion"):
            if k in v:
                return _text(v[k])
        return " ".join(_text(x) for x in v.values() if isinstance(x, (str, dict, list)))
    if isinstance(v, list):
        return " ".join(_text(x) for x in v)
    return "" if v is None else str(v)


def _op(sp):
    a = _attrs(sp)
    op = a.get("gen_ai.operation.name", "")
    if op == "execute_tool" or a.get("gen_ai.tool.name"):
        return "tool"
    if op in ("chat", "text_completion", "generate_content") or a.get("gen_ai.request.model"):
        return "model"
    if op == "invoke_agent" or a.get("gen_ai.agent.name"):
        return "agent"
    return ""


def _span_prompt(sp):
    a = _attrs(sp)
    for k in ("gen_ai.prompt", "input.value", "gen_ai.request.input", "agent.input"):
        if a.get(k):
            return _text(a[k])
    for ev in sp.get("events") or []:
        if ev.get("name") in ("gen_ai.user.message", "gen_ai.content.prompt"):
            return _text(_attrs(ev) or ev.get("attributes"))
    return ""


def _span_response(sp):
    a = _attrs(sp)
    for k in ("gen_ai.completion", "gen_ai.response.text", "output.value", "agent.response", "gen_ai.response.output"):
        if a.get(k):
            return _text(a[k])
    for ev in sp.get("events") or []:
        if ev.get("name") in ("gen_ai.choice", "gen_ai.content.completion", "gen_ai.assistant.message"):
            return _text(_attrs(ev) or ev.get("attributes"))
    return ""


def _group(spans, target):
    """-> {traceId: [spans]} limited to the target trace/span ids."""
    tids = set((target or {}).get("traceIds") or [])
    sids = set((target or {}).get("spanIds") or [])
    by = {}
    for sp in spans:
        if isinstance(sp, dict):
            by.setdefault(str(sp.get("traceId") or sp.get("trace_id") or "t0"), []).append(sp)
    if tids:
        by = {k: v for k, v in by.items() if k in tids}
    if sids:
        by = {k: v for k, v in ((k, [s for s in v if (s.get("spanId") or s.get("span_id")) in sids]) for k, v in by.items()) if v}
    return by


def _trace_facts(spans):
    tools = [sp for sp in spans if _op(sp) == "tool"]
    prompt = next((p for p in (_span_prompt(s) for s in sorted(spans, key=lambda s: int(s.get("startTimeUnixNano") or 0))) if p), "")
    resp = ""
    for sp in sorted(spans, key=lambda s: -int(s.get("endTimeUnixNano") or 0)):
        resp = _span_response(sp)
        if resp:
            break
    names = [(_attrs(t).get("gen_ai.tool.name") or t.get("name") or "") for t in sorted(tools, key=lambda s: int(s.get("startTimeUnixNano") or 0))]
    errs = sum(1 for t in tools if (t.get("status") or {}).get("code") in (2, "STATUS_CODE_ERROR", "ERROR") or _attrs(t).get("error"))
    sid = next((str(_attrs(s)["session.id"]) for s in spans if _attrs(s).get("session.id")), "default")
    tok_in = sum(int(_attrs(s).get("gen_ai.usage.input_tokens") or 0) for s in spans)
    tok_out = sum(int(_attrs(s).get("gen_ai.usage.output_tokens") or 0) for s in spans)
    return {"prompt": prompt, "response": resp, "tools": names, "tool_spans": tools, "tool_errors": errs, "session": sid,
            "tok": (tok_in, tok_out)}


# ── scorers ─────────────────────────────────────────────────────────────────
def _toks(s):
    return re.findall(r"[a-z0-9]+", (s or "").lower())


def _f1(a, b):
    ta, tb = _toks(a), _toks(b)
    if not ta or not tb:
        return 0.0
    from collections import Counter
    common = sum((Counter(ta) & Counter(tb)).values())
    if not common:
        return 0.0
    p, r = common / len(ta), common / len(tb)
    return 2 * p * r / (p + r)


def _cosine(a, b):
    try:
        from core import llm_core
        v = llm_core.embed([a, b])["vectors"]
        x, y = v[0], v[1]
        d = sum(i * j for i, j in zip(x, y))
        n = (sum(i * i for i in x) ** 0.5) * (sum(j * j for j in y) ** 0.5)
        return max(0.0, d / n) if n else 0.0
    except Exception:
        return None


def _similarity(a, b):
    f = _f1(a, b)
    c = _cosine(a, b)
    return f if c is None else (f + c) / 2.0


def _coverage(assertion, response):
    ta = set(_toks(assertion))
    return len(ta & set(_toks(response))) / len(ta) if ta else 0.0


def _judge(instructions, scale, facts):
    """LLM-as-judge through the local-LLM seam. -> (value, label, explanation, tokens) or None when no model is up."""
    try:
        from core import llm_core
        labels = [f"{s.get('value', '')}={s['label']}: {s.get('definition', '')}" if "value" in s else f"{s['label']}: {s.get('definition', '')}"
                  for s in (scale.get("numerical") or scale.get("categorical") or [])]
        prompt = (f"{instructions}\n\nRating scale:\n" + "\n".join(labels) +
                  f"\n\nUser request: {facts['prompt']}\nAgent response: {facts['response']}\nTools called: {', '.join(facts['tools'])}\n"
                  'Answer with JSON only: {"label": "<one scale label>", "explanation": "<one sentence>"}')
        out = llm_core.chat([{"role": "user", "content": prompt}], max_tokens=160, temperature=0.0)
        obj, ok = llm_core.extract_json(out.get("text", ""))
        if not ok or not isinstance(obj, dict) or "label" not in obj:
            return None
        lab = str(obj["label"])
        entry = next((s for s in (scale.get("numerical") or scale.get("categorical") or []) if str(s["label"]).lower() == lab.lower()), None)
        if entry is None:
            return None
        return (float(entry["value"]) if "value" in entry else None, entry["label"], str(obj.get("explanation", "")),
                (out.get("input_tokens", 0), out.get("output_tokens", 0)))
    except Exception:
        return None


def _nearest(scale, score):
    """Map a 0..1 score onto the evaluator's rating scale."""
    num = scale.get("numerical")
    if num:
        lo, hi = min(s["value"] for s in num), max(s["value"] for s in num)
        target = lo + score * (hi - lo)
        s = min(num, key=lambda x: abs(x["value"] - target))
        return float(s["value"]), s["label"]
    cat = scale.get("categorical") or []
    if cat:
        return None, cat[min(len(cat) - 1, int(score * len(cat)))]["label"]
    return score, ""


def _score(kind, facts, ref, cfg):
    """-> (value 0..1, label, explanation, tokens)"""
    ref = ref or {}
    exp = _text((ref.get("expectedResponse") or {}).get("text"))
    asserts = [_text(a.get("text") if isinstance(a, dict) else a) for a in ref.get("assertions") or []]
    traj = (ref.get("expectedTrajectory") or {}).get("toolNames") or []
    tools = facts["tools"]
    if kind == "reference" or (kind == "judge" and exp):
        if not exp:
            return 0.0, "NoReference", "Correctness needs expectedResponse in evaluationReferenceInputs.", None
        v = _similarity(facts["response"], exp)
        return v, "", f"token-F1/embedding similarity of the response to expectedResponse = {v:.2f}", None
    if kind in ("relevance", "judge"):
        v = _similarity(facts["response"], facts["prompt"]) if facts["response"] else 0.0
        return min(1.0, v * 2), "", "heuristic (no judge model): lexical/embedding overlap of response with the request", None
    if kind == "concise":
        n = len(_toks(facts["response"]))
        v = 1.0 if 0 < n <= 120 else max(0.0, 1 - (n - 120) / 400) if n else 0.0
        return v, "", f"response length {n} tokens", None
    if kind == "assertions":
        if not asserts:
            return (1.0 if facts["response"] and not facts["tool_errors"] else 0.0), "", "no assertions given: non-empty response with no tool errors", None
        hit = [a for a in asserts if _coverage(a, facts["response"]) >= 0.6]
        return len(hit) / len(asserts), "", f"{len(hit)}/{len(asserts)} assertions supported by the response", None
    if kind == "toolsel":
        if traj:
            ok = sum(1 for t in tools if t in traj)
            v = ok / len(tools) if tools else 0.0
            return v, "", f"{ok}/{len(tools)} tool calls are in the expected tool set {traj}", None
        v = 1 - facts["tool_errors"] / len(tools) if tools else 1.0
        return v, "", f"{facts['tool_errors']} of {len(tools)} tool calls errored", None
    if kind.startswith("traj_"):
        if not traj:
            return 0.0, "NoReference", "trajectory evaluators need expectedTrajectory.toolNames", None
        if kind == "traj_exact":
            v = 1.0 if tools == traj else 0.0
        elif kind == "traj_inorder":
            it = iter(tools)
            v = 1.0 if all(any(t == x for x in it) for t in traj) else 0.0
        else:
            v = 1.0 if sorted(traj) == sorted(t for t in tools if t in traj) else 0.0
        return v, "", f"actual tools {tools} vs expected {traj}", None
    return 0.0, "", "unsupported evaluator", None


def _evaluate(st, eid, p):
    ev = _find(st, eid)
    inp = (p.get("evaluationInput") or {}).get("sessionSpans")
    if not isinstance(inp, list) or not inp:
        raise _Err(400, "ValidationException", "evaluationInput.sessionSpans must contain at least one span")
    by = _group(inp, p.get("evaluationTarget"))
    refs = p.get("evaluationReferenceInputs") or []
    results = []

    def ref_for(tid, sid):
        for r in refs:
            c = (r.get("context") or {}).get("spanContext") or {}
            if c.get("traceId") == tid or (not c.get("traceId") and c.get("sessionId") == sid):
                return r
        return refs[0] if len(refs) == 1 else None
    cfg = ev.get("evaluatorConfig") or {}
    llm = (cfg.get("llmAsAJudge") or {}) if cfg else {}
    kind = BUILTINS[ev["evaluatorId"]][1] if ev["evaluatorId"] in BUILTINS else ("judge_custom" if llm else "custom_code")
    if kind == "custom_code":
        raise _Err(400, "ValidationException", "codeBased (Lambda) evaluators are not executed by this simulator; use llmAsAJudge or a Builtin evaluator")
    units = []
    if ev["level"] == "SESSION":
        allspans = [s for v in by.values() for s in v]
        units.append((next(iter(by)), allspans))
    elif ev["level"] == "TOOL_CALL":
        for tid, v in by.items():
            for sp in v:
                if _op(sp) == "tool":
                    units.append((tid, [sp] + [s for s in v if s is not sp]))
    else:
        units = list(by.items())
    for tid, spans in units:
        facts = _trace_facts(spans)
        ref = ref_for(tid, facts["session"])
        scale = llm.get("ratingScale") or {}
        tokens, explanation, label, value = None, "", "", None
        if kind == "judge_custom":
            j = _judge(llm.get("instructions", ""), scale, facts)
            if j:
                value, label, explanation, tokens = j
                explanation = "LLM judge: " + explanation
            else:
                v0, _l, why, _t = _score("reference" if ref and (ref.get("expectedResponse") or {}) else "relevance", facts, ref, cfg)
                value, label = _nearest(scale, v0)
                explanation = f"no judge model reachable; fell back to deterministic metric ({why})"
        else:
            v0, label, explanation, tokens = _score(kind, facts, ref, cfg)
            value = round(v0, 4)
        sc = {"sessionId": facts["session"], "traceId": tid}
        if ev["level"] == "TOOL_CALL":
            sc["spanId"] = str(spans[0].get("spanId") or spans[0].get("span_id") or "")
        r = {"evaluatorArn": ev["evaluatorArn"], "evaluatorId": ev["evaluatorId"], "evaluatorName": ev["evaluatorName"],
             "explanation": explanation, "context": {"spanContext": sc}}
        if value is not None:
            r["value"] = float(value)
        if label:
            r["label"] = label
        if tokens:
            r["tokenUsage"] = {"inputTokens": int(tokens[0]), "outputTokens": int(tokens[1]), "totalTokens": int(tokens[0] + tokens[1])}
        results.append(r)
    return _j(200, {"evaluationResults": results})


def dispatch(s3, method, path, query, headers, body):
    method = method.upper()
    segs = [urllib.parse.unquote(x) for x in path.strip("/").split("/")]
    try:
        try:
            p = json.loads(body) if body else {}
        except ValueError:
            raise _Err(400, "ValidationException", "Malformed request body")
        if not isinstance(p, dict):
            raise _Err(400, "ValidationException", "Malformed request body")
        st = _state(s3)
        if segs[0] == "evaluations" and len(segs) == 3 and method == "POST":
            return _evaluate(st, segs[2], p)
        return _control(st, method, segs, query, p)
    except _Err as e:
        r = _j(e.status, {"message": e.msg})
        r["headers"]["x-amzn-errortype"] = e.code
        return r
