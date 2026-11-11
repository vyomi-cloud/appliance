"""SDK side for validate-aws-roundtrip.mjs: official boto3, endpoint only changed.
usage: _aws_roundtrip_sdk.py <svc> <create|describe|delete> <name> -> one JSON line"""
import json, os, sys
import boto3
from botocore.exceptions import ClientError

KW = dict(endpoint_url=os.environ["VYOMI_BASE_URL"].rstrip("/"), region_name="us-east-1", aws_access_key_id="test", aws_secret_access_key="test")
svc, op, name = sys.argv[1:4]
BOTO = {"cloudwatch": "logs", "states": "stepfunctions", "apigateway": "apigateway", "eventbridge": "events", "ec2": "ec2", "vpc": "ec2", "ssm": "ssm", "backup": "backup", "networkmanager": "networkmanager", "imagebuilder": "imagebuilder", "cloudformation": "cloudformation", "ecr": "ecr", "kinesis": "kinesis", "iam": "iam", "lambda": "lambda", "rds": "rds", "eks": "eks"}
c = boto3.client(BOTO.get(svc, svc), **KW)


def s3():
    if op == "create": c.create_bucket(Bucket=name); return {}
    ex = name in [b["Name"] for b in c.list_buckets()["Buckets"]]
    if op == "describe": return {"exists": ex}
    if ex: c.delete_bucket(Bucket=name)
    return {"deleted": ex}


def sqs():
    if op == "create": return {"url": c.create_queue(QueueName=name)["QueueUrl"]}
    try: url = c.get_queue_url(QueueName=name)["QueueUrl"]
    except ClientError: return {"exists": False, "deleted": False}
    if op == "describe": return {"exists": True, "url": url}
    c.delete_queue(QueueUrl=url); return {"deleted": True}


def sns():
    if op == "create": return {"arn": c.create_topic(Name=name)["TopicArn"]}
    arn = next((t["TopicArn"] for t in c.list_topics()["Topics"] if t["TopicArn"].endswith(":" + name)), None)
    if op == "describe": return {"exists": bool(arn), "arn": arn}
    if arn: c.delete_topic(TopicArn=arn)
    return {"deleted": bool(arn)}


def dynamodb():
    if op == "create":
        c.create_table(TableName=name, KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}], AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}], BillingMode="PAY_PER_REQUEST"); return {}
    ex = name in c.list_tables()["TableNames"]
    if op == "describe": return {"exists": ex}
    if ex: c.delete_table(TableName=name)
    return {"deleted": ex}


def kms():
    al = "alias/" + name
    if op == "create":
        k = c.create_key(Description=name)["KeyMetadata"]["KeyId"]; c.create_alias(AliasName=al, TargetKeyId=k); return {"key": k}
    tgt = next((a.get("TargetKeyId") for a in c.list_aliases()["Aliases"] if a["AliasName"] == al), None)
    # real KMS: deleting a key = ScheduleKeyDeletion; the key stays (PendingDeletion) so "gone" means state PendingDeletion
    live = bool(tgt) and c.describe_key(KeyId=tgt)["KeyMetadata"]["KeyState"] != "PendingDeletion"
    ex = bool(tgt)
    if op == "describe": return {"exists": live}
    if ex:
        k = next(a["TargetKeyId"] for a in c.list_aliases()["Aliases"] if a["AliasName"] == al)
        c.delete_alias(AliasName=al); c.schedule_key_deletion(KeyId=k, PendingWindowInDays=7)
    return {"deleted": ex}


def secretsmanager():
    if op == "create": return {"arn": c.create_secret(Name=name, SecretString="v")["ARN"]}
    ex = name in [s["Name"] for s in c.list_secrets()["SecretList"]]
    if op == "describe": return {"exists": ex}
    if ex: c.delete_secret(SecretId=name, ForceDeleteWithoutRecovery=True)
    return {"deleted": ex}


def _simple(create, exists, delete):
    if op == "create": return create() or {}
    ex = bool(exists())
    if op == "describe": return {"exists": ex}
    if ex: delete()
    return {"deleted": ex}


def iam():
    return _simple(lambda: c.create_user(UserName=name), lambda: name in [u["UserName"] for u in c.list_users()["Users"]], lambda: c.delete_user(UserName=name))


def vpc():
    def ex():
        return any(t["Value"] == name for v in c.describe_vpcs()["Vpcs"] for t in v.get("Tags", []) if t["Key"] == "Name")
    def mk():
        v = c.create_vpc(CidrBlock="10.77.0.0/16")["Vpc"]["VpcId"]; c.create_tags(Resources=[v], Tags=[{"Key": "Name", "Value": name}])
    def rm():
        for v in c.describe_vpcs()["Vpcs"]:
            if any(t["Value"] == name for t in v.get("Tags", [])): c.delete_vpc(VpcId=v["VpcId"])
    return _simple(mk, ex, rm)


def ec2():
    return _simple(lambda: c.create_key_pair(KeyName=name), lambda: name in [k["KeyName"] for k in c.describe_key_pairs()["KeyPairs"]], lambda: c.delete_key_pair(KeyName=name))


def ssm():
    return _simple(lambda: c.put_parameter(Name="/" + name, Value="v", Type="String"), lambda: any(p["Name"] in (name, "/" + name) for p in c.describe_parameters()["Parameters"]), lambda: c.delete_parameter(Name="/" + name))


def kinesis():
    return _simple(lambda: c.create_stream(StreamName=name, ShardCount=1), lambda: name in c.list_streams()["StreamNames"], lambda: c.delete_stream(StreamName=name))


def ecr():
    return _simple(lambda: c.create_repository(repositoryName=name), lambda: name in [r["repositoryName"] for r in c.describe_repositories()["repositories"]], lambda: c.delete_repository(repositoryName=name, force=True))


def eventbridge():
    return _simple(lambda: c.create_event_bus(Name=name), lambda: name in [b["Name"] for b in c.list_event_buses()["EventBuses"]], lambda: c.delete_event_bus(Name=name))


def cloudwatch():
    return _simple(lambda: c.create_log_group(logGroupName=name), lambda: name in [g["logGroupName"] for g in c.describe_log_groups(logGroupNamePrefix=name)["logGroups"]], lambda: c.delete_log_group(logGroupName=name))


def apigateway():
    def ids(): return [a for a in c.get_rest_apis()["items"] if a["name"] == name]
    def rm():
        for a in ids(): c.delete_rest_api(restApiId=a["id"])
    return _simple(lambda: c.create_rest_api(name=name), ids, rm)


def backup():
    return _simple(lambda: c.create_backup_vault(BackupVaultName=name), lambda: name in [v["BackupVaultName"] for v in c.list_backup_vaults()["BackupVaultList"]], lambda: c.delete_backup_vault(BackupVaultName=name))


def networkmanager():
    def ids(): return [g for g in c.describe_global_networks()["GlobalNetworks"] if any(t["Value"] == name for t in g.get("Tags", []))]
    def rm():
        for g in ids(): c.delete_global_network(GlobalNetworkId=g["GlobalNetworkId"])
    return _simple(lambda: c.create_global_network(Description=name, Tags=[{"Key": "Name", "Value": name}]), ids, rm)


def states():
    role = "arn:aws:iam::123456789012:role/sf"
    d = json.dumps({"StartAt": "P", "States": {"P": {"Type": "Pass", "End": True}}})
    def ids(): return [m for m in c.list_state_machines()["stateMachines"] if m["name"] == name]
    def rm():
        for m in ids(): c.delete_state_machine(stateMachineArn=m["stateMachineArn"])
    return _simple(lambda: c.create_state_machine(name=name, definition=d, roleArn=role), ids, rm)


def eks():
    return _simple(lambda: c.create_cluster(name=name, roleArn="arn:aws:iam::123456789012:role/eks", resourcesVpcConfig={"subnetIds": []}), lambda: name in c.list_clusters()["clusters"], lambda: c.delete_cluster(name=name))


def lambda_():
    return None


def lambda_fn():
    import io, zipfile
    def mk():
        b = io.BytesIO()
        with zipfile.ZipFile(b, "w") as z: z.writestr("index.py", "def handler(e, c):\n    return {}\n")
        c.create_function(FunctionName=name, Runtime="python3.12", Role="arn:aws:iam::123456789012:role/r", Handler="index.handler", Code={"ZipFile": b.getvalue()})
    return _simple(mk, lambda: name in [f["FunctionName"] for f in c.list_functions()["Functions"]], lambda: c.delete_function(FunctionName=name))


def rds():
    return _simple(lambda: c.create_db_instance(DBInstanceIdentifier=name, DBInstanceClass="db.t3.micro", Engine="postgres", MasterUsername="u", MasterUserPassword="password123", AllocatedStorage=20),
                   lambda: name in [d["DBInstanceIdentifier"] for d in c.describe_db_instances()["DBInstances"] if d.get("DBInstanceStatus") != "deleting"],  # real RDS keeps a deleting instance listed briefly
                   lambda: c.delete_db_instance(DBInstanceIdentifier=name, SkipFinalSnapshot=True))


def cloudformation():
    t = json.dumps({"Resources": {"Q": {"Type": "AWS::SQS::Queue", "Properties": {"QueueName": name + "-q"}}}})
    return _simple(lambda: c.create_stack(StackName=name, TemplateBody=t), lambda: name in [s["StackName"] for s in c.describe_stacks()["Stacks"] if s["StackStatus"] != "DELETE_COMPLETE"], lambda: c.delete_stack(StackName=name))


def _ib_prereq():
    """recipe + infra config the pipeline needs (the console create form asks to choose existing ones)"""
    infra = next((i["arn"] for i in c.list_infrastructure_configurations()["infrastructureConfigurationSummaryList"] if i["name"] == "rt-infra"), None)
    if not infra:
        infra = c.create_infrastructure_configuration(name="rt-infra", instanceProfileName="rt-profile")["infrastructureConfigurationArn"]
    rec = next((r["arn"] for r in c.list_image_recipes()["imageRecipeSummaryList"] if r["name"] == "rt-recipe"), None)
    if not rec:
        comp = c.create_component(name="rt-comp", semanticVersion="1.0.0", platform="Linux", data="name: rt\nschemaVersion: 1.0\nphases:\n  - name: build\n    steps:\n      - name: s\n        action: ExecuteBash\n        inputs:\n          commands: [echo hi]\n")["componentBuildVersionArn"]
        rec = c.create_image_recipe(name="rt-recipe", semanticVersion="1.0.0", parentImage="ubuntu", components=[{"componentArn": comp}])["imageRecipeArn"]
    return rec, infra


def imagebuilder():
    def pipes(): return [p for p in c.list_image_pipelines()["imagePipelineList"] if p["name"] == name]
    def mk():
        rec, infra = _ib_prereq()
        c.create_image_pipeline(name=name, imageRecipeArn=rec, infrastructureConfigurationArn=infra)
    def rm():
        for p in pipes(): c.delete_image_pipeline(imagePipelineArn=p["arn"])
    return _simple(mk, pipes, rm)


if op == "prep":  # make a UI-created resource deletable (e.g. RDS console default = deletion protection ON, as in real AWS)
    if svc == "cloudformation":   # the UI wizard takes a template URL: host one in S3 first
        s3c = boto3.client("s3", **KW)
        try: s3c.create_bucket(Bucket="rt-cfn-templates")
        except ClientError: pass
        s3c.put_object(Bucket="rt-cfn-templates", Key="t.json", Body=json.dumps({"Resources": {"Q": {"Type": "AWS::SQS::Queue", "Properties": {"QueueName": name + "-q"}}}}))
    if svc == "imagebuilder": _ib_prereq()
    if svc == "rds": c.modify_db_instance(DBInstanceIdentifier=name, DeletionProtection=False, ApplyImmediately=True)
    print("{}"); sys.exit(0)
print(json.dumps((lambda_fn if svc == "lambda" else globals()[svc])(), default=str))
