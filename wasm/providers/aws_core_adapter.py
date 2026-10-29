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
from core import cloudwatch_core as cw

# Shared registry (Fix #2): the console adapter and the native-wire relay
# (AwsWireRouter via stores=) draw from ONE store set, so console-created resources
# are visible to the SDK/relay in the same context (and vice-versa).
from core import nano_registry as _reg
_R = _reg.get()
OBJ = _R["s3"]
DDB = _R["ddb"]
KMS = _R["kms"]
SEC = _R["sec"]
RDB = _R["rds"]
IAM = _R["iam"]
MSG = _R["msg"]
CW = _R["cw"]
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
            "versioning": ver, "versioning_enabled": ver == "Enabled",
            "arn": f"arn:aws:s3:::{name}", "access": DET.s3_access_summary(b), "tags": dict(b.get("tags") or {})}


def s3_put_tagging(p: dict) -> dict:
    """PutBucketTagging — the bucket's Tags tab saves its whole tag set."""
    name = str(p.get("bucket") or "")
    if name not in OBJ.buckets:
        return _no_bucket(name)
    tags = p.get("tags") or {}
    if not isinstance(tags, dict) or len(tags) > 50:
        return _det_err(DET.DetailError("InvalidTag", "A bucket can have up to 50 tags."))
    OBJ.buckets[name]["tags"] = {str(k): str(v) for k, v in tags.items() if str(k)}
    return {"ok": True, "name": name, "tags": OBJ.buckets[name]["tags"]}


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


def s3_get_versioning(p: dict) -> dict:
    name = str(p.get("bucket") or p.get("name") or "")
    if not OBJ.bucket_exists(name):
        return _no_bucket(name)
    return {"ok": True, "name": name, "versioning": OBJ.versioning_status(name)}


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
    name = str(p.get("name") or p.get("TableName") or p.get("table_name") or "").strip()
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
    try:
        DET.ddb_check_delete(ddb._find_table(DDB, name))   # deletion protection
    except DET.DetailError as e:
        return _det_err(e)
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
            "description": md.get("Description", ""),
            "arn": f"arn:aws:kms:{REGION}:{KMS.account_id}:key/{key_id}"}


def kms_list_keys(p=None):
    return {"ok": True, "value": [_kms_key_row(k) for k in KMS.key_ids()]}


def kms_create_key(p):
    spec = str(p.get("key_spec") or "SYMMETRIC_DEFAULT")
    r = kms.dispatch(KMS, "TrentService.CreateKey", {"KeySpec": spec, "Description": str(p.get("description") or "")})
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
                              "created": u["created"], "arn": u["arn"], "path": u.get("path", "/"),
                              "policies": list(u.get("attached_policies", [])),
                              "groups": [g for g, grp in IAM.groups.items() if u["user_name"] in grp.get("members", [])]}
def _iam_role_row(r): return {"role_name": r["role_name"], "role_id": r["role_id"],
                              "created": r["created"], "arn": r["arn"], "path": r.get("path", "/"),
                              "policies": list(r.get("attached_policies", []))}
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


def _iam_detail(kind, name, row):
    """Detail record for the IAM resource page: the list row plus what the
    detail tabs show (attached policies, group membership)."""
    return {"ok": True, **row, "path": "/", "attached_policies": list(kind.get("attached_policies", [])),
            "policies": list(kind.get("attached_policies", []))}


def iam_get_user(p):
    name = str(p.get("name") or "")
    u = IAM.get_user(name)
    if not u:
        return {"ok": False, "code": "NoSuchEntity", "name": name}
    out = _iam_detail(u, name, _iam_user_row(u))
    out["groups"] = sorted(g for g, rec in IAM.groups.items() if name in rec.get("members", []))
    return out


def iam_get_role(p):
    name = str(p.get("name") or "")
    r = IAM.get_role(name)
    if not r:
        return {"ok": False, "code": "NoSuchEntity", "name": name}
    return _iam_detail(r, name, _iam_role_row(r))


def iam_get_group(p):
    name = str(p.get("name") or "")
    g = IAM.get_group(name)
    if not g:
        return {"ok": False, "code": "NoSuchEntity", "name": name}
    out = _iam_detail(g, name, _iam_group_row(g))
    out["members"] = list(g.get("members", []))
    return out


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
    db = RDB.get_instance(name)
    DET.rds_ensure(db, ec2_net())        # placed in the default VPC, default backup/maintenance settings
    DET.rds_record_event(db, "CreateDBInstance")
    return {"ok": True, **_rds_row(db)}


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
    if db:
        DET.rds_record_event(db, action)
    return {"ok": True, **(_rds_row(db) if db else {"name": name})}


def rds_delete(p):
    name = str(p.get("name") or "")
    db = RDB.get_instance(name)
    if db:
        try:
            DET.rds_check_delete(db)     # deletion protection
        except DET.DetailError as e:
            return _det_err(e)
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


# ── CloudWatch (alarms console; native wire in core/cloudwatch_core.py) ─────
def cw_list(p=None):
    return cw.console_list(CW)


def cw_create(p):
    return cw.console_create(CW, p or {})


def cw_get(p):
    return cw.console_get(CW, str(p.get("name") or ""))


def cw_delete(p):
    return cw.console_delete(CW, str(p.get("name") or ""))


# ── Resource-detail tabs (core/aws_console_detail.py — the same engine the offline
#    routes/aws_console_detail.py runs). EC2 instances live in the generic catalog
#    store (backends.resources, service "ec2"); their network is the VPC core model.
from core import aws_console_detail as DET

_EXTRAS = _R["extras"]


def _det_err(e):
    return {"ok": False, "code": e.code, "message": e.message,
            "__http": {"status": e.status, "body": {"detail": {"code": e.code, "message": e.message}}}}


def ec2_net():
    return DET.CoreNet(_R["vpc_net"])


def _iam_role_lookup(name):
    r = IAM.roles.get(name)
    return {"role_name": name, "arn": r.get("arn")} if r else None


def ec2_apply_launch(body: dict) -> dict:
    """RunInstances placement for a console launch (called by the registry's EC2 Create)."""
    rec = dict(body or {})
    DET.apply_launch(rec, body, ec2_net(), _iam_role_lookup)
    return rec


def _ec2_rec(b, a, p):
    rec = b.resources.get("aws", a, "ec2", str(p.get("name") or p.get("id") or ""))
    if rec is not None:
        try:
            DET.ensure_instance_model(rec, ec2_net())
        except DET.DetailError:
            pass
        rec.setdefault("owner_id", IAM.account_id)
    return rec


def _nf(p):
    iid = str(p.get("name") or "")
    return {"ok": False, "code": "InvalidInstanceID.NotFound",
            "__http": {"status": 404, "body": {"detail": {"code": "InvalidInstanceID.NotFound",
                                                          "message": f"The instance ID '{iid}' does not exist"}}}}


def ec2_detail(b, a, p):
    rec = _ec2_rec(b, a, p)
    if rec is None:
        return _nf(p)
    tab = p.get("tab")
    if tab == "details":
        return {"ok": True, **DET.details_view(rec)}
    if tab == "network-interfaces":
        return {"ok": True, "network_interfaces": DET.network_interfaces_view(rec, ec2_net())}
    if tab == "security":
        return {"ok": True, **DET.security_view(rec, ec2_net())}
    if tab == "storage":
        vols = [v for v in (_EXTRAS.items.get("ec2/volumes") or {}).values()
                if any(x.get("instance_id") == rec.get("instance_id") for x in v.get("attachments") or [])] \
            if isinstance(_EXTRAS.items.get("ec2/volumes"), dict) else []
        return {"ok": True, **DET.storage_view(rec, vols)}
    if tab == "user-data":
        return {"ok": True, "instance_id": rec.get("instance_id"), "user_data": rec.get("user_data") or "",
                "state": rec.get("state", "")}
    if tab == "iam-instance-profile":
        return {"ok": True, "instance_id": rec.get("instance_id"), "iam_instance_profile": rec.get("iam_instance_profile") or None,
                "roles": sorted(IAM.roles)}
    if tab == "console-output":
        # Nano runs no instance OS, so nothing has been written to the console.
        return {"ok": True, **DET.console_output(rec, "")}
    return {"ok": False, "code": "UnknownTab"}


def ec2_modify(b, a, p):
    """ModifyInstanceAttribute / user data / IAM instance profile writes."""
    rec = _ec2_rec(b, a, p)
    if rec is None:
        return _nf(p)
    body = p.get("body") or {}
    try:
        what = p.get("tab")
        if what == "attributes":
            return {"ok": True, **DET.modify_attributes(rec, body)}
        if what == "user-data":
            return {"ok": True, **DET.set_user_data(rec, body.get("user_data", ""))}
        if what == "iam-instance-profile":
            if p.get("method") == "DELETE":
                return {"ok": True, "instance_id": rec.get("instance_id"), "iam_instance_profile": None,
                        "disassociated": DET.disassociate_iam_instance_profile(rec)}
            return {"ok": True, "instance_id": rec.get("instance_id"),
                    "iam_instance_profile": DET.associate_iam_instance_profile(rec, body.get("name", ""), _iam_role_lookup, IAM.account_id)}
    except DET.DetailError as e:
        return _det_err(e)
    return {"ok": False, "code": "UnknownTab"}


def ec2_guard(rec: dict, operation: str):
    """Termination / stop protection + state-transition reason for lifecycle ops."""
    try:
        if operation == "Terminate":
            DET.check_terminate(rec)
        elif operation == "Stop":
            DET.check_stop(rec)
    except DET.DetailError as e:
        return _det_err(e)
    DET.record_state_change(rec, {"Terminate": "terminated", "Stop": "stopped", "Start": "running"}.get(operation, ""))
    return None


def ec2_serial_access(p):
    cfg = _EXTRAS.cfg.setdefault("ec2/account-attributes", {})
    if p.get("method") == "PUT":
        cfg["serial_console_access"] = (p.get("body") or {}).get("enabled") in DET._TRUE
    return {"ok": True, "serial_console_access_enabled": bool(cfg.get("serial_console_access"))}


def iam_principals() -> list:
    """Nano IAM users / groups / roles with their attached + inline policy documents."""
    def docs(rec):
        out = []
        for arn in rec.get("attached_policies") or []:
            pol = IAM.policies.get(arn)
            if pol:
                out.append({"name": pol.get("policy_name", arn), "arn": arn, "document": pol.get("document")})
        for name, doc in (rec.get("inline_policies") or {}).items():
            out.append({"name": name + " (inline)", "arn": "", "document": doc})
        return out
    out = []
    for kind, coll in (("User", IAM.users), ("Group", IAM.groups), ("Role", IAM.roles)):
        for name, rec in coll.items():
            out.append({"type": kind, "name": name, "arn": rec.get("arn", ""), "policies": docs(rec)})
    return out


def resource_access(p):
    arn = str(p.get("arn") or "")
    return {"ok": True, "resource_arn": arn, "statements": DET.resource_access(iam_principals(), arn, str(p.get("service") or ""))}


# ── S3 bucket detail tabs (core/aws_console_detail.py, same engine as offline) ──
def _no_bucket(name):
    return {"ok": False, "code": "NoSuchBucket",
            "__http": {"status": 404, "body": {"detail": {"code": "NoSuchBucket", "message": "The specified bucket does not exist"}}}}


def s3_bucket_config(p):
    name = str(p.get("bucket") or "")
    b = OBJ.buckets.get(name)
    if b is None:
        return _no_bucket(name)
    kind, method = str(p.get("kind") or ""), p.get("method") or "GET"
    try:
        if method == "PUT":
            DET.s3_put_bucket_config(b, name, kind, p.get("value"))
        elif method == "DELETE":
            if kind not in ("lifecycle", "cors", "policy"):
                raise DET.DetailError("InvalidRequest", f"{kind} cannot be deleted.")
            DET.s3_put_bucket_config(b, name, kind, [] if kind != "policy" else "")
        return {"ok": True, "bucket": name, "kind": kind, "value": DET.s3_bucket_config(b, kind)}
    except DET.DetailError as e:
        return _det_err(e)


def s3_list_versions(p):
    name = str(p.get("bucket") or "")
    if name not in OBJ.buckets:
        return _no_bucket(name)
    v = DET.s3_versions(OBJ.objects.get(name) or {}, str(p.get("prefix") or ""))
    return {"ok": True, "bucket": name, "versions": v, "count": len(v)}


def s3_notifications(p):
    name = str(p.get("bucket") or "")
    b = OBJ.buckets.get(name)
    if b is None:
        return _no_bucket(name)
    try:
        if p.get("method") == "PUT":
            DET.s3_put_notifications(b, p.get("body") or {})
    except DET.DetailError as e:
        return _det_err(e)
    n = {**DET.s3_notifications_default(), **(b.get("notifications") or {})}
    return {"ok": True, "bucket": name, **n}


# ── RDS DB instance tabs (core/aws_console_detail.py) ───────────────────────
def _rds_db(p):
    name = str(p.get("name") or "")
    db = RDB.get_instance(name)
    if db is not None:
        DET.rds_ensure(db, ec2_net())
    return db


def _rds_nf(p):
    return {"ok": False, "code": "DBInstanceNotFound",
            "__http": {"status": 404, "body": {"detail": {"code": "DBInstanceNotFound",
                                                          "message": f"DBInstance {p.get('name')} not found."}}}}


def rds_detail(p):
    db = _rds_db(p)
    if db is None:
        return _rds_nf(p)
    tab = p.get("tab")
    if tab == "pending-maintenance":
        return {"ok": True, "db_instance_identifier": db["db_instance_identifier"],
                "pending_maintenance_actions": DET.rds_pending_maintenance(db)}
    if tab == "performance-insights":
        return {"ok": True, **DET.rds_performance_insights(db)}
    if tab in ("connectivity", "subnet-group"):
        return {"ok": True, **DET.rds_connectivity(db, ec2_net(), {"db_subnet_group_name": "default"})}
    if tab == "events":
        return {"ok": True, "db_instance_identifier": db["db_instance_identifier"], "events": DET.rds_events(db)}
    return {"ok": True, **DET.rds_configuration(db)}


def rds_modify_configuration(p):
    db = _rds_db(p)
    if db is None:
        return _rds_nf(p)
    try:
        out = DET.rds_modify(db, p.get("body") or {})
    except DET.DetailError as e:
        return _det_err(e)
    except (ValueError, TypeError) as e:
        return _det_err(DET.DetailError("InvalidParameterValue", str(e)))
    RDB.persist()
    return {"ok": True, **out}


# ── DynamoDB table tabs (core/aws_console_detail.py) ────────────────────────
def ddb_table_section(p):
    name = str(p.get("table") or "")
    t = ddb._find_table(DDB, name)
    if t is None:
        return {"ok": False, "code": "ResourceNotFoundException",
                "__http": {"status": 404, "body": {"detail": {"code": "ResourceNotFoundException",
                                                              "message": f"Requested resource not found: Table: {name} not found"}}}}
    section = str(p.get("section") or "")
    try:
        if p.get("method") == "PUT":
            out = DET.ddb_update_section(t, section, p.get("body") or {})
            DDB.persist()
        else:
            out = DET.ddb_section(t, section)
    except DET.DetailError as e:
        return _det_err(e)
    except (TypeError, ValueError) as e:
        return _det_err(DET.DetailError("ValidationException", str(e)))
    return {"ok": True, "table_name": name, "section": section, **out}


# ── Lambda function tabs (core/aws_console_detail.py) ───────────────────────
def _nano_role_info(name):
    r = IAM.roles.get(name)
    if not r:
        return None
    return {"policies": [a.rsplit("/", 1)[-1] for a in r.get("attached_policies") or []] + list((r.get("inline_policies") or {}).keys()),
            "trust": r.get("assume_role_policy_document")}


def lambda_section(p):
    name = str(p.get("name") or "")
    fn = (getattr(_R["compute"], "_lambda_functions", None) or {}).get(name)
    if fn is None:
        return {"ok": False, "code": "ResourceNotFoundException",
                "__http": {"status": 404, "body": {"detail": {"code": "ResourceNotFoundException", "message": f"Function not found: {name}"}}}}
    section = str(p.get("section") or "")
    try:
        if p.get("method") == "PUT":
            out = DET.lambda_update_section(fn, section, p.get("body") or {}, _nano_role_info)
        else:
            out = DET.lambda_section(fn, section, _nano_role_info)
    except DET.DetailError as e:
        return _det_err(e)
    except (TypeError, ValueError) as e:
        return _det_err(DET.DetailError("InvalidParameterValueException", str(e)))
    return {"ok": True, "function_name": name, "section": section, **out}


# ── IAM account tabs (core/aws_console_detail.py). Stored as public attrs on the
#    IAM store so nano_persist snapshots them with the users/roles/policies. ──
def _iam_attr(name, default):
    if not isinstance(getattr(IAM, name, None), type(default)):
        setattr(IAM, name, default)
    return getattr(IAM, name)


def _nano_shared_resources():
    out = []
    for name, b in OBJ.buckets.items():
        if isinstance(b, dict) and b.get("policy"):
            out.append({"type": "AWS::S3::Bucket", "arn": f"arn:aws:s3:::{name}", "policy": b["policy"]})
    for fn in (getattr(_R["compute"], "_lambda_functions", None) or {}).values():
        if fn.get("permissions"):
            out.append({"type": "AWS::Lambda::Function", "arn": fn.get("arn", ""), "policy": DET.lambda_policy_document(fn)})
    for name, r in IAM.roles.items():
        if r.get("assume_role_policy_document"):
            out.append({"type": "AWS::IAM::Role", "arn": r.get("arn", ""), "policy": r["assume_role_policy_document"]})
    return out


def _iam_view(section):
    acct = IAM.account_id
    if section == "identity-providers":
        return {"ok": True, "identity_providers": DET.iam_identity_providers(_iam_attr("identity_providers", {}), acct)}
    if section == "password-policy":
        return {"ok": True, **DET.iam_password_policy(_iam_attr("account_settings", {}))}
    if section == "access-analyzer":
        an = _iam_attr("access_analyzers", [])
        return {"ok": True, "analyzers": DET.iam_analyzers(an), "findings": DET.access_findings(acct, _nano_shared_resources()) if an else []}
    return _det_err(DET.DetailError("NoSuchEntity", f"Unknown IAM section {section}", 404))


def iam_section(p):
    section, b = str(p.get("section") or ""), p.get("body") or {}
    if p.get("method") == "PUT":
        acct = IAM.account_id
        try:
            if section == "identity-providers":
                store = _iam_attr("identity_providers", {})
                if b.get("action") == "delete":
                    if store.pop(str(b.get("provider_id") or ""), None) is None:
                        raise DET.DetailError("NoSuchEntity", "Identity provider not found.", 404)
                else:
                    DET.iam_create_identity_provider(store, b, acct)
            elif section == "password-policy":
                DET.iam_update_password_policy(_iam_attr("account_settings", {}), b)
            elif section == "access-analyzer":
                an = _iam_attr("access_analyzers", [])
                if b.get("action") == "delete":
                    an[:] = [a for a in an if a["name"] != b.get("name")]
                else:
                    DET.iam_create_analyzer(an, b.get("name"), acct)
        except DET.DetailError as e:
            return _det_err(e)
        except (TypeError, ValueError) as e:
            return _det_err(DET.DetailError("ValidationError", str(e)))
        IAM.persist()
    return _iam_view(section)
