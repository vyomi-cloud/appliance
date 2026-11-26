"""Seed side of validate-aws-v4-detail.mjs: official boto3 (endpoint only changed) creates one resource per
service on the /_wire endpoint and prints ONE json line {kind: {id, name, ...}}. usage: _aws_v4_seed.py <stamp> [kind,kind,...]"""
import io, json, os, sys, zipfile
import boto3

KW = dict(endpoint_url=os.environ["VYOMI_BASE_URL"].rstrip("/"), region_name="us-east-1", aws_access_key_id="test", aws_secret_access_key="test")
stamp = sys.argv[1]
want = (sys.argv[2] if len(sys.argv) > 2 else "").split(",")
cl = lambda s: boto3.client(s, **KW)
out = {}


def sqs():
    c = cl("sqs"); n = "dtq" + stamp; c.create_queue(QueueName=n); return {"id": n, "name": n}


def sns():
    c = cl("sns"); n = "dtt" + stamp; return {"id": n, "name": n, "arn": c.create_topic(Name=n)["TopicArn"]}


def rds(vp):
    # a realistic DB in a real security group (the engine default "sg-default" is not an EC2 group: see the doc, finding F1)
    c = cl("rds"); n = "dtdb" + stamp
    c.create_db_instance(DBInstanceIdentifier=n, DBInstanceClass="db.t3.micro", Engine="postgres", MasterUsername="u", MasterUserPassword="password123", AllocatedStorage=20, VpcSecurityGroupIds=[vp["sg"]])
    return {"id": n, "name": n}


def vpc():
    c = cl("ec2"); n = "dtv" + stamp
    v = c.create_vpc(CidrBlock="10.91.0.0/16")["Vpc"]["VpcId"]; c.create_tags(Resources=[v], Tags=[{"Key": "Name", "Value": n}])
    sub = c.create_subnet(VpcId=v, CidrBlock="10.91.1.0/24")["Subnet"]["SubnetId"]
    sg = c.create_security_group(GroupName="dtsg" + stamp, Description="dt sg", VpcId=v)["GroupId"]
    igw = c.create_internet_gateway()["InternetGateway"]["InternetGatewayId"]; c.attach_internet_gateway(InternetGatewayId=igw, VpcId=v)
    rt = c.create_route_table(VpcId=v)["RouteTable"]["RouteTableId"]
    return {"id": v, "name": n, "subnet": sub, "sg": sg, "sgname": "dtsg" + stamp, "igw": igw, "rtb": rt}


def ec2(vp):
    c = cl("ec2")
    ami = c.describe_images()["Images"][0]["ImageId"]
    r = c.run_instances(ImageId=ami, MinCount=1, MaxCount=1, InstanceType="t3.micro", SubnetId=vp["subnet"], SecurityGroupIds=[vp["sg"]],
                        TagSpecifications=[{"ResourceType": "instance", "Tags": [{"Key": "Name", "Value": "dti" + stamp}]}])
    i = r["Instances"][0]["InstanceId"]; return {"id": i, "name": "dti" + stamp, "subnet": vp["subnet"], "sg": vp["sg"]}


def lam():
    c = cl("lambda"); n = "dtfn" + stamp; b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z: z.writestr("index.py", "def handler(e, c):\n    return {}\n")
    c.create_function(FunctionName=n, Runtime="python3.12", Role="arn:aws:iam::123456789012:role/r", Handler="index.handler", Code={"ZipFile": b.getvalue()})
    return {"id": n, "name": n}


def apigw():
    c = cl("apigateway"); n = "dtapi" + stamp; r = c.create_rest_api(name=n); return {"id": r["id"], "name": n}


def iam():
    c = cl("iam"); n = "dtu" + stamp; u = c.create_user(UserName=n)["User"]; return {"id": n, "name": n, "arn": u["Arn"]}


def events():
    c = cl("events"); n = "dtbus" + stamp; c.create_event_bus(Name=n); return {"id": n, "name": n}


def ssm():
    c = cl("ssm"); n = "/dtp" + stamp; c.put_parameter(Name=n, Value="v", Type="String"); return {"id": n.lstrip("/"), "name": n}


def secret():
    c = cl("secretsmanager"); n = "dts" + stamp; c.create_secret(Name=n, SecretString="v"); return {"id": n, "name": n}


def kinesis():
    c = cl("kinesis"); n = "dtk" + stamp; c.create_stream(StreamName=n, ShardCount=1); return {"id": n, "name": n}


def states():
    c = cl("stepfunctions"); n = "dtsm" + stamp
    a = c.create_state_machine(name=n, definition=json.dumps({"StartAt": "P", "States": {"P": {"Type": "Pass", "End": True}}}), roleArn="arn:aws:iam::123456789012:role/sf")["stateMachineArn"]
    return {"id": n, "name": n, "arn": a}


def logs():
    c = cl("logs"); n = "dtlg" + stamp; c.create_log_group(logGroupName=n); return {"id": n, "name": n}


def s3():
    c = cl("s3"); n = "dtb" + stamp; c.create_bucket(Bucket=n); return {"id": n, "name": n}


def ddb():
    c = cl("dynamodb"); n = "dtd" + stamp
    c.create_table(TableName=n, KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}], AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}], BillingMode="PAY_PER_REQUEST")
    return {"id": n, "name": n}


def alarm():
    c = cl("cloudwatch"); n = "dtal" + stamp
    c.put_metric_alarm(AlarmName=n, MetricName="CPUUtilization", Namespace="AWS/EC2", Statistic="Average", Period=300, EvaluationPeriods=1, Threshold=80.0, ComparisonOperator="GreaterThanThreshold")
    return {"id": n, "name": n}


def rule():
    c = cl("events"); n = "dtrl" + stamp
    c.put_rule(Name=n, EventPattern=json.dumps({"source": ["dt.test"]}), State="ENABLED"); return {"id": n, "name": n}


def httpapi():
    c = cl("apigatewayv2"); n = "dtha" + stamp; r = c.create_api(Name=n, ProtocolType="HTTP"); return {"id": r["ApiId"], "name": n}


def kms():
    c = cl("kms"); n = "dtkm" + stamp; k = c.create_key(Description=n)["KeyMetadata"]["KeyId"]; c.create_alias(AliasName="alias/" + n, TargetKeyId=k)
    return {"id": k, "name": n}


def elbv2(vp):
    c = cl("elbv2"); n = "dtlb" + stamp
    sub2 = cl("ec2").create_subnet(VpcId=vp["id"], CidrBlock="10.91.2.0/24", AvailabilityZone="us-east-1b")["Subnet"]["SubnetId"]
    a = c.create_load_balancer(Name=n, Subnets=[vp["subnet"], sub2], SecurityGroups=[vp["sg"]])["LoadBalancers"][0]["LoadBalancerArn"]
    return {"id": n, "name": n, "arn": a}


SIMPLE = dict(sqs=sqs, sns=sns, lambda_=lam, apigw=apigw, iam=iam, events=events, ssm=ssm, secret=secret, kinesis=kinesis, states=states, logs=logs, s3=s3, ddb=ddb, kms=kms, alarm=alarm, rule=rule, httpapi=httpapi)
need_vpc = any(k in want for k in ("vpc", "ec2", "elbv2")) or want == [""]
vp = None
for k in ([] if want == [""] else want):
    pass
kinds = list(SIMPLE) + ["vpc", "rds", "ec2", "elbv2"] if want == [""] else want
for k in kinds:
    try:
        if k in SIMPLE: out[k.rstrip("_")] = SIMPLE[k]()
        elif k == "rds": vp = vp or vpc(); out["vpc"] = vp; out["rds"] = rds(vp)
        elif k == "vpc": vp = vp or vpc(); out["vpc"] = vp
        elif k == "ec2": vp = vp or vpc(); out["vpc"] = vp; out["ec2"] = ec2(vp)
        elif k == "elbv2": vp = vp or vpc(); out["vpc"] = vp; out["elbv2"] = elbv2(vp)
    except Exception as e:
        out[k.rstrip("_")] = {"error": str(e)[:200]}
print(json.dumps(out))
