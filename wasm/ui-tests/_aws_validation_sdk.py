"""SDK half of the AWS validation matrix (check 4): invalid input must be refused with a 4xx, the real AWS error code
and a human-readable message - never a 5xx, a stack trace, 'undefined', an empty message, or silent success.

    VYOMI_BASE_URL=http://127.0.0.1:8771/_wire python3 _aws_validation_sdk.py [svc,svc,...]

boto3 with client-side parameter validation OFF (so the SERVER's validation is what is tested) and no retries.
Prints `[PASS]/[FAIL] <svc>: <case>` lines and a final `N/M passed`. Exit 1 on any FAIL.
"""
import json
import os
import sys
import time

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

EP = os.environ.get("VYOMI_BASE_URL", "http://127.0.0.1:8771/_wire").rstrip("/")
U = str(int(time.time()))[-6:]
CFG = Config(parameter_validation=False, retries={"max_attempts": 0}, connect_timeout=10, read_timeout=60)
KW = dict(endpoint_url=EP, region_name="us-east-1", aws_access_key_id="test", aws_secret_access_key="test", config=CFG)
_clients = {}


def c(name):
    if name not in _clients:
        _clients[name] = boto3.client(name, **KW)
    return _clients[name]


BAD_MSG = ("Traceback", "undefined", "[object", "NoneType", "KeyError", "AttributeError", "TypeError", "Internal Server")
CASES = []   # (service, label, fn, expected codes)


def case(svc, label, expect):
    def deco(fn):
        CASES.append((svc, label, fn, tuple(expect)))
        return fn
    return deco


def run_case(svc, label, fn, expect):
    try:
        fn()
    except ClientError as e:
        st = e.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0)
        code = e.response.get("Error", {}).get("Code", "")
        msg = e.response.get("Error", {}).get("Message", "") or ""
        short = code.split("#")[-1].split(":")[0]
        if st >= 500:
            return False, f"HTTP {st} {code}: {msg[:140]}"
        if not msg.strip():
            return False, f"{code} has an empty message"
        if any(b in msg for b in BAD_MSG):
            return False, f"{code} message leaks internals: {msg[:140]}"
        if expect and short not in expect and code not in expect:
            return False, f"wrong code {code!r} (want {'/'.join(expect)}): {msg[:120]}"
        return True, f"{code}"
    except Exception as e:  # botocore parse failure, connection error, ...
        return False, f"{type(e).__name__}: {str(e)[:160]}"
    return False, "SILENT SUCCESS (the call was accepted)"


def pre(fn):
    """setup step that must succeed; ignore 'already exists' so reruns work"""
    try:
        return fn()
    except ClientError:
        return None


# ---------------------------------------------------------------- S3
@case("s3", "bucket name with uppercase/underscore", ["InvalidBucketName"])
def _(): c("s3").create_bucket(Bucket="Bad_Bucket_Name")
@case("s3", "bucket name too short (2 chars)", ["InvalidBucketName"])
def _(): c("s3").create_bucket(Bucket="ab")
@case("s3", "bucket name too long (64 chars)", ["InvalidBucketName"])
def _(): c("s3").create_bucket(Bucket="a" * 64)
@case("s3", "delete a bucket that does not exist", ["NoSuchBucket"])
def _(): c("s3").delete_bucket(Bucket=f"nope-{U}-zz")
@case("s3", "put object into a missing bucket", ["NoSuchBucket"])
def _(): c("s3").put_object(Bucket=f"nope-{U}-zz", Key="k", Body=b"x")
@case("s3", "get a missing key", ["NoSuchKey"])
def _():
    pre(lambda: c("s3").create_bucket(Bucket=f"val-s3-{U}"))
    c("s3").get_object(Bucket=f"val-s3-{U}", Key="missing")
@case("s3", "delete a non-empty bucket", ["BucketNotEmpty"])
def _():
    pre(lambda: c("s3").create_bucket(Bucket=f"val-s3ne-{U}"))
    c("s3").put_object(Bucket=f"val-s3ne-{U}", Key="k", Body=b"x")
    c("s3").delete_bucket(Bucket=f"val-s3ne-{U}")
@case("s3", "bucket tagging with a malformed body is refused", ["MalformedXML", "InvalidTag", "InvalidArgument"])
def _():
    pre(lambda: c("s3").create_bucket(Bucket=f"val-s3t-{U}"))
    c("s3").put_bucket_tagging(Bucket=f"val-s3t-{U}", Tagging={"TagSet": [{"Key": "", "Value": "v"}]})

# ---------------------------------------------------------------- SQS
@case("sqs", "queue name with illegal characters", ["InvalidParameterValue", "InvalidAttributeName", "AWS.SimpleQueueService.InvalidName"])
def _(): c("sqs").create_queue(QueueName="bad name!")
@case("sqs", "queue name over 80 characters", ["InvalidParameterValue", "InvalidAttributeName"])
def _(): c("sqs").create_queue(QueueName="q" * 81)
@case("sqs", "FIFO attribute on a queue name without .fifo", ["InvalidParameterValue", "InvalidAttributeName"])
def _(): c("sqs").create_queue(QueueName=f"val-notfifo-{U}", Attributes={"FifoQueue": "true"})
@case("sqs", "same queue name, different attributes", ["QueueNameExists"])
def _():
    pre(lambda: c("sqs").create_queue(QueueName=f"val-dup-{U}", Attributes={"VisibilityTimeout": "30"}))
    c("sqs").create_queue(QueueName=f"val-dup-{U}", Attributes={"VisibilityTimeout": "60"})
@case("sqs", "VisibilityTimeout out of range (99999)", ["InvalidParameterValue", "InvalidAttributeValue"])
def _(): c("sqs").create_queue(QueueName=f"val-vt-{U}", Attributes={"VisibilityTimeout": "99999"})
@case("sqs", "get URL of a missing queue", ["AWS.SimpleQueueService.NonExistentQueue", "QueueDoesNotExist", "NonExistentQueue"])
def _(): c("sqs").get_queue_url(QueueName=f"nope-{U}")
@case("sqs", "send a message over 256 KiB", ["InvalidParameterValue", "InvalidMessageContents", "MessageTooLong"])
def _():
    q = pre(lambda: c("sqs").create_queue(QueueName=f"val-big-{U}")) or c("sqs").create_queue(QueueName=f"val-big-{U}")
    c("sqs").send_message(QueueUrl=q["QueueUrl"], MessageBody="x" * (262144 + 10))
@case("sqs", "send to a missing queue URL", ["AWS.SimpleQueueService.NonExistentQueue", "QueueDoesNotExist", "NonExistentQueue"])
def _(): c("sqs").send_message(QueueUrl="https://sqs.us-east-1.amazonaws.com/123456789012/nope-" + U, MessageBody="x")

# ---------------------------------------------------------------- SNS
@case("sns", "topic name with illegal characters", ["InvalidParameter", "InvalidParameterValue"])
def _(): c("sns").create_topic(Name="bad name!")
@case("sns", "empty topic name", ["InvalidParameter", "InvalidParameterValue", "ValidationError"])
def _(): c("sns").create_topic(Name="")
@case("sns", "topic name over 256 characters", ["InvalidParameter", "InvalidParameterValue"])
def _(): c("sns").create_topic(Name="t" * 257)
@case("sns", "publish to a missing topic", ["NotFound", "NotFoundException"])
def _(): c("sns").publish(TopicArn=f"arn:aws:sns:us-east-1:123456789012:nope-{U}", Message="m")
@case("sns", "subscribe with an unsupported protocol", ["InvalidParameter", "InvalidParameterValue"])
def _():
    t = c("sns").create_topic(Name=f"val-sub-{U}")["TopicArn"]
    c("sns").subscribe(TopicArn=t, Protocol="carrier-pigeon", Endpoint="x")
@case("sns", "publish with an empty message", ["InvalidParameter", "InvalidParameterValue"])
def _():
    t = c("sns").create_topic(Name=f"val-pub-{U}")["TopicArn"]
    c("sns").publish(TopicArn=t, Message="")

# ---------------------------------------------------------------- DynamoDB
@case("dynamodb", "create table with no key schema", ["ValidationException"])
def _(): c("dynamodb").create_table(TableName=f"val-nk-{U}", BillingMode="PAY_PER_REQUEST")
@case("dynamodb", "table name too short (2 chars)", ["ValidationException"])
def _(): c("dynamodb").create_table(TableName="ab", KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}], AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}], BillingMode="PAY_PER_REQUEST")
@case("dynamodb", "table name with illegal characters", ["ValidationException"])
def _(): c("dynamodb").create_table(TableName="bad name!", KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}], AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}], BillingMode="PAY_PER_REQUEST")
@case("dynamodb", "duplicate table", ["ResourceInUseException"])
def _():
    kw = dict(TableName=f"val-dup-{U}", KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}], AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}], BillingMode="PAY_PER_REQUEST")
    pre(lambda: c("dynamodb").create_table(**kw))
    c("dynamodb").create_table(**kw)
@case("dynamodb", "describe a missing table", ["ResourceNotFoundException"])
def _(): c("dynamodb").describe_table(TableName=f"nope-{U}")
@case("dynamodb", "put item without the key attribute", ["ValidationException"])
def _():
    pre(lambda: c("dynamodb").create_table(TableName=f"val-pi-{U}", KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}], AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}], BillingMode="PAY_PER_REQUEST"))
    c("dynamodb").put_item(TableName=f"val-pi-{U}", Item={"other": {"S": "x"}})
@case("dynamodb", "put item with the wrong key type", ["ValidationException"])
def _():
    pre(lambda: c("dynamodb").create_table(TableName=f"val-pt-{U}", KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}], AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}], BillingMode="PAY_PER_REQUEST"))
    c("dynamodb").put_item(TableName=f"val-pt-{U}", Item={"id": {"N": "5"}})
@case("dynamodb", "unknown BillingMode", ["ValidationException"])
def _(): c("dynamodb").create_table(TableName=f"val-bm-{U}", KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}], AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}], BillingMode="FREE")

# ---------------------------------------------------------------- KMS
@case("kms", "unknown KeySpec", ["ValidationException", "UnsupportedOperationException"])
def _(): c("kms").create_key(KeySpec="ROT13")
@case("kms", "describe an unknown key", ["NotFoundException", "InvalidArnException"])
def _(): c("kms").describe_key(KeyId="11111111-2222-3333-4444-555555555555")
@case("kms", "alias without the alias/ prefix", ["ValidationException"])
def _():
    k = c("kms").create_key()["KeyMetadata"]["KeyId"]
    c("kms").create_alias(AliasName=f"noprefix-{U}", TargetKeyId=k)
@case("kms", "duplicate alias", ["AlreadyExistsException"])
def _():
    k = c("kms").create_key()["KeyMetadata"]["KeyId"]
    pre(lambda: c("kms").create_alias(AliasName=f"alias/val-dup-{U}", TargetKeyId=k))
    c("kms").create_alias(AliasName=f"alias/val-dup-{U}", TargetKeyId=k)
@case("kms", "deletion window of 3 days (min 7)", ["ValidationException"])
def _():
    k = c("kms").create_key()["KeyMetadata"]["KeyId"]
    c("kms").schedule_key_deletion(KeyId=k, PendingWindowInDays=3)
@case("kms", "encrypt with an unknown key", ["NotFoundException", "InvalidArnException"])
def _(): c("kms").encrypt(KeyId="11111111-2222-3333-4444-555555555555", Plaintext=b"x")
@case("kms", "alias that targets a missing key", ["NotFoundException"])
def _(): c("kms").create_alias(AliasName=f"alias/val-tgt-{U}", TargetKeyId="11111111-2222-3333-4444-555555555555")

# ---------------------------------------------------------------- Secrets Manager
@case("secretsmanager", "empty secret name", ["InvalidParameterException", "ValidationException"])
def _(): c("secretsmanager").create_secret(Name="", SecretString="v")
@case("secretsmanager", "secret name with illegal characters", ["InvalidParameterException", "ValidationException"])
def _(): c("secretsmanager").create_secret(Name="bad name!#", SecretString="v")
@case("secretsmanager", "duplicate secret", ["ResourceExistsException"])
def _():
    pre(lambda: c("secretsmanager").create_secret(Name=f"val-dup-{U}", SecretString="v"))
    c("secretsmanager").create_secret(Name=f"val-dup-{U}", SecretString="v")
@case("secretsmanager", "get a missing secret", ["ResourceNotFoundException"])
def _(): c("secretsmanager").get_secret_value(SecretId=f"nope-{U}")
@case("secretsmanager", "recovery window and force-delete together", ["InvalidParameterException"])
def _():
    pre(lambda: c("secretsmanager").create_secret(Name=f"val-both-{U}", SecretString="v"))
    c("secretsmanager").delete_secret(SecretId=f"val-both-{U}", RecoveryWindowInDays=7, ForceDeleteWithoutRecovery=True)
@case("secretsmanager", "recovery window of 3 days (min 7)", ["InvalidParameterException"])
def _():
    pre(lambda: c("secretsmanager").create_secret(Name=f"val-rw-{U}", SecretString="v"))
    c("secretsmanager").delete_secret(SecretId=f"val-rw-{U}", RecoveryWindowInDays=3)
@case("secretsmanager", "secret with neither string nor binary is allowed; both is not", ["InvalidParameterException"])
def _(): c("secretsmanager").create_secret(Name=f"val-sb-{U}", SecretString="a", SecretBinary=b"b")

# ---------------------------------------------------------------- IAM
@case("iam", "user name with illegal characters", ["ValidationError", "InvalidInput"])
def _(): c("iam").create_user(UserName="bad name!")
@case("iam", "empty user name", ["ValidationError", "InvalidInput"])
def _(): c("iam").create_user(UserName="")
@case("iam", "duplicate user", ["EntityAlreadyExists"])
def _():
    pre(lambda: c("iam").create_user(UserName=f"valdup{U}"))
    c("iam").create_user(UserName=f"valdup{U}")
@case("iam", "get a missing user", ["NoSuchEntity"])
def _(): c("iam").get_user(UserName=f"nope{U}")
@case("iam", "policy document that is not JSON", ["MalformedPolicyDocument"])
def _(): c("iam").create_policy(PolicyName=f"valbad{U}", PolicyDocument="{not json")
@case("iam", "policy document with no Statement", ["MalformedPolicyDocument"])
def _(): c("iam").create_policy(PolicyName=f"valnos{U}", PolicyDocument=json.dumps({"Version": "2012-10-17"}))
@case("iam", "attach a malformed policy ARN", ["InvalidInput", "ValidationError", "NoSuchEntity"])
def _():
    pre(lambda: c("iam").create_user(UserName=f"valatt{U}"))
    c("iam").attach_user_policy(UserName=f"valatt{U}", PolicyArn="not-an-arn")
@case("iam", "role with a malformed trust policy", ["MalformedPolicyDocument"])
def _(): c("iam").create_role(RoleName=f"valrole{U}", AssumeRolePolicyDocument="nope")
@case("iam", "delete a user that has an access key", ["DeleteConflict"])
def _():
    pre(lambda: c("iam").create_user(UserName=f"valdel{U}"))
    pre(lambda: c("iam").create_access_key(UserName=f"valdel{U}"))
    c("iam").delete_user(UserName=f"valdel{U}")

# ---------------------------------------------------------------- VPC
@case("vpc", "malformed CIDR", ["InvalidParameterValue", "InvalidVpc.Range"])
def _(): c("ec2").create_vpc(CidrBlock="not-a-cidr")
@case("vpc", "CIDR /8 (outside /16-/28)", ["InvalidVpc.Range", "InvalidParameterValue"])
def _(): c("ec2").create_vpc(CidrBlock="10.0.0.0/8")
@case("vpc", "CIDR /30 (outside /16-/28)", ["InvalidVpc.Range", "InvalidParameterValue"])
def _(): c("ec2").create_vpc(CidrBlock="10.0.0.0/30")
@case("vpc", "subnet in a missing VPC", ["InvalidVpcID.NotFound"])
def _(): c("ec2").create_subnet(VpcId="vpc-deadbeef0000", CidrBlock="10.0.1.0/24")
@case("vpc", "subnet outside the VPC CIDR", ["InvalidSubnet.Range"])
def _():
    v = c("ec2").create_vpc(CidrBlock="10.50.0.0/16")["Vpc"]["VpcId"]
    c("ec2").create_subnet(VpcId=v, CidrBlock="192.168.0.0/24")
@case("vpc", "overlapping subnets", ["InvalidSubnet.Conflict"])
def _():
    v = c("ec2").create_vpc(CidrBlock="10.51.0.0/16")["Vpc"]["VpcId"]
    c("ec2").create_subnet(VpcId=v, CidrBlock="10.51.1.0/24")
    c("ec2").create_subnet(VpcId=v, CidrBlock="10.51.1.0/25")
@case("vpc", "delete a VPC that still has a subnet", ["DependencyViolation"])
def _():
    v = c("ec2").create_vpc(CidrBlock="10.52.0.0/16")["Vpc"]["VpcId"]
    c("ec2").create_subnet(VpcId=v, CidrBlock="10.52.1.0/24")
    c("ec2").delete_vpc(VpcId=v)
@case("vpc", "delete a missing VPC", ["InvalidVpcID.NotFound"])
def _(): c("ec2").delete_vpc(VpcId="vpc-deadbeef0000")

# ---------------------------------------------------------------- EC2
@case("ec2", "duplicate key pair", ["InvalidKeyPair.Duplicate"])
def _():
    pre(lambda: c("ec2").create_key_pair(KeyName=f"val-kp-{U}"))
    c("ec2").create_key_pair(KeyName=f"val-kp-{U}")
@case("ec2", "RunInstances with an unknown AMI", ["InvalidAMIID.NotFound", "InvalidAMIID.Malformed"])
def _(): c("ec2").run_instances(ImageId="ami-00000000deadbeef", MinCount=1, MaxCount=1, InstanceType="t3.micro")
@case("ec2", "RunInstances with MinCount 0", ["InvalidParameterValue"])
def _(): c("ec2").run_instances(ImageId="ami-00000000deadbeef", MinCount=0, MaxCount=1)
@case("ec2", "RunInstances with an unknown instance type", ["InvalidParameterValue", "InvalidInstanceType"])
def _():
    ami = c("ec2").describe_images()["Images"]
    c("ec2").run_instances(ImageId=(ami[0]["ImageId"] if ami else "ami-12345678"), MinCount=1, MaxCount=1, InstanceType="zz9.mega")
@case("ec2", "terminate an unknown instance", ["InvalidInstanceID.NotFound", "InvalidInstanceID.Malformed"])
def _(): c("ec2").terminate_instances(InstanceIds=["i-00000000deadbeef"])
@case("ec2", "volume of size 0", ["InvalidParameterValue", "VolumeSize"])
def _(): c("ec2").create_volume(AvailabilityZone="us-east-1a", Size=0)
@case("ec2", "volume in an unknown AZ", ["InvalidParameterValue", "InvalidZone.NotFound"])
def _(): c("ec2").create_volume(AvailabilityZone="mars-north-1a", Size=8)
@case("ec2", "security group with no description", ["MissingParameter", "InvalidParameterValue"])
def _(): c("ec2").create_security_group(GroupName=f"val-sg-{U}", Description="")

# ---------------------------------------------------------------- SSM
@case("ssm", "duplicate parameter without Overwrite", ["ParameterAlreadyExists"])
def _():
    pre(lambda: c("ssm").put_parameter(Name=f"/val/dup{U}", Value="v", Type="String"))
    c("ssm").put_parameter(Name=f"/val/dup{U}", Value="v", Type="String")
@case("ssm", "parameter name starting with aws", ["ValidationException"])
def _(): c("ssm").put_parameter(Name=f"/aws/val{U}", Value="v", Type="String")
@case("ssm", "unknown parameter Type", ["ValidationException", "UnsupportedParameterType"])
def _(): c("ssm").put_parameter(Name=f"/val/ty{U}", Value="v", Type="Blob")
@case("ssm", "get a missing parameter", ["ParameterNotFound"])
def _(): c("ssm").get_parameter(Name=f"/val/nope{U}")
@case("ssm", "standard parameter over 4 KB", ["ValidationException", "ParameterMaxVersionLimitExceeded"])
def _(): c("ssm").put_parameter(Name=f"/val/big{U}", Value="x" * 5000, Type="String")
@case("ssm", "empty parameter value", ["ValidationException"])
def _(): c("ssm").put_parameter(Name=f"/val/empty{U}", Value="", Type="String")

# ---------------------------------------------------------------- Kinesis
@case("kinesis", "duplicate stream", ["ResourceInUseException"])
def _():
    pre(lambda: c("kinesis").create_stream(StreamName=f"val-dup-{U}", ShardCount=1))
    c("kinesis").create_stream(StreamName=f"val-dup-{U}", ShardCount=1)
@case("kinesis", "shard count 0", ["InvalidArgumentException", "ValidationException"])
def _(): c("kinesis").create_stream(StreamName=f"val-sc-{U}", ShardCount=0)
@case("kinesis", "stream name with illegal characters", ["InvalidArgumentException", "ValidationException"])
def _(): c("kinesis").create_stream(StreamName="bad name!", ShardCount=1)
@case("kinesis", "describe a missing stream", ["ResourceNotFoundException"])
def _(): c("kinesis").describe_stream(StreamName=f"nope-{U}")
@case("kinesis", "put a record to a missing stream", ["ResourceNotFoundException"])
def _(): c("kinesis").put_record(StreamName=f"nope-{U}", Data=b"x", PartitionKey="p")

# ---------------------------------------------------------------- ECR
@case("ecr", "repository name in upper case", ["InvalidParameterException"])
def _(): c("ecr").create_repository(repositoryName="UPPER/Case")
@case("ecr", "repository name too short", ["InvalidParameterException"])
def _(): c("ecr").create_repository(repositoryName="a")
@case("ecr", "duplicate repository", ["RepositoryAlreadyExistsException"])
def _():
    pre(lambda: c("ecr").create_repository(repositoryName=f"val-dup-{U}"))
    c("ecr").create_repository(repositoryName=f"val-dup-{U}")
@case("ecr", "describe a missing repository", ["RepositoryNotFoundException"])
def _(): c("ecr").describe_repositories(repositoryNames=[f"nope-{U}"])
@case("ecr", "delete a missing repository", ["RepositoryNotFoundException"])
def _(): c("ecr").delete_repository(repositoryName=f"nope-{U}")

# ---------------------------------------------------------------- EventBridge
@case("eventbridge", "event bus name with illegal characters", ["ValidationException"])
def _(): c("events").create_event_bus(Name="bad name!")
@case("eventbridge", "duplicate event bus", ["ResourceAlreadyExistsException"])
def _():
    pre(lambda: c("events").create_event_bus(Name=f"val-dup-{U}"))
    c("events").create_event_bus(Name=f"val-dup-{U}")
@case("eventbridge", "rule with an invalid schedule expression", ["ValidationException"])
def _(): c("events").put_rule(Name=f"val-cron-{U}", ScheduleExpression="every now and then")
@case("eventbridge", "rule with invalid cron fields", ["ValidationException"])
def _(): c("events").put_rule(Name=f"val-cron2-{U}", ScheduleExpression="cron(99 99 * * ? *)")
@case("eventbridge", "rule with a malformed event pattern", ["InvalidEventPatternException"])
def _(): c("events").put_rule(Name=f"val-pat-{U}", EventPattern="{not json")
@case("eventbridge", "rule with neither pattern nor schedule", ["ValidationException"])
def _(): c("events").put_rule(Name=f"val-none-{U}")
@case("eventbridge", "describe a missing rule", ["ResourceNotFoundException"])
def _(): c("events").describe_rule(Name=f"nope-{U}")

# ---------------------------------------------------------------- CloudWatch Logs
@case("cloudwatch", "duplicate log group", ["ResourceAlreadyExistsException"])
def _():
    pre(lambda: c("logs").create_log_group(logGroupName=f"/val/dup{U}"))
    c("logs").create_log_group(logGroupName=f"/val/dup{U}")
@case("cloudwatch", "log group name with illegal characters", ["InvalidParameterException"])
def _(): c("logs").create_log_group(logGroupName="bad name with spaces!")
@case("cloudwatch", "log group name over 512 characters", ["InvalidParameterException"])
def _(): c("logs").create_log_group(logGroupName="/g/" + "x" * 520)
@case("cloudwatch", "retention of 8 days (not an allowed value)", ["InvalidParameterException"])
def _():
    pre(lambda: c("logs").create_log_group(logGroupName=f"/val/ret{U}"))
    c("logs").put_retention_policy(logGroupName=f"/val/ret{U}", retentionInDays=8)
@case("cloudwatch", "put events to a missing group", ["ResourceNotFoundException"])
def _(): c("logs").put_log_events(logGroupName=f"/val/nope{U}", logStreamName="s", logEvents=[{"timestamp": 1, "message": "m"}])
@case("cloudwatch", "alarm with an unknown comparison operator", ["ValidationError", "InvalidParameterValue"])
def _(): c("cloudwatch").put_metric_alarm(AlarmName=f"val-{U}", MetricName="m", Namespace="n", Statistic="Average", Period=60, EvaluationPeriods=1, Threshold=1.0, ComparisonOperator="Sideways")

# ---------------------------------------------------------------- API Gateway
@case("apigateway", "REST API with no name", ["BadRequestException"])
def _(): c("apigateway").create_rest_api(name="")
@case("apigateway", "get a missing REST API", ["NotFoundException"])
def _(): c("apigateway").get_rest_api(restApiId="zzzzzzzzzz")
@case("apigateway", "resource under a missing parent", ["NotFoundException"])
def _():
    a = c("apigateway").create_rest_api(name=f"val-{U}")["id"]
    c("apigateway").create_resource(restApiId=a, parentId="zzzzzzzzzz", pathPart="x")
@case("apigateway", "resource path part with illegal characters", ["BadRequestException"])
def _():
    a = c("apigateway").create_rest_api(name=f"val2-{U}")["id"]
    root = [r for r in c("apigateway").get_resources(restApiId=a)["items"] if r["path"] == "/"][0]["id"]
    c("apigateway").create_resource(restApiId=a, parentId=root, pathPart="bad path!")

# ---------------------------------------------------------------- Backup
@case("backup", "duplicate vault", ["AlreadyExistsException"])
def _():
    pre(lambda: c("backup").create_backup_vault(BackupVaultName=f"val-dup-{U}"))
    c("backup").create_backup_vault(BackupVaultName=f"val-dup-{U}")
@case("backup", "vault name with illegal characters", ["InvalidParameterValueException"])
def _(): c("backup").create_backup_vault(BackupVaultName="bad name!")
@case("backup", "describe a missing vault", ["ResourceNotFoundException"])
def _(): c("backup").describe_backup_vault(BackupVaultName=f"nope-{U}")
@case("backup", "plan with no rules", ["InvalidParameterValueException", "MissingParameterValueException"])
def _(): c("backup").create_backup_plan(BackupPlan={"BackupPlanName": f"val-{U}", "Rules": []})

# ---------------------------------------------------------------- Network Manager
@case("networkmanager", "delete a missing global network", ["ResourceNotFoundException", "ValidationException"])
def _(): c("networkmanager").delete_global_network(GlobalNetworkId="global-network-00000000deadbeef")
@case("networkmanager", "site in a missing global network", ["ResourceNotFoundException", "ValidationException"])
def _(): c("networkmanager").create_site(GlobalNetworkId="global-network-00000000deadbeef")

# ---------------------------------------------------------------- Step Functions
ROLE = "arn:aws:iam::123456789012:role/sf"
DEFN = json.dumps({"StartAt": "P", "States": {"P": {"Type": "Pass", "End": True}}})
@case("states", "definition that is not JSON", ["InvalidDefinition"])
def _(): c("stepfunctions").create_state_machine(name=f"val-d-{U}", definition="{nope", roleArn=ROLE)
@case("states", "definition whose StartAt is missing", ["InvalidDefinition"])
def _(): c("stepfunctions").create_state_machine(name=f"val-s-{U}", definition=json.dumps({"States": {"P": {"Type": "Pass", "End": True}}}), roleArn=ROLE)
@case("states", "state machine name with illegal characters", ["InvalidName"])
def _(): c("stepfunctions").create_state_machine(name="bad name!", definition=DEFN, roleArn=ROLE)
@case("states", "malformed role ARN", ["InvalidArn", "ValidationException"])
def _(): c("stepfunctions").create_state_machine(name=f"val-r-{U}", definition=DEFN, roleArn="not-an-arn")
@case("states", "duplicate state machine with a different definition", ["StateMachineAlreadyExists"])
def _():
    pre(lambda: c("stepfunctions").create_state_machine(name=f"val-dup-{U}", definition=DEFN, roleArn=ROLE))
    c("stepfunctions").create_state_machine(name=f"val-dup-{U}", definition=json.dumps({"StartAt": "Q", "States": {"Q": {"Type": "Pass", "End": True}}}), roleArn=ROLE)
@case("states", "describe a missing state machine", ["StateMachineDoesNotExist"])
def _(): c("stepfunctions").describe_state_machine(stateMachineArn=f"arn:aws:states:us-east-1:123456789012:stateMachine:nope{U}")
@case("states", "start an execution with non-JSON input", ["InvalidExecutionInput"])
def _():
    sm = c("stepfunctions").create_state_machine(name=f"val-ex-{U}", definition=DEFN, roleArn=ROLE)["stateMachineArn"]
    c("stepfunctions").start_execution(stateMachineArn=sm, input="{nope")

# ---------------------------------------------------------------- Lambda
import io, zipfile
def _zip():
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("index.py", "def handler(e, c):\n    return {}\n")
    return b.getvalue()
LROLE = "arn:aws:iam::123456789012:role/r"
@case("lambda", "unknown runtime", ["InvalidParameterValueException"])
def _(): c("lambda").create_function(FunctionName=f"val-rt-{U}", Runtime="cobol85", Role=LROLE, Handler="index.handler", Code={"ZipFile": _zip()})
@case("lambda", "function name with illegal characters", ["InvalidParameterValueException", "ValidationException"])
def _(): c("lambda").create_function(FunctionName="bad name!", Runtime="python3.12", Role=LROLE, Handler="index.handler", Code={"ZipFile": _zip()})
@case("lambda", "malformed role ARN", ["InvalidParameterValueException", "ValidationException"])
def _(): c("lambda").create_function(FunctionName=f"val-ro-{U}", Runtime="python3.12", Role="nope", Handler="index.handler", Code={"ZipFile": _zip()})
@case("lambda", "duplicate function", ["ResourceConflictException"])
def _():
    kw = dict(FunctionName=f"val-dup-{U}", Runtime="python3.12", Role=LROLE, Handler="index.handler", Code={"ZipFile": _zip()})
    pre(lambda: c("lambda").create_function(**kw))
    c("lambda").create_function(**kw)
@case("lambda", "memory size outside 128-10240", ["InvalidParameterValueException", "ValidationException"])
def _(): c("lambda").create_function(FunctionName=f"val-mem-{U}", Runtime="python3.12", Role=LROLE, Handler="index.handler", Code={"ZipFile": _zip()}, MemorySize=64)
@case("lambda", "timeout over 900 seconds", ["InvalidParameterValueException", "ValidationException"])
def _(): c("lambda").create_function(FunctionName=f"val-to-{U}", Runtime="python3.12", Role=LROLE, Handler="index.handler", Code={"ZipFile": _zip()}, Timeout=1000)
@case("lambda", "get a missing function", ["ResourceNotFoundException"])
def _(): c("lambda").get_function(FunctionName=f"nope-{U}")
@case("lambda", "invoke a missing function", ["ResourceNotFoundException"])
def _(): c("lambda").invoke(FunctionName=f"nope-{U}", Payload=b"{}")
@case("lambda", "invoke with a non-JSON payload", ["InvalidRequestContentException"])
def _():
    pre(lambda: c("lambda").create_function(FunctionName=f"val-inv-{U}", Runtime="python3.12", Role=LROLE, Handler="index.handler", Code={"ZipFile": _zip()}))
    c("lambda").invoke(FunctionName=f"val-inv-{U}", Payload=b"{nope")

# ---------------------------------------------------------------- RDS
def _db(**o):
    kw = dict(DBInstanceIdentifier=f"valdb{U}", DBInstanceClass="db.t3.micro", Engine="postgres", MasterUsername="u", MasterUserPassword="password123", AllocatedStorage=20)
    kw.update(o)
    return kw
@case("rds", "duplicate DB instance", ["DBInstanceAlreadyExists"])
def _():
    pre(lambda: c("rds").create_db_instance(**_db(DBInstanceIdentifier=f"valdup{U}")))
    c("rds").create_db_instance(**_db(DBInstanceIdentifier=f"valdup{U}"))
@case("rds", "unknown instance class", ["InvalidParameterValue", "InvalidParameterCombination"])
def _(): c("rds").create_db_instance(**_db(DBInstanceIdentifier=f"valcl{U}", DBInstanceClass="db.zz9.mega"))
@case("rds", "unknown engine", ["InvalidParameterValue", "InvalidParameterCombination"])
def _(): c("rds").create_db_instance(**_db(DBInstanceIdentifier=f"valen{U}", Engine="dbase3"))
@case("rds", "master password shorter than 8", ["InvalidParameterValue"])
def _(): c("rds").create_db_instance(**_db(DBInstanceIdentifier=f"valpw{U}", MasterUserPassword="short"))
@case("rds", "allocated storage below the minimum", ["InvalidParameterValue", "InvalidParameterCombination"])
def _(): c("rds").create_db_instance(**_db(DBInstanceIdentifier=f"valst{U}", AllocatedStorage=1))
@case("rds", "identifier with illegal characters", ["InvalidParameterValue"])
def _(): c("rds").create_db_instance(**_db(DBInstanceIdentifier="bad_name!"))
@case("rds", "identifier that starts with a digit", ["InvalidParameterValue"])
def _(): c("rds").create_db_instance(**_db(DBInstanceIdentifier="1bad"))
@case("rds", "describe a missing instance", ["DBInstanceNotFound"])
def _(): c("rds").describe_db_instances(DBInstanceIdentifier=f"nope{U}")
@case("rds", "delete without final snapshot choice", ["InvalidParameterCombination"])
def _():
    pre(lambda: c("rds").create_db_instance(**_db(DBInstanceIdentifier=f"valfs{U}")))
    c("rds").delete_db_instance(DBInstanceIdentifier=f"valfs{U}")

# ---------------------------------------------------------------- CloudFormation
TPL = json.dumps({"Resources": {"Q": {"Type": "AWS::SQS::Queue", "Properties": {"QueueName": f"val-cfn-{U}"}}}})
@case("cloudformation", "template that is not JSON/YAML", ["ValidationError"])
def _(): c("cloudformation").create_stack(StackName=f"val-bad-{U}", TemplateBody="{{{{nope")
@case("cloudformation", "template with no Resources", ["ValidationError"])
def _(): c("cloudformation").create_stack(StackName=f"val-nr-{U}", TemplateBody=json.dumps({"Description": "x"}))
@case("cloudformation", "stack name with illegal characters", ["ValidationError"])
def _(): c("cloudformation").create_stack(StackName="bad name!", TemplateBody=TPL)
@case("cloudformation", "stack name starting with a digit", ["ValidationError"])
def _(): c("cloudformation").create_stack(StackName="1abc", TemplateBody=TPL)
@case("cloudformation", "no template at all", ["ValidationError"])
def _(): c("cloudformation").create_stack(StackName=f"val-nt-{U}")
@case("cloudformation", "duplicate stack", ["AlreadyExistsException"])
def _():
    pre(lambda: c("cloudformation").create_stack(StackName=f"val-dup-{U}", TemplateBody=json.dumps({"Resources": {"Q": {"Type": "AWS::SQS::Queue", "Properties": {"QueueName": f"val-dupq-{U}"}}}})))
    c("cloudformation").create_stack(StackName=f"val-dup-{U}", TemplateBody=TPL)
@case("cloudformation", "describe a missing stack", ["ValidationError"])
def _(): c("cloudformation").describe_stacks(StackName=f"nope-{U}")
@case("cloudformation", "unknown resource type", ["ValidationError"])
def _():
    n = f"val-rt-{U}"
    c("cloudformation").create_stack(StackName=n, TemplateBody=json.dumps({"Resources": {"X": {"Type": "AWS::Nope::Thing", "Properties": {}}}}))
    st = c("cloudformation").describe_stacks(StackName=n)["Stacks"][0]["StackStatus"]
    if st == "CREATE_COMPLETE":   # an unsupported type must fail honestly (rollback), never report success
        return
    raise ClientError({"Error": {"Code": "ValidationError", "Message": f"stack ended {st} (honest failure)"}, "ResponseMetadata": {"HTTPStatusCode": 400}}, "CreateStack")

# ---------------------------------------------------------------- Image Builder
@case("imagebuilder", "pipeline with malformed recipe/infra ARNs", ["InvalidParameterValueException", "ValidationException", "ResourceNotFoundException"])
def _(): c("imagebuilder").create_image_pipeline(name=f"val-{U}", imageRecipeArn="nope", infrastructureConfigurationArn="nope")
@case("imagebuilder", "get a missing pipeline", ["ResourceNotFoundException", "InvalidParameterValueException"])
def _(): c("imagebuilder").get_image_pipeline(imagePipelineArn=f"arn:aws:imagebuilder:us-east-1:123456789012:image-pipeline/nope{U}")
@case("imagebuilder", "component with a malformed version", ["InvalidVersionNumberException", "InvalidParameterValueException"])
def _(): c("imagebuilder").create_component(name=f"val-c-{U}", semanticVersion="one.two", platform="Linux", data="name: x\nschemaVersion: 1.0\nphases: []\n")
@case("imagebuilder", "infrastructure configuration with no profile", ["InvalidParameterValueException", "ValidationException", "MissingRequiredParameter"])
def _(): c("imagebuilder").create_infrastructure_configuration(name=f"val-i-{U}", instanceProfileName="")


def main():
    only = set((sys.argv[1] if len(sys.argv) > 1 else "").split(",")) - {""}
    ok = bad = 0
    for svc, label, fn, expect in CASES:
        if only and svc not in only:
            continue
        good, detail = run_case(svc, label, fn, expect)
        ok += good
        bad += (not good)
        print(f"[{'PASS' if good else 'FAIL'}] {svc}: {label} -> {detail}", flush=True)
    print(f"\n{ok}/{ok + bad} passed")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
