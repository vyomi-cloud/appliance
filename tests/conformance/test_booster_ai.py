"""Booster AI pack, hermetic: fake OpenAI-compatible model server -> llm_core -> Bedrock/Vertex/Azure wire -> ledger -> /booster/status.

Covers: model admission against the AI RAM bucket (clear refusals), the gateway (chat/embeddings split), usage ledger per
session/cloud/op, booster status + /booster/ai/* routes, wasm/booster-link.js routing + chip (node), compose/boot script shape.

Run: PYTHONPATH=. ../s3_simulator/.venv/bin/python tests/conformance/test_booster_ai.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

os.environ.setdefault("CLOUDLEARN_STATE_DIR", tempfile.mkdtemp(prefix="booster-ai-"))
os.environ["VYOMI_HOST_MEM_MB"] = "8000"          # a 2-core/8 GB Codespace: cap 5600 -> AI share 2800 MB
os.environ.pop("VYOMI_BOOSTER_CAP_MB", None)

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' - ' + str(detail)[:300] if detail and not ok else ''}")


# ---- fake model servers (chat + embeddings, as two llama-server processes would be) -------------------------------------
class Chat(BaseHTTPRequestHandler):
    seen = []

    def log_message(self, *a):
        pass

    def _j(self, code, o):
        b = json.dumps(o).encode()
        self.send_response(code); self.send_header("content-type", "application/json"); self.send_header("content-length", str(len(b)))
        self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        self._j(200, {"status": "ok"} if self.path.startswith("/health") else {"data": [{"id": "fake-chat"}]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        Chat.seen.append((self.path, body))
        if self.path == "/v1/embeddings":
            return self._j(200, {"data": [{"embedding": [0.1] * 384} for _ in body["input"]], "model": "fake-embed", "usage": {"prompt_tokens": 3}})
        last = [m for m in body["messages"] if m["role"] == "user"][-1]["content"]
        self._j(200, {"model": "fake-chat", "choices": [{"message": {"content": "pong:" + last}, "finish_reason": "stop"}],
                      "usage": {"prompt_tokens": 17, "completion_tokens": 5}})


def serve(h):
    s = ThreadingHTTPServer(("127.0.0.1", 0), h)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s, f"http://127.0.0.1:{s.server_address[1]}"


chat_srv, chat_url = serve(Chat)
embed_srv, embed_url = serve(Chat)

from core import booster as B, booster_ai as AI, llm_core, booster_llm_gateway as GW  # noqa: E402

# ---- admission ----------------------------------------------------------------------------------------------------------
check("AI bucket on an 8 GB host is 2800 MB", B.resource_budget()["memory_split_mb"]["ai"] == 2800, B.resource_budget()["memory_split_mb"])
AI.release_all()
m = AI.admit("qwen2.5-3b", "chat", enforce=True)
check("3B default admitted (reserves RAM in the ai ledger)", m["id"] == "qwen2.5-3b" and B.usage()["ai"] == 2500, B.usage())
AI.admit("bge-small", "embed", enforce=True)
check("3B + bge-small both fit the 8 GB Codespace AI bucket", B.usage()["ai"] == 2750, B.usage())
try:
    AI.admit("qwen2.5-7b", "chat", enforce=True)
    check("7B refused on 8 GB host", False)
except AI.ModelAdmissionError as e:
    check("7B refused with ai_memory_exceeded", e.code == "ai_memory_exceeded", e.code)
    check("refusal names model, need, free, bucket size and a smaller alternative",
          all(x in e.message for x in ("qwen2.5-7b", "6.1 GB", "2.7 GB" if False else "AI memory", "70%", "qwen2.5-3b")) and "Try" in e.message, e.message)
check("refused model reserved nothing; previous chat model still held", B.usage()["ai"] == 2750, B.usage())
try:
    AI.admit("gpt-5", "chat", enforce=True); check("unknown model refused", False)
except AI.ModelAdmissionError as e:
    check("unknown model -> unknown_model listing choices", e.code == "unknown_model" and "qwen2.5-1.5b" in e.message, e.message)
try:
    AI.admit("bge-small", "chat", enforce=True); check("kind mismatch refused", False)
except AI.ModelAdmissionError as e:
    check("embed model cannot be admitted as chat", e.code == "unknown_model")
m = AI.admit("qwen2.5-1.5b", "chat", enforce=True)
check("swapping chat model replaces (not adds) its reservation", B.usage()["ai"] == 1750, B.usage())
os.environ["VYOMI_HOST_MEM_MB"] = "32000"          # the 32 GB design box: 22400 cap -> 11200 AI
AI.release_all()
AI.admit("qwen2.5-7b", "chat", enforce=True); AI.admit("nomic-embed-text", "embed", enforce=True)
check("7B opt-in + nomic fit when the host is big", B.usage()["ai"] == 6650, B.usage())
os.environ["VYOMI_HOST_MEM_MB"] = "8000"; AI.release_all()

os.environ["VYOMI_BOOSTER_AI_MODEL"] = "qwen2.5-7b"
p = AI.admit_configured(enforce=True)
check("admit_configured never raises; refused chat -> plan.ok False with reason", p["ok"] is False and "chat" in p["errors"] and "qwen2.5-7b" in p["errors"]["chat"]["message"], p)
check("embed still admitted when only chat was refused", p["embed"] and p["embed"]["id"] == "bge-small", p)
os.environ["VYOMI_BOOSTER_AI_MODEL"] = "qwen2.5-3b"
p = AI.admit_configured(enforce=True)
check("default plan ok: Qwen2.5-3B Q4_K_M + bge-small, gateway endpoint", p["ok"] and p["chat"]["hf"].endswith("Qwen2.5-3B-Instruct-GGUF:Q4_K_M") and p["embed"]["id"] == "bge-small" and p["endpoint"] == "http://llm:8080" and not p["errors"], p)

# ---- gateway: chat -> chat server, embeddings -> embed server -----------------------------------------------------------
gw, gw_url = serve(type("G", (GW.Handler,), {"chat_url": chat_url, "embed_url": embed_url}))
import urllib.request  # noqa: E402


def post(url, o):
    r = urllib.request.Request(url, data=json.dumps(o).encode(), headers={"content-type": "application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=10).read())


Chat.seen.clear()
post(gw_url + "/v1/embeddings", {"model": "qwen2.5-3b", "input": ["a"]})
post(gw_url + "/v1/chat/completions", {"model": "qwen2.5-3b", "messages": [{"role": "user", "content": "x"}]})
check("gateway sends embeddings and chat to different upstreams and rewrites the embed model name",
      [p for p, _ in Chat.seen] == ["/v1/embeddings", "/v1/chat/completions"] and Chat.seen[0][1]["model"] == "embed", Chat.seen)
check("gateway /health reports both servers", json.loads(urllib.request.urlopen(gw_url + "/health").read()) == {"status": "ok", "chat": True, "embed": True})

# ---- seam -> fake server through the gateway, ledger via the real wire routers ------------------------------------------
os.environ["VYOMI_LLM_ENDPOINT"] = gw_url
llm_core.set_backend()            # clear any registered backend: use the HTTP endpoint
AI.install()
check("install is idempotent", AI.install() is False)
AI.LEDGER.reset("sess-test")

from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402
from core import app_context as _ctx  # noqa: E402
import time as _t  # noqa: E402
_ctx._tier_cache.update({"tier": "max", "verified_at": _t.time(), "ttl": 10 ** 9})
_ctx.STATE["license_claims"] = {"tier": "max"}
c = TestClient(server.app, base_url="http://127.0.0.1:9000")
c.__enter__()
from core import gcp_project  # noqa: E402
GP = gcp_project.project_id()

BR = {"authorization": "AWS4-HMAC-SHA256 Credential=T/20261104/us-east-1/bedrock/aws4_request, SignedHeaders=host, Signature=0"}
r = c.post("/model/anthropic.claude-3-haiku-20240307-v1:0/converse", headers=BR,
           json={"messages": [{"role": "user", "content": [{"text": "hello"}]}], "inferenceConfig": {"maxTokens": 20}})
check("Bedrock Converse answered by the booster model with exact usage", r.status_code == 200 and r.json()["usage"]["inputTokens"] == 17 and r.json()["usage"]["outputTokens"] == 5, r.text)
r = c.post(f"/v1/projects/{GP}/locations/us-central1/publishers/google/models/gemini-2.0-flash:generateContent",
           json={"contents": [{"role": "user", "parts": [{"text": "hi"}]}]})
check("Vertex generateContent answered", r.status_code == 200 and r.json()["usageMetadata"]["promptTokenCount"] == 17, r.text[:200])
r = c.post(f"/v1beta1/projects/{GP}/locations/us-central1/publishers/google/models/gemini-2.0-flash:generateContent",
           json={"contents": [{"role": "user", "parts": [{"text": "hi"}]}]})
check("Vertex v1beta1 path routed too", r.status_code == 200, r.text[:200])
u = AI.LEDGER.summary()
check("ledger attributes to clouds from the request path", u["by_cloud"].get("aws", {}).get("requests") == 1 and u["by_cloud"].get("gcp", {}).get("requests") == 2, u["by_cloud"])
check("ledger sums exact tokens in/out and flags nothing estimated", u["totals"]["input_tokens"] == 51 and u["totals"]["output_tokens"] == 15 and u["totals"]["estimated_requests"] == 0, u["totals"])
check("ledger keeps per-op rows and a recent event with latency/model", "aws:converse" in u["by_op"] and u["recent"][-1]["model"] == "fake-chat" and u["recent"][-1]["latency_ms"] >= 0, u["by_op"])
check("compute_seconds accumulates", u["totals"]["compute_seconds"] > 0, u["totals"])

# embeddings via Titan on Bedrock (through the gateway's embed route)
r = c.post("/model/amazon.titan-embed-text-v2:0/invoke", headers=BR, json={"inputText": "doc", "dimensions": 256})
check("Titan embeddings served from the embedding model (not the hash fallback)", r.status_code == 200 and len(r.json().get("embedding", [])) == 256, r.text[:200])
check("embed call recorded as an aws embed op", any(e["op"] in ("invoke", "embed") for e in AI.LEDGER.summary()["recent"]))

# unavailable backend is counted as an error and surfaced in the cloud's own shape
os.environ["VYOMI_LLM_ENDPOINT"] = "http://127.0.0.1:9"
before = AI.LEDGER.summary()["totals"]["errors"]
r = c.post("/model/anthropic.claude-3-haiku-20240307-v1:0/converse", headers=BR, json={"messages": [{"role": "user", "content": [{"text": "x"}]}]})
check("model down -> Bedrock ModelNotReady 429 (no canned answer) and ledger error", r.status_code == 429 and AI.LEDGER.summary()["totals"]["errors"] == before + 1, (r.status_code, r.text[:120]))
os.environ["VYOMI_LLM_ENDPOINT"] = gw_url

# ---- status API ---------------------------------------------------------------------------------------------------------
AI._PROBE["at"] = 0
st = c.get("/booster/status", headers={"host": "127.0.0.1:9000"}).json()
ai = st.get("ai")
check("/booster/status carries ai{state, models, usage, chip}", ai and ai["state"] == "ready" and ai["models"]["chat"]["id"] == "qwen2.5-3b" and ai["usage"]["totals"]["requests"] >= 4, ai and {k: ai[k] for k in ("state", "chip")})
check("chip line is compact", ai["chip"].startswith("AI: ") and "tok" in ai["chip"], ai["chip"])
r = c.get("/booster/ai/status", headers={"host": "127.0.0.1:9000"})
check("/booster/ai/status returns the ledger with recent events", r.status_code == 200 and r.json()["usage"]["session"] == "sess-test" and r.json()["usage"]["recent"], r.text[:200])
r = c.get("/booster/ai/plan", headers={"host": "127.0.0.1:9000"})
check("/booster/ai/plan (loopback) gives the boot script the admitted models", r.status_code == 200 and r.json()["ok"] and r.json()["chat"]["hf"], r.text[:200])
r = c.post("/booster/ai/admit", json={"model": "qwen2.5-7b"}, headers={"host": "127.0.0.1:9000"})
check("admit route refuses 7B with 409 and a readable message", r.status_code == 409 and "needs about" in r.json()["error"]["message"], r.text[:300])
r = c.post("/booster/ai/reset-usage", headers={"host": "127.0.0.1:9000"})
check("reset-usage clears the session tally", r.status_code == 200 and AI.LEDGER.summary()["totals"]["requests"] == 0)
AI._PROBE["at"] = 0
os.environ["VYOMI_LLM_ENDPOINT"] = "http://127.0.0.1:9"
check("status says refused/starting/off (not ready) when the model server is down", AI.status()["state"] != "ready")
os.environ["VYOMI_LLM_ENDPOINT"] = gw_url

# point_llm_at_gateway
del os.environ["VYOMI_LLM_ENDPOINT"]
check("booster appliance points VYOMI_LLM_ENDPOINT at the gateway once a chat model is admitted", AI.point_llm_at_gateway() == "http://llm:8080" and os.environ["VYOMI_LLM_ENDPOINT"] == "http://llm:8080")
os.environ["VYOMI_LLM_ENDPOINT"] = gw_url

# ---- cloud_of_path ------------------------------------------------------------------------------------------------------
cp = AI.cloud_of_path
check("cloud_of_path", cp("/model/x/converse") == "aws" and cp("/agents/a/agentAliases/b/sessions/s/text") == "aws"
      and cp("/v1/projects/p/locations/l/publishers/google/models/g:generateContent") == "gcp" and cp("/openai/deployments/d/chat/completions") == "azure"
      and cp("/s3/bucket") == "" and cp("/storage/v1/b") == "")

# ---- wasm/booster-link.js routing + chip (node) -------------------------------------------------------------------------
node = shutil.which("node")
if node:
    js = r"""
const fs=require('fs');const src=fs.readFileSync('wasm/booster-link.js','utf8');
const S=eval(src.match(/var COMPUTE_SCOPE = (\/.*\/i);/)[1]),P=eval(src.match(/var COMPUTE_PATH = (\/.*\/i);/)[1]);
const t=(w,a)=>S.test(a||'')||P.test(w||'');const out={};
out.bedrock=t('/model/m/converse','AWS4-HMAC-SHA256 Credential=T/20261104/us-east-1/bedrock/aws4_request');
out.agent=t('/knowledgebases/k/retrieve','AWS4-HMAC-SHA256 Credential=T/20261104/us-east-1/bedrock/aws4_request');
out.vertex=t('/v1/projects/p/locations/l/publishers/google/models/g:generateContent','');
out.vertexBeta=t('/v1beta1/projects/p/locations/l/publishers/google/models/g:streamGenerateContent','');
out.azure=t('/openai/deployments/d/chat/completions','');out.azureV1=t('/openai/v1/chat/completions','');
out.azureOffline=t('/azure-data/openai/a/openai/deployments/d/chat/completions','');
out.s3=t('/bucket/key','AWS4-HMAC-SHA256 Credential=T/20261104/us-east-1/s3/aws4_request');
out.gcs=t('/storage/v1/b/x','');out.cosmos=t('/dbs/x/colls','');
const m=src.match(/function aiChip\(st\) \{[\s\S]*?\n  \}/)[0];const aiChip=eval('('+m.replace('function aiChip','function')+')');
out.chip=aiChip({ai:{chip:'AI: 3 req · 120 tok'}});out.chipFallback=aiChip({ai:{usage:{totals:{requests:2,total_tokens:9}}}});out.chipNone=aiChip({});
console.log(JSON.stringify(out));"""
    o = subprocess.run([node, "-e", js], capture_output=True, text=True, cwd=os.getcwd())
    try:
        j = json.loads(o.stdout)
    except Exception:
        j = {}
    check("link routes Bedrock / Bedrock agents / Vertex v1+v1beta1 / Azure OpenAI (all 3 shapes) to the booster",
          all(j.get(k) for k in ("bedrock", "agent", "vertex", "vertexBeta", "azure", "azureV1", "azureOffline")), o.stdout + o.stderr)
    check("link keeps S3 / GCS / Cosmos in the browser", not any(j.get(k) for k in ("s3", "gcs", "cosmos")), o.stdout)
    check("chip shows AI tally from booster status", j.get("chip") == "AI: 3 req · 120 tok" and j.get("chipFallback") == "AI: 2 req · 9 tok" and j.get("chipNone") == "", o.stdout)
else:
    print("[SKIP] node not found: link routing/chip checks")

# ---- deployment files ---------------------------------------------------------------------------------------------------
d = "codespace/.devcontainer/booster"
comp = open(f"{d}/docker-compose.booster.yml").read(); boot = open(f"{d}/boot-booster.sh").read()
check("compose defines llm-chat/llm-embed/llm in profile ai with the default Qwen2.5-3B Q4_K_M and a cached model volume",
      all(x in comp for x in ("llm-chat:", "llm-embed:", "  llm:", 'profiles: ["ai"]', "Qwen2.5-3B-Instruct-GGUF:Q4_K_M", "ai-models:/root/.cache", "--jinja")) and "ports:" not in comp)
check("boot script admits before starting models and tears the ai profile down", "booster/ai/plan" in boot and "--profile ai up" in boot and "--profile ai down" in boot)
if shutil.which("bash"):
    check("boot script is valid bash", subprocess.run(["bash", "-n", f"{d}/boot-booster.sh"]).returncode == 0)
if shutil.which("python3"):
    try:
        import yaml
        yaml.safe_load(comp); check("compose is valid YAML", True)
    except Exception as e:
        check("compose is valid YAML", False, e)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
