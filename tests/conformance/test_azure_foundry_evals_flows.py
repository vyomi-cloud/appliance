"""Azure OpenAI Evals API (openai SDK client.evals) + Microsoft Foundry Prompt flow (flow.dag.yaml run on the Bedrock Flows runner), lane limflows.
Run: PYTHONPATH=. CLOUDLEARN_STATE_FILE=/tmp/x.sqlite3 /private/tmp/ai-probe-venv13/bin/python tests/conformance/test_azure_foundry_evals_flows.py
The judge is the local model: here a deterministic rule stand-in (monkeypatched llm_core.chat) so the grading pipeline is verifiable; it is NOT a quality claim."""
import asyncio, json, os, re, socket, sys, threading, time, urllib.request

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools", "llm_stub"))
import stub_llm_server  # noqa: E402
os.environ["VYOMI_LLM_ENDPOINT"] = stub_llm_server.start()
os.environ.setdefault("CLOUDLEARN_STATE_FILE", "/tmp/azure-foundry-evals-test.sqlite3")
import anyio, openai, uvicorn  # noqa: E402
from fastapi import FastAPI, Request  # noqa: E402
from core import llm_core, wire_ingress  # noqa: E402
from core.aws_wire_router import AwsWireRouter  # noqa: E402
from core.azure_arm_core import AzureArm  # noqa: E402

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' - ' + str(detail)[:300] if detail and not ok else ''}")


_real = llm_core.chat
CAPITALS = {"Capital of France?": "Paris", "Capital of Spain?": "Madrid", "Capital of Italy?": "Milan"}


def fake_chat(messages, *a, **k):
    text = messages[-1]["content"] if isinstance(messages[-1]["content"], str) else str(messages[-1]["content"])
    m = re.search(r"Question: (.*)", text)
    if text.startswith("You are an impartial grader."):
        if "Choose exactly one label" in text:
            ans = "correct" if re.search(r"Answer: (Paris|Madrid)", text) else "wrong"
            return {"text": json.dumps({"reasoning": "rule", "answer": ans})}
        sc = 0.9 if re.search(r"Answer: (Paris|Madrid)", text) else 0.2
        return {"text": json.dumps({"reasoning": "rule", "score": sc})}
    if "You are a geography bot" in " ".join(str(x.get("content")) for x in messages):
        q = messages[-1]["content"]
        return {"text": CAPITALS.get(q, "unknown")}
    if "TRANSLATE" in text:
        return {"text": "Bonjour " + text.split("TRANSLATE")[-1].strip()}
    return _real(messages, *a, **k)


llm_core.chat = fake_chat

router = AwsWireRouter()
router.az_arm = AzureArm()
base = "/subscriptions/00000000-0000-0000-0000-cloudlearn01/resourceGroups/rg1/providers/Microsoft.CognitiveServices/accounts/oai1"
router.az_arm.handle("PUT", base, {"api-version": "2024-10-01"}, {"kind": "OpenAI", "location": "eastus", "sku": {"name": "S0"}})
router.az_arm.handle("PUT", base + "/deployments/chat", {"api-version": "2024-10-01"}, {"sku": {"name": "Standard", "capacity": 1}, "properties": {"model": {"format": "OpenAI", "name": "gpt-4o", "version": "2024-11-20"}}})
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
cl = openai.AzureOpenAI(api_key="k", api_version="2025-04-01-preview", azure_endpoint=url, max_retries=0)


def http(method, path, body=None):
    rq = urllib.request.Request(url + path, data=json.dumps(body).encode() if body is not None else None, method=method, headers={"api-key": "k", "content-type": "application/json"})
    try:
        return json.loads(urllib.request.urlopen(rq).read() or b"{}")
    except urllib.error.HTTPError as e:
        return {"_status": e.code, **json.loads(e.read() or b"{}")}


def wait(eid, rid, secs=60):
    t = time.time()
    while time.time() - t < secs:
        r = cl.evals.runs.retrieve(rid, eval_id=eid)
        if r.status != "in_progress":
            return r
        time.sleep(0.2)
    return r


# ── Evals
schema = {"type": "object", "properties": {"q": {"type": "string"}, "a": {"type": "string"}}, "required": ["q", "a"]}
ev = cl.evals.create(name="capitals", data_source_config={"type": "custom", "item_schema": schema, "include_sample_schema": True},
                     testing_criteria=[{"type": "string_check", "name": "exact", "input": "{{sample.output_text}}", "operation": "eq", "reference": "{{item.a}}"},
                                       {"type": "text_similarity", "name": "rouge", "input": "{{sample.output_text}}", "reference": "{{item.a}}", "evaluation_metric": "rouge_l", "pass_threshold": 0.8},
                                       {"type": "label_model", "name": "judge", "model": "chat", "input": [{"role": "user", "content": "Question: {{item.q}} Answer: {{sample.output_text}}"}], "labels": ["correct", "wrong"], "passing_labels": ["correct"]},
                                       {"type": "score_model", "name": "scored", "model": "chat", "input": [{"role": "user", "content": "Question: {{item.q}} Answer: {{sample.output_text}}"}], "range": [0, 1], "pass_threshold": 0.5}])
check("openai client.evals.create returns an eval object with criteria ids", ev.object == "eval" and ev.id.startswith("eval_") and len(ev.testing_criteria) == 4)
items = [{"q": q, "a": a} for q, a in (("Capital of France?", "Paris"), ("Capital of Spain?", "Madrid"), ("Capital of Italy?", "Rome"))]
run = cl.evals.runs.create(ev.id, name="r1", data_source={"type": "completions", "model": "chat", "input_messages": {"type": "template", "template": [{"role": "developer", "content": "You are a geography bot"}, {"role": "user", "content": "{{item.q}}"}]},
                                                          "source": {"type": "file_content", "content": [{"item": i} for i in items]}})
r = wait(ev.id, run.id)
check("run completes; 3 items counted", r.status == "completed" and r.result_counts.total == 3, r)
pc = {x.testing_criteria: (x.passed, x.failed) for x in r.per_testing_criteria_results}
check("exact: Paris, Madrid pass / Milan fails (2,1)", pc["exact"] == (2, 1), pc)
check("rouge_l threshold 0.8 matches exact here (2,1)", pc["rouge"] == (2, 1), pc)
check("label_model judge (rule stand-in) passes 2 of 3", pc["judge"] == (2, 1), pc)
check("score_model with pass_threshold 0.5 passes 2 of 3", pc["scored"] == (2, 1), pc)
check("run result_counts: passed 2, failed 1", r.result_counts.passed == 2 and r.result_counts.failed == 1, r.result_counts)
oi = list(cl.evals.runs.output_items.list(r.id, eval_id=ev.id))
check("output_items list: 3 items with per-criterion results and the sample output", len(oi) == 3 and oi[0].results and all(i.sample for i in oi), oi[:1])
fl = list(cl.evals.runs.output_items.list(r.id, eval_id=ev.id, status="fail"))
check("output_items filter status=fail returns Milan only", len(fl) == 1 and fl[0].datasource_item["a"] == "Rome", fl)
g = cl.evals.runs.output_items.retrieve(oi[0].id, eval_id=ev.id, run_id=r.id)
check("output_items.retrieve by id", g.id == oi[0].id)
r2 = cl.evals.runs.create(ev.id, name="static", data_source={"type": "jsonl", "source": {"type": "file_content", "content": [{"item": {"q": "x", "a": "y"}, "sample": {"output_text": "y"}}, {"item": {"q": "x", "a": "y"}, "sample": {"output_text": "z"}}]}})
r2 = wait(ev.id, r2.id)
check("jsonl source with precomputed sample.output_text grades without a model", r2.status == "completed" and r2.result_counts.total == 2 and r2.result_counts.errored == 0, r2.result_counts)   # an item passes only if ALL graders pass; the rule judge rejects "y"
pcs = {x.testing_criteria: x.passed for x in r2.per_testing_criteria_results}
check("static run: exact passes the matching row", pcs["exact"] == 1, pcs)
big = [{"item": {"q": f"q{i}", "a": "y"}, "sample": {"output_text": "y"}} for i in range(60)]
ev2 = cl.evals.create(name="big", data_source_config={"type": "custom", "item_schema": schema}, testing_criteria=[{"type": "string_check", "name": "exact", "input": "{{sample.output_text}}", "operation": "eq", "reference": "{{item.a}}"}])
rb = cl.evals.runs.create(ev2.id, data_source={"type": "jsonl", "source": {"type": "file_content", "content": big}})
pg = (rb.to_dict().get("vyomiProgress") or {})
check("60-item run reports progress (Vyomi extension vyomiProgress)", pg.get("totalItems") == 60 and rb.status in ("in_progress", "completed"), pg)
rb = wait(ev2.id, rb.id)
check("60-item run completes in batches with all items graded", rb.status == "completed" and rb.result_counts.passed == 60, rb.result_counts)
b2 = cl.evals.create(name="bad", data_source_config={"type": "custom", "item_schema": schema}, testing_criteria=[{"type": "string_check", "name": "e", "input": "a", "operation": "eq", "reference": "a"}])
huge = [{"item": {"q": "x", "a": "y"}, "sample": {"output_text": "y"}}] * 1001
try:
    cl.evals.runs.create(b2.id, data_source={"type": "jsonl", "source": {"type": "file_content", "content": huge}})
    check("over 1000 rows -> 400", False)
except openai.BadRequestError as e:
    check("over 1000 rows -> 400", "1000" in str(e))
try:
    cl.evals.create(name="py", data_source_config={"type": "custom", "item_schema": schema}, testing_criteria=[{"type": "python", "name": "p", "source": "def grade(): pass"}])
    check("python grader rejected", False)
except openai.BadRequestError as e:
    check("python grader rejected with a clear message", "python" in str(e).lower())
try:
    cl.evals.create(name="logs", data_source_config={"type": "logs", "metadata": {}}, testing_criteria=[{"type": "string_check", "name": "e", "input": "a", "operation": "eq", "reference": "a"}])
    check("logs data source rejected", False)
except openai.BadRequestError:
    check("logs / stored_completions data source rejected", True)
try:
    cl.evals.runs.create(ev.id, data_source={"type": "completions", "model": "nope", "input_messages": {"type": "template", "template": [{"role": "user", "content": "{{item.q}}"}]}, "source": {"type": "file_content", "content": [{"item": items[0]}]}})
    rr = [x for x in cl.evals.runs.list(ev.id)][0]
    rr = wait(ev.id, rr.id)
    check("unknown deployment: run fails with DeploymentNotFound", rr.status == "failed" and "DeploymentNotFound" in json.dumps(rr.error.to_dict()), rr.error)
except openai.OpenAIError as e:
    check("unknown deployment: run fails with DeploymentNotFound", "DeploymentNotFound" in str(e) or "nope" in str(e), e)
check("list evals / runs", [e.name for e in cl.evals.list()][:1] and len(list(cl.evals.runs.list(ev.id))) >= 2)
cl.evals.delete(ev2.id)
check("delete eval", all(e.id != ev2.id for e in cl.evals.list()))

# ── Prompt flow (flow.dag.yaml shape on the Bedrock Flows runner)
flow = {"inputs": {"text": {"type": "string", "default": "world"}, "lang": {"type": "string"}},
        "outputs": {"answer": {"type": "string", "reference": "${chat.output}"}, "prompt_used": {"type": "string", "reference": "${build.output}"}},
        "nodes": [{"name": "build", "type": "prompt", "source": {"type": "code", "path": "build.jinja2"}, "inputs": {"text": "${inputs.text}", "lang": "${inputs.lang}"}},
                  {"name": "chat", "type": "llm", "source": {"type": "code", "path": "chat.jinja2"}, "inputs": {"deployment_name": "chat", "temperature": 0, "task": "${build.output}"}, "api": "chat", "connection": "aoai"}],
        "files": {"build.jinja2": "TRANSLATE {{text}} into {{lang}}", "chat.jinja2": "system:\nYou translate.\n\nuser:\n{{task}}\n"}}
pf = http("POST", "/openai/vyomi/promptflow/flows", {"name": "translate", "flow": flow})
check("create prompt flow (Vyomi extension on the Azure OpenAI data plane)", pf.get("name") == "translate" and pf.get("vyomiExtension") is True, pf)
t = http("POST", "/openai/vyomi/promptflow/flows/translate/test", {"inputs": {"text": "world", "lang": "French"}})
check("flow test: prompt node renders, llm node runs on the deployment, outputs map by name", t.get("outputs", {}).get("prompt_used") == "TRANSLATE world into French" and "Bonjour" in t["outputs"].get("answer", ""), t)
nodes = [(x["node"], x["event"]) for x in t.get("trace", [])]
check("flow test returns a per-node trace (build then chat)", ("build", "output") in nodes and ("chat", "output") in nodes and nodes.index(("build", "output")) < nodes.index(("chat", "output")), nodes)
sc = http("POST", "/openai/vyomi/promptflow/flows/translate/score", {"text": "dog", "lang": "French"})
check("score endpoint (managed-online-endpoint contract) returns the outputs object", "answer" in sc and "Bonjour" in sc["answer"], sc)
d = http("POST", "/openai/vyomi/promptflow/flows/translate/score", {"lang": "French"})
check("input defaults apply (text defaults to 'world')", d.get("prompt_used") == "TRANSLATE world into French", d)
m = http("POST", "/openai/vyomi/promptflow/flows/translate/score", {"text": "x"})
check("missing input -> 400 naming it", m.get("_status") == 400 and "lang" in json.dumps(m), m)
py = dict(flow, nodes=flow["nodes"] + [{"name": "py", "type": "python", "source": {"type": "code", "path": "p.py"}, "inputs": {}}], files={**flow["files"], "p.py": "x"})
r_ = http("POST", "/openai/vyomi/promptflow/flows", {"name": "withpy", "flow": py})
check("python tool nodes rejected with the reason", r_.get("_status") == 400 and "python" in json.dumps(r_).lower(), r_)
nodep = dict(flow, nodes=[dict(flow["nodes"][1], inputs={"deployment_name": "nope", "task": "${inputs.text}"})], outputs={"answer": {"type": "string", "reference": "${chat.output}"}})
http("POST", "/openai/vyomi/promptflow/flows", {"name": "nodep", "flow": nodep})
nd = http("POST", "/openai/vyomi/promptflow/flows/nodep/score", {"text": "x", "lang": "fr"})
check("unknown deployment_name -> DeploymentNotFound", "DeploymentNotFound" in json.dumps(nd) or nd.get("_status") in (400, 404, 500), nd)
check("list flows shows inputs/outputs/nodes", [f for f in http("GET", "/openai/vyomi/promptflow/flows")["data"] if f["name"] == "translate"][0]["nodes"] == 2)
http("PUT", "/openai/vyomi/promptflow/flows/translate", {"description": "d"})
check("update + get flow", http("GET", "/openai/vyomi/promptflow/flows/translate")["description"] == "d")
http("DELETE", "/openai/vyomi/promptflow/flows/translate")
check("delete flow", http("GET", "/openai/vyomi/promptflow/flows/translate").get("_status") == 404)
print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
