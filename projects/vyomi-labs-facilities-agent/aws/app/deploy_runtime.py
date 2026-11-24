import io
import time
import zipfile

import boto3

BUCKET, KEY = "facilities-docs", "agent-runtime/facilities-supervisor.zip"
s3 = boto3.client("s3")
ac = boto3.client("bedrock-agentcore-control")

try:
    s3.create_bucket(Bucket=BUCKET)
except Exception:
    pass          # the bucket already exists

buf = io.BytesIO()
with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
    z.write("agent_main.py", "main.py")
    z.write("agents.py", "agents.py")
    z.write("mcp_client.py", "mcp_client.py")
s3.put_object(Bucket=BUCKET, Key=KEY, Body=buf.getvalue())
print("uploaded s3://%s/%s (%d bytes)" % (BUCKET, KEY, len(buf.getvalue())))

r = ac.create_agent_runtime(
    agentRuntimeName="facilities_supervisor",
    agentRuntimeArtifact={"codeConfiguration": {"code": {"s3": {"bucket": BUCKET, "prefix": KEY}}, "runtime": "PYTHON_3_12", "entryPoint": ["main.py"]}},
    roleArn="arn:aws:iam::123456789012:role/facilities-role", networkConfiguration={"networkMode": "PUBLIC"},
    environmentVariables={"AGENT_NAME": "facilities-supervisor"})
print("created runtime", r["agentRuntimeId"])

for _ in range(30):
    status = ac.get_agent_runtime(agentRuntimeId=r["agentRuntimeId"])["status"]
    if status != "CREATING":
        break
    time.sleep(0.5)
print("runtime status", status)
