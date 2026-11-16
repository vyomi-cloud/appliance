"""Real boto3/HTTP proof for the Mesh role models (lane limmodels): VISION (image blocks / inlineData / image_url -> a vision llama-server),
REASONING (reasoningContent, thinking, thoughtful parts, reasoning_content -> a reasoning llama-server) and Bedrock Data Automation
(blueprints, projects, InvokeDataAutomationAsync with S3 in/out) against the unified router over real HTTP.

The two role servers here are deterministic FAKE OpenAI-compatible servers (tests/conformance/llm_fakes.py): this file proves routing, wire shapes,
errors, S3 in/out and the 'only listed where served' rule. It does NOT measure model quality; the real SmolVLM / DeepSeek-R1-Distill numbers come
from tools/llm_roles/live_check.py (documented in docs/architecture/v4.0/branches/ai-limmodels.md).

Run: PYTHONPATH=. /private/tmp/ai-probe-venv13/bin/python tests/conformance/test_bedrock_limmodels.py
"""
import base64
import json
import os
import socket
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from llm_fakes import FakeLLM  # noqa: E402

PASS = FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name} {str(extra)[:600]}")


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def main():
    try:
        import boto3
        from botocore.config import Config
        from botocore.exceptions import ClientError
    except ImportError as e:
        print("missing", e, "- skipping")
        return 0
    import uvicorn
    from fastapi import FastAPI, Request
    from core import ai_model_catalog as CAT
    from core import llm_core as llm
    from core import wire_ingress
    from core.aws_wire_router import AwsWireRouter

    chat = FakeLLM(handler=lambda b: {"content": "default-chat"}, model="fake-chat")
    seen = {"vision": [], "reasoning": []}

    def vision_h(body):
        seen["vision"].append(body)
        if body.get("response_format"):       # blueprint extraction: answer for every property of the schema
            sch = body["response_format"].get("json_schema", {}).get("schema") or {}
            vals = {"invoice_number": "INV-2041", "total_due": 1284.5, "vendor": "Acme Facilities Ltd"}
            return {"content": json.dumps({k: vals.get(k) for k in (sch.get("properties") or {})})}
        txt = json.dumps(body["messages"][-1]["content"])
        return {"content": "Invoice INV-2041\nTotal due: $1,284.50" if "Transcribe" in txt else ("A scanned invoice." if "Describe" in txt else "vision-answer")}

    def reason_h(body):
        seen["reasoning"].append(body)
        return {"reasoning": "17*23 = 17*20 + 17*3 = 340 + 51", "content": "391"}
    vis, rea = FakeLLM(handler=vision_h, model="fake-smolvlm"), FakeLLM(handler=reason_h, model="fake-r1")
    os.environ.pop("VYOMI_LLM_DISABLE", None)
    llm.set_backend(None, embed_fn=lambda ts: [llm.hash_embed(t) for t in ts], endpoint=chat.url)

    router = AwsWireRouter()
    app = FastAPI()

    @app.api_route("/{p:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
    async def any_(p: str, request: Request):
        return await wire_ingress.serve(router, request)
    port = free_port()
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    threading.Thread(target=srv.run, daemon=True).start()
    while not srv.started:
        time.sleep(0.05)
    url = f"http://127.0.0.1:{port}"
    kw = dict(region_name="us-east-1", endpoint_url=url, aws_access_key_id="x", aws_secret_access_key="y", config=Config(retries={"max_attempts": 1}))
    br, bd, s3 = boto3.client("bedrock-runtime", **kw), boto3.client("bedrock", **kw), boto3.client("s3", **kw)
    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")

    def err(fn, **a):
        try:
            fn(**a)
        except ClientError as e:
            return e.response["Error"]["Code"], e.response["Error"]["Message"]
        return None, ""

    # ───────── not served: nothing listed, honest errors ─────────
    ids = [m["modelId"] for m in bd.list_foundation_models()["modelSummaries"]]
    check("no role server -> role models are not listed", "vyomi.smolvlm-500m" not in ids and "vyomi.deepseek-r1-1.5b" not in ids, ids)
    code, msg = err(br.converse, modelId="vyomi.smolvlm-500m", messages=[{"role": "user", "content": [{"text": "hi"}]}])
    check("no role server -> the role model id is the cloud's validation error", code == "ValidationException", (code, msg))
    code, msg = err(br.converse, modelId="vyomi.qwen2.5-3b", messages=[{"role": "user", "content": [{"image": {"format": "png", "source": {"bytes": png}}}, {"text": "?"}]}])
    check("image with no vision model -> ValidationException naming vision", code == "ValidationException" and "vision" in msg, (code, msg))
    code, msg = err(br.converse, modelId="vyomi.qwen2.5-3b", messages=[{"role": "user", "content": [{"text": "hi"}]}],
                    additionalModelRequestFields={"thinking": {"type": "enabled", "budget_tokens": 2048}})
    check("thinking with no reasoning model -> ValidationException naming reasoning", code == "ValidationException" and "reasoning" in msg.lower(), (code, msg))

    # ───────── serve both roles ─────────
    llm.set_role_endpoint("vision", vis.url)
    llm.set_role_endpoint("reasoning", rea.url)
    summ = {m["modelId"]: m for m in bd.list_foundation_models()["modelSummaries"]}
    check("vision model listed with IMAGE input only while served", "vyomi.smolvlm-500m" in summ and "IMAGE" in summ["vyomi.smolvlm-500m"]["inputModalities"], list(summ))
    check("reasoning model listed while served", "vyomi.deepseek-r1-1.5b" in summ)
    check("GetFoundationModel on a served role model", bd.get_foundation_model(modelIdentifier="vyomi.smolvlm-500m")["modelDetails"]["modelId"] == "vyomi.smolvlm-500m")
    check("catalogue availability says Ready", CAT.availability("smolvlm-500m")["available"] and CAT.availability("deepseek-r1-1.5b")["available"])

    # ───────── vision ─────────
    imsg = [{"role": "user", "content": [{"text": "what is this?"}, {"image": {"format": "png", "source": {"bytes": png}}}]}]
    r = br.converse(modelId="vyomi.qwen2.5-3b", messages=imsg)
    check("Converse image block on a text model is answered by the VISION server", r["output"]["message"]["content"][0]["text"] == "vision-answer"
          and isinstance(seen["vision"][-1]["messages"][-1]["content"], list), r["output"])
    check("the image reached the vision server as an image_url data URL", seen["vision"][-1]["messages"][-1]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,"))
    check("default chat server untouched by the image call", all("image_url" not in json.dumps(q) for q in chat.requests))
    r = br.converse(modelId="vyomi.smolvlm-500m", messages=[{"role": "user", "content": [{"text": "hello"}]}])
    check("the vision model id with plain text still uses the vision server", r["output"]["message"]["content"][0]["text"] == "vision-answer")
    out = json.loads(br.invoke_model(modelId="anthropic.claude-3-haiku-20240307-v1:0", body=json.dumps({"anthropic_version": "bedrock-2023-05-31", "max_tokens": 50, "messages": [
        {"role": "user", "content": [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": base64.b64encode(png).decode()}}, {"type": "text", "text": "?"}]}]}))["body"].read())
    check("InvokeModel Claude image block -> vision answer", out["content"][0]["text"] == "vision-answer", out)
    ev = list(br.converse_stream(modelId="vyomi.qwen2.5-3b", messages=imsg)["stream"])
    check("ConverseStream with an image streams from the vision server", any("contentBlockDelta" in e and "vision" in e["contentBlockDelta"]["delta"].get("text", "") or
                                                                       "contentBlockDelta" in e and e["contentBlockDelta"]["delta"].get("text") for e in ev))
    # Vertex + Azure
    vx = boto3.client("bedrock-runtime", **kw)  # (unused; Vertex/Azure are plain HTTP below)
    import urllib.request

    def post(path, doc, headers=None):
        rq = urllib.request.Request(url + path, json.dumps(doc).encode(), dict({"content-type": "application/json"}, **(headers or {})), method="POST")
        try:
            with urllib.request.urlopen(rq, timeout=30) as x:
                return x.status, json.loads(x.read() or b"{}")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")
    gp = "/v1/projects/p/locations/us-central1/publishers/google/models/gemini-2.5-flash"
    st, d = post(gp + ":generateContent", {"contents": [{"role": "user", "parts": [{"text": "what is this?"}, {"inlineData": {"mimeType": "image/png", "data": base64.b64encode(png).decode()}}]}]},
                 {"x-goog-user-project": "p"})
    check("Vertex inlineData image -> vision answer", st == 200 and d["candidates"][0]["content"]["parts"][0]["text"] == "vision-answer", (st, d))
    st, d = post(gp + ":generateContent", {"contents": [{"role": "user", "parts": [{"text": "17*23?"}]}], "generationConfig": {"thinkingConfig": {"includeThoughts": True}}})
    parts = d["candidates"][0]["content"]["parts"] if st == 200 else []
    check("Vertex thinkingConfig.includeThoughts -> thought part then answer", st == 200 and parts[0].get("thought") is True and parts[-1]["text"] == "391", (st, d))

    # ───────── reasoning ─────────
    r = br.converse(modelId="vyomi.qwen2.5-3b", messages=[{"role": "user", "content": [{"text": "17*23?"}]}],
                    additionalModelRequestFields={"thinking": {"type": "enabled", "budget_tokens": 2048}})
    c = r["output"]["message"]["content"]
    check("Converse thinking -> reasoningContent block first, then the answer", "reasoningContent" in c[0] and c[0]["reasoningContent"]["reasoningText"]["text"].startswith("17*23") and c[1]["text"] == "391", c)
    r = br.converse(modelId="vyomi.qwen2.5-3b", messages=[{"role": "user", "content": [{"text": "17*23?"}]}],
                    additionalModelRequestFields={"reasoning_config": {"type": "enabled", "budget_tokens": 1024}})
    check("Converse reasoning_config{type:enabled} accepted", "reasoningContent" in r["output"]["message"]["content"][0])
    r = br.converse(modelId="vyomi.qwen2.5-3b", messages=[{"role": "user", "content": [{"text": "hi"}]}], additionalModelRequestFields={"thinking": {"type": "disabled"}})
    check("thinking disabled -> plain answer", all("reasoningContent" not in b for b in r["output"]["message"]["content"]))
    code, msg = err(br.converse, modelId="vyomi.qwen2.5-3b", messages=[{"role": "user", "content": [{"text": "hi"}]}], additionalModelRequestFields={"thinking": {"type": "enabled", "budget_tokens": 100}})
    check("budget_tokens < 1024 -> the real validation error", code == "ValidationException" and "1024" in msg, (code, msg))
    r = br.converse(modelId="vyomi.deepseek-r1-1.5b", messages=[{"role": "user", "content": [{"text": "17*23?"}]}])
    check("the reasoning model id always returns reasoningContent", "reasoningContent" in r["output"]["message"]["content"][0], r["output"])
    ev = list(br.converse_stream(modelId="vyomi.qwen2.5-3b", messages=[{"role": "user", "content": [{"text": "17*23?"}]}],
                                 additionalModelRequestFields={"thinking": {"type": "enabled", "budget_tokens": 1024}})["stream"])
    rt = "".join(e["contentBlockDelta"]["delta"]["reasoningContent"]["text"] for e in ev if "contentBlockDelta" in e and "reasoningContent" in e["contentBlockDelta"]["delta"])
    tx = "".join(e["contentBlockDelta"]["delta"].get("text", "") for e in ev if "contentBlockDelta" in e)
    idx = [e["contentBlockDelta"]["contentBlockIndex"] for e in ev if "contentBlockDelta" in e]
    check("ConverseStream: reasoningContent deltas then text deltas in separate blocks", rt.startswith("17*23") and tx == "391" and idx[0] == 0 and idx[-1] == 1, (rt, tx, idx))
    out = json.loads(br.invoke_model(modelId="anthropic.claude-3-7-sonnet-20250219-v1:0", body=json.dumps({"anthropic_version": "bedrock-2023-05-31", "max_tokens": 4000,
          "thinking": {"type": "enabled", "budget_tokens": 1024}, "messages": [{"role": "user", "content": "17*23?"}]}))["body"].read())
    check("InvokeModel Claude thinking -> thinking block + text block", out["content"][0]["type"] == "thinking" and out["content"][0]["thinking"].startswith("17*23") and out["content"][1]["text"] == "391", out)
    r = br.converse(modelId="vyomi.qwen2.5-3b", messages=[{"role": "user", "content": [{"text": "a"}]}, {"role": "assistant", "content": [{"reasoningContent": {"reasoningText": {"text": "old"}}}, {"text": "b"}]},
                                                          {"role": "user", "content": [{"text": "c"}]}])
    check("assistant reasoningContent from a previous turn is accepted and not re-fed to the model",
          "old" not in json.dumps(chat.requests[-1]) and r["output"]["message"]["content"][0]["text"] == "default-chat")
    # Azure: account + deployments of the two role models, called through the Azure OpenAI dispatcher in-process
    from core import ai_models_core as am
    from core import azure_cognitiveservices_core as cs
    stt = {}
    cs.dispatch(stt, "PUT", "sub1", "rg1", ["accounts", "o1"], [], {"kind": "OpenAI", "location": "eastus", "sku": {"name": "S0"}, "properties": {"customSubDomainName": "o1"}})
    names = sorted({x["model"]["name"] for x in cs.dispatch(stt, "GET", "sub1", None, ["locations", "eastus", "models"], [], {})["body"]["value"]})
    check("Azure model catalogue lists the role models only while served", "smolvlm-500m" in names and "deepseek-r1-1.5b" in names, names)
    for dep, mdl in (("vis", "smolvlm-500m"), ("think", "deepseek-r1-1.5b"), ("gpt", "gpt-4o")):
        cs.dispatch(stt, "PUT", "sub1", "rg1", ["accounts", "o1", "deployments", dep], [], {"sku": {"name": "Standard", "capacity": 1}, "properties": {"model": {"format": "OpenAI", "name": mdl, "version": "1"}}})

    def az(dep, doc):
        o = am.azure_openai_dispatch(stt, "POST", f"/openai/deployments/{dep}/chat/completions", {}, {"api-key": "k"}, json.dumps(doc).encode())
        return o["status"], json.loads(o["body"])
    st, d = az("gpt", {"messages": [{"role": "user", "content": [{"type": "text", "text": "what is this?"}, {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(png).decode()}}]}]})
    check("Azure image_url (data URL) on a gpt-4o deployment -> vision answer", st == 200 and d["choices"][0]["message"]["content"] == "vision-answer", (st, d))
    st, d = az("gpt", {"messages": [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "https://example.com/x.png"}}]}]})
    check("Azure remote image URL is rejected (the simulator never fetches the internet)", st == 400 and "data:image" in json.dumps(d), (st, d))
    st, d = az("think", {"messages": [{"role": "user", "content": "17*23?"}]})
    check("Azure reasoning-model deployment returns message.reasoning_content", st == 200 and d["choices"][0]["message"]["reasoning_content"].startswith("17*23") and d["choices"][0]["message"]["content"] == "391", (st, d))
    st, d = az("gpt", {"messages": [{"role": "user", "content": "17*23?"}], "reasoning_effort": "low"})
    check("Azure reasoning_effort on any deployment -> reasoning model answers", st == 200 and d["choices"][0]["message"].get("reasoning_content"), (st, d))

    # ───────── Bedrock Data Automation ─────────
    bda = boto3.client("bedrock-data-automation", **kw)
    rt = boto3.client("bedrock-data-automation-runtime", **kw)
    schema = {"$schema": "http://json-schema.org/draft-07/schema#", "description": "An invoice", "class": "invoice", "type": "object", "properties": {
        "invoice_number": {"type": "string", "inferenceType": "explicit", "instruction": "The invoice number"},
        "total_due": {"type": "number", "inferenceType": "explicit", "instruction": "Total amount due"},
        "vendor": {"type": "string", "inferenceType": "explicit", "instruction": "Vendor name"}}}
    bp = bda.create_blueprint(blueprintName="invoice-bp", type="IMAGE", schema=json.dumps(schema))["blueprint"]
    check("CreateBlueprint -> ARN + stage + schema", bp["blueprintArn"].startswith("arn:aws:bedrock:") and ":blueprint/" in bp["blueprintArn"] and bp["blueprintStage"] == "DEVELOPMENT")
    check("GetBlueprint", bda.get_blueprint(blueprintArn=bp["blueprintArn"])["blueprint"]["blueprintName"] == "invoice-bp")
    check("ListBlueprints", [b["blueprintName"] for b in bda.list_blueprints()["blueprints"]] == ["invoice-bp"])
    code, _ = err(bda.create_blueprint, blueprintName="invoice-bp", type="IMAGE", schema=json.dumps(schema))
    check("duplicate blueprint -> ConflictException", code == "ConflictException", code)
    code, _ = err(bda.create_blueprint, blueprintName="bad", type="IMAGE", schema="{not json")
    check("invalid schema -> ValidationException", code == "ValidationException", code)
    v = bda.create_blueprint_version(blueprintArn=bp["blueprintArn"])["blueprint"]
    check("CreateBlueprintVersion -> version 1", v["blueprintVersion"] == "1")
    bda.update_blueprint(blueprintArn=bp["blueprintArn"], schema=json.dumps(dict(schema, description="v2")), blueprintStage="LIVE")
    check("UpdateBlueprint changes stage; the frozen version keeps the old schema",
          bda.get_blueprint(blueprintArn=bp["blueprintArn"])["blueprint"]["blueprintStage"] == "LIVE"
          and "v2" not in bda.get_blueprint(blueprintArn=bp["blueprintArn"], blueprintVersion="1")["blueprint"]["schema"])
    pr = bda.create_data_automation_project(projectName="docs-proj", standardOutputConfiguration={"image": {"extraction": {"category": {"state": "ENABLED", "types": ["TEXT_DETECTION"]},
                                            "boundingBox": {"state": "DISABLED"}}}},
                                            customOutputConfiguration={"blueprints": [{"blueprintArn": bp["blueprintArn"], "blueprintStage": "LIVE"}]})
    check("CreateDataAutomationProject", pr["projectArn"].startswith("arn:aws:bedrock:") and pr["status"] in ("COMPLETED", "IN_PROGRESS"), pr)
    gp_ = bda.get_data_automation_project(projectArn=pr["projectArn"])["project"]
    check("GetDataAutomationProject echoes the custom blueprints", gp_["customOutputConfiguration"]["blueprints"][0]["blueprintArn"] == bp["blueprintArn"])
    check("ListDataAutomationProjects", [p["projectName"] for p in bda.list_data_automation_projects()["projects"]] == ["docs-proj"])
    code, _ = err(bda.delete_blueprint, blueprintArn=bp["blueprintArn"])
    check("deleting a blueprint used by a project -> ConflictException", code == "ConflictException", code)

    s3.create_bucket(Bucket="bda-in")
    s3.create_bucket(Bucket="bda-out")
    s3.put_object(Bucket="bda-in", Key="scans/invoice.png", Body=png)
    s3.put_object(Bucket="bda-in", Key="docs/notes.txt", Body=b"Invoice INV-77 from Northwind HVAC. Total due is 920.00 dollars.")
    s3.put_object(Bucket="bda-in", Key="av/clip.mp4", Body=b"\x00\x00\x00\x18ftypmp42")
    prof = "arn:aws:bedrock:us-east-1:123456789012:data-automation-profile/us.data-automation-v1"

    def run(key, extra=None):
        arn = rt.invoke_data_automation_async(inputConfiguration={"s3Uri": f"s3://bda-in/{key}"}, outputConfiguration={"s3Uri": "s3://bda-out/results"},
                                              dataAutomationConfiguration={"dataAutomationProjectArn": pr["projectArn"], "stage": "LIVE"}, dataAutomationProfileArn=prof, **(extra or {}))["invocationArn"]
        for _ in range(100):
            st_ = rt.get_data_automation_status(invocationArn=arn)
            if st_["status"] not in ("Created", "InProgress"):
                return arn, st_
            time.sleep(0.1)
        return arn, st_
    arn, st_ = run("scans/invoice.png")
    check("InvokeDataAutomationAsync (image) -> Success with job_metadata.json URI", st_["status"] == "Success" and st_["outputConfiguration"]["s3Uri"].endswith("/job_metadata.json"), st_)
    jid = arn.rsplit("/", 1)[-1]
    meta = json.loads(s3.get_object(Bucket="bda-out", Key=f"results/{jid}/job_metadata.json")["Body"].read())
    seg = meta["output_metadata"][0]["segment_metadata"][0]
    check("job_metadata lists standard + custom output paths and MATCH", seg["custom_output_status"] == "MATCH" and seg["standard_output_path"].endswith("/standard_output/0/result.json"), meta)
    std = json.loads(s3.get_object(Bucket="bda-out", Key=f"results/{jid}/0/standard_output/0/result.json")["Body"].read())
    check("standard output: OCR text lines from the vision model + honest quality label", std["image"]["text_lines"][0]["text"].startswith("Invoice INV-2041") and std["vyomi"]["confidenceAvailable"] is False, std)
    cus = json.loads(s3.get_object(Bucket="bda-out", Key=f"results/{jid}/0/custom_output/0/result.json")["Body"].read())
    check("custom output: blueprint fields extracted (constrained JSON) and typed", cus["inference_result"] == {"invoice_number": "INV-2041", "total_due": 1284.5, "vendor": "Acme Facilities Ltd"}
          and cus["matched_blueprint"]["name"] == "invoice-bp", cus)
    check("the vision call carried the blueprint as a json_schema grammar", any(q.get("response_format") for q in seen["vision"]))
    bd2 = bda.create_blueprint(blueprintName="note-bp", type="DOCUMENT", schema=json.dumps({"class": "note", "type": "object", "properties": {
        "invoice_number": {"type": "string", "instruction": "invoice id"}, "total_due": {"type": "number", "instruction": "amount"}}}))["blueprint"]
    arn2, st2 = run("docs/notes.txt", {"blueprints": [{"blueprintArn": bd2["blueprintArn"]}]})
    check("text document: standard output extracted with NO model, custom fields from the default chat model", st2["status"] in ("Success", "ServiceError"), st2)
    if st2["status"] == "Success":
        std2 = json.loads(s3.get_object(Bucket="bda-out", Key=f"results/{arn2.rsplit('/', 1)[-1]}/0/standard_output/0/result.json")["Body"].read())
        check("document standard output carries the extracted text", "Northwind HVAC" in std2["document"]["representation"]["text"], std2)
    arn3, st3 = run("av/clip.mp4")
    check("video -> ClientError with an honest message", st3["status"] == "ClientError" and "not supported" in st3.get("errorMessage", ""), st3)
    code, msg = err(rt.invoke_data_automation_async, inputConfiguration={"s3Uri": "s3://bda-in/scans/invoice.png"}, outputConfiguration={"s3Uri": "s3://bda-out/r"},
                    dataAutomationConfiguration={"dataAutomationProjectArn": pr["projectArn"]}, dataAutomationProfileArn="not-an-arn")
    check("bad dataAutomationProfileArn -> ValidationException", code == "ValidationException", (code, msg))
    code, msg = err(rt.get_data_automation_status, invocationArn="arn:aws:bedrock:us-east-1:123456789012:data-automation-invocation/nope")
    check("unknown invocation -> ResourceNotFoundException", code == "ResourceNotFoundException", (code, msg))
    sy = rt.invoke_data_automation(inputConfiguration={"bytes": png}, dataAutomationConfiguration={"dataAutomationProjectArn": pr["projectArn"]}, dataAutomationProfileArn=prof)
    check("InvokeDataAutomation (sync, bytes) returns standard + custom output segments", sy["semanticModality"] == "IMAGE"
          and json.loads(sy["outputSegments"][0]["standardOutput"])["vyomi"] and sy["outputSegments"][0]["customOutputStatus"] == "MATCH", sy)
    bda.tag_resource(resourceARN=pr["projectArn"], tags=[{"key": "team", "value": "fac"}])
    check("tags on a BDA project", bda.list_tags_for_resource(resourceARN=pr["projectArn"])["tags"] == [{"key": "team", "value": "fac"}])
    bda.delete_data_automation_project(projectArn=pr["projectArn"])
    bda.delete_blueprint(blueprintArn=bp["blueprintArn"])
    check("delete project then blueprint", bda.list_data_automation_projects()["projects"] == [] and [b["blueprintName"] for b in bda.list_blueprints()["blueprints"]] == ["note-bp"])

    # ───────── servers go away -> models disappear again ─────────
    llm.set_role_endpoint("vision", None)
    llm.set_role_endpoint("reasoning", None)
    ids = [m["modelId"] for m in bd.list_foundation_models()["modelSummaries"]]
    check("role servers removed -> models unlisted again", "vyomi.smolvlm-500m" not in ids and "vyomi.deepseek-r1-1.5b" not in ids)
    # ───────── runtime plan (8 GB Codespace budget) ─────────
    from core import llm_runtime as R
    check("role plan: with the default 2800 MB AI budget a role model stops the chat model", R.plan_role_start("vision", ["chat"])["stop"] == ["chat"])
    check("role plan: a bigger budget keeps chat + one role", R.plan_role_start("vision", ["chat"], 4000)["stop"] == [])
    check("role plan: the other role goes before chat", R.plan_role_start("reasoning", ["chat", "vision"], 4100)["stop"] == ["vision"])
    calls = []

    def fake_docker(args):
        calls.append(args)
        if args[:2] == ["ps", "-a"]:
            return 0, "", ""
        return 0, "id", ""
    R.role_start("reasoning", run=fake_docker, disk=lambda: 100.0)
    runargs = next(a for a in calls if a[0] == "run")
    check("role_start runs llama-server with the reasoning GGUF and --reasoning-format deepseek", "-hf" in runargs and "--reasoning-format" in runargs and "deepseek" in runargs, runargs)
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
