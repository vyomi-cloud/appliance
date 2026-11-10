"""boto3 (official SDK, endpoint changed only) against Step Functions activities /
aliases / versions / map runs, SSM parameter labels / commands / managed instances and
EC2 route tables: engine operations that no SDK test called."""
import json
import os
import sys
import uuid

import boto3
from botocore.exceptions import ClientError

EP = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000")
KW = dict(endpoint_url=EP, region_name="us-east-1", aws_access_key_id="test", aws_secret_access_key="test")
failed = False
sfx = uuid.uuid4().hex[:8]


def check(name, fn):
    global failed
    try:
        ok = fn()
    except Exception as e:  # noqa: BLE001
        print(f"  {type(e).__name__}: {str(e)[:300]}")
        ok = False
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    failed = failed or not ok


def raises(fn, code):
    try:
        fn()
    except ClientError as e:
        return e.response["Error"]["Code"] == code
    return False


ASL = json.dumps({"StartAt": "P", "States": {"P": {"Type": "Pass", "End": True}}})


def main():
    sfn, ssm, ec2 = boto3.client("stepfunctions", **KW), boto3.client("ssm", **KW), boto3.client("ec2", **KW)
    role = "arn:aws:iam::000000000000:role/sfn"
    act = sfn.create_activity(name=f"act-{sfx}")["activityArn"]
    check("sfn DescribeActivity returns it", lambda: sfn.describe_activity(activityArn=act)["name"] == f"act-{sfx}")
    sm = sfn.create_state_machine(name=f"m-{sfx}", definition=ASL, roleArn=role, publish=True)
    arn, v1 = sm["stateMachineArn"], sm.get("stateMachineVersionArn")
    v2 = sfn.publish_state_machine_version(stateMachineArn=arn, description="second")["stateMachineVersionArn"]
    al = sfn.create_state_machine_alias(name="live", routingConfiguration=[{"stateMachineVersionArn": v2, "weight": 100}])["stateMachineAliasArn"]
    check("sfn DescribeStateMachineAlias returns it", lambda: sfn.describe_state_machine_alias(stateMachineAliasArn=al)["name"] == "live")
    check("sfn ListStateMachineAliases lists it", lambda: al in [a["stateMachineAliasArn"] for a in
          sfn.list_state_machine_aliases(stateMachineArn=arn)["stateMachineAliases"]])
    sfn.update_state_machine_alias(stateMachineAliasArn=al, description="blue")
    check("sfn UpdateStateMachineAlias persists", lambda: sfn.describe_state_machine_alias(stateMachineAliasArn=al)["description"] == "blue")
    ex = sfn.start_execution(stateMachineArn=arn, input="{}")["executionArn"]
    check("sfn DescribeStateMachineForExecution", lambda: sfn.describe_state_machine_for_execution(executionArn=ex)["stateMachineArn"] == arn)
    check("sfn ListMapRuns on an execution without Map states is empty", lambda: sfn.list_map_runs(executionArn=ex)["mapRuns"] == [])
    check("sfn RedriveExecution of a succeeded execution is refused",
          lambda: raises(lambda: sfn.redrive_execution(executionArn=ex), "ExecutionNotRedrivable"))
    check("sfn SendTaskHeartbeat with an unknown token is refused",
          lambda: raises(lambda: sfn.send_task_heartbeat(taskToken="nope"), "TaskDoesNotExist"))
    check("sfn SendTaskFailure with an unknown token is refused",
          lambda: raises(lambda: sfn.send_task_failure(taskToken="nope"), "TaskDoesNotExist"))
    sfn.delete_state_machine_alias(stateMachineAliasArn=al)
    sfn.delete_state_machine_version(stateMachineVersionArn=v2)
    check("sfn DeleteStateMachineVersion removes it", lambda: v2 not in [v["stateMachineVersionArn"] for v in
          sfn.list_state_machine_versions(stateMachineArn=arn)["stateMachineVersions"]])
    sfn.delete_state_machine(stateMachineArn=arn)
    sfn.delete_activity(activityArn=act)

    p = f"/conf4/{sfx}"
    ssm.put_parameter(Name=p, Value="1", Type="String")
    ssm.put_parameter(Name=p, Value="2", Type="String", Overwrite=True)
    ssm.label_parameter_version(Name=p, ParameterVersion=1, Labels=["blue"])
    ssm.unlabel_parameter_version(Name=p, ParameterVersion=1, Labels=["blue"])
    check("ssm UnlabelParameterVersion removes the label", lambda: not any(
        h.get("Labels") for h in ssm.get_parameter_history(Name=p)["Parameters"] if h["Version"] == 1))
    check("ssm RegisterDefaultHostManagementConfiguration returns a RoleArn", lambda: ssm.register_default_host_management_configuration(
        PermissionModel="ManagedInstance", Overwrite=True)["RoleArn"].startswith("arn:aws:iam::"))
    check("ssm DeregisterDefaultHostManagementConfiguration succeeds", lambda: ssm.deregister_default_host_management_configuration() is not None)
    ssm.delete_parameter(Name=p)
    cid = ssm.send_command(DocumentName="AWS-RunShellScript", InstanceIds=["i-0123456789abcdef0"],
                           Parameters={"commands": ["true"]})["Command"]["CommandId"]
    ssm.cancel_command(CommandId=cid)
    check("ssm CancelCommand on a finished command is a no-op", lambda: ssm.list_commands(CommandId=cid)["Commands"][0]["Status"] == "Success")
    check("ssm CancelCommand with an unknown id is refused", lambda: raises(lambda: ssm.cancel_command(CommandId=str(uuid.uuid4())), "InvalidCommandId"))
    check("ssm DescribeInstanceInformation answers", lambda: "InstanceInformationList" in ssm.describe_instance_information())

    vpc = ec2.create_vpc(CidrBlock="10.77.0.0/16")["Vpc"]["VpcId"]
    rt = ec2.create_route_table(VpcId=vpc)["RouteTable"]["RouteTableId"]
    ec2.delete_route_table(RouteTableId=rt)
    check("ec2 DeleteRouteTable removes it", lambda: raises(lambda: ec2.describe_route_tables(RouteTableIds=[rt]), "InvalidRouteTableID.NotFound"))
    ec2.delete_vpc(VpcId=vpc)
    sys.exit(1 if failed else 0)


main()
