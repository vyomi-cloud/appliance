import json

import boto3
from botocore.exceptions import ClientError

import iamkit
import vymodels
from iamkit import allow

ag = boto3.client("bedrock-agent")
kb = next(k for k in ag.list_knowledge_bases()["knowledgeBaseSummaries"] if k["name"] == "facilities-kb")["knowledgeBaseId"]
fn = lambda name: "arn:aws:lambda:us-east-1:123456789012:function:" + name
iamkit.enforce("enforce")
role = iamkit.principal("facilities-runtime-role", [allow("bedrock:InvokeModel", "arn:aws:bedrock:us-east-1::foundation-model/" + vymodels.CHAT_MODEL)])


def what_the_agent_does():
    iamkit.client("bedrock-runtime", role).converse(modelId=vymodels.CHAT_MODEL, messages=[{"role": "user", "content": [{"text": "ok"}]}])
    iamkit.client("bedrock-agent-runtime", role).retrieve(knowledgeBaseId=kb, retrievalQuery={"text": "boiler"})
    for tool in ("facilities-asset-status", "facilities-kb-search"):
        iamkit.client("lambda", role).invoke(FunctionName=tool, InvocationType="DryRun")      # permission check only: nothing executes


added = iamkit.settle(role, what_the_agent_does)
granted = sorted(a for s in added for a in s["Action"])
print("the audit log taught the policy:", granted)
assert any(a.startswith("bedrock:Retrieve") for a in granted) and "lambda:InvokeFunction" in granted

# Narrow means narrow: scope the Lambda grant to the two read tools and prove the write tool is outside it.
role["statements"] = [st for st in role["statements"] if "lambda:InvokeFunction" not in st["Action"]]
iamkit.grant(role, [allow("lambda:InvokeFunction", [fn("facilities-asset-status"), fn("facilities-kb-search")])])
since = iamkit.last_audit_id()
for label, call in (
        ("invoke the write tool", lambda: iamkit.client("lambda", role).invoke(FunctionName="facilities-create-work-order", InvocationType="DryRun")),
        ("delete a work order", lambda: iamkit.client("dynamodb", role).delete_item(TableName="facilities-work-orders", Key={"work_order_id": {"S": "WO-000101"}})),
        ("read the approval ledger", lambda: iamkit.client("dynamodb", role).scan(TableName="approval-ledger")),
        ("approve its own request", lambda: iamkit.client("stepfunctions", role).send_task_success(taskToken="x", output="{}"))):
    try:
        call()
        raise AssertionError(label + " must be refused")
    except ClientError as e:
        assert e.response["Error"]["Code"] in ("AccessDenied", "AccessDeniedException"), (label, e)
        print("refused as intended:", label)
assert len(iamkit.denied(role, since)) == 4
print("agent role verified: %d allowed actions, 4 dangerous ones refused and on the audit trail" % len({a for s in role["statements"] for a in s["Action"]}))
