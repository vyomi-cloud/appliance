"""WP opmap-aws: AWS wire request -> required IAM actions + resource ARNs (core/iam_engine/map_aws.py).

Requests are fabricated the way boto3 / aws-cli send them (SigV4 Authorization credential scope, X-Amz-Target, form Action=, REST paths)."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from core.iam_engine import map_aws  # noqa: E402

ACCT = "123456789012"
R = "us-east-1"


def _auth(svc, region=R):
    return {"Authorization": "AWS4-HMAC-SHA256 Credential=AKIAEXAMPLE/20260101/%s/%s/aws4_request, SignedHeaders=host;x-amz-date, Signature=abc" % (region, svc)}


def tgt(svc, target, body=None, region=R):
    return {"method": "POST", "path": "/", "headers": dict(_auth(svc, region), **{"X-Amz-Target": target, "Content-Type": "application/x-amz-json-1.1"}),
            "body": json.dumps(body or {}).encode()}


def form(svc, body, region=R):
    return {"method": "POST", "path": "/", "headers": dict(_auth(svc, region), **{"Content-Type": "application/x-www-form-urlencoded; charset=utf-8"}),
            "body": body.encode()}


def rest(svc, method, path, headers=None, body=b"", query=None, region=R):
    return {"method": method, "path": path, "query": query or {}, "headers": dict(_auth(svc, region), **(headers or {})), "body": body}


def s3(method, path, host="s3.us-east-1.amazonaws.com", headers=None, query=None, body=b""):
    return rest("s3", method, path, dict({"Host": host}, **(headers or {})), body, query)


def pairs(req):
    return {(e["action"], e["resource"]) for e in map_aws.required(req)}


B = "arn:aws:s3:::"
CASES = [
    # ---- S3: path style, virtual host, sub-resources, versions, copy, multipart
    ("s3-get-object-path", s3("GET", "/bkt/dir/key.txt"), {("s3:GetObject", B + "bkt/dir/key.txt")}),
    ("s3-get-object-vhost", s3("GET", "/dir/key.txt", host="bkt.s3.us-east-1.amazonaws.com"), {("s3:GetObject", B + "bkt/dir/key.txt")}),
    ("s3-get-object-vhost-legacy-host", s3("GET", "/k", host="bkt.s3-us-west-2.amazonaws.com"), {("s3:GetObject", B + "bkt/k")}),
    ("s3-vhost-dotted-bucket", s3("GET", "/k", host="my.dotted.bkt.s3.amazonaws.com"), {("s3:GetObject", B + "my.dotted.bkt/k")}),
    ("s3-list-buckets", s3("GET", "/"), {("s3:ListAllMyBuckets", "*")}),
    ("s3-list-objects-v2", s3("GET", "/bkt", query={"list-type": "2", "prefix": "a/"}), {("s3:ListBucket", B + "bkt")}),
    ("s3-list-objects-v1", s3("GET", "/bkt"), {("s3:ListBucket", B + "bkt")}),
    ("s3-head-bucket", s3("HEAD", "/bkt"), {("s3:ListBucket", B + "bkt")}),
    ("s3-create-bucket", s3("PUT", "/newb"), {("s3:CreateBucket", B + "newb")}),
    ("s3-create-bucket-object-lock", s3("PUT", "/newb", headers={"x-amz-bucket-object-lock-enabled": "true"}),
     {("s3:CreateBucket", B + "newb"), ("s3:PutBucketObjectLockConfiguration", B + "newb")}),
    ("s3-delete-bucket", s3("DELETE", "/bkt"), {("s3:DeleteBucket", B + "bkt")}),
    ("s3-put-object", s3("PUT", "/bkt/k"), {("s3:PutObject", B + "bkt/k")}),
    ("s3-put-object-tagging-header", s3("PUT", "/bkt/k", headers={"x-amz-tagging": "a=b"}), {("s3:PutObject", B + "bkt/k"), ("s3:PutObjectTagging", B + "bkt/k")}),
    ("s3-put-object-acl-header", s3("PUT", "/bkt/k", headers={"x-amz-acl": "public-read"}), {("s3:PutObject", B + "bkt/k"), ("s3:PutObjectAcl", B + "bkt/k")}),
    ("s3-get-object-versioned", s3("GET", "/bkt/k", query={"versionId": "v1"}), {("s3:GetObjectVersion", B + "bkt/k")}),
    ("s3-delete-object", s3("DELETE", "/bkt/k"), {("s3:DeleteObject", B + "bkt/k")}),
    ("s3-delete-object-versioned", s3("DELETE", "/bkt/k", query={"versionId": "v1"}), {("s3:DeleteObjectVersion", B + "bkt/k")}),
    ("s3-copy-object", s3("PUT", "/dst/k2", headers={"x-amz-copy-source": "/src/k1"}), {("s3:GetObject", B + "src/k1"), ("s3:PutObject", B + "dst/k2")}),
    ("s3-copy-object-urlencoded-source", s3("PUT", "/dst/k2", headers={"x-amz-copy-source": "src%2Fdir%2Fk%201"}), {("s3:GetObject", B + "src/dir/k 1"), ("s3:PutObject", B + "dst/k2")}),
    ("s3-bucket-policy-get", s3("GET", "/bkt", query={"policy": ""}), {("s3:GetBucketPolicy", B + "bkt")}),
    ("s3-bucket-policy-put", s3("PUT", "/bkt", query={"policy": ""}), {("s3:PutBucketPolicy", B + "bkt")}),
    ("s3-bucket-versioning-put", s3("PUT", "/bkt", query={"versioning": ""}), {("s3:PutBucketVersioning", B + "bkt")}),
    ("s3-bucket-acl-get", s3("GET", "/bkt", query={"acl": ""}), {("s3:GetBucketAcl", B + "bkt")}),
    ("s3-bucket-tagging-put", s3("PUT", "/bkt", query={"tagging": ""}), {("s3:PutBucketTagging", B + "bkt")}),
    ("s3-object-acl-get", s3("GET", "/bkt/k", query={"acl": ""}), {("s3:GetObjectAcl", B + "bkt/k")}),
    ("s3-object-tagging-put", s3("PUT", "/bkt/k", query={"tagging": ""}), {("s3:PutObjectTagging", B + "bkt/k")}),
    ("s3-create-multipart", s3("POST", "/bkt/big", query={"uploads": ""}), {("s3:PutObject", B + "bkt/big")}),
    ("s3-upload-part", s3("PUT", "/bkt/big", query={"partNumber": "1", "uploadId": "u"}), {("s3:PutObject", B + "bkt/big")}),
    ("s3-complete-multipart", s3("POST", "/bkt/big", query={"uploadId": "u"}), {("s3:PutObject", B + "bkt/big")}),
    ("s3-abort-multipart", s3("DELETE", "/bkt/big", query={"uploadId": "u"}), {("s3:AbortMultipartUpload", B + "bkt/big")}),
    ("s3-list-parts", s3("GET", "/bkt/big", query={"uploadId": "u"}), {("s3:ListMultipartUploadParts", B + "bkt/big")}),
    ("s3-delete-objects-batch", s3("POST", "/bkt", query={"delete": ""}), {("s3:DeleteObject", B + "bkt/*")}),
    ("s3-path-in-raw-path-querystring", rest("s3", "GET", "/bkt/k?versionId=9", {"Host": "s3.us-east-1.amazonaws.com"}), {("s3:GetObjectVersion", B + "bkt/k")}),
    ("s3-accesspoint-host", s3("GET", "/k", host="myap-123456789012.s3-accesspoint.us-east-1.amazonaws.com"),
     {("s3:GetObject", "arn:aws:s3:us-east-1:123456789012:accesspoint/myap/object/k")}),
    # ---- DynamoDB
    ("ddb-getitem", tgt("dynamodb", "DynamoDB_20120810.GetItem", {"TableName": "Orders", "Key": {}}), {("dynamodb:GetItem", "arn:aws:dynamodb:us-east-1:%s:table/Orders" % ACCT)}),
    ("ddb-putitem", tgt("dynamodb", "DynamoDB_20120810.PutItem", {"TableName": "Orders", "Item": {}}), {("dynamodb:PutItem", "arn:aws:dynamodb:us-east-1:%s:table/Orders" % ACCT)}),
    ("ddb-query-index", tgt("dynamodb", "DynamoDB_20120810.Query", {"TableName": "Orders", "IndexName": "gsi1"}), {("dynamodb:Query", "arn:aws:dynamodb:us-east-1:%s:table/Orders/index/gsi1" % ACCT)}),
    ("ddb-query-table", tgt("dynamodb", "DynamoDB_20120810.Query", {"TableName": "Orders"}), {("dynamodb:Query", "arn:aws:dynamodb:us-east-1:%s:table/Orders" % ACCT)}),
    ("ddb-listtables", tgt("dynamodb", "DynamoDB_20120810.ListTables"), {("dynamodb:ListTables", "*")}),
    ("ddb-createtable", tgt("dynamodb", "DynamoDB_20120810.CreateTable", {"TableName": "New"}), {("dynamodb:CreateTable", "arn:aws:dynamodb:us-east-1:%s:table/New" % ACCT)}),
    # ---- SQS (JSON and legacy query)
    ("sqs-send-json", tgt("sqs", "AmazonSQS.SendMessage", {"QueueUrl": "https://sqs.us-east-1.amazonaws.com/111122223333/jobs", "MessageBody": "x"}),
     {("sqs:SendMessage", "arn:aws:sqs:us-east-1:111122223333:jobs")}),
    ("sqs-receive-query", form("sqs", "Action=ReceiveMessage&QueueUrl=http%3A%2F%2Fsqs.us-east-1.amazonaws.com%2F111122223333%2Fjobs"), {("sqs:ReceiveMessage", "arn:aws:sqs:us-east-1:111122223333:jobs")}),
    ("sqs-create-queue", form("sqs", "Action=CreateQueue&QueueName=newq"), {("sqs:CreateQueue", "arn:aws:sqs:us-east-1:%s:newq" % ACCT)}),
    ("sqs-list-queues", form("sqs", "Action=ListQueues"), {("sqs:ListQueues", "*")}),
    # ---- SNS
    ("sns-publish", form("sns", "Action=Publish&TopicArn=arn%3Aaws%3Asns%3Aus-east-1%3A123456789012%3Aalerts&Message=hi"), {("sns:Publish", "arn:aws:sns:us-east-1:%s:alerts" % ACCT)}),
    ("sns-create-topic", form("sns", "Action=CreateTopic&Name=alerts"), {("sns:CreateTopic", "arn:aws:sns:us-east-1:%s:alerts" % ACCT)}),
    ("sns-subscribe", form("sns", "Action=Subscribe&TopicArn=arn%3Aaws%3Asns%3Aus-east-1%3A123456789012%3Aalerts&Protocol=sqs"), {("sns:Subscribe", "arn:aws:sns:us-east-1:%s:alerts" % ACCT)}),
    # ---- KMS / Secrets Manager
    ("kms-encrypt", tgt("kms", "TrentService.Encrypt", {"KeyId": "1234abcd-12ab-34cd-56ef-1234567890ab"}), {("kms:Encrypt", "arn:aws:kms:us-east-1:%s:key/1234abcd-12ab-34cd-56ef-1234567890ab" % ACCT)}),
    ("kms-encrypt-alias", tgt("kms", "TrentService.Encrypt", {"KeyId": "alias/app"}), {("kms:Encrypt", "arn:aws:kms:us-east-1:%s:alias/app" % ACCT)}),
    ("kms-decrypt-arn", tgt("kms", "TrentService.Decrypt", {"KeyId": "arn:aws:kms:us-east-1:999999999999:key/k1"}), {("kms:Decrypt", "arn:aws:kms:us-east-1:999999999999:key/k1")}),
    ("kms-list-keys", tgt("kms", "TrentService.ListKeys"), {("kms:ListKeys", "*")}),
    ("secrets-get", tgt("secretsmanager", "secretsmanager.GetSecretValue", {"SecretId": "prod/db"}), {("secretsmanager:GetSecretValue", "arn:aws:secretsmanager:us-east-1:%s:secret:prod/db" % ACCT)}),
    ("secrets-create-with-tags", tgt("secretsmanager", "secretsmanager.CreateSecret", {"Name": "prod/db", "Tags": [{"Key": "a", "Value": "b"}]}),
     {("secretsmanager:CreateSecret", "arn:aws:secretsmanager:us-east-1:%s:secret:prod/db" % ACCT), ("secretsmanager:TagResource", "arn:aws:secretsmanager:us-east-1:%s:secret:prod/db" % ACCT)}),
    # ---- EC2 / IAM / STS (query)
    ("ec2-describe-instances", form("ec2", "Action=DescribeInstances&Version=2016-11-15"), {("ec2:DescribeInstances", "*")}),
    ("ec2-terminate", form("ec2", "Action=TerminateInstances&InstanceId.1=i-0abc"), {("ec2:TerminateInstances", "arn:aws:ec2:us-east-1:%s:instance/i-0abc" % ACCT)}),
    ("ec2-stop-two", form("ec2", "Action=StopInstances&InstanceId.1=i-1&InstanceId.2=i-2"),
     {("ec2:StopInstances", "arn:aws:ec2:us-east-1:%s:instance/i-1" % ACCT)}),
    ("ec2-run-instances", form("ec2", "Action=RunInstances&ImageId=ami-1&SubnetId=subnet-1&SecurityGroupId.1=sg-1"),
     {("ec2:RunInstances", "arn:aws:ec2:us-east-1::image/ami-1"), ("ec2:RunInstances", "arn:aws:ec2:us-east-1:%s:subnet/subnet-1" % ACCT),
      ("ec2:RunInstances", "arn:aws:ec2:us-east-1:%s:security-group/sg-1" % ACCT), ("ec2:RunInstances", "arn:aws:ec2:us-east-1:%s:instance/*" % ACCT),
      ("ec2:RunInstances", "arn:aws:ec2:us-east-1:%s:network-interface/*" % ACCT), ("ec2:RunInstances", "arn:aws:ec2:us-east-1:%s:volume/*" % ACCT)}),
    ("ec2-delete-sg", form("ec2", "Action=DeleteSecurityGroup&GroupId=sg-9"), {("ec2:DeleteSecurityGroup", "arn:aws:ec2:us-east-1:%s:security-group/sg-9" % ACCT)}),
    ("iam-create-user", form("iam", "Action=CreateUser&UserName=bob", "us-east-1"), {("iam:CreateUser", "arn:aws:iam::%s:user/bob" % ACCT)}),
    ("iam-attach-role-policy", form("iam", "Action=AttachRolePolicy&RoleName=app&PolicyArn=arn%3Aaws%3Aiam%3A%3Aaws%3Apolicy%2FReadOnlyAccess"), {("iam:AttachRolePolicy", "arn:aws:iam::%s:role/app" % ACCT)}),
    ("iam-list-users", form("iam", "Action=ListUsers"), {("iam:ListUsers", "*")}),
    ("sts-assume-role", form("sts", "Action=AssumeRole&RoleArn=arn%3Aaws%3Aiam%3A%3A123456789012%3Arole%2Fapp&RoleSessionName=s"), {("sts:AssumeRole", "arn:aws:iam::%s:role/app" % ACCT)}),
    ("sts-assume-role-with-tags", form("sts", "Action=AssumeRole&RoleArn=arn%3Aaws%3Aiam%3A%3A123456789012%3Arole%2Fapp&RoleSessionName=s&Tags.member.1.Key=k&Tags.member.1.Value=v"),
     {("sts:AssumeRole", "arn:aws:iam::%s:role/app" % ACCT), ("sts:TagSession", "arn:aws:iam::%s:role/app" % ACCT)}),
    ("sts-get-caller-identity", form("sts", "Action=GetCallerIdentity"), {("sts:GetCallerIdentity", "*")}),
    # ---- RDS / CloudFormation / CloudWatch
    ("rds-create-instance", form("rds", "Action=CreateDBInstance&DBInstanceIdentifier=db1&DBInstanceClass=db.t3.micro"), {("rds:CreateDBInstance", "arn:aws:rds:us-east-1:%s:db:db1" % ACCT)}),
    ("rds-describe-instances", form("rds", "Action=DescribeDBInstances"), {("rds:DescribeDBInstances", "arn:aws:rds:us-east-1:%s:db:*" % ACCT)}),
    ("cfn-create-stack", form("cloudformation", "Action=CreateStack&StackName=s1"), {("cloudformation:CreateStack", "arn:aws:cloudformation:us-east-1:%s:stack/s1/*" % ACCT)}),
    ("cw-put-metric-data", form("monitoring", "Action=PutMetricData&Namespace=App"), {("cloudwatch:PutMetricData", "arn:aws:cloudwatch:us-east-1:%s:dataset/*" % ACCT)}),
    ("cw-describe-alarms-cbor-path", {"method": "POST", "path": "/service/GraniteServiceVersion20100801/operation/DescribeAlarms",
                                      "headers": dict(_auth("monitoring"), **{"smithy-protocol": "rpc-v2-cbor"}), "body": b"\xa0"},
     {("cloudwatch:DescribeAlarms", "arn:aws:cloudwatch:us-east-1:%s:alarm:*" % ACCT)}),
    # ---- Lambda / EKS / API Gateway / execute-api (REST)
    ("lambda-invoke", rest("lambda", "POST", "/2015-03-31/functions/myfn/invocations"), {("lambda:InvokeFunction", "arn:aws:lambda:us-east-1:%s:function:myfn" % ACCT)}),
    ("lambda-invoke-arn", rest("lambda", "POST", "/2015-03-31/functions/arn:aws:lambda:us-east-1:123456789012:function:myfn/invocations"), {("lambda:InvokeFunction", "arn:aws:lambda:us-east-1:%s:function:myfn" % ACCT)}),
    ("lambda-get-function", rest("lambda", "GET", "/2015-03-31/functions/myfn"), {("lambda:GetFunction", "arn:aws:lambda:us-east-1:%s:function:myfn" % ACCT)}),
    ("lambda-list-functions", rest("lambda", "GET", "/2015-03-31/functions"), {("lambda:ListFunctions", "*")}),
    ("lambda-create-function", rest("lambda", "POST", "/2015-03-31/functions", {"Content-Type": "application/json"}, b'{"FunctionName":"newfn","Runtime":"python3.12","Role":"arn:aws:iam::123456789012:role/r"}'),
     {("lambda:CreateFunction", "arn:aws:lambda:us-east-1:%s:function:newfn" % ACCT)}),
    ("lambda-delete-function", rest("lambda", "DELETE", "/2015-03-31/functions/myfn"), {("lambda:DeleteFunction", "arn:aws:lambda:us-east-1:%s:function:myfn" % ACCT)}),
    ("eks-describe-cluster", rest("eks", "GET", "/clusters/prod"), {("eks:DescribeCluster", "arn:aws:eks:us-east-1:%s:cluster/prod" % ACCT)}),
    ("eks-create-cluster", rest("eks", "POST", "/clusters", {"Content-Type": "application/json"}, b'{"name":"c1","roleArn":"x"}'), {("eks:CreateCluster", "arn:aws:eks:us-east-1:%s:cluster/c1" % ACCT)}),
    ("eks-list-clusters", rest("eks", "GET", "/clusters"), {("eks:ListClusters", "*")}),
    ("apigw-get-stages", rest("apigateway", "GET", "/restapis/abc123/stages"), {("apigateway:GET", "arn:aws:apigateway:us-east-1::/restapis/abc123/stages")}),
    ("apigw-create-restapi", rest("apigateway", "POST", "/restapis"), {("apigateway:POST", "arn:aws:apigateway:us-east-1::/restapis")}),
    ("apigw-v2-create-api", rest("apigateway", "POST", "/v2/apis"), {("apigateway:POST", "arn:aws:apigateway:us-east-1::/apis")}),
    ("apigw-delete-resource", rest("apigateway", "DELETE", "/restapis/abc/resources/r1"), {("apigateway:DELETE", "arn:aws:apigateway:us-east-1::/restapis/abc/resources/r1")}),
    ("execute-api-invoke", rest("execute-api", "GET", "/prod/items/1", {"Host": "abc123.execute-api.us-east-1.amazonaws.com"}), {("execute-api:Invoke", "arn:aws:execute-api:us-east-1:%s:abc123/prod/GET/items/1" % ACCT)}),
    ("execute-api-post-connections", rest("execute-api", "POST", "/prod/@connections/conn1", {"Host": "abc123.execute-api.us-east-1.amazonaws.com"}),
     {("execute-api:ManageConnections", "arn:aws:execute-api:us-east-1:%s:abc123/prod/POST/@connections/conn1" % ACCT)}),
    # ---- other JSON services
    ("ecr-put-image", tgt("ecr", "AmazonEC2ContainerRegistry_V20150921.PutImage", {"repositoryName": "web"}), {("ecr:PutImage", "arn:aws:ecr:us-east-1:%s:repository/web" % ACCT)}),
    ("ecr-get-auth-token", tgt("ecr", "AmazonEC2ContainerRegistry_V20150921.GetAuthorizationToken"), {("ecr:GetAuthorizationToken", "*")}),
    ("logs-put-events", tgt("logs", "Logs_20140328.PutLogEvents", {"logGroupName": "/app", "logStreamName": "s1"}), {("logs:PutLogEvents", "arn:aws:logs:us-east-1:%s:log-group:/app:log-stream:s1" % ACCT)}),
    ("events-put-events", tgt("events", "AWSEvents.PutEvents", {"Entries": [{"EventBusName": "default"}]}), {("events:PutEvents", "arn:aws:events:us-east-1:%s:event-bus/default" % ACCT)}),
    ("sfn-start-execution", tgt("states", "AWSStepFunctions.StartExecution", {"stateMachineArn": "arn:aws:states:us-east-1:123456789012:stateMachine:sm"}),
     {("states:StartExecution", "arn:aws:states:us-east-1:%s:stateMachine:sm" % ACCT)}),
    ("ssm-get-parameter", tgt("ssm", "AmazonSSM.GetParameter", {"Name": "/app/db"}), {("ssm:GetParameter", "arn:aws:ssm:us-east-1:%s:parameter/app/db" % ACCT)}),
    ("kinesis-put-record", tgt("kinesis", "Kinesis_20131202.PutRecord", {"StreamName": "clicks"}), {("kinesis:PutRecord", "arn:aws:kinesis:us-east-1:%s:stream/clicks" % ACCT)}),
    ("bedrock-invoke-model", rest("bedrock", "POST", "/model/anthropic.claude-3-haiku-20240307-v1:0/invoke"), {("bedrock:InvokeModel", "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-3-haiku-20240307-v1:0")}),
]


@pytest.mark.parametrize("name,req,expected", CASES, ids=[c[0] for c in CASES])
def test_required(name, req, expected):
    got = pairs(req)
    assert got == expected, "%s: got %r" % (name, sorted(got))


def test_case_count():
    assert len(CASES) >= 60


# ---- shape / region / account / robustness
def test_entry_shape():
    e = map_aws.required(s3("GET", "/b/k"))[0]
    assert set(e) == {"action", "resource", "service", "operation"} and e["service"] == "s3" and e["operation"] == "GetObject"


def test_region_from_credential_scope():
    got = pairs(tgt("dynamodb", "DynamoDB_20120810.GetItem", {"TableName": "t"}, region="eu-west-2"))
    assert got == {("dynamodb:GetItem", "arn:aws:dynamodb:eu-west-2:%s:table/t" % ACCT)}


def test_account_override():
    req = tgt("dynamodb", "DynamoDB_20120810.GetItem", {"TableName": "t"})
    req["account"] = "999988887777"
    assert pairs(req) == {("dynamodb:GetItem", "arn:aws:dynamodb:us-east-1:999988887777:table/t")}


def test_presigned_url_credential_in_query():
    req = {"method": "GET", "path": "/bkt/k", "query": {"X-Amz-Credential": "AKIA%2F20260101%2Feu-west-1%2Fs3%2Faws4_request", "X-Amz-Signature": "s"}, "headers": {"Host": "s3.eu-west-1.amazonaws.com"}}
    assert pairs(req) == {("s3:GetObject", B + "bkt/k")}


def test_header_case_and_string_body_and_raw_query_string():
    req = {"method": "post", "path": "/", "query": "", "headers": {"AUTHORIZATION": _auth("sqs")["Authorization"], "content-type": "application/x-www-form-urlencoded"}, "body": "Action=ListQueues"}
    assert pairs(req) == {("sqs:ListQueues", "*")}


def test_query_action_in_url_query():
    req = rest("sts", "GET", "/", query={"Action": "GetCallerIdentity", "Version": "2011-06-15"})
    assert pairs(req) == {("sts:GetCallerIdentity", "*")}


def test_unsigned_target_falls_back_to_target_prefix():
    req = {"method": "POST", "path": "/", "headers": {"X-Amz-Target": "DynamoDB_20120810.ListTables"}, "body": b"{}"}
    assert pairs(req) == {("dynamodb:ListTables", "*")}


def test_unknown_requests_map_to_nothing():
    assert map_aws.required({"method": "GET", "path": "/nope", "headers": _auth("totally-unknown")}) == []
    assert map_aws.required(tgt("dynamodb", "DynamoDB_20120810.NoSuchOperation")) == []
    assert map_aws.required({"method": "POST", "path": "/", "headers": {}, "body": b""}) == []


def test_malformed_json_body_does_not_raise():
    req = rest("lambda", "POST", "/2015-03-31/functions", {"Content-Type": "application/json"}, b"{not json")
    assert map_aws.required(req)[0]["action"] == "lambda:CreateFunction"


def test_all_actions_exist_in_catalog():
    for _, req, _exp in CASES:
        for e in map_aws.required(req):
            if e["service"] in ("apigateway", "execute-api"):
                continue
            cat = map_aws.catalog(e["service"])
            assert e["action"].split(":", 1)[1] in cat["actions"], e


def test_overrides_documented():
    assert len(map_aws.OVERRIDES) >= 8 and all(isinstance(v, str) and len(v) > 20 for v in map_aws.OVERRIDES.values())


# ---- coverage (wire round-trip of every catalog operation)
TOP10 = ["s3", "dynamodb", "ec2", "ecr", "eks", "lambda", "rds", "apigateway", "iam", "sts", "kms", "secretsmanager", "sqs", "sns", "events", "logs", "cloudwatch"]


@pytest.fixture(scope="module")
def cov():
    return map_aws.coverage()


@pytest.mark.parametrize("prefix", TOP10)
def test_coverage_at_least_95_percent(cov, prefix):
    c = cov[prefix]
    assert c["ops"] > 0
    assert c["mapped"] / float(c["ops"]) >= 0.95, "%s unmapped: %s" % (prefix, c["unmapped"])


def test_coverage_overall(cov):
    mapped = sum(c["mapped"] for c in cov.values())
    total = sum(c["ops"] for c in cov.values())
    assert mapped / float(total) >= 0.95


def test_coverage_cli():
    import subprocess
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    out = subprocess.run([sys.executable, "-m", "core.iam_engine.map_aws", "--coverage"], cwd=root, capture_output=True, text=True, timeout=300)
    assert out.returncode == 0 and "TOTAL" in out.stdout


def test_s3_entries_carry_request_condition_keys():
    from core.iam_engine import map_aws
    r = map_aws.required({"method": "GET", "path": "/bkt", "query": "list-type=2&prefix=home%2F&delimiter=%2F", "headers": {}, "host": "localhost"})
    assert r and r[0]["service"] == "s3" and r[0]["context"] == {"s3:prefix": "home/", "s3:delimiter": "/"}
    put = map_aws.required({"method": "PUT", "path": "/bkt/k", "query": "", "headers": {"x-amz-acl": "public-read"}, "host": "localhost"})
    assert put and put[0]["context"] == {"s3:x-amz-acl": "public-read"}
