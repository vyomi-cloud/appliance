"""Console ↔ conformance-core adapter (the Nano substrate's analogue of the
Pro/Max FastAPI adapter).

The three SPA consoles speak a small REST-ish API (`/api/s3/buckets/...`,
`/api/dynamodb/tables/...`, `/api/iam/users`, `/api/rds/databases`, `/api/sqs/queues`,
`/api/aws/secrets`, `/api/aws/kms/keys`) with friendly JSON envelopes
(`{buckets:[...]}`, `{tables:[...]}`, `{users:[...]}`, `{databases:[...]}`,
`{queues:[...]}`, `{value:[...]}`). The PROVEN conformance cores speak the NATIVE
cloud wire (S3: method+path; DynamoDB/KMS/Secrets/SQS: X-Amz-Target + JSON;
IAM/RDS: Query-protocol XML). This module is the thin translation between them —
so the in-browser console's data-plane is served by the SAME logic the
conformance suite proves, not the generic stub. Mutations and reads ALL flow
through the cores; this file only reshapes requests/responses, exactly the role
the FastAPI route plays in Pro/Max.

For JSON-wire cores (DynamoDB/KMS/Secrets/SQS) the adapter calls dispatch() and
reads the response dict. For XML-wire cores (IAM/RDS) it dispatches the mutation
(authoritative) and reads the store for the console's JSON view (so it never has
to parse XML). Every service has its own in-tab store, the single source of truth.

The two `InMemory*Store`s here are the single in-tab source of truth. (Unifying
them with the relay endpoint's store — so an external `aws s3` call and the
console see one dataset — is a later step; today each page owns its store.)
"""
from __future__ import annotations

import base64
import copy
import re

from datetime import datetime, timezone

from core.object_store import InMemoryObjectStore
from core import s3_object_core as s3
from core.nosql_store import InMemoryNoSqlStore
from core import dynamodb_core as ddb
from core.kms_keystore import InMemoryKeyStore
from core import kms_core as kms
from core.kv_store import InMemoryKvStore
from core import secrets_core as secrets
from core.sql_store import InMemorySqlStore
from core import rds_core as rds
from core.iam_store import InMemoryIamStore
from core import iam_core as iam
from core.messaging_store import InMemoryMessagingStore
from core import sqs_core as sqs

OBJ = InMemoryObjectStore()
DDB = InMemoryNoSqlStore()
KMS = InMemoryKeyStore()
SEC = InMemoryKvStore()
RDB = InMemorySqlStore()
IAM = InMemoryIamStore()
MSG = InMemoryMessagingStore()
REGION = "us-east-1"

_CODE_RE = re.compile(rb"<Code>([^<]+)</Code>")
_XML_CODE_RE = re.compile(r"<Code>([^<]+)</Code>")


def _s3_code(body: bytes) -> str:
    m = _CODE_RE.search(body or b"")
    return m.group(1).decode() if m else "Error"


def _xml_code(body: str) -> str:
    m = _XML_CODE_RE.search(body or "")
    return m.group(1) if m else "Error"


def _iso(epoch) -> str:
    try:
        return datetime.fromtimestamp(float(epoch), timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    except Exception:
        return ""


# ── S3 ─────────────────────────────────────────────────────────────────────
def _bucket_view(name: str) -> dict:
    b = OBJ.buckets.get(name, {})
    ver = b.get("versioning", "Disabled")
    return {"name": name, "creation_date": b.get("creation_date", ""), "region": REGION,
            "versioning": ver, "versioning_enabled": ver == "Enabled"}


def s3_create_bucket(p: dict) -> dict:
    name = str(p.get("name") or p.get("bucket") or p.get("Bucket") or "").strip()
    if not name:
        return {"ok": False, "code": "InvalidBucketName"}
    existed = OBJ.bucket_exists(name)
    OBJ.create_bucket(name)
    OBJ.buckets[name].setdefault("creation_date", s3._now())
    if p.get("versioning_enabled") in (True, "true", "Enabled", "on"):
        OBJ.buckets[name]["versioning"] = "Enabled"
    return {"ok": True, "created": not existed, **_bucket_view(name)}


def s3_list_buckets(p: dict | None = None) -> dict:
    return {"ok": True, "buckets": [_bucket_view(n) for n in sorted(OBJ.buckets)]}


def s3_get_bucket(p: dict) -> dict:
    name = str(p.get("bucket") or p.get("name") or "")
    if not OBJ.bucket_exists(name):
        return {"ok": False, "code": "NoSuchBucket", "name": name}
    return {"ok": True, **_bucket_view(name)}


def s3_delete_bucket(p: dict) -> dict:
    name = str(p.get("bucket") or p.get("name") or "")
    r = s3.dispatch(OBJ, "DELETE", "/" + name)
    return {"ok": r.status in (200, 204), "name": name}


def s3_set_versioning(p: dict) -> dict:
    name = str(p.get("bucket") or p.get("name") or "")
    if not OBJ.bucket_exists(name):
        return {"ok": False, "code": "NoSuchBucket", "name": name}
    status = str(p.get("status") or "Suspended")
    OBJ.buckets[name]["versioning"] = status if status in ("Enabled", "Suspended", "Disabled") else "Suspended"
    return {"ok": True, "status": OBJ.buckets[name]["versioning"]}


def s3_list_objects(p: dict) -> dict:
    name = str(p.get("bucket") or p.get("name") or "")
    if not OBJ.bucket_exists(name):
        return {"ok": False, "code": "NoSuchBucket", "name": name}
    bucket_objects = OBJ.bucket_objects(name)
    objs = []
    for key in sorted(bucket_objects):
        versions = bucket_objects[key].get("versions", [])
        if not versions or versions[0].get("is_delete_marker"):
            continue
        v = versions[0]
        objs.append({"key": key, "name": key, "size": v.get("size", 0),
                     "content_length": v.get("size", 0),
                     "last_modified": v.get("last_modified", ""),
                     "etag": v.get("etag", ""),
                     "storage_class": v.get("storage_class", "STANDARD")})
    return {"ok": True, "objects": objs}


def s3_put_object(p: dict) -> dict:
    name = str(p.get("bucket") or p.get("name") or "")
    key = str(p.get("key") or "")
    body = base64.b64decode(p.get("body_b64") or "")
    ct = str(p.get("content_type") or "application/octet-stream")
    r = s3.dispatch(OBJ, "PUT", f"/{name}/{key}", headers={"content-type": ct}, body=body)
    if r.status != 200:
        return {"ok": False, "code": _s3_code(r.body), "status": r.status}
    return {"ok": True, "key": key, "etag": r.headers.get("ETag", ""), "size": len(body)}


def s3_get_object(p: dict) -> dict:
    name = str(p.get("bucket") or p.get("name") or "")
    key = str(p.get("key") or "")
    r = s3.dispatch(OBJ, "GET", f"/{name}/{key}")
    if r.status not in (200, 206):
        return {"ok": False, "code": _s3_code(r.body), "status": r.status}
    return {"ok": True, "key": key, "body_b64": base64.b64encode(r.body or b"").decode(),
            "content_type": r.headers.get("Content-Type", ""),
            "etag": r.headers.get("ETag", ""), "size": len(r.body or b"")}


def s3_delete_object(p: dict) -> dict:
    name = str(p.get("bucket") or p.get("name") or "")
    key = str(p.get("key") or "")
    r = s3.dispatch(OBJ, "DELETE", f"/{name}/{key}")
    return {"ok": r.status in (200, 204), "key": key}


# ── DynamoDB ───────────────────────────────────────────────────────────────
def _table_view(name: str) -> dict:
    t = DDB.get_table(name) or {}
    return {"table_name": name, "name": name,
            "partition_key_name": t.get("partition_key_name", "id"),
            "partition_key_type": t.get("partition_key_type", "S"),
            "sort_key_name": t.get("sort_key_name", ""),
            "billing_mode": t.get("billing_mode", "PAY_PER_REQUEST"),
            "item_count": len(t.get("items", {})),
            "table_status": t.get("table_status", "ACTIVE"),
            "table_arn": t.get("table_arn", "")}


def _ddb_err(r) -> dict:
    return {"ok": False, "code": r.body.get("__type", "Error"), "message": r.body.get("message", "")}


def ddb_create_table(p: dict) -> dict:
    name = str(p.get("name") or p.get("TableName") or "").strip()
    pk = str(p.get("partition_key") or p.get("partition_key_name") or "id").strip() or "id"
    sk = str(p.get("sort_key") or p.get("sort_key_name") or "").strip()
    billing = str(p.get("billing_mode") or "PAY_PER_REQUEST")
    payload = {"TableName": name, "BillingMode": billing,
               "AttributeDefinitions": [{"AttributeName": pk, "AttributeType": "S"}],
               "KeySchema": [{"AttributeName": pk, "KeyType": "HASH"}]}
    if sk:
        payload["AttributeDefinitions"].append({"AttributeName": sk, "AttributeType": "S"})
        payload["KeySchema"].append({"AttributeName": sk, "KeyType": "RANGE"})
    r = ddb.dispatch(DDB, "DynamoDB_20120810.CreateTable", payload)
    if r.status != 200:
        return _ddb_err(r)
    return {"ok": True, **_table_view(name)}


def ddb_list_tables(p: dict | None = None) -> dict:
    return {"ok": True, "tables": [_table_view(n) for n in DDB.table_names()]}


def ddb_get_table(p: dict) -> dict:
    name = str(p.get("table") or p.get("name") or "")
    if not DDB.table_exists(name):
        return {"ok": False, "code": "ResourceNotFoundException", "name": name}
    return {"ok": True, **_table_view(name)}


def ddb_delete_table(p: dict) -> dict:
    name = str(p.get("table") or p.get("name") or "")
    r = ddb.dispatch(DDB, "DynamoDB_20120810.DeleteTable", {"TableName": name})
    if r.status != 200:
        return _ddb_err(r)
    return {"ok": True, "name": name}


def _looks_typed(item: dict) -> bool:
    return bool(item) and all(ddb._is_typed_value(v) for v in item.values())


def ddb_put_item(p: dict) -> dict:
    name = str(p.get("table") or p.get("name") or "")
    item = p.get("item") or {}
    # Console may post a plain native item ({"id":"u1","age":30}); the native wire
    # wants typed values. Wrap plain values, pass already-typed items through.
    typed = item if _looks_typed(item) else {k: ddb.native_to_json(v) for k, v in item.items()}
    r = ddb.dispatch(DDB, "DynamoDB_20120810.PutItem", {"TableName": name, "Item": typed})
    if r.status != 200:
        return _ddb_err(r)
    return {"ok": True}


def ddb_list_items(p: dict) -> dict:
    name = str(p.get("table") or p.get("name") or "")
    t = DDB.get_table(name)
    if t is None:
        return {"ok": False, "code": "ResourceNotFoundException", "name": name}
    items = [copy.deepcopy(rec.get("item", {})) for rec in t.get("items", {}).values()]
    return {"ok": True, "items": items}


def _scan_query_params(p: dict) -> dict:
    # The console posts the query body either nested under `params` (SW tuple) or
    # flat. The core's filters accept the console's snake_case shape directly.
    return p.get("params") if isinstance(p.get("params"), dict) else p


def ddb_query(p: dict) -> dict:
    name = str(p.get("table") or p.get("name") or "")
    t = ddb._find_table(DDB, name)
    if t is None:
        return {"ok": False, "code": "ResourceNotFoundException", "name": name}
    matched, scanned = ddb._query_filter(t, _scan_query_params(p))
    return {"ok": True, "items": [copy.deepcopy(r.get("item", {})) for r in matched],
            "count": len(matched), "scanned_count": scanned}


def ddb_scan(p: dict) -> dict:
    name = str(p.get("table") or p.get("name") or "")
    t = ddb._find_table(DDB, name)
    if t is None:
        return {"ok": False, "code": "ResourceNotFoundException", "name": name}
    matched, scanned = ddb._scan_filter(t, _scan_query_params(p))
    return {"ok": True, "items": [copy.deepcopy(r.get("item", {})) for r in matched],
            "count": len(matched), "scanned_count": scanned}


# ── KMS (JSON wire — core/kms_core.py) ──────────────────────────────────────
def _kms_alias_for(key_id: str) -> str:
    for alias, kid in KMS.aliases.items():
        if kid == key_id:
            return alias
    return ""


def _kms_key_row(key_id: str) -> dict:
    md = KMS.get_key(key_id) or {}
    return {"key_id": key_id, "name": key_id, "alias": _kms_alias_for(key_id),
            "key_spec": md.get("KeySpec", "SYMMETRIC_DEFAULT"),
            "key_usage": md.get("KeyUsage", "ENCRYPT_DECRYPT"),
            "state": md.get("KeyState", "Enabled"),
            "created": _iso(md.get("CreationDate")),
            "arn": f"arn:aws:kms:{REGION}:{KMS.account_id}:key/{key_id}"}


def kms_list_keys(p=None):
    return {"ok": True, "value": [_kms_key_row(k) for k in KMS.key_ids()]}


def kms_create_key(p):
    spec = str(p.get("key_spec") or "SYMMETRIC_DEFAULT")
    r = kms.dispatch(KMS, "TrentService.CreateKey", {"KeySpec": spec})
    if r.status != 200:
        return {"ok": False, "code": r.body.get("__type", "Error")}
    key_id = r.body["KeyMetadata"]["KeyId"]
    alias = str(p.get("name") or "").strip()
    if alias:
        if not alias.startswith("alias/"):
            alias = "alias/" + alias
        kms.dispatch(KMS, "TrentService.CreateAlias", {"AliasName": alias, "TargetKeyId": key_id})
    return {"ok": True, **_kms_key_row(key_id)}


def kms_get_key(p):
    ref = str(p.get("name") or p.get("key_id") or "")
    r = kms.dispatch(KMS, "TrentService.DescribeKey", {"KeyId": ref})
    if r.status != 200:
        return {"ok": False, "code": r.body.get("__type", "NotFoundException")}
    return {"ok": True, **_kms_key_row(r.body["KeyMetadata"]["KeyId"])}


def kms_delete_key(p):
    ref = str(p.get("name") or p.get("key_id") or "")
    r = kms.dispatch(KMS, "TrentService.ScheduleKeyDeletion", {"KeyId": ref, "PendingWindowInDays": 7})
    return {"ok": r.status == 200, "name": ref, "code": r.body.get("__type") if r.status != 200 else None}


def kms_list_aliases(p=None):
    r = kms.dispatch(KMS, "TrentService.ListAliases", {})
    return {"ok": True, "value": r.body.get("Aliases", []), "aliases": r.body.get("Aliases", [])}


# ── Secrets Manager (JSON wire — core/secrets_core.py) ──────────────────────
def _secret_row(meta: dict) -> dict:
    return {"name": meta.get("Name", ""), "arn": meta.get("ARN", ""),
            "secret_type": "SecretString", "last_rotated": "", "next_rotation": "",
            "kms_key_id": "alias/aws/secretsmanager"}


def secrets_list(p=None):
    r = secrets.dispatch(SEC, "secretsmanager.ListSecrets", {})
    return {"ok": True, "value": [_secret_row(s) for s in r.body.get("SecretList", [])]}


def secrets_create(p):
    name = str(p.get("name") or "").strip()
    value = p.get("value")
    body = {"Name": name}
    if value is not None:
        body["SecretString"] = str(value)
    r = secrets.dispatch(SEC, "secretsmanager.CreateSecret", body)
    if r.status != 200:
        return {"ok": False, "code": r.body.get("__type", "Error"), "message": r.body.get("message", "")}
    return {"ok": True, "name": name, "arn": r.body.get("ARN", "")}


def secrets_get(p):
    name = str(p.get("name") or p.get("SecretId") or "")
    r = secrets.dispatch(SEC, "secretsmanager.DescribeSecret", {"SecretId": name})
    if r.status != 200:
        return {"ok": False, "code": r.body.get("__type", "ResourceNotFoundException")}
    return {"ok": True, **_secret_row(r.body)}


def secrets_delete(p):
    name = str(p.get("name") or p.get("SecretId") or "")
    r = secrets.dispatch(SEC, "secretsmanager.DeleteSecret",
                         {"SecretId": name, "ForceDeleteWithoutRecovery": True})
    return {"ok": r.status == 200, "name": name}


# ── SQS (JSON wire — core/sqs_core.py) ──────────────────────────────────────
def _queue_row(q: dict) -> dict:
    live = [m for m in q.get("messages", []) if not m.get("deleted")]
    return {"queue_name": q["queue_name"], "name": q["queue_name"],
            "queue_type": "standard", "queue_url": q["queue_url"],
            "queue_arn": q["queue_arn"], "message_count": len(live)}


def sqs_list_queues(p=None):
    return {"ok": True, "queues": [_queue_row(MSG.get_queue(n)) for n in MSG.queue_names()]}


def sqs_create_queue(p):
    name = str(p.get("name") or "").strip()
    r = sqs.dispatch(MSG, "AmazonSQS.CreateQueue", {"QueueName": name})
    if r.status != 200:
        return {"ok": False, "code": r.body.get("__type", "Error")}
    return {"ok": True, **_queue_row(MSG.get_queue(name))}


def sqs_get_queue(p):
    name = str(p.get("name") or "")
    q = MSG.get_queue(name)
    if not q:
        return {"ok": False, "code": "QueueDoesNotExist", "name": name}
    return {"ok": True, **_queue_row(q)}


def sqs_delete_queue(p):
    name = str(p.get("name") or "")
    q = MSG.get_queue(name)
    if not q:
        return {"ok": False, "code": "QueueDoesNotExist", "name": name}
    sqs.dispatch(MSG, "AmazonSQS.DeleteQueue", {"QueueUrl": q["queue_url"]})
    return {"ok": True, "name": name}


def _queue_url(name):
    q = MSG.get_queue(name)
    return q["queue_url"] if q else None


def sqs_send(p):
    url = _queue_url(str(p.get("name") or ""))
    if not url:
        return {"ok": False, "code": "QueueDoesNotExist"}
    body = p.get("MessageBody")
    if body is None:
        body = p.get("body") if p.get("body") is not None else p.get("message", "")
    r = sqs.dispatch(MSG, "AmazonSQS.SendMessage", {"QueueUrl": url, "MessageBody": str(body)})
    if r.status != 200:
        return {"ok": False, "code": r.body.get("__type", "Error")}
    return {"ok": True, "message_id": r.body.get("MessageId"), "md5": r.body.get("MD5OfMessageBody")}


def sqs_receive(p):
    url = _queue_url(str(p.get("name") or ""))
    if not url:
        return {"ok": False, "code": "QueueDoesNotExist"}
    max_n = int(p.get("MaxNumberOfMessages") or p.get("max") or 10)
    r = sqs.dispatch(MSG, "AmazonSQS.ReceiveMessage", {"QueueUrl": url, "MaxNumberOfMessages": max_n})
    return {"ok": True, "messages": r.body.get("Messages", [])}


def sqs_purge(p):
    url = _queue_url(str(p.get("name") or ""))
    if not url:
        return {"ok": False, "code": "QueueDoesNotExist"}
    sqs.dispatch(MSG, "AmazonSQS.PurgeQueue", {"QueueUrl": url})
    return {"ok": True}


# ── IAM (XML wire — dispatch writes, read store for views) ──────────────────
def _iam_user_row(u): return {"user_name": u["user_name"], "user_id": u["user_id"],
                              "created": u["created"], "arn": u["arn"]}
def _iam_role_row(r): return {"role_name": r["role_name"], "role_id": r["role_id"],
                              "created": r["created"], "arn": r["arn"]}
def _iam_policy_row(p): return {"policy_name": p["policy_name"], "arn": p["arn"],
                               "attachable": True, "created": p["created"]}
def _iam_group_row(g): return {"group_name": g["group_name"], "group_id": g["group_id"],
                               "created": g["created"], "arn": g["arn"]}


def iam_list_users(p=None):
    return {"ok": True, "users": [_iam_user_row(IAM.users[n]) for n in sorted(IAM.users)]}


def iam_list_roles(p=None):
    return {"ok": True, "roles": [_iam_role_row(IAM.roles[n]) for n in sorted(IAM.roles)]}


def iam_list_policies(p=None):
    return {"ok": True, "policies": [_iam_policy_row(IAM.policies[a]) for a in sorted(IAM.policies)]}


def iam_list_groups(p=None):
    return {"ok": True, "groups": [_iam_group_row(IAM.groups[n]) for n in sorted(IAM.groups)]}


def iam_list_attachments(p=None):
    out = []
    for n, u in IAM.users.items():
        for arn in u["attached_policies"]:
            out.append({"target_type": "user", "target": n, "policy_arn": arn})
    for n, r in IAM.roles.items():
        for arn in r["attached_policies"]:
            out.append({"target_type": "role", "target": n, "policy_arn": arn})
    for n, g in IAM.groups.items():
        for arn in g["attached_policies"]:
            out.append({"target_type": "group", "target": n, "policy_arn": arn})
    return {"ok": True, "attachments": out, "value": out}


def iam_create_user(p):
    name = str(p.get("name") or p.get("user_name") or "").strip()
    r = iam.dispatch(IAM, {"Action": "CreateUser", "UserName": name})
    if r.status != 200:
        return {"ok": False, "code": _xml_code(r.body)}
    return {"ok": True, **_iam_user_row(IAM.get_user(name))}


def iam_delete_user(p):
    name = str(p.get("name") or "")
    r = iam.dispatch(IAM, {"Action": "DeleteUser", "UserName": name})
    return {"ok": r.status == 200, "name": name, "code": None if r.status == 200 else _xml_code(r.body)}


def iam_delete_role(p):
    name = str(p.get("name") or "")
    r = iam.dispatch(IAM, {"Action": "DeleteRole", "RoleName": name})
    return {"ok": r.status == 200, "name": name}


def iam_delete_policy(p):
    name = str(p.get("name") or "")
    arn = name if name.startswith("arn:") else f"arn:aws:iam::{IAM.account_id}:policy/{name}"
    r = iam.dispatch(IAM, {"Action": "DeletePolicy", "PolicyArn": arn})
    return {"ok": r.status == 200, "name": name}


# ── RDS (XML wire — dispatch writes, read store for views) ──────────────────
def _rds_row(db: dict) -> dict:
    return {"db_instance_identifier": db["db_instance_identifier"], "name": db["db_instance_identifier"],
            "engine": db.get("engine", "postgres"), "db_instance_class": db.get("db_instance_class", ""),
            "status": db.get("db_instance_status", "available"),
            "endpoint_address": db.get("endpoint_address", ""), "endpoint_port": db.get("endpoint_port", 5432),
            "engine_version": db.get("engine_version", ""), "allocated_storage": db.get("allocated_storage", 20),
            "master_username": db.get("master_username", "admin"), "db_instance_arn": db.get("db_instance_arn", "")}


def rds_list(p=None):
    return {"ok": True, "databases": [_rds_row(RDB.get_instance(i)) for i in RDB.instance_ids()]}


def rds_create(p):
    name = str(p.get("name") or "").strip()
    r = rds.dispatch(RDB, {"Action": "CreateDBInstance", "DBInstanceIdentifier": name,
                           "Engine": str(p.get("engine") or "postgres"),
                           "DBInstanceClass": str(p.get("instance_class") or "db.t3.micro"),
                           "MasterUsername": str(p.get("master_username") or "admin")})
    if r.status != 200:
        return {"ok": False, "code": _xml_code(r.body)}
    return {"ok": True, **_rds_row(RDB.get_instance(name))}


def rds_get(p):
    name = str(p.get("name") or "")
    db = RDB.get_instance(name)
    if not db:
        return {"ok": False, "code": "DBInstanceNotFound", "name": name}
    return {"ok": True, **_rds_row(db)}


def _rds_action(name, action):
    r = rds.dispatch(RDB, {"Action": action, "DBInstanceIdentifier": name})
    if r.status != 200:
        return {"ok": False, "code": _xml_code(r.body), "name": name}
    db = RDB.get_instance(name)
    return {"ok": True, **(_rds_row(db) if db else {"name": name})}


def rds_delete(p):
    name = str(p.get("name") or "")
    r = rds.dispatch(RDB, {"Action": "DeleteDBInstance", "DBInstanceIdentifier": name})
    if r.status != 200:
        return {"ok": False, "code": _xml_code(r.body), "name": name}
    return {"ok": True, "name": name, "status": "deleting"}  # instance is now gone


def rds_start(p):  return _rds_action(str(p.get("name") or ""), "StartDBInstance")
def rds_stop(p):   return _rds_action(str(p.get("name") or ""), "StopDBInstance")
def rds_reboot(p): return _rds_action(str(p.get("name") or ""), "RebootDBInstance")


def rds_modify(p):
    name = str(p.get("name") or "")
    body = {"Action": "ModifyDBInstance", "DBInstanceIdentifier": name}
    if p.get("instance_class"):
        body["DBInstanceClass"] = str(p["instance_class"])
    if p.get("allocated_storage"):
        body["AllocatedStorage"] = str(p["allocated_storage"])
    r = rds.dispatch(RDB, body)
    if r.status != 200:
        return {"ok": False, "code": _xml_code(r.body)}
    return {"ok": True, **_rds_row(RDB.get_instance(name))}


def rds_snapshots(p=None):
    snaps = [RDB.get_snapshot(s) for s in RDB.snapshot_ids()]
    return {"ok": True, "snapshots": [{"snapshot_id": s["db_snapshot_identifier"],
            "db_instance": s["db_instance_identifier"], "status": s["status"],
            "type": s.get("snapshot_type", "manual"), "created": s.get("created", "")} for s in snaps]}
