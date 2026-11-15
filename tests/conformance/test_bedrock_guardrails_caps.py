"""Bedrock Guardrails capability close-out, proved with the REAL boto3 bedrock + bedrock-runtime clients over HTTP (deterministic fake model).

  1. stream/Invoke output guarding: ConverseStream (sync window + async), InvokeModel, InvokeModelWithResponseStream
  2. contextual grounding + relevance (ApplyGuardrail qualifiers, Converse guardContent) over the embedding seam
  3. content-filter strength LOW/MEDIUM/HIGH (+ embedding-prototype classifier plumbing with a FAKE embedder, quality not measured)
  4. state persists in the account bag (survives a store round-trip)
Run: PYTHONPATH=. python tests/conformance/test_bedrock_guardrails_caps.py
"""
import json
import os
import socket
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from llm_fakes import FakeLLM  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

PASS = FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name} {str(extra)[:700]}")


def main():
    import boto3
    import uvicorn
    from botocore.config import Config
    from fastapi import FastAPI, Request
    from core import llm_core as llm
    from core import bedrock_guardrails_core as G
    from core.aws_wire_router import AwsWireRouter
    from core import wire_ingress

    os.environ["VYOMI_GUARDRAIL_SEMANTIC"] = "0"      # the fake model server's embeddings are not semantic: keyword confidence only until section 3b
    fake = FakeLLM(delay=0.0)
    llm.set_backend(None)
    llm._state.update(endpoint=fake.url, no_rf=False, no_native=False)
    llm._state["embed_fn"] = lambda texts: [llm.hash_embed(t) for t in texts]     # deterministic bag-of-words embedder (the fake server's vectors are not semantic)
    os.environ.pop("VYOMI_LLM_DISABLE", None)
    router = AwsWireRouter()
    app = FastAPI()

    @app.api_route("/{p:path}", methods=["GET", "POST", "PUT", "DELETE"])
    async def any_(p: str, request: Request):
        return await wire_ingress.serve(router, request)
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    threading.Thread(target=srv.run, daemon=True).start()
    while not srv.started:
        time.sleep(0.05)
    url = f"http://127.0.0.1:{port}"
    kw = dict(region_name="us-east-1", endpoint_url=url, aws_access_key_id="x", aws_secret_access_key="y", config=Config(retries={"max_attempts": 1}))
    br, bc = boto3.client("bedrock-runtime", **kw), boto3.client("bedrock", **kw)
    M = "amazon.nova-lite-v1:0"
    CL = "anthropic.claude-3-haiku-20240307-v1:0"
    msgs = lambda t: [{"role": "user", "content": [{"text": t}]}]   # noqa: E731

    gid = bc.create_guardrail(
        name="facilities-guardrail", blockedInputMessaging="Input blocked.", blockedOutputsMessaging="Output blocked.",
        wordPolicyConfig={"wordsConfig": [{"text": "forbidden"}]},
        sensitiveInformationPolicyConfig={"piiEntitiesConfig": [{"type": "EMAIL", "action": "ANONYMIZE"}]})["guardrailId"]
    v1 = bc.create_guardrail_version(guardrailIdentifier=gid)["version"]
    cfg = lambda mode=None, trace="enabled": dict({"guardrailIdentifier": gid, "guardrailVersion": v1, "trace": trace}, **({"streamProcessingMode": mode} if mode else {}))   # noqa: E731

    def cstream(text, **g):
        out, stop, meta = "", None, {}
        for e in br.converse_stream(modelId=M, messages=msgs("hi"), guardrailConfig=g or cfg())["stream"]:
            if "contentBlockDelta" in e:
                out += e["contentBlockDelta"]["delta"].get("text", "")
            elif "messageStop" in e:
                stop = e["messageStop"]["stopReason"]
            elif "metadata" in e:
                meta = e["metadata"]
        return out, stop, meta

    # ───────── 1. stream output guarding
    long_ok = "safe words here. " * 70                       # ~1190 chars: first window passes untouched
    fake.handler = lambda b: {"content": "all good here"}
    out, stop, meta = cstream("hi")
    check("ConverseStream clean output passes, stopReason end_turn", out == "all good here" and stop == "end_turn", (out, stop))
    fake.handler = lambda b: {"content": "this is forbidden content"}
    out, stop, meta = cstream("hi")
    check("ConverseStream (sync): unsafe model output is replaced, never delivered, stopReason guardrail_intervened",
          out == "Output blocked." and "forbidden" not in out and stop == "guardrail_intervened", (out, stop))
    oa = ((meta.get("trace") or {}).get("guardrail") or {}).get("outputAssessments", {}).get(gid)
    check("ConverseStream metadata trace carries the output assessment", oa and oa[0]["wordPolicy"]["customWords"][0]["match"] == "forbidden", meta)
    fake.handler = lambda b: {"content": long_ok + " then forbidden tail"}
    out, stop, _ = cstream("hi")
    check("ConverseStream (sync) buffered window: first window delivered, block lands on the next, stream cut",
          out.startswith("safe words here.") and out.endswith("Output blocked.") and "forbidden" not in out and stop == "guardrail_intervened", (out[-60:], stop))
    out, stop, meta = cstream("hi", **cfg("async"))
    check("ConverseStream streamProcessingMode=async: text streams unmodified, intervention only reported in trace",
          out.endswith("forbidden tail") and stop == "end_turn" and meta["trace"]["guardrail"]["outputAssessments"][gid], (out[-40:], stop, meta))
    fake.handler = lambda b: {"content": "mail bob@example.com now"}
    out, stop, _ = cstream("hi")
    check("ConverseStream (sync) ANONYMIZE masks PII in the streamed output", out == "mail {EMAIL} now", out)
    fake.handler = lambda b: {"content": "ok"}
    r = None
    try:
        for _ in br.converse_stream(modelId=M, messages=msgs("this is forbidden"), guardrailConfig=cfg())["stream"]:
            pass
        n_calls = None
    except Exception as e:  # noqa: BLE001
        n_calls = e
    check("ConverseStream blocked INPUT still short-circuits", n_calls is None)

    def invoke(model, body, **g):
        return json.loads(br.invoke_model(modelId=model, body=json.dumps(body), **g)["body"].read())

    def istream(model, body, **g):
        evs = [json.loads(e["chunk"]["bytes"]) for e in br.invoke_model_with_response_stream(modelId=model, body=json.dumps(body), **g)["body"]]
        return evs
    G_ = dict(guardrailIdentifier=gid, guardrailVersion=v1, trace="ENABLED")
    claude = lambda t: {"anthropic_version": "bedrock-2023-05-31", "max_tokens": 100, "messages": [{"role": "user", "content": t}]}   # noqa: E731
    fake.handler = lambda b: {"content": "fine answer"}
    r = invoke(CL, claude("hi"), **G_)
    check("InvokeModel + guardrail: clean -> guardrailAction NONE and normal content", r.get("amazon-bedrock-guardrailAction") == "NONE" and r["content"][0]["text"] == "fine answer", r)
    n0 = len(fake.requests)
    r = invoke(CL, claude("say forbidden"), **G_)
    check("InvokeModel + guardrail: unsafe INPUT -> blocked message, INTERVENED, trace, model not called",
          r["content"][0]["text"] == "Input blocked." and r["amazon-bedrock-guardrailAction"] == "INTERVENED" and "inputAssessment" in r["amazon-bedrock-trace"]["guardrail"]
          and len(fake.requests) == n0, r)
    fake.handler = lambda b: {"content": "reply has forbidden word"}
    r = invoke(CL, claude("hi"), **G_)
    check("InvokeModel + guardrail: unsafe OUTPUT replaced with blockedOutputsMessaging", r["content"][0]["text"] == "Output blocked." and r["amazon-bedrock-guardrailAction"] == "INTERVENED"
          and "outputAssessments" in r["amazon-bedrock-trace"]["guardrail"], r)
    evs = istream(CL, claude("hi"), **G_)
    txt = "".join(e["delta"]["text"] for e in evs if e["type"] == "content_block_delta")
    check("InvokeModelWithResponseStream + guardrail: unsafe OUTPUT replaced, INTERVENED on the final chunk", txt == "Output blocked." and "forbidden" not in txt
          and evs[-1].get("amazon-bedrock-guardrailAction") == "INTERVENED" and "outputAssessments" in evs[-1]["amazon-bedrock-trace"]["guardrail"], evs[-1])
    evs = istream(CL, claude("say forbidden"), **G_)
    txt = "".join(e["delta"]["text"] for e in evs if e["type"] == "content_block_delta")
    check("InvokeModelWithResponseStream + guardrail: unsafe INPUT blocked", txt == "Input blocked." and evs[-1]["amazon-bedrock-guardrailAction"] == "INTERVENED", evs[-1])
    fake.handler = lambda b: {"content": "mail bob@example.com"}
    evs = istream(CL, claude("hi"), **G_)
    check("InvokeModelWithResponseStream + guardrail: PII anonymised", "".join(e["delta"]["text"] for e in evs if e["type"] == "content_block_delta") == "mail {EMAIL}")
    fake.handler = lambda b: {"content": "reply has forbidden word"}
    evs = istream(M, {"messages": msgs("hi"), "inferenceConfig": {"max_new_tokens": 50}}, **G_)
    check("InvokeModelWithResponseStream (Nova) + guardrail: output blocked, action on messageStop", "".join(e["contentBlockDelta"]["delta"]["text"] for e in evs if "contentBlockDelta" in e) == "Output blocked."
          and [e for e in evs if "messageStop" in e][0]["messageStop"].get("amazon-bedrock-guardrailAction") == "INTERVENED", evs[-2:])

    # ───────── 2. contextual grounding + relevance
    cg = bc.create_guardrail(name="grounded", blockedInputMessaging="in", blockedOutputsMessaging="Ungrounded.",
                             contextualGroundingPolicyConfig={"filtersConfig": [{"type": "GROUNDING", "threshold": 0.7}, {"type": "RELEVANCE", "threshold": 0.5}]})
    cid = cg["guardrailId"]
    src = "The HVAC filter in building 4 is replaced every 90 days by the facilities team."

    def ag(answer, query="How often is the building 4 HVAC filter replaced?"):
        return br.apply_guardrail(guardrailIdentifier=cid, guardrailVersion="DRAFT", source="OUTPUT", content=[
            {"text": {"text": src, "qualifiers": ["grounding_source"]}}, {"text": {"text": query, "qualifiers": ["query"]}},
            {"text": {"text": answer, "qualifiers": ["guard_content"]}}])
    ok = ag("The building 4 HVAC filter is replaced every 90 days by the facilities team.")
    gf = ok["assessments"][0]["contextualGroundingPolicy"]["filters"]
    check("ApplyGuardrail grounding: grounded answer passes with GROUNDING+RELEVANCE scores and thresholds",
          ok["action"] == "NONE" and {f["type"] for f in gf} == {"GROUNDING", "RELEVANCE"} and all("score" in f and "threshold" in f for f in gf), ok)
    bad = ag("The filter is replaced every 30 days and the budget is 5000 dollars.")
    check("ApplyGuardrail grounding: hallucinated answer -> GUARDRAIL_INTERVENED, GROUNDING detected + blocked messaging",
          bad["action"] == "GUARDRAIL_INTERVENED" and bad["outputs"][0]["text"] == "Ungrounded."
          and any(f["type"] == "GROUNDING" and f["detected"] and f["action"] == "BLOCKED" for f in bad["assessments"][0]["contextualGroundingPolicy"]["filters"]), bad)
    off = ag("Penguins live in Antarctica and enjoy fish.")
    check("ApplyGuardrail relevance: off-topic answer is flagged by RELEVANCE",
          any(f["type"] == "RELEVANCE" and f["detected"] for f in off["assessments"][0]["contextualGroundingPolicy"]["filters"]), off)
    fake.handler = lambda b: {"content": "The filter is replaced every 30 days and the budget is 5000 dollars."}
    gc = lambda t, q: [{"role": "user", "content": [{"guardContent": {"text": {"text": t, "qualifiers": ["grounding_source"]}}},   # noqa: E731
                                                       {"guardContent": {"text": {"text": q, "qualifiers": ["query"]}}}]}]
    r = br.converse(modelId=M, messages=gc(src, "How often is the building 4 HVAC filter replaced?"),
                    guardrailConfig={"guardrailIdentifier": cid, "guardrailVersion": "DRAFT", "trace": "enabled"})
    check("Converse guardContent (grounding_source + query): ungrounded model answer is intervened",
          r["stopReason"] == "guardrail_intervened" and r["output"]["message"]["content"][0]["text"] == "Ungrounded."
          and "contextualGroundingPolicy" in r["trace"]["guardrail"]["outputAssessments"][cid][0], r)
    fake.handler = lambda b: {"content": "The building 4 HVAC filter is replaced every 90 days by the facilities team."}
    r = br.converse(modelId=M, messages=gc(src, "How often is the building 4 HVAC filter replaced?"), guardrailConfig={"guardrailIdentifier": cid, "guardrailVersion": "DRAFT"})
    check("Converse guardContent: grounded answer passes", r["stopReason"] == "end_turn", r)

    # ───────── 3. strength levels
    def strength(s_in):
        g = bc.create_guardrail(name="st" + s_in.lower(), blockedInputMessaging="blocked", blockedOutputsMessaging="blocked",
                                contentPolicyConfig={"filtersConfig": [{"type": "INSULTS", "inputStrength": s_in, "outputStrength": "NONE"}]})["guardrailId"]
        return lambda t: br.apply_guardrail(guardrailIdentifier=g, guardrailVersion="DRAFT", source="INPUT", content=[{"text": {"text": t}}])
    lo, me, hi = strength("LOW"), strength("MEDIUM"), strength("HIGH")
    one, two, three = "you are an idiot", "you idiot, what a moron", "stupid idiot moron loser"
    sig = lambda f, t: f(t)["action"] == "GUARDRAIL_INTERVENED"   # noqa: E731
    check("strength HIGH blocks LOW/MEDIUM/HIGH-confidence hits", sig(hi, one) and sig(hi, two) and sig(hi, three))
    check("strength MEDIUM blocks MEDIUM+ but passes LOW-confidence", not sig(me, one) and sig(me, two) and sig(me, three))
    check("strength LOW blocks only HIGH-confidence", not sig(lo, one) and not sig(lo, two) and sig(lo, three))
    a = hi(two)["assessments"][0]["contentPolicy"]["filters"][0]
    check("content filter assessment reports confidence + filterStrength", a["confidence"] == "MEDIUM" and a["filterStrength"] == "HIGH" and a["type"] == "INSULTS", a)
    # embedding-prototype classifier plumbing: a FAKE registered embedder (bag-of-words), proves the wiring, says nothing about real model quality
    os.environ.pop("VYOMI_GUARDRAIL_SEMANTIC")
    proto = G._PROTO["INSULTS"][0]
    near = "you are a worthless awful person"      # no keyword hit, close to a prototype under the fake embedder
    sc = G._semantic_scores(near)
    check("semantic classifier active only with a real (registered) embedder; scores per category", sc and sc["INSULTS"] > 0.5, sc)
    G.SEM_THRESHOLDS = (0.4, 0.5, 0.9)
    check("semantic hit with no keyword: blocked at HIGH strength, passes at LOW", sig(hi, near) and not sig(lo, near), hi(near))
    llm._state["embed_fn"] = None
    llm._state.update(endpoint=None)
    G.SEM_THRESHOLDS = (0.58, 0.68, 0.78)
    check("hash-fallback embedder disables the semantic path (keywords only)", G._semantic_scores(near) is None and not sig(hi, near))
    llm._state.update(endpoint=fake.url)

    # ───────── 4. persistence
    blob = json.dumps(router.s3.account)
    check("guardrail state lives in the persisted account bag (JSON-safe)", gid in json.loads(blob).get("bedrock_guardrails", {}), list(router.s3.account))
    router.s3.account.clear()
    try:
        bc.get_guardrail(guardrailIdentifier=gid)
        gone = False
    except bc.exceptions.ResourceNotFoundException:
        gone = True
    router.s3.account.update(json.loads(blob))        # what a restart does: the account bag is reloaded from the persisted store
    back = bc.get_guardrail(guardrailIdentifier=gid, guardrailVersion=v1)
    check("after a restart-style reload the guardrail, its version and policies are intact", gone and back["version"] == v1 and back["name"] == "facilities-guardrail"
          and back["wordPolicy"]["words"][0]["text"] == "forbidden")
    fake.handler = lambda b: {"content": "contains forbidden"}
    r = br.converse(modelId=M, messages=msgs("hi"), guardrailConfig=cfg())
    check("reloaded guardrail still intervenes at runtime", r["stopReason"] == "guardrail_intervened", r)
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
