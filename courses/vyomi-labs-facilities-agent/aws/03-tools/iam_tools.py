import importlib
import os

import boto3
from botocore.exceptions import ClientError

import iamkit
from iamkit import allow

TABLES = {"ASSETS_TABLE": "facilities-assets", "WORK_ORDERS_TABLE": "facilities-work-orders", "LEDGER_TABLE": "approval-ledger"}
tbl = lambda name: "arn:aws:dynamodb:us-east-1:123456789012:table/" + name
iamkit.enforce("enforce")


def run_as(p, module, event):
    """Run the tool's real handler with this principal's credentials."""
    saved = {k: os.environ.get(k) for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", *TABLES)}
    os.environ.update(AWS_ACCESS_KEY_ID=p["key"], AWS_SECRET_ACCESS_KEY=p["secret"], **TABLES)
    boto3.setup_default_session()          # the default session caches credentials: start a fresh one for this identity
    try:
        return importlib.import_module(module).handler(event, None)
    finally:
        for k, v in saved.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        boto3.setup_default_session()


# 1. The read tool, starting too thin: GetItem on the assets table only.
reader = iamkit.principal("tool-asset-status", [allow("dynamodb:GetItem", tbl("facilities-assets"))])
added = iamkit.settle(reader, lambda: run_as(reader, "asset_status", {"asset_id": "B-12"}))
fix = sorted((s["Action"][0], s["Resource"].split("/")[-1]) for s in added)
print("the audit log said the read tool was missing:", fix)
assert fix == [("dynamodb:Scan", "facilities-work-orders")], "unexpected missing permissions: %s" % fix
assert run_as(reader, "asset_status", {"asset_id": "B-12"})["found"] is True

# 2. The write tool: put the work order, update the ledger, nothing else.
writer = iamkit.principal("tool-create-work-order", [allow("dynamodb:PutItem", tbl("facilities-work-orders"))])
req = {"request_id": "req-iam-0001", "asset_id": "B-12", "summary": "least privilege check", "priority": "P3", "requester": "iam-lab"}
added = iamkit.settle(writer, lambda: run_as(writer, "create_work_order", req))
fix = sorted((s["Action"][0], s["Resource"].split("/")[-1]) for s in added)
print("the audit log said the write tool was missing:", fix)
assert ("dynamodb:UpdateItem", "approval-ledger") in fix

# 3. The boundaries: each identity is refused everything outside its job.
def refused(label, call):
    try:
        call()
    except ClientError as e:
        assert e.response["Error"]["Code"] in ("AccessDenied", "AccessDeniedException"), e
        print("refused as intended:", label)
        return
    raise AssertionError(label + " should have been refused")


rd, wr = iamkit.client("dynamodb", reader), iamkit.client("dynamodb", writer)
refused("read tool writes a work order", lambda: rd.put_item(TableName="facilities-work-orders", Item={"work_order_id": {"S": "WO-EVIL"}}))
refused("read tool reads the approval ledger", lambda: rd.scan(TableName="approval-ledger"))
refused("write tool reads the assets", lambda: wr.get_item(TableName="facilities-assets", Key={"asset_id": {"S": "B-12"}}))
refused("write tool deletes a work order", lambda: wr.delete_item(TableName="facilities-work-orders", Key={"work_order_id": {"S": "WO-000101"}}))
assert "WO-EVIL" not in [i["work_order_id"]["S"] for i in boto3.client("dynamodb").scan(TableName="facilities-work-orders")["Items"]]

# 4. The same policies as roles the functions run as on real AWS.
iam = boto3.client("iam")
trust = '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]}'
for role, p in (("facilities-asset-status-role", reader), ("facilities-create-work-order-role", writer)):
    try:
        iam.create_role(RoleName=role, AssumeRolePolicyDocument=trust)
    except iam.exceptions.EntityAlreadyExistsException:
        pass
    iam.put_role_policy(RoleName=role, PolicyName="least-privilege", PolicyDocument=__import__("json").dumps({"Version": "2012-10-17", "Statement": p["statements"]}))
print("roles created with the settled policies:", ", ".join(r["RoleName"] for r in iam.list_roles()["Roles"] if r["RoleName"].startswith("facilities-")))
print("least privilege per tool verified; denials in the audit log:", len([r for r in iamkit.audit(reader) + iamkit.audit(writer) if r["decision"] == "deny"]))
