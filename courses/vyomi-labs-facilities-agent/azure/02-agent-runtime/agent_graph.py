import json
import re
import time
from typing import TypedDict
from langgraph.graph import StateGraph, END

ROUTER_PROMPT = (
    "You route facilities requests to specialist agents. The agents are:\n"
    "- facilities: searches the knowledge base (SOPs, safety rules, policies, maintenance procedures, how-to guidance).\n"
    "- maintenance: looks up a specific asset (ids like B-12 or AHU-7) and its work orders, and can raise a work order.\n"
    "- analytics: counts and statistics over work orders (how many, trends, summaries).\n"
    "Pick every agent needed. Reply with only a JSON list such as [\"facilities\",\"maintenance\"], drawn from [\"facilities\",\"maintenance\",\"analytics\"]."
)
ROLES = {"facilities": "You are the Facilities agent. Answer procedure and safety questions.",
         "maintenance": "You are the Maintenance agent. Answer questions about assets and work orders.",
         "analytics": "You are the Analytics agent. Answer questions that need counts or summaries."}


class State(TypedDict, total=False):
    question: str
    user: str
    route: list
    notes: dict
    citations: list
    approval: str
    answer: str
    llm_used: bool
    spans: list


def build(converse, tools=None):
    """converse(system, text) -> str. tools: optional {name: callable}; sub-agents use a tool when one is supplied (chapters 7 and 4 supply them)."""
    tools = tools or {}

    def span(st, name, t0):
        st.setdefault("spans", []).append({"name": name, "kind": "agent", "start": t0, "end": time.time()})

    def supervisor(st):
        t0 = time.time()
        plan = None
        text = converse(ROUTER_PROMPT, st["question"])
        try:
            plan = [p for p in json.loads(re.search(r"\[.*\]", text, re.S).group(0)) if p in ROLES]
        except Exception:
            plan = None
        st["llm_used"] = bool(plan)
        st["route"] = plan or ["facilities"]
        st["notes"] = {}
        span(st, "supervisor.plan", t0)
        return st

    def sub_agent(name):
        def node(st):
            t0 = time.time()
            if name in tools:
                st["notes"][name] = tools[name](st)
            else:
                st["notes"][name] = converse(ROLES[name], st["question"])
            span(st, f"agent:{name}", t0)
            return st
        return node

    def synthesize(st):
        t0 = time.time()
        context = "\n".join(f"[{i + 1}] {n}" for i, n in enumerate(st["notes"].values()))
        st["answer"] = converse("Answer using only the context. Cite sources like [1].", f"Context:\n{context}\n\nQuestion: {st['question']}")
        span(st, "supervisor.synthesize", t0)
        return st

    g = StateGraph(State)
    g.add_node("supervisor", supervisor)
    for n in ROLES:
        g.add_node(n, sub_agent(n))
    g.add_node("synth", synthesize)
    g.set_entry_point("supervisor")
    order = list(ROLES)

    def next_after(after):
        def pick(st):
            rest = [a for a in (order[order.index(after) + 1:] if after else order) if a in st["route"]]
            return rest[0] if rest else "synth"
        return pick
    targets = {**{n: n for n in order}, "synth": "synth"}
    for src in ["supervisor"] + order:
        g.add_conditional_edges(src, next_after(None if src == "supervisor" else src), targets)
    g.add_edge("synth", END)
    return g.compile()
