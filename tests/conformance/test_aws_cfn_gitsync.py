"""CodeConnections-lite + CloudFormation Git sync through the AWS wire router (real CloudFormation core underneath).
Hermetic. Run: PYTHONPATH=. python tests/conformance/test_aws_cfn_gitsync.py"""
import json
from core import ci_core as ci
from core.aws_wire_router import AwsWireRouter

T = "com.amazonaws.codeconnections.CodeConnections_20231201."
TPL1 = "AWSTemplateFormatVersion: '2010-09-09'\nResources:\n  Q:\n    Type: AWS::SQS::Queue\n    Properties:\n      QueueName: gs-queue\n"
TPL2 = TPL1 + "      VisibilityTimeout: 45\n"
ROLE = "arn:aws:iam::000000000000:role/GitSyncRole"


def _check(n, c):
    if not c:
        raise AssertionError(n)
    print("  ok ", n)


def main():
    ci.set_git(None); ci.set_builder(None); ci.set_fetcher(None); ci.set_http(None)
    r = AwsWireRouter()

    def cc(op, body, expect=200):
        out = r.handle("POST", "/", {}, {"x-amz-target": T + op, "content-type": "application/x-amz-json-1.0"}, json.dumps(body).encode())
        j = json.loads(out["body"] or b"{}")
        assert out["status"] == expect, (op, out["status"], j)
        return j

    def stack(name):
        out = r.handle("POST", "/", {}, {"content-type": "application/x-www-form-urlencoded"}, f"Action=DescribeStacks&StackName={name}&Version=2010-05-15".encode())
        return out["status"], out["body"].decode()

    def cc_template():
        out = r.handle("POST", "/", {}, {"content-type": "application/x-www-form-urlencoded"}, b"Action=GetTemplate&StackName=gs-stack&Version=2010-05-15")
        return out["body"].decode()

    conn = cc("CreateConnection", {"ConnectionName": "gh", "ProviderType": "GitHub"})["ConnectionArn"]
    _check("connection available", cc("GetConnection", {"ConnectionArn": conn})["Connection"]["ConnectionStatus"] == "AVAILABLE")
    cc("CreateConnection", {"ConnectionName": "gh", "ProviderType": "GitHub"}, 400)
    cc("CreateConnection", {"ConnectionName": "x", "ProviderType": "Nope"}, 400)
    link = cc("CreateRepositoryLink", {"ConnectionArn": conn, "OwnerId": "vyomi", "RepositoryName": "infra"})["RepositoryLinkInfo"]["RepositoryLinkId"]
    cc("CreateRepositoryLink", {"ConnectionArn": conn, "OwnerId": "vyomi", "RepositoryName": "infra"}, 400)
    base = {"Branch": "main", "ConfigFile": "deployment.json", "RepositoryLinkId": link, "ResourceName": "gs-stack", "RoleArn": ROLE, "SyncType": "CFN_STACK_SYNC"}
    cc("CreateSyncConfiguration", {**base, "RoleArn": "bad"}, 400)
    cc("CreateSyncConfiguration", {**base, "SyncType": "OTHER"}, 400)
    cc("CreateSyncConfiguration", {**base, "ConfigFile": "../x"}, 400)
    cc("CreateSyncConfiguration", {**base, "RepositoryLinkId": "nope"}, 404)
    sc = cc("CreateSyncConfiguration", base)["SyncConfiguration"]
    _check("sync configuration created", sc["ResourceName"] == "gs-stack" and sc["OwnerId"] == "vyomi")
    cc("CreateSyncConfiguration", base, 400)
    _check("link in use cannot be deleted", cc("DeleteRepositoryLink", {"RepositoryLinkId": link}, 400)["__type"] == "SyncConfigurationStillExistsException")
    cc("DeleteConnection", {"ConnectionArn": conn}, 400)

    # push without the deployment file -> sync FAILED with the reason
    cc("VyomiPush", {"RepositoryLinkId": link, "Files": {"README.md": "x"}, "Message": "readme"})
    st = cc("GetResourceSyncStatus", {"ResourceName": "gs-stack", "SyncType": "CFN_STACK_SYNC"})
    _check("missing deployment file -> FAILED with reason", st["LatestSync"]["Status"] == "FAILED" and "was not found" in st["LatestSync"]["Error"])
    _check("no stack was created", stack("gs-stack")[0] == 400)

    # real push: deployment file + template -> stack CREATED through the CloudFormation core
    dep = {"template-file-path": "template.yaml", "parameters": {}, "tags": {"team": "x"}}
    cc("VyomiPush", {"RepositoryLinkId": link, "Files": {"deployment.json": json.dumps(dep), "template.yaml": TPL1}, "Message": "add stack"})
    s, body = stack("gs-stack")
    _check("push created the CloudFormation stack", s == 200 and "CREATE_COMPLETE" in body and "<Key>team</Key>" in body)
    st = cc("GetResourceSyncStatus", {"ResourceName": "gs-stack", "SyncType": "CFN_STACK_SYNC"})
    sha1 = st["DesiredState"]["Sha"]
    _check("status SUCCEEDED with desired sha + events", st["LatestSync"]["Status"] == "SUCCEEDED" and sha1 and any("Creating" in e["Event"] for e in st["LatestSync"]["Events"]))
    # q = the SQS queue really exists
    q = r.handle("POST", "/", {}, {"x-amz-target": "AmazonSQS.ListQueues", "content-type": "application/x-amz-json-1.0"}, b"{}")
    _check("the template's queue really exists in the SQS store", "gs-queue" in q["body"].decode())
    # unchanged push -> no-op, not an update
    cc("VyomiPush", {"RepositoryLinkId": link, "Files": {"NOTES": "n"}, "Message": "notes"})
    st = cc("GetResourceSyncStatus", {"ResourceName": "gs-stack", "SyncType": "CFN_STACK_SYNC"})
    _check("identical template -> recorded as no changes", st["LatestSync"]["Noop"] is True and st["LatestSync"]["Status"] == "SUCCEEDED" and st["DesiredState"]["Sha"] != sha1)
    # changed template -> UpdateStack
    cc("VyomiPush", {"RepositoryLinkId": link, "Files": {"template.yaml": TPL2}, "Message": "rename queue"})
    s, body = stack("gs-stack")
    _check("changed template updated the stack", "UPDATE_COMPLETE" in body)
    # invalid template -> FAILED, stack untouched
    cc("VyomiPush", {"RepositoryLinkId": link, "Files": {"template.yaml": "Description: no resources here\n"}, "Message": "bad"})
    st = cc("GetResourceSyncStatus", {"ResourceName": "gs-stack", "SyncType": "CFN_STACK_SYNC"})
    _check("bad template -> FAILED with CloudFormation's error; last good sync kept", st["LatestSync"]["Status"] == "FAILED" and st["LatestSuccessfulSync"]["Status"] == "SUCCEEDED")
    if "UPDATE_ROLLBACK_FAILED" in stack("gs-stack")[1]:   # as in AWS: a stuck stack needs ContinueUpdateRollback before the next sync can update it
        r.handle("POST", "/", {}, {"content-type": "application/x-www-form-urlencoded"}, b"Action=ContinueUpdateRollback&StackName=gs-stack&Version=2010-05-15")
    # FILE_CHANGE only syncs when the deployment file / template changed
    cc("UpdateSyncConfiguration", {"ResourceName": "gs-stack", "SyncType": "CFN_STACK_SYNC", "TriggerResourceUpdateOn": "FILE_CHANGE"})
    cc("VyomiPush", {"RepositoryLinkId": link, "Files": {"template.yaml": TPL1}, "Message": "restore"})
    cc("VyomiPush", {"RepositoryLinkId": link, "Files": {"docs.md": "d"}, "Message": "docs only"})
    st = cc("GetResourceSyncStatus", {"ResourceName": "gs-stack", "SyncType": "CFN_STACK_SYNC"})
    _check("FILE_CHANGE: unrelated push is skipped", st["LatestSync"]["Noop"] is True and any("Skipped" in e["Event"] for e in st["LatestSync"]["Events"]))
    # manual sync + list/delete
    st = cc("VyomiSync", {"ResourceName": "gs-stack"})
    _check("manual sync works", st["LatestSync"]["Status"] == "SUCCEEDED")
    _check("list sync configurations", len(cc("ListSyncConfigurations", {"RepositoryLinkId": link, "SyncType": "CFN_STACK_SYNC"})["SyncConfigurations"]) == 1)
    cc("DeleteSyncConfiguration", {"ResourceName": "gs-stack", "SyncType": "CFN_STACK_SYNC"})
    cc("GetSyncConfiguration", {"ResourceName": "gs-stack", "SyncType": "CFN_STACK_SYNC"}, 404)
    cc("VyomiPush", {"RepositoryLinkId": link, "Files": {"template.yaml": TPL2}, "Message": "after delete"})
    _check("deleted sync no longer reacts to pushes", "<TemplateBody>" not in stack("gs-stack")[1] and "VisibilityTimeout" not in cc_template())
    cc("DeleteRepositoryLink", {"RepositoryLinkId": link})
    cc("DeleteConnection", {"ConnectionArn": conn})
    cc("Bogus", {}, 400)
    print("PASS test_aws_cfn_gitsync")


if __name__ == "__main__":
    main()
