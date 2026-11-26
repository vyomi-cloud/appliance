import json
import re
import time
import uuid
from typing import TypedDict

import boto3
from langgraph.graph import END, StateGraph

import mcp_client

from models import CHAT_MODEL as MODEL_ID
LAMBDAS = {"kb_search": "facilities-kb-search", "asset_status": "facilities-asset-status"}
GATEWAY = {}


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


def converse(system, text, max_tokens=300):
    try:
        r = boto3.client("bedrock-runtime").converse(modelId=MODEL_ID, system=[{"text": system}],
                                                     messages=[{"role": "user", "content": [{"text": text}]}],
                                                     inferenceConfig={"maxTokens": max_tokens, "temperature": 0})
        return r["output"]["message"]["content"][0]["text"]
    except Exception:
        return None


def discover_gateway():
    """Use the AgentCore Gateway when it exists and serves both tools."""
    GATEWAY.clear()
    try:
        gws = boto3.client("bedrock-agentcore-control").list_gateways()["items"]
        gw = next(g for g in gws if g["name"] == "facilities-gateway")
        names = {t["name"] for t in mcp_client.call(gw["gatewayId"], "tools/list")["tools"]}
        if any("kb_search" in n for n in names) and any("asset_status" in n for n in names):
            GATEWAY.update(id=gw["gatewayId"], tools=names)
    except Exception:
        pass


def call_tool(tool, args, st):
    t0 = time.time()
    try:
        if GATEWAY:
            name = [n for n in GATEWAY["tools"] if tool in n][0]
            res = mcp_client.call(GATEWAY["id"], "tools/call", {"name": name, "arguments": args})
            out, via = (json.loads(res["content"][0]["text"]) if res.get("content") else res), "agentcore-gateway"
        else:
            r = boto3.client("lambda").invoke(FunctionName=LAMBDAS[tool], Payload=json.dumps(args).encode())
            out, via = json.loads(r["Payload"].read() or b"null"), "lambda-direct"
            if "FunctionError" in r:
                raise RuntimeError(str(out)[:120])
    except Exception as e:
        out, via = {"error": type(e).__name__ + ": " + str(e)[:100]}, "unavailable"
    st.setdefault("tools", []).append({"tool": tool, "via": via, "args": args})
    st.setdefault("spans", []).append(dict(name="tool:" + tool, kind="tool", start=t0, end=time.time(), via=via))
    return out


def start_approval(rid, payload):
    sf = boto3.client("stepfunctions")
    try:
        sm = next(m for m in sf.list_state_machines()["stateMachines"] if m["name"] == "work-order-approval")
        ex = sf.start_execution(stateMachineArn=sm["stateMachineArn"], name=rid, input=json.dumps(payload))
        return {"request_id": rid, "execution_arn": ex["executionArn"], "status": "PENDING_APPROVAL"}
    except Exception as e:
        return {"request_id": rid, "status": "APPROVAL_UNAVAILABLE", "error": type(e).__name__}


ROUTER_PROMPT = (
    "You route facilities requests to specialist agents. The agents are:\n"
    "- facilities: searches the knowledge base (SOPs, safety rules, policies, procedures).\n"
    "- maintenance: looks up a specific asset (ids like B-12 or AHU-7) and its work orders, and can raise a work order.\n"
    "- analytics: counts and statistics over work orders.\n"
    "Reply with only a JSON list such as [\"facilities\",\"maintenance\"], drawn from [\"facilities\",\"maintenance\",\"analytics\"].")
ANALYTICS_ONLY = re.compile(r"^\s*(how many|count|give me a summary|summary of|report|trend)", re.I)


def build():
    def span(st, name, t0):
        st.setdefault("spans", []).append(dict(name=name, kind="agent", start=t0, end=time.time()))

    def supervisor(st):
        t0 = time.time()
        plan, txt = None, converse(ROUTER_PROMPT, st["question"], 60)
        if txt:
            try:
                plan = [p for p in json.loads(re.search(r"\[.*\]", txt, re.S).group(0)) if p in ("facilities", "maintenance", "analytics")]
            except Exception:
                plan = None
        st["llm_used"] = bool(plan)
        if plan and "facilities" not in plan and not ANALYTICS_ONLY.search(st["question"]):
            plan.insert(0, "facilities")      # grounding rule: every non-statistics question is answered from the knowledge base
        if not plan:                          # no model reachable: keyword routing
            plan = ["facilities"]
            if re.search(r"[A-Z]{1,3}-\d+|work order|status|ticket|asset", st["question"]):
                plan.append("maintenance")
            if re.search(r"how many|count|summary|report|trend|open work orders", st["question"].lower()):
                plan.append("analytics")
        st["route"] = plan
        span(st, "supervisor.plan", t0)
        return st

    def facilities(st):
        t0 = time.time()
        out = call_tool("kb_search", {"query": st["question"]}, st)      # how many passages comes from your design, inside the tool
        results = out.get("results", [])
        st["facts"] = [r["text"] for r in results]
        st["citations"] = [{"n": i + 1, "source": r["source"], "text": r["text"][:160], "score": r.get("score")} for i, r in enumerate(results)]
        span(st, "agent:facilities", t0)
        return st

    def maintenance(st):
        t0 = time.time()
        m = re.search(r"\b([A-Z]{1,3}-\d+)\b", st["question"])
        if m:
            out = call_tool("asset_status", {"asset_id": m.group(1)}, st)
            if out.get("found"):
                open_wos = [w["work_order_id"] + " " + w["title"] for w in out["work_orders"] if w.get("status") == "OPEN"]
                st.setdefault("facts", []).append("Asset %s status %s; open work orders: %s." % (m.group(1), out["asset"].get("status"), open_wos or "none"))
                if re.search(r"work order|raise|open a|create", st["question"], re.I):      # write path: human approval first
                    rid = "req-" + uuid.uuid4().hex[:10]
                    st["approval"] = start_approval(rid, {
                        "request_id": rid, "asset_id": m.group(1), "summary": "Work order for %s: %s" % (m.group(1), st["question"][:100]),
                        "priority": "P1" if re.search(r"exceed|pressure|fire|trapped", st["question"], re.I) else "P2", "requester": st.get("user", "")})
                    st["tools"].append({"tool": "create_work_order", "via": "step-functions-approval", "args": {"request_id": rid}})
        span(st, "agent:maintenance", t0)
        return st

    def analytics(st):
        t0 = time.time()
        try:
            items = boto3.client("dynamodb").scan(TableName="facilities-work-orders")["Items"]
            rows = [{k: list(v.values())[0] for k, v in i.items()} for i in items]
        except Exception:
            rows = None
        if rows is None:
            st["analytics"] = {"error": "work-order table not available yet"}
        else:
            by = {}
            for w in rows:
                by.setdefault(w["status"], {}).setdefault(w["priority"], 0)
                by[w["status"]][w["priority"]] += 1
            st["analytics"] = {"total": len(rows), "by_status_priority": by}
            st.setdefault("facts", []).append("Work orders: %d total; by status/priority %s." % (len(rows), json.dumps(by)))
        st.setdefault("tools", []).append({"tool": "work_order_stats", "via": "dynamodb" if rows is not None else "unavailable", "args": {}})
        span(st, "agent:analytics", t0)
        return st

    def synth(st):
        t0 = time.time()
        cites = st.get("citations", [])
        ctxt = "\n".join("[%d] %s" % (c["n"], c["text"]) for c in cites) + "\n" + "\n".join(st.get("facts", [])[len(cites):])
        txt = converse("Answer using only the context. Cite sources like [1].", "Context:\n%s\n\nQuestion: %s" % (ctxt, st["question"]), 300)
        if txt:
            st["answer"] = txt
        else:
            parts = []
            if cites:
                first = cites[0]["text"].split("\n")
                parts.append("%s: %s [1]" % (first[0].lstrip("# ").strip(), " ".join(first[1:]).strip()))
            parts += st.get("facts", [])[len(cites):]
            if st.get("approval", {}).get("status") == "PENDING_APPROVAL":
                parts.append("A work order request (%s) was submitted and is waiting for approval." % st["approval"]["request_id"])
            st["answer"] = " ".join(parts) or "I could not reach my tools yet, so I have nothing grounded to answer with."
        span(st, "supervisor.synthesize", t0)
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
        g.add_conditional_edges(n or "supervisor", nxt(n), {"facilities": "facilities", "maintenance": "maintenance", "analytics": "analytics", "synth": "synth"})
    g.add_edge("synth", END)
    return g.compile()


def ask(question, user="anonymous"):
    discover_gateway()
    return build().invoke({"question": question, "user": user, "tools": [], "spans": []})
