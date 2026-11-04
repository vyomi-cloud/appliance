"""Visual canvas kit (AWS-10): the payloads the shared canvas produces for CloudFormation Template Studio, the EventBridge
rule Builder and the Lambda Infrastructure Composer are accepted and REALLY provisioned/delivered by the service cores.
(The canvas UI itself is covered by consoles/tests/smoke-aws-canvas.mjs.)

    PYTHONPATH=. python3 tests/conformance/test_visual_canvas.py
"""
import json
import re

from core.cloudformation_core import CloudFormationStore, dispatch as cfn_dispatch
from core.object_store import InMemoryObjectStore
from core.nosql_store import InMemoryNoSqlStore
from core.iam_store import InMemoryIamStore
from core.messaging_store import InMemoryMessagingStore
from core.logs_core import LogsStore
from core import sqs_core as sqs, eventbridge_core as eb, cloudwatch_core as cwc


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def main():
    store = CloudFormationStore()
    s3, ddb, iam, msg, logs = InMemoryObjectStore(), InMemoryNoSqlStore(), InMemoryIamStore(), InMemoryMessagingStore(), LogsStore()
    call = lambda a, **p: cfn_dispatch(store, dict(p, Action=a), s3_store=s3, ddb_store=ddb, iam_store=iam, msg_store=msg, logs_store=logs)

    # CFN Template Studio canvas output: JSON resources + DependsOn edges + Designer positions metadata
    tpl = {
        "AWSTemplateFormatVersion": "2010-09-09",
        "Resources": {
            "Bucket": {"Type": "AWS::S3::Bucket", "Properties": {"BucketName": "canvas-bkt"}},
            "Queue": {"Type": "AWS::SQS::Queue", "Properties": {"QueueName": "canvas-q"}, "DependsOn": "Bucket"},
            "Topic": {"Type": "AWS::SNS::Topic", "Properties": {"TopicName": "canvas-t"}, "DependsOn": ["Bucket", "Queue"]},
        },
        "Metadata": {"AWS::CloudFormation::Designer": {"Bucket": {"position": {"x": 24, "y": 24}}, "Queue": {"position": {"x": 244, "y": 24}}, "Topic": {"position": {"x": 464, "y": 24}}}},
    }
    r = call("ValidateTemplate", TemplateBody=json.dumps(tpl))
    _check("canvas template validates", r.status == 200)
    r = call("CreateStack", StackName="canvas-stack", TemplateBody=json.dumps(tpl))
    _check("canvas template creates stack", r.status == 200)
    _check("stack CREATE_COMPLETE", "<StackStatus>CREATE_COMPLETE</StackStatus>" in call("DescribeStacks", StackName="canvas-stack").body)
    _check("bucket really exists", s3.bucket_exists("canvas-bkt"))
    _check("queue really exists", msg.get_queue("canvas-q") is not None)
    _check("topic really exists", msg.get_topic("arn:aws:sns:us-east-1:123456789012:canvas-t") is not None)
    res = call("DescribeStackResources", StackName="canvas-stack").body
    _check("three resources recorded", len(re.findall(r"<LogicalResourceId>", res)) == 3)

    # EventBridge Builder: Triggering event node -> Target node == PutRule(event pattern) + PutTargets
    m = InMemoryMessagingStore(); m.cw_store = cwc.CloudWatchStore()
    qurl = sqs.dispatch(m, "AmazonSQS.CreateQueue", {"QueueName": "builder-q"}).body["QueueUrl"]
    qarn = sqs.dispatch(m, "AmazonSQS.GetQueueAttributes", {"QueueUrl": qurl}).body["Attributes"]["QueueArn"]
    pattern = {"source": ["canvas.app"], "detail-type": ["order"], "detail": {"state": ["paid"]}}
    eb.dispatch(m, "AWSEvents.PutRule", {"Name": "builder-rule", "EventPattern": json.dumps(pattern), "State": "ENABLED"})
    eb.dispatch(m, "AWSEvents.PutTargets", {"Rule": "builder-rule", "Targets": [{"Id": "t1", "Arn": qarn}]})
    eb.dispatch(m, "AWSEvents.PutEvents", {"Entries": [{"Source": "canvas.app", "DetailType": "order", "Detail": json.dumps({"state": "paid"})}]})
    eb.dispatch(m, "AWSEvents.PutEvents", {"Entries": [{"Source": "canvas.app", "DetailType": "order", "Detail": json.dumps({"state": "open"})}]})
    got = sqs.dispatch(m, "AmazonSQS.ReceiveMessage", {"QueueUrl": qurl, "MaxNumberOfMessages": 10}).body.get("Messages", [])
    _check("builder rule delivers the matching event only", len(got) == 1)

    # Lambda Composer: the generated stack part (physical names prefixed by the app) provisions for real
    comp = {"AWSTemplateFormatVersion": "2010-09-09", "Resources": {
        "q1": {"Type": "AWS::SQS::Queue", "Properties": {"QueueName": "myapp-jobs"}},
        "t1": {"Type": "AWS::SNS::Topic", "Properties": {"TopicName": "myapp-alerts"}},
        "d1": {"Type": "AWS::DynamoDB::Table", "Properties": {"TableName": "myapp-items", "BillingMode": "PAY_PER_REQUEST",
               "AttributeDefinitions": [{"AttributeName": "id", "AttributeType": "S"}], "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}]}}}}
    r = call("CreateStack", StackName="myapp", TemplateBody=json.dumps(comp))
    _check("composer stack creates", r.status == 200 and msg.get_queue("myapp-jobs") is not None)
    _check("composer table named as planned", "myapp-items" in list(ddb.table_names()))
    print("visual canvas conformance: all checks passed")


if __name__ == "__main__":
    main()
