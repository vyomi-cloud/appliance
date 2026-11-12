"""AWS Backup vaults / plans / selections / jobs / recovery points / restore jobs / vault lock via the wire router.
Run: PYTHONPATH=. python tests/conformance/test_aws_backup_vaults.py"""
import json
from core.aws_wire_router import AwsWireRouter

H = lambda svc: {"authorization": f"AWS4-HMAC-SHA256 Credential=T/20261030/us-east-1/{svc}/aws4_request, SignedHeaders=host, Signature=0", "content-type": "application/json"}
r = AwsWireRouter()
ROLE = "arn:aws:iam::123456789012:role/backup"


def _check(n, c):
    if not c:
        raise AssertionError(n)
    print("  ok ", n)


def bk(m, path, body=None, q=None):
    o = r.handle(m, path, q or {}, H("backup"), json.dumps(body).encode() if body is not None else b"")
    return o["status"], (json.loads(o["body"]) if o["body"] else {})


def ddb(a, body):
    o = r.handle("POST", "/", {}, dict(H("dynamodb"), **{"x-amz-target": f"DynamoDB_20120810.{a}", "content-type": "application/x-amz-json-1.0"}), json.dumps(body).encode())
    return o["status"], (json.loads(o["body"]) if o["body"] else {})


def main():
    s, d = bk("PUT", "/backup-vaults/v1", {})
    _check("create vault", s == 200 and d["BackupVaultArn"].endswith(":backup-vault:v1"))
    _check("duplicate vault", bk("PUT", "/backup-vaults/v1", {})[1]["Code"] == "AlreadyExistsException")
    _check("bad vault name", bk("PUT", "/backup-vaults/a", {})[0] == 400)
    _check("list has Default", {v["BackupVaultName"] for v in bk("GET", "/backup-vaults/")[1]["BackupVaultList"]} == {"Default", "v1"})
    # plans
    rule = {"RuleName": "daily", "TargetBackupVaultName": "v1", "ScheduleExpression": "cron(0 5 ? * * *)", "Lifecycle": {"MoveToColdStorageAfterDays": 30, "DeleteAfterDays": 130}}
    _check("lifecycle 90-day rule", bk("PUT", "/backup/plans/", {"BackupPlan": {"BackupPlanName": "p", "Rules": [dict(rule, Lifecycle={"MoveToColdStorageAfterDays": 30, "DeleteAfterDays": 60})]}})[0] == 400)
    _check("bad cron", bk("PUT", "/backup/plans/", {"BackupPlan": {"BackupPlanName": "p", "Rules": [dict(rule, ScheduleExpression="daily")]}})[0] == 400)
    _check("missing vault", bk("PUT", "/backup/plans/", {"BackupPlan": {"BackupPlanName": "p", "Rules": [dict(rule, TargetBackupVaultName="nope")]}})[0] == 400)
    s, d = bk("PUT", "/backup/plans/", {"BackupPlan": {"BackupPlanName": "p", "Rules": [rule]}})
    _check("plan created", s == 200 and d["BackupPlanId"])
    pid = d["BackupPlanId"]
    _check("plan get", bk("GET", f"/backup/plans/{pid}")[1]["BackupPlan"]["Rules"][0]["RuleId"])
    _check("selection needs targets", bk("PUT", f"/backup/plans/{pid}/selections/", {"BackupSelection": {"SelectionName": "s", "IamRoleArn": ROLE}})[0] == 400)
    s, d = bk("PUT", f"/backup/plans/{pid}/selections/", {"BackupSelection": {"SelectionName": "s", "IamRoleArn": ROLE, "Resources": ["arn:aws:dynamodb:us-east-1:123456789012:table/orders"]}})
    _check("selection created", s == 200)
    _check("plan with selections not deletable", bk("DELETE", f"/backup/plans/{pid}")[0] == 400)
    # DynamoDB backup + restore
    ddb("CreateTable", {"TableName": "orders", "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}], "AttributeDefinitions": [{"AttributeName": "id", "AttributeType": "S"}], "BillingMode": "PAY_PER_REQUEST"})
    ddb("PutItem", {"TableName": "orders", "Item": {"id": {"S": "1"}}})
    arn = "arn:aws:dynamodb:us-east-1:123456789012:table/orders"
    _check("job needs role", bk("PUT", "/backup-jobs", {"BackupVaultName": "v1", "ResourceArn": arn})[0] == 400)
    s, d = bk("PUT", "/backup-jobs", {"BackupVaultName": "v1", "ResourceArn": arn, "IamRoleArn": ROLE, "Lifecycle": {"DeleteAfterDays": 5}})
    _check("ddb backup job", s == 200 and d["RecoveryPointArn"])
    rp = d["RecoveryPointArn"]
    _check("job completed", bk("GET", f"/backup-jobs/{d['BackupJobId']}")[1]["State"] == "COMPLETED")
    _check("recovery point listed", len(bk("GET", "/backup-vaults/v1/recovery-points/")[1]["RecoveryPoints"]) == 1)
    _check("vault delete blocked", bk("DELETE", "/backup-vaults/v1")[0] == 400)
    _check("restore needs target", bk("PUT", "/restore-jobs", {"RecoveryPointArn": rp, "Metadata": {}})[0] == 400)
    ddb("PutItem", {"TableName": "orders", "Item": {"id": {"S": "2"}}})
    s, d = bk("PUT", "/restore-jobs", {"RecoveryPointArn": rp, "Metadata": {"targetTableName": "orders-restored"}, "IamRoleArn": ROLE})
    j = bk("GET", f"/restore-jobs/{d['RestoreJobId']}")[1]
    _check("restore job created table", j["Status"] == "COMPLETED" and j["CreatedResourceArn"].endswith("table/orders-restored"))
    sc = ddb("Scan", {"TableName": "orders-restored"})[1]
    _check("restored table has backup-time items only", sc["Count"] == 1)
    j2 = bk("GET", f"/restore-jobs/{bk('PUT', '/restore-jobs', {'RecoveryPointArn': rp, 'Metadata': {'targetTableName': 'orders-restored'}})[1]['RestoreJobId']}")[1]
    _check("restore over existing fails", j2["Status"] == "FAILED")
    # S3
    r.handle("PUT", "/src-bkt", {}, H("s3"), b"")
    r.handle("PUT", "/src-bkt/a.txt", {}, H("s3"), b"hello")
    s, d = bk("PUT", "/backup-jobs", {"BackupVaultName": "v1", "ResourceArn": "arn:aws:s3:::src-bkt", "IamRoleArn": ROLE})
    _check("s3 backup", s == 200 and "recovery-point" in d["RecoveryPointArn"])
    s, d2 = bk("PUT", "/restore-jobs", {"RecoveryPointArn": d["RecoveryPointArn"], "Metadata": {"DestinationBucketName": "restored-bkt", "NewBucket": "true"}})
    o = r.handle("GET", "/restored-bkt/a.txt", {}, H("s3"), b"")
    _check("s3 restore wrote real objects", o["status"] == 200 and o["body"] == b"hello")
    _check("unsupported resource fails job", bk("GET", f"/backup-jobs/{bk('PUT', '/backup-jobs', {'BackupVaultName': 'v1', 'ResourceArn': 'arn:aws:ec2:us-east-1:123456789012:instance/i-1', 'IamRoleArn': ROLE})[1]['BackupJobId']}")[1]["State"] == "FAILED")
    # vault lock
    _check("lock bad range", bk("PUT", "/backup-vaults/v1/vault-lock", {"MinRetentionDays": 10, "MaxRetentionDays": 5})[0] == 400)
    _check("lock", bk("PUT", "/backup-vaults/v1/vault-lock", {"MinRetentionDays": 7, "MaxRetentionDays": 30, "ChangeableForDays": 3})[0] == 200)
    _check("locked vault shows Locked", bk("GET", "/backup-vaults/v1")[1]["Locked"] is True)
    _check("lifecycle outside lock range rejected", bk("PUT", "/backup-jobs", {"BackupVaultName": "v1", "ResourceArn": arn, "IamRoleArn": ROLE, "Lifecycle": {"DeleteAfterDays": 90}})[0] == 400)
    _check("locked: recovery point delete blocked", bk("DELETE", f"/backup-vaults/v1/recovery-points/{rp}")[0] == 400)
    _check("unlock inside cooling-off", bk("DELETE", "/backup-vaults/v1/vault-lock")[0] == 200)
    _check("delete recovery point", bk("DELETE", f"/backup-vaults/v1/recovery-points/{rp}")[0] == 200)
    _check("protected resources", len(bk("GET", "/resources/")[1]["Results"]) >= 1)
    print("aws backup vaults: all checks passed")


main()
