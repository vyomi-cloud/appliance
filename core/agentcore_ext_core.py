"""AgentCore extensions: Memory, Policy engines (Cedar), gateway policy enforcement + semantic tool search, and the runtime
tool kinds that make a supervisor agent route to sub-agents / gateway tools / memory. Thin wire adapters over OSS/shared engines:

  * Memory  (bedrock-agentcore-control /memories/*, bedrock-agentcore /memories/*): short-term events + long-term records.
            Long-term extraction = the local-LLM seam (core/llm_core.chat) with a deterministic heuristic fallback; retrieval =
            llm_core.embed + cosine over a namespace-prefix filter. No memory engine is written; mem0 was not adopted (needs a vector
            DB + LLM client stack, far over the Nano budget).
  * Policy  (bedrock-agentcore-control /policy-engines/*): real Cedar (cedarpy, the engine core/cedar_engine uses) evaluating one
            request per gateway tool call: principal = JWT identity with claims as Cedar TAGS, action = AgentCore::Action::"<target>___<tool>",
            resource = the gateway, context.input = tool arguments. ENFORCE = default deny, LOG_ONLY = allow + audit entry.
            Nano: cedarpy is native Rust and not in Pyodide -> a gateway with an ENFORCE engine denies every call there (fail closed).
  * Runtime tool kinds (registered into core/agent_spec_core): "agent" (sub-agent, inline spec or another runtime by name/id),
            "gateway" (an MCP gateway tool, caller JWT propagated), "memory" (retrieve long-term records).

Substrate-independent except cedarpy; stdlib only. JWT claims are decoded, NOT signature-verified (the simulator has no real IdP trust
chain; the Cognito lane mints the tokens), declared limit.
"""
from __future__ import annotations

import base64
import contextvars
import json
import re
import time

try:
    from core import bedrock_agents_core as B
    from core import llm_core as llm
    from core import agent_spec_core as ag
except ImportError:  # Pyodide flat layout
    import bedrock_agents_core as B  # type: ignore
    import llm_core as llm  # type: ignore
    import agent_spec_core as ag  # type: ignore

try:
    import cedarpy
except ImportError:
    cedarpy = None  # type: ignore[assignment]

_LOWER = B._LOWER
_MEM_NAME = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{0,47}$")
_STRAT = {"semanticMemoryStrategy": ("SEMANTIC", "/strategies/{memoryStrategyId}/actors/{actorId}"),
          "summaryMemoryStrategy": ("SUMMARIZATION", "/strategies/{memoryStrategyId}/actors/{actorId}/sessions/{sessionId}"),
          "userPreferenceMemoryStrategy": ("USER_PREFERENCE", "/strategies/{memoryStrategyId}/actors/{actorId}"),
          "episodicMemoryStrategy": ("EPISODIC", "/strategies/{memoryStrategyId}/actors/{actorId}/sessions/{sessionId}"),
          "customMemoryStrategy": ("CUSTOM", "/strategies/{memoryStrategyId}/actors/{actorId}")}


def _x(st):
    for k in ("memories", "policy_engines"):
        st.setdefault(k, {})
    st.setdefault("policy_audit", [])
    return st


def _page(items, q, key, p=None):
    pq = dict(q or {})
    if p:
        pq.update({k: str(v) for k, v in p.items() if k in ("maxResults", "nextToken") and v is not None})
    return B._paginate(items, pq, key)


# ═════════════════════════════ Memory ═════════════════════════════
def _mready(m):
    if m["status"] == "CREATING" and time.time() >= m["_readyAt"]:
        m["status"] = "ACTIVE"


def _mem_view(m):
    _mready(m)
    d = {k: v for k, v in m.items() if not k.startswith("_") and k not in ("events", "records")}
    d["strategies"] = [{k: v for k, v in s.items() if not k.startswith("_")} for s in m["strategies"]]
    return d


def _mk_strategy(inp):
    kinds = [k for k in _STRAT if k in inp]
    if len(kinds) != 1:
        raise B._bad("each memory strategy must name exactly one of " + ", ".join(_STRAT))
    cfg = inp[kinds[0]] or {}
    typ, default_ns = _STRAT[kinds[0]]
    if not cfg.get("name"):
        raise B._bad(f"{kinds[0]}.name is required")
    sid = f"{cfg['name']}-{B._rid(10, _LOWER)}"
    now = time.time()
    return {"strategyId": sid, "name": cfg["name"], "description": cfg.get("description", ""), "type": typ, "configuration": {"type": typ},
            "namespaces": list(cfg.get("namespaces") or cfg.get("namespaceTemplates") or [default_ns]),
            "namespaceTemplates": list(cfg.get("namespaceTemplates") or cfg.get("namespaces") or [default_ns]),
            "createdAt": now, "updatedAt": now, "status": "ACTIVE"}


def _create_memory(st, p):
    name = p.get("name")
    if not name or not _MEM_NAME.match(name):
        raise B._bad("1 validation error detected: Value at 'name' failed to satisfy constraint: Member must satisfy regular expression pattern: [a-zA-Z][a-zA-Z0-9_]{0,47}")
    exp = p.get("eventExpiryDuration")
    if not isinstance(exp, int) or not 3 <= exp <= 365:
        raise B._bad("1 validation error detected: Value at 'eventExpiryDuration' failed to satisfy constraint: Member must be between 3 and 365")
    if any(m["name"] == name for m in st["memories"].values()):
        raise B._conflict(f"Memory with name {name} already exists")
    mid = f"{name}-{B._rid(10, _LOWER)}"
    now = time.time()
    m = {"arn": f"arn:aws:bedrock-agentcore:{B._REGION}:{B._ACCT}:memory/{mid}", "id": mid, "name": name, "description": p.get("description", ""),
         "eventExpiryDuration": exp, "status": "CREATING", "createdAt": now, "updatedAt": now, "_readyAt": time.time() + 0.5,
         "strategies": [_mk_strategy(s) for s in p.get("memoryStrategies") or []], "events": [], "records": []}
    if p.get("memoryExecutionRoleArn"):
        m["memoryExecutionRoleArn"] = p["memoryExecutionRoleArn"]
    if p.get("encryptionKeyArn"):
        m["encryptionKeyArn"] = p["encryptionKeyArn"]
    st["memories"][mid] = m
    return B._j(202, {"memory": _mem_view(m)})


def find_memory(st, ident):
    m = st["memories"].get(ident) or next((x for x in st["memories"].values() if x["name"] == ident), None)
    if not m:
        raise B._nf(f"Memory {ident} not found")
    return m


def _ts(v):
    return float(v) if isinstance(v, (int, float)) else time.time()


def _event_view(e):
    return {k: v for k, v in e.items() if not k.startswith("_")}


def _fill(ns, actor, session, sid):
    return ns.replace("{actorId}", actor).replace("{sessionId}", session or "").replace("{memoryStrategyId}", sid)


def _convo_text(events):
    out = []
    for e in events:
        for it in e["payload"]:
            c = it.get("conversational")
            if c:
                out.append(f"{c['role'].lower()}: {(c.get('content') or {}).get('text', '')}")
    return "\n".join(out)


_FIRST_PERSON = re.compile(r"\b(i|i'm|i am|i'd|i've|my|me|we|our|prefer|always|never|favorite|favourite)\b", re.I)


def _extract(typ, text):
    """Long-term facts for one strategy: the local model when reachable, else a first-person-sentence heuristic."""
    if typ == "SUMMARIZATION":
        try:
            r = llm.chat([{"role": "user", "content": "Summarize this conversation in one or two sentences:\n" + text}], max_tokens=160, temperature=0.1)
            return [r["text"].strip()] if r["text"].strip() else []
        except llm.LlmUnavailable:
            return [text[-400:]]
    what = {"USER_PREFERENCE": "durable user preferences", "EPISODIC": "notable episodes/outcomes"}.get(typ, "durable facts about the user or domain")
    try:
        r = llm.chat([{"role": "user", "content": f"Extract {what} from the conversation below as a JSON array of short standalone strings "
                                                  f"(an empty array if none). Output only the JSON array.\n\n{text}"}], max_tokens=256, temperature=0.0)
        v, okj = llm.extract_json(r["text"])
        if okj and isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
    except (llm.LlmUnavailable, ValueError, TypeError):
        pass
    facts = []
    for line in text.split("\n"):
        if line.lower().startswith("user:"):
            for s in re.split(r"(?<=[.!?])\s+", line[5:].strip()):
                if s and _FIRST_PERSON.search(s):
                    facts.append(s)
    return facts


def _add_records(m, strat, actor, session, facts):
    for f in facts:
        for tmpl in strat["namespaceTemplates"]:
            ns = _fill(tmpl, actor, session, strat["strategyId"])
            if any(r["content"]["text"] == f and ns in r["namespaces"] for r in m["records"]):
                continue
            m["records"].append({"memoryRecordId": "mem-" + B._rid(36, _LOWER), "content": {"text": f}, "memoryStrategyId": strat["strategyId"],
                                 "namespaces": [ns], "createdAt": time.time(), "metadata": {}, "_vec": llm.embed(f)["vectors"][0]})


def _create_event(m, p):
    actor = p.get("actorId")
    if not actor:
        raise B._bad("actorId is required")
    pay = p.get("payload")
    if not isinstance(pay, list) or not pay:
        raise B._bad("payload must be a non-empty list")
    for it in pay:
        if "conversational" in it:
            c = it["conversational"]
            if c.get("role") not in ("ASSISTANT", "USER", "TOOL", "OTHER") or not isinstance(c.get("content"), dict):
                raise B._bad("conversational payload needs role and content.text")
        elif "blob" not in it:
            raise B._bad("payload items must be conversational or blob")
    session = p.get("sessionId") or "sess-" + B._rid(16, _LOWER)
    ev = {"memoryId": m["id"], "actorId": actor, "sessionId": session, "eventId": f"{int(time.time() * 1000):013d}#{B._rid(8, _LOWER)}",
          "eventTimestamp": _ts(p.get("eventTimestamp")), "payload": pay, "metadata": p.get("metadata") or {}}
    if p.get("branch"):
        ev["branch"] = p["branch"]
    m["events"].append(ev)
    if any(i.get("conversational") for i in pay):          # extraction runs inline (real service: async job)
        text = _convo_text([ev])
        for s in m["strategies"]:
            facts = _extract(s["type"], text)
            if facts:
                _add_records(m, s, actor, session, facts)
    return ev


def _rec_view(r, score=None):
    d = {k: v for k, v in r.items() if not k.startswith("_")}
    if score is not None:
        d["score"] = score
    return d


def _ns_ok(r, p):
    ns = p.get("namespacePath") or p.get("namespace")
    return not ns or any(n.startswith(ns) for n in r["namespaces"])


def retrieve(m, query, ns=None, top_k=5, strategy=None):
    qv = llm.embed(query)["vectors"][0]
    sc = [(llm.cosine(qv, r["_vec"]), r) for r in m["records"]
          if (not ns or any(n.startswith(ns) for n in r["namespaces"])) and (not strategy or r["memoryStrategyId"] == strategy)]
    sc.sort(key=lambda x: -x[0])
    return [_rec_view(r, round(s, 4)) for s, r in sc[:top_k]]


def _memory(st, method, segs, query, body):
    p = B._body(body) if method in ("PUT", "POST", "PATCH") else {}
    n = len(segs)
    if n == 1 and method == "POST":                                          # ListMemories (control)
        return B._j(200, _page([{"arn": m["arn"], "id": m["id"], "status": (_mready(m), m["status"])[1], "createdAt": m["createdAt"], "updatedAt": m["updatedAt"]}
                                for m in st["memories"].values()], query, "memories", p))
    if n == 2 and segs[1] == "create" and method == "POST":
        return _create_memory(st, p)
    if n < 3:
        return None
    m = find_memory(st, segs[1])
    _mready(m)
    t = segs[2]
    if t == "details" and method == "GET":
        return B._j(200, {"memory": _mem_view(m)})
    if t == "update" and method == "PUT":
        ms = p.get("memoryStrategies") or {}
        for s in ms.get("addMemoryStrategies") or []:
            m["strategies"].append(_mk_strategy(s))
        for d in ms.get("deleteMemoryStrategies") or []:
            m["strategies"] = [s for s in m["strategies"] if s["strategyId"] != d.get("memoryStrategyId")]
        for k in ("description", "eventExpiryDuration", "memoryExecutionRoleArn"):
            if k in p:
                m[k] = p[k]
        m["updatedAt"] = time.time()
        return B._j(202, {"memory": _mem_view(m)})
    if t == "delete" and method == "DELETE":
        del st["memories"][m["id"]]
        return B._j(202, {"memoryId": m["id"], "status": "DELETING"})
    # ── data plane ──
    if t == "events" and method == "POST":
        return B._j(201, {"event": _event_view(_create_event(m, p))})
    if t == "actors" and method == "POST":
        return B._j(200, _page([{"actorId": a} for a in sorted({e["actorId"] for e in m["events"]})], query, "actorSummaries", p))
    if t == "actor" and n >= 4:
        actor = segs[3]
        if n == 5 and segs[4] == "sessions" and method == "POST":
            ss = {}
            for e in m["events"]:
                if e["actorId"] == actor:
                    ss.setdefault(e["sessionId"], e["eventTimestamp"])
            return B._j(200, _page([{"sessionId": s, "actorId": actor, "createdAt": c} for s, c in ss.items()], query, "sessionSummaries", p))
        if n == 6 and segs[4] == "sessions" and method == "POST":           # ListEvents
            evs = [e for e in m["events"] if e["actorId"] == actor and e["sessionId"] == segs[5]]
            br = (p.get("filter") or {}).get("branch") or {}
            if br.get("name"):
                evs = [e for e in evs if (e.get("branch") or {}).get("name") == br["name"]]
            out = [_event_view(e) for e in evs]
            if p.get("includePayloads") is False:
                out = [dict(e, payload=[]) for e in out]
            return B._j(200, _page(out, query, "events", p))
        if n == 8 and segs[4] == "sessions" and segs[6] == "events":
            ev = next((e for e in m["events"] if e["eventId"] == segs[7] and e["actorId"] == actor and e["sessionId"] == segs[5]), None)
            if not ev:
                raise B._nf(f"Event {segs[7]} not found")
            if method == "GET":
                return B._j(200, {"event": _event_view(ev)})
            if method == "DELETE":
                m["events"].remove(ev)
                return B._j(200, {"eventId": ev["eventId"]})
    if t == "retrieve" and method == "POST":
        sc = p.get("searchCriteria") or {}
        if not sc.get("searchQuery"):
            raise B._bad("searchCriteria.searchQuery is required")
        if not (p.get("namespace") or p.get("namespacePath")):
            raise B._bad("namespace or namespacePath is required")
        top = int(sc.get("topK") or 10)
        res = retrieve(m, sc["searchQuery"], p.get("namespacePath") or p.get("namespace"), top, sc.get("memoryStrategyId"))
        return B._j(200, _page(res, query, "memoryRecordSummaries", p))
    if t == "memoryRecords":
        if n == 3 and method == "POST":
            return B._j(200, _page([_rec_view(r) for r in m["records"] if _ns_ok(r, p) and (not p.get("memoryStrategyId") or r["memoryStrategyId"] == p["memoryStrategyId"])],
                                   query, "memoryRecordSummaries", p))
        if n == 4 and segs[3] == "batchDelete" and method == "POST":
            ids = {r.get("memoryRecordId") for r in p.get("records") or []}
            m["records"] = [r for r in m["records"] if r["memoryRecordId"] not in ids]
            return B._j(200, {"successfulRecords": [{"memoryRecordId": i, "status": "SUCCEEDED"} for i in ids], "failedRecords": []})
        if n == 5 and method == "DELETE":
            rec = next((r for r in m["records"] if r["memoryRecordId"] == segs[4]), None)
            if not rec:
                raise B._nf(f"Memory record {segs[4]} not found")
            m["records"].remove(rec)
            return B._j(200, {"memoryRecordId": segs[4]})
    if t == "memoryRecord" and n == 4 and method == "GET":
        rec = next((r for r in m["records"] if r["memoryRecordId"] == segs[3]), None)
        if not rec:
            raise B._nf(f"Memory record {segs[3]} not found")
        return B._j(200, {"memoryRecord": _rec_view(rec)})
    return None


# ═════════════════════════════ Policy engines (Cedar) ═════════════════════════════
def _cedar_check(stmt):
    if cedarpy is None:
        return
    try:
        r = cedarpy.is_authorized({"principal": 'AgentCore::OAuthUser::"v"', "action": 'AgentCore::Action::"v"', "resource": 'AgentCore::Gateway::"v"', "context": {}}, stmt, [])
        if str(r.decision) == "Decision.NoDecision":
            raise ValueError("policy text does not parse")
    except Exception as e:
        raise B._Err("ValidationException", f"Invalid Cedar policy: {str(e)[:300]}", 400)


def _pe_view(e):
    return {k: v for k, v in e.items() if not k.startswith("_") and k != "policies"}


def _pol_view(x):
    return {k: v for k, v in x.items() if not k.startswith("_")}


def _policy_engines(st, method, segs, query, body):
    p = B._body(body) if method in ("PUT", "POST", "PATCH") else {}
    n = len(segs)
    if n == 1:
        if method == "POST":
            name = p.get("name")
            if not name or not re.match(r"^[A-Za-z][A-Za-z0-9_]{0,47}$", name):
                raise B._bad("1 validation error detected: Value at 'name' failed to satisfy constraint: Member must satisfy regular expression pattern: [A-Za-z][A-Za-z0-9_]{0,47}")
            if any(e["name"] == name for e in st["policy_engines"].values()):
                raise B._conflict(f"Policy engine {name} already exists")
            eid = f"{name}-{B._rid(10, _LOWER)}"
            now = time.time()
            e = {"policyEngineId": eid, "name": name, "description": p.get("description", ""), "createdAt": now, "updatedAt": now, "status": "ACTIVE",
                 "policyEngineArn": f"arn:aws:bedrock-agentcore:{B._REGION}:{B._ACCT}:policy-engine/{eid}", "statusReasons": [], "policies": {}}
            st["policy_engines"][eid] = e
            return B._j(202, _pe_view(e))
        if method == "GET":
            return B._j(200, _page([_pe_view(e) for e in st["policy_engines"].values()], query, "policyEngines"))
        return None
    e = st["policy_engines"].get(segs[1])
    if not e:
        raise B._nf(f"Policy engine {segs[1]} not found")
    if n == 2:
        if method == "GET":
            return B._j(200, _pe_view(e))
        if method == "DELETE":
            if e["policies"]:
                raise B._Err("ConflictException", "Policy engine has policies; delete them first", 409)
            del st["policy_engines"][e["policyEngineId"]]
            return B._j(202, dict(_pe_view(e), status="DELETING"))
        if method == "PATCH":
            if "description" in p:
                e["description"] = (p["description"] or {}).get("optionalValue", "") if isinstance(p["description"], dict) else p["description"]
            e["updatedAt"] = time.time()
            return B._j(202, _pe_view(e))
    if segs[2] == "policies":
        if n == 3:
            if method == "POST":
                name = p.get("name")
                stmt = ((p.get("definition") or {}).get("cedar") or {}).get("statement")
                if not name or not re.match(r"^[A-Za-z][A-Za-z0-9_]{0,47}$", name):
                    raise B._bad("name must match [A-Za-z][A-Za-z0-9_]{0,47}")
                if not stmt:
                    raise B._bad("definition.cedar.statement is required")
                if any(x["name"] == name for x in e["policies"].values()):
                    raise B._conflict(f"Policy {name} already exists")
                _cedar_check(stmt)
                pid = f"{name}-{B._rid(10, _LOWER)}"
                now = time.time()
                x = {"policyId": pid, "name": name, "policyEngineId": e["policyEngineId"], "createdAt": now, "updatedAt": now, "status": "ACTIVE", "statusReasons": [],
                     "policyArn": f"{e['policyEngineArn']}/policy/{pid}", "definition": {"cedar": {"statement": stmt}}, "description": p.get("description", "")}
                e["policies"][pid] = x
                return B._j(202, _pol_view(x))
            if method == "GET":
                return B._j(200, _page([_pol_view(x) for x in e["policies"].values()], query, "policies"))
        elif n == 4:
            x = e["policies"].get(segs[3])
            if not x:
                raise B._nf(f"Policy {segs[3]} not found")
            if method == "GET":
                return B._j(200, _pol_view(x))
            if method == "DELETE":
                del e["policies"][x["policyId"]]
                return B._j(202, dict(_pol_view(x), status="DELETING"))
            if method == "PATCH":
                stmt = ((p.get("definition") or {}).get("cedar") or {}).get("statement")
                if stmt:
                    _cedar_check(stmt)
                    x["definition"] = {"cedar": {"statement": stmt}}
                if "description" in p:
                    x["description"] = (p["description"] or {}).get("optionalValue", "")
                x["updatedAt"] = time.time()
                return B._j(202, _pol_view(x))
    return None


# ═════════════════════════════ Gateway: identity, policy, semantic search ═════════════════════════════
def jwt_claims(headers):
    """Decoded (NOT verified) claims of the Bearer token, {} when there is none."""
    h = {str(k).lower(): v for k, v in (headers or {}).items()}
    a = next((v.strip()[7:].strip() for v in (h.get("authorization") or "", h.get("x-amzn-bedrock-agentcore-runtime-custom-authorization") or "")
              if v.strip().lower().startswith("bearer ")), "")
    parts = a.split(".")
    if len(parts) != 3:
        return {}
    try:
        seg = parts[1] + "=" * (-len(parts[1]) % 4)
        c = json.loads(base64.urlsafe_b64decode(seg))
        return c if isinstance(c, dict) else {}
    except (ValueError, TypeError):
        return {}


def _tags(claims):
    out = {}
    for k, v in claims.items():
        if isinstance(v, (list, tuple)):
            out[k] = ",".join(str(x) for x in v)
        elif isinstance(v, (str, int, float, bool)):
            out[k] = str(v)
    return out


def authorize(st, gw, claims, tool, args, probe=False):
    """Central allow/deny for one gateway tool call -> (allowed, reason). No engine attached = allow."""
    _x(st)
    cfg = gw.get("policyEngineConfiguration") or {}
    arn = cfg.get("arn")
    if not arn:
        return True, "no-policy-engine"
    mode = cfg.get("mode", "ENFORCE")
    eng = next((e for e in st["policy_engines"].values() if e["policyEngineArn"] == arn), None)
    principal = str(claims.get("sub") or claims.get("username") or "anonymous")
    if not eng:
        ok, why = (mode != "ENFORCE"), "policy engine not found"
    elif cedarpy is None:
        ok, why = (mode != "ENFORCE"), "cedar engine unavailable on this substrate (fail closed)"
    else:
        pols = "\n".join(x["definition"]["cedar"]["statement"] for x in eng["policies"].values())
        ents = [{"uid": {"type": "AgentCore::OAuthUser", "id": principal}, "attrs": {}, "parents": [], "tags": _tags(claims)}]
        try:
            r = cedarpy.is_authorized({"principal": f'AgentCore::OAuthUser::"{principal}"', "action": f'AgentCore::Action::"{tool}"',
                                       "resource": f'AgentCore::Gateway::"{gw["gatewayArn"]}"', "context": {"input": args or {}}}, pols, ents)
            allowed = str(r.decision) == "Decision.Allow"
            ok = allowed or mode != "ENFORCE"
            why = "explicit-permit" if allowed else "denied by default: no policy permits the request"
        except Exception as ex:
            ok, why = (mode != "ENFORCE"), f"cedar-error: {str(ex)[:200]}"
    if probe:
        return ok, why
    st["policy_audit"].append({"time": time.time(), "gatewayId": gw["gatewayId"], "principal": principal, "tool": tool, "allowed": ok, "mode": mode, "reason": why})
    del st["policy_audit"][:-500]
    return ok, why


SEARCH_TOOL = "x_amz_bedrock_agentcore_search"


def search_tools(entries, query, top_k=5):
    """entries: [(fullName, description, inputSchema)] -> ranked by embedding similarity."""
    qv = llm.embed(query)["vectors"][0]
    vecs = llm.embed([f"{n.replace('___', ' ').replace('_', ' ')}. {d}" for n, d, _ in entries])["vectors"] if entries else []
    ranked = sorted(zip(entries, vecs), key=lambda x: -llm.cosine(qv, x[1]))
    return [{"name": n, "description": d, "inputSchema": s} for (n, d, s), _ in ranked[:top_k]]


def search_tool_def():
    return {"name": SEARCH_TOOL, "description": "A special tool that returns a trimmed down list of tools given a context. Use this tool only when there are many tools to choose from.",
            "inputSchema": {"type": "object", "properties": {"query": {"type": "string", "description": "A natural language query to search the tools."}}, "required": ["query"]}}


# ═════════════════════════════ Runtime tool kinds ═════════════════════════════
_CTX: contextvars.ContextVar = contextvars.ContextVar("agentcore_ctx", default=None)


def _spec_of_runtime(st, ref):
    rt = st["runtimes"].get(ref) or next((r for r in st["runtimes"].values() if r["agentRuntimeName"] == ref), None)
    if not rt:
        raise ValueError(f"unknown runtime {ref}")
    raw = (rt.get("environmentVariables") or {}).get("VYOMI_AGENT_SPEC")
    if not raw:
        raise ValueError(f"runtime {ref} has no agent spec")
    return ag.parse_spec(raw)


def _k_agent(tool, args):
    c = _CTX.get()
    if not c or c["depth"] >= 4:
        return {"error": "sub-agent depth limit or no runtime context"}, True
    spec = tool.get("spec") or _spec_of_runtime(c["st"], tool["runtime"])
    q = args.get("query") or args.get("prompt") or args.get("input") or json.dumps(args)
    tok = _CTX.set(dict(c, depth=c["depth"] + 1))
    try:
        r = ag.run(spec, str(q))
    finally:
        _CTX.reset(tok)
    return {"agent": tool["name"], "answer": r["text"], "toolCalls": [s["name"] for s in r["steps"] if s["type"] == "tool_result"]}, False


def _k_gateway(tool, args):
    c = _CTX.get()
    if not c:
        return {"error": "no runtime context"}, True
    gw = next((g for g in c["st"]["gateways"].values() if tool["gateway"] in (g["gatewayId"], g["name"])), None)
    if not gw:
        return {"error": f"gateway {tool['gateway']} not found"}, True
    r = B._mcp(c["st"], c["lam"], gw["gatewayId"], {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool["tool"], "arguments": args}},
               {"authorization": "Bearer " + c["jwt"]} if c.get("jwt") else {"authorization": "none"}, internal=True)
    d = json.loads(r["body"] or b"{}")
    if "error" in d:
        return {"error": d["error"]["message"]}, True
    res = d.get("result") or {}
    txt = "".join(x.get("text", "") for x in res.get("content") or [])
    try:
        return json.loads(txt), bool(res.get("isError"))
    except ValueError:
        return txt, bool(res.get("isError"))


def _k_memory(tool, args):
    c = _CTX.get()
    if not c:
        return {"error": "no runtime context"}, True
    m = find_memory(c["st"], tool["memory"])
    ns = (tool.get("namespace") or "/").replace("{actorId}", c.get("actor", "anonymous"))
    return retrieve(m, str(args.get("query", "")), ns, int(tool.get("topK", 5))), False


def install():
    for kind, fn in (("agent", _k_agent), ("gateway", _k_gateway), ("memory", _k_memory)):
        ag.register_kind(kind, fn)


install()


def run_context(st, lam, jwt, actor, fn):
    tok = _CTX.set({"st": st, "lam": lam, "jwt": jwt, "actor": actor, "depth": 0})
    try:
        return fn()
    finally:
        _CTX.reset(tok)


def memory_hooks(st, spec, actor, session, text):
    """Runtime memory integration: returns (augmented message, after(reply) writer) for spec['memory'] = {"memory": name, "namespace": ...}."""
    cfg = spec.get("memory")
    if not cfg:
        return text, lambda reply: None
    m = find_memory(st, cfg["memory"] if isinstance(cfg, dict) else cfg)
    ns = (cfg.get("namespace") if isinstance(cfg, dict) else None) or "/"
    ns = ns.replace("{actorId}", actor)
    recs = retrieve(m, text, ns, int(cfg.get("topK", 5)) if isinstance(cfg, dict) else 5)
    aug = text
    if recs:
        aug = "Known about this user from long-term memory:\n" + "\n".join("- " + r["content"]["text"] for r in recs) + "\n\nUser request: " + text

    def after(reply):
        _create_event(m, {"actorId": actor, "sessionId": session, "eventTimestamp": time.time(),
                          "payload": [{"conversational": {"role": "USER", "content": {"text": text}}},
                                      {"conversational": {"role": "ASSISTANT", "content": {"text": reply}}}]})
    return aug, after


# ═════════════════════════════ dispatch hook ═════════════════════════════
def dispatch(st, lam, method, segs, query, headers, body):
    """Returns a response dict for the extension routes, or None when the path is not ours."""
    _x(st)
    try:
        if segs[0] == "memories":
            return _memory(st, method, segs, query, body)
        if segs[0] == "policy-engines":
            return _policy_engines(st, method, segs, query, body)
    except B._Err as e:
        return B._err_resp(e)
    return None
