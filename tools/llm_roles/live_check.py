#!/usr/bin/env python3
"""LIVE check of the Mesh role models against REAL llama-server processes (not fakes): measures latency, RAM and the Bedrock/BDA wire path.

Start the servers yourself (example, CPU only, 2 threads, the shape of an 8 GB Codespace):
  llama-server -m SmolVLM-500M-Instruct-Q8_0.gguf --mmproj mmproj-SmolVLM-500M-Instruct-Q8_0.gguf --port 18101 -c 4096 --jinja -t 2
  llama-server -m DeepSeek-R1-Distill-Qwen-1.5B-Q4_K_M.gguf --port 18102 -c 4096 --jinja --reasoning-format deepseek -t 2
Then:  PYTHONPATH=. python tools/llm_roles/live_check.py <invoice.png> [vision_pid reasoning_pid]
Prints MEASURED numbers only; nothing is asserted about model quality beyond what it prints.
"""
import base64
import json
import os
import subprocess
import sys
import time

os.environ.setdefault("VYOMI_LLM_VISION_ENDPOINT", "http://127.0.0.1:18101")
os.environ.setdefault("VYOMI_LLM_REASONING_ENDPOINT", "http://127.0.0.1:18102")
os.environ["VYOMI_LLM_ENDPOINT"] = os.environ["VYOMI_LLM_REASONING_ENDPOINT"]     # stand-in default chat model for this run
sys.path.insert(0, os.getcwd())
from core import ai_models_core as am  # noqa: E402
from core import bedrock_bda_core as bda  # noqa: E402


def call(path, body):
    t = time.time()
    r = am.bedrock_dispatch("POST", path, {}, {}, json.dumps(body).encode())
    return r["status"], json.loads(r["body"]), round(time.time() - t, 1)


def footprint(pid):
    try:
        o = subprocess.run(["footprint", "-p", str(pid)], capture_output=True, text=True).stdout
        return [l.strip() for l in o.splitlines() if "phys_footprint" in l][:2]
    except Exception:  # noqa: BLE001
        return ["footprint unavailable"]


img = base64.b64encode(open(sys.argv[1], "rb").read()).decode()
st, d, t = call("/model/vyomi.qwen3-4b/converse", {"messages": [{"role": "user", "content": [{"text": "Read all the text in this image."}, {"image": {"format": "png", "source": {"bytes": img}}}]}],
                                                       "inferenceConfig": {"maxTokens": 120, "temperature": 0}})
print("VISION Converse", st, f"{t}s", json.dumps(d["output"]["message"]["content"])[:300], d["usage"])
st, d, t = call("/model/vyomi.qwen3-4b/converse", {"messages": [{"role": "user", "content": [{"text": "What is 17*23? Show the work briefly."}]}],
                                                       "additionalModelRequestFields": {"thinking": {"type": "enabled", "budget_tokens": 1024}}, "inferenceConfig": {"maxTokens": 700, "temperature": 0.6}})
c = d["output"]["message"]["content"]
print("REASONING Converse", st, f"{t}s", "reasoningContent" in c[0], "tokens", d["usage"]["outputTokens"], "tok/s", round(d["usage"]["outputTokens"] / t, 1))
print("  answer:", [b.get("text", "")[:160] for b in c if "text" in b])
# BDA end to end (in-memory bag, no S3): sync InvokeDataAutomation with a blueprint
bp = {"class": "invoice", "type": "object", "properties": {"invoice_number": {"type": "string", "instruction": "The invoice number"}, "vendor": {"type": "string", "instruction": "Vendor name"},
      "date": {"type": "string", "instruction": "Invoice date"}, "total_due": {"type": "number", "instruction": "Total amount due"}}}
bda.dispatch(None, "PUT", "/blueprints/", {}, {}, json.dumps({"blueprintName": "inv", "type": "IMAGE", "schema": json.dumps(bp)}).encode())
arn = next(iter(bda._st()["blueprints"].values()))["arn"]
t0 = time.time()
r = bda.dispatch(None, "POST", "/", {}, {"x-amz-target": bda.TARGET_PREFIX + ".InvokeDataAutomation"}, json.dumps({
    "inputConfiguration": {"bytes": img}, "blueprints": [{"blueprintArn": arn}],
    "dataAutomationProfileArn": "arn:aws:bedrock:us-east-1:123456789012:data-automation-profile/us.data-automation-v1"}).encode())
out = json.loads(r["body"])
print("BDA InvokeDataAutomation", r["status"], f"{round(time.time() - t0, 1)}s")
seg = out["outputSegments"][0]
print("  custom:", seg.get("customOutputStatus"), json.loads(seg["customOutput"])["inference_result"])
print("  standard OCR lines:", [x["text"] for x in json.loads(seg["standardOutput"])["image"]["text_lines"]])
for label, pid in zip(("vision", "reasoning"), sys.argv[2:4]):
    print("RAM", label, footprint(pid))
