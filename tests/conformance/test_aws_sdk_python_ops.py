"""boto3 (official SDK, endpoint changed only) against ops that had no SDK test:
RDS RebootDBInstance/ModifyDBInstance, Lambda UpdateFunctionCode, EventBridge
RemoveTargets/DeleteRule, IAM ListRoles/ListPolicies/GetPolicy, EC2
AuthorizeSecurityGroupEgress, SQS SetQueueAttributes, DynamoDB TransactWriteItems/
TransactGetItems, S3 CopyObject."""
import io
import json
import os
import sys
import uuid
import zipfile

import boto3

EP = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000")
KW = dict(endpoint_url=EP, region_name="us-east-1", aws_access_key_id="test", aws_secret_access_key="test")
failed = False
sfx = uuid.uuid4().hex[:8]


def check(name, fn):
    global failed
    try:
        ok = fn()
    except Exception as e:  # noqa: BLE001
        print(f"  {type(e).__name__}: {str(e)[:200]}")
        ok = False
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    failed = failed or not ok


def zipped(src):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("index.py", src)
    return b.getvalue()


def main():
    iam, ec2, sqs, ddb, s3, ev, lam, rds = (boto3.client(n, **KW) for n in
                                          ("iam", "ec2", "sqs", "dynamodb", "s3", "events", "lambda", "rds"))

    # IAM
    role = f"conf-role-{sfx}"
    trust = json.dumps({"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"}, "Action": "sts:AssumeRole"}]})
    iam.create_role(RoleName=role, AssumeRolePolicyDocument=trust)
    check("IAM ListRoles includes the new role", lambda: role in [r["RoleName"] for r in iam.list_roles()["Roles"]])
    pol = iam.create_policy(PolicyName=f"conf-pol-{sfx}", PolicyDocument=json.dumps(
        {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "s3:ListBucket", "Resource": "*"}]}))["Policy"]
    check("IAM ListPolicies includes the new policy", lambda: pol["Arn"] in [p["Arn"] for p in iam.list_policies(Scope="Local")["Policies"]])
    check("IAM GetPolicy returns it", lambda: iam.get_policy(PolicyArn=pol["Arn"])["Policy"]["PolicyName"] == f"conf-pol-{sfx}")

    # EC2 security group egress
    vpc = ec2.create_vpc(CidrBlock="10.77.0.0/16")["Vpc"]["VpcId"]
    sg = ec2.create_security_group(GroupName=f"conf-sg-{sfx}", Description="conf", VpcId=vpc)["GroupId"]
    ec2.authorize_security_group_egress(GroupId=sg, IpPermissions=[
        {"IpProtocol": "tcp", "FromPort": 8443, "ToPort": 8443, "IpRanges": [{"CidrIp": "10.0.0.0/8"}]}])
    def egress():
        g = ec2.describe_security_groups(GroupIds=[sg])["SecurityGroups"][0]
        return any(p.get("FromPort") == 8443 for p in g["IpPermissionsEgress"])
    check("EC2 AuthorizeSecurityGroupEgress shows in DescribeSecurityGroups", egress)

    # SQS
    q = sqs.create_queue(QueueName=f"conf-q-{sfx}")["QueueUrl"]
    sqs.set_queue_attributes(QueueUrl=q, Attributes={"VisibilityTimeout": "77"})
    check("SQS SetQueueAttributes persists", lambda: sqs.get_queue_attributes(
        QueueUrl=q, AttributeNames=["VisibilityTimeout"])["Attributes"]["VisibilityTimeout"] == "77")

    # DynamoDB transactions
    t = f"conf-tx-{sfx}"
    ddb.create_table(TableName=t, KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
                     AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}], BillingMode="PAY_PER_REQUEST")
    ddb.transact_write_items(TransactItems=[
        {"Put": {"TableName": t, "Item": {"id": {"S": "a"}, "v": {"N": "1"}}}},
        {"Put": {"TableName": t, "Item": {"id": {"S": "b"}, "v": {"N": "2"}}}}])
    check("DynamoDB TransactGetItems returns both items", lambda: [
        r["Item"]["v"]["N"] for r in ddb.transact_get_items(TransactItems=[
            {"Get": {"TableName": t, "Key": {"id": {"S": "a"}}}},
            {"Get": {"TableName": t, "Key": {"id": {"S": "b"}}}}])["Responses"]] == ["1", "2"])

    # S3 CopyObject
    b = f"conf-s3-{sfx}"
    s3.create_bucket(Bucket=b)
    s3.put_object(Bucket=b, Key="src.txt", Body=b"hello")
    s3.copy_object(Bucket=b, Key="dst.txt", CopySource={"Bucket": b, "Key": "src.txt"})
    check("S3 CopyObject copies the body", lambda: s3.get_object(Bucket=b, Key="dst.txt")["Body"].read() == b"hello")

    # EventBridge
    rule = f"conf-rule-{sfx}"
    ev.put_rule(Name=rule, ScheduleExpression="rate(5 minutes)")
    ev.put_targets(Rule=rule, Targets=[{"Id": "t1", "Arn": f"arn:aws:sqs:us-east-1:000000000000:conf-q-{sfx}"}])
    ev.remove_targets(Rule=rule, Ids=["t1"])
    check("EventBridge RemoveTargets empties ListTargetsByRule", lambda: ev.list_targets_by_rule(Rule=rule)["Targets"] == [])
    ev.delete_rule(Name=rule)
    check("EventBridge DeleteRule removes it", lambda: rule not in [r["Name"] for r in ev.list_rules()["Rules"]])

    # Lambda UpdateFunctionCode
    fn = f"conf-fn-{sfx}"
    lam.create_function(FunctionName=fn, Runtime="python3.12", Role=f"arn:aws:iam::000000000000:role/{role}",
                        Handler="index.handler", Code={"ZipFile": zipped("def handler(e,c): return 1")})
    r = lam.update_function_code(FunctionName=fn, ZipFile=zipped("def handler(e,c): return 2"))
    check("Lambda UpdateFunctionCode returns the function with a new CodeSha256", lambda: r["FunctionName"] == fn and bool(r.get("CodeSha256")))

    # RDS
    db = f"conf-db-{sfx}"
    rds.create_db_instance(DBInstanceIdentifier=db, DBInstanceClass="db.t3.micro", Engine="postgres",
                           MasterUsername="admin", MasterUserPassword="Passw0rd!x", AllocatedStorage=20)
    rds.modify_db_instance(DBInstanceIdentifier=db, AllocatedStorage=40, ApplyImmediately=True)
    check("RDS ModifyDBInstance changes storage", lambda: rds.describe_db_instances(
        DBInstanceIdentifier=db)["DBInstances"][0]["AllocatedStorage"] == 40)
    check("RDS RebootDBInstance succeeds", lambda: rds.reboot_db_instance(DBInstanceIdentifier=db)["DBInstance"]["DBInstanceIdentifier"] == db)

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
