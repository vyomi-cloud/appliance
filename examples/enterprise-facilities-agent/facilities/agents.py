"""Supervisor + three sub-agents (Facilities, Maintenance, Analytics) as a LangGraph StateGraph.
Tools are plain boto3-backed functions. The model is called through Bedrock Converse; when no model is reachable the
supervisor routes with keyword rules and the final answer is extractive, and the result says so (llm_used=False)."""
import json, re, time, uuid
from typing import TypedDict
from langgraph.graph import StateGraph, END
from .runtime import NAMES, aws_json

MODEL_ID = "anthropic.claude-3-haiku-20240307-v1:0"


class S(TypedDict, total=False):
    question: str
    user: str
    route: list
    facts: list
    citations: list
    analytics: dict
    approval: dict
    answer: str
    llm_used: bool
    tools: list
    spans: list


def converse(ctx, system, text, max_tokens=300):
    """Returns the model text or None when no model is reachable (ModelNotReady / unsupported)."""
    try:
        r = ctx.client("bedrock-runtime").converse(
            modelId=MODEL_ID, system=[{"text": system}], messages=[{"role": "user", "content": [{"text": text}]}],
            inferenceConfig={"maxTokens": max_tokens, "temperature": 0})
        return r["output"]["message"]["content"][0]["text"]
    except Exception as e:
        ctx.state["llm_error"] = f"{type(e).__name__}: {str(e)[:120]}"
        return None


def call_tool(ctx, tool, args, st):
    """Tool call. Through AgentCore Gateway (MCP) when the gateway serves it, otherwise a direct Lambda invoke."""
    t0 = time.time()
    lam_name = {"kb_search": "facilities-kb-search", "asset_status": "facilities-asset-status"}[tool]
    path = "lambda-direct"
    if ctx.state.get("gateway_tools_ok"):
        from . import mcp
        names = [n for n in ctx.state["mcp_tools"] if tool in n]
        res = mcp.call(ctx, ctx.state["gateway_id"], "tools/call", {"name": names[0], "arguments": args})
        out = json.loads(res["content"][0]["text"]) if res.get("content") else res
        path = "agentcore-gateway"
    else:
        r = ctx.client("lambda").invoke(FunctionName=lam_name, Payload=json.dumps(args).encode())
        out = json.loads(r["Payload"].read())
    st.setdefault("tools", []).append({"tool": tool, "via": path, "args": args})
    st.setdefault("spans", []).append(dict(name=f"tool:{tool}", kind="tool", start=t0, end=time.time(), via=path))
    return out


def build(ctx):
    def span(st, name, kind, t0):
        st.setdefault("spans", []).append(dict(name=name, kind=kind, start=t0, end=time.time()))

    def supervisor(st):
        t0 = time.time()
        q = st["question"].lower()
        plan = None
        txt = converse(ctx, "You route facilities requests. Reply with only a JSON list drawn from [\"facilities\",\"maintenance\",\"analytics\"].", st["question"], 40)
        if txt:
            try:
                plan = [p for p in json.loads(re.search(r"\[.*\]", txt, re.S).group(0)) if p in ("facilities", "maintenance", "analytics")]
            except Exception:
                plan = None
        st["llm_used"] = bool(plan)
        if not plan:
            plan = ["facilities"]
            if re.search(r"[A-Z]{1,3}-\d+|work order|status|ticket|asset", st["question"]):
                plan.append("maintenance")
            if re.search(r"how many|count|summary|report|trend|open work orders", q):
                plan.append("analytics")
        st["route"] = plan
        span(st, "supervisor.plan", "agent", t0)
        return st

    def facilities(st):
        t0 = time.time()
        out = call_tool(ctx, "kb_search", {"query": st["question"], "top_k": 3}, st)
        st["facts"] = [r["text"] for r in out["results"]]
        st["citations"] = [{"n": i + 1, "source": r["source"], "text": r["text"][:160]} for i, r in enumerate(out["results"])]
        span(st, "agent:facilities", "agent", t0)
        return st

    def maintenance(st):
        t0 = time.time()
        m = re.search(r"\b([A-Z]{1,3}-\d+)\b", st["question"])
        if m:
            out = call_tool(ctx, "asset_status", {"asset_id": m.group(1)}, st)
            if out.get("found"):
                st.setdefault("facts", []).append(f"Asset {m.group(1)} status {out['asset'].get('status')}; open work orders: "
                                                  f"{[w['work_order_id'] + ' ' + w['title'] for w in out['work_orders'] if w.get('status') == 'OPEN'] or 'none'}.")
                if re.search(r"work order|raise|open a|create", st["question"], re.I):      # write path: Step Functions human approval
                    rid = "req-" + uuid.uuid4().hex[:10]
                    ex = ctx.client("stepfunctions").start_execution(
                        stateMachineArn=ctx.state["sm_arn"], name=rid,
                        input=json.dumps({"request_id": rid, "asset_id": m.group(1), "summary": f"Work order for {m.group(1)}: " + st["question"][:100],
                                          "priority": "P1" if re.search(r"exceed|pressure|fire|trapped", st["question"], re.I) else "P2", "requester": st.get("user", "")}))
                    st["approval"] = {"request_id": rid, "execution_arn": ex["executionArn"], "status": "PENDING_APPROVAL"}
                    st["tools"].append({"tool": "create_work_order", "via": "step-functions-approval", "args": {"request_id": rid}})
        span(st, "agent:maintenance", "agent", t0)
        return st

    def analytics(st):
        t0 = time.time()
        items = [aws_json(i) for i in ctx.client("dynamodb").scan(TableName=NAMES["work_orders"])["Items"]]
        by = {}
        for w in items:
            by.setdefault(w["status"], {}).setdefault(w["priority"], 0)
            by[w["status"]][w["priority"]] += 1
        st["analytics"] = {"total": len(items), "by_status_priority": by}
        st.setdefault("facts", []).append(f"Work orders: {len(items)} total; by status/priority {json.dumps(by)}.")
        st.setdefault("tools", []).append({"tool": "work_order_stats", "via": "dynamodb", "args": {}})
        span(st, "agent:analytics", "agent", t0)
        return st

    def synth(st):
        t0 = time.time()
        ctxt = "\n".join(f"[{c['n']}] {c['text']}" for c in st.get("citations", [])) + "\n" + "\n".join(st.get("facts", [])[len(st.get("citations", [])):])
        txt = converse(ctx, "Answer using only the context. Cite sources like [1].", f"Context:\n{ctxt}\n\nQuestion: {st['question']}", 300)
        if txt:
            st["answer"] = txt
        else:
            lead = st["citations"][0] if st.get("citations") else None
            parts = ([f"{lead['text'].split(chr(10))[0].lstrip('# ').strip()}: {' '.join(lead['text'].split(chr(10))[1:]).strip()} [1]"] if lead else [])
            parts += st.get("facts", [])[len(st.get("citations", [])):]
            if st.get("approval"):
                parts.append(f"A work order request ({st['approval']['request_id']}) was submitted and is waiting for approval.")
            st["answer"] = " ".join(parts)
        span(st, "supervisor.synthesize", "agent", t0)
        return st

    g = StateGraph(S)
    for n, f in [("supervisor", supervisor), ("facilities", facilities), ("maintenance", maintenance), ("analytics", analytics), ("synth", synth)]:
        g.add_node(n, f)
    g.set_entry_point("supervisor")

    def nxt(after):
        order = ["facilities", "maintenance", "analytics"]
        def r(st):
            rest = [a for a in order[order.index(after) + 1:] if a in st["route"]] if after else [a for a in order if a in st["route"]]
            return rest[0] if rest else "synth"
        return r
    for n in (None, "facilities", "maintenance", "analytics"):
        src = n or "supervisor"
        g.add_conditional_edges(src, nxt(n), {"facilities": "facilities", "maintenance": "maintenance", "analytics": "analytics", "synth": "synth"})
    g.add_edge("synth", END)
    return g.compile()


def ask(ctx, question, user):
    return build(ctx).invoke({"question": question, "user": user, "tools": [], "spans": []})
