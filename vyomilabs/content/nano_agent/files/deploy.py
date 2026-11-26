"""Deploy the agent as a Lambda function and call it once. On Nano the function runs in a sandbox inside your browser: it can import json, os, re, math, boto3
and a few other pure modules, and reach AWS only through boto3 clients. It cannot open files or sockets. Your agent was written within those limits."""
import base64
import io
import json
import zipfile

import boto3

import bundle
import llmx
import rag
import seed
from data import DOCS

FN = "facilities-agent"
seed.seed()
rag.ensure_index(DOCS)
src = bundle.build()
open("handler.py", "w").write(src)
buf = io.BytesIO()
with zipfile.ZipFile(buf, "w") as z:
    z.writestr("handler.py", src)
lam = boto3.client("lambda")
env = {"Variables": {"CHAT_MODEL": llmx.CHAT_MODEL, "EMBED_MODEL": llmx.EMBED_MODEL}}
try:
    lam.get_function(FunctionName=FN)
    lam.update_function_code(FunctionName=FN, ZipFile=buf.getvalue())
    lam.update_function_configuration(FunctionName=FN, Environment=env, Timeout=300)
    print("updated function", FN)
except lam.exceptions.ResourceNotFoundException:
    lam.create_function(FunctionName=FN, Runtime="python3.12", Role="arn:aws:iam::123456789012:role/facilities-agent", Handler="handler.handler",
                        Code={"ZipFile": buf.getvalue()}, Timeout=300, MemorySize=512, Environment=env)
    print("created function", FN)

out = lam.invoke(FunctionName=FN, Payload=json.dumps({"question": "What is the status of AHU-7?", "session_id": "deploy-1", "user_id": "deploy"}).encode())
body = json.loads(out["Payload"].read())
assert "errorType" not in body, body
print("invoked:", body["type"], "|", body["text"][:120])
print("steps:", [s.get("action") for s in body["steps"]], "| model calls:", body["model_calls"])
assert body["type"] == "answer" and "degraded" in body["text"].lower(), body
print("deployed and answering")
