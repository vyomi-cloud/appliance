"""Nano: AWS console resource-detail tabs show THIS resource's real data.

Drives the same dispatch chain the in-browser console uses (wasm/sw.js route →
registry → aws provider handlers → aws_core_adapter → core/aws_console_detail.py
and the service cores) and checks each tab's values are the resource's own and
that tab actions persist. Host CPython, repo layout (mirrors the Pyodide FS).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from wasm.backends.store import Backends  # noqa: E402
from wasm import providers as P            # noqa: E402

failed = False
B = Backends()


def check(name, ok, extra=""):
    global failed
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{'' if ok else '  ' + str(extra)[:400]}")
    failed = failed or not ok


def d(svc, op, params=None):
    return P.dispatch(B, "aws", svc, op, params=params or {})


def ec2():
    print("── EC2 instance")
    r = d("_resource", "Create", {"service": "ec2", "body": {
        "name": "tabs-web", "instance_type": "t3.micro", "image_id": "ami-ubuntu-24.04-x86_64", "key_name": "kp-tabs",
        "storage_gb": 20, "root_volume_type": "gp3", "root_volume_encrypted": True, "user_data": "#!/bin/bash\necho hi",
        "create_security_group": {"requested": True, "ssh_cidr": "0.0.0.0/0", "allow_http": True}}})
    iid = r["instance_id"]
    tab = lambda t: d("ec2", "DescribeInstanceDetail", {"name": iid, "tab": t})
    det = tab("details")
    check("Details: AMI name + login user of the chosen image", det["image_name"].startswith("Ubuntu Server 24.04") and det["default_username"] == "ubuntu", det)
    check("Details: SSH command uses the key pair + public DNS", det["ssh_command"] == f'ssh -i "kp-tabs.pem" ubuntu@{r["public_dns"]}', det)
    vpcs = {v["id"]: v for v in d("vpc", "List")["vpcs"]}
    check("placed in the default VPC (VPC console lists it)", vpcs.get(det["vpc_id"], {}).get("cidr") == "172.31.0.0/16", vpcs)
    subs = {s["id"]: s for s in d("vpc", "ListSubnets")["subnets"]}
    check("subnet is the default VPC's subnet for the AZ", subs.get(det["subnet_id"], {}).get("vpc_id") == det["vpc_id"], subs)
    eni = tab("network-interfaces")["network_interfaces"]
    check("Networking: ENI with the instance's private IP in its subnet", len(eni) == 1 and eni[0]["private_ip_address"] == r["private_ip"]
          and eni[0]["subnet_id"] == det["subnet_id"], eni)
    sec = tab("security")
    check("Security: launch-wizard group with SSH + HTTP", sec["security_groups"][0]["group_name"] == "launch-wizard-1"
          and {x["port_range"] for x in sec["inbound_rules"]} == {"22", "80"}, sec)
    sgs = {g["id"] for g in d("vpc", "ListSecurityGroups")["security_groups"]}
    check("Security: group exists in the VPC model", sec["security_groups"][0]["group_id"] in sgs, sgs)
    st = tab("storage")["block_devices"]
    check("Storage: root volume from the launch (20 GiB gp3, encrypted)", st[0]["size"] == 20 and st[0]["encrypted"] is True and st[0]["volume_type"] == "gp3", st)
    check("User data: launch script", tab("user-data")["user_data"] == "#!/bin/bash\necho hi")
    m = d("ec2", "ModifyInstanceAttribute", {"name": iid, "tab": "user-data", "body": {"user_data": "x"}})
    check("User data: refused while running", m.get("code") == "IncorrectInstanceState", m)
    d("_resource", "Stop", {"service": "ec2", "name": iid})
    check("Details: user-initiated stop reason", tab("details")["state_transition_reason"].startswith("User initiated"))
    m = d("ec2", "ModifyInstanceAttribute", {"name": iid, "tab": "user-data", "body": {"user_data": "echo changed"}})
    check("User data: saved while stopped", m.get("ok") and tab("user-data")["user_data"] == "echo changed", m)
    d("ec2", "ModifyInstanceAttribute", {"name": iid, "tab": "attributes", "body": {"disable_api_termination": True}})
    t = d("_resource", "Terminate", {"service": "ec2", "name": iid})
    check("termination protection enforced", t.get("code") == "OperationNotPermitted", t)
    d("iam", "CreateUser", {"name": "tabs-dev"})
    from wasm.providers import aws_core_adapter as A
    from core import iam_core
    iam_core.dispatch(A.IAM, {"Action": "CreateRole", "RoleName": "tabs-role", "AssumeRolePolicyDocument": "{}"})
    p = d("ec2", "ModifyInstanceAttribute", {"name": iid, "tab": "iam-instance-profile", "body": {"name": "tabs-role"}})
    check("IAM role: associate an existing role", p.get("ok") and p["iam_instance_profile"]["role_name"] == "tabs-role", p)
    check("IAM role: unknown role rejected", d("ec2", "ModifyInstanceAttribute", {"name": iid, "tab": "iam-instance-profile", "body": {"name": "ghost"}}).get("code") == "InvalidParameterValue")
    arn = f"arn:aws:ec2:us-east-1:123456789012:instance/{iid}"
    iam_core.dispatch(A.IAM, {"Action": "PutUserPolicy", "UserName": "tabs-dev", "PolicyName": "ops",
                              "PolicyDocument": '{"Statement":[{"Effect":"Allow","Action":"ec2:*","Resource":"' + arn + '"}]}'})
    acc = d("iam", "ResourceAccess", {"arn": arn, "service": "ec2"})["statements"]
    check("Permissions: the user's inline policy on this instance", any(x["principal"] == "tabs-dev" for x in acc), acc)
    check("Permissions: not for another instance", not d("iam", "ResourceAccess", {"arn": arn + "x", "service": "ec2"})["statements"])
    ev = d("_events", "List", {"resource": iid, "provider": "aws"})["events"]
    check("Activity: this instance's attribute/profile changes recorded", any(e["action"] == "ModifyInstanceAttribute" for e in ev), ev)




def s3():
    print("── S3 bucket")
    import base64
    d("s3", "CreateBucket", {"name": "tabs-bkt"})
    cfg = lambda k: d("s3", "GetBucketConfig", {"bucket": "tabs-bkt", "kind": k})["value"]
    put = lambda k, v: d("s3", "PutBucketConfig", {"bucket": "tabs-bkt", "kind": k, "method": "PUT", "value": v})
    check("new bucket: SSE-S3, Block Public Access on, owner enforced",
          cfg("encryption")["sse_algorithm"] == "AES256" and all(cfg("public_access_block").values()) and cfg("ownership") == "BucketOwnerEnforced")
    check("Lifecycle: rule saved", put("lifecycle", [{"id": "tmp", "prefix": "tmp/", "expiration_days": 7}]).get("ok") and cfg("lifecycle")[0]["expiration_days"] == 7)
    check("Lifecycle: rule without an action rejected", put("lifecycle", [{"id": "x"}]).get("code") == "InvalidRequest")
    check("CORS: rule saved", put("cors", [{"allowed_methods": "GET", "allowed_origins": "*"}]).get("ok") and cfg("cors")[0]["allowed_methods"] == ["GET"])
    pub = {"Statement": [{"Effect": "Allow", "Principal": "*", "Action": "s3:GetObject", "Resource": "arn:aws:s3:::tabs-bkt/*"}]}
    check("Policy: public policy blocked while BlockPublicPolicy is on", put("policy", pub).get("code") == "AccessDenied")
    put("public_access_block", {"block_public_acls": True, "ignore_public_acls": True, "block_public_policy": False, "restrict_public_buckets": False})
    check("Policy: saved after Block Public Access allows it", put("policy", pub).get("ok") and "GetObject" in cfg("policy"))
    row = next(b for b in d("s3", "ListBuckets")["buckets"] if b["name"] == "tabs-bkt")
    check("bucket list Access = Public", row["access"] == "Public", row)
    d("s3", "PutVersioning", {"bucket": "tabs-bkt", "status": "Enabled"})
    check("Versioning: GET reads Enabled", d("s3", "GetVersioning", {"bucket": "tabs-bkt"})["versioning"] == "Enabled")
    for body in (b"one", b"two"):
        d("s3", "PutObject", {"bucket": "tabs-bkt", "key": "k.txt", "body_b64": base64.b64encode(body).decode()})
    v = d("s3", "ListObjectVersions", {"bucket": "tabs-bkt"})["versions"]
    check("Versions: both versions of k.txt", len(v) == 2 and v[0]["is_latest"] and not v[1]["is_latest"], v)
    n = d("s3", "PutBucketNotification", {"bucket": "tabs-bkt", "method": "PUT", "body": {"rules": [
        {"id": "n1", "events": ["s3:ObjectRemoved:*"], "destination_type": "TopicConfiguration", "destination": "arn:aws:sns:us-east-1:123456789012:t"}]}})
    check("Notifications: topic configuration saved", d("s3", "GetBucketNotification", {"bucket": "tabs-bkt"})["topicConfigurations"][0]["id"] == "n1", n)
    d("s3", "PutBucketTagging", {"bucket": "tabs-bkt", "tags": {"env": "dev"}})
    check("Tags: on the bucket", d("s3", "GetBucket", {"bucket": "tabs-bkt"})["tags"] == {"env": "dev"})
    ev = d("_events", "List", {"resource": "tabs-bkt", "provider": "aws"})["events"]
    check("Activity: bucket configuration changes recorded", any(e["action"] == "PutBucketConfig" for e in ev), ev)



def rds():
    print("── RDS DB instance")
    d("rds", "CreateDatabase", {"name": "tabs-db", "engine": "postgres"})
    det = lambda t: d("rds", "DescribeDBInstanceDetail", {"name": "tabs-db", "tab": t})
    mod = lambda body: d("rds", "ModifyDBInstanceConfiguration", {"name": "tabs-db", "body": body})
    c = det("connectivity")
    vpcs = {v["id"] for v in d("vpc", "List")["vpcs"]}
    check("Connectivity: endpoint/port + placed in the default VPC with subnets", c["endpoint"] and c["vpc_id"] in vpcs and len(c["subnets"]) == 6, c)
    check("Security: the VPC's default security group", c["security_groups"][0]["group_name"] == "default", c)
    check("Modify: backup retention persists", mod({"backup_retention_period": 3}).get("ok") and det("configuration")["backup_retention_period"] == 3)
    check("Modify: storage can't shrink", mod({"allocated_storage": 1}).get("code") == "InvalidParameterValue")
    check("Maintenance: window persists", mod({"preferred_maintenance_window": "wed:02:00-wed:02:30"}).get("ok")
          and det("configuration")["preferred_maintenance_window"] == "wed:02:00-wed:02:30")
    check("Performance Insights: on", mod({"performance_insights_enabled": True}).get("ok") and det("performance-insights")["enabled"] is True)
    d("rds", "Stop", {"name": "tabs-db"})
    ev = det("events")["events"]
    check("Logs & events: created / modified / stopped", {e["message"].split(" to ")[0] for e in ev} >= {"DB instance created", "DB instance stopped"}
          and any("modification" in e["message"] for e in ev), ev)
    mod({"deletion_protection": True})
    check("deletion protection blocks delete", d("rds", "DeleteDatabase", {"name": "tabs-db"}).get("code") == "InvalidParameterCombination")



def dynamodb():
    print("── DynamoDB table")
    import json as _json
    from wasm.providers import aws_core_adapter as A
    from core import dynamodb_core as ddbc
    d("dynamodb", "CreateTable", {"table_name": "tabs-t", "partition_key_name": "id"})
    sec = lambda s: d("dynamodb", "DescribeTableSection", {"table": "tabs-t", "section": s})
    put = lambda s, b: d("dynamodb", "UpdateTableSection", {"table": "tabs-t", "section": s, "method": "PUT", "body": b})
    check("Overview: partition key + on-demand", sec("general")["partition_key"] == "id (S)" and sec("general")["capacity_mode"] == "On-demand")
    check("Indexes: GSI created", put("indexes", {"index_name": "by-city", "partition_key": "city"}).get("ok"))
    d("dynamodb", "PutItem", {"table": "tabs-t", "item": {"id": "1", "city": "Pune"}})
    r = ddbc.dispatch(A.DDB, "DynamoDB_20120810.Query", {"TableName": "tabs-t", "IndexName": "by-city",
                      "KeyConditionExpression": "city = :c", "ExpressionAttributeValues": {":c": {"S": "Pune"}}})
    check("Indexes: the console-created GSI answers a native Query(IndexName)", r.status == 200 and r.body["Count"] == 1, r.body)
    check("TTL: on", put("ttl", {"enabled": True, "attribute_name": "exp"}).get("time_to_live_status") == "ENABLED")
    check("Streams: on", put("streams", {"stream_enabled": True, "view_type": "KEYS_ONLY"}).get("stream_enabled") is True)
    check("Capacity: provisioned", put("capacity", {"billing_mode": "PROVISIONED", "read_capacity_units": 2, "write_capacity_units": 2}).get("billing_mode") == "PROVISIONED")
    check("Backups: created", put("backups", {"backup_name": "bk1"}).get("backups")[0]["backup_name"] == "bk1")
    check("Backups: 2-character name rejected like DynamoDB", put("backups", {"backup_name": "b1"}).get("code") == "ValidationException")
    check("PITR: on", put("pitr", {"enabled": True}).get("point_in_time_recovery_status") == "ENABLED")
    put("capacity", {"deletion_protection": True})
    check("deletion protection blocks DeleteTable", d("dynamodb", "DeleteTable", {"table": "tabs-t"}).get("code") == "ValidationException")
    ev = d("_events", "List", {"resource": "tabs-t", "provider": "aws"})["events"]
    check("Activity: table setting changes recorded", any(e["action"] == "UpdateTableSection" for e in ev), ev)



def lambda_():
    print("── Lambda function")
    d("lambda", "CreateFunction", {"name": "tabs-fn"})
    sec = lambda s: d("lambda", "GetFunctionSection", {"name": "tabs-fn", "section": s})
    put = lambda s, b: d("lambda", "UpdateFunctionSection", {"name": "tabs-fn", "section": s, "method": "PUT", "body": b})
    check("Code: the function's source", "def handler" in sec("code")["code"])
    put("code", {"code": "def handler(event, context):\n    return {'tripled': event['n'] * 3}"})
    check("Code: deployed code is what Invoke runs", d("lambda", "Invoke", {"name": "tabs-fn", "payload": {"n": 5}})["result"] == {"tripled": 15})
    check("Env: saved", put("env", {"variables": {"MODE": "x"}}).get("variables") == {"MODE": "x"})
    check("Env: invalid key rejected", put("env", {"variables": {"1BAD": "x"}}).get("code") == "InvalidParameterValueException")
    check("Versions: publish", put("versions", {"description": "v1"}).get("versions")[-1]["version"] == "1")
    check("Aliases: create", put("aliases", {"name": "live", "function_version": "1"}).get("aliases")[0]["alias_arn"].endswith(":tabs-fn:live"))
    check("Aliases: duplicate conflicts", put("aliases", {"name": "live", "function_version": "1"}).get("code") == "ResourceConflictException")
    check("Policy: AddPermission", put("policy", {"statement_id": "apigw", "principal": "apigateway.amazonaws.com"}).get("policy")["Statement"][0]["Principal"]
          == {"Service": "apigateway.amazonaws.com"})
    from wasm.providers import aws_core_adapter as A
    from core import iam_core
    iam_core.dispatch(A.IAM, {"Action": "CreateRole", "RoleName": "fn-exec", "AssumeRolePolicyDocument": "{}"})
    check("Execution role: existing role accepted", put("role", {"role": "arn:aws:iam::123456789012:role/fn-exec"}).get("role_exists") is True)
    check("Execution role: unknown role rejected", put("role", {"role": "arn:aws:iam::123456789012:role/ghost"}).get("code") == "InvalidParameterValueException")
    check("Test events: saved", put("test-events", {"name": "five", "event": {"n": 5}}).get("test_events")[0]["name"] == "five")
    ev = d("_events", "List", {"resource": "tabs-fn", "provider": "aws"})["events"]
    check("Activity: function changes recorded", sum(1 for e in ev if e["action"] == "UpdateFunctionSection") >= 5, ev)

SECTIONS = {"ec2": ec2, "s3": s3, "rds": rds, "dynamodb": dynamodb, "lambda": lambda_}

if __name__ == "__main__":
    for k in sys.argv[1:] or list(SECTIONS):
        try:
            SECTIONS[k]()
        except Exception as e:
            import traceback
            traceback.print_exc()
            check(f"{k}: section ran", False, repr(e))
    sys.exit(1 if failed else 0)
