"""DynamoDB backups stored in the simulator's own S3 + AWS Backup region settings / cross-Region copy jobs.

Run: PYTHONPATH=. ../appliance/.venv/bin/python tests/conformance/test_dynamodb_backup_s3.py
"""
import json

from core.aws_wire_router import AwsWireRouter

DDB = "AWS4-HMAC-SHA256 Credential=T/20261030/us-east-1/dynamodb/aws4_request, SignedHeaders=host, Signature=0"
S3 = "AWS4-HMAC-SHA256 Credential=T/20261030/us-east-1/s3/aws4_request, SignedHeaders=host, Signature=0"
BK = "AWS4-HMAC-SHA256 Credential=T/20261030/us-east-1/backup/aws4_request, SignedHeaders=host, Signature=0"
BUCKET = "vyomi-dynamodb-backups"


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


r = AwsWireRouter()


def ddb(action, payload):
    o = r.handle("POST", "/", {}, {"authorization": DDB, "x-amz-target": f"DynamoDB_20120810.{action}", "content-type": "application/x-amz-json-1.0"}, json.dumps(payload).encode())
    return o["status"], (json.loads(o["body"]) if o["body"] else {})


def bk(method, path, payload=None, query=None):
    o = r.handle(method, path, query or {}, {"authorization": BK, "content-type": "application/json"}, json.dumps(payload).encode() if payload is not None else b"")
    return o["status"], (json.loads(o["body"]) if o["body"] else {})


def s3_keys():
    o = r.handle("GET", f"/{BUCKET}", {"list-type": "2"}, {"authorization": S3}, b"")
    return o["status"], o["body"].decode()


def main():
    ddb("CreateTable", {"TableName": "orders", "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}],
                        "AttributeDefinitions": [{"AttributeName": "id", "AttributeType": "S"}], "BillingMode": "PAY_PER_REQUEST"})
    for i in range(3):
        ddb("PutItem", {"TableName": "orders", "Item": {"id": {"S": f"o{i}"}, "qty": {"N": str(i)}}})
    s, o = ddb("CreateBackup", {"TableName": "orders", "BackupName": "b1"})
    arn = o["BackupDetails"]["BackupArn"]
    _check("create backup", s == 200 and o["BackupDetails"]["BackupSizeBytes"] > 0)
    s, body = s3_keys()
    _check("backup artifacts are real objects in simulator S3", s == 200 and "AWSDynamoDB/backups/orders/" in body and "data/1.json" in body and "backup-metadata.json" in body)

    ddb("DeleteTable", {"TableName": "orders"})
    s, o = ddb("RestoreTableFromBackup", {"BackupArn": arn, "TargetTableName": "orders2"})
    _check("restore from S3-backed backup", s == 200)
    s, o = ddb("Scan", {"TableName": "orders2"})
    _check("restored items come back", s == 200 and sorted(i["id"]["S"] for i in o["Items"]) == ["o0", "o1", "o2"])
    _check("restored table is queryable", ddb("GetItem", {"TableName": "orders2", "Key": {"id": {"S": "o2"}}})[1]["Item"]["qty"]["N"] == "2")

    # AWS Backup settings + copy
    s, o = bk("GET", "/account-settings")
    _check("DescribeRegionSettings: DynamoDB on", s == 200 and o["ResourceTypeOptInPreference"]["DynamoDB"] is True and o["ResourceTypeManagementPreference"]["DynamoDB"] is True)
    dest = "arn:aws:backup:eu-west-1:123456789012:backup-vault:dr-vault"
    s, o = bk("PUT", "/copy-jobs", {"RecoveryPointArn": arn, "SourceBackupVaultName": "Default", "DestinationBackupVaultArn": dest, "IamRoleArn": "arn:aws:iam::123456789012:role/b"})
    _check("StartCopyJob", s == 200 and o["CopyJobId"])
    jid = o["CopyJobId"]
    s, o = bk("GET", f"/copy-jobs/{jid}")
    job = o["CopyJob"]
    _check("copy job completed with a destination recovery point in the destination Region",
           s == 200 and job["State"] == "COMPLETED" and ":dynamodb:eu-west-1:" in job["DestinationRecoveryPointArn"] and job["BackupSizeInBytes"] > 0)
    s, body = s3_keys()
    _check("copy wrote its own S3 artifact", "backup-copies/123456789012/eu-west-1/dr-vault/" in body)
    s, o = ddb("ListBackups", {"TableName": "orders"})
    _check("copied backup is listed as AWS_BACKUP", {b["BackupType"] for b in o["BackupSummaries"]} == {"USER", "AWS_BACKUP"})
    s, o = ddb("RestoreTableFromBackup", {"BackupArn": job["DestinationRecoveryPointArn"], "TargetTableName": "orders-dr"})
    _check("copy is restorable", s == 200 and len(ddb("Scan", {"TableName": "orders-dr"})[1]["Items"]) == 3)
    _check("ListCopyJobs", len(bk("GET", "/copy-jobs")[1]["CopyJobs"]) == 1)
    _check("unknown recovery point 404", bk("PUT", "/copy-jobs", {"RecoveryPointArn": arn + "x", "SourceBackupVaultName": "Default", "DestinationBackupVaultArn": dest, "IamRoleArn": "r"})[0] == 404)
    _check("bad vault ARN 400", bk("PUT", "/copy-jobs", {"RecoveryPointArn": arn, "SourceBackupVaultName": "Default", "DestinationBackupVaultArn": "nope", "IamRoleArn": "r"})[0] == 400)

    # turn the integration off -> copy refused; on again -> works
    _check("turn off AWS Backup integration", bk("PUT", "/account-settings", {"ResourceTypeManagementPreference": {"DynamoDB": False}})[0] == 200
           and bk("GET", "/account-settings")[1]["ResourceTypeManagementPreference"]["DynamoDB"] is False)
    s, o = bk("PUT", "/copy-jobs", {"RecoveryPointArn": arn, "SourceBackupVaultName": "Default", "DestinationBackupVaultArn": dest, "IamRoleArn": "r"})
    _check("copy refused while off", s == 400 and "turned off" in o["Message"])
    bk("PUT", "/account-settings", {"ResourceTypeManagementPreference": {"DynamoDB": True}})
    _check("copy works again when on", bk("PUT", "/copy-jobs", {"RecoveryPointArn": arn, "SourceBackupVaultName": "Default", "DestinationBackupVaultArn": dest, "IamRoleArn": "r"})[0] == 200)

    # deleting the real S3 object breaks the backup like in AWS
    r.handle("DELETE", f"/{BUCKET}/AWSDynamoDB/backups/orders/{arn.rsplit('/', 1)[1]}/data/1.json", {}, {"authorization": S3}, b"")
    s, o = ddb("RestoreTableFromBackup", {"BackupArn": arn, "TargetTableName": "orders3"})
    _check("restore fails when the S3 data object is gone", s == 400 and o["__type"].endswith("BackupNotFoundException"))
    s, o = bk("PUT", "/copy-jobs", {"RecoveryPointArn": arn, "SourceBackupVaultName": "Default", "DestinationBackupVaultArn": dest, "IamRoleArn": "r"})
    _check("copy job FAILED when source data is gone", bk("GET", f"/copy-jobs/{o['CopyJobId']}")[1]["CopyJob"]["State"] == "FAILED")

    # DeleteBackup removes the objects
    s, o = ddb("CreateBackup", {"TableName": "orders2", "BackupName": "b2"})
    arn2 = o["BackupDetails"]["BackupArn"]
    pre = f"AWSDynamoDB/backups/orders2/{arn2.rsplit('/', 1)[1]}"
    _check("second backup present in S3", pre in s3_keys()[1])
    ddb("DeleteBackup", {"BackupArn": arn2})
    _check("DeleteBackup removes its S3 objects", pre not in s3_keys()[1])
    print("DynamoDB backup S3 + AWS Backup copy: ALL GREEN")


main()
