"""S3 object-CRUD core — substrate-independent, faithfully extracted from
routes/aws_s3.py so the SAME logic runs in Pro/Max (FastAPI), Nano (Pyodide),
and tests. NO fastapi / boto3 / socket / subprocess imports → loads under
Pyodide. Persists through the ObjectStore seam (core/object_store.py).

Each operation takes plain inputs (bytes/dicts) and returns an `S3Response`
(status, headers, body) — the native AWS S3 wire shapes (XML errors, ETag,
x-amz-version-id, ListBucketResult, byte-range 206). A thin FastAPI adapter
(Pro/Max) or the service-worker bridge (Nano) maps Request<->S3Response.

Scope: PutObject/GetObject(+range)/HeadObject/DeleteObject/CopyObject,
DeleteObjects, ListObjects V1+V2 (marker / continuation-token / start-after),
ListObjectVersions, multipart (+ListMultipartUploads), object tagging + ACL,
bucket create/delete (name validation, BucketAlreadyOwnedByYou, BucketNotEmpty)
and the bucket sub-resources (versioning, tagging, cors, lifecycle, encryption,
policy, publicAccessBlock, ownershipControls, acl, notification, location,
object-lock). v4 C0: this is now the ONE S3 engine for the offline appliance too,
so every behaviour of the retired routes/aws_s3.py handlers lives here. The core
calls `store.persist()` after every mutation and `store.emit_event()` for each
S3 event (the appliance delivers notifications; Nano/tests no-op).
"""
from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
import zlib
import base64
import re
import urllib.parse
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from xml.etree import ElementTree as ET

from core.object_store import ObjectStore

S3_NS = "http://s3.amazonaws.com/doc/2006-03-01/"


def _strip_xml_decl(s: str) -> str:
    return re.sub(r'^\s*<\?xml[^>]*\?>\s*', '', s)


def _xml_escape(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


@dataclass
class S3Response:
    status: int = 200
    headers: dict = field(default_factory=dict)
    body: bytes = b""
    media_type: str | None = None


# ── primitives (verbatim from routes/aws_s3.py) ───────────────────────────
def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _iso_to_http_date(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%a, %d %b %Y %H:%M:%S GMT")
    except Exception:
        return datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")


def _etag(data: bytes) -> str:
    return f'"{hashlib.md5(data).hexdigest()}"'


def _req_id() -> str:
    return uuid.uuid4().hex.upper()[:16]


def _decode_aws_chunked(body: bytes, headers: dict) -> bytes:
    return _decode_aws_chunked_full(body, headers)[0]


def _decode_aws_chunked_full(body: bytes, headers: dict) -> tuple[bytes, dict]:
    """Strip AWS SDK v2 ``aws-chunked`` framing (see routes/aws_s3.py for the
    full rationale — modern SDKs stream PutObject with chunk-signature headers
    that would corrupt the stored object if kept)."""
    ce = (headers.get("content-encoding") or "").lower()
    sha = headers.get("x-amz-content-sha256", "") or ""
    if "aws-chunked" not in ce and not sha.startswith("STREAMING"):
        return body, {}
    out = bytearray()
    i, n = 0, len(body)
    while i < n:
        j = body.find(b"\r\n", i)
        if j == -1:
            break
        size_field = body[i:j].split(b";", 1)[0].strip()
        i = j + 2
        try:
            size = int(size_field, 16)
        except ValueError:
            break
        if size == 0:
            # trailing headers after the last chunk (x-amz-checksum-*: value)
            trailers = {}
            for line in body[i:].split(b"\r\n"):
                if b":" in line:
                    k, _, v = line.partition(b":")
                    trailers[k.decode("latin-1").strip().lower()] = v.decode("latin-1").strip()
            return bytes(out), trailers
        out += body[i:i + size]
        i += size
        if body[i:i + 2] == b"\r\n":
            i += 2
    return bytes(out), {}


# ── response builders (return S3Response, not FastAPI Response) ────────────
def _amz_headers(extra: dict | None = None) -> dict:
    h = {"x-amz-request-id": _req_id(), "x-amz-id-2": uuid.uuid4().hex}
    if extra:
        h.update(extra)
    return h


def _xml_response(content: str, status: int = 200, extra: dict | None = None) -> S3Response:
    return S3Response(status=status, headers=_amz_headers(extra),
                      body=content.encode(), media_type="application/xml")


def _empty_response(status: int = 204, extra: dict | None = None) -> S3Response:
    return S3Response(status=status, headers=_amz_headers(extra), body=b"")


def _error_xml(code: str, message: str, resource: str = "/", status: int = 400) -> S3Response:
    xml = ('<?xml version="1.0" encoding="UTF-8"?>'
           f"<Error><Code>{code}</Code><Message>{message}</Message>"
           f"<Resource>{resource}</Resource><RequestId>{_req_id()}</RequestId></Error>")
    return _xml_response(xml, status=status)


def _delete_marker_response(resource: str, last_modified: str, status: int = 405) -> S3Response:
    xml = ('<?xml version="1.0" encoding="UTF-8"?>'
           "<Error><Code>MethodNotAllowed</Code>"
           "<Message>The specified version is a delete marker.</Message>"
           f"<Resource>{resource}</Resource><RequestId>{_req_id()}</RequestId></Error>")
    return _xml_response(xml, status=status, extra={
        "x-amz-delete-marker": "true", "Last-Modified": _iso_to_http_date(last_modified)})


# ── versioning + entry helpers (verbatim, but over `store` not globals) ────
def _new_version_id(store: ObjectStore, bucket: str) -> str:
    return "null" if store.versioning_status(bucket) == "Suspended" else uuid.uuid4().hex


def _refresh_object_entry(entry: dict) -> None:
    versions = entry.get("versions", [])
    for idx, v in enumerate(versions):
        v["is_latest"] = idx == 0
    if not versions:
        entry.update({"current_version_id": "", "is_delete_marker": False, "data": b"",
                      "size": 0, "content_type": "application/octet-stream",
                      "last_modified": _now(), "etag": "", "storage_class": "STANDARD",
                      "metadata": {}, "tags": {}})
        return
    cur = versions[0]
    entry.update({
        "current_version_id": cur.get("version_id", "null"),
        "version_id": cur.get("version_id", "null"),
        "is_delete_marker": bool(cur.get("is_delete_marker", False)),
        "data": cur.get("data", b"") if not cur.get("is_delete_marker") else b"",
        "size": int(cur.get("size", 0) or 0),
        "content_type": cur.get("content_type", "application/octet-stream"),
        "last_modified": cur.get("last_modified", _now()),
        "etag": cur.get("etag", ""),
        "storage_class": cur.get("storage_class", "STANDARD"),
        "metadata": copy.deepcopy(cur.get("metadata", {})),
        "tags": copy.deepcopy(cur.get("tags", {})),
    })


def _ensure_object_entry(store: ObjectStore, bucket: str, key: str, create: bool = False) -> dict | None:
    bucket_objects = store.bucket_objects(bucket)
    entry = bucket_objects.get(key)
    if not isinstance(entry, dict):
        if not create:
            return None
        entry = {"versions": []}
        bucket_objects[key] = entry
    if not isinstance(entry.get("versions"), list):
        entry["versions"] = []
    if entry["versions"]:
        _refresh_object_entry(entry)
    return entry


# ── additional checksums (x-amz-checksum-*): CRC32 / CRC32C / CRC64NVME / SHA1 / SHA256 ──────
_CHECKSUM_ALGOS = ("CRC32", "CRC32C", "CRC64NVME", "SHA1", "SHA256")


def _crc_table(poly: int, width: int) -> list:
    t = []
    for n in range(256):
        c = n
        for _ in range(8):
            c = (c >> 1) ^ poly if c & 1 else c >> 1
        t.append(c & ((1 << width) - 1))
    return t


_CRC32C_T = _crc_table(0x82F63B78, 32)
_CRC64NVME_T = _crc_table(0x9A6C9329AC4BC9B5, 64)   # reflected form of 0xAD93D23594C93659


def _crc(table: list, width: int, data: bytes) -> int:
    mask = (1 << width) - 1
    c = mask
    for byte in data:
        c = table[(c ^ byte) & 0xFF] ^ (c >> 8)
    return c ^ mask


def _checksum_value(algo: str, data: bytes) -> str:
    """Base64 of the big-endian checksum, exactly the x-amz-checksum-* wire value."""
    if algo == "CRC32":
        raw = (zlib.crc32(data) & 0xFFFFFFFF).to_bytes(4, "big")
    elif algo == "CRC32C":
        raw = _crc(_CRC32C_T, 32, data).to_bytes(4, "big")
    elif algo == "CRC64NVME":
        raw = _crc(_CRC64NVME_T, 64, data).to_bytes(8, "big")
    elif algo == "SHA1":
        raw = hashlib.sha1(data).digest()
    else:
        raw = hashlib.sha256(data).digest()
    return base64.b64encode(raw).decode()


def _request_checksum(headers: dict, trailers: dict, data: bytes):
    """-> (record | None, error_response | None). A supplied x-amz-checksum-<algo> (header or
    aws-chunked trailer) is VERIFIED against the body (BadDigest on mismatch); a bare
    x-amz-sdk-checksum-algorithm / x-amz-checksum-algorithm asks the server to compute it."""
    for algo in _CHECKSUM_ALGOS:
        want = headers.get(f"x-amz-checksum-{algo.lower()}") or trailers.get(f"x-amz-checksum-{algo.lower()}")
        if want:
            got = _checksum_value(algo, data)
            if want != got:
                return None, _error_xml("BadDigest", f"The {algo} you specified did not match the calculated checksum.", "", 400)
            return {"algorithm": algo, "value": got, "type": "FULL_OBJECT"}, None
    asked = (headers.get("x-amz-sdk-checksum-algorithm") or headers.get("x-amz-checksum-algorithm") or "").upper()
    if asked in _CHECKSUM_ALGOS:
        return {"algorithm": asked, "value": _checksum_value(asked, data), "type": "FULL_OBJECT"}, None
    if asked:
        return None, _error_xml("InvalidRequest", f"Checksum algorithm provided is unsupported. Please try again with any of the valid types: [{', '.join(_CHECKSUM_ALGOS)}]", "", 400)
    return None, None


def _checksum_headers(record: dict | None, headers: dict, always: bool = False) -> dict:
    if not record:
        return {}
    if not always and (headers.get("x-amz-checksum-mode") or "").upper() != "ENABLED":
        return {}
    return {f"x-amz-checksum-{record['algorithm'].lower()}": record["value"],
            "x-amz-checksum-type": record.get("type", "FULL_OBJECT")}


def _make_version_record(*, data: bytes = b"", content_type: str = "application/octet-stream",
                         storage_class: str = "STANDARD", metadata: dict | None = None,
                         tags: dict | None = None, version_id: str | None = None,
                         delete_marker: bool = False, last_modified: str | None = None,
                         etag: str | None = None) -> dict:
    return {
        "version_id": version_id or "null",
        "is_delete_marker": delete_marker,
        "data": b"" if delete_marker else data,
        "size": 0 if delete_marker else len(data),
        "content_type": "application/octet-stream" if delete_marker else content_type,
        "last_modified": last_modified or _now(),
        "etag": etag or ("" if delete_marker else _etag(data)),
        "storage_class": storage_class,
        "metadata": copy.deepcopy(metadata or {}),
        "tags": copy.deepcopy(tags or {}),
    }


def _find_version(entry: dict | None, version_id: str | None) -> dict | None:
    if not entry:
        return None
    versions = entry.get("versions", [])
    if not version_id:
        return versions[0] if versions else None
    for v in versions:
        if str(v.get("version_id")) == str(version_id):
            return v
    return None


def _version_bytes(store: ObjectStore, bucket: str, key: str, version: dict) -> bytes:
    """A version's bytes: inline, else the substrate's external byte store."""
    data = version.get("data")
    if data is None or (data == b"" and int(version.get("size") or 0) > 0):
        data = store.fetch_bytes(bucket, key)
    if isinstance(data, str):
        data = data.encode("utf-8")
    return bytes(data or b"")


def _mirror_current(store: ObjectStore, bucket: str, key: str) -> None:
    """After a version-specific delete: re-sync the external byte store with the
    key's (possibly older) current version, or remove it if none is visible."""
    entry = store.bucket_objects(bucket).get(key)
    cur = (entry or {}).get("versions", [None])[0] if isinstance(entry, dict) and entry.get("versions") else None
    if not cur or cur.get("is_delete_marker"):
        store.mirror_delete(bucket, key)
    else:
        store.mirror_put(bucket, key, _version_bytes(store, bucket, key, cur),
                         content_type=cur.get("content_type", "application/octet-stream"),
                         metadata=cur.get("metadata"))


def _write_object_version(store: ObjectStore, bucket: str, key: str, version: dict,
                          replace_version_id: str | None = None) -> dict:
    if not version.get("is_delete_marker"):
        store.enforce_storage_cap(int(version.get("size") or len(version.get("data") or b"")))
    entry = _ensure_object_entry(store, bucket, key, create=True)
    versions = entry.setdefault("versions", [])
    if replace_version_id == "__overwrite__":
        versions = [version]
    elif replace_version_id is not None:
        for idx, ex in enumerate(versions):
            if str(ex.get("version_id")) == str(replace_version_id):
                versions[idx] = version
                break
        else:
            versions.insert(0, version)
    else:
        versions.insert(0, version)
    entry["versions"] = [copy.deepcopy(v) for v in versions]
    _refresh_object_entry(entry)
    if not version.get("is_delete_marker") and version.get("data") is not None:
        store.mirror_put(bucket, key, version["data"],
                         content_type=version.get("content_type", "application/octet-stream"),
                         metadata=version.get("metadata"))
    return entry


def _delete_version(store: ObjectStore, bucket: str, key: str, version_id: str) -> bool:
    entry = _ensure_object_entry(store, bucket, key, create=False)
    if not entry:
        return False
    versions = entry.get("versions", [])
    for idx, v in enumerate(versions):
        if str(v.get("version_id")) == str(version_id):
            versions.pop(idx)
            if versions:
                _refresh_object_entry(entry)
            else:
                store.bucket_objects(bucket).pop(key, None)
            return True
    return False


def _insert_simple_delete_marker(store: ObjectStore, bucket: str, key: str) -> dict:
    vid = _new_version_id(store, bucket)
    marker = _make_version_record(delete_marker=True, version_id=vid)
    entry = _write_object_version(store, bucket, key, marker)
    store.mirror_delete(bucket, key)   # the external byte store mirrors the CURRENT view
    _replicate_delete_marker(store, bucket, key)
    return entry


# ── bucket naming / tagging / notification helpers (ported from routes/aws_s3.py) ──
_OWNER_XML = "<Owner><ID>simulator</ID><DisplayName>cloudlearn-simulator</DisplayName></Owner>"


def _validate_bucket_name(name: str) -> S3Response | None:
    if len(name) < 3 or len(name) > 63:
        return _error_xml("InvalidBucketName", "Bucket name must be between 3 and 63 characters.", f"/{name}", 400)
    if not re.match(r"^[a-z0-9][a-z0-9\-.]*[a-z0-9]$", name):
        return _error_xml("InvalidBucketName",
                          "Bucket name can contain only lowercase letters, numbers, hyphens, and dots.", f"/{name}", 400)
    return None


def parse_tagging_xml(body: bytes) -> dict:
    tags: dict = {}
    if not body:
        return tags
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return tags
    for tag in root.iter():
        if _local(tag.tag) != "Tag":
            continue
        k = _child_text(tag, "Key")
        if k:
            tags[k] = _child_text(tag, "Value")
    return tags


def build_tagging_xml(tags: dict) -> str:
    inner = "".join(f"<Tag><Key>{_xml_escape(k)}</Key><Value>{_xml_escape(v)}</Value></Tag>"
                    for k, v in (tags or {}).items())
    return f'<?xml version="1.0" encoding="UTF-8"?><Tagging xmlns="{S3_NS}"><TagSet>{inner}</TagSet></Tagging>'


def _local(tag: str) -> str:
    return (tag or "").rsplit("}", 1)[-1]


def _child(elem, name: str):
    for c in list(elem) if elem is not None else []:
        if _local(c.tag) == name:
            return c
    return None


def _children(elem, name: str) -> list:
    return [c for c in list(elem) if _local(c.tag) == name] if elem is not None else []


def _child_text(elem, name: str, default: str = "") -> str:
    c = _child(elem, name)
    return (c.text or default).strip() if c is not None else default


def default_notifications() -> dict:
    """The appliance's bucket["notifications"] shape (also read by its console)."""
    return {"eventBridgeEnabled": False, "topicConfigurations": [], "queueConfigurations": [],
            "cloudFunctionConfigurations": [], "deliveries": [], "updatedAt": _now()}


def bucket_notifications(store: ObjectStore, bucket: str) -> dict:
    meta = store.buckets[bucket]
    n = meta.get("notifications")
    if not isinstance(n, dict):
        n = default_notifications()
        meta["notifications"] = n
    for k, v in default_notifications().items():
        n.setdefault(k, v)
    return n


def parse_notification_xml(body: bytes) -> dict | S3Response:
    """PutBucketNotificationConfiguration body → the stored config (or an error)."""
    config = default_notifications()
    if not body or not body.strip():
        return config
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return _error_xml("MalformedXML", "The XML you provided was not well-formed or did not validate against our published schema.", "/", 400)
    if _local(root.tag) != "NotificationConfiguration":
        return _error_xml("MalformedXML", "The XML you provided was not well-formed or did not validate against our published schema.", "/", 400)
    config["eventBridgeEnabled"] = _child(root, "EventBridgeConfiguration") is not None

    def rule(el, kind: str) -> dict:
        r = {"id": _child_text(el, "Id") or "notif-" + uuid.uuid4().hex[:12],
             "events": [c.text.strip() for c in _children(el, "Event") if c.text and c.text.strip()],
             "prefix": "", "suffix": ""}
        dest = {"TopicConfiguration": ("topic", "Topic"), "QueueConfiguration": ("queue", "Queue"),
                "CloudFunctionConfiguration": ("cloudFunction", "CloudFunction")}[kind]
        r[dest[0]] = _child_text(el, dest[1])
        s3key = _child(_child(el, "Filter"), "S3Key")
        for fr in _children(s3key, "FilterRule"):
            name = _child_text(fr, "Name").lower()
            if name in ("prefix", "suffix"):
                r[name] = _child_text(fr, "Value")
        return r

    config["topicConfigurations"] = [rule(e, "TopicConfiguration") for e in _children(root, "TopicConfiguration")]
    config["queueConfigurations"] = [rule(e, "QueueConfiguration") for e in _children(root, "QueueConfiguration")]
    # Lambda: the SDK serializes CloudFunctionConfiguration (+ <CloudFunction>).
    config["cloudFunctionConfigurations"] = [rule(e, "CloudFunctionConfiguration")
                                             for e in _children(root, "CloudFunctionConfiguration")]
    return config


def notification_xml(n: dict) -> str:
    def filt(r: dict) -> str:
        rules = "".join(f"<FilterRule><Name>{k}</Name><Value>{_xml_escape(r[k])}</Value></FilterRule>"
                        for k in ("prefix", "suffix") if r.get(k))
        return f"<Filter><S3Key>{rules}</S3Key></Filter>" if rules else ""

    out = []
    for key, tag, field_, dest in (("topicConfigurations", "TopicConfiguration", "topic", "Topic"),
                                   ("queueConfigurations", "QueueConfiguration", "queue", "Queue"),
                                   ("cloudFunctionConfigurations", "CloudFunctionConfiguration",
                                    "cloudFunction", "CloudFunction")):
        for r in n.get(key) or []:
            out.append(f"<{tag}>" + (f"<Id>{_xml_escape(r.get('id', ''))}</Id>" if r.get("id") else "")
                       + "".join(f"<Event>{_xml_escape(e)}</Event>" for e in r.get("events") or [])
                       + f"<{dest}>{_xml_escape(r.get(field_, ''))}</{dest}>" + filt(r) + f"</{tag}>")
    eb = "<EventBridgeConfiguration></EventBridgeConfiguration>" if n.get("eventBridgeEnabled") else ""
    return (f'<?xml version="1.0" encoding="UTF-8"?><NotificationConfiguration xmlns="{S3_NS}">'
            f'{"".join(out)}{eb}</NotificationConfiguration>')


def _notification_event_matches(rule: dict, event_name: str, key: str) -> bool:
    """s3:TestEvent (sent once to every configured queue/topic/function on a non-empty
    PutBucketNotificationConfiguration) bypasses the Event/Filter match, like real S3."""
    if event_name == "s3:TestEvent":
        return True
    if not any(ev == event_name or (ev.endswith(":*") and event_name.startswith(ev[:-1]))
               for ev in rule.get("events") or []):
        return False
    if rule.get("prefix") and not key.startswith(rule["prefix"]):
        return False
    if rule.get("suffix") and not key.endswith(rule["suffix"]):
        return False
    return True


def _notification_payload(bucket: str, key: str, version: dict | None, event_name: str, source: str) -> dict:
    return {"Records": [{
        "eventVersion": "2.1", "eventSource": "aws:s3", "awsRegion": "us-east-1",
        "eventTime": _now(), "eventName": event_name.replace("s3:", ""),
        "userIdentity": {"principalId": "AWS:SIMULATOR"},
        "requestParameters": {"sourceIPAddress": "127.0.0.1"},
        "responseElements": {"x-amz-request-id": _req_id(), "x-amz-id-2": uuid.uuid4().hex},
        "s3": {
            "s3SchemaVersion": "1.0", "configurationId": source or "vyomi-s3-notification",
            "bucket": {"name": bucket, "arn": f"arn:aws:s3:::{bucket}"},
            "object": {"key": key, "size": int((version or {}).get("size", 0) or 0),
                       "eTag": (version or {}).get("etag", ""),
                       "versionId": (version or {}).get("version_id", "null"),
                       "sequencer": uuid.uuid4().hex[:16]},
        },
    }]}


def _deliver_notifications(store: ObjectStore, bucket: str, key: str, event_name: str,
                            version: dict | None, source: str) -> None:
    """Real delivery to the SQS queues / SNS topics / Lambda functions a bucket's
    NotificationConfiguration names — the Nano/dev-server counterpart of the appliance's
    own event delivery, reached through the sibling stores the wire router cross-wires onto
    this one (msg_store / lam_store, same pattern as vpc.cw_store / logs.lam_store). A no-op
    where those cross-refs aren't set, e.g. a bare store a unit test constructs directly —
    and where the substrate overrides emit_event with its OWN delivery (the appliance's
    AppStateObjectStore), so that store's existing path runs exactly once, not twice."""
    if type(store).emit_event is not ObjectStore.emit_event:
        return
    msg = getattr(store, "msg_store", None)
    lam = getattr(store, "lam_store", None)
    if msg is None and lam is None:
        return
    notifications = bucket_notifications(store, bucket)
    delivered = []
    if lam is not None:
        for rule in notifications.get("cloudFunctionConfigurations", []):
            if rule.get("cloudFunction") and _notification_event_matches(rule, event_name, key):
                try:
                    from core import lambda_core as _lam_core
                    if _lam_core.invoke_by_arn(lam, rule["cloudFunction"], _notification_payload(bucket, key, version, event_name, source)):
                        delivered.append(rule.get("id", ""))
                except Exception:
                    pass
    if msg is not None:
        for rule in notifications.get("queueConfigurations", []):
            if rule.get("queue") and _notification_event_matches(rule, event_name, key):
                try:
                    from core import sqs_core as _sqs_core
                    q = msg.get_queue_by_arn(rule["queue"])
                    if q:
                        _sqs_core.enqueue(msg, q, json.dumps(_notification_payload(bucket, key, version, event_name, source), default=str))
                        delivered.append(rule.get("id", ""))
                except Exception:
                    pass
        for rule in notifications.get("topicConfigurations", []):
            if rule.get("topic") and _notification_event_matches(rule, event_name, key):
                try:
                    from core import sns_core as _sns_core
                    if _sns_core.publish_arn(msg, rule["topic"], json.dumps(_notification_payload(bucket, key, version, event_name, source), default=str)):
                        delivered.append(rule.get("id", ""))
                except Exception:
                    pass
    if delivered and msg is not None:
        msg.persist()


def _default_acl_xml() -> str:
    return (f'<?xml version="1.0" encoding="UTF-8"?><AccessControlPolicy xmlns="{S3_NS}">{_OWNER_XML}'
            '<AccessControlList><Grant><Grantee xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:type="CanonicalUser"><ID>simulator</ID>'
            '<DisplayName>cloudlearn-simulator</DisplayName></Grantee><Permission>FULL_CONTROL</Permission></Grant></AccessControlList></AccessControlPolicy>')


# ── DEPTH pass: real enforcement for sub-resources that used to be config_only ────────
_GROUP_ALL_USERS = "http://acs.amazonaws.com/groups/global/AllUsers"
_GROUP_AUTH_USERS = "http://acs.amazonaws.com/groups/global/AuthenticatedUsers"
_CANNED_ACL_GRANTS = {
    "private": [],
    "public-read": [(_GROUP_ALL_USERS, "READ")],
    "public-read-write": [(_GROUP_ALL_USERS, "READ"), (_GROUP_ALL_USERS, "WRITE")],
    "authenticated-read": [(_GROUP_AUTH_USERS, "READ")],
    "bucket-owner-read": [],
    "bucket-owner-full-control": [],
}
_PUBLIC_CANNED_ACLS = ("public-read", "public-read-write", "authenticated-read")


def _canned_acl_xml(canned: str) -> str:
    """The AccessControlPolicy a canned `x-amz-acl` value grants — used so GetBucketAcl /
    GetObjectAcl actually reflect a canned PUT instead of always echoing the default."""
    grants = "".join(
        '<Grant><Grantee xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:type="Group">'
        f"<URI>{uri}</URI></Grantee><Permission>{perm}</Permission></Grant>"
        for uri, perm in _CANNED_ACL_GRANTS.get(canned, []))
    owner_grant = ('<Grant><Grantee xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:type="CanonicalUser">'
                   "<ID>simulator</ID><DisplayName>cloudlearn-simulator</DisplayName></Grantee>"
                   "<Permission>FULL_CONTROL</Permission></Grant>")
    return (f'<?xml version="1.0" encoding="UTF-8"?><AccessControlPolicy xmlns="{S3_NS}">{_OWNER_XML}'
            f"<AccessControlList>{owner_grant}{grants}</AccessControlList></AccessControlPolicy>")


def _object_ownership(store: ObjectStore, bucket: str) -> str | None:
    meta = store.buckets.get(bucket) or {}
    doc = meta.get("cfg", {}).get("ownershipControls")
    if not doc:
        return None
    try:
        root = ET.fromstring(doc)
    except ET.ParseError:
        return None
    rule = _child(root, "Rule")
    return _child_text(rule, "ObjectOwnership") or None


def _acl_blocked_by_ownership(store: ObjectStore, bucket: str) -> S3Response | None:
    """BucketOwnerEnforced disables ACLs entirely — real S3 rejects every Put*Acl call,
    not just public ones, once ownership is set this way."""
    if _object_ownership(store, bucket) == "BucketOwnerEnforced":
        return _error_xml("InvalidBucketAclWithObjectOwnership",
                          "Bucket cannot have ACLs set with ObjectOwnership's BucketOwnerEnforced setting",
                          f"/{bucket}", 400)
    return None


def _public_access_block(store: ObjectStore, bucket: str) -> dict:
    meta = store.buckets.get(bucket) or {}
    doc = meta.get("cfg", {}).get("publicAccessBlock")
    flags = {"BlockPublicAcls": False, "IgnorePublicAcls": False,
             "BlockPublicPolicy": False, "RestrictPublicBuckets": False}
    if not doc:
        return flags
    try:
        root = ET.fromstring(doc)
    except ET.ParseError:
        return flags
    for k in flags:
        flags[k] = _child_text(root, k).strip().lower() == "true"
    return flags


def _acl_blocked_by_pab(store: ObjectStore, bucket: str, canned: str | None) -> S3Response | None:
    if canned in _PUBLIC_CANNED_ACLS and _public_access_block(store, bucket)["BlockPublicAcls"]:
        return _error_xml("AccessDenied",
                          "This request is not allowed because the bucket owner enforced the "
                          "Block Public Access setting that disallows public ACLs.", f"/{bucket}", 403)
    return None


def _policy_is_public(policy: dict) -> bool:
    for st in policy.get("Statement") or []:
        if st.get("Effect") != "Allow":
            continue
        principal = st.get("Principal")
        if principal == "*":
            return True
        if isinstance(principal, dict):
            aws = principal.get("AWS")
            if aws == "*" or (isinstance(aws, list) and "*" in aws):
                return True
    return False


def _bucket_encryption(store: ObjectStore, bucket: str) -> dict:
    """The bucket's default-encryption config — AES256 is the fallback because real S3
    now encrypts every bucket by default even without an explicit PutBucketEncryption call."""
    meta = store.buckets.get(bucket) or {}
    doc = meta.get("cfg", {}).get("encryption")
    out = {"algorithm": "AES256", "kms_key": None, "bucket_key": False}
    if not doc:
        return out
    try:
        root = ET.fromstring(doc)
    except ET.ParseError:
        return out
    rule = _child(root, "Rule")
    if rule is None:
        return out
    default = _child(rule, "ApplyServerSideEncryptionByDefault")
    if default is not None:
        out["algorithm"] = _child_text(default, "SSEAlgorithm") or "AES256"
        out["kms_key"] = _child_text(default, "KMSMasterKeyID") or None
    out["bucket_key"] = _child_text(rule, "BucketKeyEnabled").strip().lower() == "true"
    return out


def _sse_headers(store: ObjectStore, bucket: str) -> dict:
    enc = _bucket_encryption(store, bucket)
    h = {"x-amz-server-side-encryption": enc["algorithm"]}
    if enc["algorithm"] != "AES256" and enc["kms_key"]:
        h["x-amz-server-side-encryption-aws-kms-key-id"] = enc["kms_key"]
    if enc["bucket_key"]:
        h["x-amz-server-side-encryption-bucket-key-enabled"] = "true"
    return h


def _request_payer_block(store: ObjectStore, bucket: str, headers: dict) -> S3Response | None:
    """Requester Pays (PutBucketRequestPayment Payer=Requester) rejects a data-retrieval
    request that doesn't carry x-amz-request-payer:requester, exactly like real S3 — the
    one part of Requester Pays actually visible on the wire (there is no billing system
    behind it to attribute the transfer cost to, but the parameter requirement itself is
    real and enforced the same way here)."""
    meta = store.buckets.get(bucket) or {}
    if meta.get("payer") != "Requester":
        return None
    h = {str(k).lower(): v for k, v in (headers or {}).items()}
    if h.get("x-amz-request-payer", "").lower() == "requester":
        return None
    return _error_xml(
        "AccessDenied",
        "Bucket is a Requester Pays bucket and the request wasn't made with the "
        "appropriate parameter (x-amz-request-payer:requester).", f"/{bucket}", 403)


def _request_charged_header(headers: dict) -> dict:
    h = {str(k).lower(): v for k, v in (headers or {}).items()}
    return {"x-amz-request-charged": "requester"} if h.get("x-amz-request-payer", "").lower() == "requester" else {}


def _cors_rules(store: ObjectStore, bucket: str) -> list:
    meta = store.buckets.get(bucket) or {}
    doc = meta.get("cfg", {}).get("cors")
    if not doc:
        return []
    try:
        root = ET.fromstring(doc)
    except ET.ParseError:
        return []
    rules = []
    for r in _children(root, "CORSRule"):
        rules.append({
            "AllowedOrigins": [c.text.strip() for c in _children(r, "AllowedOrigin") if c.text],
            "AllowedMethods": [c.text.strip() for c in _children(r, "AllowedMethod") if c.text],
            "AllowedHeaders": [c.text.strip() for c in _children(r, "AllowedHeader") if c.text],
            "ExposeHeaders": [c.text.strip() for c in _children(r, "ExposeHeader") if c.text],
            "MaxAgeSeconds": int(_child_text(r, "MaxAgeSeconds") or 0) or None,
        })
    return rules


def _matching_cors_rule(rules: list, origin: str, method: str) -> dict | None:
    for r in rules:
        origins = r.get("AllowedOrigins") or []
        methods = [m.upper() for m in (r.get("AllowedMethods") or [])]
        if ("*" in origins or origin in origins) and method.upper() in methods:
            return r
    return None


def _cors_response_headers(store: ObjectStore, bucket: str, headers: dict, method: str) -> dict:
    """Access-Control-* headers to merge into an actual (non-preflight) response, if the
    request's Origin + method match a configured CORS rule."""
    origin = {str(k).lower(): v for k, v in (headers or {}).items()}.get("origin")
    if not origin:
        return {}
    rule = _matching_cors_rule(_cors_rules(store, bucket), origin, method)
    if not rule:
        return {}
    out = {"Access-Control-Allow-Origin": origin if "*" not in rule["AllowedOrigins"] else "*"}
    if rule.get("ExposeHeaders"):
        out["Access-Control-Expose-Headers"] = ", ".join(rule["ExposeHeaders"])
    return out


def _cors_preflight(store: ObjectStore, bucket: str, headers: dict) -> S3Response:
    origin = headers.get("origin")
    req_method = headers.get("access-control-request-method", "GET")
    if not origin:
        return _error_xml("InvalidRequest", "Missing Origin header.", f"/{bucket}", 400)
    if not store.bucket_exists(bucket):
        return _error_xml("NoSuchBucket", "The specified bucket does not exist.", f"/{bucket}", 404)
    rule = _matching_cors_rule(_cors_rules(store, bucket), origin, req_method)
    if not rule:
        return _error_xml("AccessForbidden",
                          "CORSResponse: This CORS request is not allowed because the evaluation of "
                          "Origin, Access-Control-Request-Method or Access-Control-Request-Headers is "
                          "not whitelisted by the bucket's CORS configuration.", f"/{bucket}", 403)
    h = {"Access-Control-Allow-Origin": origin if "*" not in rule["AllowedOrigins"] else "*",
         "Access-Control-Allow-Methods": ", ".join(rule["AllowedMethods"])}
    if rule.get("AllowedHeaders"):
        h["Access-Control-Allow-Headers"] = ", ".join(rule["AllowedHeaders"])
    if rule.get("ExposeHeaders"):
        h["Access-Control-Expose-Headers"] = ", ".join(rule["ExposeHeaders"])
    if rule.get("MaxAgeSeconds"):
        h["Access-Control-Max-Age"] = str(rule["MaxAgeSeconds"])
    return _empty_response(200, h)


def _parse_lifecycle_rules(doc: str) -> list:
    try:
        root = ET.fromstring(doc)
    except ET.ParseError:
        return []
    rules = []
    for r in _children(root, "Rule"):
        if _child_text(r, "Status") != "Enabled":
            continue
        filt = _child(r, "Filter")
        prefix = _child_text(filt, "Prefix") if filt is not None else _child_text(r, "Prefix")
        exp = _child(r, "Expiration")
        exp_days, exp_date = None, None
        if exp is not None:
            days = _child_text(exp, "Days")
            if days:
                try:
                    exp_days = int(days)
                except ValueError:
                    exp_days = None
            exp_date = _child_text(exp, "Date") or None
        noncur_exp = _child(r, "NoncurrentVersionExpiration")
        noncurrent_days = None
        if noncur_exp is not None:
            nd = _child_text(noncur_exp, "NoncurrentDays")
            if nd:
                try:
                    noncurrent_days = int(nd)
                except ValueError:
                    noncurrent_days = None
        transitions = []
        for t in _children(r, "Transition"):
            sc = _child_text(t, "StorageClass")
            if not sc:
                continue
            t_days, t_date = None, None
            td = _child_text(t, "Days")
            if td:
                try:
                    t_days = int(td)
                except ValueError:
                    t_days = None
            t_date = _child_text(t, "Date") or None
            transitions.append({"storage_class": sc, "days": t_days, "date": t_date})
        abort_mpu = _child(r, "AbortIncompleteMultipartUpload")
        abort_days = None
        if abort_mpu is not None:
            ad = _child_text(abort_mpu, "DaysAfterInitiation")
            if ad:
                try:
                    abort_days = int(ad)
                except ValueError:
                    abort_days = None
        rules.append({"prefix": prefix or "", "expiration_days": exp_days, "expiration_date": exp_date,
                      "noncurrent_days": noncurrent_days, "transitions": transitions,
                      "abort_incomplete_days": abort_days})
    return rules


def _lifecycle_rules(store: ObjectStore, bucket: str) -> list:
    meta = store.buckets.get(bucket) or {}
    doc = meta.get("cfg", {}).get("lifecycle")
    return _parse_lifecycle_rules(doc) if doc else []


def _rule_expires(rule: dict, key: str, last_modified_iso: str) -> bool:
    if not key.startswith(rule["prefix"]):
        return False
    now = datetime.now(timezone.utc)
    if rule.get("expiration_date"):
        try:
            cutoff = datetime.fromisoformat(rule["expiration_date"].replace("Z", "+00:00"))
        except ValueError:
            return False
        return now >= cutoff
    if rule.get("expiration_days") is not None:
        try:
            lm = datetime.fromisoformat(last_modified_iso.replace("Z", "+00:00"))
        except ValueError:
            return False
        return now >= lm + timedelta(days=rule["expiration_days"])
    return False


def _rule_transition_class(rule: dict, key: str, last_modified_iso: str) -> str | None:
    """The deepest Transition tier whose threshold (Days elapsed or past Date) has
    fired, among a rule's <Transition> entries matching this key's prefix."""
    if not key.startswith(rule["prefix"]):
        return None
    now = datetime.now(timezone.utc)
    best_sc, best_rank = None, -1
    for idx, t in enumerate(rule.get("transitions") or []):
        fired = False
        if t.get("date"):
            try:
                fired = now >= datetime.fromisoformat(t["date"].replace("Z", "+00:00"))
            except ValueError:
                fired = False
        elif t.get("days") is not None:
            try:
                lm = datetime.fromisoformat(last_modified_iso.replace("Z", "+00:00"))
                fired = now >= lm + timedelta(days=t["days"])
            except ValueError:
                fired = False
        if fired and idx > best_rank:   # later <Transition> entries = colder tiers (document order)
            best_sc, best_rank = t["storage_class"], idx
    return best_sc


def _apply_lifecycle(store: ObjectStore, bucket: str) -> None:
    """Lazily evaluated on every read path (list/get/head) — Date-based Expiration rules
    fire deterministically (testable without waiting real days); Days-based rules use the
    real elapsed wall-clock, matching S3's own (non-accelerated) semantics. Also enforces
    NoncurrentVersionExpiration (deletes aged-out noncurrent versions, honouring Object Lock)
    and Transition (flips the current version's storage class once its threshold fires)."""
    rules = _lifecycle_rules(store, bucket)
    if not rules:
        return
    bucket_objects = store.bucket_objects(bucket)
    vstatus = store.versioning_status(bucket)
    changed_any = False
    for key in list(bucket_objects.keys()):
        entry = bucket_objects.get(key)
        if not isinstance(entry, dict) or not entry.get("versions"):
            continue
        cur = entry["versions"][0]
        if not cur.get("is_delete_marker"):
            if any(_rule_expires(rule, key, cur.get("last_modified", _now())) for rule in rules):
                changed_any = True
                if vstatus in ("Enabled", "Suspended"):
                    _insert_simple_delete_marker(store, bucket, key)
                    _emit(store, bucket, key, "s3:LifecycleExpiration:DeleteMarkerCreated", None, "Lifecycle")
                else:
                    bucket_objects.pop(key, None)
                    store.mirror_delete(bucket, key)
                    _emit(store, bucket, key, "s3:LifecycleExpiration:Delete", None, "Lifecycle")
                continue
            new_sc = None
            for rule in rules:
                sc = _rule_transition_class(rule, key, cur.get("last_modified", _now()))
                if sc:
                    new_sc = sc
            if new_sc and cur.get("storage_class") != new_sc:
                cur["storage_class"] = new_sc
                changed_any = True
        # NoncurrentVersionExpiration — walk every version behind the current one.
        entry2 = bucket_objects.get(key)
        if not isinstance(entry2, dict):
            continue
        for v in list(entry2.get("versions", [])[1:]):
            if _lock_block(v, None):
                continue   # legal hold / retention keeps a noncurrent version alive
            for rule in rules:
                if not key.startswith(rule["prefix"]) or rule.get("noncurrent_days") is None:
                    continue
                try:
                    lm = datetime.fromisoformat(v.get("last_modified", _now()).replace("Z", "+00:00"))
                except ValueError:
                    continue
                if datetime.now(timezone.utc) >= lm + timedelta(days=rule["noncurrent_days"]):
                    _delete_version(store, bucket, key, v.get("version_id", "null"))
                    changed_any = True
                    break
    if changed_any:
        store.persist()


def _apply_lifecycle_mpu(store: ObjectStore, bucket: str) -> None:
    """AbortIncompleteMultipartUpload — lazily sweep stale in-progress uploads for
    this bucket on ListMultipartUploads, matching the same lazy-evaluation style as
    the other lifecycle actions."""
    rules = _lifecycle_rules(store, bucket)
    if not rules:
        return
    uploads = _mpu(store)
    now = datetime.now(timezone.utc)
    aborted = False
    for uid, up in list(uploads.items()):
        if up.get("bucket") != bucket:
            continue
        key = up.get("key", "")
        for rule in rules:
            if rule.get("abort_incomplete_days") is None or not key.startswith(rule["prefix"]):
                continue
            try:
                initiated = datetime.fromisoformat(str(up.get("initiated") or _now()).replace("Z", "+00:00"))
            except ValueError:
                continue
            if now >= initiated + timedelta(days=rule["abort_incomplete_days"]):
                uploads.pop(uid, None)
                aborted = True
                break
    if aborted:
        store.persist()


_IT_TIERS = ("ARCHIVE_ACCESS", "DEEP_ARCHIVE_ACCESS")   # document order = colder tiers later


def _parse_it_rules(configs: dict) -> list:
    """IntelligentTieringConfiguration documents (stored verbatim by the generic
    id-keyed sub-resource handler) → {"prefix", "tierings": [{"access_tier","days"}]},
    Disabled configs excluded, same shape style as _parse_lifecycle_rules."""
    rules = []
    for doc in (configs or {}).values():
        try:
            root = ET.fromstring(doc)
        except ET.ParseError:
            continue
        if _child_text(root, "Status") != "Enabled":
            continue
        filt = _child(root, "Filter")
        prefix = _child_text(filt, "Prefix") if filt is not None else ""
        tierings = []
        for t in _children(_child(root, "Tierings") or root, "Tiering"):
            tier, days = _child_text(t, "AccessTier"), _child_text(t, "Days")
            if tier in _IT_TIERS and days:
                try:
                    tierings.append({"access_tier": tier, "days": int(days)})
                except ValueError:
                    pass
        if tierings:
            rules.append({"prefix": prefix or "", "tierings": tierings})
    return rules


def _it_rules(store: ObjectStore, bucket: str) -> list:
    meta = store.buckets.get(bucket) or {}
    return _parse_it_rules(meta.get("it_configs") or {})


def _apply_intelligent_tiering(store: ObjectStore, bucket: str) -> None:
    """Archive-tier transitions for objects explicitly stored with StorageClass
    INTELLIGENT_TIERING, lazily evaluated on head/get like lifecycle Transition — Days
    elapsed uses the real wall-clock from the object's last-modified time, against the
    Tierings a bucket's IntelligentTieringConfiguration(s) actually name (ARCHIVE_ACCESS /
    DEEP_ARCHIVE_ACCESS). The automatic, config-free Frequent<->Infrequent Access tiering
    every object gets after 30 days of no reads is NOT modeled (Vyomi doesn't track
    per-object read recency); only the opt-in archive tiers a configuration names are."""
    rules = _it_rules(store, bucket)
    if not rules:
        return
    now = datetime.now(timezone.utc)
    changed = False
    for key, entry in store.bucket_objects(bucket).items():
        if not isinstance(entry, dict) or not entry.get("versions"):
            continue
        cur = entry["versions"][0]
        if cur.get("is_delete_marker") or cur.get("storage_class") != "INTELLIGENT_TIERING":
            continue
        try:
            lm = datetime.fromisoformat(cur.get("last_modified", _now()).replace("Z", "+00:00"))
        except ValueError:
            continue
        best = None
        for rule in rules:
            if not key.startswith(rule["prefix"]):
                continue
            for t in rule["tierings"]:
                if now >= lm + timedelta(days=t["days"]):
                    if best is None or _IT_TIERS.index(t["access_tier"]) > _IT_TIERS.index(best):
                        best = t["access_tier"]
        if cur.get("archive_tier") != best:
            cur["archive_tier"] = best
            changed = True
    if changed:
        store.persist()


_INVENTORY_PERIOD = {"Daily": timedelta(days=1), "Weekly": timedelta(days=7)}


def _parse_inventory_rules(configs: dict) -> list:
    """InventoryConfiguration documents → {"id","dest_bucket","dest_prefix","format",
    "frequency","included","prefix"}. Disabled configs (IsEnabled=false) and ones whose
    Destination isn't a plain S3BucketDestination are excluded."""
    rules = []
    for cfg_id, doc in (configs or {}).items():
        try:
            root = ET.fromstring(doc)
        except ET.ParseError:
            continue
        if _child_text(root, "IsEnabled").strip().lower() == "false":
            continue
        s3dest = _child(_child(root, "Destination"), "S3BucketDestination")
        if s3dest is None:
            continue
        dest_arn = _child_text(s3dest, "Bucket")
        dest_bucket = dest_arn.rsplit(":", 1)[-1] if dest_arn else ""
        if not dest_bucket:
            continue
        filt = _child(root, "Filter")
        rules.append({
            "id": cfg_id, "dest_bucket": dest_bucket, "dest_prefix": _child_text(s3dest, "Prefix"),
            "format": (_child_text(s3dest, "Format") or "CSV").upper(),
            "frequency": _child_text(_child(root, "Schedule"), "Frequency") or "Daily",
            "included": _child_text(root, "IncludedObjectVersions") or "Current",
            "prefix": (_child_text(filt, "Prefix") if filt is not None else "") or "",
        })
    return rules


def _generate_inventory_manifest(store: ObjectStore, bucket: str, rule: dict, now: datetime) -> None:
    """Writes a REAL manifest into the destination bucket, listing the source bucket's
    actual current contents (or every version, for IncludedObjectVersions=All) — exactly
    what real S3's inventory report contains, minus the CSV being gzip-compressed and
    minus ORC/Parquet encoding (Vyomi has no encoder for those; only Format=CSV actually
    produces a data file — see s3.bucket.inventory's capability limitations)."""
    ts = now.strftime("%Y-%m-%dT%H-%MZ")
    base = f"{rule['dest_prefix']}{bucket}/{rule['id']}/{ts}/"
    rows = []
    for key, entry in sorted(store.bucket_objects(bucket).items()):
        if not isinstance(entry, dict) or not entry.get("versions") or not key.startswith(rule["prefix"]):
            continue
        versions = entry["versions"] if rule["included"] == "All" else entry["versions"][:1]
        for v in versions:
            if v.get("is_delete_marker"):
                continue
            rows.append([bucket, key, v.get("version_id", "null"), str(v is entry["versions"][0]).lower(),
                        str(v.get("size", 0)), v.get("last_modified", _now()),
                        v.get("etag", "").strip('"'), v.get("storage_class", "STANDARD")])
    schema = "Bucket, Key, VersionId, IsLatest, Size, LastModifiedDate, ETag, StorageClass"
    files = []
    if rule["format"] == "CSV":
        buf = io.StringIO()
        csv.writer(buf).writerows(rows)
        data = buf.getvalue().encode()
        data_key = f"{base}data/{uuid.uuid4().hex[:16]}.csv"
        _write_object_version(store, rule["dest_bucket"], data_key,
                              _make_version_record(data=data, content_type="text/csv", version_id="null"))
        files.append({"key": data_key, "size": len(data), "MD5checksum": hashlib.md5(data).hexdigest()})
    manifest = {
        "sourceBucket": bucket, "destinationBucket": f"arn:aws:s3:::{rule['dest_bucket']}",
        "version": "2016-11-30", "creationTimestamp": str(int(now.timestamp() * 1000)),
        "fileFormat": rule["format"] if rule["format"] == "CSV" else f"{rule['format']} (not produced — see capability limitations)",
        "fileSchema": schema, "files": files,
    }
    manifest_bytes = json.dumps(manifest, indent=2).encode()
    _write_object_version(store, rule["dest_bucket"], f"{base}manifest.json",
                          _make_version_record(data=manifest_bytes, content_type="application/json", version_id="null"))
    checksum = hashlib.md5(manifest_bytes).hexdigest().encode()
    _write_object_version(store, rule["dest_bucket"], f"{base}manifest.checksum",
                          _make_version_record(data=checksum, content_type="text/plain", version_id="null"))


def _apply_inventory(store: ObjectStore, bucket: str) -> None:
    """Lazily evaluated (no background scheduler in this simulator): the first access
    generates a manifest immediately; later ones regenerate only once the configuration's
    real Schedule.Frequency (Daily/Weekly) has actually elapsed, same lazy-real-wall-clock
    style as lifecycle/Intelligent-Tiering. Only reaches a destination bucket that exists
    in this same appliance, like replication/logging."""
    meta = store.buckets.get(bucket) or {}
    rules = _parse_inventory_rules(meta.get("inv_configs") or {})
    if not rules:
        return
    runs = meta.setdefault("inventory_runs", {})
    now = datetime.now(timezone.utc)
    ran = False
    for rule in rules:
        if not store.bucket_exists(rule["dest_bucket"]) or rule["dest_bucket"] == bucket:
            continue
        last = runs.get(rule["id"])
        if last:
            try:
                if now < datetime.fromisoformat(last.replace("Z", "+00:00")) + _INVENTORY_PERIOD.get(rule["frequency"], timedelta(days=1)):
                    continue
            except ValueError:
                pass
        try:
            _generate_inventory_manifest(store, bucket, rule, now)
        except Exception:
            continue   # manifest delivery is best-effort; never fail the read it rode in on
        runs[rule["id"]] = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        ran = True
    if ran:
        store.persist()


def _parse_metrics_rules(configs: dict) -> list:
    """MetricsConfiguration documents (stored verbatim by the generic id-keyed
    sub-resource handler) → {"id", "prefix"} — a request-metrics FILTER is active the
    moment it exists (unlike IntelligentTiering/Lifecycle there is no Enabled/Disabled
    toggle on the document itself)."""
    rules = []
    for cfg_id, doc in (configs or {}).items():
        try:
            root = ET.fromstring(doc)
        except ET.ParseError:
            continue
        filt = _child(root, "Filter")
        prefix = _child_text(filt, "Prefix") if filt is not None else ""
        rules.append({"id": cfg_id, "prefix": prefix or ""})
    return rules


def _metrics_rules(store: ObjectStore, bucket: str) -> list:
    meta = store.buckets.get(bucket) or {}
    return _parse_metrics_rules(meta.get("metrics_configs") or {})


_METHOD_METRIC = {"GET": "GetRequests", "HEAD": "HeadRequests", "PUT": "PutRequests",
                  "DELETE": "DeleteRequests", "POST": "PostRequests", "LIST": "ListRequests"}


def _record_request_metrics(store: ObjectStore, bucket: str, key: str, method: str, status: int,
                             bytes_down: int = 0, bytes_up: int = 0) -> None:
    """Real AWS/S3 CloudWatch request metrics, derived from this actual request — never
    synthetic — for every bucket.metrics Filter whose prefix the key matches (an empty key,
    for a bucket-level op like ListObjectsV2, only matches a filter with no prefix, same as
    a real S3 EntireBucket-scoped filter). Reached through cw_store, the same cross-wired
    sibling-store seam vpc_core/logs_core already use for their own real metrics."""
    cw = getattr(store, "cw_store", None)
    if cw is None:
        return
    rules = [r for r in _metrics_rules(store, bucket) if key.startswith(r["prefix"])]
    if not rules:
        return
    try:
        from core import cloudwatch_core as _cw_core
    except ImportError:
        return
    metric = _METHOD_METRIC.get(method)
    for r in rules:
        dims = [{"Name": "BucketName", "Value": bucket}, {"Name": "FilterId", "Value": r["id"]}]
        _cw_core.ingest_internal_metric(cw, "AWS/S3", "AllRequests", dims, 1.0, unit="Count")
        if metric:
            _cw_core.ingest_internal_metric(cw, "AWS/S3", metric, dims, 1.0, unit="Count")
        if 400 <= status < 500:
            _cw_core.ingest_internal_metric(cw, "AWS/S3", "4xxErrors", dims, 1.0, unit="Count")
        elif status >= 500:
            _cw_core.ingest_internal_metric(cw, "AWS/S3", "5xxErrors", dims, 1.0, unit="Count")
        if bytes_down:
            _cw_core.ingest_internal_metric(cw, "AWS/S3", "BytesDownloaded", dims, float(bytes_down), unit="Bytes")
        if bytes_up:
            _cw_core.ingest_internal_metric(cw, "AWS/S3", "BytesUploaded", dims, float(bytes_up), unit="Bytes")


def _lock_block(obj: dict | None, headers: dict | None) -> S3Response | None:
    """Object Lock enforcement for a DELETE of a specific version — legal hold blocks
    unconditionally; retention blocks unless GOVERNANCE mode is explicitly bypassed."""
    if not obj:
        return None
    if obj.get("legal_hold") == "ON":
        return _error_xml("AccessDenied", "Object is under a legal hold and cannot be deleted.", "/", 403)
    ret = obj.get("retention")
    if ret and ret.get("mode") and ret.get("retain_until"):
        try:
            until = datetime.fromisoformat(str(ret["retain_until"]).replace("Z", "+00:00"))
        except ValueError:
            until = None
        if until and datetime.now(timezone.utc) < until:
            if ret["mode"] == "COMPLIANCE":
                return _error_xml("AccessDenied",
                                  "Object is WORM-protected (Object Lock retention, COMPLIANCE mode) "
                                  "until the retain-until date.", "/", 403)
            bypass = str((headers or {}).get("x-amz-bypass-governance-retention", "")).lower() == "true"
            if ret["mode"] == "GOVERNANCE" and not bypass:
                return _error_xml("AccessDenied",
                                  "Object is WORM-protected (Object Lock retention, GOVERNANCE mode); "
                                  "retry with x-amz-bypass-governance-retention to override.", "/", 403)
    return None


def _apply_object_lock_on_write(store: ObjectStore, bucket: str, headers: dict, version: dict) -> None:
    """Explicit per-request Object Lock headers (x-amz-object-lock-*) take precedence;
    otherwise, on a bucket with Object Lock enabled, the bucket's DefaultRetention rule
    (PutObjectLockConfiguration) is stamped onto every new version that doesn't carry an
    explicit one — matching real S3's upload-time default-retention behaviour."""
    if not (store.buckets.get(bucket) or {}).get("object_lock"):
        return
    mode = headers.get("x-amz-object-lock-mode")
    until = headers.get("x-amz-object-lock-retain-until-date")
    if mode and until:
        version["retention"] = {"mode": mode, "retain_until": until}
    else:
        default = (store.buckets.get(bucket) or {}).get("object_lock_default_retention")
        if default:
            now = datetime.now(timezone.utc)
            if default.get("days") is not None:
                retain_until = now + timedelta(days=default["days"])
            else:
                retain_until = now.replace(year=now.year + int(default.get("years") or 0))
            version["retention"] = {
                "mode": default["mode"],
                "retain_until": retain_until.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            }
    legal_hold = headers.get("x-amz-object-lock-legal-hold-status")
    if legal_hold in ("ON", "OFF"):
        version["legal_hold"] = legal_hold


def _done(store: ObjectStore, resp: S3Response) -> S3Response:
    """Flush the durable substrate after a mutation (success or not — cheap)."""
    store.persist()
    return resp


def _emit(store: ObjectStore, bucket: str, key: str, event: str, entry: dict | None, source: str) -> None:
    version = (entry or {}).get("versions", [None])[0] if isinstance(entry, dict) and entry.get("versions") else None
    try:
        store.emit_event(bucket, key, event, version, source)
    except Exception:   # delivery is best-effort; never fail the data-plane write
        pass
    try:
        _deliver_notifications(store, bucket, key, event, version, source)
    except Exception:   # delivery is best-effort; never fail the data-plane write
        pass


def _replication_rules(store: ObjectStore, bucket: str) -> list:
    """Parsed <Rule> entries from the bucket's stored ReplicationConfiguration (if any)."""
    meta = store.buckets.get(bucket, {})
    doc = meta.get("cfg", {}).get("replication")
    if not doc:
        return []
    try:
        root = ET.fromstring(doc)
    except ET.ParseError:
        return []
    rules = []
    for r in _children(root, "Rule"):
        dest_el = _child(r, "Destination")
        dest_arn = _child_text(dest_el, "Bucket") if dest_el is not None else ""
        filt = _child(r, "Filter")
        prefix = _child_text(filt, "Prefix") if filt is not None else _child_text(r, "Prefix")
        dmr = _child(r, "DeleteMarkerReplication")
        rules.append({
            "id": _child_text(r, "ID"),
            "status": _child_text(r, "Status", "Disabled"),
            "prefix": prefix,
            "destination": dest_arn.rsplit(":", 1)[-1] if dest_arn else "",
            "delete_marker_replication": dmr is not None and _child_text(dmr, "Status") == "Enabled",
        })
    return rules


def _replicate(store: ObjectStore, bucket: str, key: str, entry: dict | None) -> None:
    """Replication rules are enforced SYNCHRONOUSLY (no async worker in this simulator):
    a matching Enabled rule copies the just-written current version into its destination
    bucket immediately, in-store. Only reaches destinations that exist in this appliance."""
    if not entry or not entry.get("versions"):
        return
    cur = entry["versions"][0]
    if cur.get("is_delete_marker"):
        return
    applied = False
    for rule in _replication_rules(store, bucket):
        if rule["status"] != "Enabled":
            continue
        if rule["prefix"] and not key.startswith(rule["prefix"]):
            continue
        dest = rule["destination"]
        if not dest or dest == bucket or not store.bucket_exists(dest):
            continue
        vstatus_dest = store.versioning_status(dest)
        vid = _new_version_id(store, dest) if vstatus_dest == "Enabled" else "null"
        version = _make_version_record(
            data=_version_bytes(store, bucket, key, cur), content_type=cur.get("content_type", "application/octet-stream"),
            storage_class=cur.get("storage_class", "STANDARD"), metadata=cur.get("metadata", {}),
            tags=cur.get("tags", {}), version_id=vid, delete_marker=False,
        )
        replace = "__overwrite__" if vstatus_dest == "Disabled" else ("null" if vstatus_dest == "Suspended" else None)
        _write_object_version(store, dest, key, version, replace_version_id=replace)
        applied = True
    if applied:
        cur["replication_status"] = "COMPLETED"


def _replicate_delete_marker(store: ObjectStore, bucket: str, key: str) -> None:
    """DeleteMarkerReplication — a delete marker inserted by a plain (no versionId)
    DELETE on a versioned+replicated source key is propagated to the destination too,
    synchronously, same as every other replicated write in this simulator."""
    for rule in _replication_rules(store, bucket):
        if rule["status"] != "Enabled" or not rule.get("delete_marker_replication"):
            continue
        if rule["prefix"] and not key.startswith(rule["prefix"]):
            continue
        dest = rule["destination"]
        if not dest or dest == bucket or not store.bucket_exists(dest):
            continue
        vstatus_dest = store.versioning_status(dest)
        vid = _new_version_id(store, dest) if vstatus_dest == "Enabled" else "null"
        marker = _make_version_record(delete_marker=True, version_id=vid)
        replace = "__overwrite__" if vstatus_dest == "Disabled" else ("null" if vstatus_dest == "Suspended" else None)
        _write_object_version(store, dest, key, marker, replace_version_id=replace)


def _bucket_logging_target(store: ObjectStore, bucket: str) -> tuple[str, str] | None:
    meta = store.buckets.get(bucket) or {}
    doc = meta.get("logging")
    if not doc:
        return None
    try:
        root = ET.fromstring(doc)
    except ET.ParseError:
        return None
    enabled = _child(root, "LoggingEnabled")
    if enabled is None:
        return None
    target = _child_text(enabled, "TargetBucket")
    if not target:
        return None
    return target, _child_text(enabled, "TargetPrefix")


def _write_access_log(store: ObjectStore, bucket: str, method: str, key: str,
                      operation: str, status: int, request_uri: str, bytes_sent: int) -> None:
    """Server access logging — ENFORCED (not merely stored): every logged request on a
    bucket with PutBucketLogging configured writes one real log-line object into the
    target bucket, in this simulator's own delivery window (immediately, request by
    request) rather than real S3's batched/delayed delivery — the one divergence from
    real S3 this lazy, single-process simulator cannot remove."""
    try:
        target = _bucket_logging_target(store, bucket)
        if not target or not store.bucket_exists(target[0]):
            return
        dest, prefix = target
        now = datetime.now(timezone.utc)
        line = (f'79a59df900b949e55d96a1e698fbacedfd6e09d98eacf8f8d5218e7cd47ef2be '
                f'{bucket} [{now.strftime("%d/%b/%Y:%H:%M:%S +0000")}] 127.0.0.1 '
                f'- {uuid.uuid4().hex.upper()} {operation} {_xml_escape(key)} '
                f'"{method} /{request_uri} HTTP/1.1" {status} - {bytes_sent} {bytes_sent} '
                f'12 12 "-" "-" -\n')
        log_key = f"{prefix}{bucket}-{now.strftime('%Y-%m-%d-%H-%M-%S')}-{uuid.uuid4().hex[:16].upper()}"
        version = _make_version_record(data=line.encode(), content_type="text/plain", version_id="null")
        vstatus_dest = store.versioning_status(dest)
        if vstatus_dest == "Enabled":
            version["version_id"] = _new_version_id(store, dest)
        _write_object_version(store, dest, log_key, version)
        store.persist()
    except Exception:
        pass   # log delivery is best-effort; never fail the request it is logging


# ── the 5 operations (faithful ports of the handler bodies) ───────────────
def put_object(store: ObjectStore, bucket: str, key: str, body: bytes, headers: dict) -> S3Response:
    headers = {k.lower(): v for k, v in (headers or {}).items()}
    if not store.bucket_exists(bucket):
        return _error_xml("NoSuchBucket", "The specified bucket does not exist.", f"/{bucket}", 404)
    data, trailers = _decode_aws_chunked_full(body or b"", headers)
    checksum, bad = _request_checksum(headers, trailers, data)
    if bad:
        return bad
    content_type = headers.get("content-type", "application/octet-stream")
    storage_class = headers.get("x-amz-storage-class", "STANDARD")
    user_meta = {h[11:]: v for h, v in headers.items() if h.startswith("x-amz-meta-")}
    tags = dict(urllib.parse.parse_qsl(headers.get("x-amz-tagging", ""), keep_blank_values=True))
    vstatus = store.versioning_status(bucket)
    vid = _new_version_id(store, bucket) if vstatus == "Enabled" else "null"
    version = _make_version_record(data=data, content_type=content_type,
                                   storage_class=storage_class, metadata=user_meta, tags=tags,
                                   version_id=vid, delete_marker=False)
    if checksum:
        version["checksum"] = checksum
    _apply_object_lock_on_write(store, bucket, headers, version)
    replace = "__overwrite__" if vstatus == "Disabled" else ("null" if vstatus == "Suspended" else None)
    entry = _write_object_version(store, bucket, key, version, replace_version_id=replace)
    _replicate(store, bucket, key, entry)
    _emit(store, bucket, key, "s3:ObjectCreated:Put", entry, "PutObject")
    extra = {"ETag": version["etag"], "x-amz-version-id": entry.get("current_version_id", vid)}
    extra.update(_checksum_headers(checksum, headers, always=True))
    extra.update(_sse_headers(store, bucket))
    extra.update(_cors_response_headers(store, bucket, headers, "PUT"))
    _record_request_metrics(store, bucket, key, "PUT", 200, bytes_up=len(data))
    return _done(store, _empty_response(200, extra))


def copy_object(store: ObjectStore, bucket: str, key: str, headers: dict) -> S3Response:
    """PUT with an `x-amz-copy-source` header — server-side copy. The source is
    `/<bucket>/<key>[?versionId=...]` (URL-encoded). MetadataDirective COPY (default)
    inherits the source's content-type + user metadata; REPLACE takes them from the
    request. Returns a CopyObjectResult XML body (SDKs parse ETag/LastModified there,
    NOT from headers) with the destination's version id in the header."""
    headers = {k.lower(): v for k, v in (headers or {}).items()}
    if not store.bucket_exists(bucket):
        return _error_xml("NoSuchBucket", "The specified bucket does not exist.", f"/{bucket}", 404)
    raw_src = headers.get("x-amz-copy-source", "")
    src, _, src_query = raw_src.partition("?")
    src = urllib.parse.unquote(src.lstrip("/"))
    src_bucket, _, src_key = src.partition("/")
    src_vid = None
    if src_query:
        src_vid = urllib.parse.parse_qs(src_query).get("versionId", [None])[0]
    if not store.bucket_exists(src_bucket):
        return _error_xml("NoSuchBucket", "The specified bucket does not exist.",
                          f"/{src_bucket}", 404)
    src_entry = _ensure_object_entry(store, src_bucket, src_key, create=False)
    src_obj = _find_version(src_entry, src_vid)
    if not src_obj or src_obj.get("is_delete_marker"):
        return _error_xml("NoSuchKey", "The specified key does not exist.",
                          f"/{src_bucket}/{src_key}", 404)

    directive = headers.get("x-amz-metadata-directive", "COPY").upper()
    if directive == "REPLACE":
        content_type = headers.get("content-type", "application/octet-stream")
        user_meta = {h[11:]: v for h, v in headers.items() if h.startswith("x-amz-meta-")}
    else:
        content_type = src_obj["content_type"]
        user_meta = copy.deepcopy(src_obj.get("metadata", {}))
    storage_class = headers.get("x-amz-storage-class", src_obj.get("storage_class", "STANDARD"))
    if headers.get("x-amz-tagging-directive", "COPY").upper() == "REPLACE":
        tags = dict(urllib.parse.parse_qsl(headers.get("x-amz-tagging", ""), keep_blank_values=True))
    else:
        tags = copy.deepcopy(src_obj.get("tags", {}))

    vstatus = store.versioning_status(bucket)
    vid = _new_version_id(store, bucket) if vstatus == "Enabled" else "null"
    version = _make_version_record(data=_version_bytes(store, src_bucket, src_key, src_obj),
                                   content_type=content_type,
                                   storage_class=storage_class, metadata=user_meta, tags=tags,
                                   version_id=vid, delete_marker=False)
    if src_obj.get("checksum"):
        version["checksum"] = dict(src_obj["checksum"])
    _apply_object_lock_on_write(store, bucket, headers, version)
    replace = "__overwrite__" if vstatus == "Disabled" else ("null" if vstatus == "Suspended" else None)
    entry = _write_object_version(store, bucket, key, version, replace_version_id=replace)
    _replicate(store, bucket, key, entry)
    _emit(store, bucket, key, "s3:ObjectCreated:Copy", entry, "CopyObject")
    store.persist()
    xml = ('<?xml version="1.0" encoding="UTF-8"?>'
           f'<CopyObjectResult xmlns="{S3_NS}">'
           f'<ETag>{version["etag"]}</ETag>'   # etag already carries literal quotes
           f'<LastModified>{version["last_modified"]}</LastModified>'
           '</CopyObjectResult>')
    extra = {"x-amz-version-id": entry.get("current_version_id", vid)}
    if src_vid:
        extra["x-amz-copy-source-version-id"] = src_vid
    extra.update(_sse_headers(store, bucket))
    return _xml_response(xml, status=200, extra=extra)


def head_object(store: ObjectStore, bucket: str, key: str, query: dict, headers: dict) -> S3Response:
    headers = {k.lower(): v for k, v in (headers or {}).items()}
    if not store.bucket_exists(bucket):
        return _error_xml("NoSuchBucket", "The specified bucket does not exist.", f"/{bucket}/{key}", 404)
    blocked = _request_payer_block(store, bucket, headers)
    if blocked:
        return blocked
    _apply_lifecycle(store, bucket)
    _apply_intelligent_tiering(store, bucket)
    entry = _ensure_object_entry(store, bucket, key, create=False)
    obj = _find_version(entry, (query or {}).get("versionId"))
    if obj and obj.get("is_delete_marker"):
        if (query or {}).get("versionId"):
            return _delete_marker_response(f"/{bucket}/{key}", obj.get("last_modified", _now()))
        _record_request_metrics(store, bucket, key, "HEAD", 404)
        return _error_xml("NoSuchKey", "The specified key does not exist.", f"/{bucket}/{key}", 404)
    if not obj:
        _record_request_metrics(store, bucket, key, "HEAD", 404)
        return _error_xml("NoSuchKey", "The specified key does not exist.", f"/{bucket}/{key}", 404)
    h = {"Content-Length": str(obj["size"]), "Content-Type": obj["content_type"],
         "ETag": obj["etag"], "Last-Modified": _iso_to_http_date(obj["last_modified"]),
         "x-amz-storage-class": obj.get("storage_class", "STANDARD"),
         "x-amz-version-id": obj.get("version_id", "null")}
    if obj.get("replication_status"):
        h["x-amz-replication-status"] = obj["replication_status"]
    if obj.get("archive_tier"):
        h["x-amz-archive-status"] = obj["archive_tier"]
    for k, v in obj.get("metadata", {}).items():
        h[f"x-amz-meta-{k}"] = v
    h.update(_sse_headers(store, bucket))
    h.update(_checksum_headers(obj.get("checksum"), headers))
    h.update(_cors_response_headers(store, bucket, headers, "HEAD"))
    h.update(_request_charged_header(headers))
    _record_request_metrics(store, bucket, key, "HEAD", 200)
    return _empty_response(200, h)


def get_object(store: ObjectStore, bucket: str, key: str, query: dict, headers: dict) -> S3Response:
    headers = {k.lower(): v for k, v in (headers or {}).items()}
    query = query or {}
    if not store.bucket_exists(bucket):
        return _error_xml("NoSuchBucket", "The specified bucket does not exist.", f"/{bucket}", 404)
    blocked = _request_payer_block(store, bucket, headers)
    if blocked:
        return blocked
    _apply_lifecycle(store, bucket)
    _apply_intelligent_tiering(store, bucket)
    entry = _ensure_object_entry(store, bucket, key, create=False)
    obj = _find_version(entry, query.get("versionId"))
    if obj and obj.get("is_delete_marker"):
        if query.get("versionId"):
            return _delete_marker_response(f"/{bucket}/{key}", obj.get("last_modified", _now()))
        _record_request_metrics(store, bucket, key, "GET", 404)
        return _error_xml("NoSuchKey", "The specified key does not exist.", f"/{bucket}/{key}", 404)
    if not obj:
        _record_request_metrics(store, bucket, key, "GET", 404)
        return _error_xml("NoSuchKey", "The specified key does not exist.", f"/{bucket}/{key}", 404)
    data = _version_bytes(store, bucket, key, obj)
    status = 200
    content_range = None
    rng = headers.get("range")
    if rng:
        m = re.match(r"bytes=(\d+)-(\d*)", rng)
        if m:
            start = int(m.group(1))
            end = int(m.group(2)) if m.group(2) else len(data) - 1
            end = min(end, len(data) - 1)
            data = data[start:end + 1]
            status = 206
            content_range = f"bytes {start}-{end}/{obj['size']}"
    h = {"Content-Type": obj["content_type"], "ETag": obj["etag"],
         "Last-Modified": _iso_to_http_date(obj["last_modified"]),
         "Content-Length": str(len(data)),
         "x-amz-storage-class": obj.get("storage_class", "STANDARD"),
         "x-amz-version-id": obj.get("version_id", "null"),
         "x-amz-request-id": _req_id(), "x-amz-id-2": uuid.uuid4().hex}
    if content_range:
        h["Content-Range"] = content_range
    if obj.get("replication_status"):
        h["x-amz-replication-status"] = obj["replication_status"]
    if obj.get("archive_tier"):
        h["x-amz-archive-status"] = obj["archive_tier"]
    for k, v in obj.get("metadata", {}).items():
        h[f"x-amz-meta-{k}"] = v
    h.update(_sse_headers(store, bucket))
    h.update(_checksum_headers(obj.get("checksum"), headers))
    h.update(_cors_response_headers(store, bucket, headers, "GET"))
    h.update(_request_charged_header(headers))
    _record_request_metrics(store, bucket, key, "GET", status, bytes_down=len(data))
    return S3Response(status=status, headers=h, body=data, media_type=obj["content_type"])


def delete_object(store: ObjectStore, bucket: str, key: str, query: dict, headers: dict) -> S3Response:
    query = query or {}
    if not store.bucket_exists(bucket):
        return _error_xml("NoSuchBucket", "The specified bucket does not exist.", f"/{bucket}", 404)
    vid = query.get("versionId")
    if vid:
        target = _find_version(_ensure_object_entry(store, bucket, key, create=False), vid)
        blocked = _lock_block(target, headers)
        if blocked:
            return blocked
        if not _delete_version(store, bucket, key, vid):
            return _error_xml("NoSuchVersion", "The specified version does not exist.", f"/{bucket}/{key}", 404)
        _mirror_current(store, bucket, key)
        _emit(store, bucket, key, "s3:ObjectRemoved:Delete", None, "DeleteObject")
        _record_request_metrics(store, bucket, key, "DELETE", 204)
        return _done(store, _empty_response(204, {"x-amz-version-id": vid}))
    status = store.versioning_status(bucket)
    if status == "Disabled":
        store.bucket_objects(bucket).pop(key, None)
        store.mirror_delete(bucket, key)
        _emit(store, bucket, key, "s3:ObjectRemoved:Delete", None, "DeleteObject")
        _record_request_metrics(store, bucket, key, "DELETE", 204)
        return _done(store, _empty_response(204))
    entry = _insert_simple_delete_marker(store, bucket, key)
    vid = entry.get("current_version_id", "null") if isinstance(entry, dict) else "null"
    _emit(store, bucket, key, "s3:ObjectRemoved:DeleteMarkerCreated", entry, "DeleteObject")
    _record_request_metrics(store, bucket, key, "DELETE", 204)
    return _done(store, _empty_response(204, {"x-amz-delete-marker": "true", "x-amz-version-id": vid}))


def _list_page(store: ObjectStore, bucket: str, prefix: str, delimiter: str,
               after: str, max_keys: int) -> tuple[list, list, bool, str]:
    """Visible (non-delete-marker) keys > `after`, rolled up by delimiter, paged by
    max_keys over keys + common prefixes in key order (the S3 semantics)."""
    bucket_objects = store.bucket_objects(bucket)
    rows: list = []          # (sort_key, kind, value)
    seen_cp: set = set()
    for key in sorted(bucket_objects):
        if prefix and not key.startswith(prefix):
            continue
        entry = bucket_objects[key]
        versions = entry.get("versions", []) if isinstance(entry, dict) else []
        if not versions or versions[0].get("is_delete_marker"):
            continue
        if delimiter:
            rest = key[len(prefix):]
            if delimiter in rest:
                cp = prefix + rest.split(delimiter, 1)[0] + delimiter
                if cp not in seen_cp and cp > after:
                    seen_cp.add(cp)
                    rows.append((cp, "cp", cp))
                continue
        if key > after:
            rows.append((key, "key", (key, versions[0])))
    truncated = len(rows) > max_keys
    rows = rows[:max_keys]
    keys = [r[2] for r in rows if r[1] == "key"]
    cps = [r[2] for r in rows if r[1] == "cp"]
    return keys, cps, truncated, (rows[-1][0] if (truncated and rows) else "")


def _max_keys(query: dict) -> int:
    try:
        return max(0, min(int(query.get("max-keys", 1000)), 1000))
    except (TypeError, ValueError):
        return 1000


def _contents_xml(keys: list, owner: bool) -> list:
    out = []
    for key, v in keys:
        out += ["<Contents>", f"<Key>{_xml_escape(key)}</Key>",
                f"<LastModified>{v.get('last_modified', _now())}</LastModified>",
                f"<ETag>{v.get('etag', '')}</ETag>", f"<Size>{v.get('size', 0)}</Size>",
                f"<StorageClass>{v.get('storage_class', 'STANDARD')}</StorageClass>",
                _OWNER_XML if owner else "", "</Contents>"]
    return out


def list_objects_v2(store: ObjectStore, bucket: str, query: dict) -> S3Response:
    query = query or {}
    if not store.bucket_exists(bucket):
        return _error_xml("NoSuchBucket", "The specified bucket does not exist.", f"/{bucket}", 404)
    _apply_lifecycle(store, bucket)
    _apply_inventory(store, bucket)
    prefix = query.get("prefix", "") or ""
    delimiter = query.get("delimiter", "") or ""
    token = query.get("continuation-token", "") or ""
    start_after = query.get("start-after", "") or ""
    max_keys = _max_keys(query)
    keys, cps, truncated, nxt = _list_page(store, bucket, prefix, delimiter, token or start_after, max_keys)
    parts = ['<?xml version="1.0" encoding="UTF-8"?>', f'<ListBucketResult xmlns="{S3_NS}">',
             f"<Name>{bucket}</Name>", f"<Prefix>{_xml_escape(prefix)}</Prefix>",
             f"<KeyCount>{len(keys) + len(cps)}</KeyCount>", f"<MaxKeys>{max_keys}</MaxKeys>",
             f"<Delimiter>{_xml_escape(delimiter)}</Delimiter>" if delimiter else "",
             f"<IsTruncated>{'true' if truncated else 'false'}</IsTruncated>",
             f"<ContinuationToken>{_xml_escape(token)}</ContinuationToken>" if token else "",
             f"<NextContinuationToken>{_xml_escape(nxt)}</NextContinuationToken>" if truncated else "",
             f"<StartAfter>{_xml_escape(start_after)}</StartAfter>" if start_after else ""]
    parts += _contents_xml(keys, owner=True)
    for cp in cps:
        parts += ["<CommonPrefixes>", f"<Prefix>{_xml_escape(cp)}</Prefix>", "</CommonPrefixes>"]
    parts.append("</ListBucketResult>")
    _record_request_metrics(store, bucket, "", "LIST", 200)
    return _xml_response("".join(parts))


def list_objects_v1(store: ObjectStore, bucket: str, query: dict) -> S3Response:
    """GET /{bucket} without list-type=2 — ListObjects (V1, marker paging)."""
    query = query or {}
    if not store.bucket_exists(bucket):
        return _error_xml("NoSuchBucket", "The specified bucket does not exist.", f"/{bucket}", 404)
    _apply_lifecycle(store, bucket)
    _apply_inventory(store, bucket)
    prefix = query.get("prefix", "") or ""
    delimiter = query.get("delimiter", "") or ""
    marker = query.get("marker", "") or ""
    max_keys = _max_keys(query)
    keys, cps, truncated, nxt = _list_page(store, bucket, prefix, delimiter, marker, max_keys)
    parts = ['<?xml version="1.0" encoding="UTF-8"?>', f'<ListBucketResult xmlns="{S3_NS}">',
             f"<Name>{bucket}</Name>", f"<Prefix>{_xml_escape(prefix)}</Prefix>",
             f"<Marker>{_xml_escape(marker)}</Marker>", f"<MaxKeys>{max_keys}</MaxKeys>",
             f"<Delimiter>{_xml_escape(delimiter)}</Delimiter>" if delimiter else "",
             f"<IsTruncated>{'true' if truncated else 'false'}</IsTruncated>",
             f"<NextMarker>{_xml_escape(nxt)}</NextMarker>" if truncated else ""]
    parts += _contents_xml(keys, owner=True)
    for cp in cps:
        parts += ["<CommonPrefixes>", f"<Prefix>{_xml_escape(cp)}</Prefix>", "</CommonPrefixes>"]
    parts.append("</ListBucketResult>")
    _record_request_metrics(store, bucket, "", "LIST", 200)
    return _xml_response("".join(parts))


def _list_object_versions(store: ObjectStore, bucket: str, query: dict) -> S3Response:
    """GET /{bucket}?versions — ListObjectVersions. The data is already there (every
    PUT/DELETE keeps its version chain in the object entry); this just walks it."""
    _apply_lifecycle(store, bucket)
    prefix = (query or {}).get("prefix", "") or ""
    bucket_objects = store.bucket_objects(bucket)
    parts = ['<?xml version="1.0" encoding="UTF-8"?>', f'<ListVersionsResult xmlns="{S3_NS}">',
             f"<Name>{bucket}</Name>", f"<Prefix>{prefix}</Prefix>",
             "<KeyMarker></KeyMarker>", "<VersionIdMarker></VersionIdMarker>", "<IsTruncated>false</IsTruncated>"]
    owner = "<Owner><ID>simulator</ID><DisplayName>cloudlearn-simulator</DisplayName></Owner>"
    for key in sorted(bucket_objects):
        if prefix and not key.startswith(prefix):
            continue
        entry = bucket_objects[key]
        for v in entry.get("versions", []) if isinstance(entry, dict) else []:
            is_latest = f"<IsLatest>{'true' if v.get('is_latest') else 'false'}</IsLatest>"
            last_modified = f"<LastModified>{v.get('last_modified', _now())}</LastModified>"
            version_id = f"<VersionId>{v.get('version_id', 'null')}</VersionId>"
            if v.get("is_delete_marker"):
                parts += ["<DeleteMarker>", f"<Key>{key}</Key>", version_id, is_latest, last_modified, owner, "</DeleteMarker>"]
            else:
                parts += ["<Version>", f"<Key>{key}</Key>", version_id, is_latest, last_modified,
                          f"<ETag>{v.get('etag', '')}</ETag>", f"<Size>{v.get('size', 0)}</Size>",
                          f"<StorageClass>{v.get('storage_class', 'STANDARD')}</StorageClass>", owner, "</Version>"]
    parts.append("</ListVersionsResult>")
    return _xml_response("".join(parts))


# ── native-S3 wire dispatcher (method + path → operation) ─────────────────
# The single routing point for the native AWS S3 wire protocol — what an
# unmodified aws-cli / SDK speaks. Shared by the Nano relay/bridge (tab side)
# and, on convergence, the appliance's routes/aws_s3.py. Path is the raw
# request path, e.g. "/my-bucket/a/key.txt".
# ── multipart upload ──────────────────────────────────────────────────────
def _mpu(store: ObjectStore) -> dict:
    """The in-progress multipart uploads, kept on the store (like the base object
    map). upload_id -> {bucket, key, content_type, metadata, parts:{n:{etag,data}}}."""
    m = getattr(store, "_multipart_uploads", None)
    if m is None:
        m = {}
        store._multipart_uploads = m
    return m


def create_multipart_upload(store, bucket, key, headers) -> S3Response:
    headers = {k.lower(): v for k, v in (headers or {}).items()}
    if not store.bucket_exists(bucket):
        return _error_xml("NoSuchBucket", "The specified bucket does not exist.", f"/{bucket}", 404)
    upload_id = uuid.uuid4().hex + uuid.uuid4().hex
    _mpu(store)[upload_id] = {
        "bucket": bucket, "key": key,
        "content_type": headers.get("content-type", "application/octet-stream"),
        "metadata": {h[11:]: v for h, v in headers.items() if h.startswith("x-amz-meta-")},
        "storage_class": headers.get("x-amz-storage-class", "STANDARD"),
        "lock_headers": {h: v for h, v in headers.items() if h.startswith("x-amz-object-lock-")},
        "parts": {},
        "initiated": _now(),
    }
    xml = ('<?xml version="1.0" encoding="UTF-8"?>'
           f'<InitiateMultipartUploadResult xmlns="{S3_NS}">'
           f'<Bucket>{bucket}</Bucket><Key>{_xml_escape(key)}</Key>'
           f'<UploadId>{upload_id}</UploadId></InitiateMultipartUploadResult>')
    return _done(store, _xml_response(xml, status=200))


def _parts(up: dict) -> dict:
    """upload["parts"] keyed by int part number (a JSON-persisted upload comes back
    with string keys)."""
    parts = up.get("parts")
    if not isinstance(parts, dict):
        parts = up["parts"] = {}
    if any(not isinstance(k, int) for k in parts):
        parts = {int(k): v for k, v in parts.items()}
        up["parts"] = parts
    return parts


def upload_part(store, bucket, key, query, body) -> S3Response:
    upload_id = query.get("uploadId", "")
    up = _mpu(store).get(upload_id)
    if not up or up["bucket"] != bucket or up["key"] != key:
        return _error_xml("NoSuchUpload", "The specified upload does not exist.", f"/{bucket}/{key}", 404)
    try:
        part_number = int(query.get("partNumber", "0"))
    except ValueError:
        part_number = 0
    if part_number < 1 or part_number > 10000:
        return _error_xml("InvalidArgument", "Part number must be 1..10000.", f"/{bucket}/{key}", 400)
    data = bytes(body or b"")
    etag = _etag(data)
    _parts(up)[part_number] = {"etag": etag, "data": data, "size": len(data)}
    return _done(store, _empty_response(200, {"ETag": etag}))


def list_parts(store, bucket, key, query) -> S3Response:
    upload_id = query.get("uploadId", "")
    up = _mpu(store).get(upload_id)
    if not up:
        return _error_xml("NoSuchUpload", "The specified upload does not exist.", f"/{bucket}/{key}", 404)
    parts_xml = "".join(
        f"<Part><PartNumber>{n}</PartNumber><ETag>{p['etag']}</ETag>"
        f"<Size>{len(p['data'])}</Size></Part>"
        for n, p in sorted(_parts(up).items()))
    xml = ('<?xml version="1.0" encoding="UTF-8"?>'
           f'<ListPartsResult xmlns="{S3_NS}"><Bucket>{bucket}</Bucket>'
           f'<Key>{_xml_escape(key)}</Key><UploadId>{upload_id}</UploadId>'
           f'{parts_xml}</ListPartsResult>')
    return _xml_response(xml, status=200)


def abort_multipart_upload(store, bucket, key, query) -> S3Response:
    upload_id = query.get("uploadId", "")
    if _mpu(store).pop(upload_id, None) is None:
        return _error_xml("NoSuchUpload", "The specified upload does not exist.", f"/{bucket}/{key}", 404)
    return _done(store, _empty_response(204))


def _multipart_etag(parts: list) -> str:
    """The canonical S3 multipart ETag: md5 of the concatenated binary md5s of each
    part, hex, suffixed with `-{partcount}`."""
    digests = b"".join(hashlib.md5(p["data"]).digest() for p in parts)
    return f'"{hashlib.md5(digests).hexdigest()}-{len(parts)}"'


def complete_multipart_upload(store, bucket, key, query, body) -> S3Response:
    upload_id = query.get("uploadId", "")
    up = _mpu(store).get(upload_id)
    if not up or up["bucket"] != bucket or up["key"] != key:
        return _error_xml("NoSuchUpload", "The specified upload does not exist.", f"/{bucket}/{key}", 404)
    # Honor the caller's part list + order when supplied; else all stored parts.
    requested = [int(n) for n in re.findall(r"<PartNumber>\s*(\d+)\s*</PartNumber>", body.decode("utf-8", "ignore"))] \
        if body else []
    stored = _parts(up)
    order = requested or sorted(stored)
    if not order:
        return _error_xml("InvalidRequest", "You must specify at least one part.", f"/{bucket}/{key}", 400)
    parts = []
    for n in order:
        p = stored.get(n)
        if p is None:
            return _error_xml("InvalidPart", f"Part {n} was not uploaded.", f"/{bucket}/{key}", 400)
        parts.append(p)
    data = b"".join(bytes(p["data"]) for p in parts)
    etag = _multipart_etag(parts)
    vstatus = store.versioning_status(bucket)
    vid = _new_version_id(store, bucket) if vstatus == "Enabled" else "null"
    version = _make_version_record(data=data, content_type=up["content_type"],
                                   storage_class=up.get("storage_class", "STANDARD"),
                                   metadata=up.get("metadata") or {},
                                   version_id=vid, delete_marker=False, etag=etag)
    _apply_object_lock_on_write(store, bucket, up.get("lock_headers") or {}, version)
    replace = "__overwrite__" if vstatus == "Disabled" else ("null" if vstatus == "Suspended" else None)
    entry = _write_object_version(store, bucket, key, version, replace_version_id=replace)
    _replicate(store, bucket, key, entry)
    _mpu(store).pop(upload_id, None)
    _emit(store, bucket, key, "s3:ObjectCreated:CompleteMultipartUpload", entry, "CompleteMultipartUpload")
    store.persist()
    xml = ('<?xml version="1.0" encoding="UTF-8"?>'
           f'<CompleteMultipartUploadResult xmlns="{S3_NS}">'
           f'<Location>/{bucket}/{_xml_escape(key)}</Location>'
           f'<Bucket>{bucket}</Bucket><Key>{_xml_escape(key)}</Key>'
           f'<ETag>{etag}</ETag></CompleteMultipartUploadResult>')
    return _xml_response(xml, status=200, extra=_sse_headers(store, bucket))


def list_all_buckets(store: ObjectStore) -> S3Response:
    """Service-level GET / → ListAllMyBuckets (what `aws s3 ls` / list_buckets send)."""
    rows = []
    buckets = getattr(store, "buckets", {}) or {}
    for name in sorted(buckets):
        meta = buckets.get(name) if hasattr(buckets, "get") else None
        created = ((meta.get("creation_date") or meta.get("created")) if isinstance(meta, dict) else None) or _now()
        rows.append(f"<Bucket><Name>{_xml_escape(name)}</Name>"
                    f"<CreationDate>{created}</CreationDate></Bucket>")
    xml = ('<?xml version="1.0" encoding="UTF-8"?>'
           '<ListAllMyBucketsResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
           '<Owner><ID>simulator</ID><DisplayName>cloudlearn-simulator</DisplayName></Owner>'
           f'<Buckets>{"".join(rows)}</Buckets></ListAllMyBucketsResult>')
    return _xml_response(xml, 200)


# ── Bucket sub-resources (?versioning, ?tagging, …) ──────────────────────────────────
# Stored in the bucket's own dict (store.buckets[name]) so every substrate persists them
# with the bucket. PUT bodies are kept verbatim and returned by GET (S3 round-trips the
# document); anything Vyomi does not model returns 501 NotImplemented — never a silent
# 200 or an object listing, which would let an SDK or the console believe it worked.
_SUBRESOURCES_STORED = {
    # query key: (element returned when absent → 404 code, or None = has a default)
    "tagging": "NoSuchTagSet",
    "encryption": "ServerSideEncryptionConfigurationNotFoundError",
    "publicAccessBlock": "NoSuchPublicAccessBlockConfiguration",
    "policy": "NoSuchBucketPolicy",
    "lifecycle": "NoSuchLifecycleConfiguration",
    "cors": "NoSuchCORSConfiguration",
    "ownershipControls": "OwnershipControlsNotFoundError",
    "replication": "ReplicationConfigurationNotFoundError",
}
# Sub-resources whose PUT body must be well-formed XML (validated like real S3).
_SUBRESOURCES_XML = ("tagging", "encryption", "publicAccessBlock", "lifecycle", "cors", "ownershipControls", "replication")
# query key → id-keyed config store key, list/item XML tags (BUILD: stored+returned verbatim,
# not enforced — Vyomi runs neither the long-horizon tiering scheduler nor the CloudWatch
# metrics/inventory export pipelines these configure).
_ID_KEYED_SUBRESOURCES = {
    "intelligent-tiering": ("it_configs", "ListBucketIntelligentTieringConfigurationsOutput", "NoSuchConfiguration"),
    "inventory": ("inv_configs", "ListInventoryConfigurationsResult", "NoSuchConfiguration"),
    "metrics": ("metrics_configs", "ListBucketMetricsConfigurationsResult", "NoSuchConfiguration"),
}
_SUBRESOURCES_UNSUPPORTED = (
    "accelerate", "analytics", "object-lock",
)
_NS = 'xmlns="http://s3.amazonaws.com/doc/2006-03-01/"'


def _list_multipart_uploads(store: ObjectStore, bucket: str, query: dict) -> S3Response:
    _apply_lifecycle_mpu(store, bucket)
    prefix = (query or {}).get("prefix", "") or ""
    rows = []
    for uid, up in sorted(_mpu(store).items(), key=lambda kv: (kv[1].get("key", ""), kv[0])):
        if up.get("bucket") != bucket or not str(up.get("key", "")).startswith(prefix):
            continue
        rows.append(f"<Upload><Key>{_xml_escape(up.get('key', ''))}</Key><UploadId>{uid}</UploadId>"
                    f"<Initiator><ID>simulator</ID><DisplayName>cloudlearn-simulator</DisplayName></Initiator>"
                    f"{_OWNER_XML}<StorageClass>{up.get('storage_class', 'STANDARD')}</StorageClass>"
                    f"<Initiated>{up.get('initiated') or _now()}</Initiated></Upload>")
    xml = (f'<?xml version="1.0" encoding="UTF-8"?><ListMultipartUploadsResult xmlns="{S3_NS}">'
           f"<Bucket>{bucket}</Bucket><KeyMarker></KeyMarker><UploadIdMarker></UploadIdMarker>"
           f"<NextKeyMarker></NextKeyMarker><NextUploadIdMarker></NextUploadIdMarker>"
           f"<Prefix>{_xml_escape(prefix)}</Prefix><MaxUploads>1000</MaxUploads>"
           f"<IsTruncated>false</IsTruncated>{''.join(rows)}</ListMultipartUploadsResult>")
    return _xml_response(xml)


def _bucket_subresource(store: ObjectStore, method: str, bucket: str, query: dict,
                        headers: dict, body: bytes) -> S3Response | None:
    sub = next((k for k in ("versioning", "location", "acl", "object-lock", "versions", "notification",
                            "uploads", "website", "logging", "requestPayment",
                            *_ID_KEYED_SUBRESOURCES, *_SUBRESOURCES_STORED) if k in query), None)
    if sub is None:
        sub = next((k for k in _SUBRESOURCES_UNSUPPORTED if k in query), None)
        if sub is None:
            return None
    if sub == "uploads" and method != "GET":
        return None
    if not store.bucket_exists(bucket):
        return _error_xml("NoSuchBucket", "The specified bucket does not exist", f"/{bucket}", 404)
    meta = store.buckets[bucket]
    cfg = meta.setdefault("cfg", {})
    if sub == "versioning":
        if method == "GET":
            st = meta.get("versioning", "Disabled")
            inner = f"<Status>{st}</Status>" if st in ("Enabled", "Suspended") else ""
            return _xml_response(f'<?xml version="1.0" encoding="UTF-8"?><VersioningConfiguration {_NS}>{inner}</VersioningConfiguration>')
        if method == "PUT":
            m = re.search(r"<Status>\s*(Enabled|Suspended)\s*</Status>", body.decode("utf-8", "replace"))
            if not m:
                return _error_xml("MalformedXML", "The XML you provided was not well-formed or did not validate against our published schema.", f"/{bucket}", 400)
            meta["versioning"] = m.group(1)
            return _done(store, _empty_response(200))
    elif sub == "location":
        if method == "GET":
            region = meta.get("region", "")
            inner = region if region and region != "us-east-1" else ""
            return _xml_response(f'<?xml version="1.0" encoding="UTF-8"?><LocationConstraint {_NS}>{inner}</LocationConstraint>')
    elif sub == "acl":
        if method == "GET":
            return _xml_response(meta.get("acl") or _default_acl_xml())
        if method == "PUT":
            canned = (headers or {}).get("x-amz-acl")
            text = (body or b"").decode("utf-8", "replace").strip()
            if text or canned:
                blocked = _acl_blocked_by_ownership(store, bucket) or _acl_blocked_by_pab(store, bucket, canned)
                if blocked:
                    return blocked
            if text:
                try:
                    ET.fromstring(text)
                except ET.ParseError:
                    return _error_xml("MalformedACLError", "The XML you provided was not well-formed or did not validate against our published schema.", f"/{bucket}", 400)
                meta["acl"] = text
            elif canned:
                meta["acl"] = _canned_acl_xml(canned)
            if canned:
                meta["canned_acl"] = canned
            return _done(store, _empty_response(200))
    elif sub == "notification":
        if method == "GET":
            return _xml_response(notification_xml(bucket_notifications(store, bucket)))
        if method == "PUT":
            parsed = parse_notification_xml(body or b"")
            if isinstance(parsed, S3Response):
                return parsed
            parsed["deliveries"] = bucket_notifications(store, bucket).get("deliveries", [])
            meta["notifications"] = parsed
            if (body or b"").strip():
                _emit(store, bucket, "", "s3:TestEvent", None, "PutBucketNotificationConfiguration")
            return _done(store, _empty_response(200))
        if method == "DELETE":
            meta["notifications"] = default_notifications()
            return _done(store, _empty_response(204))
    elif sub == "website":
        if method == "GET":
            doc = meta.get("website")
            if doc is None:
                return _error_xml("NoSuchWebsiteConfiguration", "The specified bucket does not have a website configuration", f"/{bucket}", 404)
            return _xml_response(doc)
        if method == "PUT":
            text = (body or b"").decode("utf-8", "replace").strip()
            if not text:
                return _error_xml("MalformedXML", "The XML you provided was not well-formed or did not validate against our published schema.", f"/{bucket}", 400)
            try:
                ET.fromstring(text)
            except ET.ParseError:
                return _error_xml("MalformedXML", "The XML you provided was not well-formed or did not validate against our published schema.", f"/{bucket}", 400)
            meta["website"] = text
            return _done(store, _empty_response(200))
        if method == "DELETE":
            meta.pop("website", None)
            return _done(store, _empty_response(204))
    elif sub == "logging":
        if method == "GET":
            doc = meta.get("logging") or f'<?xml version="1.0" encoding="UTF-8"?><BucketLoggingStatus {_NS}/>'
            return _xml_response(doc)
        if method == "PUT":
            text = (body or b"").decode("utf-8", "replace").strip()
            if text:
                try:
                    ET.fromstring(text)
                except ET.ParseError:
                    return _error_xml("MalformedXML", "The XML you provided was not well-formed or did not validate against our published schema.", f"/{bucket}", 400)
                meta["logging"] = text
            else:
                meta.pop("logging", None)
            return _done(store, _empty_response(200))
    elif sub == "requestPayment":
        if method == "GET":
            payer = meta.get("payer", "BucketOwner")
            return _xml_response(f'<?xml version="1.0" encoding="UTF-8"?><RequestPaymentConfiguration {_NS}><Payer>{payer}</Payer></RequestPaymentConfiguration>')
        if method == "PUT":
            text = (body or b"").decode("utf-8", "replace")
            m = re.search(r"<Payer>\s*(BucketOwner|Requester)\s*</Payer>", text)
            if not m:
                return _error_xml("MalformedXML", "The XML you provided was not well-formed or did not validate against our published schema.", f"/{bucket}", 400)
            meta["payer"] = m.group(1)
            return _done(store, _empty_response(200))
    elif sub in _ID_KEYED_SUBRESOURCES:
        store_key, list_tag, not_found_code = _ID_KEYED_SUBRESOURCES[sub]
        configs = meta.setdefault(store_key, {})
        cfg_id = (query or {}).get("id")
        if sub == "inventory" and method == "GET":
            _apply_inventory(store, bucket)   # checking the config is also when a manifest is due
        if method == "GET":
            if cfg_id:
                doc = configs.get(cfg_id)
                if doc is None:
                    return _error_xml(not_found_code, "The specified configuration does not exist.", f"/{bucket}", 404)
                return _xml_response(doc)
            items = "".join(_strip_xml_decl(v) for v in configs.values())
            return _xml_response(f'<?xml version="1.0" encoding="UTF-8"?><{list_tag} {_NS}><IsTruncated>false</IsTruncated>{items}</{list_tag}>')
        if not cfg_id:
            return _error_xml("InvalidArgument", "The id parameter must be specified.", f"/{bucket}", 400)
        if method == "PUT":
            text = (body or b"").decode("utf-8", "replace").strip()
            if not text:
                return _error_xml("MalformedXML", "The XML you provided was not well-formed or did not validate against our published schema.", f"/{bucket}", 400)
            try:
                ET.fromstring(text)
            except ET.ParseError:
                return _error_xml("MalformedXML", "The XML you provided was not well-formed or did not validate against our published schema.", f"/{bucket}", 400)
            configs[cfg_id] = text
            return _done(store, _empty_response(200))
        if method == "DELETE":
            configs.pop(cfg_id, None)
            return _done(store, _empty_response(204))
    elif sub == "object-lock":
        if not meta.get("object_lock"):
            if method == "GET":
                return _error_xml("ObjectLockConfigurationNotFoundError", "Object Lock configuration does not exist for this bucket", f"/{bucket}", 404)
            if method == "PUT":
                return _error_xml("InvalidBucketState", "Object Lock configuration cannot be enabled on a bucket that was not created with Object Lock enabled.", f"/{bucket}", 409)
        else:
            if method == "GET":
                default = meta.get("object_lock_default_retention")
                rule_xml = ""
                if default:
                    period = (f"<Days>{default['days']}</Days>" if default.get("days") is not None
                              else f"<Years>{default['years']}</Years>")
                    rule_xml = f"<Rule><DefaultRetention><Mode>{default['mode']}</Mode>{period}</DefaultRetention></Rule>"
                return _xml_response(f'<?xml version="1.0" encoding="UTF-8"?><ObjectLockConfiguration {_NS}><ObjectLockEnabled>Enabled</ObjectLockEnabled>{rule_xml}</ObjectLockConfiguration>')
            if method == "PUT":
                text = (body or b"").decode("utf-8", "replace").strip()
                if text:
                    try:
                        root = ET.fromstring(text)
                    except ET.ParseError:
                        return _error_xml("MalformedXML", "The XML you provided was not well-formed or did not validate against our published schema.", f"/{bucket}", 400)
                    rule = _child(root, "Rule")
                    default_ret = _child(rule, "DefaultRetention") if rule is not None else None
                    if default_ret is not None:
                        mode = _child_text(default_ret, "Mode")
                        days = _child_text(default_ret, "Days")
                        years = _child_text(default_ret, "Years")
                        if mode not in ("GOVERNANCE", "COMPLIANCE") or not (days or years):
                            return _error_xml("MalformedXML", "DefaultRetention requires Mode and one of Days/Years.", f"/{bucket}", 400)
                        meta["object_lock_default_retention"] = {
                            "mode": mode,
                            "days": int(days) if days else None,
                            "years": int(years) if years else None,
                        }
                    else:
                        meta.pop("object_lock_default_retention", None)
                return _done(store, _empty_response(200))
    elif sub == "versions":
        if method == "GET":
            return _list_object_versions(store, bucket, query)
    elif sub == "uploads":
        return _list_multipart_uploads(store, bucket, query)
    elif sub in _SUBRESOURCES_STORED:
        if method == "GET":
            doc = cfg.get(sub)
            if doc is None and sub == "tagging" and meta.get("tags"):
                doc = build_tagging_xml(meta["tags"])          # tags set by the console REST
            if doc is None and sub in ("cors", "lifecycle") and isinstance(meta.get(sub), str):
                doc = meta[sub]                                   # pre-v4 appliance layout
            if doc is None:
                return _error_xml(_SUBRESOURCES_STORED[sub], f"The {sub} configuration does not exist", f"/{bucket}", 404)
            if sub == "policy":
                return S3Response(status=200, headers=_amz_headers({"Content-Type": "application/json"}), body=doc.encode())
            return _xml_response(doc)
        if method == "PUT":
            text = body.decode("utf-8", "replace").strip()
            if not text:
                return _error_xml("MalformedXML" if sub != "policy" else "MalformedPolicy", "The request body is empty.", f"/{bucket}", 400)
            if sub in _SUBRESOURCES_XML:
                try:
                    ET.fromstring(text)
                except ET.ParseError:
                    return _error_xml("MalformedXML", "The XML you provided was not well-formed or did not validate against our published schema.", f"/{bucket}", 400)
            if sub == "policy":
                try:
                    parsed_policy = json.loads(text)
                except Exception:
                    return _error_xml("MalformedPolicy", "Policy document must be valid JSON.", f"/{bucket}", 400)
                if _policy_is_public(parsed_policy) and _public_access_block(store, bucket)["BlockPublicPolicy"]:
                    return _error_xml("AccessDenied",
                                      "This request is not allowed because the bucket owner enforced the "
                                      "Block Public Access setting that disallows public bucket policies.", f"/{bucket}", 403)
            if sub == "replication" and store.versioning_status(bucket) != "Enabled":
                return _error_xml("InvalidRequest", "Versioning must be 'Enabled' on the bucket to apply a replication configuration.", f"/{bucket}", 400)
            cfg[sub] = text
            if sub == "tagging":
                meta["tags"] = parse_tagging_xml(text.encode("utf-8"))
            if sub in ("cors", "lifecycle"):
                meta.pop(sub, None)
            return _done(store, _empty_response(204 if sub in ("tagging", "policy", "cors", "lifecycle") else 200))
        if method == "DELETE":
            cfg.pop(sub, None)
            if sub == "tagging":
                meta["tags"] = {}
            if sub in ("cors", "lifecycle"):
                meta.pop(sub, None)
            return _done(store, _empty_response(204))
    return _error_xml("NotImplemented", f"Vyomi does not implement the bucket {sub} sub-resource yet.", f"/{bucket}?{sub}", 501)


# ── object sub-resources (?tagging, ?acl, ?retention, ?legal-hold) ────────────────
def _object_subresource(store: ObjectStore, method: str, bucket: str, key: str,
                        query: dict, headers: dict, body: bytes) -> S3Response | None:
    sub = next((k for k in ("tagging", "acl", "retention", "legal-hold") if k in query), None)
    if sub is None:
        return None
    if not store.bucket_exists(bucket):
        return _error_xml("NoSuchBucket", "The specified bucket does not exist.", f"/{bucket}", 404)
    entry = _ensure_object_entry(store, bucket, key, create=False)
    vid = query.get("versionId")
    obj = _find_version(entry, vid) if entry else None
    if not obj or obj.get("is_delete_marker"):
        return _error_xml("NoSuchKey", "The specified key does not exist.", f"/{bucket}/{key}", 404)
    extra = {"x-amz-version-id": obj.get("version_id", "null")}
    if sub in ("retention", "legal-hold") and not (store.buckets.get(bucket) or {}).get("object_lock"):
        return _error_xml("InvalidRequest", "Bucket is missing Object Lock Configuration", f"/{bucket}/{key}", 400)
    if sub == "tagging":
        if method == "GET":
            return _xml_response(build_tagging_xml(obj.get("tags", {})), extra=extra)
        if method == "PUT":
            try:
                ET.fromstring(body or b"")
            except ET.ParseError:
                return _error_xml("MalformedXML", "The XML you provided was not well-formed or did not validate against our published schema.", f"/{bucket}/{key}", 400)
            obj["tags"] = parse_tagging_xml(body)
        elif method == "DELETE":
            obj["tags"] = {}
        else:
            return _error_xml("MethodNotAllowed", method, f"/{bucket}/{key}", 405)
        _refresh_object_entry(entry)
        return _done(store, _empty_response(204 if method == "DELETE" else 200, extra))
    if sub == "retention":
        if method == "GET":
            ret = obj.get("retention")
            if not ret:
                return _error_xml("NoSuchObjectLockConfiguration", "The specified object does not have a ObjectLockConfiguration set.", f"/{bucket}/{key}", 404)
            return _xml_response(f'<?xml version="1.0" encoding="UTF-8"?><Retention {_NS}><Mode>{ret["mode"]}</Mode><RetainUntilDate>{ret["retain_until"]}</RetainUntilDate></Retention>', extra=extra)
        if method == "PUT":
            try:
                root = ET.fromstring(body or b"")
            except ET.ParseError:
                return _error_xml("MalformedXML", "The XML you provided was not well-formed or did not validate against our published schema.", f"/{bucket}/{key}", 400)
            mode = _child_text(root, "Mode")
            until = _child_text(root, "RetainUntilDate")
            if mode not in ("GOVERNANCE", "COMPLIANCE") or not until:
                return _error_xml("MalformedXML", "Mode and RetainUntilDate are required.", f"/{bucket}/{key}", 400)
            blocked = _lock_block(obj, headers)
            if blocked:
                return blocked
            obj["retention"] = {"mode": mode, "retain_until": until}
            return _done(store, _empty_response(200, extra))
        return _error_xml("MethodNotAllowed", method, f"/{bucket}/{key}", 405)
    if sub == "legal-hold":
        if method == "GET":
            return _xml_response(f'<?xml version="1.0" encoding="UTF-8"?><LegalHold {_NS}><Status>{obj.get("legal_hold", "OFF")}</Status></LegalHold>', extra=extra)
        if method == "PUT":
            try:
                root = ET.fromstring(body or b"")
            except ET.ParseError:
                return _error_xml("MalformedXML", "The XML you provided was not well-formed or did not validate against our published schema.", f"/{bucket}/{key}", 400)
            status = _child_text(root, "Status")
            if status not in ("ON", "OFF"):
                return _error_xml("MalformedXML", "Status must be ON or OFF.", f"/{bucket}/{key}", 400)
            obj["legal_hold"] = status
            return _done(store, _empty_response(200, extra))
        return _error_xml("MethodNotAllowed", method, f"/{bucket}/{key}", 405)
    # acl
    if method == "GET":
        return _xml_response(obj.get("acl") or _default_acl_xml(), extra=extra)
    if method == "PUT":
        canned = (headers or {}).get("x-amz-acl")
        text = (body or b"").decode("utf-8", "replace").strip()
        if text or canned:
            blocked = _acl_blocked_by_ownership(store, bucket) or _acl_blocked_by_pab(store, bucket, canned)
            if blocked:
                return blocked
        if text:
            obj["acl"] = text
        elif canned:
            obj["acl"] = _canned_acl_xml(canned)
        return _done(store, _empty_response(200, extra))
    return _error_xml("MethodNotAllowed", method, f"/{bucket}/{key}", 405)


def delete_objects(store: ObjectStore, bucket: str, body: bytes, headers: dict | None = None) -> S3Response:
    """POST /{bucket}?delete — DeleteObjects (what `aws s3 rm --recursive` sends)."""
    if not store.bucket_exists(bucket):
        return _error_xml("NoSuchBucket", "The specified bucket does not exist.", f"/{bucket}", 404)
    try:
        root = ET.fromstring(body or b"")
    except ET.ParseError:
        return _error_xml("MalformedXML", "The XML you provided was not well-formed or did not validate against our published schema.", f"/{bucket}", 400)
    quiet = _child_text(root, "Quiet").lower() == "true"
    out = []
    for el in _children(root, "Object"):
        key = _child_text(el, "Key")
        if not key:
            continue
        vid = _child_text(el, "VersionId")
        if vid:
            blocked = _lock_block(_find_version(_ensure_object_entry(store, bucket, key, create=False), vid), headers)
            if blocked:
                out.append(f"<Error><Key>{_xml_escape(key)}</Key><VersionId>{_xml_escape(vid)}</VersionId>"
                           "<Code>AccessDenied</Code><Message>Object is WORM-protected or under legal hold.</Message></Error>")
                continue
            if not _delete_version(store, bucket, key, vid):
                out.append(f"<Error><Key>{_xml_escape(key)}</Key><VersionId>{_xml_escape(vid)}</VersionId>"
                           "<Code>NoSuchVersion</Code><Message>The specified version does not exist.</Message></Error>")
                continue
            _mirror_current(store, bucket, key)
            _emit(store, bucket, key, "s3:ObjectRemoved:Delete", None, "DeleteObjects")
            if not quiet:
                out.append(f"<Deleted><Key>{_xml_escape(key)}</Key><VersionId>{_xml_escape(vid)}</VersionId></Deleted>")
            continue
        exists = key in store.bucket_objects(bucket)
        if store.versioning_status(bucket) == "Disabled":
            if exists:
                store.bucket_objects(bucket).pop(key, None)
                store.mirror_delete(bucket, key)
                _emit(store, bucket, key, "s3:ObjectRemoved:Delete", None, "DeleteObjects")
            if not quiet:
                out.append(f"<Deleted><Key>{_xml_escape(key)}</Key></Deleted>")
            continue
        marker_vid = ""
        if exists:
            entry = _insert_simple_delete_marker(store, bucket, key)
            marker_vid = entry.get("current_version_id", "null") if isinstance(entry, dict) else "null"
            _emit(store, bucket, key, "s3:ObjectRemoved:DeleteMarkerCreated", entry, "DeleteObjects")
        if not quiet:
            dm = (f"<DeleteMarker>true</DeleteMarker><DeleteMarkerVersionId>{marker_vid}</DeleteMarkerVersionId>"
                  if marker_vid else "")
            out.append(f"<Deleted><Key>{_xml_escape(key)}</Key>{dm}</Deleted>")
    xml = f'<?xml version="1.0" encoding="UTF-8"?><DeleteResult xmlns="{S3_NS}">{"".join(out)}</DeleteResult>'
    return _done(store, _xml_response(xml))


def _create_bucket(store: ObjectStore, bucket: str, headers: dict, body: bytes) -> S3Response:
    bad = _validate_bucket_name(bucket)
    if bad:
        return bad
    if store.bucket_exists(bucket):
        return _error_xml("BucketAlreadyOwnedByYou",
                          "Your previous request to create the named bucket succeeded and you already own it.",
                          f"/{bucket}", 409)
    store.enforce_quantity_cap("bucket")
    m = re.search(r"<LocationConstraint>\s*([\w-]+)\s*</LocationConstraint>", (body or b"").decode("utf-8", "replace"))
    store.create_bucket(bucket)
    meta = store.buckets[bucket]
    now = _now()
    for k, v in (("region", m.group(1) if m else "us-east-1"), ("created", now), ("creation_date", now),
                 ("access", "Bucket and objects not public"), ("versioning", "Disabled"),
                 ("arn", f"arn:aws:s3:::{bucket}"), ("tags", {}), ("notifications", default_notifications())):
        meta.setdefault(k, v)
    if str((headers or {}).get("x-amz-bucket-object-lock-enabled", "")).lower() == "true":
        meta["object_lock"] = True
        meta["versioning"] = "Enabled"
    canned = (headers or {}).get("x-amz-acl")
    if canned:
        meta["canned_acl"] = canned
    store.bucket_objects(bucket)
    return _done(store, _empty_response(200, {"Location": f"/{bucket}"}))


def _delete_bucket(store: ObjectStore, bucket: str) -> S3Response:
    if not store.bucket_exists(bucket):
        return _error_xml("NoSuchBucket", "The specified bucket does not exist.", f"/{bucket}", 404)
    if any(isinstance(e, dict) and e.get("versions") for e in store.bucket_objects(bucket).values()):
        return _error_xml("BucketNotEmpty", "The bucket you tried to delete is not empty.", f"/{bucket}", 409)
    store.objects.pop(bucket, None)
    store.buckets.pop(bucket, None)
    for uid in [u for u, up in _mpu(store).items() if up.get("bucket") == bucket]:
        _mpu(store).pop(uid, None)
    return _done(store, _empty_response(204))


# ── Static website hosting — the bucket's OWN separate serving origin ───────────────────
# Real S3 exposes this over a distinct, unsigned HTTP(S) origin
# (bucket-name.s3-website-<region>.amazonaws.com), not the control+data API endpoint —
# AwsWireRouter reaches it over its own unsigned path prefix (see service_of's
# "/__s3_website__/" check), never through a signed S3 REST call.
def _parse_website_config(doc: str | None) -> dict | None:
    if not doc:
        return None
    try:
        root = ET.fromstring(doc)
    except ET.ParseError:
        return None
    redirect_all = _child(root, "RedirectAllRequestsTo")
    rules = []
    for rule in _children(_child(root, "RoutingRules"), "RoutingRule"):
        cond = _child(rule, "Condition")
        redir = _child(rule, "Redirect")
        if redir is None:
            continue
        rules.append({
            "key_prefix": _child_text(cond, "KeyPrefixEquals") if cond is not None else "",
            "error_code": _child_text(cond, "HttpErrorCodeReturnedEquals") if cond is not None else "",
            "host_name": _child_text(redir, "HostName"),
            "protocol": _child_text(redir, "Protocol") or "http",
            "replace_key_with": _child_text(redir, "ReplaceKeyWith"),
            "replace_key_prefix_with": _child_text(redir, "ReplaceKeyPrefixWith"),
            "http_code": _child_text(redir, "HttpRedirectCode") or "301",
        })
    return {
        "index": _child_text(_child(root, "IndexDocument"), "Suffix") or "index.html",
        "error_key": _child_text(_child(root, "ErrorDocument"), "Key"),
        "redirect_all": ({"host_name": _child_text(redirect_all, "HostName"),
                          "protocol": _child_text(redirect_all, "Protocol") or "http"}
                        if redirect_all is not None else None),
        "rules": rules,
    }


def _website_redirect_response(rule: dict, key: str) -> S3Response:
    if rule.get("replace_key_with"):
        new_key = rule["replace_key_with"]
    elif rule.get("replace_key_prefix_with") is not None and rule.get("key_prefix"):
        new_key = rule["replace_key_prefix_with"] + key[len(rule["key_prefix"]):]
    else:
        new_key = key
    host = rule.get("host_name") or ""
    location = f"{rule.get('protocol', 'http')}://{host}/{new_key}" if host else f"/{new_key}"
    try:
        status = int(rule.get("http_code") or 301)
    except ValueError:
        status = 301
    return S3Response(status=status, headers={"Location": location}, body=b"", media_type="text/html")


def _website_html_error(status: int, code: str, message: str) -> S3Response:
    body = (f"<html><head><title>{status} {code}</title></head><body><h1>{status} {code}</h1>"
            f"<ul><li>Code: {_xml_escape(code)}</li><li>Message: {_xml_escape(message)}</li></ul>"
            f"</body></html>").encode()
    return S3Response(status=status, headers={}, body=body, media_type="text/html")


def website_dispatch(store: ObjectStore, method: str, bucket: str, key: str, headers: dict | None = None) -> S3Response:
    """GET/HEAD against the bucket's static-website origin — REAL serving (index/error
    documents, RedirectAllRequestsTo, RoutingRules), not just the stored configuration's
    round-trip. Vyomi has no per-request identity model (same documented limitation as
    s3.bucket.public-access-block), so this never checks whether the object is actually
    publicly readable — it serves whatever the bucket's current content is."""
    if not store.bucket_exists(bucket):
        return _website_html_error(404, "NoSuchBucket", "The specified bucket does not exist.")
    cfg = _parse_website_config((store.buckets.get(bucket) or {}).get("website"))
    if cfg is None:
        return _website_html_error(404, "NoSuchWebsiteConfiguration",
                                   "The specified bucket does not have a website configuration")
    if cfg["redirect_all"]:
        return _website_redirect_response({**cfg["redirect_all"], "http_code": "301"}, key)

    def fetch(k: str):
        entry = store.bucket_objects(bucket).get(k)
        if not isinstance(entry, dict) or not entry.get("versions"):
            return None
        cur = entry["versions"][0]
        return None if cur.get("is_delete_marker") else cur

    for rule in cfg["rules"]:
        if not rule["error_code"] and key.startswith(rule["key_prefix"]):
            return _website_redirect_response(rule, key)

    lookup_key = key if key and not key.endswith("/") else key + cfg["index"]
    obj = fetch(lookup_key)
    if obj:
        data = b"" if method == "HEAD" else _version_bytes(store, bucket, lookup_key, obj)
        _record_request_metrics(store, bucket, lookup_key, "GET", 200, bytes_down=len(data))
        return S3Response(status=200, headers={"ETag": obj["etag"], "Last-Modified": _iso_to_http_date(obj["last_modified"])},
                          body=data, media_type=obj["content_type"])

    for rule in cfg["rules"]:
        if rule["error_code"] == "404" and key.startswith(rule["key_prefix"]):
            return _website_redirect_response(rule, key)
    if cfg["error_key"]:
        err_obj = fetch(cfg["error_key"])
        if err_obj:
            data = b"" if method == "HEAD" else _version_bytes(store, bucket, cfg["error_key"], err_obj)
            return S3Response(status=404, headers={}, body=data, media_type=err_obj["content_type"])
    return _website_html_error(404, "NoSuchKey", "The specified key does not exist.")


def dispatch(store: ObjectStore, method: str, path: str,
             query: dict | None = None, headers: dict | None = None,
             body: bytes = b"") -> S3Response:
    query = query or {}
    headers = headers or {}
    lheaders = {str(k).lower(): v for k, v in headers.items()}
    raw = (path or "/").lstrip("/")
    bucket, _, key = raw.partition("/")
    bucket = urllib.parse.unquote(bucket)
    method = (method or "GET").upper()
    if method == "OPTIONS":
        return _cors_preflight(store, bucket, lheaders)
    if not bucket:
        # Service-level root: GET / lists all buckets; others are genuinely invalid.
        if method == "GET":
            return list_all_buckets(store)
        return _error_xml("InvalidRequest", "Missing bucket.", "/", 400)
    if not key:
        # bucket-level
        sr = _bucket_subresource(store, method, bucket, query, lheaders, body)
        if sr is not None:
            return sr
        if method == "PUT":
            return _create_bucket(store, bucket, lheaders, body)
        if method == "GET":
            if str(query.get("list-type", "")) == "2":
                return list_objects_v2(store, bucket, query)
            return list_objects_v1(store, bucket, query)
        if method == "HEAD":
            return _empty_response(200 if store.bucket_exists(bucket) else 404)
        if method == "DELETE":
            return _delete_bucket(store, bucket)
        if method == "POST" and "delete" in query:
            return delete_objects(store, bucket, body, lheaders)
        return _error_xml("MethodNotAllowed", "The specified method is not allowed against this resource.", f"/{bucket}", 405)
    # object-level
    osr = _object_subresource(store, method, bucket, key, query, lheaders, body)
    if osr is not None:
        return osr
    if method == "POST":
        if "uploads" in query:                          # ?uploads → initiate
            return create_multipart_upload(store, bucket, key, headers)
        if query.get("uploadId"):                        # ?uploadId → complete
            return complete_multipart_upload(store, bucket, key, query, body)
        return _error_xml("MethodNotAllowed", "The specified method is not allowed against this resource.", f"/{bucket}/{key}", 405)
    if method == "PUT":
        if query.get("uploadId") and query.get("partNumber"):
            return upload_part(store, bucket, key, query, _decode_aws_chunked(body or b"", lheaders))
        if "x-amz-copy-source" in lheaders:
            resp = copy_object(store, bucket, key, headers)
            _write_access_log(store, bucket, "PUT", key, "REST.COPY.OBJECT", resp.status, f"{bucket}/{key}", len(body or b""))
            return resp
        resp = put_object(store, bucket, key, body, headers)
        _write_access_log(store, bucket, "PUT", key, "REST.PUT.OBJECT", resp.status, f"{bucket}/{key}", len(body or b""))
        return resp
    if method == "GET":
        if query.get("uploadId"):
            return list_parts(store, bucket, key, query)
        resp = get_object(store, bucket, key, query, headers)
        _write_access_log(store, bucket, "GET", key, "REST.GET.OBJECT", resp.status, f"{bucket}/{key}", len(resp.body or b""))
        return resp
    if method == "HEAD":
        resp = head_object(store, bucket, key, query, headers)
        _write_access_log(store, bucket, "HEAD", key, "REST.HEAD.OBJECT", resp.status, f"{bucket}/{key}", 0)
        return resp
    if method == "DELETE":
        if query.get("uploadId"):
            return abort_multipart_upload(store, bucket, key, query)
        resp = delete_object(store, bucket, key, query, lheaders)
        _write_access_log(store, bucket, "DELETE", key, "REST.DELETE.OBJECT", resp.status, f"{bucket}/{key}", 0)
        return resp
    return _error_xml("MethodNotAllowed", "The specified method is not allowed against this resource.", f"/{bucket}/{key}", 405)
