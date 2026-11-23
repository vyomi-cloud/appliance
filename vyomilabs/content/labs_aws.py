"""Hands-on lab blocks for the AWS course. Every block is complete, copy-paste code: the learner saves `file`, runs `run`, and sees `expect`.
vyomilabs/labrun.py executes these blocks in order against a clean simulator, so what the guide shows is what has actually run."""


def b(title, text, file, code, run=None, expect=None, lang="python", needs_runtime=False):
    """needs_runtime: the block needs real function execution (appliance or Mesh); the local in-process simulator only runs a restricted sandbox."""
    return dict(title=title, text=text, file=file, lang=lang, code=code.strip("\n") + "\n", run=run, expect=expect, needs_runtime=needs_runtime)


LAB = {}

LAB[10] = [
 b("Write the model client", "Every other layer imports these three functions, so keep the names. boto3 reads the simulator address from AWS_ENDPOINT_URL, exactly as it would on real AWS.",
   "models.py", '''
import json
import boto3

CHAT_MODEL = "anthropic.claude-3-haiku-20240307-v1:0"
EMBED_MODEL = "amazon.titan-embed-text-v2:0"
_rt = boto3.client("bedrock-runtime")


def _text(resp):
    return "".join(b.get("text", "") for b in resp["output"]["message"]["content"])


def chat(prompt):
    r = _rt.converse(modelId=CHAT_MODEL, messages=[{"role": "user", "content": [{"text": prompt}]}], inferenceConfig={"maxTokens": 200})
    return _text(r)


def chat_with_tools(prompt, tools):
    r = _rt.converse(modelId=CHAT_MODEL, messages=[{"role": "user", "content": [{"text": prompt}]}], toolConfig={"tools": tools})
    tool = next((b["toolUse"] for b in r["output"]["message"]["content"] if "toolUse" in b), None)
    return {"stop_reason": r["stopReason"], "tool_use": tool, "text": _text(r)}


def embed(text):
    r = _rt.invoke_model(modelId=EMBED_MODEL, body=json.dumps({"inputText": text}))
    return json.loads(r["body"].read())["embedding"]
'''),
 b("Try all three calls", "A chat call, a tool-calling call and an embedding. The tool definition is the one the agents use later.",
   "try_models.py", '''
from models import chat, chat_with_tools, embed

print("chat:", chat("Reply with the single word OK."))

TOOL = {"toolSpec": {"name": "asset_status", "description": "status of an asset by id",
                     "inputSchema": {"json": {"type": "object", "properties": {"asset_id": {"type": "string"}}, "required": ["asset_id"]}}}}
r = chat_with_tools("What is the status of asset B-12?", [TOOL])
print("tools: stop_reason =", r["stop_reason"])

v = embed("boiler pressure limit")
print("embed: vector of", len(v), "numbers")
''', run="python try_models.py", expect="embed: vector of"),
]

LAB[7] = [
 b("Create the three tables", "Assets and work orders hold the operational data; the ledger is used by the approval layer later. On-demand billing, one string key each.",
   "tables.py", '''
import boto3

ddb = boto3.client("dynamodb")
for name, key in (("facilities-assets", "asset_id"), ("facilities-work-orders", "work_order_id"), ("approval-ledger", "request_id")):
    try:
        ddb.create_table(TableName=name, KeySchema=[{"AttributeName": key, "KeyType": "HASH"}],
                         AttributeDefinitions=[{"AttributeName": key, "AttributeType": "S"}], BillingMode="PAY_PER_REQUEST")
        print("created", name)
    except ddb.exceptions.ResourceInUseException:
        print("exists ", name)
''', run="python tables.py", expect="created facilities-assets"),
 b("Seed the data", "Three assets and three work orders. Boiler B-12 is running at 34 psi, which the later chapters use as the example problem.",
   "seed.py", '''
import boto3

ddb = boto3.client("dynamodb")
ASSETS = [
    {"asset_id": "B-12", "name": "Boiler B-12", "site": "HQ-1", "type": "boiler", "status": "RUNNING", "pressure_psi": 34, "last_inspection": "2026-08-02"},
    {"asset_id": "AHU-7", "name": "Air handling unit 7", "site": "HQ-1", "type": "hvac", "status": "DEGRADED", "supply_temp_drift_c": 3.8, "last_inspection": "2026-09-12"},
    {"asset_id": "EL-3", "name": "Elevator 3", "site": "HQ-2", "type": "elevator", "status": "RUNNING", "last_inspection": "2026-10-01"},
]
WORK_ORDERS = [
    {"work_order_id": "WO-000101", "asset_id": "AHU-7", "title": "Replace AHU-7 filter", "priority": "P3", "status": "CLOSED", "requester": "seed"},
    {"work_order_id": "WO-000102", "asset_id": "B-12", "title": "Quarterly PRV inspection", "priority": "P2", "status": "OPEN", "requester": "seed"},
    {"work_order_id": "WO-000103", "asset_id": "EL-3", "title": "Door-zone sensor check", "priority": "P2", "status": "OPEN", "requester": "seed"},
]


def attr(v):
    return {"N": str(v)} if isinstance(v, (int, float)) else {"S": str(v)}


for table, rows in (("facilities-assets", ASSETS), ("facilities-work-orders", WORK_ORDERS)):
    for row in rows:
        ddb.put_item(TableName=table, Item={k: attr(v) for k, v in row.items()})
    print("seeded", table, len(rows))
''', run="python seed.py", expect="seeded facilities-work-orders 3"),
 b("Write the read-only tool", "asset-status is a read-only tool: it returns one asset and its work orders. It never writes.",
   "asset_status.py", '''
import os
import boto3


def handler(event, context):
    ddb = boto3.client("dynamodb")
    asset = ddb.get_item(TableName=os.environ["ASSETS_TABLE"], Key={"asset_id": {"S": event["asset_id"]}}).get("Item")
    if not asset:
        return {"found": False}
    wos = ddb.scan(TableName=os.environ["WORK_ORDERS_TABLE"], FilterExpression="asset_id = :a",
                   ExpressionAttributeValues={":a": {"S": event["asset_id"]}}).get("Items", [])
    return {"found": True, "asset": {k: list(v.values())[0] for k, v in asset.items()},
            "work_orders": [{k: list(v.values())[0] for k, v in w.items()} for w in wos]}
'''),
 b("Write the approval-request tool", "request-approval parks a request in the ledger and tells the approver. Chapter 9 wires it to the approval flow; for now you only deploy it.",
   "request_approval.py", '''
import json, os, time
import boto3


def handler(event, context):
    token = event["TaskToken"]
    req = {k: v for k, v in event.items() if k != "TaskToken"}
    boto3.client("dynamodb").put_item(TableName=os.environ["LEDGER_TABLE"], Item={
        "request_id": {"S": req["request_id"]}, "status": {"S": "PENDING"}, "task_token": {"S": token},
        "requester": {"S": req.get("requester", "")}, "summary": {"S": req.get("summary", "")}, "ts": {"N": str(int(time.time()))}})
    boto3.client("sns").publish(TopicArn=os.environ["INBOX_TOPIC_ARN"], Subject="Approval needed: " + req.get("summary", "")[:80],
                                Message=json.dumps({"request_id": req["request_id"], "summary": req.get("summary"), "task_token": token}))
    return {"queued": True}
'''),
 b("Write the work-order tool", "create-work-order is the write tool: it only ever runs after a human has approved, and it closes the ledger entry.",
   "create_work_order.py", '''
import os
import boto3


def handler(event, context):
    req = event["request"] if "request" in event else event
    ddb = boto3.client("dynamodb")
    wo_id = "WO-" + req["request_id"][-6:].upper()
    ddb.put_item(TableName=os.environ["WORK_ORDERS_TABLE"], Item={
        "work_order_id": {"S": wo_id}, "asset_id": {"S": req["asset_id"]}, "title": {"S": req["summary"]},
        "priority": {"S": req.get("priority", "P3")}, "status": {"S": "OPEN"}, "requester": {"S": req.get("requester", "")}})
    ddb.update_item(TableName=os.environ["LEDGER_TABLE"], Key={"request_id": {"S": req["request_id"]}},
                    UpdateExpression="SET #s = :s, work_order_id = :w", ExpressionAttributeNames={"#s": "status"},
                    ExpressionAttributeValues={":s": {"S": "EXECUTED"}, ":w": {"S": wo_id}})
    return {"work_order_id": wo_id}
'''),
 b("Deploy the three Lambda functions", "Zips each handler file you saved and calls CreateFunction. Environment variables carry the table names and, because the functions call the simulator too, the endpoint.",
   "deploy_tools.py", '''
import io, os, zipfile
import boto3

lam = boto3.client("lambda")
ROLE = "arn:aws:iam::123456789012:role/facilities-role"
ENV = {"ASSETS_TABLE": "facilities-assets", "WORK_ORDERS_TABLE": "facilities-work-orders", "LEDGER_TABLE": "approval-ledger",
       "INBOX_TOPIC_ARN": "", "AWS_ENDPOINT_URL": os.environ["AWS_ENDPOINT_URL"], "AWS_DEFAULT_REGION": os.environ.get("AWS_DEFAULT_REGION", "us-east-1")}


def zip_of(module, source):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(module + ".py", source)
    return buf.getvalue()


FUNCTIONS = (("facilities-asset-status", "asset_status"), ("facilities-request-approval", "request_approval"),
             ("facilities-create-work-order", "create_work_order"))
for name, module in FUNCTIONS:
    source = open(module + ".py").read()
    lam.create_function(FunctionName=name, Runtime="python3.12", Role=ROLE, Handler=module + ".handler",
                        Code={"ZipFile": zip_of(module, source)}, Timeout=30, Environment={"Variables": ENV})
    print("deployed", name)
''', run="python deploy_tools.py", expect="deployed facilities-create-work-order"),
 b("Call the read-only tool", "Invoke asset-status for boiler B-12, the way an agent will.",
   "call_tools.py", '''
import json
import boto3

lam = boto3.client("lambda")
r = lam.invoke(FunctionName="facilities-asset-status", Payload=json.dumps({"asset_id": "B-12"}).encode())
out = json.loads(r["Payload"].read())
print("found:", out["found"], "| status:", out["asset"]["status"], "| open work orders:", len([w for w in out["work_orders"] if w["status"] == "OPEN"]))
''', run="python call_tools.py", expect="found: True | status: RUNNING | open work orders: 1", needs_runtime=True),
]
