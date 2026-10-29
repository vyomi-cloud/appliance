"""AWS console resource-detail tabs show THIS resource's real data (offline appliance).

Each section creates a resource through the console's own API, then reads every
detail-tab route the console calls and checks the values are the resource's own
(placement, interfaces, volumes, settings…) — and that tab actions persist.
Engine: core/aws_console_detail.py; routes: routes/aws_console_detail.py.

    VYOMI_BASE_URL=http://localhost:9000 python3 tests/conformance/test_aws_detail_tabs_api.py
"""
import ipaddress
import json
import os
import sys
import time

import requests

BASE = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000").rstrip("/")
failed = False


def check(name, ok, extra=""):
    global failed
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{'' if ok else '  ' + str(extra)[:400]}")
    failed = failed or not ok


def get(path, **kw):
    return requests.get(BASE + path, timeout=60, **kw)


def ec2():
    print("── EC2 instance")
    sfx = str(int(time.time()))[-6:]
    r = requests.post(f"{BASE}/api/ec2/instances?auto_start=false", timeout=120, json={
        "name": f"tabs-{sfx}", "instance_type": "t3.micro", "key_name": f"kp-{sfx}", "storage_gb": 12,
        "root_volume_type": "gp2", "user_data": "#!/bin/bash\necho tabs", "monitoring": True,
        "create_security_group": {"requested": True, "ssh_cidr": "10.1.0.0/16", "allow_https": True}})
    check("launch", r.status_code < 300, r.text)
    inst = r.json()
    iid = inst["instance_id"]
    p = f"/api/ec2/instances/{iid}"

    d = get(p + "/details").json()
    check("Details: instance id + type", d["instance_id"] == iid and d["instance_type"] == "t3.micro", d)
    check("Details: key pair it was launched with", d["key_name"] == f"kp-{sfx}", d)
    check("Details: placed in the default VPC/subnet", d["vpc_id"].startswith("vpc-") and d["subnet_id"].startswith("subnet-"), d)
    check("Details: monitoring enabled at launch", d["monitoring"] == "enabled", d)
    vpcs = {v["vpc_id"]: v for v in get("/api/vpc/vpcs").json()["vpcs"]}
    check("default VPC exists in the VPC console (172.31.0.0/16)", vpcs.get(d["vpc_id"], {}).get("cidr_block") == "172.31.0.0/16", vpcs)

    n = get(p + "/network-interfaces").json()["network_interfaces"]
    check("Networking: one primary ENI", len(n) == 1 and n[0]["network_interface_id"].startswith("eni-"), n)
    subnets = {s["subnet_id"]: s for s in get("/api/vpc/subnets").json()["subnets"]}
    check("Networking: ENI subnet is a real subnet of the VPC", subnets.get(n[0]["subnet_id"], {}).get("vpc_id") == d["vpc_id"], n)
    check("Networking: ENI carries the instance's private IP", n[0]["private_ip_address"] == inst["private_ip"], n)

    s = get(p + "/security").json()
    names = [g["group_name"] for g in s["security_groups"]]
    check("Security: launch-wizard group created", len(names) == 1 and names[0].startswith("launch-wizard-"), s)
    ports = {(r["port_range"], r["source"]) for r in s["inbound_rules"]}
    check("Security: SSH from the chosen CIDR + HTTPS", ("22", "10.1.0.0/16") in ports and ("443", "0.0.0.0/0") in ports, ports)
    sgs = {g["security_group_id"]: g for g in get("/api/vpc/security-groups").json()["security_groups"]}
    check("Security: group listed in the VPC console", s["security_groups"][0]["group_id"] in sgs, s)

    st = get(p + "/storage").json()
    root = st["block_devices"][0]
    check("Storage: root volume size/type from the launch", root["size"] == 12 and root["volume_type"] == "gp2" and root["root"], st)

    u = get(p + "/user-data").json()
    check("User data: the launch script", u["user_data"] == "#!/bin/bash\necho tabs", u)

    # Settings persist (ModifyInstanceAttribute) and termination protection is enforced.
    r = requests.put(BASE + p + "/attributes", json={"disable_api_termination": True}, timeout=30)
    check("Details: enable termination protection", r.status_code == 200 and r.json()["termination_protection"], r.text)
    check("Details: setting survives a re-read", get(p + "/details").json()["termination_protection"] is True)
    r = requests.post(BASE + p + "/terminate", timeout=60)
    check("terminate refused while protected", r.status_code == 400 and "disableApiTermination" in r.text, r.text)
    requests.put(BASE + p + "/attributes", json={"disable_api_termination": False}, timeout=30)

    # IAM role: associate a real role, then remove it.
    role = f"tabs-role-{sfx}"
    requests.post(BASE + "/api/iam/roles", json={"role_name": role}, timeout=30)
    r = requests.put(BASE + p + "/iam-instance-profile", json={"name": role}, timeout=30)
    check("IAM role: associate", r.status_code == 200 and r.json()["iam_instance_profile"]["role_name"] == role, r.text)
    check("Security tab shows the role", (get(p + "/security").json()["iam_instance_profile"] or {}).get("role_name") == role)
    r = requests.put(BASE + p + "/iam-instance-profile", json={"name": "no-such-role"}, timeout=30)
    check("IAM role: unknown role rejected", r.status_code == 400, r.text)
    r = requests.delete(BASE + p + "/iam-instance-profile", timeout=30)
    check("IAM role: remove", r.status_code == 200 and get(p + "/iam-instance-profile").json()["iam_instance_profile"] is None, r.text)

    # User data can only change while stopped.
    state = get(p).json().get("state")
    r = requests.put(BASE + p + "/user-data", json={"user_data": "echo changed"}, timeout=30)
    if state == "stopped":
        check("User data: edit while stopped persists", r.status_code == 200 and get(p + "/user-data").json()["user_data"] == "echo changed", r.text)
    else:
        check("User data: edit refused unless stopped", r.status_code == 400 and "stopped" in r.text, r.text)

    # Serial console access is an account setting.
    cur = get("/api/ec2/serial-console-access").json()["serial_console_access_enabled"]
    requests.put(BASE + "/api/ec2/serial-console-access", json={"enabled": not cur}, timeout=30)
    check("Serial console: account access toggles", get("/api/ec2/serial-console-access").json()["serial_console_access_enabled"] is (not cur))
    requests.put(BASE + "/api/ec2/serial-console-access", json={"enabled": cur}, timeout=30)
    co = get(p + "/console-output").json()
    check("Serial console: console output for this instance", co["instance_id"] == iid and "output" in co, co)

    # Permissions: an identity policy naming this instance shows up; one for another service does not.
    arn = f"arn:aws:ec2:us-east-1:123456789012:instance/{iid}"
    pol = requests.post(BASE + "/api/iam/policies", json={"policy_name": f"tabs-ec2-{sfx}", "document": {
        "Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": ["ec2:StopInstances"], "Resource": arn}]}}, timeout=30).json()
    user = requests.post(BASE + "/api/iam/users", json={"user_name": f"tabs-user-{sfx}"}, timeout=30).json()
    requests.post(BASE + "/api/iam/attach-policy", json={"target_type": "user", "target_id": user["user_id"], "policy_id": pol["policy_id"]}, timeout=30)
    acc = get("/api/aws/resource-access", params={"arn": arn, "service": "ec2"}).json()["statements"]
    check("Permissions: the user's policy for this instance applies", any(x["principal"] == f"tabs-user-{sfx}" and x["actions"] == "ec2:StopInstances" for x in acc), acc)
    other = get("/api/aws/resource-access", params={"arn": arn.replace(iid, "i-other"), "service": "ec2"}).json()["statements"]
    check("Permissions: not listed for a different instance", not any(x["principal"] == f"tabs-user-{sfx}" for x in other), other)

    ev = get("/api/cloudsim/events").json().get("events", [])
    check("Activity: attribute change recorded for this instance",
          any(((e.get("detail") or {}).get("detail") or e.get("detail") or {}).get("resource_id") == iid and "modify_instance_attribute" in e.get("event", "") for e in ev))
    requests.post(BASE + p + "/terminate", timeout=60)




def s3():
    print("── S3 bucket")
    name = f"tabs-s3-{int(time.time())}"
    r = requests.post(f"{BASE}/api/s3/buckets/{name}", timeout=30)
    check("create bucket", r.status_code < 300, r.text)
    p = f"/api/s3/buckets/{name}"
    cfg = lambda k: get(p + "/config/" + k).json()["value"]
    put = lambda k, v: requests.put(BASE + p + "/config/" + k, json={"value": v}, timeout=30)
    check("Default encryption: new bucket has SSE-S3", cfg("encryption")["sse_algorithm"] == "AES256")
    check("Block Public Access: all four on for a new bucket", all(cfg("public_access_block").values()))
    check("Object Ownership: bucket owner enforced", cfg("ownership") == "BucketOwnerEnforced")
    check("no lifecycle / CORS / policy yet", cfg("lifecycle") == [] and cfg("cors") == [] and cfg("policy") == "")

    r = put("lifecycle", [{"id": "expire-logs", "prefix": "logs/", "expiration_days": 30,
                           "transitions": [{"days": 30, "storage_class": "STANDARD_IA"}]}])
    check("Lifecycle: create rule", r.status_code == 200, r.text)
    check("Lifecycle: rule persists", cfg("lifecycle")[0]["id"] == "expire-logs")
    xml = requests.get(f"{BASE}/{name}?lifecycle", timeout=30).text
    check("Lifecycle: native GetBucketLifecycleConfiguration returns the same rule", "<ID>expire-logs</ID>" in xml, xml[:300])
    r = put("lifecycle", [{"id": "bad", "transitions": [{"days": 5, "storage_class": "STANDARD_IA"}]}])
    check("Lifecycle: STANDARD_IA under 30 days rejected like S3", r.status_code == 400 and "30" in r.text, r.text)

    r = put("cors", [{"id": "web", "allowed_methods": ["GET", "PUT"], "allowed_origins": ["https://example.com"], "max_age_seconds": 600}])
    check("CORS: add rule", r.status_code == 200 and cfg("cors")[0]["max_age_seconds"] == 600, r.text)
    check("CORS: native GetBucketCors returns it", "https://example.com" in requests.get(f"{BASE}/{name}?cors", timeout=30).text)
    check("CORS: unsupported method rejected", put("cors", [{"allowed_methods": ["PATCH"], "allowed_origins": ["*"]}]).status_code == 400)

    r = put("encryption", {"sse_algorithm": "aws:kms", "kms_master_key_id": "alias/aws/s3", "bucket_key_enabled": True})
    check("Default encryption: switch to SSE-KMS with a bucket key", r.status_code == 200 and cfg("encryption")["bucket_key_enabled"] is True, r.text)

    public = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": "*", "Action": "s3:GetObject",
                                                       "Resource": f"arn:aws:s3:::{name}/*"}]}
    r = put("policy", public)
    check("Bucket policy: public policy blocked by BlockPublicPolicy", r.status_code == 403 and "BlockPublicPolicy" in r.text, r.text)
    r = put("policy", {"Statement": [{"Effect": "Allow", "Principal": "*", "Action": "s3:GetObject", "Resource": "arn:aws:s3:::other/*"}]})
    check("Bucket policy: resource outside the bucket rejected", r.status_code == 400 and "invalid resource" in r.text, r.text)
    put("public_access_block", {"block_public_acls": True, "ignore_public_acls": True, "block_public_policy": False, "restrict_public_buckets": False})
    r = put("policy", public)
    check("Bucket policy: saved once Block Public Access allows it", r.status_code == 200 and "s3:GetObject" in cfg("policy"), r.text)
    b = next(x for x in get("/api/s3/buckets").json()["buckets"] if x["name"] == name)
    check("bucket list shows it as Public", b.get("access") == "Public", b)
    requests.delete(BASE + p + "/config/policy", timeout=30)
    check("Bucket policy: delete", cfg("policy") == "")

    requests.put(BASE + p + "/versioning", json={"status": "Enabled"}, timeout=30)
    check("Bucket Versioning: enabled", get(p + "/versioning").json()["versioning"] == "Enabled")
    for body in (b"v1", b"v2"):
        requests.post(BASE + p + "/objects", files={"file": ("a.txt", body, "text/plain")}, timeout=30)
    v = get(p + "/versions").json()["versions"]
    check("Versions: two versions of a.txt, newest latest", len([x for x in v if x["key"] == "a.txt"]) == 2 and v[0]["is_latest"], v)

    r = requests.put(BASE + p + "/notifications", timeout=30, json={"event_bridge_enabled": True, "rules": [
        {"id": "on-put", "events": ["s3:ObjectCreated:*"], "prefix": "in/", "suffix": "", "destination_type": "QueueConfiguration",
         "destination": "arn:aws:sqs:us-east-1:123456789012:tabs-q"}]})
    n = get(p + "/notifications").json()
    check("Event notifications: queue configuration + EventBridge saved", r.status_code == 200 and n["eventBridgeEnabled"]
          and n["queueConfigurations"][0]["id"] == "on-put", n)

    r = requests.patch(BASE + p, json={"tags": {"team": "data"}}, timeout=30)
    check("Tags: saved and returned with the bucket", r.status_code == 200 and get(p).json()["tags"] == {"team": "data"}, r.text)
    acc = get("/api/aws/resource-access", params={"arn": f"arn:aws:s3:::{name}", "service": "s3"}).json()
    check("Permissions: evaluated for the bucket ARN", acc["resource_arn"] == f"arn:aws:s3:::{name}")
    requests.delete(f"{BASE}{p}?force=1", timeout=30)



def rds():
    print("── RDS DB instance")
    did = f"tabs-db-{int(time.time()) % 100000}"
    r = requests.post(f"{BASE}/api/rds/databases", timeout=180, json={
        "db_instance_identifier": did, "engine": "postgres", "master_username": "postgres", "master_user_password": "Password123!"})
    check("create DB instance", r.status_code < 300, r.text)
    p = f"/api/rds/databases/{did}"
    c = get(p + "/connectivity").json()
    vpcs = {v["vpc_id"] for v in get("/api/vpc/vpcs").json()["vpcs"]}
    check("Connectivity: endpoint + port of this instance", c["endpoint"] and c["port"], c)
    check("Connectivity: in a real VPC with its subnets", c["vpc_id"] in vpcs and c["subnets"], c)
    check("Networking: subnet group view matches", get(p + "/subnet-group").json()["vpc_id"] == c["vpc_id"])
    check("Security: VPC security group from that VPC", c["security_groups"] and c["security_groups"][0]["group_id"].startswith("sg-"), c)
    cfg = get(p + "/configuration").json()
    check("Configuration: backup retention / windows reported", cfg["backup_retention_period"] >= 0 and "-" in cfg["preferred_backup_window"], cfg)
    put = lambda body: requests.put(BASE + p + "/configuration", json=body, timeout=30)
    r = put({"backup_retention_period": 14, "preferred_backup_window": "04:00-04:45", "copy_tags_to_snapshot": False})
    check("Automated backups: modify persists", r.status_code == 200 and get(p + "/configuration").json()["backup_retention_period"] == 14, r.text)
    check("Automated backups: retention > 35 rejected", put({"backup_retention_period": 36}).status_code == 400)
    check("Maintenance: window format enforced", put({"preferred_maintenance_window": "funday:01:00"}).status_code == 400)
    r = put({"preferred_maintenance_window": "tue:06:00-tue:06:30", "auto_minor_version_upgrade": False})
    check("Maintenance: modify persists", r.status_code == 200 and get(p + "/configuration").json()["preferred_maintenance_window"] == "tue:06:00-tue:06:30", r.text)
    check("Maintenance: no pending actions", get(p + "/pending-maintenance").json()["pending_maintenance_actions"] == [])
    check("Modify: storage can't shrink", put({"allocated_storage": 5}).status_code == 400)
    r = put({"performance_insights_enabled": True, "performance_insights_retention_period": 31})
    check("Performance Insights: turned on", r.status_code == 200 and get(p + "/performance-insights").json()["enabled"] is True, r.text)
    check("Performance Insights: invalid retention rejected", put({"performance_insights_retention_period": 10}).status_code == 400)
    r = put({"enabled_cloudwatch_logs_exports": ["postgresql"]})
    check("Logs: export postgresql log", r.status_code == 200 and get(p + "/configuration").json()["enabled_cloudwatch_logs_exports"] == ["postgresql"], r.text)
    check("Logs: MySQL log type refused for postgres", put({"enabled_cloudwatch_logs_exports": ["slowquery"]}).status_code == 400)
    ev = get(p + "/events").json()["events"]
    check("Logs & events: creation + modification events for this instance",
          any("created" in e["message"] for e in ev) and any("modification" in e["message"] for e in ev), ev)
    put({"deletion_protection": True})
    r = requests.delete(BASE + p, timeout=60)
    check("Deletion protection blocks DeleteDBInstance", r.status_code == 400 and "deletion protection" in r.text, r.text)
    put({"deletion_protection": False})
    r = requests.delete(BASE + p, timeout=120)
    check("delete once protection is off", r.status_code < 300, r.text)



def dynamodb():
    print("── DynamoDB table")
    name = f"tabs-ddb-{int(time.time()) % 100000}"
    r = requests.post(f"{BASE}/api/dynamodb/tables", timeout=60, json={"table_name": name, "partition_key_name": "pk", "sort_key_name": "sk"})
    check("create table", r.status_code < 300, r.text)
    p = f"/api/dynamodb/tables/{name}/detail/"
    sec = lambda s: get(p + s).json()
    put = lambda s, b: requests.put(BASE + p + s, json=b, timeout=30)
    g = sec("general")
    check("Overview: this table's keys, capacity mode and ARN", g["partition_key"] == "pk (S)" and g["sort_key"] == "sk (S)"
          and g["table_arn"].endswith(":table/" + name), g)
    r = put("indexes", {"index_name": "by-email", "partition_key": "email"})
    check("Indexes: create GSI", r.status_code == 200 and sec("indexes")["global_secondary_indexes"][0]["index_name"] == "by-email", r.text)
    check("Indexes: duplicate index rejected", put("indexes", {"index_name": "by-email", "partition_key": "x"}).status_code == 400)
    put("indexes", {"action": "delete", "index_name": "by-email"})
    check("Indexes: delete GSI", sec("indexes")["global_secondary_indexes"] == [])
    r = put("streams", {"stream_enabled": True, "view_type": "NEW_IMAGE"})
    check("Streams: turn on with a view type", r.status_code == 200 and sec("streams")["latest_stream_arn"].startswith(g["table_arn"] + "/stream/"), r.text)
    check("Streams: enabling twice rejected", put("streams", {"stream_enabled": True}).status_code == 400)
    r = put("capacity", {"billing_mode": "PROVISIONED", "read_capacity_units": 7, "write_capacity_units": 3})
    c = sec("capacity")
    check("Capacity: provisioned 7/3 persists", r.status_code == 200 and c["read_capacity_units"] == 7 and c["write_capacity_units"] == 3, c)
    check("Capacity: zero RCU rejected", put("capacity", {"billing_mode": "PROVISIONED", "read_capacity_units": 0, "write_capacity_units": 1}).status_code == 400)
    check("Encryption: default AWS owned", sec("encryption")["sse_type"] == "AWS_OWNED")
    check("Encryption: customer managed needs a key", put("encryption", {"sse_type": "CUSTOMER_MANAGED"}).status_code == 400)
    put("encryption", {"sse_type": "AWS_MANAGED"})
    check("Encryption: AWS managed key ARN", "alias/aws/dynamodb" in sec("encryption")["kms_key_arn"])
    r = put("ttl", {"enabled": True, "attribute_name": "expiresAt"})
    check("TTL: on with attribute", r.status_code == 200 and sec("ttl") == {"table_name": name, "section": "ttl",
          "time_to_live_status": "ENABLED", "attribute_name": "expiresAt"}, r.text)
    check("TTL: already enabled rejected", put("ttl", {"enabled": True, "attribute_name": "x"}).status_code == 400)
    put("pitr", {"enabled": True})
    check("PITR: on with restore window", sec("pitr")["point_in_time_recovery_status"] == "ENABLED" and sec("pitr")["recovery_period_in_days"] == 35)
    r = put("backups", {"backup_name": "nightly"})
    b = sec("backups")["backups"]
    check("Backups: on-demand backup created", r.status_code == 200 and b[0]["backup_name"] == "nightly" and ":table/" + name + "/backup/" in b[0]["backup_arn"], b)
    put("backups", {"action": "delete", "backup_arn": b[0]["backup_arn"]})
    check("Backups: deleted", sec("backups")["backups"] == [])
    put("insights", {"enabled": True})
    check("Contributor Insights: enabled with rules", sec("insights")["contributor_insights_status"] == "ENABLED")
    put("capacity", {"deletion_protection": True})
    r = requests.delete(f"{BASE}/api/dynamodb/tables/{name}", timeout=30)
    check("Deletion protection blocks DeleteTable", r.status_code == 400 and "protected" in r.text, r.text)
    put("capacity", {"deletion_protection": False})
    check("delete once unprotected", requests.delete(f"{BASE}/api/dynamodb/tables/{name}", timeout=30).status_code < 300)



def lambda_():
    print("── Lambda function")
    name = f"tabs-fn-{int(time.time()) % 100000}"
    r = requests.post(f"{BASE}/api/lambda/functions", timeout=60, json={"function_name": name})
    check("create function", r.status_code < 300, r.text)
    p = f"/api/lambda/functions/{name}/detail/"
    sec = lambda s: get(p + s).json()
    put = lambda s, b: requests.put(BASE + p + s, json=b, timeout=60)
    c = sec("code")
    check("Code: the function's own source + hash", "def " in c["code"] and c["code_sha256"] and c["handler"], c)
    new = "def lambda_handler(event, context):\n    return {'tabs': event.get('n', 0) * 2}\n"
    r = put("code", {"code": new})
    check("Code: deploy persists", r.status_code == 200 and sec("code")["code"].strip() == new.strip(), r.text)
    inv = requests.post(f"{BASE}/api/lambda/functions/{name}/invoke", json={"payload": {"n": 21}}, timeout=60).json()
    check("Test: invoking runs the deployed code", "42" in json.dumps(inv), inv)
    r = put("env", {"variables": {"STAGE": "dev", "LOG_LEVEL": "debug"}})
    check("Environment variables: saved", r.status_code == 200 and sec("env")["variables"] == {"STAGE": "dev", "LOG_LEVEL": "debug"}, r.text)
    check("Environment variables: reserved key rejected", put("env", {"variables": {"AWS_REGION": "x"}}).status_code == 400)
    check("Environment variables: also visible on the function", get(f"/api/lambda/functions/{name}").json()["environment"]["STAGE"] == "dev")
    r = put("configuration", {"memory_size": 256, "timeout": 30, "description": "tabs"})
    check("Configuration: memory/timeout saved", r.status_code == 200 and sec("configuration")["memory_size"] == 256, r.text)
    check("Configuration: timeout > 900 rejected", put("configuration", {"timeout": 901}).status_code == 400)
    put("versions", {"description": "first"})
    v = sec("versions")["versions"]
    check("Versions: published version 1 with its ARN", any(x["version"] == "1" and x["function_arn"].endswith(":" + name + ":1") for x in v), v)
    r = put("aliases", {"name": "prod", "function_version": "1"})
    check("Aliases: prod -> 1", r.status_code == 200 and sec("aliases")["aliases"][0]["function_version"] == "1", r.text)
    check("Aliases: unknown version rejected", put("aliases", {"name": "beta", "function_version": "9"}).status_code == 404)
    r = put("policy", {"statement_id": "s3-invoke", "principal": "s3.amazonaws.com", "source_arn": "arn:aws:s3:::tabs"})
    pol = sec("policy")
    check("Resource-based policy: statement added", r.status_code == 200 and pol["policy"]["Statement"][0]["Sid"] == "s3-invoke", pol)
    check("Resource-based policy: also on GetPolicy", "s3-invoke" in get(f"/api/lambda/functions/{name}/policy").json()["Policy"])
    check("Resource-based policy: duplicate Sid conflicts", put("policy", {"statement_id": "s3-invoke", "principal": "x"}).status_code == 409)
    put("policy", {"action": "remove", "statement_id": "s3-invoke"})
    check("Resource-based policy: removed", sec("policy")["statements"] == [])
    role = f"tabs-lambda-role-{int(time.time()) % 100000}"
    requests.post(BASE + "/api/iam/roles", json={"role_name": role}, timeout=30)
    r = put("role", {"role": f"arn:aws:iam::123456789012:role/{role}"})
    check("Execution role: switched to an existing role", r.status_code == 200 and sec("role")["role_exists"] is True, r.text)
    check("Execution role: unknown role rejected", put("role", {"role": "arn:aws:iam::123456789012:role/nope-x"}).status_code == 400)
    r = put("test-events", {"name": "double", "event": '{"n": 4}'})
    check("Test: saved test event", r.status_code == 200 and sec("test-events")["test_events"][0]["event"] == {"n": 4}, r.text)
    requests.delete(f"{BASE}/api/lambda/functions/{name}", timeout=30)



def iam():
    print("── IAM account settings")
    sfx = str(int(time.time()) % 100000)
    put = lambda s, b: requests.put(f"{BASE}/api/iam/detail/{s}", json=b, timeout=30)
    url = f"https://oidc-{sfx}.example.com"
    r = put("identity-providers", {"provider_type": "OIDC", "url": url, "audiences": ["sts.amazonaws.com"]})
    idps = get("/api/iam/detail/identity-providers").json()["identity_providers"]
    mine = [p for p in idps if p["url"] == url]
    check("Identity providers: OIDC provider with its ARN", r.status_code == 200 and mine and mine[0]["arn"].endswith(f":oidc-provider/oidc-{sfx}.example.com"), idps)
    check("Identity providers: http:// URL rejected", put("identity-providers", {"provider_type": "OIDC", "url": "http://x", "audiences": ["a"]}).status_code == 400)
    check("Identity providers: SAML without metadata rejected", put("identity-providers", {"provider_type": "SAML", "provider_name": "corp"}).status_code == 400)
    check("Identity providers: same URL twice conflicts", put("identity-providers", {"provider_type": "OIDC", "url": url, "audiences": ["a"]}).status_code == 409)
    put("identity-providers", {"action": "delete", "provider_id": mine[0]["provider_id"]})
    check("Identity providers: deleted", not [p for p in get("/api/iam/detail/identity-providers").json()["identity_providers"] if p["url"] == url])
    check("Password policy: length below 6 rejected", put("password-policy", {"minimum_length": 5}).status_code == 400)
    r = put("password-policy", {"minimum_length": 14, "require_symbols": True, "max_password_age": 90})
    pp = get("/api/iam/detail/password-policy").json()
    check("Password policy: saved", r.status_code == 200 and pp["minimum_length"] == 14 and pp["require_symbols"] and pp["max_password_age"] == 90, pp)
    aa = get("/api/iam/detail/access-analyzer").json()
    if not aa["analyzers"]:
        r = put("access-analyzer", {"name": f"tabs-analyzer-{sfx}"})
        check("Access Analyzer: analyzer created", r.status_code == 200, r.text)
    bucket = f"tabs-public-{sfx}"
    requests.post(f"{BASE}/api/s3/buckets/{bucket}", timeout=30)
    requests.put(f"{BASE}/api/s3/buckets/{bucket}/config/public_access_block", json={"value": {}}, timeout=30)
    requests.put(f"{BASE}/api/s3/buckets/{bucket}/config/policy", timeout=30, json={"value": {"Statement": [
        {"Effect": "Allow", "Principal": "*", "Action": "s3:GetObject", "Resource": f"arn:aws:s3:::{bucket}/*"}]}})
    f = get("/api/iam/detail/access-analyzer").json()["findings"]
    check("Access Analyzer: the public bucket is a finding", any(x["resource"] == f"arn:aws:s3:::{bucket}" and x["shared_through"] == "Public access" for x in f), f)
    requests.delete(f"{BASE}/api/s3/buckets/{bucket}/config/policy", timeout=30)
    f = get("/api/iam/detail/access-analyzer").json()["findings"]
    check("Access Analyzer: finding clears when the policy is removed", not any(x["resource"] == f"arn:aws:s3:::{bucket}" for x in f), f)
    requests.delete(f"{BASE}/api/s3/buckets/{bucket}", timeout=30)
    roles = get("/api/iam/roles").json()["roles"]
    check("Roles list carries ARNs", all(r.get("arn", "").startswith("arn:aws:iam::") for r in roles), roles[:2])

SECTIONS = {"ec2": ec2, "s3": s3, "rds": rds, "dynamodb": dynamodb, "lambda": lambda_, "iam": iam}

if __name__ == "__main__":
    only = sys.argv[1:] or list(SECTIONS)
    for k in only:
        try:
            SECTIONS[k]()
        except Exception as e:  # a crashed section is a failure, not a skip
            check(f"{k}: section ran", False, repr(e))
    sys.exit(1 if failed else 0)
