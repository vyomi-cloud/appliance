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
import hashlib
import json
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
    """Strip AWS SDK v2 ``aws-chunked`` framing (see routes/aws_s3.py for the
    full rationale — modern SDKs stream PutObject with chunk-signature headers
    that would corrupt the stored object if kept)."""
    ce = (headers.get("content-encoding") or "").lower()
    sha = headers.get("x-amz-content-sha256", "") or ""
    if "aws-chunked" not in ce and not sha.startswith("STREAMING"):
        return body
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
            break
        out += body[i:i + size]
        i += size
        if body[i:i + 2] == b"\r\n":
            i += 2
    return bytes(out)


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
        rules.append({"prefix": prefix or "", "expiration_days": exp_days, "expiration_date": exp_date})
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


def _apply_lifecycle(store: ObjectStore, bucket: str) -> None:
    """Lazily evaluated on every read path (list/get/head) — Date-based Expiration rules
    fire deterministically (testable without waiting real days); Days-based rules use the
    real elapsed wall-clock, matching S3's own (non-accelerated) semantics."""
    rules = _lifecycle_rules(store, bucket)
    if not rules:
        return
    bucket_objects = store.bucket_objects(bucket)
    vstatus = store.versioning_status(bucket)
    expired_any = False
    for key in list(bucket_objects.keys()):
        entry = bucket_objects.get(key)
        if not isinstance(entry, dict) or not entry.get("versions"):
            continue
        cur = entry["versions"][0]
        if cur.get("is_delete_marker"):
            continue
        if any(_rule_expires(rule, key, cur.get("last_modified", _now())) for rule in rules):
            expired_any = True
            if vstatus in ("Enabled", "Suspended"):
                _insert_simple_delete_marker(store, bucket, key)
                _emit(store, bucket, key, "s3:LifecycleExpiration:DeleteMarkerCreated", None, "Lifecycle")
            else:
                bucket_objects.pop(key, None)
                store.mirror_delete(bucket, key)
                _emit(store, bucket, key, "s3:LifecycleExpiration:Delete", None, "Lifecycle")
    if expired_any:
        store.persist()


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
        rules.append({
            "id": _child_text(r, "ID"),
            "status": _child_text(r, "Status", "Disabled"),
            "prefix": prefix,
            "destination": dest_arn.rsplit(":", 1)[-1] if dest_arn else "",
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


# ── the 5 operations (faithful ports of the handler bodies) ───────────────
def put_object(store: ObjectStore, bucket: str, key: str, body: bytes, headers: dict) -> S3Response:
    headers = {k.lower(): v for k, v in (headers or {}).items()}
    if not store.bucket_exists(bucket):
        return _error_xml("NoSuchBucket", "The specified bucket does not exist.", f"/{bucket}", 404)
    data = _decode_aws_chunked(body or b"", headers)
    content_type = headers.get("content-type", "application/octet-stream")
    storage_class = headers.get("x-amz-storage-class", "STANDARD")
    user_meta = {h[11:]: v for h, v in headers.items() if h.startswith("x-amz-meta-")}
    tags = dict(urllib.parse.parse_qsl(headers.get("x-amz-tagging", ""), keep_blank_values=True))
    vstatus = store.versioning_status(bucket)
    vid = _new_version_id(store, bucket) if vstatus == "Enabled" else "null"
    version = _make_version_record(data=data, content_type=content_type,
                                   storage_class=storage_class, metadata=user_meta, tags=tags,
                                   version_id=vid, delete_marker=False)
    replace = "__overwrite__" if vstatus == "Disabled" else ("null" if vstatus == "Suspended" else None)
    entry = _write_object_version(store, bucket, key, version, replace_version_id=replace)
    _replicate(store, bucket, key, entry)
    _emit(store, bucket, key, "s3:ObjectCreated:Put", entry, "PutObject")
    extra = {"ETag": version["etag"], "x-amz-version-id": entry.get("current_version_id", vid)}
    extra.update(_sse_headers(store, bucket))
    extra.update(_cors_response_headers(store, bucket, headers, "PUT"))
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
    if not store.bucket_exists(bucket):
        return _error_xml("NoSuchBucket", "The specified bucket does not exist.", f"/{bucket}/{key}", 404)
    _apply_lifecycle(store, bucket)
    entry = _ensure_object_entry(store, bucket, key, create=False)
    obj = _find_version(entry, (query or {}).get("versionId"))
    if obj and obj.get("is_delete_marker"):
        if (query or {}).get("versionId"):
            return _delete_marker_response(f"/{bucket}/{key}", obj.get("last_modified", _now()))
        return _error_xml("NoSuchKey", "The specified key does not exist.", f"/{bucket}/{key}", 404)
    if not obj:
        return _error_xml("NoSuchKey", "The specified key does not exist.", f"/{bucket}/{key}", 404)
    h = {"Content-Length": str(obj["size"]), "Content-Type": obj["content_type"],
         "ETag": obj["etag"], "Last-Modified": _iso_to_http_date(obj["last_modified"]),
         "x-amz-storage-class": obj.get("storage_class", "STANDARD"),
         "x-amz-version-id": obj.get("version_id", "null")}
    if obj.get("replication_status"):
        h["x-amz-replication-status"] = obj["replication_status"]
    for k, v in obj.get("metadata", {}).items():
        h[f"x-amz-meta-{k}"] = v
    h.update(_sse_headers(store, bucket))
    h.update(_cors_response_headers(store, bucket, headers, "HEAD"))
    return _empty_response(200, h)


def get_object(store: ObjectStore, bucket: str, key: str, query: dict, headers: dict) -> S3Response:
    headers = {k.lower(): v for k, v in (headers or {}).items()}
    query = query or {}
    if not store.bucket_exists(bucket):
        return _error_xml("NoSuchBucket", "The specified bucket does not exist.", f"/{bucket}", 404)
    _apply_lifecycle(store, bucket)
    entry = _ensure_object_entry(store, bucket, key, create=False)
    obj = _find_version(entry, query.get("versionId"))
    if obj and obj.get("is_delete_marker"):
        if query.get("versionId"):
            return _delete_marker_response(f"/{bucket}/{key}", obj.get("last_modified", _now()))
        return _error_xml("NoSuchKey", "The specified key does not exist.", f"/{bucket}/{key}", 404)
    if not obj:
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
    for k, v in obj.get("metadata", {}).items():
        h[f"x-amz-meta-{k}"] = v
    h.update(_sse_headers(store, bucket))
    h.update(_cors_response_headers(store, bucket, headers, "GET"))
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
        return _done(store, _empty_response(204, {"x-amz-version-id": vid}))
    status = store.versioning_status(bucket)
    if status == "Disabled":
        store.bucket_objects(bucket).pop(key, None)
        store.mirror_delete(bucket, key)
        _emit(store, bucket, key, "s3:ObjectRemoved:Delete", None, "DeleteObject")
        return _done(store, _empty_response(204))
    entry = _insert_simple_delete_marker(store, bucket, key)
    vid = entry.get("current_version_id", "null") if isinstance(entry, dict) else "null"
    _emit(store, bucket, key, "s3:ObjectRemoved:DeleteMarkerCreated", entry, "DeleteObject")
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
    return _xml_response("".join(parts))


def list_objects_v1(store: ObjectStore, bucket: str, query: dict) -> S3Response:
    """GET /{bucket} without list-type=2 — ListObjects (V1, marker paging)."""
    query = query or {}
    if not store.bucket_exists(bucket):
        return _error_xml("NoSuchBucket", "The specified bucket does not exist.", f"/{bucket}", 404)
    _apply_lifecycle(store, bucket)
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
                try:
                    store.emit_event(bucket, "", "s3:TestEvent", None, "PutBucketNotificationConfiguration")
                except Exception:
                    pass
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
                return _xml_response(f'<?xml version="1.0" encoding="UTF-8"?><ObjectLockConfiguration {_NS}><ObjectLockEnabled>Enabled</ObjectLockEnabled></ObjectLockConfiguration>')
            if method == "PUT":
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
            return copy_object(store, bucket, key, headers)
        return put_object(store, bucket, key, body, headers)
    if method == "GET":
        if query.get("uploadId"):
            return list_parts(store, bucket, key, query)
        return get_object(store, bucket, key, query, headers)
    if method == "HEAD":
        return head_object(store, bucket, key, query, headers)
    if method == "DELETE":
        if query.get("uploadId"):
            return abort_multipart_upload(store, bucket, key, query)
        return delete_object(store, bucket, key, query, lheaders)
    return _error_xml("MethodNotAllowed", "The specified method is not allowed against this resource.", f"/{bucket}/{key}", 405)
