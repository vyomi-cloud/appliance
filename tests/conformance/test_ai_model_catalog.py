"""All three clouds list EXACTLY the same ten booster-mesh models (core/ai_model_catalog.py), nothing else.

Checks: Bedrock ListFoundationModels, Vertex Model Garden + Gemini-API models.list, Azure location/account model catalogue; the shared
catalogue agrees with docker/booster-runner-llm/models.json (ids + alias map) and the generated consoles JSON; availability states
(no booster -> only qwen2.5-3b available; a booster pool reports starting/ready); legacy real-vendor ids still resolve through the
hidden alias map but ids outside the ten get each cloud's own not-found/validation error.

Run: PYTHONPATH=. python3 tests/conformance/test_ai_model_catalog.py
"""
import json
import os
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core import ai_model_catalog as CAT  # noqa: E402
from core import ai_models_core as am  # noqa: E402
from core import azure_cognitiveservices_core as cs  # noqa: E402
from core import llm_core  # noqa: E402
from core.aws_wire_router import AwsWireRouter  # noqa: E402

llm_core.set_backend(lambda m, sy, mt, t, st: {"text": "echo:" + [x for x in m if x["role"] == "user"][-1]["content"]})
PASS = FAIL = 0
TEN = sorted(CAT.IDS)
OLD = ("anthropic.claude", "amazon.titan", "amazon.nova", "gemini-", "gpt-4", "gpt-35", "claude", "imagen", "text-embedding", "dall-e", "whisper")


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' - ' + str(detail)[:300] if detail and not ok else ''}")


def js(o):
    return json.loads(o["body"] or b"{}")


# ── catalogue vs the runner catalogue / generated console JSON
cat = json.load(open(os.path.join(ROOT, "docker", "booster-runner-llm", "models.json")))
check("catalogue ids == booster runner models.json ids (ten, same order)", list(cat["models"]) == CAT.IDS and len(CAT.IDS) == 10, list(cat["models"]))
check("hidden alias map == models.json aliases (all three clouds)", all(cat["aliases"][c] == CAT.ALIASES[c] for c in ("aws", "gcp", "azure")))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import gen_ai_model_catalog_json as G  # noqa: E402
cj = json.load(open(os.path.join(ROOT, "consoles", "src", "common", "ai-model-catalog.json")))
check("consoles ai-model-catalog.json is in sync (run scripts/gen_ai_model_catalog_json.py)", cj == G.doc())

# ── the three clouds list exactly the same ten
aws = [m["modelId"] for m in js(am.bedrock_dispatch("GET", "/foundation-models", {}, {}, b""))["modelSummaries"]]
check("Bedrock ListFoundationModels = the ten (vyomi.<id>)", sorted(aws) == sorted("vyomi." + i for i in CAT.IDS), aws)
R = AwsWireRouter()
AwsWireRouter.STRICT_GCP_PROJECT = False


def gcall(path):
    o = R.handle("GET", path, {}, {"content-type": "application/json"}, b"")
    return o["status"], json.loads(o["body"] or b"{}")


st, b = gcall("/v1/publishers/-/models")
gcp = [m["name"].split("/")[-1] for m in b["publisherModels"]]
check("Vertex Model Garden = the ten", st == 200 and sorted(gcp) == TEN, gcp)
o = am.vertex_dispatch("GET", "/v1beta/models", {}, {"x-goog-api-key": "k"}, b"")
check("Gemini-API models.list = the ten", sorted(m["name"].split("/")[-1] for m in js(o)["models"]) == TEN)
stt = {}
az_loc = cs.dispatch(stt, "GET", "sub1", None, ["locations", "eastus", "models"], [], {})["body"]["value"]
cs.dispatch(stt, "PUT", "sub1", "rg1", ["accounts", "o1"], [], {"kind": "OpenAI", "location": "eastus", "sku": {"name": "S0"}, "properties": {"customSubDomainName": "o1"}})
az_acct = cs.dispatch(stt, "GET", "sub1", "rg1", ["accounts", "o1", "models"], [], {})["body"]["value"]
check("Azure location model catalogue = the ten", sorted({x["model"]["name"] for x in az_loc}) == TEN)
check("Azure account model catalogue = the ten", sorted({x["model"]["name"] for x in az_acct}) == TEN)
check("same ten across AWS/GCP/Azure", sorted(a.replace("vyomi.", "") for a in aws) == sorted(gcp) == sorted({x["model"]["name"] for x in az_acct}) == TEN)
every = json.dumps([aws, gcp, [x["model"] for x in az_loc]])
check("no real-vendor model ids in any listing", not any(o in every for o in OLD), every[:200])
check("providers are the real open-model vendors", {m["vendor"] for m in CAT.MODELS} == {"Alibaba", "Nomic AI", "Meta", "Google", "DeepSeek", "Mistral AI"})

# ── availability: no booster -> only the local small model
av = {m["modelId"].replace("vyomi.", ""): m["vyomiAvailability"] for m in js(am.bedrock_dispatch("GET", "/foundation-models", {}, {}, b""))["modelSummaries"]}
check("no booster: only qwen2.5-3b available", [k for k, v in av.items() if v["available"]] == ["qwen2.5-3b"], av)
check("no booster: the other nine say 'Needs Booster (Pro/Max)'", all(v["label"] == "Needs Booster (Pro/Max)" for k, v in av.items() if k != "qwen2.5-3b") and sum(1 for k in av if k != "qwen2.5-3b") == 9)
check("Azure availability matches", {x["model"]["name"]: x["vyomiAvailability"]["available"] for x in az_acct} == {i: i == "qwen2.5-3b" for i in CAT.IDS})


class FakePool:
    def state(self, mid):
        return {"qwen2.5-7b": "ready", "llama3.1-8b": "starting"}.get(mid, "starting")


class FakeR:
    @staticmethod
    def active():
        return True

    @staticmethod
    def pool():
        return FakePool()


import core.booster_remote_llm as REAL  # noqa: E402
_a, _p = REAL.active, REAL.pool
REAL.active, REAL.pool = FakeR.active, FakeR.pool
try:
    check("booster mesh attached: pool state drives availability (ready / starting)", CAT.availability("qwen2.5-7b")["state"] == "ready" and CAT.availability("llama3.1-8b")["state"] == "starting"
          and CAT.availability("qwen2.5-7b")["available"] and not CAT.availability("mistral-7b")["available"])
finally:
    REAL.active, REAL.pool = _a, _p

# ── invoke: the ten work, legacy ids still resolve, others are the cloud's own error
body = json.dumps({"messages": [{"role": "user", "content": [{"text": "hi"}]}]}).encode()
for i in CAT.IDS:
    if CAT.BY_ID[i]["kind"] == "chat":
        o = am.bedrock_dispatch("POST", f"/model/vyomi.{i}/converse", {}, {}, body)
        if o["status"] != 200:
            check(f"Bedrock converse vyomi.{i}", False, o)
            break
else:
    check("Bedrock converse works for all nine chat models", True)
o = am.bedrock_dispatch("POST", "/model/vyomi.nomic-embed-text/invoke", {}, {}, json.dumps({"inputText": "x"}).encode())
check("Bedrock embeddings vyomi.nomic-embed-text -> 768 dims", o["status"] == 200 and len(js(o)["embedding"]) == 768, o)
check("legacy Bedrock id (anthropic.claude / amazon.nova) still invokes (hidden alias)",
      all(am.bedrock_dispatch("POST", f"/model/{m}/converse", {}, {}, body)["status"] == 200 for m in ("amazon.nova-lite-v1:0", "anthropic.claude-3-haiku-20240307-v1:0")))
o = am.bedrock_dispatch("POST", "/model/some.unknown-model/converse", {}, {}, body)
check("Bedrock id outside the ten -> ValidationException", o["status"] == 400 and o["headers"]["x-amzn-errortype"] == "ValidationException")
check("Bedrock GetFoundationModel of a legacy id -> ResourceNotFound", am.bedrock_dispatch("GET", "/foundation-models/anthropic.claude-3-haiku-20240307-v1:0", {}, {}, b"")["status"] == 404)
gb = json.dumps({"contents": [{"role": "user", "parts": [{"text": "hi"}]}]}).encode()
P = "/v1/projects/p/locations/us-central1/publishers"
check("Vertex generateContent works on every chat model id", all(am.vertex_dispatch("POST", f"{P}/{CAT.BY_ID[i]['publisher']}/models/{i}:generateContent", {}, {}, gb)["status"] == 200 for i in CAT.IDS if CAT.BY_ID[i]["kind"] == "chat"))
check("Vertex legacy gemini-2.0-flash still resolves (hidden alias)", am.vertex_dispatch("POST", f"{P}/google/models/gemini-2.0-flash:generateContent", {}, {}, gb)["status"] == 200)
o = am.vertex_dispatch("POST", f"{P}/google/models/claude-sonnet-4:generateContent", {}, {}, gb)
check("Vertex id outside the ten -> 404 NOT_FOUND", o["status"] == 404 and js(o)["error"]["status"] == "NOT_FOUND")
r = cs.dispatch(stt, "PUT", "sub1", "rg1", ["accounts", "o1", "deployments", "d1"], [], {"sku": {"name": "Standard", "capacity": 1}, "properties": {"model": {"format": "OpenAI", "name": "claude-3", "version": "1"}}})
check("Azure deployment of an id outside the ten -> DeploymentModelNotSupported", r["body"]["error"]["code"] == "DeploymentModelNotSupported")
print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
