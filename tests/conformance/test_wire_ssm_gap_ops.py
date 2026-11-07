"""SSM wire gaps closed by core/ssm_gap_core.py, driven by a real boto3 `ssm` client over the router."""
import json
import os
import sys

import pytest
from botocore.exceptions import ClientError

sys.path.insert(0, os.path.dirname(__file__))
from _wire_boto import make_clients  # noqa: E402

IID = "i-0123456789abcdef0"


@pytest.fixture()
def ssm():
    _, client = make_clients()
    return client("ssm")


def code(fn, **kw):
    with pytest.raises(ClientError) as e:
        fn(**kw)
    return e.value.response["Error"]["Code"]


def test_service_settings(ssm):
    sid = "/ssm/parameter-store/high-throughput-enabled"
    s = ssm.get_service_setting(SettingId=sid)["ServiceSetting"]
    assert s["SettingValue"] == "false" and s["Status"] == "Default" and s["ARN"].endswith("servicesetting" + sid)
    ssm.update_service_setting(SettingId=s["ARN"], SettingValue="true")
    assert ssm.get_service_setting(SettingId=sid)["ServiceSetting"]["Status"] == "Customized"
    assert code(ssm.update_service_setting, SettingId=sid, SettingValue="maybe") == "ValidationException"
    assert ssm.reset_service_setting(SettingId=sid)["ServiceSetting"]["Status"] == "Default"
    assert code(ssm.get_service_setting, SettingId="/ssm/nope") == "ServiceSettingNotFound"


def test_inventory(ssm):
    ssm.put_inventory(InstanceId=IID, Items=[{"TypeName": "AWS:Application", "SchemaVersion": "1.1", "CaptureTime": "2026-11-01T00:00:00Z",
                                              "Content": [{"Name": "nginx", "Version": "1.24"}, {"Name": "curl", "Version": "8.0"}]},
                                             {"TypeName": "Custom:Rack", "SchemaVersion": "1.0", "CaptureTime": "2026-11-01T00:00:00Z", "Content": [{"slot": "7"}]}])
    ssm.put_inventory(InstanceId="i-0fedcba987654321a", Items=[{"TypeName": "AWS:Application", "SchemaVersion": "1.1", "CaptureTime": "2026-11-01T00:00:00Z", "Content": [{"Name": "redis", "Version": "7"}]}])
    assert code(ssm.put_inventory, InstanceId=IID, Items=[{"TypeName": "Bogus", "SchemaVersion": "1.0", "CaptureTime": "x", "Content": [{"a": "b"}]}]) == "InvalidTypeNameException"
    assert code(ssm.put_inventory, InstanceId="nope", Items=[{"TypeName": "Custom:X", "SchemaVersion": "1.0", "CaptureTime": "x", "Content": [{"a": "b"}]}]) == "InvalidInstanceId"
    ents = ssm.get_inventory(Filters=[{"Key": "AWS:Application.Name", "Values": ["nginx"], "Type": "Equal"}])["Entities"]
    assert [e["Id"] for e in ents] == [IID]
    assert len(ssm.get_inventory()["Entities"]) == 2
    le = ssm.list_inventory_entries(InstanceId=IID, TypeName="AWS:Application", Filters=[{"Key": "Name", "Values": ["curl"], "Type": "Equal"}])
    assert le["Entries"] == [{"Name": "curl", "Version": "8.0"}]
    names = [s["TypeName"] for s in ssm.get_inventory_schema()["Schemas"]]
    assert "AWS:Application" in names and "Custom:Rack" in names
    assert code(ssm.delete_inventory, TypeName="AWS:Application") == "InvalidTypeNameException"
    dry = ssm.delete_inventory(TypeName="Custom:Rack", DryRun=True)
    assert dry["DeletionSummary"]["TotalCount"] == 1
    assert ssm.list_inventory_entries(InstanceId=IID, TypeName="Custom:Rack")["Entries"]            # a dry run deleted nothing
    real = ssm.delete_inventory(TypeName="Custom:Rack")
    assert code(ssm.list_inventory_entries, InstanceId=IID, TypeName="Custom:Rack") == "InvalidTypeNameException"
    assert ssm.describe_inventory_deletions(DeletionId=real["DeletionId"])["InventoryDeletions"][0]["LastStatus"] == "Complete"


def test_opscenter_and_activations_and_policies(ssm):
    oid = ssm.create_ops_item(Title="disk full", Description="/ at 98%", Source="monitor", Priority=2, OperationalData={"host": {"Value": "web1", "Type": "SearchableString"}})["OpsItemId"]
    assert ssm.get_ops_item(OpsItemId=oid)["OpsItem"]["Status"] == "Open"
    ssm.update_ops_item(OpsItemId=oid, Status="InProgress")
    assert code(ssm.update_ops_item, OpsItemId=oid, Status="Bogus") == "ValidationException"
    assert [i["OpsItemId"] for i in ssm.describe_ops_items(OpsItemFilters=[{"Key": "Status", "Values": ["InProgress"], "Operator": "Equal"}])["OpsItemSummaries"]] == [oid]
    assert ssm.describe_ops_items(OpsItemFilters=[{"Key": "Status", "Values": ["Open"], "Operator": "Equal"}])["OpsItemSummaries"] == []
    rid = ssm.associate_ops_item_related_item(OpsItemId=oid, AssociationType="IsParentOf", ResourceType="AWS::SSM::Document", ResourceUri="arn:aws:ssm:us-east-1:123456789012:document/x")["AssociationId"]
    assert len(ssm.list_ops_item_related_items(OpsItemId=oid)["Summaries"]) == 1
    ssm.disassociate_ops_item_related_item(OpsItemId=oid, AssociationId=rid)
    assert any(e["DetailType"] == "ssm:OpsItem:StatusChange" for e in ssm.list_ops_item_events()["Summaries"])
    md = ssm.create_ops_metadata(ResourceId="my-app", Metadata={"owner": {"Value": "team-a"}})["OpsMetadataArn"]
    ssm.update_ops_metadata(OpsMetadataArn=md, MetadataToUpdate={"tier": {"Value": "gold"}}, KeysToDelete=["owner"])
    assert ssm.get_ops_metadata(OpsMetadataArn=md)["Metadata"] == {"tier": {"Value": "gold"}}
    ssm.delete_ops_metadata(OpsMetadataArn=md)
    ssm.delete_ops_item(OpsItemId=oid)
    assert code(ssm.get_ops_item, OpsItemId=oid) == "OpsItemNotFoundException"

    a = ssm.create_activation(IamRole="ssm-role", DefaultInstanceName="onprem", RegistrationLimit=5)
    assert len(a["ActivationCode"]) == 20
    assert ssm.describe_activations()["ActivationList"][0]["RegistrationLimit"] == 5
    ssm.delete_activation(ActivationId=a["ActivationId"])
    assert code(ssm.delete_activation, ActivationId=a["ActivationId"]) == "InvalidActivationId"

    ssm.put_parameter(Name="/app/db", Value="x", Type="String", Tier="Advanced")
    arn = "arn:aws:ssm:us-east-1:123456789012:parameter/app/db"
    pol = ssm.put_resource_policy(ResourceArn=arn, Policy=json.dumps({"Version": "2012-10-17", "Statement": []}))
    assert len(ssm.get_resource_policies(ResourceArn=arn)["Policies"]) == 1
    assert code(ssm.delete_resource_policy, ResourceArn=arn, PolicyId=pol["PolicyId"], PolicyHash="wrong") == "ResourcePolicyConflictException"
    ssm.delete_resource_policy(ResourceArn=arn, PolicyId=pol["PolicyId"], PolicyHash=pol["PolicyHash"])
    assert code(ssm.put_resource_policy, ResourceArn="arn:aws:ssm:us-east-1:123456789012:parameter/ghost", Policy="{}") == "ResourceNotFoundException"

    ssm.create_resource_data_sync(SyncName="s", S3Destination={"BucketName": "b", "SyncFormat": "JsonSerDe", "Region": "us-east-1"})
    assert ssm.list_resource_data_sync()["ResourceDataSyncItems"][0]["SyncName"] == "s"
    ssm.delete_resource_data_sync(SyncName="s")


def test_compliance_and_patch_groups(ssm):
    ssm.put_compliance_items(ResourceId=IID, ResourceType="ManagedInstance", ComplianceType="Custom:Baseline", ExecutionSummary={"ExecutionTime": 1700000000},
                             Items=[{"Id": "r1", "Title": "ssh root", "Severity": "HIGH", "Status": "NON_COMPLIANT"}, {"Id": "r2", "Title": "ntp", "Severity": "LOW", "Status": "COMPLIANT"}])
    assert code(ssm.put_compliance_items, ResourceId=IID, ResourceType="ManagedInstance", ComplianceType="PatchX", ExecutionSummary={"ExecutionTime": 1}, Items=[]) == "InvalidItemContentException"
    assert len(ssm.list_compliance_items(ResourceIds=[IID])["ComplianceItems"]) == 2
    summ = ssm.list_compliance_summaries()["ComplianceSummaryItems"][0]
    assert summ["NonCompliantSummary"]["NonCompliantCount"] == 1 and summ["NonCompliantSummary"]["SeveritySummary"]["HighCount"] == 1
    assert ssm.list_resource_compliance_summaries()["ResourceComplianceSummaryItems"][0]["Status"] == "NON_COMPLIANT"

    bid = ssm.create_patch_baseline(Name="linux-base", OperatingSystem="AMAZON_LINUX_2")["BaselineId"]
    other = ssm.create_patch_baseline(Name="linux-other", OperatingSystem="AMAZON_LINUX_2")["BaselineId"]
    ssm.register_patch_baseline_for_patch_group(BaselineId=bid, PatchGroup="prod")
    assert code(ssm.register_patch_baseline_for_patch_group, BaselineId=other, PatchGroup="prod") == "AlreadyExistsException"
    assert ssm.get_patch_baseline_for_patch_group(PatchGroup="prod", OperatingSystem="AMAZON_LINUX_2")["BaselineId"] == bid
    assert ssm.describe_patch_groups()["Mappings"][0]["BaselineIdentity"]["BaselineName"] == "linux-base"
    ssm.register_default_patch_baseline(BaselineId=other)
    assert ssm.get_default_patch_baseline(OperatingSystem="AMAZON_LINUX_2")["BaselineId"] == other
    assert ssm.get_patch_baseline_for_patch_group(PatchGroup="unregistered", OperatingSystem="AMAZON_LINUX_2")["BaselineId"] == other
    u = ssm.update_patch_baseline(BaselineId=bid, Name="renamed", ApprovedPatches=["KB1"])
    assert u["Name"] == "renamed" and ssm.get_patch_baseline(BaselineId=bid)["Name"] == "renamed"
    ssm.deregister_patch_baseline_for_patch_group(BaselineId=bid, PatchGroup="prod")
    assert ssm.describe_patch_groups()["Mappings"] == []
    assert ssm.describe_patch_properties(OperatingSystem="AMAZON_LINUX_2", Property="CLASSIFICATION")["Properties"]
    assert ssm.describe_instance_patch_states(InstanceIds=[IID])["InstancePatchStates"] == []


def test_maintenance_window_tasks_and_association_extras(ssm):
    wid = ssm.create_maintenance_window(Name="nightly", Schedule="cron(0 2 * * ? *)", Duration=2, Cutoff=1, AllowUnassociatedTargets=False)["WindowId"]
    tid = ssm.register_target_with_maintenance_window(WindowId=wid, ResourceType="INSTANCE", Targets=[{"Key": "InstanceIds", "Values": [IID]}])["WindowTargetId"]
    assert ssm.describe_maintenance_windows_for_target(Targets=[{"Key": "InstanceIds", "Values": [IID]}], ResourceType="INSTANCE")["WindowIdentities"][0]["WindowId"] == wid
    assert ssm.describe_maintenance_windows_for_target(Targets=[{"Key": "InstanceIds", "Values": ["i-0aaaaaaaaaaaaaaaa"]}], ResourceType="INSTANCE")["WindowIdentities"] == []
    assert code(ssm.register_task_with_maintenance_window, WindowId=wid, TaskArn="NoSuchDoc", TaskType="RUN_COMMAND", Targets=[{"Key": "WindowTargetIds", "Values": [tid]}]) == "DoesNotExistException"
    wt = ssm.register_task_with_maintenance_window(WindowId=wid, TaskArn="AWS-RunShellScript", TaskType="RUN_COMMAND", Targets=[{"Key": "WindowTargetIds", "Values": [tid]}],
                                                   MaxConcurrency="1", MaxErrors="1", Priority=3, Name="patch")["WindowTaskId"]
    assert ssm.describe_maintenance_window_tasks(WindowId=wid)["Tasks"][0]["Priority"] == 3
    ssm.update_maintenance_window_task(WindowId=wid, WindowTaskId=wt, Priority=1)
    assert ssm.get_maintenance_window_task(WindowId=wid, WindowTaskId=wt)["Priority"] == 1
    ssm.update_maintenance_window_target(WindowId=wid, WindowTargetId=tid, Name="web")
    assert ssm.describe_maintenance_window_targets(WindowId=wid)["Targets"][0]["Name"] == "web"
    assert ssm.describe_maintenance_window_schedule(WindowId=wid)["ScheduledWindowExecutions"][0]["Name"] == "nightly"
    assert code(ssm.get_maintenance_window_execution, WindowExecutionId="a" * 36) == "DoesNotExistException"
    ssm.deregister_task_from_maintenance_window(WindowId=wid, WindowTaskId=wt)
    assert ssm.describe_maintenance_window_tasks(WindowId=wid)["Tasks"] == []

    r = ssm.create_association_batch(Entries=[{"Name": "AWS-RunShellScript", "InstanceId": IID}, {"Name": "NoSuchDoc", "InstanceId": IID}])
    assert len(r["Successful"]) == 1 and len(r["Failed"]) == 1
    aid = r["Successful"][0]["AssociationId"]
    ssm.update_association(AssociationId=aid, ScheduleExpression="rate(1 hour)")
    assert [v["AssociationVersion"] for v in ssm.list_association_versions(AssociationId=aid)["AssociationVersions"]] == ["1", "2"]
    ssm.start_associations_once(AssociationIds=[aid])
    ex = ssm.describe_association_executions(AssociationId=aid)["AssociationExecutions"]
    assert len(ex) == 1 and ex[0]["Status"] == "Success"
    assert ssm.describe_association_execution_targets(AssociationId=aid, ExecutionId=ex[0]["ExecutionId"])["AssociationExecutionTargets"][0]["ResourceId"] == IID
    assert ssm.describe_effective_instance_associations(InstanceId=IID)["Associations"][0]["AssociationId"] == aid
    ssm.update_association_status(Name="AWS-RunShellScript", InstanceId=IID, AssociationStatus={"Date": 1700000000, "Name": "Failed", "Message": "boom"})
    assert ssm.describe_instance_associations_status(InstanceId=IID)["InstanceAssociationStatusInfos"][0]["Status"] == "Failed"
    assert code(ssm.start_associations_once, AssociationIds=["00000000-0000-0000-0000-000000000000"]) == "AssociationDoesNotExist"


def test_document_permissions_and_automation(ssm):
    ssm.create_document(Name="my-doc", DocumentType="Automation", DocumentFormat="JSON", Content=json.dumps({
        "schemaVersion": "0.3", "parameters": {"Secs": {"type": "String", "default": "PT1S"}, "Cmd": {"type": "String"}},
        "mainSteps": [{"name": "wait", "action": "aws:sleep", "inputs": {"Duration": "{{ Secs }}"}},
                      {"name": "go", "action": "aws:runCommand", "inputs": {"DocumentName": "AWS-RunShellScript", "InstanceIds": [IID], "Parameters": {"commands": ["{{ Cmd }}"]}}}]}))
    ssm.modify_document_permission(Name="my-doc", PermissionType="Share", AccountIdsToAdd=["111122223333"])
    assert ssm.describe_document_permission(Name="my-doc", PermissionType="Share")["AccountIds"] == ["111122223333"]
    assert code(ssm.modify_document_permission, Name="AWS-RunShellScript", PermissionType="Share", AccountIdsToAdd=["111122223333"]) == "InvalidPermissionType"

    assert code(ssm.start_automation_execution, DocumentName="my-doc") == "InvalidAutomationExecutionParametersException"      # Cmd is required
    eid = ssm.start_automation_execution(DocumentName="my-doc", Parameters={"Cmd": ["echo hi"]})["AutomationExecutionId"]
    ex = ssm.get_automation_execution(AutomationExecutionId=eid)["AutomationExecution"]
    assert ex["AutomationExecutionStatus"] == "Success" and [s["StepStatus"] for s in ex["StepExecutions"]] == ["Success", "Success"]
    cmd_id = ex["StepExecutions"][1]["Outputs"]["CommandId"][0]
    assert ssm.list_commands(CommandId=cmd_id)["Commands"][0]["DocumentName"] == "AWS-RunShellScript"      # the step really created a command
    assert [e["AutomationExecutionId"] for e in ssm.describe_automation_executions(Filters=[{"Key": "DocumentNamePrefix", "Values": ["my-"]}])["AutomationExecutionMetadataList"]] == [eid]
    assert len(ssm.describe_automation_step_executions(AutomationExecutionId=eid)["StepExecutions"]) == 2
    assert code(ssm.stop_automation_execution, AutomationExecutionId=eid) == "InvalidAutomationStatusUpdateException"

    ssm.create_document(Name="gated", DocumentType="Automation", DocumentFormat="JSON", Content=json.dumps({
        "schemaVersion": "0.3", "mainSteps": [{"name": "approve", "action": "aws:pause", "inputs": {}}, {"name": "after", "action": "aws:sleep", "inputs": {"Duration": "PT1S"}}]}))
    g = ssm.start_automation_execution(DocumentName="gated")["AutomationExecutionId"]
    assert ssm.get_automation_execution(AutomationExecutionId=g)["AutomationExecution"]["AutomationExecutionStatus"] == "Waiting"
    ssm.send_automation_signal(AutomationExecutionId=g, SignalType="Approve")
    assert ssm.get_automation_execution(AutomationExecutionId=g)["AutomationExecution"]["AutomationExecutionStatus"] == "Success"

    ssm.create_document(Name="unsupported", DocumentType="Automation", DocumentFormat="JSON", Content=json.dumps({
        "schemaVersion": "0.3", "mainSteps": [{"name": "api", "action": "aws:executeAwsApi", "inputs": {"Service": "ec2", "Api": "DescribeInstances"}}]}))
    u = ssm.get_automation_execution(AutomationExecutionId=ssm.start_automation_execution(DocumentName="unsupported")["AutomationExecutionId"])["AutomationExecution"]
    assert u["AutomationExecutionStatus"] == "Failed" and "not executable" in u["FailureMessage"]
    assert code(ssm.start_automation_execution, DocumentName="AWS-RunShellScript") == "InvalidDocumentType"
    assert ssm.get_connection_status(Target=IID)["Status"] == "notconnected"
