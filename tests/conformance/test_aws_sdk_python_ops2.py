"""boto3 (official SDK, endpoint changed only) against engine operations that no
SDK test called. Each check names the simulator operation it covers
(API Gateway CreateDeployment/GetResources/GetRestApis/PutIntegration, DynamoDB
SetTags/PutItemRecord/GetItemRecord/UpdateItemRecord/DeleteItemRecord/
QueryFilter/ScanFilter/CreateTableRecord/DeleteTableRecord, KMS SetKeyRotation/
SetKeyState, RDS CreateDbSnapshot/DescribeDbSnapshots/SetStatus, S3 DeleteVersion/DeleteMarkerResponse/InsertSimpleDeleteMarker/
ListAllBuckets, Secrets Manager PutValue)."""
import os
import sys
import uuid

import boto3

EP = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000")
KW = dict(endpoint_url=EP, region_name="us-east-1", aws_access_key_id="test", aws_secret_access_key="test")
failed = False
sfx = uuid.uuid4().hex[:8]


def check(name, fn):
    global failed
    try:
        ok = fn()
    except Exception as e:  # noqa: BLE001
        print(f"  {type(e).__name__}: {str(e)[:200]}")
        ok = False
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    failed = failed or not ok


def main():
    apigw, ddb, kms, rds, s3, sm = (boto3.client(n, **KW) for n in
                                    ("apigateway", "dynamodb", "kms", "rds", "s3", "secretsmanager"))

    # API Gateway
    api = apigw.create_rest_api(name=f"conf-api-{sfx}")["id"]
    check("apigateway GetRestApis lists the API", lambda: api in [a["id"] for a in apigw.get_rest_apis()["items"]])
    res = apigw.get_resources(restApiId=api)["items"]
    check("apigateway GetResources returns the root resource", lambda: any(r["path"] == "/" for r in res))
    root = next(r["id"] for r in res if r["path"] == "/")
    apigw.put_method(restApiId=api, resourceId=root, httpMethod="GET", authorizationType="NONE")
    check("apigateway PutIntegration is returned", lambda: apigw.put_integration(
        restApiId=api, resourceId=root, httpMethod="GET", type="MOCK")["type"] == "MOCK")
    check("apigateway CreateDeployment returns an id", lambda: bool(apigw.create_deployment(
        restApiId=api, stageName="prod").get("id")))

    # DynamoDB
    t = f"conf-ddb2-{sfx}"
    ddb.create_table(TableName=t, KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
                     AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}, {"AttributeName": "sk", "AttributeType": "S"}],
                     BillingMode="PAY_PER_REQUEST")
    check("dynamodb CreateTableRecord: DescribeTable shows both keys", lambda: [k["AttributeName"] for k in
          ddb.describe_table(TableName=t)["Table"]["KeySchema"]] == ["pk", "sk"])
    arn = ddb.describe_table(TableName=t)["Table"]["TableArn"]
    ddb.tag_resource(ResourceArn=arn, Tags=[{"Key": "env", "Value": "ci"}])
    check("dynamodb SetTags: ListTagsOfResource shows tag", lambda: {"Key": "env", "Value": "ci"} in
          ddb.list_tags_of_resource(ResourceArn=arn)["Tags"])
    k = {"pk": {"S": "u1"}, "sk": {"S": "a"}}
    ddb.put_item(TableName=t, Item={**k, "n": {"N": "1"}})
    ddb.put_item(TableName=t, Item={"pk": {"S": "u1"}, "sk": {"S": "b"}, "n": {"N": "2"}})
    check("dynamodb PutItemRecord/GetItemRecord round-trip", lambda: ddb.get_item(TableName=t, Key=k)["Item"]["n"]["N"] == "1")
    ddb.update_item(TableName=t, Key=k, UpdateExpression="SET n = :v", ExpressionAttributeValues={":v": {"N": "9"}})
    check("dynamodb UpdateItemRecord changes the attribute", lambda: ddb.get_item(TableName=t, Key=k)["Item"]["n"]["N"] == "9")
    check("dynamodb QueryFilter applies FilterExpression", lambda: [i["sk"]["S"] for i in ddb.query(
        TableName=t, KeyConditionExpression="pk = :p", FilterExpression="n > :m",
        ExpressionAttributeValues={":p": {"S": "u1"}, ":m": {"N": "5"}})["Items"]] == ["a"])
    check("dynamodb ScanFilter applies FilterExpression", lambda: [i["sk"]["S"] for i in ddb.scan(
        TableName=t, FilterExpression="n < :m", ExpressionAttributeValues={":m": {"N": "5"}})["Items"]] == ["b"])
    ddb.delete_item(TableName=t, Key=k)
    check("dynamodb DeleteItemRecord removes the item", lambda: "Item" not in ddb.get_item(TableName=t, Key=k))
    ddb.delete_table(TableName=t)
    check("dynamodb DeleteTableRecord removes the table", lambda: t not in ddb.list_tables()["TableNames"])

    # KMS
    key = kms.create_key(Description=f"conf-{sfx}")["KeyMetadata"]["KeyId"]
    kms.enable_key_rotation(KeyId=key)
    check("kms SetKeyRotation enables rotation", lambda: kms.get_key_rotation_status(KeyId=key)["KeyRotationEnabled"] is True)
    kms.disable_key(KeyId=key)
    check("kms SetKeyState disables the key", lambda: kms.describe_key(KeyId=key)["KeyMetadata"]["KeyState"] == "Disabled")

    # RDS
    db = f"conf-db2-{sfx}"
    rds.create_db_instance(DBInstanceIdentifier=db, DBInstanceClass="db.t3.micro", Engine="postgres",
                           MasterUsername="admin", MasterUserPassword="Passw0rd!x", AllocatedStorage=20)
    rds.create_db_snapshot(DBInstanceIdentifier=db, DBSnapshotIdentifier=f"snap-{sfx}")
    check("rds CreateDbSnapshot + DescribeDbSnapshots list it", lambda: f"snap-{sfx}" in [
        s["DBSnapshotIdentifier"] for s in rds.describe_db_snapshots(DBInstanceIdentifier=db)["DBSnapshots"]])
    rds.stop_db_instance(DBInstanceIdentifier=db)
    check("rds SetStatus: StopDBInstance leaves a stopped/stopping state", lambda: rds.describe_db_instances(
        DBInstanceIdentifier=db)["DBInstances"][0]["DBInstanceStatus"] in ("stopped", "stopping"))

    # S3
    b = f"conf-s3v-{sfx}"
    s3.create_bucket(Bucket=b)
    check("s3 ListAllBuckets includes the bucket", lambda: b in [x["Name"] for x in s3.list_buckets()["Buckets"]])
    s3.put_bucket_versioning(Bucket=b, VersioningConfiguration={"Status": "Enabled"})
    v1 = s3.put_object(Bucket=b, Key="o", Body=b"1")["VersionId"]
    dm = s3.delete_object(Bucket=b, Key="o")
    check("s3 InsertSimpleDeleteMarker/DeleteMarkerResponse: delete returns a marker", lambda: dm.get("DeleteMarker") is True and bool(dm.get("VersionId")))
    s3.delete_object(Bucket=b, Key="o", VersionId=v1)
    check("s3 DeleteVersion removes that version", lambda: v1 not in [v["VersionId"] for v in s3.list_object_versions(Bucket=b).get("Versions", [])])

    # Secrets Manager
    sec = f"conf-sec-{sfx}"
    sm.create_secret(Name=sec, SecretString="v1")
    sm.put_secret_value(SecretId=sec, SecretString="v2")
    check("secretsmanager PutValue: new version is current", lambda: sm.get_secret_value(SecretId=sec)["SecretString"] == "v2")

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
