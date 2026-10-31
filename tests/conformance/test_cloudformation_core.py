"""CloudFormation core conformance — stacks/change-sets/stack-sets + real resource
provisioning through the S3/DynamoDB/SNS/SQS/IAM/Logs cores (host + Pyodide).

    PYTHONPATH=. python3 tests/conformance/test_cloudformation_core.py
"""
import json
import re

try:
    from core.cloudformation_core import CloudFormationStore, dispatch
    from core.object_store import InMemoryObjectStore
    from core.nosql_store import InMemoryNoSqlStore
    from core.iam_store import InMemoryIamStore
    from core.messaging_store import InMemoryMessagingStore
    from core.logs_core import LogsStore
except ImportError:  # pragma: no cover - Pyodide flat layout
    from cloudformation_core import CloudFormationStore, dispatch  # type: ignore
    from object_store import InMemoryObjectStore  # type: ignore
    from nosql_store import InMemoryNoSqlStore  # type: ignore
    from iam_store import InMemoryIamStore  # type: ignore
    from messaging_store import InMemoryMessagingStore  # type: ignore
    from logs_core import LogsStore  # type: ignore


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def _v(xml, tag):
    m = re.search(rf"<{tag}>(.*?)</{tag}>", xml, re.S)
    return m.group(1) if m else ""


def _vs(xml, tag):
    return re.findall(rf"<{tag}>(.*?)</{tag}>", xml, re.S)


def run():
    store = CloudFormationStore()
    s3, ddb, iam, msg, logs = InMemoryObjectStore(), InMemoryNoSqlStore(), InMemoryIamStore(), InMemoryMessagingStore(), LogsStore()
    call = lambda a, **p: dispatch(store, dict(p, Action=a), s3_store=s3, ddb_store=ddb, iam_store=iam, msg_store=msg, logs_store=logs)
    err = lambda r, code: r.status >= 400 and f"<Code>{code}</Code>" in r.body

    _check("unknown action", err(call("Nope"), "InvalidAction"))

    # ── CreateStack: multi-resource, Ref/Sub/GetAtt, Outputs + Exports ──────
    tpl = json.dumps({
        "Description": "conformance stack",
        "Parameters": {"EnvName": {"Type": "String", "Default": "dev"}},
        "Resources": {
            "Bucket": {"Type": "AWS::S3::Bucket", "Properties": {}},
            "Table": {"Type": "AWS::DynamoDB::Table", "Properties": {
                "AttributeDefinitions": [{"AttributeName": "pk", "AttributeType": "S"}],
                "KeySchema": [{"AttributeName": "pk", "KeyType": "HASH"}]}},
            "Topic": {"Type": "AWS::SNS::Topic", "Properties": {"TopicName": {"Fn::Sub": "${AWS::StackName}-topic"}}},
        },
        "Outputs": {
            "BucketRef": {"Value": {"Ref": "Bucket"}, "Export": {"Name": "cfn-conf-bucket"}},
            "TopicArn": {"Value": {"Fn::GetAtt": ["Topic", "Arn"]}},
            "Env": {"Value": {"Ref": "EnvName"}},
        },
    })
    r = call("CreateStack", StackName="conf-stack", TemplateBody=tpl)
    _check("create stack 200", r.status == 200)
    stack_id = _v(r.body, "StackId")
    _check("stack id shaped", stack_id.startswith("arn:aws:cloudformation:"))

    r = call("DescribeStacks", StackName="conf-stack")
    _check("describe CREATE_COMPLETE", "<StackStatus>CREATE_COMPLETE</StackStatus>" in r.body)
    bucket_name = _v(r.body, "OutputValue")  # first OutputValue = BucketRef (dict insertion order)
    _check("bucket actually exists in the S3 store", s3.bucket_exists(bucket_name))
    _check("topic actually exists in the messaging store", msg.get_topic("arn:aws:sns:us-east-1:123456789012:conf-stack-topic") is not None)
    _check("ddb table actually created (generated physical name)", any(ddb.table_names()))

    r = call("ListExports")
    _check("export visible + unique value", "<Name>cfn-conf-bucket</Name>" in r.body and f"<Value>{bucket_name}</Value>" in r.body)

    # exporting the same name from a second stack must fail validation (rolled back, not silently accepted)
    tpl2 = json.dumps({"Resources": {"B2": {"Type": "AWS::S3::Bucket", "Properties": {}}},
                       "Outputs": {"X": {"Value": "dup", "Export": {"Name": "cfn-conf-bucket"}}}})
    r = call("CreateStack", StackName="conf-stack-2", TemplateBody=tpl2)
    r2 = call("DescribeStacks", StackName="conf-stack-2")
    _check("duplicate export name rolled back", "<StackStatus>ROLLBACK_COMPLETE</StackStatus>" in r2.body)

    # ── unsupported resource type -> honest failure + rollback (no silent success) ──
    bad = json.dumps({"Resources": {
        "A": {"Type": "AWS::S3::Bucket", "Properties": {}},
        "B": {"Type": "AWS::EC2::Instance", "Properties": {}},
    }})
    r = call("CreateStack", StackName="bad-stack", TemplateBody=bad)
    r2 = call("DescribeStacks", StackName="bad-stack")
    _check("unsupported type rolls the whole stack back", "<StackStatus>ROLLBACK_COMPLETE</StackStatus>" in r2.body)
    _check("rollback leaves no resources", call("ListStackResources", StackName="bad-stack").body.count("<member>") == 0)
    _check("stack name blocked from reuse until deleted",
           err(call("CreateStack", StackName="bad-stack", TemplateBody=bad), "AlreadyExistsException"))

    # ── IAM resource requires a capability ──────────────────────────────────
    iam_tpl = json.dumps({"Resources": {"R": {"Type": "AWS::IAM::Role", "Properties": {"RoleName": "cfn-conf-role"}}}})
    r = call("CreateStack", StackName="iam-stack", TemplateBody=iam_tpl)
    _check("missing capability rejected", err(r, "InsufficientCapabilitiesException"))
    r = call("CreateStack", StackName="iam-stack", TemplateBody=iam_tpl, **{"Capabilities.member.1": "CAPABILITY_NAMED_IAM"})
    _check("create with capability 200", r.status == 200)
    r2 = call("DescribeStacks", StackName="iam-stack")
    _check("iam stack created", "<StackStatus>CREATE_COMPLETE</StackStatus>" in r2.body)
    _check("role actually exists in the IAM store", iam.get_role("cfn-conf-role") is not None)

    # ── YAML template (short-form !Ref / !GetAtt / long-form mapping) ──────
    yaml_tpl = (
        "Parameters:\n"
        "  QName:\n"
        "    Type: String\n"
        "    Default: cfn-conf-queue\n"
        "Resources:\n"
        "  Q:\n"
        "    Type: AWS::SQS::Queue\n"
        "    Properties:\n"
        "      QueueName: !Ref QName\n"
        "Outputs:\n"
        "  QueueArn:\n"
        "    Value: !GetAtt Q.Arn\n"
    )
    r = call("CreateStack", StackName="yaml-stack", TemplateBody=yaml_tpl)
    _check("yaml create 200", r.status == 200)
    r2 = call("DescribeStacks", StackName="yaml-stack")
    _check("yaml stack complete", "<StackStatus>CREATE_COMPLETE</StackStatus>" in r2.body)
    _check("yaml queue created", msg.get_queue("cfn-conf-queue") is not None)

    # ── UpdateStack: add + remove resources ─────────────────────────────────
    up1 = json.dumps({"Resources": {"Q": {"Type": "AWS::SQS::Queue", "Properties": {}}}})
    call("CreateStack", StackName="up-stack", TemplateBody=up1)
    up2 = json.dumps({"Resources": {
        "Q": {"Type": "AWS::SQS::Queue", "Properties": {}},
        "B": {"Type": "AWS::S3::Bucket", "Properties": {}}}})
    r = call("UpdateStack", StackName="up-stack", TemplateBody=up2)
    _check("update stack 200", r.status == 200)
    r2 = call("ListStackResources", StackName="up-stack")
    _check("update added resource", "<LogicalResourceId>B</LogicalResourceId>" in r2.body)
    up3 = json.dumps({"Resources": {"Q": {"Type": "AWS::SQS::Queue", "Properties": {}}}})
    call("UpdateStack", StackName="up-stack", TemplateBody=up3)
    r2 = call("ListStackResources", StackName="up-stack")
    _check("update removed resource", "<LogicalResourceId>B</LogicalResourceId>" not in r2.body)

    # ── ChangeSets: create, describe (diff), execute, delete ───────────────
    cs_tpl_add = json.dumps({"Resources": {
        "Q": {"Type": "AWS::SQS::Queue", "Properties": {}},
        "B2": {"Type": "AWS::S3::Bucket", "Properties": {}}}})
    r = call("CreateChangeSet", StackName="up-stack", ChangeSetName="cs1", TemplateBody=cs_tpl_add)
    _check("create change set 200", r.status == 200)
    cs_id = _v(r.body, "Id")
    r = call("DescribeChangeSet", ChangeSetName="cs1", StackName="up-stack")
    _check("change set shows an Add", "<Action>Add</Action>" in r.body and "<LogicalResourceId>B2</LogicalResourceId>" in r.body)
    r = call("ExecuteChangeSet", ChangeSetName="cs1", StackName="up-stack")
    _check("execute change set 200", r.status == 200)
    r2 = call("ListStackResources", StackName="up-stack")
    _check("executed change set created the resource", "<LogicalResourceId>B2</LogicalResourceId>" in r2.body)
    _check("re-executing an executed change set fails", err(call("ExecuteChangeSet", ChangeSetName="cs1", StackName="up-stack"), "InvalidChangeSetStatus"))

    # CREATE-type change set against a brand-new stack name
    r = call("CreateChangeSet", StackName="cs-new-stack", ChangeSetName="cs2", ChangeSetType="CREATE",
             TemplateBody=json.dumps({"Resources": {"Q3": {"Type": "AWS::SQS::Queue", "Properties": {}}}}))
    _check("create-type change set 200", r.status == 200)
    r2 = call("DescribeStacks", StackName="cs-new-stack")
    _check("review-in-progress stack shell exists", "<StackStatus>REVIEW_IN_PROGRESS</StackStatus>" in r2.body)
    r = call("ExecuteChangeSet", ChangeSetName="cs2", StackName="cs-new-stack")
    _check("execute create-type change set", r.status == 200)
    r2 = call("DescribeStacks", StackName="cs-new-stack")
    _check("stack now created", "<StackStatus>CREATE_COMPLETE</StackStatus>" in r2.body)

    r = call("DeleteChangeSet", ChangeSetName="cs1", StackName="up-stack")
    _check("delete change set 200", r.status == 200)
    _check("deleted change set gone", err(call("DescribeChangeSet", ChangeSetName="cs1", StackName="up-stack"), "ChangeSetNotFoundException"))

    # ── events / resources / template round-trip ────────────────────────────
    r = call("DescribeStackEvents", StackName="up-stack")
    _check("events recorded, newest first", r.body.index("UPDATE_COMPLETE") < r.body.rindex("CREATE_IN_PROGRESS"))
    r = call("GetTemplate", StackName="up-stack")
    _check("get template returns original body", "AWS::SQS::Queue" in r.body)

    # ── drift: delete a resource out-of-band (via its own core) then detect ─
    r = call("DescribeStackResources", StackName="conf-stack")
    bucket_phys = _vs(r.body, "PhysicalResourceId")[0]
    s3.objects.pop(bucket_phys, None)
    s3.buckets.pop(bucket_phys, None)
    r = call("DetectStackDrift", StackName="conf-stack")
    _check("drift detection kicked off", r.status == 200)
    detection_id = _v(r.body, "StackDriftDetectionId")
    r = call("DescribeStackDriftDetectionStatus", StackDriftDetectionId=detection_id)
    _check("drift detected (bucket deleted out-of-band)", "<StackDriftStatus>DRIFTED</StackDriftStatus>" in r.body)
    r = call("DescribeStackResourceDrifts", StackName="conf-stack")
    _check("resource-level drift flagged DELETED", "<StackResourceDriftStatus>DELETED</StackResourceDriftStatus>" in r.body)

    # ── AWS::Logs::LogGroup: a 6th provisioned type, with a real UpdateStack hook ───
    log_tpl = json.dumps({"Resources": {"LG": {"Type": "AWS::Logs::LogGroup",
                          "Properties": {"LogGroupName": "cfn-conf-loggroup", "RetentionInDays": 7}}}})
    r = call("CreateStack", StackName="log-stack", TemplateBody=log_tpl)
    _check("log group stack create 200", r.status == 200)
    _check("log group actually created in the Logs store", logs.log_groups.get("cfn-conf-loggroup") is not None)
    _check("retention applied at create time", logs.log_groups["cfn-conf-loggroup"].get("retentionInDays") == 7)
    log_tpl2 = json.dumps({"Resources": {"LG": {"Type": "AWS::Logs::LogGroup",
                           "Properties": {"LogGroupName": "cfn-conf-loggroup", "RetentionInDays": 14}}}})
    r = call("UpdateStack", StackName="log-stack", TemplateBody=log_tpl2)
    _check("log group update 200", r.status == 200)
    _check("retention really changed (ENFORCED, not just stored)", logs.log_groups["cfn-conf-loggroup"]["retentionInDays"] == 14)

    # ── property-level drift: an out-of-band change through the resource's OWN core ──
    logs.log_groups["cfn-conf-loggroup"]["retentionInDays"] = 30  # someone edited it via the Logs console
    r = call("DetectStackDrift", StackName="log-stack")
    _check("log-stack drift detection kicked off", r.status == 200)
    r = call("DescribeStackResourceDrifts", StackName="log-stack")
    _check("property drift flagged MODIFIED (not just existence)", "<StackResourceDriftStatus>MODIFIED</StackResourceDriftStatus>" in r.body)
    _check("property difference names RetentionInDays", "<PropertyPath>/RetentionInDays</PropertyPath>" in r.body)
    _check("property difference shows expected 14", "<ExpectedValue>14</ExpectedValue>" in r.body)
    _check("property difference shows actual 30", "<ActualValue>30</ActualValue>" in r.body)
    logs.log_groups["cfn-conf-loggroup"]["retentionInDays"] = 14  # un-drift
    r = call("DetectStackDrift", StackName="log-stack")
    r = call("DescribeStackResourceDrifts", StackName="log-stack")
    _check("drift clears once the live property matches the baseline again", "<StackResourceDriftStatus>IN_SYNC</StackResourceDriftStatus>" in r.body)
    r = call("DeleteStack", StackName="log-stack")
    _check("log group stack delete 200", r.status == 200)
    _check("log group torn down with the stack", logs.log_groups.get("cfn-conf-loggroup") is None)

    # ── ValidateTemplate ─────────────────────────────────────────────────────
    r = call("ValidateTemplate", TemplateBody=iam_tpl)
    _check("validate reports CAPABILITY_IAM", "<member>CAPABILITY_IAM</member>" in r.body)
    _check("validate rejects unsupported type", err(call("ValidateTemplate", TemplateBody=bad), "ValidationError"))

    # ── termination protection blocks delete ────────────────────────────────
    call("UpdateTerminationProtection", StackName="yaml-stack", EnableTerminationProtection="true")
    _check("delete blocked by termination protection", err(call("DeleteStack", StackName="yaml-stack"), "ValidationError"))
    call("UpdateTerminationProtection", StackName="yaml-stack", EnableTerminationProtection="false")
    r = call("DeleteStack", StackName="yaml-stack")
    _check("delete stack 200", r.status == 200)
    _check("queue torn down with the stack", msg.get_queue("cfn-conf-queue") is None)
    r2 = call("DescribeStacks", StackName="yaml-stack")
    _check("deleted stack reports DELETE_COMPLETE", "<StackStatus>DELETE_COMPLETE</StackStatus>" in r2.body)
    _check("name freed for reuse", call("CreateStack", StackName="yaml-stack",
           TemplateBody=json.dumps({"Resources": {"Z": {"Type": "AWS::SQS::Queue", "Properties": {}}}})).status == 200)

    # ── ListStacks filter ────────────────────────────────────────────────────
    r = call("ListStacks", **{"StackStatusFilter.member.1": "DELETE_COMPLETE"})
    _check("list filter finds the deleted stack history", "yaml-stack" in r.body)

    # ── StackSets (control-plane only) ──────────────────────────────────────
    r = call("CreateStackSet", StackSetName="ss1",
             TemplateBody=json.dumps({"Resources": {"Q": {"Type": "AWS::SQS::Queue", "Properties": {}}}}))
    _check("create stack set 200", r.status == 200)
    r = call("ListStackSets")
    _check("stack set listed", "<StackSetName>ss1</StackSetName>" in r.body)
    r = call("DeleteStackSet", StackSetName="ss1")
    _check("delete stack set 200", r.status == 200)
    _check("stack set gone", err(call("DescribeStackSet", StackSetName="ss1"), "StackSetNotFoundException"))

    r = call("ListStackRefactors")
    _check("stack refactors list (empty, real endpoint)", "<StackRefactorSummaries>" in r.body)

    # ── registry: ListTypes / DescribeType (the real provisionable resource types) ──
    r = call("ListTypes", Visibility="PUBLIC", Type="RESOURCE")
    _check("ListTypes 200", r.status == 200)
    _check("ListTypes lists AWS::S3::Bucket", "<TypeName>AWS::S3::Bucket</TypeName>" in r.body)
    _check("ListTypes marks it activated", "<IsActivated>true</IsActivated>" in r.body)
    r = call("ListTypes", Visibility="PRIVATE", Type="RESOURCE")
    _check("ListTypes PRIVATE is empty (nothing private registered)", "<member>" not in r.body)
    r = call("DescribeType", TypeName="AWS::S3::Bucket")
    _check("DescribeType 200", r.status == 200)
    _check("DescribeType returns a schema", "<Schema>" in r.body and "typeName" in r.body)
    _check("DescribeType unknown type fails honestly", err(call("DescribeType", TypeName="AWS::EC2::Instance"), "TypeNotFoundException"))

    # ── stack refactors: CreateStackRefactor / ExecuteStackRefactor really move a
    # resource's runtime state between two existing stacks ──────────────────────
    call("CreateStack", StackName="refactor-src", TemplateBody=json.dumps({"Resources": {"Q": {"Type": "AWS::SQS::Queue", "Properties": {"QueueName": "cfn-conf-refactor-q"}}}}))
    call("CreateStack", StackName="refactor-dst", TemplateBody=json.dumps({"Resources": {"B": {"Type": "AWS::S3::Bucket", "Properties": {}}}}))
    r = call("CreateStackRefactor", Description="conformance-refactor",
             **{"ResourceMappings.member.1.Source.StackName": "refactor-src",
                "ResourceMappings.member.1.Source.LogicalResourceId": "Q",
                "ResourceMappings.member.1.Destination.StackName": "refactor-dst",
                "ResourceMappings.member.1.Destination.LogicalResourceId": "QMoved"})
    _check("create stack refactor 200", r.status == 200)
    refactor_id = _v(r.body, "StackRefactorId")
    _check("missing resource mapping rejected", err(call("CreateStackRefactor"), "ValidationError"))
    r = call("DescribeStackRefactor", StackRefactorId=refactor_id)
    _check("describe stack refactor AVAILABLE", "<ExecutionStatus>AVAILABLE</ExecutionStatus>" in r.body)
    r = call("ExecuteStackRefactor", StackRefactorId=refactor_id)
    _check("execute stack refactor 200", r.status == 200)
    r = call("ListStackResources", StackName="refactor-dst")
    _check("moved resource now in destination stack", "<LogicalResourceId>QMoved</LogicalResourceId>" in r.body)
    r = call("ListStackResources", StackName="refactor-src")
    _check("moved resource gone from source stack", "<LogicalResourceId>Q</LogicalResourceId>" not in r.body)
    _check("queue still exists (moved, not destroyed)", msg.get_queue("cfn-conf-refactor-q") is not None)
    _check("re-executing an executed refactor fails", err(call("ExecuteStackRefactor", StackRefactorId=refactor_id), "ValidationError"))
    r = call("ListStackRefactors")
    _check("executed refactor listed", f"<StackRefactorId>{refactor_id}</StackRefactorId>" in r.body and "<ExecutionStatus>EXECUTE_COMPLETE</ExecutionStatus>" in r.body)

    # ── IaC generator: scan real resources, generate a template from a selection ──
    call("CreateStack", StackName="iacgen-managed", TemplateBody=json.dumps(
        {"Resources": {"Q": {"Type": "AWS::SQS::Queue", "Properties": {"QueueName": "cfn-iacgen-managed-q"}}}}))
    r = call("CreateStack", StackName="iacgen-unmanaged", TemplateBody=json.dumps(
        {"Resources": {"R": {"Type": "AWS::IAM::Role", "Properties": {
            "RoleName": "cfn-iacgen-role", "Description": "scan me"}}}},
    ), **{"Capabilities.member.1": "CAPABILITY_NAMED_IAM"})
    _check("iacgen role stack created", r.status == 200)

    r = call("StartResourceScan")
    _check("start resource scan 200", r.status == 200)
    scan_id = _v(r.body, "ResourceScanId")
    _check("scan id shaped", scan_id.startswith("arn:aws:cloudformation:"))
    r = call("DescribeResourceScan", ResourceScanId=scan_id)
    _check("scan complete", "<Status>COMPLETE</Status>" in r.body)
    _check("scan found resources", int(_v(r.body, "ResourcesScanned")) >= 2)
    r = call("ListResourceScans")
    _check("scan listed", f"<ResourceScanId>{scan_id}</ResourceScanId>" in r.body)
    r = call("ListResourceScanResources", ResourceScanId=scan_id, ResourceTypePrefix="AWS::IAM::")
    _check("scan resources filtered to IAM roles", "<ResourceType>AWS::IAM::Role</ResourceType>" in r.body
           and "<key>RoleName</key>" in r.body and "<value>cfn-iacgen-role</value>" in r.body)
    _check("role resource scanned as managed by its stack", "<ManagedByStack>true</ManagedByStack>" in r.body)
    r = call("ListResourceScanResources", ResourceScanId=scan_id, ResourceTypePrefix="AWS::SQS::")
    _check("unrelated prefix filter excludes other types", "<ResourceType>" not in r.body or "AWS::SQS::Queue" in r.body)

    r = call("CreateGeneratedTemplate", GeneratedTemplateName="iacgen-tpl",
             **{"Resources.member.1.ResourceType": "AWS::IAM::Role",
                "Resources.member.1.ResourceIdentifier.entry.1.key": "RoleName",
                "Resources.member.1.ResourceIdentifier.entry.1.value": "cfn-iacgen-role"})
    _check("create generated template 200", r.status == 200)
    template_arn = _v(r.body, "GeneratedTemplateId")
    _check("generated template id shaped", "generatedtemplate" in template_arn)
    _check("duplicate generated template name rejected",
           err(call("CreateGeneratedTemplate", GeneratedTemplateName="iacgen-tpl",
                     **{"Resources.member.1.ResourceType": "AWS::IAM::Role",
                        "Resources.member.1.ResourceIdentifier.entry.1.key": "RoleName",
                        "Resources.member.1.ResourceIdentifier.entry.1.value": "cfn-iacgen-role"}), "AlreadyExistsException"))
    _check("scanning a resource that doesn't exist fails honestly",
           err(call("CreateGeneratedTemplate", GeneratedTemplateName="iacgen-tpl-missing",
                     **{"Resources.member.1.ResourceType": "AWS::IAM::Role",
                        "Resources.member.1.ResourceIdentifier.entry.1.key": "RoleName",
                        "Resources.member.1.ResourceIdentifier.entry.1.value": "no-such-role"}), "ResourceNotFoundException"))

    r = call("DescribeGeneratedTemplate", GeneratedTemplateName="iacgen-tpl")
    _check("describe generated template complete", "<Status>COMPLETE</Status>" in r.body)
    _check("describe shows the logical id", "<LogicalResourceId>Cfniacgenrole</LogicalResourceId>" in r.body)
    r = call("GetGeneratedTemplate", GeneratedTemplateName="iacgen-tpl")
    _check("get generated template returns real live properties, not just the name",
           "AWS::IAM::Role" in r.body and "cfn-iacgen-role" in r.body and "scan me" in r.body)
    # the generated template really round-trips back through CreateStack
    body = json.loads(_v(r.body, "TemplateBody"))
    _check("generated template Resources block is well-formed", "Cfniacgenrole" in body["Resources"])
    r = call("ListGeneratedTemplates")
    _check("generated template listed", "<GeneratedTemplateName>iacgen-tpl</GeneratedTemplateName>" in r.body
           and "<NumberOfResources>1</NumberOfResources>" in r.body)
    r = call("DeleteGeneratedTemplate", GeneratedTemplateName="iacgen-tpl")
    _check("delete generated template 200", r.status == 200)
    _check("deleted generated template gone",
           err(call("DescribeGeneratedTemplate", GeneratedTemplateName="iacgen-tpl"), "GeneratedTemplateNotFoundException"))

    print("\nRESULT: PASS — CloudFormation core conforms.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
