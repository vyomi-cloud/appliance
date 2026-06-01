#!/usr/bin/env python3
"""
CloudLearn conformance harness.

Points the *real* AWS SDK (boto3) at the simulator and exercises real client
lifecycles. This is the judge for fidelity work: it tells us whether an
unmodified application can deploy/test/validate against the sim.

Usage:
    .venv/bin/python tests/conformance/run_conformance.py [--endpoint URL] [--service s3,iam,ec2]

Exit code is non-zero if any check FAILs (errors that would break a real client).
Shape DEVIATIONS (a real client tolerated it, but it diverges from the provider
contract) are reported as warnings and do not fail the run.
"""
from __future__ import annotations

import argparse
import sys
import traceback
import uuid

# boto3 is loaded lazily inside check_* functions that need it, so the harness
# can still run AWS-free checks (azure, gcp) when boto3 isn't installed.
try:
    import boto3
    from botocore.config import Config
    from botocore.exceptions import ClientError, EndpointConnectionError
except ImportError:
    boto3 = None
    Config = None
    class ClientError(Exception):
        pass
    class EndpointConnectionError(Exception):
        pass

PASS, FAIL, WARN, SKIP = "PASS", "FAIL", "WARN", "SKIP"
RESULTS: list[tuple[str, str, str, str]] = []  # (service, check, status, note)


def record(service: str, check: str, status: str, note: str = "") -> None:
    RESULTS.append((service, check, status, note))
    icon = {PASS: "✓", FAIL: "✗", WARN: "!", SKIP: "-"}[status]
    print(f"  [{icon}] {service}:{check} {status}" + (f" — {note}" if note else ""))


def client(service: str, endpoint: str):
    if boto3 is None:
        raise RuntimeError("boto3 is not installed; pip install boto3 to run AWS checks")
    cfg = Config(
        region_name="us-east-1",
        signature_version="v4",
        retries={"max_attempts": 1, "mode": "standard"},
        s3={"addressing_style": "path"},
    )
    return boto3.client(
        service,
        endpoint_url=endpoint,
        aws_access_key_id="test",
        aws_secret_access_key="test",
        config=cfg,
    )


# ---------------------------------------------------------------- S3 (data plane)
def check_s3(endpoint: str) -> None:
    print("\n== S3 (control + data plane) ==")
    s3 = client("s3", endpoint)
    bucket = f"conf-{uuid.uuid4().hex[:12]}"
    key = "hello/world.txt"
    body = b"cloudlearn-conformance-payload"

    try:
        s3.list_buckets()
        record("s3", "ListBuckets", PASS)
    except Exception as exc:  # noqa: BLE001
        record("s3", "ListBuckets", FAIL, repr(exc))

    try:
        s3.create_bucket(Bucket=bucket)
        record("s3", "CreateBucket", PASS)
    except Exception as exc:  # noqa: BLE001
        record("s3", "CreateBucket", FAIL, repr(exc))
        return

    # read-after-write: the new bucket must appear
    try:
        names = [b["Name"] for b in s3.list_buckets().get("Buckets", [])]
        record("s3", "CreateBucket.readAfterWrite", PASS if bucket in names else FAIL,
               "" if bucket in names else "bucket missing from ListBuckets after create")
    except Exception as exc:  # noqa: BLE001
        record("s3", "CreateBucket.readAfterWrite", FAIL, repr(exc))

    # idempotency: AWS returns 200/BucketAlreadyOwnedByYou for same-owner re-create
    try:
        s3.create_bucket(Bucket=bucket)
        record("s3", "CreateBucket.idempotent", PASS)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        ok = code in {"BucketAlreadyOwnedByYou", "BucketAlreadyExists"}
        record("s3", "CreateBucket.idempotent", PASS if ok else WARN,
               f"re-create returned {code or 'error'} (AWS: 200 or BucketAlreadyOwnedByYou)")

    # data plane: PUT object
    try:
        s3.put_object(Bucket=bucket, Key=key, Body=body)
        record("s3", "PutObject", PASS)
    except Exception as exc:  # noqa: BLE001
        record("s3", "PutObject", FAIL, repr(exc))

    # data plane: GET object must return the exact bytes
    try:
        got = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
        record("s3", "GetObject.bytes", PASS if got == body else FAIL,
               "" if got == body else f"body mismatch: {got!r}")
    except Exception as exc:  # noqa: BLE001
        record("s3", "GetObject.bytes", FAIL, repr(exc))

    try:
        h = s3.head_object(Bucket=bucket, Key=key)
        clen = int(h.get("ContentLength", -1))
        record("s3", "HeadObject.ContentLength", PASS if clen == len(body) else WARN,
               "" if clen == len(body) else f"ContentLength={clen}, expected {len(body)}")
    except Exception as exc:  # noqa: BLE001
        record("s3", "HeadObject", FAIL, repr(exc))

    try:
        lo = s3.list_objects_v2(Bucket=bucket)
        keys = [o["Key"] for o in lo.get("Contents", [])]
        record("s3", "ListObjectsV2", PASS if key in keys else FAIL,
               "" if key in keys else f"key not listed; got {keys}")
    except Exception as exc:  # noqa: BLE001
        record("s3", "ListObjectsV2", FAIL, repr(exc))

    # error shape: GET a missing key must raise NoSuchKey
    try:
        s3.get_object(Bucket=bucket, Key="does/not/exist")
        record("s3", "GetObject.404", FAIL, "missing key did not raise")
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        record("s3", "GetObject.404", PASS if code == "NoSuchKey" else WARN,
               f"got {code} (AWS: NoSuchKey)")
    except Exception as exc:  # noqa: BLE001
        record("s3", "GetObject.404", FAIL, repr(exc))

    # error shape: HEAD/GET a missing bucket
    try:
        client("s3", endpoint).get_object(Bucket=f"missing-{uuid.uuid4().hex[:8]}", Key="x")
        record("s3", "GetObject.NoSuchBucket", FAIL, "missing bucket did not raise")
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        record("s3", "GetObject.NoSuchBucket", PASS if code == "NoSuchBucket" else WARN,
               f"got {code} (AWS: NoSuchBucket)")
    except Exception as exc:  # noqa: BLE001
        record("s3", "GetObject.NoSuchBucket", FAIL, repr(exc))

    # cleanup
    try:
        s3.delete_object(Bucket=bucket, Key=key)
        record("s3", "DeleteObject", PASS)
    except Exception as exc:  # noqa: BLE001
        record("s3", "DeleteObject", FAIL, repr(exc))
    try:
        s3.delete_bucket(Bucket=bucket)
        record("s3", "DeleteBucket", PASS)
    except Exception as exc:  # noqa: BLE001
        record("s3", "DeleteBucket", FAIL, repr(exc))


# ---------------------------------------------------------------- IAM (control plane)
def check_iam(endpoint: str) -> None:
    print("\n== IAM (control plane) ==")
    iam = client("iam", endpoint)
    uname = f"conf-user-{uuid.uuid4().hex[:8]}"
    try:
        iam.list_users()
        record("iam", "ListUsers", PASS)
    except Exception as exc:  # noqa: BLE001
        record("iam", "ListUsers", FAIL, repr(exc))
    try:
        resp = iam.create_user(UserName=uname)
        arn = resp.get("User", {}).get("Arn", "")
        ok = arn.startswith("arn:aws:iam::") and arn.endswith(f":user/{uname}")
        record("iam", "CreateUser.arn", PASS if ok else WARN, f"arn={arn!r}")
    except Exception as exc:  # noqa: BLE001
        record("iam", "CreateUser", FAIL, repr(exc))
    try:
        names = [u["UserName"] for u in iam.list_users().get("Users", [])]
        record("iam", "CreateUser.readAfterWrite", PASS if uname in names else FAIL,
               "" if uname in names else "user missing after create")
    except Exception as exc:  # noqa: BLE001
        record("iam", "CreateUser.readAfterWrite", FAIL, repr(exc))
    try:
        iam.delete_user(UserName=uname)
        record("iam", "DeleteUser", PASS)
    except Exception as exc:  # noqa: BLE001
        record("iam", "DeleteUser", WARN, repr(exc))


# ---------------------------------------------------------------- EC2 (control, light)
def check_ec2(endpoint: str) -> None:
    print("\n== EC2 (control plane, describe-only) ==")
    ec2 = client("ec2", endpoint)
    try:
        ec2.describe_instances()
        record("ec2", "DescribeInstances", PASS)
    except Exception as exc:  # noqa: BLE001
        record("ec2", "DescribeInstances", FAIL, repr(exc))
    try:
        ec2.describe_vpcs()
        record("ec2", "DescribeVpcs", PASS)
    except Exception as exc:  # noqa: BLE001
        record("ec2", "DescribeVpcs", WARN, repr(exc))


# ---------------------------------------------------------------- SQS (data plane)
def check_sqs(endpoint: str) -> None:
    print("\n== SQS (data plane) ==")
    sqs = client("sqs", endpoint)
    qname = f"conf-q-{uuid.uuid4().hex[:8]}"
    try:
        qurl = sqs.create_queue(QueueName=qname)["QueueUrl"]
        record("sqs", "CreateQueue", PASS if qurl else FAIL, f"url={qurl}")
    except Exception as exc:  # noqa: BLE001
        record("sqs", "CreateQueue", FAIL, repr(exc))
        return
    try:
        urls = sqs.list_queues().get("QueueUrls", [])
        record("sqs", "ListQueues", PASS if any(qname in u for u in urls) else WARN, f"{len(urls)} queue(s)")
    except Exception as exc:  # noqa: BLE001
        record("sqs", "ListQueues", FAIL, repr(exc))
    try:
        sqs.send_message(QueueUrl=qurl, MessageBody="hello")
        record("sqs", "SendMessage", PASS)
    except Exception as exc:  # noqa: BLE001
        record("sqs", "SendMessage", FAIL, repr(exc))
    try:
        msgs = sqs.receive_message(QueueUrl=qurl, MaxNumberOfMessages=1).get("Messages", [])
        ok = bool(msgs) and msgs[0].get("Body") == "hello"
        record("sqs", "ReceiveMessage.body", PASS if ok else FAIL, "" if ok else f"got {msgs}")
        if msgs:
            try:
                sqs.delete_message(QueueUrl=qurl, ReceiptHandle=msgs[0]["ReceiptHandle"])
                record("sqs", "DeleteMessage", PASS)
            except Exception as exc:  # noqa: BLE001
                record("sqs", "DeleteMessage", WARN, repr(exc))
    except Exception as exc:  # noqa: BLE001
        record("sqs", "ReceiveMessage", FAIL, repr(exc))
    try:
        sqs.delete_queue(QueueUrl=qurl)
        record("sqs", "DeleteQueue", PASS)
    except Exception as exc:  # noqa: BLE001
        record("sqs", "DeleteQueue", WARN, repr(exc))


# ---------------------------------------------------------------- RDS (control plane)
def check_rds(endpoint: str) -> None:
    print("\n== RDS (control plane) ==")
    rds = client("rds", endpoint)
    dbid = f"conf-db-{uuid.uuid4().hex[:8]}"
    try:
        rds.describe_db_instances()
        record("rds", "DescribeDBInstances", PASS)
    except Exception as exc:  # noqa: BLE001
        record("rds", "DescribeDBInstances", FAIL, repr(exc))
    try:
        rds.create_db_instance(
            DBInstanceIdentifier=dbid, DBInstanceClass="db.t3.micro", Engine="postgres",
            MasterUsername="admin", MasterUserPassword="password123", AllocatedStorage=20,
        )
        record("rds", "CreateDBInstance", PASS)
    except Exception as exc:  # noqa: BLE001
        record("rds", "CreateDBInstance", FAIL, repr(exc))
        return
    try:
        dbs = rds.describe_db_instances(DBInstanceIdentifier=dbid).get("DBInstances", [])
        ok = bool(dbs) and dbs[0].get("DBInstanceIdentifier") == dbid
        record("rds", "CreateDBInstance.readAfterWrite", PASS if ok else FAIL)
    except Exception as exc:  # noqa: BLE001
        record("rds", "DescribeDBInstances.byId", FAIL, repr(exc))
    try:
        rds.delete_db_instance(DBInstanceIdentifier=dbid, SkipFinalSnapshot=True)
        record("rds", "DeleteDBInstance", PASS)
    except Exception as exc:  # noqa: BLE001
        record("rds", "DeleteDBInstance", WARN, repr(exc))


# ---------------------------------------------------------------- DynamoDB (data plane)
def check_dynamodb(endpoint: str) -> None:
    print("\n== DynamoDB (data plane) ==")
    ddb = client("dynamodb", endpoint)
    table = f"conf-t-{uuid.uuid4().hex[:8]}"
    try:
        ddb.list_tables()
        record("dynamodb", "ListTables", PASS)
    except Exception as exc:  # noqa: BLE001
        record("dynamodb", "ListTables", FAIL, repr(exc))
    try:
        ddb.create_table(
            TableName=table,
            AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
            KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
            BillingMode="PAY_PER_REQUEST",
        )
        record("dynamodb", "CreateTable", PASS)
    except Exception as exc:  # noqa: BLE001
        record("dynamodb", "CreateTable", FAIL, repr(exc))
        return
    try:
        ddb.put_item(TableName=table, Item={"id": {"S": "k1"}, "val": {"N": "42"}})
        record("dynamodb", "PutItem", PASS)
    except Exception as exc:  # noqa: BLE001
        record("dynamodb", "PutItem", FAIL, repr(exc))
    try:
        item = ddb.get_item(TableName=table, Key={"id": {"S": "k1"}}).get("Item")
        ok = bool(item) and item.get("val", {}).get("N") == "42"
        record("dynamodb", "GetItem.value", PASS if ok else FAIL, "" if ok else f"got {item}")
    except Exception as exc:  # noqa: BLE001
        record("dynamodb", "GetItem", FAIL, repr(exc))
    try:
        ddb.delete_table(TableName=table)
        record("dynamodb", "DeleteTable", PASS)
    except Exception as exc:  # noqa: BLE001
        record("dynamodb", "DeleteTable", WARN, repr(exc))


# ---------------------------------------------------------------- GCP (native REST lifecycles)
def check_gcp(endpoint: str) -> None:
    import base64 as _b64
    import json as _json
    import urllib.error
    import urllib.request

    print("\n== GCP (native REST lifecycles; Discovery/gcloud-style endpoints) ==")
    project, zone, region, loc, db = "cloudlearn-demo", "us-central1-a", "us-central1", "us-central1", "(default)"

    def call(method: str, path: str, body=None):
        url = endpoint.rstrip("/") + path
        data = _json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            url, data=data, method=method,
            headers={"Content-Type": "application/json", "Authorization": "Bearer fake-token"},
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.status, _json.loads(r.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            try:
                return e.code, _json.loads(e.read().decode() or "{}")
            except Exception:  # noqa: BLE001
                return e.code, {}
        except Exception as e:  # noqa: BLE001
            return 0, {"_err": repr(e)}

    def grade(svc, check, st, ok_cond, note=""):
        status = PASS if ok_cond else (WARN if st and 200 <= st < 500 else FAIL)
        record(svc, check, status, note or f"status={st}")

    # ---- Cloud Storage: bucket + object data plane ----
    bucket = f"conf-gcs-{uuid.uuid4().hex[:8]}"
    st, resp = call("POST", f"/storage/v1/b?project={project}", {"name": bucket})
    grade("gcp.storage", "buckets.insert", st, st in (200, 201) and resp.get("name") == bucket, f"status={st} kind={resp.get('kind')!r}")
    st, resp = call("GET", f"/storage/v1/b?project={project}")
    names = [b.get("name") for b in resp.get("items", [])] if isinstance(resp.get("items"), list) else []
    grade("gcp.storage", "buckets.list", st, bucket in names, f"status={st} kind={resp.get('kind')!r}")
    st, resp = call("POST", f"/storage/v1/b/{bucket}/o?name=hello.txt", {"contents": "hi"})
    grade("gcp.storage", "objects.insert", st, st in (200, 201) and resp.get("name") == "hello.txt", f"status={st} kind={resp.get('kind')!r}")
    st, resp = call("GET", f"/storage/v1/b/{bucket}/o")
    onames = [o.get("name") for o in resp.get("items", [])] if isinstance(resp.get("items"), list) else []
    grade("gcp.storage", "objects.list", st, "hello.txt" in onames, f"status={st}")

    # ---- Compute Engine: networks + instances (control plane, Operation-based) ----
    net = f"conf-net-{uuid.uuid4().hex[:6]}"
    st, resp = call("POST", f"/compute/v1/projects/{project}/global/networks", {"name": net, "autoCreateSubnetworks": False})
    grade("gcp.vpc", "networks.insert", st, st in (200, 201) and (resp.get("kind") in (None, "compute#operation") or resp.get("name")), f"status={st} kind={resp.get('kind')!r}")
    st, resp = call("GET", f"/compute/v1/projects/{project}/global/networks")
    grade("gcp.vpc", "networks.list", st, st == 200 and isinstance(resp.get("items", []), list), f"status={st} kind={resp.get('kind')!r}")
    inst = f"conf-vm-{uuid.uuid4().hex[:6]}"
    body = {
        "name": inst, "machineType": f"zones/{zone}/machineTypes/e2-micro",
        "disks": [{"boot": True, "initializeParams": {"sourceImage": "projects/debian-cloud/global/images/family/debian-12"}}],
        "networkInterfaces": [{"network": f"global/networks/{net}"}],
    }
    st, resp = call("POST", f"/compute/v1/projects/{project}/zones/{zone}/instances", body)
    grade("gcp.compute", "instances.insert", st, st in (200, 201), f"status={st} kind={resp.get('kind')!r}")
    st, resp = call("GET", f"/compute/v1/projects/{project}/zones/{zone}/instances")
    inames = [i.get("name") for i in resp.get("items", [])] if isinstance(resp.get("items"), list) else []
    grade("gcp.compute", "instances.list", st, st == 200, f"status={st} kind={resp.get('kind')!r} found={inst in inames}")

    # ---- Cloud SQL ----
    sql = f"conf-sql-{uuid.uuid4().hex[:6]}"
    st, resp = call("POST", f"/sql/v1beta4/projects/{project}/instances", {"name": sql, "databaseVersion": "POSTGRES_15", "settings": {"tier": "db-f1-micro"}})
    grade("gcp.sql", "instances.insert", st, st in (200, 201), f"status={st} kind={resp.get('kind')!r}")
    st, resp = call("GET", f"/sql/v1beta4/projects/{project}/instances")
    grade("gcp.sql", "instances.list", st, st == 200, f"status={st} kind={resp.get('kind')!r}")

    # ---- Pub/Sub: topic + subscription + publish + pull + ack ----
    topic, sub = f"conf-topic-{uuid.uuid4().hex[:6]}", f"conf-sub-{uuid.uuid4().hex[:6]}"
    st, resp = call("PUT", f"/v1/projects/{project}/topics/{topic}")
    grade("gcp.pubsub", "topics.create", st, st in (200, 201) and str(resp.get("name", "")).endswith(topic), f"status={st}")
    st, resp = call("PUT", f"/v1/projects/{project}/subscriptions/{sub}", {"topic": f"projects/{project}/topics/{topic}"})
    grade("gcp.pubsub", "subscriptions.create", st, st in (200, 201), f"status={st}")
    st, resp = call("POST", f"/v1/projects/{project}/topics/{topic}:publish", {"messages": [{"data": _b64.b64encode(b"hello-pubsub").decode()}]})
    msg_ids = resp.get("messageIds", []) if isinstance(resp, dict) else []
    grade("gcp.pubsub", "topics.publish", st, st == 200 and bool(msg_ids), f"status={st} ids={len(msg_ids)}")
    st, resp = call("POST", f"/v1/projects/{project}/subscriptions/{sub}:pull", {"maxMessages": 1, "returnImmediately": True})
    received = resp.get("receivedMessages", []) if isinstance(resp, dict) else []
    ok_body = bool(received) and _b64.b64decode(received[0].get("message", {}).get("data", "") or "").decode(errors="ignore") == "hello-pubsub"
    grade("gcp.pubsub", "subscriptions.pull", st, ok_body, f"status={st} got={len(received)}")
    if received:
        ack = received[0].get("ackId", "")
        st, _ = call("POST", f"/v1/projects/{project}/subscriptions/{sub}:acknowledge", {"ackIds": [ack]})
        grade("gcp.pubsub", "subscriptions.acknowledge", st, st in (200, 204), f"status={st}")

    # ---- Firestore: document create + get ----
    coll = "conf"
    st, resp = call("POST", f"/firestore/v1/projects/{project}/databases/{db}/documents/{coll}", {"fields": {"k": {"stringValue": "v"}}})
    grade("gcp.firestore", "documents.create", st, st in (200, 201) and "name" in resp, f"status={st}")
    st, resp = call("GET", f"/firestore/v1/projects/{project}/databases/{db}/documents/{coll}")
    grade("gcp.firestore", "documents.list", st, st == 200, f"status={st}")

    # ---- Cloud Functions ----
    fn = f"conf-fn-{uuid.uuid4().hex[:6]}"
    st, resp = call("POST", f"/v1/projects/{project}/locations/{loc}/functions", {"name": f"projects/{project}/locations/{loc}/functions/{fn}", "entryPoint": "main", "runtime": "python311"})
    grade("gcp.functions", "functions.create", st, st in (200, 201), f"status={st}")
    st, resp = call("GET", f"/v1/projects/{project}/locations/{loc}/functions")
    grade("gcp.functions", "functions.list", st, st == 200, f"status={st}")

    # ---- IAM: service accounts + project policy ----
    sa = f"conf-sa-{uuid.uuid4().hex[:6]}"
    st, resp = call("POST", f"/v1/projects/{project}/serviceAccounts", {"accountId": sa})
    grade("gcp.iam", "serviceAccounts.create", st, st in (200, 201), f"status={st}")
    st, resp = call("GET", f"/v1/projects/{project}/serviceAccounts")
    grade("gcp.iam", "serviceAccounts.list", st, st == 200, f"status={st}")
    st, resp = call("POST", f"/v1/projects/{project}:getIamPolicy")
    grade("gcp.iam", "getIamPolicy", st, st == 200 and "bindings" in resp, f"status={st}")


def check_azure(endpoint: str) -> None:
    """Azure ARM lifecycle + real-backend data-plane proofs.

    Today: Microsoft.Sql/servers/databases is backed by the cloudlearn-sql-postgres
    container via ``core/gcp_sql_engine``. We assert ARM PUT returns 200/201, then
    GET-after-PUT surfaces a ``properties.connectionInfo`` block — that block is
    only populated when on_create() successfully calls ``eng.provision()``.
    """
    import json as _json
    import uuid
    import urllib.error
    import urllib.request

    print("\n== Azure (ARM lifecycles + real Postgres data plane for SQL) ==")
    sub, rg = "sub-conf", "rg-conf"
    sqlsvr = f"conf-sql-{uuid.uuid4().hex[:6]}"
    sqldb = f"db-{uuid.uuid4().hex[:6]}"

    def call(method: str, path: str, body=None):
        url = endpoint.rstrip("/") + path
        data = _json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            url, data=data, method=method,
            headers={"Content-Type": "application/json", "Authorization": "Bearer fake-token"},
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.status, _json.loads(r.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            try:
                return e.code, _json.loads(e.read().decode() or "{}")
            except Exception:  # noqa: BLE001
                return e.code, {}
        except Exception as e:  # noqa: BLE001
            return 0, {"_err": repr(e)}

    def grade(svc, check, st, ok_cond, note=""):
        status = PASS if ok_cond else (WARN if st and 200 <= st < 500 else FAIL)
        record(svc, check, status, note or f"status={st}")

    # Find an Azure space and switch to it (data-plane provisioning is space-scoped).
    st, resp = call("GET", "/api/spaces")
    azure_space = next(
        (s.get("space_id") for s in resp.get("spaces", []) if s.get("provider") == "azure"),
        "",
    )
    if not azure_space:
        st, resp = call("POST", "/api/spaces", {"name": f"conf-azure-{uuid.uuid4().hex[:6]}", "provider": "azure"})
        azure_space = resp.get("space_id", "")
    grade("azure.spaces", "ensure-azure-space", 200 if azure_space else 0, bool(azure_space), f"space_id={azure_space!r}")
    if azure_space:
        st, _ = call("POST", f"/api/spaces/{azure_space}/switch")
        grade("azure.spaces", "switch", st, st == 200, f"status={st}")

    # ARM: Microsoft.Sql/servers PUT (metadata).
    api = "api-version=2023-08-01"
    base = f"/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Sql/servers/{sqlsvr}"
    st, resp = call("PUT", f"{base}?{api}", {
        "location": "eastus",
        "properties": {"administratorLogin": "azureadmin", "administratorLoginPassword": "Password123!"},
    })
    grade("azure.sql", "servers.put", st, st in (200, 201), f"status={st}")

    # ARM: databases PUT — this is where on_create fires and provisions real Postgres.
    st, resp = call("PUT", f"{base}/databases/{sqldb}?{api}", {"location": "eastus", "properties": {}})
    grade("azure.sql", "databases.put", st, st in (200, 201), f"status={st}")

    # The PUT response is serialized BEFORE on_create runs, so we GET-after-PUT
    # to assert the real-Postgres connectionInfo block was populated.
    st, resp = call("GET", f"{base}/databases/{sqldb}?{api}")
    conn = (resp.get("properties") or {}).get("connectionInfo") or {}
    ok = st == 200 and conn.get("engine", "").startswith("PostgreSQL") and conn.get("database", "").startswith("cl_")
    grade("azure.sql", "databases.real-postgres-backend", st, ok,
          f"status={st} engine={conn.get('engine','')!r} db={conn.get('database','')!r}")

    # Clean up — best-effort.
    call("DELETE", f"{base}/databases/{sqldb}?{api}")
    call("DELETE", f"{base}?{api}")

    # Key Vault data plane (Vault-backed) — encrypt → decrypt round-trip.
    import base64 as _b64
    pt = b"azure-keyvault-conformance"
    pt_b64url = _b64.urlsafe_b64encode(pt).decode().rstrip("=")
    vault_name = f"conf-kv-{uuid.uuid4().hex[:6]}"
    st, resp = call("POST", f"/azure-data/keyvault/{vault_name}/keys/conf-key/encrypt",
                    {"alg": "RSA-OAEP-256", "value": pt_b64url})
    ct = resp.get("value", "")
    grade("azure.keyvault", "keys.encrypt", st, st == 200 and ct.startswith("vault:v1:"),
          f"status={st} ct={ct[:24]!r}")
    st, resp = call("POST", f"/azure-data/keyvault/{vault_name}/keys/conf-key/decrypt",
                    {"alg": "RSA-OAEP-256", "value": ct})
    dec_b64url = resp.get("value", "")
    try:
        dec = _b64.urlsafe_b64decode(dec_b64url + "=" * (-len(dec_b64url) % 4))
    except Exception:
        dec = b""
    grade("azure.keyvault", "keys.decrypt.round-trip", st, st == 200 and dec == pt,
          f"status={st} got={dec!r}")

    # Key Vault secrets.
    st, resp = call("PUT", f"/azure-data/keyvault/{vault_name}/secrets/conf-secret",
                    {"value": "shh-its-a-secret"})
    grade("azure.keyvault", "secrets.put", st, st == 200, f"status={st}")
    st, resp = call("GET", f"/azure-data/keyvault/{vault_name}/secrets/conf-secret")
    grade("azure.keyvault", "secrets.get", st,
          st == 200 and resp.get("value") == "shh-its-a-secret", f"status={st}")


def check_kms_secrets_all(endpoint: str) -> None:
    """Vault-backed crypto + secrets — same Vault, three provider surfaces.

    This is the cross-cutting proof that one container (cloudlearn-vault) gives
    us real KMS + Secrets for AWS, GCP, and Azure simultaneously.
    """
    import base64 as _b64
    import json as _json
    import uuid
    import urllib.error
    import urllib.request

    print("\n== Vault-backed KMS + Secrets (AWS X-Amz / GCP REST / Azure REST) ==")

    def call(method, path, body=None, headers=None):
        url = endpoint.rstrip("/") + path
        data = _json.dumps(body).encode() if body is not None else None
        hdr = {"Content-Type": "application/json"}
        if headers:
            hdr.update(headers)
        req = urllib.request.Request(url, data=data, method=method, headers=hdr)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, _json.loads(r.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            try:
                return e.code, _json.loads(e.read().decode() or "{}")
            except Exception:
                return e.code, {}
        except Exception as e:
            return 0, {"_err": repr(e)}

    def grade(svc, check, st, ok_cond, note=""):
        status = PASS if ok_cond else (WARN if st and 200 <= st < 500 else FAIL)
        record(svc, check, status, note or f"status={st}")

    # ---------------- AWS KMS via X-Amz-Target ----------------
    pt = b"aws-kms-conformance-payload"
    pt_b64 = _b64.b64encode(pt).decode()
    aws_headers = {
        "Content-Type": "application/x-amz-json-1.1",
        "X-Amz-Target": "TrentService.Encrypt",
        "Authorization": "AWS4-HMAC-SHA256 Credential=test/20260531/us-east-1/kms/aws4_request",
    }
    st, resp = call("POST", "/", {"KeyId": "alias/conf-kms", "Plaintext": pt_b64}, headers=aws_headers)
    ct = resp.get("CiphertextBlob", "")
    grade("aws.kms", "Encrypt", st, st == 200 and ct.startswith("vault:v1:"),
          f"status={st} ct={ct[:24]!r}")
    aws_headers["X-Amz-Target"] = "TrentService.Decrypt"
    st, resp = call("POST", "/", {"KeyId": "alias/conf-kms", "CiphertextBlob": ct}, headers=aws_headers)
    dec_b64 = resp.get("Plaintext", "")
    try:
        dec = _b64.b64decode(dec_b64)
    except Exception:
        dec = b""
    grade("aws.kms", "Decrypt.round-trip", st, st == 200 and dec == pt,
          f"status={st} got={dec!r}")

    # ---------------- AWS Secrets Manager ----------------
    sm_headers = {
        "Content-Type": "application/x-amz-json-1.1",
        "X-Amz-Target": "secretsmanager.CreateSecret",
        "Authorization": "AWS4-HMAC-SHA256 Credential=test/20260531/us-east-1/secretsmanager/aws4_request",
    }
    sname = f"conf/sm/{uuid.uuid4().hex[:6]}"
    st, resp = call("POST", "/", {"Name": sname, "SecretString": "aws-secret-roundtrip"}, headers=sm_headers)
    grade("aws.secretsmanager", "CreateSecret", st, st == 200 and resp.get("VersionId"),
          f"status={st}")
    sm_headers["X-Amz-Target"] = "secretsmanager.GetSecretValue"
    st, resp = call("POST", "/", {"SecretId": sname}, headers=sm_headers)
    grade("aws.secretsmanager", "GetSecretValue.round-trip", st,
          st == 200 and resp.get("SecretString") == "aws-secret-roundtrip", f"status={st}")

    # ---------------- GCP Cloud KMS ----------------
    proj = "conf-proj"
    pt2 = b"gcp-kms-roundtrip"
    pt2_b64 = _b64.b64encode(pt2).decode()
    st, resp = call("POST", f"/v1/projects/{proj}/locations/global/keyRings/r/cryptoKeys/k:encrypt",
                    {"plaintext": pt2_b64})
    ct2 = resp.get("ciphertext", "")
    grade("gcp.kms", "encrypt", st, st == 200 and ct2.startswith("vault:v1:"),
          f"status={st} ct={ct2[:24]!r}")
    st, resp = call("POST", f"/v1/projects/{proj}/locations/global/keyRings/r/cryptoKeys/k:decrypt",
                    {"ciphertext": ct2})
    try:
        dec2 = _b64.b64decode(resp.get("plaintext", ""))
    except Exception:
        dec2 = b""
    grade("gcp.kms", "decrypt.round-trip", st, st == 200 and dec2 == pt2,
          f"status={st} got={dec2!r}")

    # ---------------- GCP Secret Manager ----------------
    sec_name = f"conf-sec-{uuid.uuid4().hex[:6]}"
    sec_val_b64 = _b64.b64encode(b"gcp-secret-roundtrip").decode()
    st, _ = call("POST", f"/v1/projects/{proj}/secrets?secretId={sec_name}", {"replication": {"automatic": {}}})
    grade("gcp.secretmanager", "create", st, st == 200, f"status={st}")
    st, _ = call("POST", f"/v1/projects/{proj}/secrets/{sec_name}:addVersion", {"payload": {"data": sec_val_b64}})
    grade("gcp.secretmanager", "addVersion", st, st == 200, f"status={st}")
    st, resp = call("POST", f"/v1/projects/{proj}/secrets/{sec_name}/versions/latest:access", {})
    try:
        got = _b64.b64decode((resp.get("payload") or {}).get("data", ""))
    except Exception:
        got = b""
    grade("gcp.secretmanager", "access.round-trip", st, st == 200 and got == b"gcp-secret-roundtrip",
          f"status={st} got={got!r}")


def check_eventing_all(endpoint: str) -> None:
    """NATS-backed eventing — same broker, three provider surfaces.

    Publishes via each provider's wire shape (EventBridge PutEvents / Eventarc
    trigger fire / Event Grid topic publish), then reads the simulator-only
    inbox (``/__nats/inbox``) to assert each message was delivered.
    """
    import json as _json
    import uuid
    import urllib.error
    import urllib.request

    print("\n== NATS-backed eventing (EventBridge / Eventarc / Event Grid) ==")

    def call(method, path, body=None, headers=None):
        url = endpoint.rstrip("/") + path
        data = _json.dumps(body).encode() if body is not None else None
        hdr = {"Content-Type": "application/json"}
        if headers:
            hdr.update(headers)
        req = urllib.request.Request(url, data=data, method=method, headers=hdr)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, _json.loads(r.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            try:
                return e.code, _json.loads(e.read().decode() or "{}")
            except Exception:
                return e.code, {}
        except Exception as e:
            return 0, {"_err": repr(e)}

    def grade(svc, check, st, ok_cond, note=""):
        status = PASS if ok_cond else (WARN if st and 200 <= st < 500 else FAIL)
        record(svc, check, status, note or f"status={st}")

    # NATS reachability gate.
    st, resp = call("GET", "/__nats/status")
    grade("nats", "broker.available", st, st == 200 and resp.get("available") is True,
          f"status={st} available={resp.get('available')}")

    marker = uuid.uuid4().hex[:8]

    # AWS EventBridge PutEvents.
    aws_h = {
        "Content-Type": "application/x-amz-json-1.1",
        "X-Amz-Target": "AWSEvents.PutEvents",
        "Authorization": "AWS4-HMAC-SHA256 Credential=test/20260531/us-east-1/events/aws4_request",
    }
    st, resp = call("POST", "/", {
        "Entries": [{
            "Source": f"conf.{marker}",
            "DetailType": "ConfEvent",
            "EventBusName": "default",
            "Detail": _json.dumps({"marker": marker}),
        }]
    }, headers=aws_h)
    grade("aws.eventbridge", "PutEvents", st,
          st == 200 and (resp.get("Entries") or [{}])[0].get("EventId"),
          f"status={st}")

    # GCP Eventarc trigger fire.
    st, resp = call("POST", "/v1/projects/p/locations/us-central1/triggers/conf-trigger:fire",
                    {"marker": marker})
    grade("gcp.eventarc", "trigger.fire", st, st == 200 and resp.get("delivered") is True,
          f"status={st}")

    # Azure Event Grid topic publish.
    st, resp = call("POST", "/azure-data/eventgrid/conf-topic/events", [{
        "id": f"conf-{marker}", "subject": "conformance",
        "eventType": "ConfEvent", "data": {"marker": marker}, "dataVersion": "1.0",
    }])
    grade("azure.eventgrid", "topic.publish", st, st == 200 and resp.get("published") == 1,
          f"status={st}")

    # Read inbox — all three messages must be there + tagged with our marker.
    st, resp = call("GET", "/__nats/inbox?limit=100")
    msgs = resp.get("messages") or []

    def found(prefix: str) -> bool:
        for m in msgs:
            if not m["subject"].startswith(prefix):
                continue
            blob = _json.dumps(m["payload"])
            if marker in blob:
                return True
        return False

    grade("aws.eventbridge", "PutEvents.delivered", st, found("aws.eventbridge."),
          f"inbox-msgs={len(msgs)}")
    grade("gcp.eventarc", "trigger.fire.delivered", st, found("gcp.eventarc."),
          f"inbox-msgs={len(msgs)}")
    grade("azure.eventgrid", "topic.publish.delivered", st, found("azure.eventgrid."),
          f"inbox-msgs={len(msgs)}")


def check_aws_real_sdks(endpoint: str) -> None:
    """Run the AWS Go + Java real-SDK conformance harnesses.

    These harnesses run UNMODIFIED ``aws-sdk-go-v2`` and ``software.amazon.awssdk``
    clients against the simulator, proving real SDK fidelity (the gap that the
    boto3 check alone couldn't catch — e.g. the Last-Modified RFC 1123 bug that
    aws-sdk-go-v2 surfaced on first run).

    Shell out to docker because the SDKs themselves need a build toolchain.
    Skip-with-WARN if docker isn't available on the host running the harness.
    """
    import shutil
    import subprocess

    print("\n== AWS real-SDK conformance (aws-sdk-go-v2 + aws-sdk-java-v2) ==")

    def grade(svc, check, st, ok_cond, note=""):
        status = PASS if ok_cond else (WARN if st and 200 <= st < 500 else FAIL)
        record(svc, check, status, note or f"status={st}")

    if not shutil.which("docker"):
        record("aws.sdk-go", "harness", SKIP, "docker not available on host")
        record("aws.sdk-java", "harness", SKIP, "docker not available on host")
        return

    # The harnesses live at tests/conformance/aws-sdk-{go,java}/
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    go_dir = os.path.join(here, "aws-sdk-go")
    java_dir = os.path.join(here, "aws-sdk-java")

    # Go.
    try:
        r = subprocess.run(
            ["docker", "run", "--rm", "--network", "host",
             "-e", f"ENDPOINT={endpoint}",
             "-v", f"{go_dir}:/app", "-w", "/app",
             "golang:1.22", "sh", "-c", "go run ."],
            capture_output=True, text=True, timeout=180,
        )
        passes = r.stdout.count("PASS ")
        fails = r.stdout.count("FAIL ")
        record("aws.sdk-go", "go-harness", PASS if (r.returncode == 0 and fails == 0) else FAIL,
               f"passes={passes} fails={fails} exit={r.returncode}")
    except Exception as e:
        record("aws.sdk-go", "go-harness", FAIL, f"err={e!r}")

    # Java. Maven downloads are slow on first run; allow a generous timeout.
    try:
        r = subprocess.run(
            ["docker", "run", "--rm", "--network", "host",
             "-e", f"ENDPOINT={endpoint}",
             "-v", f"{java_dir}:/work", "-w", "/work",
             "-v", os.path.expanduser("~/.m2") + ":/root/.m2",
             "maven:3.9-eclipse-temurin-17", "mvn", "-q", "compile", "exec:java"],
            capture_output=True, text=True, timeout=600,
        )
        passes = r.stdout.count("PASS ")
        fails = r.stdout.count("FAIL ")
        record("aws.sdk-java", "java-harness", PASS if (r.returncode == 0 and fails == 0) else FAIL,
               f"passes={passes} fails={fails} exit={r.returncode}")
    except Exception as e:
        record("aws.sdk-java", "java-harness", FAIL, f"err={e!r}")


def check_azure_pack_parity(endpoint: str) -> None:
    """Azure now uses the same pack architecture as AWS+GCP.

    Backfilled 2026-06-01 — packs/azure/ holds 11 service + 3 tooling packs,
    PROVIDER_PACK_GROUPS["azure"] is populated, providers/azure.py mirrors
    aws.py/gcp.py, and /api/providers/azure/{cli,sdk/java,sdk/go,...} return
    real responses (not 404s like before the backfill).
    """
    import json as _json
    import urllib.error
    import urllib.request

    print("\n== Azure pack-architecture parity (parity with AWS+GCP) ==")

    def grade(svc, check, st, ok_cond, note=""):
        status = PASS if ok_cond else (WARN if st and 200 <= st < 500 else FAIL)
        record(svc, check, status, note or f"status={st}")

    def call(method, path, body=None):
        url = endpoint.rstrip("/") + path
        data = _json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method,
                                      headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, _json.loads(r.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            try:
                return e.code, _json.loads(e.read().decode() or "{}")
            except Exception:
                return e.code, {}
        except Exception as e:
            return 0, {"_err": repr(e)}

    # Matrix returns real packs.
    st, r = call("GET", "/api/providers/azure/matrix")
    service_packs = (r.get("packs") or {}).get("service", [])
    tooling_packs = (r.get("packs") or {}).get("tooling", [])
    grade("azure.packs", "matrix.service-packs", st,
          st == 200 and len(service_packs) == 11,
          f"status={st} service_pack_count={len(service_packs)}")
    grade("azure.packs", "matrix.tooling-packs", st,
          st == 200 and len(tooling_packs) == 3,
          f"status={st} tooling_pack_count={len(tooling_packs)}")

    # Tool metadata routes.
    st, r = call("GET", "/api/providers/azure/cli")
    grade("azure.packs", "cli.metadata", st,
          st == 200 and r.get("tool") == "az", f"status={st} tool={r.get('tool')!r}")
    st, r = call("GET", "/api/providers/azure/sdk/java")
    grade("azure.packs", "sdk-java.metadata", st,
          st == 200 and "azure-resourcemanager" in (r.get("dependency", "") or ""),
          f"status={st}")
    st, r = call("GET", "/api/providers/azure/sdk/go")
    grade("azure.packs", "sdk-go.metadata", st,
          st == 200 and "azure-sdk-for-go" in (r.get("dependency", "") or ""),
          f"status={st}")

    # az CLI resolver.
    st, r = call("POST", "/api/providers/azure/cli/resolve",
                 {"command": "az vm list --resource-group rg-demo"})
    grade("azure.packs", "cli.resolve.vm-list", st,
          st == 200 and r.get("operation") == "VirtualMachines_ListAll",
          f"status={st} op={r.get('operation')!r}")
    st, r = call("POST", "/api/providers/azure/cli/resolve",
                 {"command": "az storage account create --name mvp"})
    grade("azure.packs", "cli.resolve.storage-create", st,
          st == 200 and r.get("operation") == "StorageAccounts_Create",
          f"status={st} op={r.get('operation')!r}")

    # SDK snippets.
    st, r = call("GET", "/api/providers/azure/sdk/java/snippet")
    grade("azure.packs", "sdk-java.snippet", st,
          st == 200 and "ComputeManager" in (r.get("snippet", "") or ""),
          f"status={st}")
    st, r = call("GET", "/api/providers/azure/sdk/go/snippet")
    grade("azure.packs", "sdk-go.snippet", st,
          st == 200 and "armcompute" in (r.get("snippet", "") or ""),
          f"status={st}")


def check_sqs_elasticmq(endpoint: str) -> None:
    """SQS legacy/query → ElasticMQ round-trip. Modern JSON-RPC stays in-memory
    (limitation noted in proxy module: elasticmq-native is XML-only)."""
    import re
    import urllib.error
    import urllib.request
    import uuid as _uuid

    print("\n== ElasticMQ proxy (SQS query protocol → real broker) ==")

    def grade(svc, check, st, ok_cond, note=""):
        status = PASS if ok_cond else (WARN if st and 200 <= st < 500 else FAIL)
        record(svc, check, status, note or f"status={st}")

    def post_form(body: str):
        req = urllib.request.Request(
            endpoint.rstrip("/") + "/",
            data=body.encode(), method="POST",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": "AWS4-HMAC-SHA256 Credential=test/20260531/us-east-1/sqs/aws4_request",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()
        except Exception as e:
            return 0, repr(e)

    qname = f"conf-emq-{_uuid.uuid4().hex[:8]}"
    payload = "elasticmq-conformance-roundtrip-" + _uuid.uuid4().hex[:8]

    st, body = post_form(f"Action=CreateQueue&Version=2012-11-05&QueueName={qname}")
    qurl_match = re.search(r"<QueueUrl>([^<]+)</QueueUrl>", body)
    qurl = qurl_match.group(1) if qurl_match else ""
    grade("aws.sqs.elasticmq", "CreateQueue", st,
          st == 200 and qname in qurl, f"status={st} qurl={qurl!r}")

    st, body = post_form(
        f"Action=SendMessage&Version=2012-11-05&QueueUrl={urllib.parse.quote(qurl, safe='')}"
        f"&MessageBody={payload}"
    )
    mid_match = re.search(r"<MessageId>([^<]+)</MessageId>", body)
    grade("aws.sqs.elasticmq", "SendMessage", st,
          st == 200 and bool(mid_match), f"status={st}")

    st, body = post_form(
        f"Action=ReceiveMessage&Version=2012-11-05&QueueUrl={urllib.parse.quote(qurl, safe='')}"
        f"&MaxNumberOfMessages=10&WaitTimeSeconds=1"
    )
    grade("aws.sqs.elasticmq", "ReceiveMessage.round-trip", st,
          st == 200 and payload in body, f"status={st} payload-in-body={payload in body}")


def check_dynamodb_proxy(endpoint: str) -> None:
    """Assert DDB CreateTable+PutItem+GetItem round-trips through DDB Local."""
    import json as _json
    import urllib.error
    import urllib.request
    import uuid as _uuid

    print("\n== DynamoDB Local proxy (CreateTable / PutItem / GetItem) ==")

    def grade(svc, check, st, ok_cond, note=""):
        status = PASS if ok_cond else (WARN if st and 200 <= st < 500 else FAIL)
        record(svc, check, status, note or f"status={st}")

    def call(target, body):
        req = urllib.request.Request(
            endpoint.rstrip("/") + "/",
            data=_json.dumps(body).encode(), method="POST",
            headers={
                "X-Amz-Target": target,
                "Content-Type": "application/x-amz-json-1.0",
                "Authorization": "AWS4-HMAC-SHA256 Credential=test/20260531/us-east-1/dynamodb/aws4_request",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, _json.loads(r.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            try:
                return e.code, _json.loads(e.read().decode() or "{}")
            except Exception:
                return e.code, {}
        except Exception as e:
            return 0, {"_err": repr(e)}

    table = f"conf-ddb-{_uuid.uuid4().hex[:8]}"
    st, r = call("DynamoDB_20120810.CreateTable", {
        "TableName": table,
        "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}],
        "AttributeDefinitions": [{"AttributeName": "id", "AttributeType": "S"}],
        "BillingMode": "PAY_PER_REQUEST",
    })
    grade("aws.ddb.proxy", "CreateTable", st,
          st == 200 and (r.get("TableDescription") or {}).get("TableStatus") == "ACTIVE",
          f"status={st}")

    item_id = _uuid.uuid4().hex[:12]
    st, _ = call("DynamoDB_20120810.PutItem", {
        "TableName": table,
        "Item": {"id": {"S": item_id}, "payload": {"S": "conformance-roundtrip"}},
    })
    grade("aws.ddb.proxy", "PutItem", st, st == 200, f"status={st}")

    st, r = call("DynamoDB_20120810.GetItem", {
        "TableName": table,
        "Key": {"id": {"S": item_id}},
    })
    got = ((r.get("Item") or {}).get("payload") or {}).get("S", "")
    grade("aws.ddb.proxy", "GetItem.round-trip", st,
          st == 200 and got == "conformance-roundtrip", f"status={st} got={got!r}")

    st, _ = call("DynamoDB_20120810.DeleteTable", {"TableName": table})
    grade("aws.ddb.proxy", "DeleteTable", st, st == 200, f"status={st}")


def check_minio_mirror(endpoint: str) -> None:
    """Assert PUT through simulator S3 actually lands in MinIO with the same bytes."""
    import json
    import os
    import urllib.error
    import urllib.request
    import uuid as _uuid

    print("\n== MinIO mirror (AWS S3 PUT → bytes durable in cloudlearn-minio) ==")

    def grade(svc, check, st, ok_cond, note=""):
        status = PASS if ok_cond else (WARN if st and 200 <= st < 500 else FAIL)
        record(svc, check, status, note or f"status={st}")

    # Switch to an AWS space first — S3 buckets are space-scoped, and the
    # prior azure/vault checks may have left us in a non-AWS space.
    try:
        with urllib.request.urlopen(endpoint.rstrip("/") + "/api/spaces", timeout=5) as r:
            spaces = json.loads(r.read().decode()).get("spaces", [])
        aws_space = next((s.get("space_id") for s in spaces if s.get("provider") == "aws"), "")
        if aws_space:
            req = urllib.request.Request(
                endpoint.rstrip("/") + f"/api/spaces/{aws_space}/switch", method="POST"
            )
            urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass

    bucket = f"conf-mirror-{_uuid.uuid4().hex[:8]}"
    key = "round/trip.txt"
    payload = b"minio-mirror-conformance-" + _uuid.uuid4().hex.encode()

    # PUT bucket + object via simulator.
    aws_auth = {"Authorization": "AWS4-HMAC-SHA256 Credential=test/20260531/us-east-1/s3/aws4_request"}

    def http(method, path, body=None, hdr=None):
        url = endpoint.rstrip("/") + path
        h = dict(aws_auth)
        if hdr:
            h.update(hdr)
        req = urllib.request.Request(url, data=body, method=method, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()
        except Exception as e:
            return 0, repr(e).encode()

    st, _ = http("PUT", f"/{bucket}")
    grade("aws.s3.minio", "bucket.put", st, st in (200, 201), f"status={st}")
    st, _ = http("PUT", f"/{bucket}/{key}", body=payload, hdr={"Content-Type": "text/plain"})
    grade("aws.s3.minio", "object.put", st, st == 200, f"status={st}")

    # Read back via simulator — must equal payload.
    st, body = http("GET", f"/{bucket}/{key}")
    grade("aws.s3.minio", "object.get.via-simulator", st, st == 200 and body == payload,
          f"status={st} bytes={len(body)}")

    # Read back via MinIO direct (boto3 against :9100 from host).
    minio_url = os.environ.get("CLOUDLEARN_MINIO_URL_HOST", "http://192.168.252.7:9100")
    try:
        if boto3 is None:
            grade("aws.s3.minio", "object.get.via-minio-direct", 0, False, "boto3 not installed locally")
        else:
            cli = boto3.client(
                "s3", endpoint_url=minio_url,
                aws_access_key_id="cloudlearn", aws_secret_access_key="cloudlearn-dev-secret-key",
                region_name="us-east-1",
                config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
            )
            r = cli.get_object(Bucket=bucket, Key=key)
            got = r["Body"].read()
            grade("aws.s3.minio", "object.get.via-minio-direct", 200,
                  got == payload, f"bytes={len(got)} match={got == payload}")
    except Exception as e:
        grade("aws.s3.minio", "object.get.via-minio-direct", 0, False, f"err={e!r}")


def check_iam_eval_all(endpoint: str) -> None:
    """Cedar-backed IAM evaluation across AWS/GCP/Azure policy shapes.

    For each provider's native policy doc shape, we compile to Cedar and assert
    deny-by-default + allow-when-policy-grants behavior.
    """
    import json as _json
    import urllib.error
    import urllib.request

    print("\n== Cedar-backed IAM eval (AWS / GCP / Azure dialects) ==")

    def call(method, path, body=None):
        url = endpoint.rstrip("/") + path
        data = _json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, _json.loads(r.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            try:
                return e.code, _json.loads(e.read().decode() or "{}")
            except Exception:
                return e.code, {}
        except Exception as e:
            return 0, {"_err": repr(e)}

    def grade(svc, check, st, ok_cond, note=""):
        status = PASS if ok_cond else (WARN if st and 200 <= st < 500 else FAIL)
        record(svc, check, status, note or f"status={st}")

    # AWS IAM JSON.
    st, _ = call("POST", "/api/iam/policies", {"aws": [{
        "__principal__": 'User::"alice"',
        "Statement": [
            {"Effect": "Allow", "Action": "s3:GetObject", "Resource": "arn:aws:s3:::bkt/*"},
            {"Effect": "Deny", "Action": "s3:DeleteBucket", "Resource": "arn:aws:s3:::bkt"},
        ],
    }]})
    grade("aws.iam", "policies.set", st, st == 200, f"status={st}")
    st, r = call("POST", "/api/iam/evaluate", {
        "principal": 'User::"alice"', "action": 'Action::"s3:GetObject"',
        "resource": 'Resource::"arn:aws:s3:::bkt/*"',
    })
    grade("aws.iam", "evaluate.explicit-allow", st, st == 200 and r.get("allowed") is True,
          f"status={st} reason={r.get('reason')!r}")
    st, r = call("POST", "/api/iam/evaluate", {
        "principal": 'User::"bob"', "action": 'Action::"s3:GetObject"',
        "resource": 'Resource::"arn:aws:s3:::bkt/*"',
    })
    grade("aws.iam", "evaluate.deny-by-default", st, st == 200 and r.get("allowed") is False,
          f"status={st} reason={r.get('reason')!r}")

    # GCP IAM binding.
    st, _ = call("POST", "/api/iam/policies", {"gcp": [
        {"role": "roles/storage.objectViewer", "members": ["user:alice@x.com"]}
    ]})
    grade("gcp.iam", "policies.set", st, st == 200, f"status={st}")
    st, r = call("POST", "/api/iam/evaluate", {
        "principal": 'User::"alice@x.com"',
        "action": 'Action::"roles/storage.objectViewer"',
        "resource": 'Resource::"any"',
    })
    grade("gcp.iam", "evaluate.explicit-allow", st, st == 200 and r.get("allowed") is True,
          f"status={st} reason={r.get('reason')!r}")
    st, r = call("POST", "/api/iam/evaluate", {
        "principal": 'User::"mallory@x.com"',
        "action": 'Action::"roles/storage.objectViewer"',
        "resource": 'Resource::"any"',
    })
    grade("gcp.iam", "evaluate.deny-by-default", st, st == 200 and r.get("allowed") is False,
          f"status={st} reason={r.get('reason')!r}")

    # Azure RBAC.
    st, _ = call("POST", "/api/iam/policies", {"azure": [
        {"principalId": "deploy-sp", "principalType": "User",
         "roleName": "Contributor", "scope": "/subs/sub-001/rg/prod"}
    ]})
    grade("azure.rbac", "policies.set", st, st == 200, f"status={st}")
    st, r = call("POST", "/api/iam/evaluate", {
        "principal": 'User::"deploy-sp"',
        "action": 'Action::"Contributor"',
        "resource": 'Scope::"/subs/sub-001/rg/prod"',
    })
    grade("azure.rbac", "evaluate.explicit-allow", st, st == 200 and r.get("allowed") is True,
          f"status={st} reason={r.get('reason')!r}")


# Per-check provider mapping for isolated space creation. Each CloudLearn
# space is 1:1 with a provider, so a check that hits GCP needs a GCP space.
# Checks that touch multiple providers (vault, eventing, iameval) cycle
# through providers via `_PROVIDER_CYCLE` to give each provider a fresh space.
_CHECK_PROVIDER: dict[str, str] = {
    "s3":          "aws",
    "iam":         "aws",
    "ec2":         "aws",
    "sqs":         "aws",
    "rds":         "aws",
    "dynamodb":    "aws",
    "minio":       "aws",
    "emq":         "aws",
    "ddb":         "aws",
    "aws-sdks":    "aws",
    "gcp":         "gcp",
    "azure":       "azure",
    "azpacks":     "azure",
    # Multi-provider checks — leave default; the check itself walks providers.
    "vault":       None,
    "eventing":    None,
    "iameval":     None,
}


def _isolate_for_check(endpoint: str, check_name: str) -> None:
    """Create a fresh space (per-provider) + switch to it before a check
    runs. Closes the space-context bleed where check N's resource creates
    pollute check N+1's space view. For multi-provider checks (vault/
    eventing/iameval) leaves the existing space — those tests pick the
    provider internally."""
    import time as _time
    import requests as _req
    provider = _CHECK_PROVIDER.get(check_name)
    if provider is None:
        return  # multi-provider check; don't override the active space
    space_name = f"conformance-{check_name}-{int(_time.time() * 1000) % 10_000_000}"
    try:
        r = _req.post(f"{endpoint}/api/spaces/create",
                      json={"name": space_name, "provider": provider}, timeout=5)
        if r.status_code in (200, 201):
            body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            sid = (body.get("space") or {}).get("space_id") or body.get("space_id", "")
            if sid:
                _req.post(f"{endpoint}/api/spaces/{sid}/switch", timeout=5)
    except Exception:
        pass  # fail-open — checks still run, just without fresh isolation


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoint", default="http://127.0.0.1:9000")
    ap.add_argument("--service", default="s3,iam,ec2,sqs,rds,dynamodb,gcp,azure,vault,eventing,iameval,minio")
    ap.add_argument("--isolate-spaces", action="store_true",
                    help="Create a fresh space before each check (closes context bleed; "
                         "raises cumulative pass rate from ~82%% to >95%%).")
    ap.add_argument("--fail-under", type=float, default=0.0,
                    help="Exit non-zero when overall parity %% < threshold. CI uses 95.0.")
    args = ap.parse_args()

    print(f"CloudLearn conformance harness -> {args.endpoint}"
          + (f" [isolate-spaces=on]" if args.isolate_spaces else ""))
    services = [s.strip() for s in args.service.split(",") if s.strip()]
    runners = {
        "s3": check_s3, "iam": check_iam, "ec2": check_ec2,
        "sqs": check_sqs, "rds": check_rds, "dynamodb": check_dynamodb,
        "gcp": check_gcp, "azure": check_azure,
        "vault": check_kms_secrets_all,
        "eventing": check_eventing_all,
        "iameval": check_iam_eval_all,
        "minio": check_minio_mirror,
        "ddb": check_dynamodb_proxy,
        "emq": check_sqs_elasticmq,
        "azpacks": check_azure_pack_parity,
        "aws-sdks": check_aws_real_sdks,
    }
    for svc in services:
        runner = runners.get(svc)
        if not runner:
            record(svc, "(unknown service)", SKIP)
            continue
        if args.isolate_spaces:
            _isolate_for_check(args.endpoint, svc)
        try:
            runner(args.endpoint)
        except EndpointConnectionError as exc:
            record(svc, "(connect)", FAIL, repr(exc))
        except Exception:  # noqa: BLE001
            record(svc, "(harness error)", FAIL, traceback.format_exc().splitlines()[-1])

    # scoreboard
    print("\n==================== PARITY SCOREBOARD ====================")
    by_svc: dict[str, dict[str, int]] = {}
    for svc, _check, status, _note in RESULTS:
        by_svc.setdefault(svc, {PASS: 0, FAIL: 0, WARN: 0, SKIP: 0})
        by_svc[svc][status] += 1
    total = {PASS: 0, FAIL: 0, WARN: 0, SKIP: 0}
    for svc, counts in by_svc.items():
        gradable = counts[PASS] + counts[FAIL] + counts[WARN]
        pct = (100.0 * counts[PASS] / gradable) if gradable else 0.0
        print(f"  {svc:6s}  parity {pct:5.1f}%   "
              f"pass={counts[PASS]} warn(deviation)={counts[WARN]} fail={counts[FAIL]}")
        for k in total:
            total[k] += counts[k]
    gradable = total[PASS] + total[FAIL] + total[WARN]
    overall = (100.0 * total[PASS] / gradable) if gradable else 0.0
    print(f"  ----  OVERALL parity {overall:5.1f}%  "
          f"pass={total[PASS]} warn={total[WARN]} fail={total[FAIL]} skip={total[SKIP]}")
    print("===========================================================")
    if args.fail_under and overall < args.fail_under:
        print(f"FAIL: overall {overall:.1f}% < threshold {args.fail_under:.1f}%")
        return 2
    return 1 if total[FAIL] else 0


if __name__ == "__main__":
    raise SystemExit(main())
