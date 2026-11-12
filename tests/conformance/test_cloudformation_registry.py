"""AWS-13 CloudFormation registry: public extensions catalog + filters, ActivateType/DeactivateType, REAL module expansion into SQS queues,
type configuration, publisher registration. Via AwsWireRouter. Run: PYTHONPATH=. python3 tests/conformance/test_cloudformation_registry.py
"""
import json
import re
import urllib.parse

from core.aws_wire_router import AwsWireRouter

AUTH = "AWS4-HMAC-SHA256 Credential=T/20261030/us-east-1/cloudformation/aws4_request, SignedHeaders=host, Signature=0"
SQS = "AWS4-HMAC-SHA256 Credential=T/20261030/us-east-1/sqs/aws4_request, SignedHeaders=host, Signature=0"


def cf(r, action, **p):
    body = urllib.parse.urlencode({"Action": action, "Version": "2010-05-15", **p}).encode()
    out = r.handle("POST", "/", {}, {"authorization": AUTH, "content-type": "application/x-www-form-urlencoded"}, body)
    return out["status"], out["body"].decode()


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


MOD = "Vyomi::Messaging::QueuePair::MODULE"


def main():
    r = AwsWireRouter()
    st, x = cf(r, "ListTypes", Visibility="PUBLIC", Type="RESOURCE")
    _check("public resource catalog has AWS + third-party types", "<TypeName>AWS::S3::Bucket</TypeName>" in x and "<TypeName>Vyomi::Shop::Order</TypeName>" in x)
    st, x = cf(r, "ListTypes", Visibility="PUBLIC", Type="RESOURCE", **{"Filters.Category": "THIRD_PARTY"})
    _check("THIRD_PARTY filter excludes AWS types", "AWS::S3::Bucket" not in x and "Vyomi::Shop::Order" in x)
    st, x = cf(r, "ListTypes", Visibility="PUBLIC", Type="RESOURCE", **{"Filters.Category": "AWS_TYPES"})
    _check("AWS_TYPES filter", "Vyomi::" not in x and "AWS::S3::Bucket" in x)
    st, x = cf(r, "ListTypes", Visibility="PUBLIC", Type="MODULE")
    _check("public modules", MOD in x and "Vyomi::Storage::LogBucket::MODULE" in x)
    st, x = cf(r, "ListTypes", Visibility="PUBLIC", Type="RESOURCE", **{"Filters.TypeNamePrefix": "AWS::SQS"})
    _check("TypeNamePrefix filter", "AWS::SQS::Queue" in x and "AWS::S3" not in x)
    st, x = cf(r, "ListTypes", Visibility="PRIVATE", Type="MODULE")
    _check("no activated modules yet", "<member>" not in x)
    st, x = cf(r, "ActivateType", Type="MODULE", TypeName="Vyomi::Nope::Nope::MODULE", PublisherId="7f3c9d1e5b2a48c6a0d1e2f3b4c5d6e7")
    _check("unknown public type -> TypeNotFoundException", st == 404)
    st, x = cf(r, "ActivateType", Type="RESOURCE", TypeName="AWS::S3::Bucket")
    _check("AWS-published types cannot be activated", st == 400)
    st, x = cf(r, "ActivateType", Type="MODULE", TypeName=MOD, PublisherId="7f3c9d1e5b2a48c6a0d1e2f3b4c5d6e7", ExecutionRoleArn="nope")
    _check("bad ExecutionRoleArn rejected", st == 400)

    tpl = json.dumps({"Resources": {"Q": {"Type": MOD, "Properties": {"VisibilityTimeout": 45}}}})
    st, x = cf(r, "CreateStack", StackName="nomod", TemplateBody=tpl)
    _check("module not activated -> template error", st == 400 and "not activated" in x)
    st, x = cf(r, "ActivateType", Type="MODULE", TypeName=MOD, PublisherId="7f3c9d1e5b2a48c6a0d1e2f3b4c5d6e7", AutoUpdate="false")
    _check("ActivateType returns the activated type ARN", st == 200 and re.search(r"<Arn>arn:aws:cloudformation:us-east-1:\d{12}:type/module/Vyomi-Messaging-QueuePair-MODULE</Arn>", x))
    st, x = cf(r, "ListTypes", Visibility="PRIVATE", Type="MODULE")
    _check("activated module listed", MOD in x and "<IsActivated>true</IsActivated>" in x)
    st, x = cf(r, "DescribeType", Type="MODULE", TypeName=MOD)
    _check("DescribeType of the activated module", "<AutoUpdate>false</AutoUpdate>" in x and "<Visibility>PRIVATE</Visibility>" in x)
    st, x = cf(r, "CreateStack", StackName="withmod", TemplateBody=json.dumps({"Resources": {"Q": {"Type": MOD, "Properties": {"VisibilityTimeout": 45, "Bogus": 1}}}}))
    _check("unknown module parameter rejected", st == 400 and "Bogus" in x)
    st, x = cf(r, "CreateStack", StackName="withmod", TemplateBody=tpl)
    _check("CreateStack with a module", st == 200)
    st, x = cf(r, "ListStackResources", StackName="withmod")
    _check("module expanded into prefixed real resources", "<LogicalResourceId>QQueue</LogicalResourceId>" in x and "<LogicalResourceId>QDlq</LogicalResourceId>" in x)
    out = r.handle("POST", "/", {}, {"authorization": SQS, "x-amz-target": "AmazonSQS.ListQueues", "content-type": "application/x-amz-json-1.0"}, b"{}")
    qs = json.loads(out["body"]).get("QueueUrls", [])
    _check("real SQS queues exist", len([q for q in qs if "withmod" in q]) == 2)
    st, x = cf(r, "DeactivateType", Type="MODULE", TypeName=MOD)
    _check("cannot deactivate a module used by a stack", st == 400)
    cf(r, "DeleteStack", StackName="withmod")
    st, x = cf(r, "DeactivateType", Type="MODULE", TypeName=MOD)
    _check("deactivate after the stack is deleted", st == 200)

    # alias + configuration
    st, x = cf(r, "ActivateType", Type="MODULE", TypeName=MOD, PublisherId="7f3c9d1e5b2a48c6a0d1e2f3b4c5d6e7", TypeNameAlias="My::Queues::Pair::MODULE")
    _check("alias activation", st == 200 and "My-Queues-Pair-MODULE" in x)
    st, x = cf(r, "SetTypeConfiguration", TypeName="My::Queues::Pair::MODULE", Configuration="{not json")
    _check("configuration must be JSON", st == 400)
    st, x = cf(r, "SetTypeConfiguration", TypeName="My::Queues::Pair::MODULE", Configuration='{"a":1}')
    _check("SetTypeConfiguration", st == 200 and "ConfigurationArn" in x)
    st, x = cf(r, "BatchDescribeTypeConfigurations", **{"TypeConfigurationIdentifiers.member.1.TypeName": "My::Queues::Pair::MODULE"})
    _check("BatchDescribeTypeConfigurations", '{"a":1}' in x.replace("&quot;", '"'))
    st, x = cf(r, "SetTypeConfiguration", TypeName="Vyomi::Shop::Order", Configuration="{}")
    _check("configuring a type that is not activated fails", st == 400)
    st, x = cf(r, "ListTypeVersions", TypeName="Vyomi::Shop::Order")
    _check("ListTypeVersions", "<VersionId>00000001</VersionId>" in x)

    # hook activation reuses the hook engine
    st, x = cf(r, "ActivateType", Type="HOOK", TypeName="Vyomi::Guard::RequiredTags", PublisherId="7f3c9d1e5b2a48c6a0d1e2f3b4c5d6e7")
    st, x = cf(r, "ListTypes", Visibility="PRIVATE", Type="HOOK")
    _check("activated public hook shows up in the hooks registry", "Vyomi::Guard::RequiredTags" in x)

    # publisher
    st, x = cf(r, "DescribePublisher")
    _check("unregistered account has no publisher", st == 400)
    st, x = cf(r, "RegisterPublisher")
    _check("terms must be accepted", st == 400)
    st, x = cf(r, "RegisterPublisher", AcceptTermsAndConditions="true", ConnectionArn="bogus")
    _check("bad ConnectionArn", st == 400)
    st, x = cf(r, "RegisterPublisher", AcceptTermsAndConditions="true")
    pid = re.search(r"<PublisherId>([0-9a-f]{32})</PublisherId>", x).group(1)
    _check("RegisterPublisher returns a 32-hex PublisherId", bool(pid))
    st, x = cf(r, "RegisterPublisher", AcceptTermsAndConditions="true")
    _check("RegisterPublisher is idempotent", pid in x)
    st, x = cf(r, "DescribePublisher")
    _check("DescribePublisher UNVERIFIED without a connection", "<PublisherStatus>UNVERIFIED</PublisherStatus>" in x)
    st, x = cf(r, "DescribePublisher", PublisherId="7f3c9d1e5b2a48c6a0d1e2f3b4c5d6e7")
    _check("Vyomi publisher is VERIFIED", "VERIFIED" in x and "vyomi.cloud" in x)
    cf(r, "RegisterType", Type="HOOK", TypeName="My::Guard::Hook", SchemaHandlerPackage="s3://b/k")
    st, x = cf(r, "PublishType", Type="HOOK", TypeName="My::Guard::Hook", PublicVersionNumber="1.0")
    _check("PublishType validates the version", st == 400)
    st, x = cf(r, "PublishType", Type="HOOK", TypeName="My::Guard::Hook", PublicVersionNumber="1.0.0")
    _check("PublishType", st == 200)
    st, x = cf(r, "ListTypes", Visibility="PUBLIC", Type="HOOK", **{"Filters.PublisherId": pid})
    _check("published hook is in the public catalog under my publisher id", "My::Guard::Hook" in x)
    print("PASS cloudformation registry")


if __name__ == "__main__":
    main()
