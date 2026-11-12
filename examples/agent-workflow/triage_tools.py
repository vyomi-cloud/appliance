"""Shared pieces of the support-triage sample agent: the three tools, the tiny 'database', a local vector search, the system prompt,
the scenarios and a small CLI harness. Nothing here is Vyomi-specific - the three agent_*.py drivers use the NATIVE cloud SDKs and
only differ from production code in the endpoint they point at.

Tools (plain Python functions, JSON-schema described in TOOLS):
    get_order_status(order_id)            -> looks the order up in the database
    search_kb(query)                      -> embeds the query, cosine-ranks the knowledge-base articles (local vector search)
    create_ticket(summary, priority, order_id?) -> appends a ticket to the database

Database: a JSON document. Local file by default (./triage_db.json, or $TRIAGE_DB_FILE); set TRIAGE_DB_S3_BUCKET to keep it in an
S3 object instead (boto3 against $VYOMI_ENDPOINT, so it lands in the simulator's S3).
"""
import json
import math
import os
import sys
import time
import uuid

SEED = {
    "orders": {
        "A1001": {"status": "shipped", "carrier": "UPS", "tracking": "1Z999AA10123456784", "eta": "2026-11-12", "items": ["USB-C dock"]},
        "A1002": {"status": "delivered", "carrier": "FedEx", "tracking": "7712 3456 7890", "eta": "2026-11-03", "items": ["27in monitor"]},
        "A1003": {"status": "processing", "carrier": None, "tracking": None, "eta": "2026-11-15", "items": ["mechanical keyboard"]},
    },
    "kb": [
        {"id": "kb-1", "title": "Reset your password", "text": "To reset your password open Settings, choose Security and click 'Forgot password'. A reset link is emailed and expires in 30 minutes."},
        {"id": "kb-2", "title": "Refund policy", "text": "Items can be returned within 30 days of delivery for a full refund. Damaged items are refunded or replaced at no cost; open a ticket with the order number."},
        {"id": "kb-3", "title": "Shipping times", "text": "Standard shipping takes 3 to 5 business days, express shipping 1 to 2 business days. Tracking numbers are emailed when the order ships."},
        {"id": "kb-4", "title": "Change delivery address", "text": "The delivery address can be changed only while the order is still processing. Once shipped, contact the carrier with the tracking number."},
        {"id": "kb-5", "title": "Invoices and receipts", "text": "Download invoices from Account, then Billing history. Invoices are available as PDF for 7 years."},
    ],
    "kb_vectors": {},
    "tickets": [],
}

# ---------------------------------------------------------------- the JSON "database" (local file or S3 object)


def _s3():
    import boto3
    return boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-east-1"), endpoint_url=os.environ.get("VYOMI_ENDPOINT") or None,
                        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID", "test"), aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY", "test"))


def load_db() -> dict:
    bucket = os.environ.get("TRIAGE_DB_S3_BUCKET")
    if bucket:
        s3 = _s3()
        try:
            return json.loads(s3.get_object(Bucket=bucket, Key="triage_db.json")["Body"].read())
        except Exception:
            try:
                s3.create_bucket(Bucket=bucket)
            except Exception:
                pass
            save_db(json.loads(json.dumps(SEED)))
            return json.loads(json.dumps(SEED))
    path = os.environ.get("TRIAGE_DB_FILE", "triage_db.json")
    if not os.path.exists(path):
        save_db(json.loads(json.dumps(SEED)))
    with open(path) as f:
        return json.load(f)


def save_db(db: dict) -> None:
    bucket = os.environ.get("TRIAGE_DB_S3_BUCKET")
    if bucket:
        _s3().put_object(Bucket=bucket, Key="triage_db.json", Body=json.dumps(db).encode())
        return
    with open(os.environ.get("TRIAGE_DB_FILE", "triage_db.json"), "w") as f:
        json.dump(db, f, indent=1)


def reset_db() -> None:
    save_db(json.loads(json.dumps(SEED)))


# ---------------------------------------------------------------- embeddings + vector search

_embedder = None


def set_embedder(fn) -> None:
    """fn(list[str]) -> list[list[float]]. Each driver plugs in its cloud's NATIVE embeddings call (Titan / Vertex / Azure OpenAI)."""
    global _embedder
    _embedder = fn


def _cos(a, b):
    return sum(x * y for x, y in zip(a, b)) / ((math.sqrt(sum(x * x for x in a)) or 1) * (math.sqrt(sum(y * y for y in b)) or 1))


def _kw_score(q, text):                     # only used when no embedder is configured; clearly labelled in the result
    qs, ts = set(q.lower().split()), set(text.lower().split())
    return len(qs & ts) / (len(qs) or 1)


# ---------------------------------------------------------------- the tools


def get_order_status(order_id: str) -> dict:
    o = load_db()["orders"].get(str(order_id).strip().upper())
    return {"order_id": str(order_id).upper(), **o} if o else {"error": f"order {order_id} not found"}


def search_kb(query: str, top_k: int = 2) -> dict:
    db = load_db()
    kb = db["kb"]
    if _embedder is None:
        ranked = sorted(kb, key=lambda d: -_kw_score(query, d["title"] + " " + d["text"]))
        return {"method": "keyword-fallback (no embedder configured)", "results": [{"title": d["title"], "text": d["text"]} for d in ranked[:top_k]]}
    vecs = db.setdefault("kb_vectors", {})
    missing = [d for d in kb if d["id"] not in vecs]
    if missing:                                         # embed the corpus once, cache the vectors in the database
        for d, v in zip(missing, _embedder([d["title"] + ". " + d["text"] for d in missing])):
            vecs[d["id"]] = v
        save_db(db)
    q = _embedder([query])[0]
    scored = sorted(((_cos(q, vecs[d["id"]]), d) for d in kb), key=lambda t: -t[0])[:top_k]
    return {"method": "vector-search", "results": [{"title": d["title"], "text": d["text"], "score": round(s, 3)} for s, d in scored]}


def create_ticket(summary: str, priority: str = "normal", order_id: str = "") -> dict:
    db = load_db()
    t = {"ticket_id": "T-" + uuid.uuid4().hex[:6].upper(), "summary": summary, "priority": priority if priority in ("low", "normal", "high") else "normal",
         "order_id": order_id or None, "created": time.strftime("%Y-%m-%dT%H:%M:%S")}
    db["tickets"].append(t)
    save_db(db)
    return t


FUNCS = {"get_order_status": get_order_status, "search_kb": search_kb, "create_ticket": create_ticket}

# Provider-neutral JSON-schema descriptions; each driver reshapes them into its SDK's tool format.
TOOLS = [
    {"name": "get_order_status", "description": "Look up an order by its id (for example A1001) and return status, carrier, tracking number and ETA.",
     "parameters": {"type": "object", "properties": {"order_id": {"type": "string", "description": "order id such as A1001"}}, "required": ["order_id"]}},
    {"name": "search_kb", "description": "Search the help-centre knowledge base for articles relevant to a customer question (policies, how-tos).",
     "parameters": {"type": "object", "properties": {"query": {"type": "string", "description": "what to search for"}}, "required": ["query"]}},
    {"name": "create_ticket", "description": "Open a support ticket for a human agent when the problem cannot be solved from order data or the knowledge base.",
     "parameters": {"type": "object", "properties": {"summary": {"type": "string"}, "priority": {"type": "string", "enum": ["low", "normal", "high"]},
                                                      "order_id": {"type": "string"}}, "required": ["summary", "priority"]}},
]

SYSTEM = ("You are a support triage agent. Use the tools to answer: get_order_status for questions about an order, search_kb for how-to or "
          "policy questions, create_ticket when the customer reports a problem that needs a human (damaged item, complaint). "
          "After the tool results arrive, reply to the customer in one or two short sentences. Do not invent order data.")

MAX_STEPS = 6

# name, customer message, tools that must have been called, words (any) that must appear in the final answer
SCENARIOS = [
    {"name": "order-status", "question": "Where is my order A1001?", "expect_tools": ["get_order_status"], "expect_answer_any": ["shipped", "ups", "1z999", "nov"]},
    {"name": "kb-search", "question": "How do I reset my password?", "expect_tools": ["search_kb"], "expect_answer_any": ["forgot", "settings", "security", "reset link", "30 minutes"]},
    {"name": "damaged-ticket", "question": "My order A1002 arrived damaged, please open a support ticket for it.", "expect_tools": ["create_ticket"], "expect_answer_any": ["ticket", "t-"]},
]


RESULTS = []          # every tool result of the current run (the CLI prints/saves it so transcripts show what the model was given)


def execute(name: str, args: dict) -> dict:
    """Run one tool call coming from the model. Bad names / args are returned to the model as an error result, never raised."""
    fn = FUNCS.get(name)
    try:
        res = {"error": f"unknown tool {name}"} if not fn else fn(**(args or {}))
    except TypeError as e:
        res = {"error": f"bad arguments for {name}: {e}"}
    RESULTS.append({"tool": name, "args": args, "result": res})
    return res


def cli(run_agent, label: str, argv=None) -> int:
    """run_agent(question, trace) -> final answer text. trace is a list the driver appends {"step", "seconds", "tool_calls", "text"} dicts to."""
    import argparse
    ap = argparse.ArgumentParser(description=f"{label} support-triage agent")
    ap.add_argument("question", nargs="?", help="a customer message (default: run the 3 built-in scenarios)")
    ap.add_argument("--runs", type=int, default=1, help="repeat each scenario N times")
    ap.add_argument("--json", help="write the full traces to this file")
    a = ap.parse_args(argv)
    scen = [{"name": "adhoc", "question": a.question, "expect_tools": [], "expect_answer_any": []}] if a.question else SCENARIOS
    out, ok_n, total = [], 0, 0
    for sc in scen:
        for i in range(a.runs):
            reset_db()
            RESULTS.clear()
            trace, t0, err, ans = [], time.time(), None, ""
            try:
                ans = run_agent(sc["question"], trace)
            except Exception as e:                       # report, don't hide: a flaky small model is part of the story
                err = f"{type(e).__name__}: {str(e)[:300]}"
            called = [c["name"] for s in trace for c in s["tool_calls"]]
            ok = err is None and all(t in called for t in sc["expect_tools"]) and (not sc["expect_answer_any"] or any(w in ans.lower() for w in sc["expect_answer_any"]))
            total += 1
            ok_n += ok
            print(f"\n[{label}] {sc['name']} run {i + 1}: {'OK' if ok else 'FAIL'}  ({time.time() - t0:.1f}s, {len(trace)} steps)  Q: {sc['question']}")
            for s in trace:
                print(f"   step {s['step']} {s['seconds']:.1f}s  calls={[(c['name'], c['args']) for c in s['tool_calls']]}  {('text=' + repr(s['text'][:100])) if s['text'] else ''}")
            for r in RESULTS:
                print(f"   tool result {r['tool']}: {json.dumps(r['result'])[:230]}")
            print(f"   answer: {ans.strip()[:300]}" + (f"\n   error: {err}" if err else ""))
            out.append({"scenario": sc["name"], "run": i + 1, "ok": ok, "error": err, "answer": ans, "seconds": round(time.time() - t0, 1), "steps": trace, "tool_results": list(RESULTS)})
    print(f"\n[{label}] {ok_n}/{total} runs OK")
    if a.json:
        json.dump(out, open(a.json, "w"), indent=1)
    return 0 if ok_n == total else 1


def endpoint() -> str:
    ep = os.environ.get("VYOMI_ENDPOINT")
    if not ep:
        sys.exit("Set VYOMI_ENDPOINT to the simulator base URL (see README), e.g. http://127.0.0.1:8099 - run_demo.py starts one for you.")
    return ep.rstrip("/")
