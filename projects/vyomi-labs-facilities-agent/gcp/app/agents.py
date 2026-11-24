import json
import re
import time
from typing import TypedDict

from langgraph.graph import END, StateGraph

import models
import starter_tools as tools

ROUTER_PROMPT = (
    "You route facilities requests to specialist agents. The agents are:\n"
    "- facilities: searches the knowledge base (SOPs, safety rules, policies, procedures). Use it for ANY question about what the procedure, rule, limit or policy is.\n"
    "- maintenance: looks up a specific asset (ids like B-12 or AHU-7) and its work orders, and can raise a work order.\n"
    "- analytics: counts and statistics over work orders (how many, trends, summaries).\n"
    "Pick every agent needed. Reply with only a JSON list such as [\"facilities\",\"maintenance\"], drawn from [\"facilities\",\"maintenance\",\"analytics\"]."
)
ANALYTICS_ONLY = re.compile(r"^\s*(how many|count|give me a summary|summary of|report|trend)", re.I)


class State(TypedDict, total=False):
    question: str
    user: str
    route: list
    facts: list
    citations: list
    answer: str
    llm_used: bool
    tools: list
    spans: list


def build():
    def span(st, name, kind, t0):
        st.setdefault("spans", []).append(dict(name=name, kind=kind, start=t0, end=time.time()))

    def supervisor(st):
        t0 = time.time()
        plan = None
        try:
            txt = models.chat(st["question"], system=ROUTER_PROMPT, max_tokens=60)
            plan = [p for p in json.loads(re.search(r"\[.*\]", txt, re.S).group(0)) if p in ("facilities", "maintenance", "analytics")]
        except Exception:
            plan = None
        st["llm_used"] = bool(plan)
        if plan and "facilities" not in plan and not ANALYTICS_ONLY.search(st["question"].lower()):
            plan.insert(0, "facilities")          # grounding rule: every question except pure statistics is answered from the knowledge base
        if not plan:
            plan = ["facilities"]
            if re.search(r"[A-Z]{1,3}-\d+|work order|status|ticket|asset", st["question"]):
                plan.append("maintenance")
            if re.search(r"how many|count|summary|report|trend|open work orders", st["question"].lower()):
                plan.append("analytics")
        st["route"] = plan
        span(st, "supervisor.plan", "agent", t0)
        return st

    def facilities(st):
        t0 = time.time()
        hits = tools.kb_search(st["question"], 3)
        st["citations"] = [{"n": i + 1, "source": h["source"], "text": h["text"]} for i, h in enumerate(hits)]
        st["tools"].append({"tool": "kb_search", "via": "in-package"})
        span(st, "agent:facilities", "agent", t0)
        return st

    def maintenance(st):
        t0 = time.time()
        m = re.search(r"\b([A-Z]{1,3}-\d+)\b", st["question"])
        if m:
            out = tools.asset_status(m.group(1))
            st["tools"].append({"tool": "asset_status", "via": "in-package"})
            if out["found"]:
                open_wos = [w["work_order_id"] + " " + w["title"] for w in out["work_orders"] if w["status"] == "OPEN"]
                st.setdefault("facts", []).append(f"Asset {m.group(1)} status {out['asset']['status']}; open work orders: {open_wos or 'none'}.")
                if re.search(r"work order|raise|open a|create", st["question"], re.I):
                    st["facts"].append("Raising a work order is a write action: it needs a human approval first (chapter 5), so nothing was written.")
        span(st, "agent:maintenance", "agent", t0)
        return st

    def analytics(st):
        t0 = time.time()
        stats = tools.work_order_stats()
        st.setdefault("facts", []).append(f"Work orders: {stats['total']} total; by status and priority {json.dumps(stats['by_status_priority'])}.")
        st["tools"].append({"tool": "work_order_stats", "via": "in-package"})
        span(st, "agent:analytics", "agent", t0)
        return st

    def synthesize(st):
        t0 = time.time()
        context = "\n".join(f"[{c['n']}] {c['text']}" for c in st.get("citations", [])) + "\n" + "\n".join(st.get("facts", []))
        st["answer"] = models.chat(f"Context:\n{context}\n\nQuestion: {st['question']}", system="Answer using only the context. Cite sources like [1].", max_tokens=300)
        span(st, "supervisor.synthesize", "agent", t0)
        return st

    g = StateGraph(State)
    for name, fn in (("supervisor", supervisor), ("facilities", facilities), ("maintenance", maintenance), ("analytics", analytics), ("synth", synthesize)):
        g.add_node(name, fn)
    g.set_entry_point("supervisor")
    order = ["facilities", "maintenance", "analytics"]

    def after(prev):
        def pick(st):
            rest = [a for a in order[order.index(prev) + 1:] if a in st["route"]] if prev else [a for a in order if a in st["route"]]
            return rest[0] if rest else "synth"
        return pick
    for src, prev in (("supervisor", None), ("facilities", "facilities"), ("maintenance", "maintenance"), ("analytics", "analytics")):
        g.add_conditional_edges(src, after(prev), {"facilities": "facilities", "maintenance": "maintenance", "analytics": "analytics", "synth": "synth"})
    g.add_edge("synth", END)
    return g.compile()


def ask(question, user="anonymous"):
    return build().invoke({"question": question, "user": user, "tools": [], "spans": [], "facts": []})
