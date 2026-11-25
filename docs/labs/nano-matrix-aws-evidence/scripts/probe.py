# Model probe: the course's own prompts, called exactly as agents.py / try_models.py / retrieve_and_generate.py call them.
import json, re, time, boto3
from models import CHAT_MODEL, chat_with_tools
rt = boto3.client("bedrock-runtime")
ROUTER_PROMPT = (
    "You route facilities requests to specialist agents. The agents are:\n"
    "- facilities: searches the knowledge base (SOPs, safety rules, policies, procedures).\n"
    "- maintenance: looks up a specific asset (ids like B-12 or AHU-7) and its work orders, and can raise a work order.\n"
    "- analytics: counts and statistics over work orders.\n"
    "Reply with only a JSON list such as [\"facilities\",\"maintenance\"], drawn from [\"facilities\",\"maintenance\",\"analytics\"].")
QS = ["Boiler B-12 is at 34 psi. What does the SOP say, and please raise a work order for it. How many work orders are open?",
      "What should I do when boiler pressure exceeds 30 psi?", "How many work orders are open?"]
def conv(system, text, mt):
    t0 = time.time()
    r = rt.converse(modelId=CHAT_MODEL, system=[{"text": system}], messages=[{"role": "user", "content": [{"text": text}]}], inferenceConfig={"maxTokens": mt, "temperature": 0})
    return r["output"]["message"]["content"][0]["text"], r["usage"], r["stopReason"], round(time.time() - t0, 1)
out = {"model": CHAT_MODEL}
# 1. router JSON adherence (supervisor.plan)
rt_res = []
for q in QS:
    try:
        txt, u, sr, dt = conv(ROUTER_PROMPT, q, 60)
        try:
            plan = [p for p in json.loads(re.search(r"\[.*\]", txt, re.S).group(0)) if p in ("facilities", "maintenance", "analytics")]
        except Exception:
            plan = None
        rt_res.append({"q": q[:50], "raw": txt, "plan": plan, "json_ok": bool(plan), "usage": u, "secs": dt})
    except Exception as e:
        rt_res.append({"q": q[:50], "error": type(e).__name__ + ": " + str(e)[:200]})
out["router"] = rt_res
# 2. tool-use turn (try_models.py TOOL, verbatim)
TOOL = {"toolSpec": {"name": "asset_status", "description": "status of an asset by id", "inputSchema": {"json": {"type": "object", "properties": {"asset_id": {"type": "string"}}, "required": ["asset_id"]}}}}
try:
    t0 = time.time(); r = chat_with_tools("What is the status of asset B-12?", [TOOL])
    out["tool_turn"] = {"stop_reason": r["stop_reason"], "tool_use": r["tool_use"], "text": r["text"][:200], "secs": round(time.time() - t0, 1)}
except Exception as e:
    out["tool_turn"] = {"error": type(e).__name__ + ": " + str(e)[:200]}
# 3. RAG grounding: retrieve from the KB the learner built (ch 4/5) then the synth prompt from agents.py
try:
    ag = boto3.client("bedrock-agent")
    kb = next(k for k in ag.list_knowledge_bases()["knowledgeBaseSummaries"] if k["name"] == "facilities-kb")["knowledgeBaseId"]
    q = "What should I do when boiler pressure exceeds 30 psi?"
    hits = boto3.client("bedrock-agent-runtime").retrieve(knowledgeBaseId=kb, retrievalQuery={"text": q}, retrievalConfiguration={"vectorSearchConfiguration": {"numberOfResults": 3}})["retrievalResults"]
    ctx = "\n".join("[%d] %s" % (i + 1, h["content"]["text"][:160]) for i, h in enumerate(hits))
    txt, u, sr, dt = conv("Answer using only the context. Cite sources like [1].", "Context:\n%s\n\nQuestion: %s" % (ctx, q), 300)
    out["rag"] = {"hits": len(hits), "top": (hits[0]["content"]["text"][:100] if hits else None), "answer": txt, "cites": bool(re.search(r"\[\d\]", txt)), "mentions_30_psi": "30" in txt, "usage": u, "secs": dt, "stop": sr}
except Exception as e:
    out["rag"] = {"error": type(e).__name__ + ": " + str(e)[:300]}
# 4. latency / tokens for a plain chat
try:
    txt, u, sr, dt = conv("You are a facilities assistant.", "Reply with the single word OK.", 20)
    out["chat"] = {"text": txt, "usage": u, "secs": dt}
except Exception as e:
    out["chat"] = {"error": str(e)[:200]}
print("PROBE_JSON " + json.dumps(out))
