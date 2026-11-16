#!/usr/bin/env python3
"""AgentCore Runtime hosting: CreateAgentRuntime(code deploy) -> InvokeAgentRuntime really runs the agent through the runtime contract.
Real boto3 against the in-process simulator. Run: PYTHONPATH=. python3 tests/conformance/test_agentcore_runtime_host.py"""
import io, json, os, sys, zipfile
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test"); os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
os.environ["VYOMI_REPO"] = ROOT
sys.path.insert(0, os.path.join(ROOT, "examples", "enterprise-facilities-agent"))
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from facilities.server import start_in_process

FAILS = []
def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + (f"  {detail}" if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

AGENT = '''
import os, boto3
def handler(payload, context):
    if payload.get("stream"):
        def ev():
            for i in range(3):
                yield {"chunk": i}
            yield {"final": True, "session": context.session_id}
        return ev()
    if payload.get("boom"):
        raise RuntimeError("agent exploded")
    s3 = boto3.client("s3", region_name="us-east-1")          # the agent's own AWS SDK call: AWS_ENDPOINT_URL points back at the simulator
    return {"echo": payload.get("prompt"), "pid": os.getpid(), "session": context.session_id, "env": os.environ.get("GREETING"),
            "buckets": [b["Name"] for b in s3.list_buckets()["Buckets"]], "arn": os.environ.get("AGENT_RUNTIME_ARN"), "version": "%s"}
'''
def zipped(v):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("app.py", AGENT % v)
    return b.getvalue()

ep = start_in_process()
cfg = Config(retries={"max_attempts": 1}, read_timeout=120)
mk = lambda s: boto3.client(s, region_name="us-east-1", endpoint_url=ep, config=cfg)
ctl, dp, s3 = mk("bedrock-agentcore-control"), mk("bedrock-agentcore"), mk("s3")
s3.create_bucket(Bucket="agent-code"); s3.put_object(Bucket="agent-code", Key="a/v1.zip", Body=zipped("v1")); s3.put_object(Bucket="agent-code", Key="a/v2.zip", Body=zipped("v2"))
art = lambda k: {"codeConfiguration": {"code": {"s3": {"bucket": "agent-code", "prefix": k}}, "runtime": "PYTHON_3_12", "entryPoint": ["app.py"]}}
import time
def ready(rid):
    for _ in range(30):
        if ctl.get_agent_runtime(agentRuntimeId=rid)["status"] == "READY":
            return
        time.sleep(0.3)
r = ctl.create_agent_runtime(agentRuntimeName="host_test", agentRuntimeArtifact=art("a/v1.zip"), roleArn="arn:aws:iam::123456789012:role/r",
                             networkConfiguration={"networkMode": "PUBLIC"}, environmentVariables={"GREETING": "hello"})
rid, arn = r["agentRuntimeId"], r["agentRuntimeArn"]; ready(rid)
inv = lambda sid, body, **k: dp.invoke_agent_runtime(agentRuntimeArn=arn, runtimeSessionId=sid, payload=json.dumps(body).encode(), contentType="application/json", **k)
A, B = "session-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "session-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"

o1 = json.loads(inv(A, {"prompt": "hi"})["response"].read())
check("invoke runs the entrypoint (echo + env var)", o1["echo"] == "hi" and o1["env"] == "hello" and o1["arn"] == arn, o1)
check("agent runs in its own process", o1["pid"] != os.getpid())
check("agent's AWS SDK call reached the simulator", "agent-code" in o1["buckets"], o1["buckets"])
check("session id passed to the agent", o1["session"] == A)
o2 = json.loads(inv(B, {"prompt": "x"})["response"].read()); o1b = json.loads(inv(A, {"prompt": "again"})["response"].read())
check("sessions isolated (distinct process), session reused", o2["pid"] != o1["pid"] and o1b["pid"] == o1["pid"])
chunks = inv(A, {"stream": True})["response"].read().decode()
check("generator handler streams SSE", chunks.count("data: ") == 4 and '"chunk": 2' in chunks, chunks)
try:
    inv(A, {"boom": 1}); check("agent exception -> RuntimeClientError", False)
except ClientError as e:
    check("agent exception -> RuntimeClientError 424", e.response["ResponseMetadata"]["HTTPStatusCode"] == 424 and "agent exploded" in str(e), str(e)[:200])
try:
    dp.invoke_agent_runtime(agentRuntimeArn=arn, runtimeSessionId="short", payload=b"{}"); check("short session id rejected", False)
except Exception as e:      # the SDK enforces min length 33 client-side
    check("short runtimeSessionId rejected", "runtimeSessionId" in str(e))
# versions / endpoints: update -> v2; an endpoint pinned to v1 keeps v1 code, DEFAULT follows latest
u = ctl.update_agent_runtime(agentRuntimeId=rid, agentRuntimeArtifact=art("a/v2.zip"), roleArn="arn:aws:iam::123456789012:role/r", networkConfiguration={"networkMode": "PUBLIC"}, environmentVariables={"GREETING": "v2"}); ready(rid)
ctl.create_agent_runtime_endpoint(agentRuntimeId=rid, name="stable", agentRuntimeVersion="1")
time.sleep(1.2)
v_def = json.loads(dp.invoke_agent_runtime(agentRuntimeArn=arn, runtimeSessionId="session-cccccccccccccccccccccccccccccccccc", payload=b'{"prompt":"p"}', qualifier="DEFAULT")["response"].read())
v_pin = json.loads(dp.invoke_agent_runtime(agentRuntimeArn=arn, runtimeSessionId="session-dddddddddddddddddddddddddddddddddd", payload=b'{"prompt":"p"}', qualifier="stable")["response"].read())
check("DEFAULT endpoint runs the new version's code and env", v_def["version"] == "v2" and v_def["env"] == "v2", v_def)
check("endpoint pinned to version 1 keeps running v1 code and env", v_pin["version"] == "v1" and v_pin["env"] == "hello", v_pin)
dp.stop_runtime_session(agentRuntimeArn=arn, runtimeSessionId=A)
o3 = json.loads(dp.invoke_agent_runtime(agentRuntimeArn=arn, runtimeSessionId=A, payload=b'{"prompt":"p"}', qualifier="stable")["response"].read())
check("StopRuntimeSession ends the process (next call starts a fresh one)", o3["pid"] != o1["pid"])
# missing code object -> 424, not 500
r2 = ctl.create_agent_runtime(agentRuntimeName="host_missing", agentRuntimeArtifact=art("nope.zip"), roleArn="arn:aws:iam::123456789012:role/r", networkConfiguration={"networkMode": "PUBLIC"}); ready(r2["agentRuntimeId"])
try:
    dp.invoke_agent_runtime(agentRuntimeArn=r2["agentRuntimeArn"], runtimeSessionId=A, payload=b"{}"); check("missing code -> error", False)
except ClientError as e:
    check("unreadable code object -> RuntimeClientError 424 (modeled, no 500)", e.response["ResponseMetadata"]["HTTPStatusCode"] == 424, str(e)[:160])
# Nano substrate path: no subprocess, entrypoint exec'd in-process (handler functions only)
os.environ["VYOMI_RUNTIME_BACKEND"] = "inproc"
ip = json.loads(dp.invoke_agent_runtime(agentRuntimeArn=arn, runtimeSessionId="session-eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee", payload=b'{"prompt":"ip"}', qualifier="DEFAULT")["response"].read())
check("inproc backend (Nano path) runs the same entrypoint through the same contract", ip["echo"] == "ip" and ip["pid"] == os.getpid() and ip["env"] == "v2", ip)
os.environ.pop("VYOMI_RUNTIME_BACKEND")
ctl.delete_agent_runtime(agentRuntimeId=rid)
print("\nFAILED: %s" % FAILS if FAILS else "\nALL PASS")
sys.exit(1 if FAILS else 0)
