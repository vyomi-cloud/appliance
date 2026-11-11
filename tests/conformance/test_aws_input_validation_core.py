"""AWS cores refuse invalid input with a 4xx + the real AWS error code, never silent success (check 4).

Each case below was a SILENT SUCCESS (or wrong code) before; the SDK-level matrix that found them is
wasm/ui-tests/_aws_validation_sdk.py. Run on host:  PYTHONPATH=.:wasm/core python3 tests/conformance/test_aws_input_validation_core.py
"""
import json
import types

try:
    from core.nosql_store import InMemoryNoSqlStore
    from core.kms_keystore import InMemoryKeyStore
    from core.kv_store import InMemoryKvStore
    from core.messaging_store import InMemoryMessagingStore
    from core.sql_store import InMemorySqlStore
    from core.iam_store import InMemoryIamStore
    from core import dynamodb_core as ddb, kms_core as kms, secrets_core as sm, eventbridge_core as eb
    from core import sqs_core as sqs, vpc_core as vpc, rds_core as rds, iam_core as iam, lambda_core as lam
except ImportError:  # pragma: no cover - Pyodide flat layout
    from nosql_store import InMemoryNoSqlStore  # type: ignore
    from kms_keystore import InMemoryKeyStore  # type: ignore
    from kv_store import InMemoryKvStore  # type: ignore
    from messaging_store import InMemoryMessagingStore  # type: ignore
    from sql_store import InMemorySqlStore  # type: ignore
    from iam_store import InMemoryIamStore  # type: ignore
    import dynamodb_core as ddb, kms_core as kms, secrets_core as sm, eventbridge_core as eb  # type: ignore
    import sqs_core as sqs, vpc_core as vpc, rds_core as rds, iam_core as iam, lambda_core as lam  # type: ignore


def _check(name, cond, detail=""):
    if not cond:
        raise AssertionError(f"{name} {detail}")
    print(f"[PASS] {name}")


def _txt(r):
    b = r.body
    b = b.decode() if isinstance(b, bytes) else b
    return b if isinstance(b, str) else json.dumps(b)


def refused(name, r, code):
    _check(f"{name} -> {code}", r.status in range(400, 500) and code in _txt(r), f"got {r.status} {_txt(r)[:200]}")


def accepted(name, r):
    _check(f"{name} (valid input still accepted)", r.status == 200, f"got {r.status} {_txt(r)[:200]}")


def run():
    # ---- DynamoDB
    s = InMemoryNoSqlStore()
    P = "DynamoDB_20120810."
    ks = [{"AttributeName": "id", "KeyType": "HASH"}]
    ad = [{"AttributeName": "id", "AttributeType": "S"}]
    refused("DDB no KeySchema", ddb.dispatch(s, P + "CreateTable", {"TableName": "nokeys", "BillingMode": "PAY_PER_REQUEST"}), "ValidationException")
    refused("DDB 2-char name", ddb.dispatch(s, P + "CreateTable", {"TableName": "ab", "KeySchema": ks, "AttributeDefinitions": ad}), "ValidationException")
    refused("DDB unknown BillingMode", ddb.dispatch(s, P + "CreateTable", {"TableName": "bm1", "KeySchema": ks, "AttributeDefinitions": ad, "BillingMode": "FREE"}), "ValidationException")
    accepted("DDB good table", ddb.dispatch(s, P + "CreateTable", {"TableName": "good", "KeySchema": ks, "AttributeDefinitions": ad, "BillingMode": "PAY_PER_REQUEST"}))

    # ---- KMS
    k = InMemoryKeyStore()
    T = "TrentService."
    refused("KMS unknown KeySpec", kms.dispatch(k, T + "CreateKey", {"KeySpec": "ROT13"}), "ValidationException")
    accepted("KMS default key", kms.dispatch(k, T + "CreateKey", {}))
    kid = kms.dispatch(k, T + "CreateKey", {}).body["KeyMetadata"]["KeyId"]
    accepted("KMS alias", kms.dispatch(k, T + "CreateAlias", {"AliasName": "alias/a1", "TargetKeyId": kid}))
    refused("KMS duplicate alias", kms.dispatch(k, T + "CreateAlias", {"AliasName": "alias/a1", "TargetKeyId": kid}), "AlreadyExistsException")

    # ---- Secrets Manager
    v = InMemoryKvStore()
    S = "secretsmanager."
    refused("Secrets illegal name", sm.dispatch(v, S + "CreateSecret", {"Name": "bad name!#", "SecretString": "x"}), "ValidationException")
    accepted("Secrets good", sm.dispatch(v, S + "CreateSecret", {"Name": "good/name", "SecretString": "x"}))
    refused("Secrets force+window", sm.dispatch(v, S + "DeleteSecret", {"SecretId": "good/name", "RecoveryWindowInDays": 7, "ForceDeleteWithoutRecovery": True}), "InvalidParameterException")
    refused("Secrets string+binary", sm.dispatch(v, S + "CreateSecret", {"Name": "both", "SecretString": "a", "SecretBinary": "Yg=="}), "InvalidParameterException")

    # ---- EventBridge
    m = InMemoryMessagingStore()
    E = "AWSEvents."
    refused("EB bus illegal name", eb.dispatch(m, E + "CreateEventBus", {"Name": "bad name!"}), "ValidationException")
    refused("EB bad schedule", eb.dispatch(m, E + "PutRule", {"Name": "r1", "ScheduleExpression": "every now and then"}), "ValidationException")
    refused("EB bad cron fields", eb.dispatch(m, E + "PutRule", {"Name": "r2", "ScheduleExpression": "cron(99 99 * * ? *)"}), "ValidationException")
    refused("EB rate singular/plural", eb.dispatch(m, E + "PutRule", {"Name": "r3", "ScheduleExpression": "rate(1 hours)"}), "ValidationException")
    refused("EB neither pattern nor schedule", eb.dispatch(m, E + "PutRule", {"Name": "r4"}), "ValidationException")
    accepted("EB rate ok", eb.dispatch(m, E + "PutRule", {"Name": "r5", "ScheduleExpression": "rate(5 minutes)"}))
    accepted("EB cron ok", eb.dispatch(m, E + "PutRule", {"Name": "r6", "ScheduleExpression": "cron(0 12 * * ? *)"}))

    # ---- SQS
    refused("SQS VisibilityTimeout 99999", sqs.dispatch(m, "AmazonSQS.CreateQueue", {"QueueName": "q1", "Attributes": {"VisibilityTimeout": "99999"}}), "InvalidAttributeValue")
    sqs.dispatch(m, "AmazonSQS.CreateQueue", {"QueueName": "q2", "Attributes": {"VisibilityTimeout": "30"}})
    refused("SQS same name, other attributes", sqs.dispatch(m, "AmazonSQS.CreateQueue", {"QueueName": "q2", "Attributes": {"VisibilityTimeout": "60"}}), "QueueNameExists")

    # ---- VPC / EC2 (EC2 Query protocol)
    vs = types.SimpleNamespace()
    call = lambda **p: vpc.dispatch(vs, p)  # noqa: E731
    refused("VPC /8", call(Action="CreateVpc", CidrBlock="10.0.0.0/8"), "InvalidVpc.Range")
    refused("VPC /30", call(Action="CreateVpc", CidrBlock="10.0.0.0/30"), "InvalidVpc.Range")
    refused("VPC not a CIDR", call(Action="CreateVpc", CidrBlock="nope"), "InvalidParameterValue")
    import re
    vid = re.search(r"<vpcId>(vpc-\w+)</vpcId>", _txt(call(Action="CreateVpc", CidrBlock="10.7.0.0/16"))).group(1)
    accepted("subnet", call(Action="CreateSubnet", VpcId=vid, CidrBlock="10.7.1.0/24"))
    refused("overlapping subnet", call(Action="CreateSubnet", VpcId=vid, CidrBlock="10.7.1.0/25"), "InvalidSubnet.Conflict")
    refused("volume size 0", call(Action="CreateVolume", AvailabilityZone="us-east-1a", Size="0"), "InvalidParameterValue")
    refused("volume unknown AZ", call(Action="CreateVolume", AvailabilityZone="mars-north-1a", Size="8"), "InvalidParameterValue")
    refused("SG without description", call(Action="CreateSecurityGroup", GroupName="g1", VpcId=vid), "MissingParameter")
    refused("unknown instance type", call(Action="RunInstances", MinCount="1", MaxCount="1", InstanceType="zz9.mega"), "InvalidParameterValue")
    refused("MinCount 0", call(Action="RunInstances", MinCount="0", MaxCount="1"), "InvalidParameterValue")

    # ---- RDS
    r = InMemorySqlStore()
    base = {"Action": "CreateDBInstance", "DBInstanceIdentifier": "okdb", "Engine": "postgres", "MasterUsername": "u",
            "MasterUserPassword": "longenough1", "AllocatedStorage": "20"}
    refused("RDS short password", rds.dispatch(r, {**base, "MasterUserPassword": "short"}), "InvalidParameterValue")
    refused("RDS bad class", rds.dispatch(r, {**base, "DBInstanceClass": "db.zz9.mega"}), "InvalidParameterValue")
    refused("RDS bad engine", rds.dispatch(r, {**base, "Engine": "dbase3"}), "InvalidParameterValue")
    refused("RDS storage 1 GiB", rds.dispatch(r, {**base, "AllocatedStorage": "1"}), "InvalidParameterValue")
    refused("RDS identifier with underscore", rds.dispatch(r, {**base, "DBInstanceIdentifier": "bad_name!"}), "InvalidParameterValue")
    refused("RDS identifier starts with digit", rds.dispatch(r, {**base, "DBInstanceIdentifier": "1bad"}), "InvalidParameterValue")
    accepted("RDS good", rds.dispatch(r, base))
    refused("RDS delete with no snapshot choice", rds.dispatch(r, {"Action": "DeleteDBInstance", "DBInstanceIdentifier": "okdb"}), "InvalidParameterCombination")
    accepted("RDS delete with SkipFinalSnapshot", rds.dispatch(r, {"Action": "DeleteDBInstance", "DBInstanceIdentifier": "okdb", "SkipFinalSnapshot": "true"}))

    # ---- IAM
    i = InMemoryIamStore()
    refused("IAM user with a space", iam.dispatch(i, {"Action": "CreateUser", "UserName": "bad name!"}), "ValidationError")
    refused("IAM policy with no Statement", iam.dispatch(i, {"Action": "CreatePolicy", "PolicyName": "p1", "PolicyDocument": json.dumps({"Version": "2012-10-17"})}), "MalformedPolicyDocument")
    accepted("IAM user", iam.dispatch(i, {"Action": "CreateUser", "UserName": "alice.b@x-y"}))

    # ---- Lambda
    ls = types.SimpleNamespace()
    import base64
    import io
    import zipfile
    z = io.BytesIO()
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("index.py", "def handler(e, c):\n    return {}\n")
    fn = {"FunctionName": "f1", "Runtime": "python3.12", "Handler": "index.handler",
          "Role": "arn:aws:iam::123456789012:role/r", "Code": {"ZipFile": base64.b64encode(z.getvalue()).decode()}}
    mk = lambda **o: lam.dispatch(ls, "POST", "/2015-03-31/functions", {}, {}, json.dumps({**fn, **o}).encode())  # noqa: E731
    refused("Lambda unknown runtime", mk(FunctionName="f2", Runtime="cobol85"), "InvalidParameterValueException")
    refused("Lambda bad role ARN", mk(FunctionName="f3", Role="nope"), "InvalidParameterValueException")
    refused("Lambda memory 64", mk(FunctionName="f4", MemorySize=64), "InvalidParameterValueException")
    refused("Lambda timeout 1000", mk(FunctionName="f5", Timeout=1000), "InvalidParameterValueException")
    print("AWS INPUT VALIDATION OK")


if __name__ == "__main__":
    run()
