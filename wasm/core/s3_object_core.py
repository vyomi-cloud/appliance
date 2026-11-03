# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
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
import time
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


_GRANT_HEADERS = (("x-amz-grant-read", "READ"), ("x-amz-grant-read-acp", "READ_ACP"),
                  ("x-amz-grant-write-acp", "WRITE_ACP"), ("x-amz-grant-full-control", "FULL_CONTROL"))


def _acl_headers(headers: dict) -> dict:
    """The upload-time permission headers (x-amz-acl, x-amz-grant-*) of a request."""
    return {k: v for k, v in (headers or {}).items()
            if k.lower() == "x-amz-acl" or k.lower().startswith("x-amz-grant-")}


def _grants_acl_xml(headers: dict) -> str | None:
    """AccessControlPolicy for explicit x-amz-grant-* headers (id=/uri=/emailAddress= lists)."""
    grants = []
    for h, perm in _GRANT_HEADERS:
        for part in str((headers or {}).get(h, "")).split(","):
            m = re.match(r'\s*(id|uri|emailAddress)\s*=\s*"?([^"]+?)"?\s*$', part)
            if not m:
                continue
            kind, val = m.groups()
            xsi = 'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
            if kind == "uri":
                g = f'<Grantee {xsi} xsi:type="Group"><URI>{_xml_escape(val)}</URI></Grantee>'
            elif kind == "id":
                g = f'<Grantee {xsi} xsi:type="CanonicalUser"><ID>{_xml_escape(val)}</ID></Grantee>'
            else:
                g = f'<Grantee {xsi} xsi:type="AmazonCustomerByEmail"><EmailAddress>{_xml_escape(val)}</EmailAddress></Grantee>'
            grants.append(f"<Grant>{g}<Permission>{perm}</Permission></Grant>")
    if not grants:
        return None
    owner = ('<Grant><Grantee xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:type="CanonicalUser">'
             "<ID>simulator</ID><DisplayName>cloudlearn-simulator</DisplayName></Grantee>"
             "<Permission>FULL_CONTROL</Permission></Grant>")
    return (f'<?xml version="1.0" encoding="UTF-8"?><AccessControlPolicy xmlns="{S3_NS}">{_OWNER_XML}'
            f"<AccessControlList>{owner}{''.join(grants)}</AccessControlList></AccessControlPolicy>")


def _upload_acl(store: ObjectStore, bucket: str, key: str, headers: dict):
    """Upload-time permissions (PutObject / CreateMultipartUpload x-amz-acl + x-amz-grant-*):
    returns (acl_xml | None, error | None). Enforced like real S3 — a bucket with
    BucketOwnerEnforced rejects ACL headers (bucket-owner-full-control is the one allowed
    value), Block Public Access refuses public canned ACLs, an unknown canned ACL is invalid."""
    hdrs = {k.lower(): v for k, v in _acl_headers(headers).items()}
    if not hdrs:
        return None, None
    canned = hdrs.get("x-amz-acl")
    if canned is not None and canned not in _CANNED_ACL_GRANTS:
        return None, _error_xml("InvalidArgument", "Invalid canned ACL value", f"/{bucket}/{key}", 400)
    if canned is not None and len(hdrs) > 1:
        return None, _error_xml("InvalidRequest", "Specifying both Canned ACLs and Header Grants is not allowed", f"/{bucket}/{key}", 400)
    if _object_ownership(store, bucket) == "BucketOwnerEnforced" and canned != "bucket-owner-full-control":
        return None, _error_xml("AccessControlListNotSupported", "The bucket does not allow ACLs", f"/{bucket}/{key}", 400)
    blocked = _acl_blocked_by_pab(store, bucket, canned)
    if blocked:
        return None, blocked
    if canned is not None:
        return _canned_acl_xml(canned), None
    return _grants_acl_xml(hdrs), None


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


_PAB_KEYS = ("BlockPublicAcls", "IgnorePublicAcls", "BlockPublicPolicy", "RestrictPublicBuckets")


def _account_pab(store: ObjectStore) -> dict:
    """The account-level Block Public Access settings (s3control PutPublicAccessBlock)."""
    acct = getattr(store, "account", None) or {}
    return {k: bool((acct.get("pab") or {}).get(k)) for k in _PAB_KEYS}


def _public_access_block(store: ObjectStore, bucket: str) -> dict:
    """EFFECTIVE Block Public Access for a bucket: the bucket's own settings OR'd with the
    account's (real S3: a setting on either level is enforced)."""
    meta = store.buckets.get(bucket) or {}
    doc = meta.get("cfg", {}).get("publicAccessBlock")
    flags = dict.fromkeys(_PAB_KEYS, False)
    if doc:
        try:
            root = ET.fromstring(doc)
            for k in flags:
                flags[k] = _child_text(root, k).strip().lower() == "true"
        except ET.ParseError:
            pass
    acct = _account_pab(store)
    return {k: flags[k] or acct[k] for k in _PAB_KEYS}


def _acl_blocked_by_pab(store: ObjectStore, bucket: str, canned: str | None) -> S3Response | None:
    if canned in _PUBLIC_CANNED_ACLS and _public_access_block(store, bucket)["BlockPublicAcls"]:
        level = "account" if _account_pab(store)["BlockPublicAcls"] else "bucket"
        return _error_xml("AccessDenied",
                          f"This request is not allowed because the {level} owner enforced the "
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


_EB_TYPES = {"ObjectCreated": "Object Created", "ObjectRemoved": "Object Deleted",
             "LifecycleExpiration": "Object Deleted", "LifecycleTransition": "Object Storage Class Changed"}
_STORAGE_TYPE = {"STANDARD": "StandardStorage", "STANDARD_IA": "StandardIAStorage",
                 "ONEZONE_IA": "OneZoneIAStorage", "REDUCED_REDUNDANCY": "ReducedRedundancyStorage",
                 "GLACIER": "GlacierStorage", "GLACIER_IR": "GlacierInstantRetrievalStorage",
                 "DEEP_ARCHIVE": "DeepArchiveStorage", "INTELLIGENT_TIERING": "IntelligentTieringFAStorage"}


def _eventbridge_deliver(store: ObjectStore, bucket: str, key: str, event_name: str,
                          version: dict | None, source: str) -> None:
    """Amazon EventBridge notifications: a bucket with EventBridgeConfiguration publishes a
    real "Object Created" / "Object Deleted" / "Delete Marker Created" event (source aws.s3,
    the native detail shape) onto the account's DEFAULT event bus, where the account's
    rules/targets match and fan out through the real eventbridge core."""
    eb = getattr(store, "events_store", None)
    if eb is None or event_name == "s3:TestEvent" or not store.bucket_exists(bucket):
        return
    if not bucket_notifications(store, bucket).get("eventBridgeEnabled"):
        return
    parts = event_name.replace("s3:", "").split(":")
    detail_type = _EB_TYPES.get(parts[0])
    if detail_type is None:
        return
    if len(parts) > 1 and parts[1] == "DeleteMarkerCreated":
        detail_type = "Object Deleted"
    detail = {"version": "0", "bucket": {"name": bucket},
              "object": {"key": key, "size": int((version or {}).get("size", 0) or 0),
                         "etag": ((version or {}).get("etag", "") or "").strip('"'),
                         "version-id": (version or {}).get("version_id", "null"),
                         "sequencer": uuid.uuid4().hex[:16]},
              "request-id": _req_id(), "requester": "123456789012",
              "source-ip-address": "127.0.0.1", "reason": source or parts[-1]}
    if parts[0] == "ObjectRemoved":
        detail["deletion-type"] = ("Delete Marker Created" if parts[-1] == "DeleteMarkerCreated"
                                   else "Permanently Deleted")
        detail.get("object", {}).pop("etag", None)
    from core import eventbridge_core as _eb
    _eb.dispatch(eb, "AWSEvents.PutEvents", {"Entries": [{
        "Source": "aws.s3", "DetailType": detail_type, "Detail": json.dumps(detail),
        "Resources": [f"arn:aws:s3:::{bucket}"], "EventBusName": "default"}]},
        lam_store=getattr(store, "lam_store", None))


def _record_storage_metrics(store: ObjectStore, bucket: str) -> None:
    """Real AWS/S3 storage metrics (BucketSizeBytes per StorageType, NumberOfObjects), computed
    from the bucket's ACTUAL contents each time its contents change (real S3 publishes them
    once a day; here the point lands the instant the change does)."""
    cw = getattr(store, "cw_store", None)
    if cw is None or not store.bucket_exists(bucket):
        return
    try:
        from core import cloudwatch_core as _cw_core
    except ImportError:
        return
    sizes: dict[str, int] = {"StandardStorage": 0}
    count = 0
    for entry in store.bucket_objects(bucket).values():
        for v in (entry or {}).get("versions") or []:
            if v.get("is_delete_marker"):
                continue
            st_type = _STORAGE_TYPE.get(v.get("storage_class") or "STANDARD", "StandardStorage")
            sizes[st_type] = sizes.get(st_type, 0) + int(v.get("size", 0) or 0)
            count += 1
    base = [{"Name": "BucketName", "Value": bucket}]
    for st_type, n in sizes.items():
        _cw_core.ingest_internal_metric(cw, "AWS/S3", "BucketSizeBytes",
                                         base + [{"Name": "StorageType", "Value": st_type}], float(n), unit="Bytes")
    _cw_core.ingest_internal_metric(cw, "AWS/S3", "NumberOfObjects",
                                     base + [{"Name": "StorageType", "Value": "AllStorageTypes"}], float(count), unit="Count")


def _emit(store: ObjectStore, bucket: str, key: str, event: str, entry: dict | None, source: str) -> None:
    version = (entry or {}).get("versions", [None])[0] if isinstance(entry, dict) and entry.get("versions") else None
    for hook in (lambda: _eventbridge_deliver(store, bucket, key, event, version, source),
                 lambda: _record_storage_metrics(store, bucket) if event != "s3:TestEvent" else None):
        try:
            hook()
        except Exception:   # best-effort; never fail the data-plane write
            pass
    try:
        _ext().on_emit(store, bucket, key, event, version, source)
    except Exception:
        pass
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
        mt = _child(dest_el, "Metrics") if dest_el is not None else None
        rtc = _child(dest_el, "ReplicationTime") if dest_el is not None else None
        rules.append({
            "metrics": (mt is not None and _child_text(mt, "Status") == "Enabled")
                       or (rtc is not None and _child_text(rtc, "Status") == "Enabled"),
            "id": _child_text(r, "ID"),
            "status": _child_text(r, "Status", "Disabled"),
            "prefix": prefix,
            "destination": dest_arn.rsplit(":", 1)[-1] if dest_arn else "",
            "delete_marker_replication": dmr is not None and _child_text(dmr, "Status") == "Enabled",
        })
    return rules


def _record_replication_metrics(store: ObjectStore, src: str, dest: str, rule_id: str, latency: float) -> None:
    """Real AWS/S3 replication metrics for a rule with Metrics/ReplicationTime enabled: the
    measured copy latency; replication is synchronous here so nothing is ever pending."""
    cw = getattr(store, "cw_store", None)
    if cw is None:
        return
    try:
        from core import cloudwatch_core as _cw_core
        dims = [{"Name": "DestinationBucket", "Value": dest}, {"Name": "RuleId", "Value": rule_id},
                {"Name": "SourceBucket", "Value": src}]   # name-sorted, as the CloudWatch API keys series
        _cw_core.ingest_internal_metric(cw, "AWS/S3", "ReplicationLatency", dims, round(latency, 6), unit="Seconds")
        _cw_core.ingest_internal_metric(cw, "AWS/S3", "BytesPendingReplication", dims, 0.0, unit="Bytes")
        _cw_core.ingest_internal_metric(cw, "AWS/S3", "OperationsPendingReplication", dims, 0.0, unit="Count")
    except Exception:
        pass


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
    t0 = time.monotonic()
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
        if rule.get("metrics"):
            _record_replication_metrics(store, bucket, dest, rule["id"], time.monotonic() - t0)
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
    acl_xml, acl_err = _upload_acl(store, bucket, key, headers)
    if acl_err:
        return acl_err
    if acl_xml:
        version["acl"] = acl_xml
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
    if obj.get("restore"):
        h["x-amz-restore"] = f'ongoing-request="false", expiry-date="{obj["restore"]["expiry"]}"'
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
    if obj.get("restore"):
        h["x-amz-restore"] = f'ongoing-request="false", expiry-date="{obj["restore"]["expiry"]}"'
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
    acl_xml, acl_err = _upload_acl(store, bucket, key, headers)
    if acl_err:
        return acl_err
    upload_id = uuid.uuid4().hex + uuid.uuid4().hex
    _mpu(store)[upload_id] = {
        "bucket": bucket, "key": key, "acl": acl_xml,
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
    if up.get("acl"):
        version["acl"] = up["acl"]
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
        if isinstance(meta, dict) and meta.get("bucket_type") == "Directory":
            continue      # directory buckets are listed by ListDirectoryBuckets only
        if isinstance(meta, dict) and meta.get("internal"):
            continue      # S3 Tables warehouse buckets (<uuid>--table-s3) are not customer buckets
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
    "analytics", "object-lock",
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
    if any(k in query for k in ("accelerate", *_ext().META_SUBS)):
        if not store.bucket_exists(bucket):
            return _error_xml("NoSuchBucket", "The specified bucket does not exist", f"/{bucket}", 404)
        if "accelerate" in query:
            return _ext().accelerate(store, method, bucket, body)
        return _ext().metadata_api(store, method, bucket, query, body)
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
    text = (body or b"").decode("utf-8", "replace")
    dir_cfg = re.search(r"<Type>\s*Directory\s*</Type>", text) is not None
    if dir_cfg or bucket.endswith(_DIR_SUFFIX):
        return _create_directory_bucket(store, bucket, text, dir_cfg)
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


# ── S3 Express One Zone: directory buckets ─────────────────────────────────────────────
# A directory bucket is a general bucket record in the SAME store (so object CRUD, list,
# delete, multipart all reuse the one engine) tagged meta["bucket_type"] = "Directory",
# named `<base>--<zone-id>--x-s3`, living in ONE Availability Zone. Differences enforced:
# no versioning/ACL/lifecycle-style sub-resources, only EXPRESS_ONEZONE storage, "/" is the
# only list delimiter, listed by ListDirectoryBuckets (not ListBuckets), CreateSession.
_DIR_SUFFIX = "--x-s3"
_DIR_NAME_RE = re.compile(r"^([a-z0-9][a-z0-9-]*[a-z0-9])--([a-z0-9]+(?:-[a-z0-9]+)?-az\d+)--x-s3$")
_AZ_REGIONS = {"use1": "us-east-1", "use2": "us-east-2", "usw1": "us-west-1", "usw2": "us-west-2",
               "euw1": "eu-west-1", "euw2": "eu-west-2", "euw3": "eu-west-3", "euc1": "eu-central-1",
               "eun1": "eu-north-1", "apne1": "ap-northeast-1", "apne2": "ap-northeast-2",
               "apse1": "ap-southeast-1", "apse2": "ap-southeast-2", "aps1": "ap-south-1",
               "sae1": "sa-east-1", "cac1": "ca-central-1"}
_DIR_UNSUPPORTED_SUB = ("versioning", "acl", "object-lock", "versions", "website", "logging", "requestPayment",
                        "notification", "replication", "accelerate", "analytics", "metrics", "inventory",
                        "intelligent-tiering")


def is_directory_bucket(store: ObjectStore, bucket: str) -> bool:
    meta = (getattr(store, "buckets", {}) or {}).get(bucket)
    return isinstance(meta, dict) and meta.get("bucket_type") == "Directory"


def _create_directory_bucket(store: ObjectStore, bucket: str, text: str, dir_cfg: bool) -> S3Response:
    m = _DIR_NAME_RE.match(bucket) if len(bucket) <= 63 else None
    if not m:
        return _error_xml("InvalidBucketName",
                          "The specified bucket is not valid. Directory bucket names must be of the form "
                          "base-name--zone-id--x-s3 (e.g. my-bucket--usw2-az1--x-s3), at most 63 characters, "
                          "lowercase letters, numbers and hyphens.", f"/{bucket}", 400)
    base, zone = m.group(1), m.group(2)
    if len(base) < 3:
        return _error_xml("InvalidBucketName", "The base name of a directory bucket must be at least 3 characters.", f"/{bucket}", 400)
    loc = re.search(r"<Location>\s*<Name>\s*([\w-]+)\s*</Name>\s*<Type>\s*([\w]+)\s*</Type>\s*</Location>"
                    r"|<Location>\s*<Type>\s*([\w]+)\s*</Type>\s*<Name>\s*([\w-]+)\s*</Name>\s*</Location>", text)
    if not dir_cfg or not loc:
        return _error_xml("InvalidRequest",
                          "Directory buckets can only be created with a CreateBucketConfiguration that specifies "
                          "both Location (Name + Type=AvailabilityZone) and Bucket (Type=Directory).", f"/{bucket}", 400)
    loc_name = loc.group(1) or loc.group(4)
    loc_type = loc.group(2) or loc.group(3)
    if loc_type not in ("AvailabilityZone", "LocalZone"):
        return _error_xml("MalformedXML", "The XML you provided was not well-formed or did not validate against our published schema.", f"/{bucket}", 400)
    if loc_name != zone:
        return _error_xml("InvalidRequest",
                          f"The Location.Name ({loc_name}) must match the zone id in the bucket name ({zone}).", f"/{bucket}", 400)
    red = re.search(r"<DataRedundancy>\s*(\w+)\s*</DataRedundancy>", text)
    redundancy = red.group(1) if red else ("SingleLocalZone" if loc_type == "LocalZone" else "SingleAvailabilityZone")
    if redundancy not in ("SingleAvailabilityZone", "SingleLocalZone"):
        return _error_xml("MalformedXML", "The XML you provided was not well-formed or did not validate against our published schema.", f"/{bucket}", 400)
    if store.bucket_exists(bucket):
        return _error_xml("BucketAlreadyOwnedByYou",
                          "Your previous request to create the named bucket succeeded and you already own it.", f"/{bucket}", 409)
    store.enforce_quantity_cap("bucket")
    region = _AZ_REGIONS.get(zone.split("-")[0], "us-east-1")
    store.create_bucket(bucket)
    now = _now()
    meta = store.buckets[bucket]
    meta.update({"region": region, "created": now, "creation_date": now, "access": "Bucket and objects not public",
                 "versioning": "Disabled", "arn": f"arn:aws:s3express:{region}:{_ACCOUNT_ID}:bucket/{bucket}",
                 "tags": {}, "notifications": default_notifications(), "bucket_type": "Directory",
                 "location": {"name": zone, "type": loc_type}, "data_redundancy": redundancy})
    store.bucket_objects(bucket)
    return _done(store, _empty_response(200, {"Location": f"/{bucket}"}))


def _is_express_control(lheaders: dict) -> bool:
    return "/s3express/" in (lheaders.get("authorization") or "") or str(lheaders.get("host") or "").startswith("s3express-control")


def list_directory_buckets(store: ObjectStore, query: dict) -> S3Response:
    """GET / on the s3express control endpoint -> ListDirectoryBuckets (paginated)."""
    try:
        limit = int((query or {}).get("max-directory-buckets") or 1000)
    except ValueError:
        limit = 0
    if not 0 < limit <= 1000:
        return _error_xml("InvalidArgument", "max-directory-buckets must be between 1 and 1000.", "/", 400)
    token = str((query or {}).get("continuation-token") or "")
    names = sorted(n for n in store.buckets if is_directory_bucket(store, n) and (not token or n > token))
    page, more = names[:limit], len(names) > limit
    rows = "".join(f"<Bucket><Name>{_xml_escape(n)}</Name><CreationDate>{store.buckets[n].get('creation_date') or _now()}</CreationDate>"
                   f"<BucketRegion>{store.buckets[n].get('region', 'us-east-1')}</BucketRegion></Bucket>" for n in page)
    nxt = f"<ContinuationToken>{_xml_escape(page[-1])}</ContinuationToken>" if more else ""
    return _xml_response('<?xml version="1.0" encoding="UTF-8"?><ListAllMyDirectoryBucketsResult '
                         f'xmlns="http://s3.amazonaws.com/doc/2006-03-01/"><Buckets>{rows}</Buckets>{nxt}</ListAllMyDirectoryBucketsResult>')


def _create_session(store: ObjectStore, bucket: str, lheaders: dict) -> S3Response:
    if not store.bucket_exists(bucket):
        return _error_xml("NoSuchBucket", "The specified bucket does not exist.", f"/{bucket}", 404)
    if not is_directory_bucket(store, bucket):
        return _error_xml("InvalidRequest", "CreateSession is only supported on directory buckets.", f"/{bucket}", 400)
    mode = lheaders.get("x-amz-create-session-mode") or "ReadWrite"
    if mode not in ("ReadOnly", "ReadWrite"):
        return _error_xml("InvalidArgument", "x-amz-create-session-mode must be ReadOnly or ReadWrite.", f"/{bucket}", 400)
    exp = (datetime.now(timezone.utc) + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return _xml_response('<?xml version="1.0" encoding="UTF-8"?><CreateSessionResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
                         f"<Credentials><SessionToken>{uuid.uuid4().hex}{uuid.uuid4().hex}</SessionToken>"
                         f"<SecretAccessKey>{uuid.uuid4().hex}{uuid.uuid4().hex[:8]}</SecretAccessKey>"
                         f"<AccessKeyId>ASIA{uuid.uuid4().hex[:16].upper()}</AccessKeyId><Expiration>{exp}</Expiration></Credentials>"
                         "</CreateSessionResult>")


def _directory_guard(store: ObjectStore, method: str, bucket: str, key: str, query: dict, headers: dict) -> S3Response | None:
    """Realistic S3 Express restrictions for a request addressed at a directory bucket."""
    if not key:
        sub = next((k for k in _DIR_UNSUPPORTED_SUB if k in query), None)
        if sub:
            return _error_xml("NotImplemented", f"Directory buckets do not support the '{sub}' bucket configuration.", f"/{bucket}", 501)
        if method == "GET" and str(query.get("list-type", "")) != "2" and "session" not in query and "location" not in query:
            return _error_xml("InvalidRequest", "Directory buckets only support ListObjectsV2 (list-type=2).", f"/{bucket}", 400)
        delim = query.get("delimiter")
        if method == "GET" and delim not in (None, "", "/"):
            return _error_xml("InvalidArgument", "Directory buckets only support '/' as the delimiter.", f"/{bucket}", 400)
        return None
    if method in ("PUT", "POST"):
        sc = headers.get("x-amz-storage-class")
        if sc and sc != "EXPRESS_ONEZONE":
            return _error_xml("InvalidStorageClass", "The storage class you specified is not valid for a directory bucket (only EXPRESS_ONEZONE).", f"/{bucket}/{key}", 400)
        if headers.get("x-amz-acl") or any(h.startswith("x-amz-grant-") for h in headers):
            return _error_xml("NotImplemented", "Directory buckets do not support ACLs.", f"/{bucket}/{key}", 501)
    if "acl" in query or "tagging" in query or ("versionId" in query and query.get("versionId") not in ("", "null")):
        return _error_xml("NotImplemented", "This operation is not supported for directory buckets.", f"/{bucket}/{key}", 501)
    return None


# ── S3 Control: Access Points (restXml /v20180820/accesspoint…) ───────────────────────
# An access point is a named endpoint onto ONE bucket. Records live in the parent bucket's
# meta["access_points"] (so they persist wherever bucket config persists, offline and Nano).
# The access point's ALIAS (<name>-<id>-s3alias) is accepted anywhere a bucket name is — it is
# resolved to the real bucket before dispatch, so objects are reachable through it. The
# access point policy / Block Public Access settings are stored and returned (the simulator
# does not authenticate principals, so a policy is never evaluated against a caller).
_S3C_NS = "http://awss3control.amazonaws.com/doc/2016-08-20/"
_ACCOUNT_ID = "123456789012"
_AP_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,48}[a-z0-9]$")
_AP_PAB_KEYS = ("BlockPublicAcls", "IgnorePublicAcls", "BlockPublicPolicy", "RestrictPublicBuckets")


def _s3c_error(code: str, message: str, status: int) -> S3Response:
    return _xml_response(f'<?xml version="1.0" encoding="UTF-8"?><ErrorResponse><Error><Code>{code}</Code>'
                         f"<Message>{_xml_escape(message)}</Message></Error><RequestId>{_req_id()}</RequestId></ErrorResponse>", status)


def _access_points(store: ObjectStore):
    """Yield (bucket, name, record) for every access point in the account."""
    for b, meta in list(store.buckets.items()):
        for n, rec in ((meta or {}).get("access_points") or {}).items():
            yield b, n, rec


def _find_access_point(store: ObjectStore, name: str):
    return next(((b, rec) for b, n, rec in _access_points(store) if n == name), (None, None))


def _resolve_access_point(store: ObjectStore, bucket: str) -> str:
    """An access point alias (…-s3alias) addresses its bucket."""
    if bucket.endswith("-s3alias"):
        for b, _n, rec in _access_points(store):
            if rec.get("alias") == bucket:
                return b
    return bucket


def _ap_xml(name: str, bucket: str, rec: dict, tag: str, full: bool) -> str:
    vpc = (f"<VpcConfiguration><VpcId>{_xml_escape(rec['vpc'])}</VpcId></VpcConfiguration>" if rec.get("vpc") else "")
    pab = "<PublicAccessBlockConfiguration>" + "".join(
        f"<{k}>{'true' if rec['pab'].get(k) else 'false'}</{k}>" for k in _AP_PAB_KEYS) + "</PublicAccessBlockConfiguration>"
    head = (f"<Name>{_xml_escape(name)}</Name><NetworkOrigin>{'VPC' if rec.get('vpc') else 'Internet'}</NetworkOrigin>{vpc}"
            f"<Bucket>{bucket}</Bucket>")
    if full:
        return (f"<{tag}>{head}{pab}<CreationDate>{rec['created']}</CreationDate><Alias>{rec['alias']}</Alias>"
                f"<AccessPointArn>{rec['arn']}</AccessPointArn><Endpoints><entry><key>ipv4</key><value>{name}-{_ACCOUNT_ID}.s3-accesspoint.us-east-1.amazonaws.com</value></entry></Endpoints>"
                f"<BucketAccountId>{_ACCOUNT_ID}</BucketAccountId></{tag}>")
    return (f"<{tag}>{head}<AccessPointArn>{rec['arn']}</AccessPointArn><Alias>{rec['alias']}</Alias>"
            f"<BucketAccountId>{_ACCOUNT_ID}</BucketAccountId></{tag}>")


def _load_core(name: str):
    """Sibling core module (flat on Pyodide, package on the appliance)."""
    import importlib
    try:
        return importlib.import_module("core." + name)
    except ImportError:
        return importlib.import_module(name)


def _ext():
    return _load_core("s3_ext_core")


def _s3control(store: ObjectStore, method: str, raw: str, query: dict, lheaders: dict, body: bytes) -> S3Response:
    segs = [urllib.parse.unquote(x) for x in raw.split("/") if x]      # v20180820, accesspoint, name, [policy|policyStatus]
    acct = lheaders.get("x-amz-account-id")
    if acct and acct != _ACCOUNT_ID:
        return _s3c_error("AccessDenied", "Account ID does not match the caller's account.", 403)
    if len(segs) >= 3 and segs[1] == "configuration" and segs[2] == "publicAccessBlock" and len(segs) == 3:
        return _s3c_account_pab(store, method, body)
    if len(segs) >= 2 and segs[1].lower() == "accesspointforobjectlambda":
        return _s3c_olap(store, method, segs, body)
    if len(segs) >= 2 and segs[1] in ("mrap", "async-requests"):
        return _s3c_mrap(store, method, segs, query, body)
    if len(segs) >= 2 and segs[1] in ("accessgrantsinstance", "accessgrantsinstances"):
        return _s3c_grants(store, method, segs, query, body)
    if len(segs) >= 2 and segs[1] == "jobs":
        return _s3c_jobs(store, method, segs, query, body)
    if len(segs) >= 2 and segs[1] in ("storagelens", "storagelensgroup", "tags", "_vyomi"):
        ins = _load_core("s3_insights_core")
        if segs[1] == "storagelens":
            return ins.s3control_lens(store, method, segs, query, body)
        if segs[1] == "storagelensgroup":
            return ins.s3control_group(store, method, segs, query, body)
        if segs[1] == "tags":
            return ins.s3control_tags(store, method, segs, query, body)
        ext = _ext().vyomi_route(store, method, segs[2:], query)
        if ext is not None:
            return ext
        return ins.s3_vyomi(store, method, segs, query, body)
    if len(segs) < 2 or segs[1] != "accesspoint":
        return _s3c_error("NotImplemented", "This S3 Control operation is not implemented by Vyomi.", 501)
    hdr = '<?xml version="1.0" encoding="UTF-8"?>'
    if len(segs) == 2:                                                  # list
        if method != "GET":
            return _s3c_error("MethodNotAllowed", method, 405)
        want = (query or {}).get("bucket")
        rows = "".join(_ap_xml(n, b, rec, "AccessPoint", False) for b, n, rec in sorted(_access_points(store), key=lambda t: t[1])
                       if not want or b == want)
        return _xml_response(f'{hdr}<ListAccessPointsResult xmlns="{_S3C_NS}"><AccessPointList>{rows}</AccessPointList></ListAccessPointsResult>')
    name = segs[2]
    sub = segs[3] if len(segs) > 3 else ""
    if sub not in ("", "policy", "policyStatus") or len(segs) > 4:
        return _s3c_error("NotImplemented", f"Access point sub-resource '{sub}' is not implemented by Vyomi.", 501)
    bucket, rec = _find_access_point(store, name)
    if method == "PUT" and not sub:
        if bucket is not None:
            return _s3c_error("AccessPointAlreadyOwnedByYou", "Your previous request to create the named access point succeeded and you already own it.", 409)
        if name in ((getattr(store, "account", None) or {}).get("olaps") or {}):
            return _s3c_error("AccessPointAlreadyOwnedByYou", "An Object Lambda access point with this name already exists.", 409)
        if not _AP_NAME_RE.match(name):
            return _s3c_error("InvalidRequest", "Access point names must be 3-50 characters of lowercase letters, numbers and hyphens.", 400)
        try:
            root = ET.fromstring(body or b"")
        except ET.ParseError:
            return _s3c_error("MalformedXML", "The XML you provided was not well-formed or did not validate against our published schema.", 400)
        b = _child_text(root, "Bucket")
        if not b or not store.bucket_exists(b):
            return _s3c_error("NoSuchBucket", "The specified bucket does not exist.", 404)
        vpc = _child_text(_child(root, "VpcConfiguration"), "VpcId") if _child(root, "VpcConfiguration") is not None else ""
        pab_el = _child(root, "PublicAccessBlockConfiguration")
        pab = {k: (_child_text(pab_el, k).lower() == "true" if pab_el is not None else not vpc) for k in _AP_PAB_KEYS}
        rec = {"alias": f"{name}-{uuid.uuid4().hex[:10]}-s3alias", "vpc": vpc, "pab": pab, "created": _now(),
               "arn": f"arn:aws:s3:us-east-1:{_ACCOUNT_ID}:accesspoint/{name}", "policy": None}
        store.buckets[b].setdefault("access_points", {})[name] = rec
        return _done(store, _xml_response(f'{hdr}<CreateAccessPointResult xmlns="{_S3C_NS}"><AccessPointArn>{rec["arn"]}</AccessPointArn><Alias>{rec["alias"]}</Alias></CreateAccessPointResult>'))
    if bucket is None:
        return _s3c_error("NoSuchAccessPoint", "The specified accesspoint does not exist.", 404)
    if not sub:
        if method == "GET":
            return _xml_response(f'{hdr}' + _ap_xml(name, bucket, rec, "GetAccessPointResult", True).replace(
                "<GetAccessPointResult>", f'<GetAccessPointResult xmlns="{_S3C_NS}">', 1))
        if method == "DELETE":
            del store.buckets[bucket]["access_points"][name]
            return _done(store, _empty_response(204))
    elif sub == "policy":
        if method == "GET":
            if not rec.get("policy"):
                return _s3c_error("NoSuchAccessPointPolicy", "The specified accesspoint policy does not exist.", 404)
            return _xml_response(f'{hdr}<GetAccessPointPolicyResult xmlns="{_S3C_NS}"><Policy>{_xml_escape(rec["policy"])}</Policy></GetAccessPointPolicyResult>')
        if method == "PUT":
            try:
                doc = _child_text(ET.fromstring(body or b""), "Policy")
                json.loads(doc)
            except Exception:
                return _s3c_error("MalformedPolicy", "Policies must be valid JSON and the first byte must be '{'", 400)
            rec["policy"] = doc
            return _done(store, _empty_response(200))
        if method == "DELETE":
            rec["policy"] = None
            return _done(store, _empty_response(204))
    elif sub == "policyStatus" and method == "GET":
        if not rec.get("policy"):
            return _s3c_error("NoSuchAccessPointPolicy", "The specified accesspoint policy does not exist.", 404)
        public = _policy_is_public(json.loads(rec["policy"]))
        return _xml_response(f'{hdr}<GetAccessPointPolicyStatusResult xmlns="{_S3C_NS}"><PolicyStatus><IsPublic>{"true" if public else "false"}</IsPublic></PolicyStatus></GetAccessPointPolicyStatusResult>')
    return _s3c_error("MethodNotAllowed", method, 405)



# ── S3 Control: account-level Block Public Access (restXml /v20180820/configuration/publicAccessBlock)
def _s3c_account_pab(store: ObjectStore, method: str, body: bytes) -> S3Response:
    acct = store.account
    hdr = '<?xml version="1.0" encoding="UTF-8"?>'
    if method == "GET":
        if "pab" not in acct:
            return _s3c_error("NoSuchPublicAccessBlockConfiguration", "The public access block configuration was not found.", 404)
        inner = "".join(f"<{k}>{'true' if acct['pab'].get(k) else 'false'}</{k}>" for k in _PAB_KEYS)
        return _xml_response(f'{hdr}<PublicAccessBlockConfiguration xmlns="{_S3C_NS}">{inner}</PublicAccessBlockConfiguration>')
    if method == "PUT":
        try:
            root = ET.fromstring(body or b"")
        except ET.ParseError:
            return _s3c_error("MalformedXML", "The XML you provided was not well-formed or did not validate against our published schema.", 400)
        pab = {}
        for k in _PAB_KEYS:
            v = _child_text(root, k).strip().lower()
            if v not in ("", "true", "false"):
                return _s3c_error("MalformedXML", f"{k} must be true or false.", 400)
            pab[k] = v == "true"
        if not any(_child(root, k) is not None for k in _PAB_KEYS):
            return _s3c_error("InvalidRequest", "At least one Block Public Access setting must be specified.", 400)
        acct["pab"] = pab
        return _done(store, _empty_response(200))
    if method == "DELETE":
        if "pab" not in acct:
            return _s3c_error("NoSuchPublicAccessBlockConfiguration", "The public access block configuration was not found.", 404)
        acct.pop("pab", None)
        return _done(store, _empty_response(204))
    return _s3c_error("MethodNotAllowed", method, 405)


# ── S3 Control: Object Lambda Access Points (restXml /v20180820/accesspointforobjectlambda…)
# An OLAP is a control-plane record in store.account["olaps"] layered on a standard access
# point (its SupportingAccessPoint). GetObject through the OLAP alias/ARN reads the object via
# the supporting access point's bucket, invokes the configured Lambda with the real event
# shape, and returns the Lambda's transformed body (see _olap_get_object for the contract).
_OLAP_ACTIONS = ("GetObject", "HeadObject", "ListObjects", "ListObjectsV2")
_OLAP_FEATURES = ("GetObject-Range", "GetObject-PartNumber", "HeadObject-Range", "HeadObject-PartNumber")


def _olaps(store: ObjectStore) -> dict:
    return store.account.setdefault("olaps", {})


def _olap_config_xml(c: dict) -> str:
    feats = "".join(f"<AllowedFeature>{f}</AllowedFeature>" for f in c["allowed"])
    trans = "".join(
        "<TransformationConfiguration><Actions>" + "".join(f"<Action>{a}</Action>" for a in t["actions"]) + "</Actions>"
        f"<ContentTransformation><AwsLambda><FunctionArn>{_xml_escape(t['function_arn'])}</FunctionArn>"
        + (f"<FunctionPayload>{_xml_escape(t['payload'])}</FunctionPayload>" if t.get("payload") else "")
        + "</AwsLambda></ContentTransformation></TransformationConfiguration>" for t in c["transformations"])
    return (f"<SupportingAccessPoint>{_xml_escape(c['supporting'])}</SupportingAccessPoint>"
            f"<CloudWatchMetricsEnabled>{'true' if c['metrics'] else 'false'}</CloudWatchMetricsEnabled>"
            f"<AllowedFeatures>{feats}</AllowedFeatures><TransformationConfigurations>{trans}</TransformationConfigurations>")


def _parse_olap_config(store: ObjectStore, root) -> tuple[dict | None, S3Response | None]:
    sup = _child_text(root, "SupportingAccessPoint").strip()
    m = re.match(r"^arn:aws:s3:[a-z0-9-]+:(\d{12}):accesspoint/([a-z0-9-]{3,50})$", sup)
    if not m:
        return None, _s3c_error("InvalidRequest", "SupportingAccessPoint must be the ARN of a standard access point.", 400)
    if m.group(1) != _ACCOUNT_ID or _find_access_point(store, m.group(2))[0] is None:
        return None, _s3c_error("InvalidRequest", "The supporting access point does not exist.", 400)
    allowed = [(e.text or "").strip() for e in _children(_child(root, "AllowedFeatures"), "AllowedFeature")]
    if any(f not in _OLAP_FEATURES for f in allowed):
        return None, _s3c_error("MalformedXML", f"AllowedFeature must be one of {', '.join(_OLAP_FEATURES)}.", 400)
    trans = []
    for t in _children(_child(root, "TransformationConfigurations"), "TransformationConfiguration"):
        actions = [(e.text or "").strip() for e in _children(_child(t, "Actions"), "Action")]
        if not actions or any(a not in _OLAP_ACTIONS for a in actions):
            return None, _s3c_error("MalformedXML", f"Actions must be a non-empty subset of {', '.join(_OLAP_ACTIONS)}.", 400)
        lam = _child(_child(t, "ContentTransformation"), "AwsLambda") if _child(t, "ContentTransformation") is not None else None
        fn = _child_text(lam, "FunctionArn").strip() if lam is not None else ""
        if not re.match(r"^arn:aws:lambda:[a-z0-9-]+:\d{12}:function:[\w-]+(:[\w$-]+)?$", fn):
            return None, _s3c_error("InvalidRequest", "ContentTransformation.AwsLambda.FunctionArn must be a Lambda function ARN.", 400)
        trans.append({"actions": actions, "function_arn": fn, "payload": _child_text(lam, "FunctionPayload")})
    if not trans:
        return None, _s3c_error("MalformedXML", "At least one TransformationConfiguration is required.", 400)
    return {"supporting": sup, "metrics": _child_text(root, "CloudWatchMetricsEnabled").strip().lower() == "true",
            "allowed": allowed, "transformations": trans}, None


def _s3c_olap(store: ObjectStore, method: str, segs: list, body: bytes) -> S3Response:
    hdr = '<?xml version="1.0" encoding="UTF-8"?>'
    olaps = _olaps(store)
    if len(segs) == 2:
        if method != "GET":
            return _s3c_error("MethodNotAllowed", method, 405)
        rows = "".join(f"<ObjectLambdaAccessPoint><Name>{n}</Name><ObjectLambdaAccessPointArn>{r['arn']}</ObjectLambdaAccessPointArn>"
                       f"<Alias><Value>{r['alias']}</Value><Status>READY</Status></Alias></ObjectLambdaAccessPoint>"
                       for n, r in sorted(olaps.items()))
        return _xml_response(f'{hdr}<ListAccessPointsForObjectLambdaResult xmlns="{_S3C_NS}"><ObjectLambdaAccessPointList>{rows}</ObjectLambdaAccessPointList></ListAccessPointsForObjectLambdaResult>')
    name, sub = segs[2], (segs[3] if len(segs) > 3 else "")
    if sub not in ("", "configuration", "policy", "policyStatus") or len(segs) > 4:
        return _s3c_error("NotImplemented", f"Object Lambda access point sub-resource '{sub}' is not implemented by Vyomi.", 501)
    rec = olaps.get(name)
    if method == "PUT" and not sub:
        if rec is not None or _find_access_point(store, name)[0] is not None:
            return _s3c_error("AccessPointAlreadyOwnedByYou", "An access point with this name already exists.", 409)
        if not re.match(r"^[a-z0-9][a-z0-9-]{1,43}[a-z0-9]$", name):
            return _s3c_error("InvalidRequest", "Object Lambda access point names must be 3-45 characters of lowercase letters, numbers and hyphens.", 400)
        try:
            root = ET.fromstring(body or b"")
        except ET.ParseError:
            return _s3c_error("MalformedXML", "The XML you provided was not well-formed or did not validate against our published schema.", 400)
        cfg, err = _parse_olap_config(store, _child(root, "Configuration") if _child(root, "Configuration") is not None else root)
        if err:
            return err
        rec = {"alias": f"{name}-{uuid.uuid4().hex[:10]}--ol-s3", "created": _now(), "config": cfg, "policy": None,
               "arn": f"arn:aws:s3-object-lambda:us-east-1:{_ACCOUNT_ID}:accesspoint/{name}"}
        olaps[name] = rec
        return _done(store, _xml_response(f'{hdr}<CreateAccessPointForObjectLambdaResult xmlns="{_S3C_NS}"><ObjectLambdaAccessPointArn>{rec["arn"]}</ObjectLambdaAccessPointArn>'
                                          f'<Alias><Value>{rec["alias"]}</Value><Status>READY</Status></Alias></CreateAccessPointForObjectLambdaResult>'))
    if rec is None:
        return _s3c_error("NoSuchAccessPoint", "The specified object lambda access point does not exist.", 404)
    if not sub:
        if method == "GET":
            pab = "".join(f"<{k}>true</{k}>" for k in _PAB_KEYS)
            return _xml_response(f'{hdr}<GetAccessPointForObjectLambdaResult xmlns="{_S3C_NS}"><Name>{name}</Name>'
                                 f'<PublicAccessBlockConfiguration>{pab}</PublicAccessBlockConfiguration><CreationDate>{rec["created"]}</CreationDate>'
                                 f'<Alias><Value>{rec["alias"]}</Value><Status>READY</Status></Alias></GetAccessPointForObjectLambdaResult>')
        if method == "DELETE":
            del olaps[name]
            return _done(store, _empty_response(204))
    elif sub == "configuration":
        if method == "GET":
            return _xml_response(f'{hdr}<GetAccessPointConfigurationForObjectLambdaResult xmlns="{_S3C_NS}"><Configuration>{_olap_config_xml(rec["config"])}</Configuration></GetAccessPointConfigurationForObjectLambdaResult>')
        if method == "PUT":
            try:
                root = ET.fromstring(body or b"")
            except ET.ParseError:
                return _s3c_error("MalformedXML", "The XML you provided was not well-formed or did not validate against our published schema.", 400)
            cfg, err = _parse_olap_config(store, _child(root, "Configuration") if _child(root, "Configuration") is not None else root)
            if err:
                return err
            rec["config"] = cfg
            return _done(store, _empty_response(200))
    elif sub == "policy":
        if method == "GET":
            if not rec.get("policy"):
                return _s3c_error("NoSuchAccessPointPolicy", "The specified accesspoint policy does not exist.", 404)
            return _xml_response(f'{hdr}<GetAccessPointPolicyForObjectLambdaResult xmlns="{_S3C_NS}"><Policy>{_xml_escape(rec["policy"])}</Policy></GetAccessPointPolicyForObjectLambdaResult>')
        if method == "PUT":
            try:
                doc = _child_text(ET.fromstring(body or b""), "Policy")
                json.loads(doc)
            except Exception:
                return _s3c_error("MalformedPolicy", "Policies must be valid JSON and the first byte must be '{'", 400)
            rec["policy"] = doc
            return _done(store, _empty_response(200))
        if method == "DELETE":
            rec["policy"] = None
            return _done(store, _empty_response(204))
    elif sub == "policyStatus" and method == "GET":
        if not rec.get("policy"):
            return _s3c_error("NoSuchAccessPointPolicy", "The specified accesspoint policy does not exist.", 404)
        public = _policy_is_public(json.loads(rec["policy"]))
        return _xml_response(f'{hdr}<GetAccessPointPolicyStatusForObjectLambdaResult xmlns="{_S3C_NS}"><PolicyStatus><IsPublic>{"true" if public else "false"}</IsPublic></PolicyStatus></GetAccessPointPolicyStatusForObjectLambdaResult>')
    return _s3c_error("MethodNotAllowed", method, 405)


def _olap_lookup(store: ObjectStore, raw: str):
    """(record, name, key) when the request addresses an OLAP by alias or ARN, else (None, '', '')."""
    olaps = (getattr(store, "account", None) or {}).get("olaps") or {}
    if not olaps:
        return None, "", ""
    head, _, rest = raw.partition("/")
    if raw.startswith("arn:aws:s3-object-lambda:") and ":accesspoint/" in raw:
        tail = raw.split(":accesspoint/", 1)[1]
        name, _, key = tail.partition("/")
        return olaps.get(name), name, key
    head = urllib.parse.unquote(head)
    if head.endswith("--ol-s3"):
        for n, r in olaps.items():
            if r["alias"] == head:
                return r, n, rest
    return None, "", ""


def _olap_dispatch(store: ObjectStore, rec: dict, name: str, method: str, key: str, query: dict, headers: dict, lheaders: dict) -> S3Response:
    """Data plane through an Object Lambda access point. Only GetObject is transformed."""
    cfg = rec["config"]
    if method == "GET" and key and not any(k in query for k in ("uploadId", "tagging", "acl", "attributes")):
        t = next((t for t in cfg["transformations"] if "GetObject" in t["actions"]), None)
        if t is None:
            return _error_xml("InvalidRequest", "This Object Lambda access point has no GetObject transformation configured.", f"/{key}", 400)
        return _olap_get_object(store, rec, name, t, key, query, headers, lheaders)
    configured = {a for t in cfg["transformations"] for a in t["actions"]}
    if method == "HEAD" and "HeadObject" in configured or (method == "GET" and not key and configured & {"ListObjects", "ListObjectsV2"}):
        return _error_xml("NotImplemented", "HeadObject / ListObjects transformations through an Object Lambda access point are not implemented by Vyomi (GetObject is).", f"/{key}", 501)
    return _error_xml("InvalidRequest", "This operation is not supported through an Object Lambda access point.", f"/{key}", 400)


def _olap_get_object(store, rec, name, t, key, query, headers, lheaders) -> S3Response:
    cfg = rec["config"]
    if "range" in lheaders and "GetObject-Range" not in cfg["allowed"]:
        return _error_xml("InvalidRequest", "Range requests are not enabled on this Object Lambda access point (AllowedFeatures: GetObject-Range).", f"/{key}", 400)
    if "partNumber" in query and "GetObject-PartNumber" not in cfg["allowed"]:
        return _error_xml("InvalidRequest", "partNumber is not enabled on this Object Lambda access point (AllowedFeatures: GetObject-PartNumber).", f"/{key}", 400)
    sup_name = cfg["supporting"].rsplit("/", 1)[-1]
    bucket, _ap = _find_access_point(store, sup_name)
    if bucket is None:
        return _error_xml("NoSuchAccessPoint", "The supporting access point of this Object Lambda access point no longer exists.", f"/{key}", 404)
    src = get_object(store, bucket, key, query, headers)
    if src.status >= 300:
        return src
    lam = getattr(store, "lam_store", None)
    if lam is None:
        return _error_xml("InternalError", "No Lambda backend is attached to this store.", f"/{key}", 500)
    try:
        from core import lambda_core as _lam
    except ImportError:  # pragma: no cover - flat vendoring
        import lambda_core as _lam  # type: ignore
    host = lheaders.get("host") or "localhost"
    token = uuid.uuid4().hex
    event = {"xAmzRequestId": uuid.uuid4().hex,
             "getObjectContext": {"inputS3Url": f"http://{host}/{bucket}/{urllib.parse.quote(key)}?X-Amz-Expires=61",
                                  "outputRoute": f"io-use1-{uuid.uuid4().hex[:6]}", "outputToken": token,
                                  # Vyomi extension: the original object, so a Lambda needs no network round-trip
                                  "vyomiInputBase64": base64.b64encode(src.body or b"").decode(),
                                  "vyomiInputContentType": src.media_type or "application/octet-stream"},
             "configuration": {"accessPointArn": rec["arn"], "supportingAccessPointArn": cfg["supporting"], "payload": t.get("payload") or ""},
             "userRequest": {"url": f"/{rec['alias']}/{key}", "headers": {k: v for k, v in lheaders.items() if k in ("host", "range", "user-agent")}},
             "userIdentity": {"type": "IAMUser", "accountId": _ACCOUNT_ID, "arn": f"arn:aws:iam::{_ACCOUNT_ID}:root"},
             "protocolVersion": "1.00"}
    out = _lam._invoke(lam, _lam._norm_name(t["function_arn"]), json.dumps(event).encode())
    if out.status == 404:
        return _error_xml("InternalError", f"The Object Lambda transformation function {t['function_arn']} does not exist.", f"/{key}", 500)
    fn_err = (out.headers or {}).get("X-Amz-Function-Error")
    try:
        res = json.loads(out.body or b"null")
    except ValueError:
        res = None
    if out.status != 200 or fn_err or not isinstance(res, dict) or "body" not in res:
        why = (res or {}).get("errorMessage") if isinstance(res, dict) and fn_err else "the Lambda did not return {statusCode, body}"
        return _error_xml("InternalError", f"Object Lambda transformation failed: {why}", f"/{key}", 500)
    raw_body = res["body"]
    data = base64.b64decode(raw_body) if res.get("isBase64Encoded") else (raw_body if isinstance(raw_body, bytes) else str(raw_body if raw_body is not None else "").encode())
    hdrs = {str(k): str(v) for k, v in (res.get("headers") or {}).items() if str(k).lower() != "content-type"}
    ctype = next((str(v) for k, v in (res.get("headers") or {}).items() if str(k).lower() == "content-type"), src.media_type)
    return S3Response(status=int(res.get("statusCode") or 200), headers=hdrs, body=data, media_type=ctype)


# ── S3 Control: shared helpers for the batch-2 control planes (MRAP / Access Grants / Batch Operations)
def _s3c_root(body: bytes):
    """Parse a restXml request body into an element tree with the namespaces stripped (None if malformed)."""
    try:
        root = ET.fromstring(body or b"<x/>")
    except ET.ParseError:
        return None
    for e in root.iter():
        if isinstance(e.tag, str) and "}" in e.tag:
            e.tag = e.tag.split("}", 1)[1]
    return root


def _s3c_malformed() -> S3Response:
    return _s3c_error("MalformedXML", "The XML you provided was not well-formed or did not validate against our published schema.", 400)


def _s3c_ok(op: str, inner: str = "") -> S3Response:
    return _xml_response(f'<?xml version="1.0" encoding="UTF-8"?><{op}Result xmlns="{_S3C_NS}">{inner}</{op}Result>')


def _inner_xml(el) -> str:
    return "".join(ET.tostring(c, encoding="unicode") for c in list(el)) if el is not None else ""


def _tags_of(el) -> list:
    return [(_child_text(t, "Key"), _child_text(t, "Value")) for t in list(el)] if el is not None else []


def _tags_xml(tags: list, wrapper: str = "Tags", member: str = "member") -> str:
    return f"<{wrapper}>" + "".join(f"<{member}><Key>{_xml_escape(k)}</Key><Value>{_xml_escape(v)}</Value></{member}>" for k, v in tags) + f"</{wrapper}>"


def _page(items: list, query: dict, default: int = 1000):
    """(slice, next_token) from nextToken/maxResults (offset tokens)."""
    try:
        start = int(query.get("nextToken") or 0)
        size = max(1, min(int(query.get("maxResults") or default), default))
    except (TypeError, ValueError):
        start, size = 0, default
    nxt = str(start + size) if start + size < len(items) else ""
    return items[start:start + size], nxt


def _next_xml(tok: str) -> str:
    return f"<NextToken>{tok}</NextToken>" if tok else ""


_REGIONS = {"us-east-1", "us-east-2", "us-west-1", "us-west-2", "af-south-1", "ap-east-1", "ap-south-1", "ap-south-2",
            "ap-southeast-1", "ap-southeast-2", "ap-southeast-3", "ap-southeast-4", "ap-northeast-1", "ap-northeast-2",
            "ap-northeast-3", "ca-central-1", "ca-west-1", "eu-central-1", "eu-central-2", "eu-west-1", "eu-west-2",
            "eu-west-3", "eu-south-1", "eu-south-2", "eu-north-1", "il-central-1", "me-south-1", "me-central-1", "sa-east-1"}
_ROLE_RE = re.compile(r"^arn:aws(-[a-z]+)*:iam::(\d{12}):role/[\w+=,.@/-]+$")


# ── S3 Control: Multi-Region Access Points (restXml /v20180820/mrap/…, /async-requests/mrap/…)
# An MRAP is a control-plane record in store.account["mrap"] over buckets in DISTINCT regions.
# Create/Delete/PutPolicy are asynchronous in real S3 (a RequestTokenARN you poll with
# DescribeMultiRegionAccessPointOperation); here they complete inline and the operation record
# is already SUCCEEDED. Data-plane requests addressed to the alias (<id>.mrap) or the MRAP ARN
# go to the highest-dial member bucket (that has the object, for reads); writes are mirrored to
# every other member bucket synchronously (real MRAP replication is asynchronous).
def _mraps(store: ObjectStore) -> dict:
    return store.account.setdefault("mrap", {})


def _mrap_ops(store: ObjectStore) -> dict:
    return store.account.setdefault("mrap_ops", {})


def _bucket_region(store: ObjectStore, bucket: str) -> str:
    return (store.buckets.get(bucket) or {}).get("region") or "us-east-1"


def _mrap_arn(alias: str) -> str:
    return f"arn:aws:s3::{_ACCOUNT_ID}:accesspoint/{alias}"


def _mrap_report_xml(store: ObjectStore, tag: str, r: dict) -> str:
    pab = "<PublicAccessBlock>" + "".join(f"<{k}>{'true' if r['pab'].get(k) else 'false'}</{k}>" for k in _PAB_KEYS) + "</PublicAccessBlock>"
    regs = "<Regions>" + "".join(f"<Region><Bucket>{_xml_escape(b)}</Bucket><Region>{_bucket_region(store, b)}</Region>"
                                 f"<BucketAccountId>{_ACCOUNT_ID}</BucketAccountId></Region>" for b in r["buckets"]) + "</Regions>"
    return (f"<{tag}><Name>{_xml_escape(r['name'])}</Name><Alias>{r['alias']}</Alias><CreatedAt>{r['created']}</CreatedAt>"
            f"{pab}<Status>{r['status']}</Status>{regs}</{tag}>")


def _mrap_find(store: ObjectStore, ident: str):
    """By name, alias (<id>.mrap) or ARN."""
    ident = ident.rsplit("accesspoint/", 1)[-1] if "accesspoint/" in ident else ident
    m = _mraps(store)
    if ident in m:
        return m[ident]
    return next((r for r in m.values() if r["alias"] == ident), None)


_MRAP_VERB = {"CreateMultiRegionAccessPoint": "create", "DeleteMultiRegionAccessPoint": "delete", "PutMultiRegionAccessPointPolicy": "put-policy"}


def _mrap_new_op(store: ObjectStore, op: str, params_tag: str, params_xml: str, regions: list) -> str:
    token = f"arn:aws:s3:us-west-2:{_ACCOUNT_ID}:async-request/mrap/{_MRAP_VERB[op]}/{uuid.uuid4().hex}"
    _mrap_ops(store)[token] = {"created": _now(), "operation": op, "params_tag": params_tag, "params": params_xml, "regions": regions}
    return token


def _mrap_dials(store: ObjectStore, r: dict) -> dict:
    return {b: int(r["routes"].get(b, 100)) for b in r["buckets"]}


def _s3c_mrap(store: ObjectStore, method: str, segs: list, query: dict, body: bytes) -> S3Response:
    rest = segs[2:]
    if segs[1] == "async-requests":
        if len(rest) < 2 or rest[0] != "mrap":
            return _s3c_error("NotImplemented", "Unknown async request operation.", 501)
        if method == "GET":
            tok = "/".join(rest[1:])
            op = _mrap_ops(store).get(tok)
            if op is None:
                return _s3c_error("NoSuchAsyncRequest", "The specified async request does not exist.", 404)
            regs = "".join(f"<Region><Name>{x}</Name><RequestStatus>SUCCEEDED</RequestStatus></Region>" for x in op["regions"])
            return _s3c_ok("DescribeMultiRegionAccessPointOperation",
                           f"<AsyncOperation><CreationTime>{op['created']}</CreationTime><Operation>{op['operation']}</Operation>"
                           f"<RequestTokenARN>{tok}</RequestTokenARN><RequestParameters>{op['params']}</RequestParameters>"
                           f"<RequestStatus>SUCCEEDED</RequestStatus><ResponseDetails><MultiRegionAccessPointDetails><Regions>{regs}</Regions>"
                           f"</MultiRegionAccessPointDetails></ResponseDetails></AsyncOperation>")
        if method == "POST" and len(rest) == 2:
            return _mrap_async(store, rest[1], body)
        return _s3c_error("MethodNotAllowed", method, 405)
    # /mrap/instances[/{name+}[/policy|/policystatus|/routes]]
    if not rest or rest[0] != "instances":
        return _s3c_error("NotImplemented", "Unknown MultiRegionAccessPoint operation.", 501)
    rest = rest[1:]
    if not rest:
        if method != "GET":
            return _s3c_error("MethodNotAllowed", method, 405)
        rows, nxt = _page([_mraps(store)[n] for n in sorted(_mraps(store))], query)
        return _s3c_ok("ListMultiRegionAccessPoints", "<AccessPoints>" + "".join(_mrap_report_xml(store, "AccessPoint", r) for r in rows) + f"</AccessPoints>{_next_xml(nxt)}")
    sub = rest[-1] if rest[-1] in ("policy", "policystatus", "routes") and len(rest) > 1 else ""
    ident = "/".join(rest[:-1] if sub else rest)
    r = _mrap_find(store, ident)
    if r is None:
        return _s3c_error("NoSuchMultiRegionAccessPoint", "The specified Multi-Region Access Point does not exist.", 404)
    if not sub and method == "GET":
        return _s3c_ok("GetMultiRegionAccessPoint", _mrap_report_xml(store, "AccessPoint", r))
    if sub == "policy" and method == "GET":
        if not r.get("policy"):
            return _s3c_error("NoSuchMultiRegionAccessPointPolicy", "The specified Multi-Region Access Point policy does not exist.", 404)
        return _s3c_ok("GetMultiRegionAccessPointPolicy", f"<Policy><Established><Policy>{_xml_escape(r['policy'])}</Policy></Established><Proposed/></Policy>")
    if sub == "policystatus" and method == "GET":
        if not r.get("policy"):
            return _s3c_error("NoSuchMultiRegionAccessPointPolicy", "The specified Multi-Region Access Point policy does not exist.", 404)
        pub = _policy_is_public(json.loads(r["policy"]))
        return _s3c_ok("GetMultiRegionAccessPointPolicyStatus", f"<Established><IsPublic>{'true' if pub else 'false'}</IsPublic></Established>")
    if sub == "routes":
        if method == "GET":
            d = _mrap_dials(store, r)
            return _s3c_ok("GetMultiRegionAccessPointRoutes", f"<Mrap>{_mrap_arn(r['alias'])}</Mrap><Routes>" + "".join(
                f"<Route><Bucket>{_xml_escape(b)}</Bucket><Region>{_bucket_region(store, b)}</Region><TrafficDialPercentage>{d[b]}</TrafficDialPercentage></Route>"
                for b in r["buckets"]) + "</Routes>")
        if method == "PATCH":
            root = _s3c_root(body)
            if root is None:
                return _s3c_malformed()
            upd = {}
            for el in _children(_child(root, "RouteUpdates"), "Route"):
                b = _child_text(el, "Bucket")
                if not b and _child_text(el, "Region"):     # a route can be addressed by its region
                    b = next((x for x in r["buckets"] if _bucket_region(store, x) == _child_text(el, "Region")), "")
                try:
                    pct = int(_child_text(el, "TrafficDialPercentage"))
                except ValueError:
                    return _s3c_error("InvalidRequest", "TrafficDialPercentage must be an integer between 0 and 100.", 400)
                if b not in r["buckets"]:
                    return _s3c_error("InvalidRequest", f"Route bucket/region is not part of Multi-Region Access Point {r['name']}.", 400)
                if not 0 <= pct <= 100:
                    return _s3c_error("InvalidRequest", "TrafficDialPercentage must be between 0 and 100.", 400)
                upd[b] = pct
            if not upd:
                return _s3c_error("InvalidRequest", "RouteUpdates must contain at least one route.", 400)
            merged = {**_mrap_dials(store, r), **upd}
            if not any(merged.values()):
                return _s3c_error("InvalidRequest", "At least one route must be active (TrafficDialPercentage > 0).", 400)
            r["routes"] = merged
            return _done(store, _empty_response(200))
    return _s3c_error("MethodNotAllowed", method, 405)


def _mrap_async(store: ObjectStore, op: str, body: bytes) -> S3Response:
    root = _s3c_root(body)
    if root is None:
        return _s3c_malformed()
    det = _child(root, "Details")
    name = _child_text(det, "Name")
    ms = _mraps(store)
    if op == "create":
        if not re.match(r"^[a-z0-9][a-z0-9-]{1,48}[a-z0-9]$", name):
            return _s3c_error("InvalidRequest", "Multi-Region Access Point names must be 3-50 characters of lowercase letters, numbers and hyphens.", 400)
        if name in ms:
            return _s3c_error("MultiRegionAccessPointAlreadyExists", "A Multi-Region Access Point with this name already exists.", 409)
        regs = _children(_child(det, "Regions"), "Region")
        if not regs:
            return _s3c_error("InvalidRequest", "At least one bucket (Regions) is required.", 400)
        buckets, seen = [], {}
        for el in regs:
            b, acct = _child_text(el, "Bucket"), _child_text(el, "BucketAccountId", _ACCOUNT_ID)
            if acct != _ACCOUNT_ID:
                return _s3c_error("InvalidRequest", "Buckets owned by other accounts are not supported.", 400)
            if not b or not store.bucket_exists(b) or is_directory_bucket(store, b):
                return _s3c_error("NoSuchBucket", f"The specified bucket does not exist: {b}", 404)
            rg = _bucket_region(store, b)
            if rg not in _REGIONS:
                return _s3c_error("InvalidRequest", f"{rg} is not a valid region.", 400)
            if rg in seen:
                return _s3c_error("InvalidRequest", f"Buckets {seen[rg]} and {b} are in the same region ({rg}); a Multi-Region Access Point needs one bucket per region.", 400)
            if any(b in m["buckets"] for m in ms.values()):
                return _s3c_error("InvalidRequest", f"Bucket {b} is already part of a Multi-Region Access Point.", 400)
            seen[rg] = b
            buckets.append(b)
        pab_el = _child(det, "PublicAccessBlock")
        pab = {k: (_child_text(pab_el, k).lower() == "true" if pab_el is not None else True) for k in _PAB_KEYS}
        alias = uuid.uuid4().hex[:13].translate(str.maketrans("0123456789abcdef", "abcdefghijklmnop")) + ".mrap"
        ms[name] = {"name": name, "alias": alias, "created": _now(), "pab": pab, "buckets": buckets, "routes": {b: 100 for b in buckets},
                    "status": "READY", "policy": None}
        regions = [_bucket_region(store, b) for b in buckets]
        params = ("<CreateMultiRegionAccessPointRequest>" + f"<Name>{_xml_escape(name)}</Name>" + _inner_xml(pab_el and pab_el).join(["<PublicAccessBlock>", "</PublicAccessBlock>"])
                  + "<Regions>" + "".join(f"<Region><Bucket>{_xml_escape(b)}</Bucket><BucketAccountId>{_ACCOUNT_ID}</BucketAccountId></Region>" for b in buckets)
                  + "</Regions></CreateMultiRegionAccessPointRequest>")
        tok = _mrap_new_op(store, "CreateMultiRegionAccessPoint", "", params, regions)
    elif op == "delete":
        r = ms.get(name)
        if r is None:
            return _s3c_error("NoSuchMultiRegionAccessPoint", "The specified Multi-Region Access Point does not exist.", 404)
        regions = [_bucket_region(store, b) for b in r["buckets"]]
        del ms[name]
        tok = _mrap_new_op(store, "DeleteMultiRegionAccessPoint", "", f"<DeleteMultiRegionAccessPointRequest><Name>{_xml_escape(name)}</Name></DeleteMultiRegionAccessPointRequest>", regions)
    elif op == "put-policy":
        r = ms.get(name)
        if r is None:
            return _s3c_error("NoSuchMultiRegionAccessPoint", "The specified Multi-Region Access Point does not exist.", 404)
        doc = _child_text(det, "Policy")
        try:
            if not isinstance(json.loads(doc), dict):
                raise ValueError
        except Exception:
            return _s3c_error("MalformedPolicy", "Policies must be valid JSON and the first byte must be '{'", 400)
        r["policy"] = doc
        tok = _mrap_new_op(store, "PutMultiRegionAccessPointPolicy", "",
                           f"<PutMultiRegionAccessPointPolicyRequest><Name>{_xml_escape(name)}</Name><Policy>{_xml_escape(doc)}</Policy></PutMultiRegionAccessPointPolicyRequest>",
                           [_bucket_region(store, b) for b in r["buckets"]])
    else:
        return _s3c_error("NotImplemented", "Unknown async request operation.", 501)
    verb = {"create": "CreateMultiRegionAccessPoint", "delete": "DeleteMultiRegionAccessPoint", "put-policy": "PutMultiRegionAccessPointPolicy"}[op]
    return _done(store, _s3c_ok(verb, f"<RequestTokenARN>{tok}</RequestTokenARN>"))


def _mrap_lookup(store: ObjectStore, raw: str):
    """(record, key) when the path addresses an MRAP by alias (<id>.mrap) or ARN, else (None, '')."""
    ms = (getattr(store, "account", None) or {}).get("mrap")
    if not ms:
        return None, ""
    if raw.startswith("arn:aws:s3::") and ":accesspoint/" in raw:
        tail = raw.split(":accesspoint/", 1)[1]
        alias, _, key = tail.partition("/")
    else:
        alias, _, key = urllib.parse.unquote(raw.partition("/")[0]), "", raw.partition("/")[2]
    if not alias.endswith(".mrap"):
        return None, ""
    return next(((r, key) for r in ms.values() if r["alias"] == alias), (None, ""))


def _mrap_dispatch(store: ObjectStore, r: dict, method: str, key: str, query: dict, headers: dict, body: bytes) -> S3Response:
    """Data plane through an MRAP: object operations only (like real S3, no bucket listing)."""
    if not key:
        return _error_xml("InvalidRequest", "Bucket-level operations are not supported through a Multi-Region Access Point.", "/", 400)
    dials = _mrap_dials(store, r)
    active = [b for b in r["buckets"] if dials[b] > 0 and store.bucket_exists(b)]
    active.sort(key=lambda b: (-dials[b], r["buckets"].index(b)))
    if not active:
        return _error_xml("NoSuchBucket", "No active bucket behind this Multi-Region Access Point.", f"/{key}", 404)
    lh = {str(k).lower(): v for k, v in headers.items()}
    if method in ("GET", "HEAD"):
        pick = next((b for b in active if (_ensure_object_entry(store, b, key, create=False) or {}).get("versions")), active[0])
        return _dispatch_inner(store, method, f"/{pick}/{key}", query, headers, body)
    primary = active[0]
    resp = _dispatch_inner(store, method, f"/{primary}/{key}", query, headers, body)
    if resp.status >= 300 or "tagging" in query or "acl" in query:
        return resp
    completes_write = (method == "PUT" and not query.get("uploadId") and not query.get("partNumber")) or \
                      (method == "POST" and query.get("uploadId")) or method == "DELETE" and not query.get("uploadId")
    if completes_write:
        for other in r["buckets"]:
            if other == primary or not store.bucket_exists(other):
                continue
            if method == "DELETE":
                delete_object(store, other, key, {}, lh)
            else:
                copy_object(store, other, key, {"x-amz-copy-source": f"/{primary}/{urllib.parse.quote(key)}"})
    return resp


# ── S3 Control: Access Grants (restXml /v20180820/accessgrantsinstance…)
# One Access Grants instance per account holds locations (a bucket/prefix an IAM role can reach)
# and grants (grantee + READ/WRITE/READWRITE + prefix scope under a location). GetDataAccess
# returns temporary credentials (ASIA… key, secret, session token) that the data plane ENFORCES:
# a request signed with such a key id is limited to the grant's bucket/prefix and permission and
# is refused after expiry. The secret/signature are not verified (the simulator never
# authenticates), and grantee identity is not matched against a caller.
def _ag(store: ObjectStore) -> dict | None:
    return store.account.get("grants")


def _ag_no_instance() -> S3Response:
    return _s3c_error("NoSuchAccessGrantsInstanceError", "The S3 Access Grants instance does not exist in this account.", 404)


def _ag_inst_fields(i: dict) -> str:
    out = f"<CreatedAt>{i['created']}</CreatedAt><AccessGrantsInstanceId>default</AccessGrantsInstanceId><AccessGrantsInstanceArn>{i['arn']}</AccessGrantsInstanceArn>"
    if i.get("idc"):
        out += (f"<IdentityCenterArn>{_xml_escape(i['idc'])}</IdentityCenterArn><IdentityCenterInstanceArn>{_xml_escape(i['idc'])}</IdentityCenterInstanceArn>"
                f"<IdentityCenterApplicationArn>arn:aws:sso::{_ACCOUNT_ID}:application/ssoins-vyomi/apl-{i['arn'].rsplit('/', 1)[-1]}0000</IdentityCenterApplicationArn>")
    return out


def _ag_loc_fields(loc: dict) -> str:
    return (f"<CreatedAt>{loc['created']}</CreatedAt><AccessGrantsLocationId>{loc['id']}</AccessGrantsLocationId><AccessGrantsLocationArn>{loc['arn']}</AccessGrantsLocationArn>"
            f"<LocationScope>{_xml_escape(loc['scope'])}</LocationScope><IAMRoleArn>{_xml_escape(loc['role'])}</IAMRoleArn>")


def _ag_grant_fields(g: dict) -> str:
    app = f"<ApplicationArn>{_xml_escape(g['app'])}</ApplicationArn>" if g.get("app") else ""
    return (f"<CreatedAt>{g['created']}</CreatedAt><AccessGrantId>{g['id']}</AccessGrantId><AccessGrantArn>{g['arn']}</AccessGrantArn>"
            f"<Grantee><GranteeType>{g['gtype']}</GranteeType><GranteeIdentifier>{_xml_escape(g['gid'])}</GranteeIdentifier></Grantee>"
            f"<Permission>{g['perm']}</Permission><AccessGrantsLocationId>{g['loc']}</AccessGrantsLocationId>"
            f"<AccessGrantsLocationConfiguration><S3SubPrefix>{_xml_escape(g['sub'])}</S3SubPrefix></AccessGrantsLocationConfiguration>"
            f"<GrantScope>{_xml_escape(g['scope'])}</GrantScope>{app}")


def _s3c_grants(store: ObjectStore, method: str, segs: list, query: dict, body: bytes) -> S3Response:
    s0, rest = segs[1], segs[2:]
    if s0 == "accessgrantsinstances":
        if method != "GET":
            return _s3c_error("MethodNotAllowed", method, 405)
        inst = (_ag(store) or {}).get("instance")
        return _s3c_ok("ListAccessGrantsInstances", "<AccessGrantsInstancesList>" + (f"<AccessGrantsInstance>{_ag_inst_fields(inst)}</AccessGrantsInstance>" if inst else "") + "</AccessGrantsInstancesList>")
    ag = _ag(store)
    sub = rest[0] if rest else ""
    if not sub:                                                        # the instance itself
        if method == "POST":
            if ag and ag.get("instance"):
                return _s3c_error("AccessGrantsInstanceAlreadyExists", "An S3 Access Grants instance already exists in this account.", 409)
            root = _s3c_root(body)
            if root is None:
                return _s3c_malformed()
            idc = _child_text(root, "IdentityCenterArn")
            ag = store.account["grants"] = {"instance": {"created": _now(), "arn": f"arn:aws:s3:us-east-1:{_ACCOUNT_ID}:access-grants/default", "idc": idc,
                                                          "tags": _tags_of(_child(root, "Tags"))},
                                            "locations": {}, "grants": {}, "policy": None, "creds": {}}
            return _done(store, _s3c_ok("CreateAccessGrantsInstance", _ag_inst_fields(ag["instance"])))
        if not ag or not ag.get("instance"):
            return _ag_no_instance()
        if method == "GET":
            return _s3c_ok("GetAccessGrantsInstance", _ag_inst_fields(ag["instance"]))
        if method == "DELETE":
            if ag["locations"] or ag["grants"]:
                return _s3c_error("InvalidRequest", "Delete all access grants and locations before deleting the S3 Access Grants instance.", 409)
            store.account.pop("grants", None)
            return _done(store, _empty_response(204))
        return _s3c_error("MethodNotAllowed", method, 405)
    if not ag or not ag.get("instance"):
        return _ag_no_instance()
    inst = ag["instance"]
    if sub == "prefix" and method == "GET":
        return _s3c_ok("GetAccessGrantsInstanceForPrefix", f"<AccessGrantsInstanceArn>{inst['arn']}</AccessGrantsInstanceArn><AccessGrantsInstanceId>default</AccessGrantsInstanceId>")
    if sub == "identitycenter":
        if method == "POST":
            root = _s3c_root(body)
            arn = _child_text(root, "IdentityCenterArn") if root is not None else ""
            if not arn.startswith("arn:aws:sso"):
                return _s3c_error("InvalidRequest", "IdentityCenterArn must be an IAM Identity Center instance ARN (arn:aws:sso:::instance/…).", 400)
            inst["idc"] = arn
            return _done(store, _empty_response(200))
        if method == "DELETE":
            inst["idc"] = ""
            return _done(store, _empty_response(200))
    if sub == "resourcepolicy":
        if method == "PUT":
            root = _s3c_root(body)
            doc = _child_text(root, "Policy") if root is not None else ""
            try:
                if not isinstance(json.loads(doc), dict):
                    raise ValueError
            except Exception:
                return _s3c_error("MalformedPolicy", "Policies must be valid JSON and the first byte must be '{'", 400)
            ag["policy"] = {"doc": doc, "org": _child_text(root, "Organization"), "created": _now()}
            p = ag["policy"]
            return _done(store, _s3c_ok("PutAccessGrantsInstanceResourcePolicy", f"<Policy>{_xml_escape(p['doc'])}</Policy><Organization>{_xml_escape(p['org'])}</Organization><CreatedAt>{p['created']}</CreatedAt>"))
        if method == "GET":
            p = ag.get("policy")
            if not p:
                return _s3c_error("NoSuchResourcePolicy", "The S3 Access Grants instance has no resource policy.", 404)
            return _s3c_ok("GetAccessGrantsInstanceResourcePolicy", f"<Policy>{_xml_escape(p['doc'])}</Policy><Organization>{_xml_escape(p['org'])}</Organization><CreatedAt>{p['created']}</CreatedAt>")
        if method == "DELETE":
            ag["policy"] = None
            return _done(store, _empty_response(204))
    if sub == "locations" and method == "GET":
        locs = sorted(ag["locations"].values(), key=lambda x: x["scope"])
        want = query.get("locationscope")
        if want:
            locs = [x for x in locs if x["scope"].startswith(want.rstrip("*"))]
        rows, nxt = _page(locs, query)
        return _s3c_ok("ListAccessGrantsLocations", "<AccessGrantsLocationsList>" + "".join(f"<AccessGrantsLocation>{_ag_loc_fields(x)}</AccessGrantsLocation>" for x in rows) + f"</AccessGrantsLocationsList>{_next_xml(nxt)}")
    if sub == "location":
        return _ag_location(store, ag, method, rest[1:], body)
    if sub == "grants" and method == "GET":
        gs = sorted(ag["grants"].values(), key=lambda x: x["created"])
        for q, f in (("granteetype", "gtype"), ("granteeidentifier", "gid"), ("permission", "perm"), ("grantscope", "scope"), ("application_arn", "app")):
            if query.get(q):
                gs = [g for g in gs if g.get(f) == query[q]]
        rows, nxt = _page(gs, query)
        return _s3c_ok("ListAccessGrants", "<AccessGrantsList>" + "".join(f"<AccessGrant>{_ag_grant_fields(g)}</AccessGrant>" for g in rows) + f"</AccessGrantsList>{_next_xml(nxt)}")
    if sub == "grant":
        return _ag_grant(store, ag, method, rest[1:], body)
    if sub == "dataaccess" and method == "GET":
        return _ag_data_access(store, ag, query)
    return _s3c_error("NotImplemented", f"Access Grants operation '{sub}' is not implemented by Vyomi.", 501)


def _ag_location(store, ag, method, rest, body) -> S3Response:
    if method == "POST" and not rest:
        root = _s3c_root(body)
        if root is None:
            return _s3c_malformed()
        scope, role = _child_text(root, "LocationScope"), _child_text(root, "IAMRoleArn")
        m = re.match(r"^s3://([a-z0-9][a-z0-9.-]{1,61}[a-z0-9])?(/.*)?$", scope)
        if not m or (m.group(2) and not m.group(1)):
            return _s3c_error("InvalidRequest", "LocationScope must be s3://, s3://<bucket> or s3://<bucket>/<prefix>*.", 400)
        if m.group(1) and not store.bucket_exists(m.group(1)):
            return _s3c_error("NoSuchBucket", "The bucket of this location does not exist.", 404)
        if not _ROLE_RE.match(role):
            return _s3c_error("InvalidRequest", "IAMRoleArn must be the ARN of an IAM role.", 400)
        if any(x["scope"] == scope for x in ag["locations"].values()):
            return _s3c_error("InvalidRequest", "A location with this scope is already registered.", 409)
        lid = "default" if scope == "s3://" else uuid.uuid4().hex[:8] + "-" + uuid.uuid4().hex[:4]
        loc = {"id": lid, "scope": scope, "role": role, "created": _now(), "tags": _tags_of(_child(root, "Tags")),
               "arn": f"arn:aws:s3:us-east-1:{_ACCOUNT_ID}:access-grants/default/location/{lid}"}
        ag["locations"][lid] = loc
        return _done(store, _s3c_ok("CreateAccessGrantsLocation", _ag_loc_fields(loc)))
    loc = ag["locations"].get(rest[0]) if rest else None
    if loc is None:
        return _s3c_error("NoSuchAccessGrantsLocation", "The specified access grants location does not exist.", 404)
    if method == "GET":
        return _s3c_ok("GetAccessGrantsLocation", _ag_loc_fields(loc))
    if method == "PUT":
        root = _s3c_root(body)
        role = _child_text(root, "IAMRoleArn") if root is not None else ""
        if not _ROLE_RE.match(role):
            return _s3c_error("InvalidRequest", "IAMRoleArn must be the ARN of an IAM role.", 400)
        loc["role"] = role
        return _done(store, _s3c_ok("UpdateAccessGrantsLocation", _ag_loc_fields(loc)))
    if method == "DELETE":
        if any(g["loc"] == loc["id"] for g in ag["grants"].values()):
            return _s3c_error("InvalidRequest", "Delete the access grants of this location first.", 409)
        del ag["locations"][loc["id"]]
        return _done(store, _empty_response(204))
    return _s3c_error("MethodNotAllowed", method, 405)


def _ag_base(loc_scope: str) -> str:
    base = loc_scope[:-1] if loc_scope.endswith("*") else loc_scope
    return base + "/" if re.match(r"^s3://[^/]+$", base) else base


def _ag_grant(store, ag, method, rest, body) -> S3Response:
    if method == "POST" and not rest:
        root = _s3c_root(body)
        if root is None:
            return _s3c_malformed()
        loc = ag["locations"].get(_child_text(root, "AccessGrantsLocationId"))
        if loc is None:
            return _s3c_error("NoSuchAccessGrantsLocation", "The specified access grants location does not exist.", 404)
        gr = _child(root, "Grantee")
        gtype, gid = _child_text(gr, "GranteeType"), _child_text(gr, "GranteeIdentifier")
        perm = _child_text(root, "Permission")
        if gtype not in ("IAM", "DIRECTORY_USER", "DIRECTORY_GROUP") or not gid:
            return _s3c_error("InvalidRequest", "Grantee.GranteeType must be IAM, DIRECTORY_USER or DIRECTORY_GROUP, with a GranteeIdentifier.", 400)
        if gtype != "IAM" and not ag["instance"].get("idc"):
            return _s3c_error("InvalidRequest", "Directory grantees need an IAM Identity Center instance associated with the Access Grants instance.", 400)
        if gtype == "IAM" and not re.match(r"^arn:aws(-[a-z]+)*:iam::\d{12}:(role|user|root)", gid) and not re.match(r"^\d{12}$", gid):
            return _s3c_error("InvalidRequest", "An IAM grantee must be an IAM user/role ARN or an account id.", 400)
        if perm not in ("READ", "WRITE", "READWRITE"):
            return _s3c_error("InvalidRequest", "Permission must be READ, WRITE or READWRITE.", 400)
        sub = _child_text(_child(root, "AccessGrantsLocationConfiguration"), "S3SubPrefix")
        ptype = _child_text(root, "S3PrefixType")
        if ptype not in ("", "Object"):
            return _s3c_error("InvalidRequest", "S3PrefixType must be Object when specified.", 400)
        if ptype == "Object" and not sub:
            return _s3c_error("InvalidRequest", "S3SubPrefix is the object key when S3PrefixType is Object.", 400)
        scope = _ag_base(loc["scope"]) + (sub if (sub or ptype) else "*")
        if ptype == "Object":
            scope = scope.rstrip("*") if not sub.endswith("*") else scope
        gid_new = uuid.uuid4().hex[:8] + "-" + uuid.uuid4().hex[:4]
        g = {"id": gid_new, "arn": f"arn:aws:s3:us-east-1:{_ACCOUNT_ID}:access-grants/default/grant/{gid_new}", "created": _now(), "gtype": gtype, "gid": gid,
             "perm": perm, "loc": loc["id"], "sub": sub, "scope": scope, "app": _child_text(root, "ApplicationArn"), "tags": _tags_of(_child(root, "Tags")),
             "object": ptype == "Object"}
        ag["grants"][gid_new] = g
        return _done(store, _s3c_ok("CreateAccessGrant", _ag_grant_fields(g)))
    g = ag["grants"].get(rest[0]) if rest else None
    if g is None:
        return _s3c_error("NoSuchAccessGrant", "The specified access grant does not exist.", 404)
    if method == "GET":
        return _s3c_ok("GetAccessGrant", _ag_grant_fields(g))
    if method == "DELETE":
        del ag["grants"][g["id"]]
        return _done(store, _empty_response(204))
    return _s3c_error("MethodNotAllowed", method, 405)


def _ag_covers(scope: str, target: str, is_object: bool) -> bool:
    """Does a grant scope (s3://bucket/prefix* or an exact object) cover a target s3:// path?"""
    if scope.endswith("*"):
        return target.startswith(scope[:-1])
    return target == scope


def _ag_data_access(store, ag, query) -> S3Response:
    target = query.get("target") or ""
    perm = query.get("permission") or ""
    ttype = query.get("targetType") or ""
    if not target.startswith("s3://") or perm not in ("READ", "WRITE", "READWRITE"):
        return _s3c_error("InvalidRequest", "Target must be an s3:// path and Permission READ, WRITE or READWRITE.", 400)
    try:
        dur = int(query.get("durationSeconds") or 3600)
    except ValueError:
        dur = -1
    if not 900 <= dur <= 43200:
        return _s3c_error("InvalidRequest", "DurationSeconds must be between 900 and 43200.", 400)
    wild = target.endswith("*")
    probe = target[:-1] if wild else target
    cands = []
    for g in ag["grants"].values():
        if g["perm"] != "READWRITE" and g["perm"] != perm:
            continue
        if wild:       # a prefix target needs a grant at least as broad
            if g["scope"].endswith("*") and probe.startswith(g["scope"][:-1]):
                cands.append(g)
        elif _ag_covers(g["scope"], probe, False):
            cands.append(g)
    if not cands:
        return _s3c_error("AccessDenied", "No access grant covers the requested target and permission.", 403)
    g = max(cands, key=lambda x: len(x["scope"]))
    # credentials are limited to the matched grant, narrowed to the requested permission
    granted = perm if g["perm"] == "READWRITE" else g["perm"]
    akid, secret, token = "ASIA" + uuid.uuid4().hex[:16].upper(), uuid.uuid4().hex + uuid.uuid4().hex[:8], uuid.uuid4().hex + uuid.uuid4().hex
    exp_dt = datetime.now(timezone.utc) + timedelta(seconds=dur)
    m = re.match(r"^s3://([^/]+)/?(.*)$", g["scope"])
    ag["creds"][akid] = {"bucket": m.group(1), "prefix": m.group(2).rstrip("*"), "exact": not g["scope"].endswith("*"), "perm": granted,
                         "expires": exp_dt.timestamp(), "token": token, "grant": g["id"]}
    matched = g["scope"][:-1] if g["scope"].endswith("*") else g["scope"]
    return _done(store, _s3c_ok("GetDataAccess",
        f"<Credentials><AccessKeyId>{akid}</AccessKeyId><SecretAccessKey>{secret}</SecretAccessKey><SessionToken>{token}</SessionToken>"
        f"<Expiration>{exp_dt.strftime('%Y-%m-%dT%H:%M:%S.000Z')}</Expiration></Credentials><MatchedGrantTarget>{_xml_escape(matched)}</MatchedGrantTarget>"
        f"<Grantee><GranteeType>{g['gtype']}</GranteeType><GranteeIdentifier>{_xml_escape(g['gid'])}</GranteeIdentifier></Grantee>"))


def _grant_cred_guard(store: ObjectStore, method: str, raw: str, query: dict, lheaders: dict) -> S3Response | None:
    """Requests signed with an Access Grants (GetDataAccess) key id are confined to the grant."""
    auth = lheaders.get("authorization") or ""
    m = re.search(r"Credential=(ASIA[A-Z0-9]{16})/", auth)
    creds = (store.account.get("grants") or {}).get("creds") if m else None
    c = (creds or {}).get(m.group(1)) if m else None
    if c is None:
        return None
    deny = lambda msg: _error_xml("AccessDenied", msg, "/" + raw, 403)
    if time.time() > c["expires"]:
        return _error_xml("ExpiredToken", "The provided token has expired.", "/" + raw, 400)
    tok = lheaders.get("x-amz-security-token")
    if tok and tok != c["token"]:
        return _error_xml("InvalidToken", "The provided token is malformed or otherwise invalid.", "/" + raw, 400)
    bucket, _, key = raw.partition("/")
    bucket = _resolve_access_point(store, urllib.parse.unquote(bucket))
    write = method not in ("GET", "HEAD")
    need = "WRITE" if write else "READ"
    if c["perm"] != "READWRITE" and c["perm"] != need:
        return deny(f"The Access Grants credentials only allow {c['perm']}.")
    if bucket != c["bucket"]:
        return deny("The Access Grants credentials do not cover this bucket.")
    if key:
        if (c["exact"] and key != c["prefix"]) or (not c["exact"] and not key.startswith(c["prefix"])):
            return deny("The Access Grants credentials do not cover this key.")
    elif method == "GET" and not c["exact"] and not any(k in query for k in ("acl", "policy", "versioning", "uploads")):
        if not str(query.get("prefix") or "").startswith(c["prefix"]):
            return deny("ListObjects needs a prefix within the Access Grants scope.")
    else:
        return deny("Bucket-level operations are outside the Access Grants scope.")
    return None


# ── S3 Control: Batch Operations (restXml /v20180820/jobs…)
# A job = manifest (CSV of bucket,key[,version] or an inventory CSV) + one operation that is
# EXECUTED against the store for every row + a completion report written to the report bucket.
# Lifecycle: Suspended (ConfirmationRequired) -> Ready -> Active -> Complete/Failed (Cancelled).
# There is no worker thread (Nano has none and the offline loop must not block): jobs advance
# one stage per control-plane or object request (a poll of DescribeJob/ListJobs is enough), and
# the Active->Complete stage runs every task synchronously, in-process, against the store.
_JOB_OPS = ("LambdaInvoke", "S3PutObjectCopy", "S3PutObjectAcl", "S3PutObjectTagging", "S3DeleteObjectTagging", "S3InitiateRestoreObject",
            "S3PutObjectLegalHold", "S3PutObjectRetention", "S3ReplicateObject")
_JOB_UNSUPPORTED = ("S3ComputeObjectChecksum", "S3UpdateObjectEncryption")
_JOB_TERMINAL = ("Complete", "Failed", "Cancelled")
_JOBS_BUSY = [False]


def _jobs(store: ObjectStore) -> dict:
    return store.account.setdefault("jobs", {})


def _job_progress_xml(j: dict) -> str:
    p = j["progress"]
    return (f"<ProgressSummary><TotalNumberOfTasks>{p['total']}</TotalNumberOfTasks><NumberOfTasksSucceeded>{p['ok']}</NumberOfTasksSucceeded>"
            f"<NumberOfTasksFailed>{p['fail']}</NumberOfTasksFailed><Timers><ElapsedTimeInActiveSeconds>{int(j.get('active_secs', 0))}</ElapsedTimeInActiveSeconds></Timers></ProgressSummary>")


def _job_xml(j: dict) -> str:
    fr = "".join(f"<member><FailureCode>{_xml_escape(c)}</FailureCode><FailureReason>{_xml_escape(m)}</FailureReason></member>" for c, m in j.get("failures", []))
    out = (f"<JobId>{j['id']}</JobId><ConfirmationRequired>{'true' if j['confirm'] else 'false'}</ConfirmationRequired>"
           f"<Description>{_xml_escape(j['description'])}</Description><JobArn>{j['arn']}</JobArn><Status>{j['status']}</Status>"
           f"<Manifest>{j['manifest_xml']}</Manifest><Operation>{j['operation_xml']}</Operation><Priority>{j['priority']}</Priority>{_job_progress_xml(j)}"
           f"<StatusUpdateReason>{_xml_escape(j.get('reason', ''))}</StatusUpdateReason>"
           + (f"<FailureReasons>{fr}</FailureReasons>" if fr else "")
           + f"<Report>{j['report_xml']}</Report><CreationTime>{j['created']}</CreationTime>"
           + (f"<TerminationDate>{j['terminated']}</TerminationDate>" if j.get("terminated") else "")
           + f"<RoleArn>{_xml_escape(j['role'])}</RoleArn>")
    if j["status"] == "Suspended":
        out += f"<SuspendedDate>{j['created']}</SuspendedDate><SuspendedCause>Job is waiting for confirmation.</SuspendedCause>"
    return out


def _job_summary_xml(j: dict) -> str:
    return (f"<member><JobId>{j['id']}</JobId><Description>{_xml_escape(j['description'])}</Description><Operation>{j['op']}</Operation>"
            f"<Priority>{j['priority']}</Priority><Status>{j['status']}</Status><CreationTime>{j['created']}</CreationTime>"
            + (f"<TerminationDate>{j['terminated']}</TerminationDate>" if j.get("terminated") else "") + f"{_job_progress_xml(j)}</member>")


def _s3c_jobs(store: ObjectStore, method: str, segs: list, query: dict, body: bytes) -> S3Response:
    rest = segs[2:]
    js = _jobs(store)
    if not rest:
        if method == "GET":
            want = query.get("jobStatuses") or query.get("jobstatuses") or ""
            want = [w for w in (want if isinstance(want, (list, tuple)) else str(want).split(",")) if w]
            rows = sorted(js.values(), key=lambda j: j["created"], reverse=True)
            if want:
                rows = [j for j in rows if j["status"] in want]
            page, nxt = _page(rows, query)
            return _s3c_ok("ListJobs", f"<Jobs>{''.join(_job_summary_xml(j) for j in page)}</Jobs>{_next_xml(nxt)}")
        if method == "POST":
            return _job_create(store, body)
        return _s3c_error("MethodNotAllowed", method, 405)
    j = js.get(rest[0])
    if j is None:
        return _s3c_error("NoSuchJob", "The specified job does not exist.", 404)
    sub = rest[1] if len(rest) > 1 else ""
    if not sub and method == "GET":
        return _s3c_ok("DescribeJob", f"<Job>{_job_xml(j)}</Job>")
    if sub == "tagging":
        if method == "GET":
            return _s3c_ok("GetJobTagging", _tags_xml(j["tags"]))
        if method == "PUT":
            root = _s3c_root(body)
            if root is None:
                return _s3c_malformed()
            tags = _tags_of(_child(root, "Tags"))
            if len(tags) > 50 or len({k for k, _ in tags}) != len(tags) or any(not k for k, _ in tags):
                return _s3c_error("InvalidTag", "Tags must have unique non-empty keys and there can be at most 50.", 400)
            j["tags"] = tags
            return _done(store, _empty_response(204))
        if method == "DELETE":
            j["tags"] = []
            return _done(store, _empty_response(204))
    if sub == "priority" and method == "POST":
        try:
            pr = int(query.get("priority"))
            if pr < 0 or pr > 2147483647:
                raise ValueError
        except (TypeError, ValueError):
            return _s3c_error("InvalidRequest", "priority must be an integer between 0 and 2147483647.", 400)
        if j["status"] in _JOB_TERMINAL:
            return _s3c_error("JobStatusException", f"The job is {j['status']} and its priority can no longer be changed.", 409)
        j["priority"] = pr
        return _done(store, _s3c_ok("UpdateJobPriority", f"<JobId>{j['id']}</JobId><Priority>{pr}</Priority>"))
    if sub == "status" and method == "POST":
        req = query.get("requestedJobStatus")
        if req not in ("Ready", "Cancelled"):
            return _s3c_error("InvalidRequest", "RequestedJobStatus must be Ready or Cancelled.", 400)
        ok_from = ("Suspended",) if req == "Ready" else ("Suspended", "Ready", "Active", "Preparing", "New", "Paused")
        if j["status"] not in ok_from:
            return _s3c_error("JobStatusException", f"Job {j['id']} is {j['status']}; it cannot move to {req}.", 409)
        j["status"] = req
        j["reason"] = query.get("statusUpdateReason") or ""
        if req == "Cancelled":
            j["terminated"] = _now()
            j.pop("tasks", None)
        return _done(store, _s3c_ok("UpdateJobStatus", f"<JobId>{j['id']}</JobId><Status>{j['status']}</Status><StatusUpdateReason>{_xml_escape(j['reason'])}</StatusUpdateReason>"))
    return _s3c_error("MethodNotAllowed", method, 405)


def _arn_bucket(arn: str):
    m = re.match(r"^arn:aws[a-z-]*:s3:::([^/]+)(?:/(.*))?$", arn or "")
    return (m.group(1), m.group(2) or "") if m else (None, None)


def _job_create(store: ObjectStore, body: bytes) -> S3Response:
    root = _s3c_root(body)
    if root is None:
        return _s3c_malformed()
    js = _jobs(store)
    token = _child_text(root, "ClientRequestToken")
    if token:
        prior = next((j for j in js.values() if j.get("token") == token), None)
        if prior:
            return _s3c_ok("CreateJob", f"<JobId>{prior['id']}</JobId>")
    bad = lambda m, c="InvalidRequest", s=400: _s3c_error(c, m, s)
    op_el, man_el, rep_el = _child(root, "Operation"), _child(root, "Manifest"), _child(root, "Report")
    if op_el is None or not list(op_el):
        return bad("Operation is required.")
    op = list(op_el)[0].tag
    if len(list(op_el)) != 1:
        return bad("Exactly one operation must be specified.")
    if op in _JOB_UNSUPPORTED:
        return _s3c_error("NotImplemented", f"The {op} batch operation is not implemented by Vyomi.", 501)
    if op not in _JOB_OPS:
        return bad(f"Unknown operation {op}.")
    if _child(root, "ManifestGenerator") is not None and man_el is None:
        return _s3c_error("NotImplemented", "Generated manifests (ManifestGenerator) are not implemented by Vyomi; supply a CSV manifest.", 501)
    if man_el is None:
        return bad("Manifest is required.")
    if rep_el is None:
        return bad("Report is required (set Enabled=false for no report).")
    role = _child_text(root, "RoleArn")
    rm = _ROLE_RE.match(role)
    if not rm:
        return bad("RoleArn must be the ARN of an IAM role.")
    if rm.group(2) != _ACCOUNT_ID:
        return bad("The role must belong to this account.", "InvalidRequest")
    try:
        prio = int(_child_text(root, "Priority"))
        if prio < 0 or prio > 2147483647:
            raise ValueError
    except ValueError:
        return bad("Priority is required and must be an integer between 0 and 2147483647.")
    fmt = _child_text(_child(man_el, "Spec"), "Format")
    if fmt not in ("S3BatchOperations_CSV_20180820", "S3InventoryReport_CSV_20161130"):
        return bad("Manifest.Spec.Format must be S3BatchOperations_CSV_20180820 or S3InventoryReport_CSV_20161130.")
    loc = _child(man_el, "Location")
    mb, mk = _arn_bucket(_child_text(loc, "ObjectArn"))
    if not mb or not mk:
        return bad("Manifest.Location.ObjectArn must be an S3 object ARN.")
    if fmt == "S3BatchOperations_CSV_20180820" and not _children(_child(_child(man_el, "Spec"), "Fields"), "member"):
        return bad("Manifest.Spec.Fields (Bucket, Key[, VersionId]) is required for CSV manifests.")
    rep_on = _child_text(rep_el, "Enabled").lower() == "true"
    if rep_on:
        rb, _ = _arn_bucket(_child_text(rep_el, "Bucket"))
        if not rb or not store.bucket_exists(rb):
            return bad("Report.Bucket must be the ARN of an existing bucket.")
        if _child_text(rep_el, "Format") != "Report_CSV_20180820":
            return bad("Report.Format must be Report_CSV_20180820.")
        if _child_text(rep_el, "ReportScope") not in ("AllTasks", "FailedTasksOnly"):
            return bad("Report.ReportScope must be AllTasks or FailedTasksOnly.")
    tags = _tags_of(_child(root, "Tags"))
    if len(tags) > 50 or len({k for k, _ in tags}) != len(tags):
        return bad("Tags must have unique keys and there can be at most 50.", "InvalidTag")
    spec = {}
    if op == "S3PutObjectCopy":
        c = _child(op_el, "S3PutObjectCopy")
        tb, _ = _arn_bucket(_child_text(c, "TargetResource"))
        if not tb:
            return bad("S3PutObjectCopy.TargetResource must be a bucket ARN.")
        if not store.bucket_exists(tb):
            return bad("The copy target bucket does not exist.", "NoSuchBucket", 404)
        if _child(c, "ModifiedSinceConstraint") is not None or _child(c, "UnModifiedSinceConstraint") is not None:
            return _s3c_error("NotImplemented", "Modified-since constraints on S3PutObjectCopy are not implemented by Vyomi.", 501)
    elif op == "LambdaInvoke":
        if not _child_text(_child(op_el, "LambdaInvoke"), "FunctionArn"):
            return bad("LambdaInvoke.FunctionArn is required.")
    elif op == "S3PutObjectTagging":
        if not _tags_of(_child(_child(op_el, "S3PutObjectTagging"), "TagSet")):
            return bad("S3PutObjectTagging.TagSet is required.")
    elif op == "S3PutObjectRetention":
        r = _child(_child(op_el, "S3PutObjectRetention"), "Retention")
        if _child_text(r, "Mode") not in ("GOVERNANCE", "COMPLIANCE") or not _child_text(r, "RetainUntilDate"):
            return bad("Retention.Mode (GOVERNANCE|COMPLIANCE) and RetainUntilDate are required.")
    elif op == "S3PutObjectLegalHold":
        if _child_text(_child(_child(op_el, "S3PutObjectLegalHold"), "LegalHold"), "Status") not in ("ON", "OFF"):
            return bad("LegalHold.Status must be ON or OFF.")
    j = {"id": str(uuid.uuid4()), "token": token, "op": op, "confirm": _child_text(root, "ConfirmationRequired").lower() == "true",
         "description": _child_text(root, "Description"), "priority": prio, "role": role, "created": _now(), "tags": tags,
         "manifest_xml": _inner_xml(man_el), "operation_xml": _inner_xml(op_el), "report_xml": _inner_xml(rep_el),
         "progress": {"total": 0, "ok": 0, "fail": 0}, "failures": [], "reason": "", "active_secs": 0, "report_keys": []}
    j["arn"] = f"arn:aws:s3:us-east-1:{_ACCOUNT_ID}:job/{j['id']}"
    tasks, err = _job_read_manifest(store, man_el, fmt, mb, mk, _child_text(loc, "ObjectVersionId"), _child_text(loc, "ETag"))
    if err:
        j["status"], j["terminated"] = "Failed", _now()
        j["failures"] = [("ManifestError", err)]
    else:
        j["tasks"] = tasks
        j["progress"]["total"] = len(tasks)
        j["status"] = "Suspended" if j["confirm"] else "Ready"
    js[j["id"]] = j
    return _done(store, _s3c_ok("CreateJob", f"<JobId>{j['id']}</JobId>"))


def _job_read_manifest(store, man_el, fmt, mb, mk, vid, etag):
    if not store.bucket_exists(mb):
        return None, f"Manifest bucket {mb} does not exist."
    obj = _find_version(_ensure_object_entry(store, mb, mk, create=False), vid or None)
    if not obj or obj.get("is_delete_marker"):
        return None, f"Manifest object s3://{mb}/{mk} was not found."
    if etag and etag.strip('"') != str(obj.get("etag", "")).strip('"'):
        return None, "The manifest ETag does not match the object's ETag."
    fields = [(f.text or "").strip() for f in _children(_child(_child(man_el, "Spec"), "Fields"), "member")] or ["Bucket", "Key"]
    try:
        text = _version_bytes(store, mb, mk, obj).decode("utf-8")
        rows = list(csv.reader(io.StringIO(text)))
    except Exception:
        return None, "The manifest could not be read as a UTF-8 CSV."
    if "Bucket" not in fields or "Key" not in fields:
        return None, "Manifest fields must include Bucket and Key."
    ib, ik, iv = fields.index("Bucket"), fields.index("Key"), (fields.index("VersionId") if "VersionId" in fields else None)
    tasks = []
    for n, row in enumerate(rows, 1):
        if not row or not any(c.strip() for c in row):
            continue
        if len(row) <= max(ib, ik):
            return None, f"Manifest line {n} has fewer columns than Spec.Fields."
        v = row[iv].strip() if iv is not None and len(row) > iv else ""
        tasks.append([row[ib].strip(), urllib.parse.unquote_plus(row[ik].strip()), v])
    if not tasks:
        return None, "The manifest has no rows."
    return tasks, ""


def _jobs_tick(store: ObjectStore) -> None:
    """Advance every pending job one stage: Ready -> Active -> (run all tasks) Complete/Failed."""
    js = (getattr(store, "account", None) or {}).get("jobs")
    if not js or _JOBS_BUSY[0]:
        return
    pend = sorted((j for j in js.values() if j["status"] in ("Ready", "Active")), key=lambda j: (-j["priority"], j["created"]))
    if not pend:
        return
    _JOBS_BUSY[0] = True
    try:
        for j in pend:
            if j["status"] == "Ready":
                j["status"], j["started"] = "Active", time.time()
            elif j["status"] == "Active":
                _job_run(store, j)
    finally:
        _JOBS_BUSY[0] = False
    store.persist()


def _task_err(resp: S3Response):
    m = re.search(rb"<Code>([^<]+)</Code>", resp.body or b"")
    msg = re.search(rb"<Message>([^<]*)</Message>", resp.body or b"")
    return (m.group(1).decode() if m else "InternalError"), (msg.group(1).decode() if msg else "")


def _job_run(store: ObjectStore, j: dict) -> None:
    t0 = time.time()
    results, ok, fail = [], 0, 0
    op_el = _s3c_root(f"<Operation>{j['operation_xml']}</Operation>".encode())
    cfg = _child(op_el, j["op"])
    lam_cache: dict = {}
    for b, k, v in j.get("tasks") or []:
        try:
            res = _job_task(store, j, cfg, b, k, v, lam_cache)
        except Exception as e:    # a task bug must fail that task, never the loop
            res = ("failed", "InternalError", 500, str(e))
        results.append((b, k, v) + res)
        if res[0] == "succeeded":
            ok += 1
        else:
            fail += 1
    total = ok + fail
    j["progress"] = {"total": total, "ok": ok, "fail": fail}
    j["active_secs"] = max(0, int(time.time() - j.get("started", t0)))
    j["terminated"] = _now()
    over = total >= 1000 and fail / total > 0.5          # real S3: >50% failures after 1000 tasks fails the job
    j["status"] = "Failed" if over else "Complete"
    if over:
        j["failures"] = [("JobFailureThresholdExceeded", "More than 50% of the tasks failed.")]
    j.pop("tasks", None)
    _job_report(store, j, results)


def _job_report(store, j, results) -> None:
    rep = _s3c_root(f"<Report>{j['report_xml']}</Report>".encode())
    if _child_text(rep, "Enabled").lower() != "true":
        return
    rb, _ = _arn_bucket(_child_text(rep, "Bucket"))
    if not rb or not store.bucket_exists(rb):
        j["failures"].append(("ReportError", "The report bucket no longer exists."))
        return
    pre = _child_text(rep, "Prefix").strip("/")
    base = (pre + "/" if pre else "") + f"job-{j['id']}/"
    rows = [r for r in results if _child_text(rep, "ReportScope") == "AllTasks" or r[3] != "succeeded"]
    sio = io.StringIO()
    w = csv.writer(sio, quoting=csv.QUOTE_ALL, lineterminator="\n")
    for b, k, v, st, code, http, msg in rows:
        w.writerow([b, urllib.parse.quote(k), v, st, code, http, msg])
    data = sio.getvalue().encode()
    rkey = f"{base}results/{uuid.uuid4().hex}.csv"
    put_object(store, rb, rkey, data, {"content-type": "text/csv"})
    man = json.dumps({"Format": "Report_CSV_20180820", "ReportCreationDate": _now(), "Results": [
        {"TaskExecutionStatus": "succeeded" if any(r[3] == "succeeded" for r in rows) else "failed", "Bucket": rb, "MD5Checksum": hashlib.md5(data).hexdigest(), "Key": rkey}]}).encode()
    mkey = base + "manifest.json"
    put_object(store, rb, mkey, man, {"content-type": "application/json"})
    j["report_keys"] = [f"s3://{rb}/{mkey}", f"s3://{rb}/{rkey}"]


def _job_task(store, j, cfg, bucket, key, vid, lam_cache):
    """Run ONE task -> (status, code, http, message)."""
    op = j["op"]
    if not store.bucket_exists(bucket):
        return ("failed", "NoSuchBucket", 404, f"Bucket {bucket} does not exist.")
    vq = {"versionId": vid} if vid else {}
    path = f"/{bucket}/{key}"
    if not _find_version(_ensure_object_entry(store, bucket, key, create=False), vid or None):
        return ("failed", "NoSuchKey", 404, "The specified key does not exist.")

    def fin(resp):
        if resp.status < 300:
            return ("succeeded", "200", resp.status, "Successful")
        code, msg = _task_err(resp)
        return ("failed", code, resp.status, msg)

    if op == "S3PutObjectTagging":
        tags = _tags_of(_child(cfg, "TagSet"))
        xml = "<Tagging><TagSet>" + "".join(f"<Tag><Key>{_xml_escape(k)}</Key><Value>{_xml_escape(v)}</Value></Tag>" for k, v in tags) + "</TagSet></Tagging>"
        return fin(_dispatch_inner(store, "PUT", path, {"tagging": "", **vq}, {}, xml.encode()))
    if op == "S3DeleteObjectTagging":
        return fin(_dispatch_inner(store, "DELETE", path, {"tagging": "", **vq}, {}, b""))
    if op == "S3PutObjectLegalHold":
        st = _child_text(_child(cfg, "LegalHold"), "Status")
        return fin(_dispatch_inner(store, "PUT", path, {"legal-hold": "", **vq}, {}, f"<LegalHold><Status>{st}</Status></LegalHold>".encode()))
    if op == "S3PutObjectRetention":
        r = _child(cfg, "Retention")
        h = {"x-amz-bypass-governance-retention": "true"} if _child_text(cfg, "BypassGovernanceRetention").lower() == "true" else {}
        return fin(_dispatch_inner(store, "PUT", path, {"retention": "", **vq}, h,
                                   f"<Retention><Mode>{_child_text(r, 'Mode')}</Mode><RetainUntilDate>{_child_text(r, 'RetainUntilDate')}</RetainUntilDate></Retention>".encode()))
    if op == "S3PutObjectAcl":
        pol = _child(cfg, "AccessControlPolicy")
        canned = _child_text(pol, "CannedAccessControlList")
        if canned:
            return fin(_dispatch_inner(store, "PUT", path, {"acl": "", **vq}, {"x-amz-acl": canned}, b""))
        acl = _child(pol, "AccessControlList")
        grants = ""
        for g in _children(_child(acl, "Grants"), "member"):
            gr = _child(g, "Grantee")
            t, ident = _child_text(gr, "TypeIdentifier"), _child_text(gr, "Identifier")
            if t == "id":
                gx = f'<Grantee xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:type="CanonicalUser"><ID>{_xml_escape(ident)}</ID><DisplayName>{_xml_escape(_child_text(gr, "DisplayName"))}</DisplayName></Grantee>'
            elif t == "uri":
                gx = f'<Grantee xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:type="Group"><URI>{_xml_escape(ident)}</URI></Grantee>'
            else:
                gx = f'<Grantee xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:type="AmazonCustomerByEmail"><EmailAddress>{_xml_escape(ident)}</EmailAddress></Grantee>'
            grants += f"<Grant>{gx}<Permission>{_child_text(g, 'Permission')}</Permission></Grant>"
        owner = _child(acl, "Owner")
        oid = _child_text(owner, "ID") or _ACCOUNT_ID
        body = f"<AccessControlPolicy><Owner><ID>{_xml_escape(oid)}</ID></Owner><AccessControlList>{grants}</AccessControlList></AccessControlPolicy>"
        return fin(_dispatch_inner(store, "PUT", path, {"acl": "", **vq}, {}, body.encode()))
    if op == "S3InitiateRestoreObject":
        obj = _find_version(_ensure_object_entry(store, bucket, key, create=False), vid or None)
        if obj.get("storage_class") not in ("GLACIER", "DEEP_ARCHIVE", "GLACIER_IR"):
            return ("failed", "InvalidObjectState", 403, "Restore is only valid for objects in GLACIER, GLACIER_IR or DEEP_ARCHIVE.")
        days = int(_child_text(cfg, "ExpirationInDays") or 1)
        obj["restore"] = {"expiry": (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%a, %d %b %Y %H:%M:%S GMT"),
                          "tier": _child_text(cfg, "GlacierJobTier") or "STANDARD"}
        return ("succeeded", "202", 202, "Successful")
    if op == "S3ReplicateObject":
        rules = [r for r in _replication_rules(store, bucket) if r["status"] == "Enabled" and key.startswith(r.get("prefix") or "")
                 and r["destination"] and store.bucket_exists(r["destination"])]
        if not rules:
            return ("failed", "ReplicationConfigurationNotFoundError", 404, "The bucket has no enabled replication rule covering this key with an existing destination.")
        _replicate(store, bucket, key, _ensure_object_entry(store, bucket, key, create=False))
        return ("succeeded", "200", 200, "Successful")
    if op == "S3PutObjectCopy":
        tb, _ = _arn_bucket(_child_text(cfg, "TargetResource"))
        if not store.bucket_exists(tb):
            return ("failed", "NoSuchBucket", 404, f"Target bucket {tb} does not exist.")
        h = {"x-amz-copy-source": f"/{bucket}/{urllib.parse.quote(key)}" + (f"?versionId={vid}" if vid else "")}
        sc = _child_text(cfg, "StorageClass")
        if sc:
            h["x-amz-storage-class"] = sc
        acl = _child_text(cfg, "CannedAccessControlList")
        if acl:
            h["x-amz-acl"] = acl
        nm = _child(cfg, "NewObjectMetadata")
        if nm is not None and _child_text(cfg, "MetadataDirective") != "COPY":
            h["x-amz-metadata-directive"] = "REPLACE"
            if _child_text(nm, "ContentType"):
                h["content-type"] = _child_text(nm, "ContentType")
            for e in list(_child(nm, "UserMetadata") or []):
                h[f"x-amz-meta-{_child_text(e, 'key')}"] = _child_text(e, "value")
        nt = _tags_of(_child(cfg, "NewObjectTagging"))
        if nt:
            h["x-amz-tagging-directive"] = "REPLACE"
            h["x-amz-tagging"] = urllib.parse.urlencode(nt)
        for src, dst in (("ObjectLockMode", "x-amz-object-lock-mode"), ("ObjectLockRetainUntilDate", "x-amz-object-lock-retain-until-date"),
                         ("ObjectLockLegalHoldStatus", "x-amz-object-lock-legal-hold")):
            if _child_text(cfg, src):
                h[dst] = _child_text(cfg, src)
        if h.get("x-amz-object-lock-legal-hold"):
            h["x-amz-object-lock-legal-hold-status"] = h.pop("x-amz-object-lock-legal-hold")
        return fin(_dispatch_inner(store, "PUT", f"/{tb}/{_child_text(cfg, 'TargetKeyPrefix')}{key}", {}, h, b""))
    if op == "LambdaInvoke":
        lam = getattr(store, "lam_store", None)
        if lam is None:
            return ("failed", "InternalError", 500, "No Lambda backend is attached to this store.")
        try:
            from core import lambda_core as _lam
        except ImportError:  # pragma: no cover - flat vendoring
            import lambda_core as _lam  # type: ignore
        arn = _child_text(cfg, "FunctionArn")
        ver = _child_text(cfg, "InvocationSchemaVersion") or "1.0"
        ua = {_child_text(e, "key"): _child_text(e, "value") for e in list(_child(cfg, "UserArguments") or [])}
        tid = uuid.uuid4().hex
        task = {"taskId": tid, "s3Key": key, "s3VersionId": vid or None, "s3BucketArn": f"arn:aws:s3:::{bucket}"}
        if ver == "2.0":
            task["s3Bucket"] = bucket
        event = {"invocationSchemaVersion": ver, "invocationId": uuid.uuid4().hex, "job": {"id": j["id"], **({"userArguments": ua} if ver == "2.0" else {})}, "tasks": [task]}
        out = _lam._invoke(lam, _lam._norm_name(arn), json.dumps(event).encode())
        if out.status == 404:
            return ("failed", "InternalError", 500, f"Lambda function {arn} does not exist.")
        try:
            res = json.loads(out.body or b"null")
        except ValueError:
            res = None
        if out.status != 200 or (out.headers or {}).get("X-Amz-Function-Error") or not isinstance(res, dict):
            return ("failed", "PermanentFailure", 500, (res or {}).get("errorMessage", "The Lambda invocation failed.") if isinstance(res, dict) else "The Lambda invocation failed.")
        r0 = next((r for r in res.get("results") or [] if r.get("taskId") == tid), None)
        if r0 is None:
            return ("failed", "PermanentFailure", 500, "The Lambda response has no result for the task.")
        code = r0.get("resultCode")
        if code == "Succeeded":
            return ("succeeded", "200", 200, str(r0.get("resultString") or "Successful"))
        return ("failed", code or "PermanentFailure", 500, str(r0.get("resultString") or ""))
    return ("failed", "NotImplemented", 501, f"{op} is not implemented.")


def dispatch(store: ObjectStore, method: str, path: str,
             query: dict | None = None, headers: dict | None = None,
             body: bytes = b"") -> S3Response:
    """Public entry: one request, then a Batch Operations tick (jobs advance a stage per request)."""
    raw0 = (path or "/").lstrip("/")
    lh = {str(k).lower(): v for k, v in (headers or {}).items()}
    if raw0.startswith("__cloudtrail__"):      # minimal CloudTrail (JSON 1.1), routed from AwsWireRouter
        return _ext().cloudtrail_dispatch(store, lh.get("x-amz-target", ""), body)
    if lh.get("host"):                          # <bucket>.s3-accelerate.amazonaws.com
        new_raw, bad = _ext().accelerate_host(store, raw0, lh)
        if bad is not None:
            return bad
        if new_raw != raw0:
            path = "/" + new_raw
    resp = _dispatch_inner(store, method, path, query, headers, body)
    _jobs_tick(store)
    _ext().on_request(store, (method or "GET").upper(), path or "/", query or {}, lh, body, resp)
    return resp


def _dispatch_inner(store: ObjectStore, method: str, path: str,
                    query: dict | None = None, headers: dict | None = None,
                    body: bytes = b"") -> S3Response:
    query = query or {}
    headers = headers or {}
    lheaders = {str(k).lower(): v for k, v in headers.items()}
    raw = (path or "/").lstrip("/")
    bucket, _, key = raw.partition("/")
    bucket = urllib.parse.unquote(bucket)
    method = (method or "GET").upper()
    if bucket == "__s3tables__":  # Amazon S3 Tables REST (SigV4 signing name s3tables), routed by AwsWireRouter
        return _load_core("s3_tables_core").dispatch(store, method, "/" + raw.partition("/")[2], query, headers, body)
    if bucket == "v20180820":     # S3 Control (access points; every other control op -> NotImplemented)
        return _s3control(store, method, raw, query, lheaders, body)
    guard = _grant_cred_guard(store, method, raw, query, lheaders)
    if guard is not None:
        return guard
    olap, olap_name, olap_key = _olap_lookup(store, raw)
    if olap is not None:
        return _olap_dispatch(store, olap, olap_name, method, olap_key, query, headers, lheaders)
    mrap, mrap_key = _mrap_lookup(store, raw)
    if mrap is not None:
        return _mrap_dispatch(store, mrap, method, mrap_key, query, headers, body)
    bucket = _resolve_access_point(store, bucket)
    if method == "OPTIONS":
        return _cors_preflight(store, bucket, lheaders)
    if not bucket:
        # Service-level root: GET / lists all buckets; others are genuinely invalid.
        if method == "GET":
            return list_directory_buckets(store, query) if _is_express_control(lheaders) else list_all_buckets(store)
        return _error_xml("InvalidRequest", "Missing bucket.", "/", 400)
    if "session" in query and not key and method == "GET":
        return _create_session(store, bucket, lheaders)
    if is_directory_bucket(store, bucket):
        bad = _directory_guard(store, method, bucket, key, query, lheaders)
        if bad is not None:
            return bad
        if method in ("PUT", "POST") and key:
            headers = {**headers, "x-amz-storage-class": "EXPRESS_ONEZONE"}
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
