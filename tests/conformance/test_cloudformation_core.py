"""CloudFormation core — native Query wire on the shared router + persistence seam."""
import re

from core import cloudformation_core as cfn
from core.aws_wire_router import AwsWireRouter
from core.persistent_store import PersistentCfnStore, SqliteStateBackend

SCOPE = {"Authorization": "AWS4-HMAC-SHA256 Credential=AK/20260101/us-east-1/cloudformation/aws4_request"}
YAML = """
Parameters:
  Env: {Type: String, Default: dev}
Conditions:
  Prod: !Equals [!Ref Env, prod]
Resources:
  B:
    Type: AWS::S3::Bucket
    Properties:
      BucketName: !Sub "${AWS::StackName}-${Env}"
  P:
    Type: AWS::SNS::Topic
    Condition: Prod
Outputs:
  Arn:
    Value: !GetAtt B.Arn
    Export: {Name: !Sub "${AWS::StackName}-arn"}
"""


def call(router, **p):
    body = "&".join(f"{k}={v}" for k, v in {"Version": "2010-05-15", **p}.items()).encode()
    return router.handle("POST", "/", {}, SCOPE, body)


def test_router_serves_cloudformation_wire():
    r = AwsWireRouter()
    out = call(r, Action="ListStacks")
    assert out["status"] == 200 and b"<ListStacksResponse" in out["body"]


def test_yaml_stack_lifecycle_and_errors():
    s = cfn.CfnStore()
    r = cfn.dispatch(s, {"Action": "CreateStack", "StackName": "t1", "TemplateBody": YAML})
    assert r.status == 200
    st = next(iter(s.stacks.values()))
    assert st["StackStatus"] == "CREATE_COMPLETE" and list(st["_resources"]) == ["B"]
    assert st["Outputs"][0]["OutputValue"] == "arn:aws:s3:::t1-dev"
    assert "t1-arn" in cfn.exports_of(s)
    dup = cfn.dispatch(s, {"Action": "CreateStack", "StackName": "t1", "TemplateBody": YAML})
    assert dup.status == 400 and "AlreadyExistsException" in dup.body
    noop = cfn.dispatch(s, {"Action": "UpdateStack", "StackName": "t1", "TemplateBody": YAML})
    assert "No updates are to be performed" in noop.body
    up = cfn.dispatch(s, {"Action": "UpdateStack", "StackName": "t1", "TemplateBody": YAML,
                          "Parameters.member.1.ParameterKey": "Env", "Parameters.member.1.ParameterValue": "prod"})
    assert up.status == 200 and set(st["_resources"]) == {"B", "P"} and st["StackStatus"] == "UPDATE_COMPLETE"
    assert cfn.dispatch(s, {"Action": "DeleteStack", "StackName": "t1"}).status == 200
    gone = cfn.dispatch(s, {"Action": "DescribeStacks", "StackName": "t1"})
    assert gone.status == 400 and "does not exist" in gone.body


def test_import_blocks_export_delete():
    s = cfn.CfnStore()
    cfn.dispatch(s, {"Action": "CreateStack", "StackName": "exp", "TemplateBody": YAML})
    user = '{"Resources":{"Q":{"Type":"AWS::SQS::Queue","Properties":{"QueueName":{"Fn::ImportValue":"exp-arn"}}}}}'
    assert cfn.dispatch(s, {"Action": "CreateStack", "StackName": "imp", "TemplateBody": user}).status == 200
    blocked = cfn.dispatch(s, {"Action": "DeleteStack", "StackName": "exp"})
    assert blocked.status == 400 and "in use" in blocked.body


def test_iam_needs_capabilities_and_bad_type_rolls_back():
    s = cfn.CfnStore()
    iam = '{"Resources":{"R":{"Type":"AWS::IAM::Role","Properties":{}}}}'
    assert "InsufficientCapabilitiesException" in cfn.dispatch(s, {"Action": "CreateStack", "StackName": "i", "TemplateBody": iam}).body
    cfn.dispatch(s, {"Action": "CreateStack", "StackName": "bad", "TemplateBody": '{"Resources":{"X":{"Type":"Nope"}}}'})
    assert next(iter(s.stacks.values()))["StackStatus"] == "ROLLBACK_COMPLETE"


def test_persistent_store_survives_reload(tmp_path):
    path = str(tmp_path / "cfn.sqlite")
    a = PersistentCfnStore(SqliteStateBackend(path))
    cfn.dispatch(a, {"Action": "CreateStack", "StackName": "keep", "TemplateBody": YAML})
    b = PersistentCfnStore(SqliteStateBackend(path))
    assert [x["StackName"] for x in b.stacks.values()] == ["keep"]
    assert re.search(r"<StackName>keep</StackName>", cfn.dispatch(b, {"Action": "DescribeStacks"}).body)
