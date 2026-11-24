import os
import re
import time
import uuid
os.environ.setdefault("VYOMI_ENDPOINT", os.environ["VYOMI_AZURE_HTTP_ENDPOINT"])
import agent_graph
from app import converse
from approval import request_approval, work_orders
from azdata import call_function, FUNCTION_APP


def _tool_span(st, name, t0):
    st["spans"].append({"name": f"tool:{name}", "kind": "tool", "start": t0, "end": time.time()})


def facilities(st):
    t0 = time.time()
    out = call_function(FUNCTION_APP, "kb-search", {"query": st["question"], "top_k": 3})
    _tool_span(st, "kb_search", t0)
    st["citations"] = [{"n": i + 1, "source": r["source"], "text": r["text"]} for i, r in enumerate(out["results"])]
    return "\n".join(f"[{c['n']}] {c['text']}" for c in st["citations"])


def maintenance(st):
    t0 = time.time()
    m = re.search(r"\b([A-Z]{1,3}-\d+)\b", st["question"])
    if not m:
        return "No asset id in the question."
    out = call_function(FUNCTION_APP, "asset-status", {"asset_id": m.group(1)})
    _tool_span(st, "asset_status", t0)
    note = f"Asset {m.group(1)} status {out['asset']['status']}; open work orders: {[w['work_order_id'] for w in out['work_orders'] if w['status'] == 'OPEN']}."
    if re.search(r"work order|raise|create", st["question"], re.I):
        rid = "req-" + uuid.uuid4().hex[:10]
        t1 = time.time()
        request_approval(rid, m.group(1), f"Work order for {m.group(1)}: " + st["question"][:100], "P1" if re.search(r"exceed|pressure|fire", st["question"], re.I) else "P2", st.get("user", ""))
        _tool_span(st, "create_work_order", t1)
        st["approval"] = rid
        note += f" A work order request ({rid}) was submitted and is waiting for approval."
    return note


def analytics(st):
    t0 = time.time()
    rows = work_orders()
    _tool_span(st, "work_order_stats", t0)
    return f"Work orders: {len(rows)} total, {len([r for r in rows if r.get('status') == 'OPEN'])} open."


graph = agent_graph.build(converse, tools={"facilities": facilities, "maintenance": maintenance, "analytics": analytics})


def ask(question, user="maria"):
    return graph.invoke({"question": question, "user": user, "spans": []})


if __name__ == "__main__":
    st = ask("Boiler B-12 is at 34 psi. What does the SOP say, and please raise a work order for it. How many work orders are open?")
    print("route:", st["route"])
    print("spans:", [s["name"] for s in st["spans"]])
    print("approval request:", st.get("approval", "none")[:8], "| answer:", st["answer"][:70])
