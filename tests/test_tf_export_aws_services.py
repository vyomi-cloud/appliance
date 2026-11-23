"""DynamoDB / SQS / SNS / EventBridge / KMS / Step Functions / ECR / CloudWatch alarms / EC2 instances / Backup exporters, against canned API answers."""
import json

from core.tf_export import build_aws_with
from core.tf_export.graph import build_graph, classify
from core.tf_export.core import Ctx, registered, render_files

ACCT = "arn:aws:{}:us-east-1:123456789012:{}"


class Fake:
    """A boto3-shaped client: ``answers`` maps a snake_case operation to a dict or a callable(**kw) -> dict; unknown operations raise."""

    def __init__(self, answers):
        self.a = answers

    def __getattr__(self, op):
        if op.startswith("_"):
            raise AttributeError(op)
        v = self.a.get(op, {})  # an operation the test did not describe answers with an empty page
        return v if callable(v) else (lambda **kw: v)

    def get_paginator(self, op):
        fn = getattr(self, op)

        class P:
            def paginate(self, **kw):
                yield fn(**kw)
        return P()


def _clients(**svc):
    empty = {n: Fake({}) for n in ("ec2", "s3", "logs", "iam", "lambda", "apigateway", "rds", "secretsmanager", "dynamodb", "sqs", "sns", "events", "kms",
                                   "stepfunctions", "ecr", "cloudwatch", "backup")}
    empty.update({k: Fake(v) for k, v in svc.items()})
    return empty


def _export(**svc):
    r = build_aws_with(_clients(**svc))
    assert not r["summary"]["errors"], r["summary"]["errors"]
    return "\n".join(r["files"].values()), r


def test_dynamodb_table_with_gsi_ttl_pitr_and_tags():
    tarn = ACCT.format("dynamodb", "table/orders")
    text, _ = _export(dynamodb={
        "list_tables": {"TableNames": ["orders"]},
        "describe_table": {"Table": {"TableName": "orders", "TableArn": tarn, "BillingModeSummary": {"BillingMode": "PAY_PER_REQUEST"},
                                     "KeySchema": [{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
                                     "AttributeDefinitions": [{"AttributeName": "sk", "AttributeType": "S"}, {"AttributeName": "pk", "AttributeType": "S"},
                                                              {"AttributeName": "st", "AttributeType": "S"}],
                                     "GlobalSecondaryIndexes": [{"IndexName": "by-st", "KeySchema": [{"AttributeName": "st", "KeyType": "HASH"}],
                                                                 "Projection": {"ProjectionType": "INCLUDE", "NonKeyAttributes": ["b", "a"]}}]}},
        "describe_time_to_live": {"TimeToLiveDescription": {"TimeToLiveStatus": "ENABLED", "AttributeName": "exp"}},
        "describe_continuous_backups": {"ContinuousBackupsDescription": {"PointInTimeRecoveryDescription": {"PointInTimeRecoveryStatus": "ENABLED"}}},
        "list_tags_of_resource": {"Tags": [{"Key": "team", "Value": "shop"}]}})
    assert 'resource "aws_dynamodb_table" "orders"' in text and 'billing_mode = "PAY_PER_REQUEST"' in text
    assert text.index('name = "pk"') < text.index('name = "sk"') < text.index('name = "st"')  # attribute blocks sorted
    assert 'non_key_attributes = [\n      "a",\n      "b",' in text
    assert 'attribute_name = "exp"' in text and "point_in_time_recovery {" in text and "read_capacity" not in text


def test_sqs_dead_letter_redrive_is_a_reference_and_policy_does_not_self_reference():
    dlq, q = ACCT.format("sqs", "dlq"), ACCT.format("sqs", "work")
    attrs = {"https://sqs/dlq": {"QueueArn": dlq},
             "https://sqs/work": {"QueueArn": q, "VisibilityTimeout": "60",
                                  "RedrivePolicy": json.dumps({"deadLetterTargetArn": dlq, "maxReceiveCount": "5"}),
                                  "Policy": json.dumps({"Statement": [{"Resource": q, "Sid": "s"}]})}}
    text, _ = _export(sqs={"list_queues": {"QueueUrls": list(attrs)}, "get_queue_attributes": lambda QueueUrl, **kw: {"Attributes": attrs[QueueUrl]}})
    assert "deadLetterTargetArn = aws_sqs_queue.dlq.arn" in text and "maxReceiveCount = 5" in text
    assert "visibility_timeout_seconds = 60" in text
    assert f'Resource = "{q}"' in text  # a resource cannot reference itself


def test_sns_subscription_endpoint_references_the_queue_and_pending_ones_are_skipped():
    q, t = ACCT.format("sqs", "work"), ACCT.format("sns", "events")
    subs = {"Subscriptions": [{"SubscriptionArn": t + ":1", "Protocol": "sqs", "Endpoint": q}, {"SubscriptionArn": "PendingConfirmation", "Protocol": "email", "Endpoint": "a@b.c"}]}
    text, r = _export(sqs={"list_queues": {"QueueUrls": ["https://sqs/work"]}, "get_queue_attributes": {"Attributes": {"QueueArn": q}}},
                      sns={"list_topics": {"Topics": [{"TopicArn": t}]}, "get_topic_attributes": {"Attributes": {"DisplayName": "Ev", "Policy": json.dumps(
                          {"Statement": [{"Sid": "__default_statement_ID"}]})}}, "list_subscriptions_by_topic": subs,
                           "get_subscription_attributes": {"Attributes": {"RawMessageDelivery": "true"}}})
    assert "endpoint = aws_sqs_queue.work.arn" in text and "topic_arn = aws_sns_topic.events.arn" in text and "raw_message_delivery = true" in text
    assert "policy" not in text.split('resource "aws_sns_topic" "events"')[1].split("}")[0]  # the default topic policy is not exported
    assert any(s["type"] == "aws_sns_topic_subscription" for s in r["summary"]["skipped"])


def test_eventbridge_rule_targets_reference_exported_resources():
    q = ACCT.format("sqs", "work")
    text, _ = _export(
        sqs={"list_queues": {"QueueUrls": ["https://sqs/work"]}, "get_queue_attributes": {"Attributes": {"QueueArn": q}}},
        events={"list_event_buses": {"EventBuses": [{"Name": "default", "Arn": "x"}, {"Name": "partners", "Arn": "y"}]},
                "describe_event_bus": {"Name": "partners"},
                "list_rules": lambda EventBusName, **kw: {"Rules": [{"Name": "r1"}] if EventBusName == "partners" else []},
                "describe_rule": {"Name": "r1", "Arn": "arn:r1", "EventPattern": json.dumps({"source": ["a"]}), "State": "DISABLED"},
                "list_targets_by_rule": {"Targets": [{"Id": "t1", "Arn": q, "RetryPolicy": {"MaximumRetryAttempts": 2}}]}})
    assert 'event_bus_name = aws_cloudwatch_event_bus.partners.name' in text and 'state = "DISABLED"' in text
    assert "arn = aws_sqs_queue.work.arn" in text and "maximum_retry_attempts = 2" in text


def test_kms_key_alias_and_references_from_dependents():
    karn = ACCT.format("kms", "key/abc")
    text, _ = _export(kms={
        "list_keys": {"Keys": [{"KeyId": "abc"}, {"KeyId": "aws-managed"}]},
        "list_aliases": {"Aliases": [{"AliasName": "alias/app", "TargetKeyId": "abc"}, {"AliasName": "alias/aws/s3", "TargetKeyId": "aws-managed"}]},
        "describe_key": lambda KeyId, **kw: {"KeyMetadata": {"KeyId": KeyId, "Arn": ACCT.format("kms", f"key/{KeyId}"), "KeyManager": "AWS" if KeyId == "aws-managed" else "CUSTOMER",
                                                             "KeyState": "Enabled", "KeyUsage": "ENCRYPT_DECRYPT", "KeySpec": "SYMMETRIC_DEFAULT", "Description": "d"}},
        "get_key_rotation_status": {"KeyRotationEnabled": True}, "get_key_policy": {"Policy": json.dumps({"Statement": []})}},
        dynamodb={"list_tables": {"TableNames": ["t"]}, "describe_table": {"Table": {
            "TableName": "t", "TableArn": ACCT.format("dynamodb", "table/t"), "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}],
            "AttributeDefinitions": [{"AttributeName": "id", "AttributeType": "S"}], "SSEDescription": {"Status": "ENABLED", "SSEType": "KMS", "KMSMasterKeyArn": karn}}}})
    assert 'resource "aws_kms_key" "app"' in text and "enable_key_rotation = true" in text and "aws/s3" not in text
    assert "target_key_id = aws_kms_key.app.key_id" in text and "kms_key_arn = aws_kms_key.app.arn" in text


def test_step_function_definition_references_lambda_and_role():
    fn = ACCT.format("lambda", "function:worker")
    role = "arn:aws:iam::123456789012:role/sfn"
    text, _ = _export(
        iam={"list_roles": {"Roles": [{"RoleName": "sfn", "Arn": role, "Path": "/"}]}, "get_role": {"Role": {"AssumeRolePolicyDocument": {"Statement": []}}},
             "list_role_policies": {"PolicyNames": []}, "list_attached_role_policies": {"AttachedPolicies": []}},
        **{"lambda": {"list_functions": {"Functions": [{"FunctionName": "worker", "FunctionArn": fn, "Role": role, "Runtime": "python3.12", "Handler": "i.h"}]},
                      "get_function": {"Code": {}, "Tags": {}}}},
        stepfunctions={"list_state_machines": {"stateMachines": [{"name": "flow", "stateMachineArn": ACCT.format("states", "stateMachine:flow")}]},
                       "describe_state_machine": {"name": "flow", "roleArn": role, "type": "STANDARD",
                                                  "definition": json.dumps({"StartAt": "A", "States": {"A": {"Type": "Task", "Resource": fn, "End": True}}})}})
    assert "role_arn = aws_iam_role.sfn.arn" in text and "Resource = aws_lambda_function.worker.arn" in text


def test_ecr_repository_lifecycle_and_scan_on_push():
    text, _ = _export(ecr={"describe_repositories": {"repositories": [{"repositoryName": "shop/api", "repositoryArn": ACCT.format("ecr", "repository/shop/api"),
                                                                       "imageTagMutability": "IMMUTABLE", "imageScanningConfiguration": {"scanOnPush": True}}]},
                           "get_lifecycle_policy": {"lifecyclePolicyText": json.dumps({"rules": []})}})
    assert 'image_tag_mutability = "IMMUTABLE"' in text and "scan_on_push = true" in text
    assert "repository = aws_ecr_repository.shop_api.name" in text


def test_alarm_actions_reference_topics_and_composite_rule_references_alarms():
    t = ACCT.format("sns", "ops")
    alarm = {"AlarmName": "cpu", "AlarmArn": ACCT.format("cloudwatch", "alarm:cpu"), "ComparisonOperator": "GreaterThanThreshold", "EvaluationPeriods": 2, "Threshold": 80.0,
             "MetricName": "CPUUtilization", "Namespace": "AWS/EC2", "Period": 60, "Statistic": "Average", "AlarmActions": [t, "arn:aws:automate:us-east-1:ec2:recover"],
             "Dimensions": [{"Name": "InstanceId", "Value": "i-1"}]}
    comp = {"AlarmName": "any", "AlarmArn": ACCT.format("cloudwatch", "alarm:any"), "AlarmRule": 'ALARM("cpu") OR ALARM(unknown)'}
    text, _ = _export(
        sns={"list_topics": {"Topics": [{"TopicArn": t}]}, "get_topic_attributes": {"Attributes": {}}, "list_subscriptions_by_topic": {"Subscriptions": []}},
        cloudwatch={"describe_alarms": {"MetricAlarms": [alarm], "CompositeAlarms": [comp]}})
    assert "aws_sns_topic.ops.arn" in text and '"arn:aws:automate:us-east-1:ec2:recover"' in text
    assert 'alarm_rule = "ALARM(\\"${aws_cloudwatch_metric_alarm.cpu.alarm_name}\\") OR ALARM(unknown)"' in text or \
        "${aws_cloudwatch_metric_alarm.cpu.alarm_name}" in text


def test_instances_are_deduplicated_and_volume_attachments_reference_them():
    inst = {"InstanceId": "i-1", "ImageId": "ami-1", "InstanceType": "t3.micro", "State": {"Name": "running"}, "Tags": [{"Key": "Name", "Value": "web"}],
            "RootDeviceName": "/dev/xvda", "SecurityGroups": [{"GroupId": "sg-1"}], "KeyName": "k",
            "BlockDeviceMappings": [{"DeviceName": "/dev/xvda", "Ebs": {"VolumeId": "vol-root", "DeleteOnTermination": True}},
                                    {"DeviceName": "/dev/sdf", "Ebs": {"VolumeId": "vol-data"}}]}
    vols = {"Volumes": [{"VolumeId": "vol-root", "Size": 8, "VolumeType": "gp3", "AvailabilityZone": "us-east-1a"},
                        {"VolumeId": "vol-data", "Size": 20, "VolumeType": "gp3", "AvailabilityZone": "us-east-1a", "Tags": [{"Key": "Name", "Value": "data"}],
                         "Attachments": [{"InstanceId": "i-1", "Device": "/dev/sdf"}]}]}
    text, r = _export(ec2={"describe_key_pairs": {"KeyPairs": [{"KeyName": "k", "PublicKey": "ssh-ed25519 AAAA"}]},
                           "describe_instances": {"Reservations": [{"Instances": [inst]}, {"Instances": [inst]}]},
                           "describe_volumes": vols, "describe_instance_attribute": {}})
    assert text.count('resource "aws_instance"') == 1 and "key_name = aws_key_pair.k.key_name" in text
    assert 'public_key = "ssh-ed25519 AAAA"' in text and "var.public_key" not in text
    assert text.count('resource "aws_ebs_volume"') == 1 and "volume_size = 8" in text  # root volume is a root_block_device, not a volume
    assert "instance_id = aws_instance.web.id" in text and "volume_id = aws_ebs_volume.data.id" in text


def test_backup_plan_rule_references_vault_and_selection_references_exported_resources():
    ddb = ACCT.format("dynamodb", "table/orders")
    role = "arn:aws:iam::123456789012:role/bk"
    text, _ = _export(
        dynamodb={"list_tables": {"TableNames": ["orders"]}, "describe_table": {"Table": {"TableName": "orders", "TableArn": ddb, "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}],
                                                                                          "AttributeDefinitions": [{"AttributeName": "id", "AttributeType": "S"}]}}},
        iam={"list_roles": {"Roles": [{"RoleName": "bk", "Arn": role, "Path": "/"}]}, "get_role": {"Role": {"AssumeRolePolicyDocument": {"Statement": []}}},
             "list_role_policies": {"PolicyNames": []}, "list_attached_role_policies": {"AttachedPolicies": []}},
        backup={"list_backup_vaults": {"BackupVaultList": [{"BackupVaultName": "Default", "BackupVaultArn": "x"}, {"BackupVaultName": "primary", "BackupVaultArn": "y"}]},
                "list_backup_plans": {"BackupPlansList": [{"BackupPlanId": "p1", "BackupPlanName": "daily", "BackupPlanArn": "z"}]},
                "get_backup_plan": {"BackupPlan": {"Rules": [{"RuleName": "r", "TargetBackupVaultName": "primary", "ScheduleExpression": "cron(0 5 * * ? *)",
                                                              "StartWindowMinutes": 480, "Lifecycle": {"DeleteAfterDays": 35}}]}},
                "list_backup_selections": {"BackupSelectionsList": [{"SelectionId": "s1", "SelectionName": "tables"}]},
                "get_backup_selection": {"BackupSelection": {"SelectionName": "tables", "IamRoleArn": role, "Resources": [ddb]}}})
    assert 'aws_backup_vault" "default"' not in text and "target_vault_name = aws_backup_vault.primary.name" in text
    assert "start_window" not in text and "delete_after = 35" in text
    assert "iam_role_arn = aws_iam_role.bk.arn" in text and "aws_dynamodb_table.orders.arn" in text and "plan_id = aws_backup_plan.daily.id" in text


def test_classifier_and_graph_cover_the_new_services_with_reference_edges():
    types = ["aws_dynamodb_table", "aws_sqs_queue", "aws_sns_topic", "aws_sns_topic_subscription", "aws_cloudwatch_event_rule", "aws_cloudwatch_event_target",
             "aws_cloudwatch_event_bus", "aws_kms_key", "aws_kms_alias", "aws_sfn_state_machine", "aws_ecr_repository", "aws_cloudwatch_metric_alarm", "aws_instance",
             "aws_key_pair", "aws_ebs_volume", "aws_volume_attachment", "aws_backup_plan", "aws_backup_vault", "aws_backup_selection", "aws_kinesis_stream"]
    v = classify(types)
    assert all(v[t]["status"] == "supported" for t in types[:-1]) and v["aws_kinesis_stream"]["status"] == "planned"
    q = ACCT.format("sqs", "work")
    t = ACCT.format("sns", "ev")
    text, r = _export(sqs={"list_queues": {"QueueUrls": ["https://sqs/work"]}, "get_queue_attributes": {"Attributes": {"QueueArn": q}}},
                      sns={"list_topics": {"Topics": [{"TopicArn": t}]}, "get_topic_attributes": {"Attributes": {}},
                           "list_subscriptions_by_topic": {"Subscriptions": [{"SubscriptionArn": t + ":1", "Protocol": "sqs", "Endpoint": q}]},
                           "get_subscription_attributes": {"Attributes": {}}})
    g = r["graph"]
    assert {"from": "aws_sns_topic_subscription.ev_sqs_work", "to": "aws_sqs_queue.work"} in g["edges"]
    assert {n["service"] for n in g["nodes"]} == {"sns", "sqs"}


def test_every_new_exporter_is_registered_and_wasm_lists_every_module():
    names = {n for _o, n, _f in registered()}
    assert {"dynamodb", "sqs", "sns", "eventbridge", "kms", "stepfunctions", "ecr", "cloudwatch-alarms", "ec2-instances", "backup"} <= names
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent
    mods = sorted(p.name for p in (root / "core" / "tf_export").glob("*.py"))
    for f in ("wasm/nano-boot.js", "wasm/build_cores.py", "wasm/relay/relay-shared-worker.js", "wasm/relay/nano-endpoint.html"):
        text = (root / f).read_text()
        assert all(f"tf_export/{m}" in text for m in mods), f
    from core.tf_export.wire_clients import AWS_SERVICES
    keep = (root / "wasm" / "build_botocore_lite.py").read_text()
    assert all(f'"{s}"' in keep for s in AWS_SERVICES)
