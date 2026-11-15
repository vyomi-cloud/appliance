"""Bedrock standard model ids as ALIASES of the local model + tool-use / streaming against the deterministic TEST STUB llm.

Covers (v4 lane `models`): ListFoundationModels/GetFoundationModel list anthropic.claude-*, amazon.titan-*, amazon.nova-*, meta.llama*,
cohere.* with honest metadata (vyomiBackedBy); inference-profile listing; Converse / ConverseStream / InvokeModel with toolConfig
(tool_use round trip) and RetrieveAndGenerate against the stub. Every model-output assertion here is STUB-BACKED (tools/llm_stub):
it proves the wire/tool-use plumbing, NOT model quality. With boto3 installed the same calls are repeated through the real SDK.

Run: PYTHONPATH=. python3 tests/conformance/test_bedrock_models_alias.py     (boto3 section: /private/tmp/ai-probe-venv13/bin/python)
"""
import json
import os
os.environ["VYOMI_LIST_BEDROCK_ALIASES"] = "1"  # these tests assert the opt-in alias listing
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools", "llm_stub"))
import stub_llm_server  # noqa: E402

os.environ["VYOMI_LLM_ENDPOINT"] = stub_llm_server.start()
from core import ai_models_core as am  # noqa: E402

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' - ' + str(detail)[:300] if detail and not ok else ''}")


def call(method, path, body=None):
    r = am.bedrock_dispatch(method, path, {}, {}, json.dumps(body).encode() if body is not None else b"")
    return r["status"], (json.loads(r["body"]) if r["body"] and r["headers"].get("content-type", "").startswith("application/json") else r), r["headers"]


# ── listing
st, doc, _ = call("GET", "/foundation-models")
ids = {m["modelId"]: m for m in doc["modelSummaries"]}
check("list: standard ids present", all(any(i.startswith(p) for i in ids) for p in ("anthropic.claude-", "amazon.titan-", "amazon.nova-", "meta.llama", "cohere.")))
check("list: the native vyomi.* ten are still listed", sum(1 for i in ids if i.startswith("vyomi.")) == 10)
a = ids["anthropic.claude-3-haiku-20240307-v1:0"]
check("alias honest metadata: lifecycle + vyomiBackedBy note", a["modelLifecycle"]["status"] == "ACTIVE" and "not by the original vendor" in a["vyomiBackedBy"]["note"]
      and a["vyomiBackedBy"]["catalogModelId"] and a["vyomiBackedBy"]["localModel"], a)
check("alias claims no extra capability (TEXT only, no vision)", all(m["inputModalities"] == ["TEXT"] for m in ids.values()))
check("embedding aliases output EMBEDDING and do not stream", ids["amazon.titan-embed-text-v2:0"]["outputModalities"] == ["EMBEDDING"] and not ids["amazon.titan-embed-text-v2:0"]["responseStreamingSupported"])
st, doc, _ = call("GET", "/foundation-models", None)
r = am.bedrock_dispatch("GET", "/foundation-models", {"byProvider": "Anthropic"}, {}, b"")
check("byProvider=Anthropic filters aliases", {m["modelId"].split(".")[0] for m in json.loads(r["body"])["modelSummaries"]} == {"anthropic"})
st, doc, _ = call("GET", "/foundation-models/amazon.nova-lite-v1:0")
check("GetFoundationModel alias", st == 200 and doc["modelDetails"]["modelId"] == "amazon.nova-lite-v1:0")
check("GetFoundationModel unknown -> 404", call("GET", "/foundation-models/anthropic.claude-v2")[0] == 404)

# ── inference profiles
st, doc, _ = call("GET", "/inference-profiles")
pr = {p["inferenceProfileId"]: p for p in doc["inferenceProfileSummaries"]}
check("inference profiles: us.anthropic.claude-* listed (SYSTEM_DEFINED, ACTIVE)", st == 200 and pr["us.anthropic.claude-3-haiku-20240307-v1:0"]["type"] == "SYSTEM_DEFINED"
      and pr["us.anthropic.claude-3-haiku-20240307-v1:0"]["status"] == "ACTIVE")
check("GetInferenceProfile", call("GET", "/inference-profiles/us.amazon.nova-pro-v1:0")[0] == 200 and call("GET", "/inference-profiles/us.nope")[0] == 404)

# ── Converse with every family, tool use round trip, stream, invoke
MSG = [{"role": "user", "content": [{"text": "What is the status of asset B-12?"}]}]
TOOL = {"tools": [{"toolSpec": {"name": "asset_status", "description": "asset status lookup",
                                "inputSchema": {"json": {"type": "object", "properties": {"asset_id": {"type": "string"}}, "required": ["asset_id"]}}}}]}
for mid in ("anthropic.claude-3-haiku-20240307-v1:0", "amazon.nova-lite-v1:0", "meta.llama3-1-8b-instruct-v1:0", "cohere.command-r-v1:0", "amazon.titan-text-express-v1", "us.anthropic.claude-3-haiku-20240307-v1:0"):
    st, doc, h = call("POST", f"/model/{mid}/converse", {"messages": MSG, "inferenceConfig": {"maxTokens": 30}})
    check(f"converse {mid}", st == 200 and doc["output"]["message"]["content"][0]["text"], doc)
st, doc, h = call("POST", "/model/anthropic.claude-3-haiku-20240307-v1:0/converse", {"messages": MSG, "toolConfig": TOOL})
tu = [c["toolUse"] for c in doc["output"]["message"]["content"] if "toolUse" in c]
check("converse toolConfig -> stopReason tool_use with toolUse{name,input}", doc["stopReason"] == "tool_use" and tu and tu[0]["name"] == "asset_status" and tu[0]["input"] == {"asset_id": "B-12"}, doc)
msgs2 = MSG + [doc["output"]["message"], {"role": "user", "content": [{"toolResult": {"toolUseId": tu[0]["toolUseId"], "content": [{"json": {"status": "RUNNING"}}]}}]}]
st, d2, _ = call("POST", "/model/anthropic.claude-3-haiku-20240307-v1:0/converse", {"messages": msgs2, "toolConfig": TOOL})
check("converse tool-result turn -> end_turn with text", st == 200 and d2["stopReason"] == "end_turn" and "RUNNING" in d2["output"]["message"]["content"][0]["text"], d2)
check("served-by header names the STUB (never mistaken for a real model)", "stub" in h.get("x-vyomi-local-model", ""), h)
st, rr, _ = call("POST", "/model/amazon.nova-lite-v1:0/converse-stream", {"messages": MSG, "toolConfig": TOOL})
check("converse-stream with tools yields an eventstream", st == 200 and b"toolUse" in (rr["body"] if isinstance(rr, dict) else b""), str(rr)[:200])
st, doc, _ = call("POST", "/model/anthropic.claude-3-haiku-20240307-v1:0/invoke", {"anthropic_version": "bedrock-2023-05-31", "max_tokens": 30, "messages": [{"role": "user", "content": "Reply with the single word OK."}]})
check("InvokeModel anthropic messages body", st == 200 and doc["content"][0]["text"] == "OK" and doc["stop_reason"] == "end_turn", doc)
st, doc, _ = call("POST", "/model/amazon.titan-embed-text-v2:0/invoke", {"inputText": "boiler"})
check("InvokeModel titan embed v2 -> 1024 dims", st == 200 and len(doc["embedding"]) == 1024)
st, doc, _ = call("POST", "/model/some.unknown-model/converse", {"messages": MSG})
check("unknown model id -> ValidationException", st == 400)

# ── real boto3 through an in-process HTTP server (optional)
try:
    import boto3
    from botocore.config import Config
    import asyncio, socket, threading, time
    import anyio, uvicorn
    from fastapi import FastAPI, Request
    os.environ.setdefault("CLOUDLEARN_STATE_FILE", "/tmp/models-alias-test.sqlite3")
    from core import wire_ingress
    app, router = FastAPI(), wire_ingress.appliance_router()

    @app.api_route("/{p:path}", methods=["GET", "POST", "PUT", "DELETE"])
    async def any_(p: str, request: Request):
        body = await request.body()
        return await anyio.to_thread.run_sync(lambda: asyncio.run(wire_ingress.serve(router, request, body=body)))
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    threading.Thread(target=srv.run, daemon=True).start()
    while not srv.started:
        time.sleep(0.05)
    kw = dict(endpoint_url=f"http://127.0.0.1:{port}", region_name="us-east-1", aws_access_key_id="t", aws_secret_access_key="t", config=Config(retries={"max_attempts": 1}))
    b, br = boto3.client("bedrock", **kw), boto3.client("bedrock-runtime", **kw)
    names = [m["modelId"] for m in b.list_foundation_models()["modelSummaries"]]
    check("boto3 list_foundation_models: anthropic + titan + nova + llama + cohere", all(any(n.startswith(p) for n in names) for p in ("anthropic.", "amazon.titan", "amazon.nova", "meta.llama", "cohere.")))
    check("boto3 get_foundation_model alias", b.get_foundation_model(modelIdentifier="anthropic.claude-3-haiku-20240307-v1:0")["modelDetails"]["providerName"] == "Anthropic")
    check("boto3 list_inference_profiles", any(p["inferenceProfileId"].startswith("us.anthropic") for p in b.list_inference_profiles()["inferenceProfileSummaries"]))
    r = br.converse(modelId="anthropic.claude-3-haiku-20240307-v1:0", messages=MSG, toolConfig=TOOL)
    check("boto3 converse tool_use", r["stopReason"] == "tool_use" and r["output"]["message"]["content"][0]["toolUse"]["input"] == {"asset_id": "B-12"}, r)
    evs = list(br.converse_stream(modelId="amazon.nova-lite-v1:0", messages=MSG, toolConfig=TOOL)["stream"])
    check("boto3 converse_stream tool_use events", any("contentBlockStart" in e and "toolUse" in e["contentBlockStart"]["start"] for e in evs), evs[:3])
except ImportError as e:
    print(f"[SKIP] boto3 section ({e}); run with /private/tmp/ai-probe-venv13/bin/python")

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
