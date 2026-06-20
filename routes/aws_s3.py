"""AWS S3 REST API — bucket and object CRUD, versioning, multipart upload,
notifications, and the root AWS query-protocol dispatcher.

Extracted from server.py — this is the largest route module.  Contains:
- All S3 helper functions (_s3_*, _xml_response, _error_xml, etc.)
- S3 wire-protocol REST API routes (GET/PUT/DELETE /{bucket}/{key:path})
- Root POST / dispatcher for AWS SDK/CLI query-protocol requests
- ListObjectsV1/V2 helpers
- Tagging XML helpers

CRITICAL: This module's catch-all routes (/{bucket}, /{bucket}/{key:path})
MUST be registered LAST on the FastAPI app so they don't shadow other routes.
"""
from __future__ import annotations

import copy
import hashlib
import io
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from xml.etree import ElementTree as ET

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

from core import app_context as ctx

# ---------------------------------------------------------------------------
# Lazy back-reference to server.py
# ---------------------------------------------------------------------------


def _srv():
    import server as _s
    return _s


# ---------------------------------------------------------------------------
# Aliases for shared utilities
# ---------------------------------------------------------------------------

_now = ctx.now
_id = ctx.id_gen
_record_usage = ctx.record_usage

S3_NS = ctx.S3_NS
AWS_ACCOUNT_ID = ctx.AWS_ACCOUNT_ID

# ---------------------------------------------------------------------------
# Reserved bucket names — path prefixes the S3 catch-all MUST NOT match.
# ---------------------------------------------------------------------------
# The S3 wire protocol uses /{bucket}[/{key:path}] at the URL root. That
# pattern also matches every appliance-internal API path like
# /api/aws/ec2/... or /api/gcp/compute/... when no explicit handler is
# registered. Without this guard the catch-all eats those requests and
# returns NoSuchBucket XML — which makes ~50 conformance tests fail
# with a misleading error, AND breaks any future API path that hasn't
# been registered yet. Reject these at the top of every catch-all
# handler so FastAPI's standard 404 wins instead. Users can't create
# buckets with these names — a tiny limitation worth the observability.
_RESERVED_BUCKET_NAMES: frozenset[str] = frozenset({
    "api",          # all /api/* paths
    "static",       # static assets
    "assets",       # /assets/*
    "console",      # /console/aws etc.
    "clouds",       # SPA entry
    "ws",           # websocket routes
    "healthz",      # health endpoint
    "metrics",      # prometheus etc.
    "docs", "openapi.json", "redoc",  # FastAPI auto-docs
})


def _is_reserved_bucket(bucket: str) -> bool:
    """True when the path's first segment is a reserved name (i.e. NOT
    a user-created bucket). Catch-all handlers should bail with a
    FastAPI HTTPException(404) so the next router in the chain — or
    the default 404 handler — gets a chance to respond."""
    return bucket in _RESERVED_BUCKET_NAMES

# ---------------------------------------------------------------------------
# State access
# ---------------------------------------------------------------------------

buckets = ctx.buckets
objects = ctx.objects
multiparts = ctx.multiparts


# ---------------------------------------------------------------------------
# Small utility functions
# ---------------------------------------------------------------------------


def _iso_to_http_date(iso: str) -> str:
    """Convert ISO-8601 timestamp to HTTP date format."""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%a, %d %b %Y %H:%M:%S GMT")
    except Exception:
        return datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")


def _etag(data: bytes) -> str:
    return f'"{hashlib.md5(data).hexdigest()}"'


def _decode_aws_chunked(body: bytes, headers) -> bytes:
    """Strip AWS SDK v2 ``aws-chunked`` framing from a request body.

    Modern AWS SDKs (Java v2, etc.) stream PutObject/UploadPart with
    ``Content-Encoding: aws-chunked`` and ``x-amz-content-sha256:
    STREAMING-...``: the body is wrapped in ``<hex-size>;chunk-signature=...``
    chunk headers with optional trailing checksum lines, NOT the raw object
    bytes. Starlette's ``request.body()`` returns this framed payload as-is, so
    storing it corrupts the object — GET then returns the framed bytes and the
    SDK's flexible-checksum validation fails ("Data read has a different
    checksum than expected"). Decode it back to the real bytes; non-chunked
    bodies pass through untouched."""
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
        if size == 0:          # last chunk; trailers (if any) follow
            break
        out += body[i:i + size]
        i += size
        if body[i:i + 2] == b"\r\n":   # CRLF separating chunk data
            i += 2
    return bytes(out)


def _fmt_size(n: int) -> str:
    orig = n
    for unit in ["B", "KB", "MB", "GB"]:
        if orig < 1024:
            return f"{orig:.1f} {unit}"
        orig /= 1024
    return f"{orig:.1f} TB"


def _req_id() -> str:
    return uuid.uuid4().hex.upper()[:16]


# ---------------------------------------------------------------------------
# XML response helpers
# ---------------------------------------------------------------------------


def _xml_response(content: str, status: int = 200, extra_headers: dict = None) -> Response:
    headers = {
        "x-amz-request-id": _req_id(),
        "x-amz-id-2": uuid.uuid4().hex,
    }
    if extra_headers:
        headers.update(extra_headers)
    return Response(
        content=content,
        status_code=status,
        media_type="application/xml",
        headers=headers,
    )


def _empty_response(status: int = 204, extra_headers: dict = None) -> Response:
    headers = {
        "x-amz-request-id": _req_id(),
        "x-amz-id-2": uuid.uuid4().hex,
    }
    if extra_headers:
        headers.update(extra_headers)
    return Response(status_code=status, headers=headers)


def _error_xml(code: str, message: str, resource: str = "/", status: int = 400) -> Response:
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Error>"
        f"<Code>{code}</Code>"
        f"<Message>{message}</Message>"
        f"<Resource>{resource}</Resource>"
        f"<RequestId>{_req_id()}</RequestId>"
        "</Error>"
    )
    return _xml_response(xml, status=status)


def _delete_marker_response(resource: str, last_modified: str, status: int = 405) -> Response:
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Error>"
        "<Code>MethodNotAllowed</Code>"
        "<Message>The specified version is a delete marker.</Message>"
        f"<Resource>{resource}</Resource>"
        f"<RequestId>{_req_id()}</RequestId>"
        "</Error>"
    )
    return _xml_response(
        xml,
        status=status,
        extra_headers={
            "x-amz-delete-marker": "true",
            "Last-Modified": _iso_to_http_date(last_modified),
        },
    )


# ---------------------------------------------------------------------------
# Bucket helpers
# ---------------------------------------------------------------------------


def _bucket_exists(name: str) -> bool:
    return name in buckets


def _validate_bucket_name(name: str) -> Optional[Response]:
    if len(name) < 3 or len(name) > 63:
        return _error_xml("InvalidBucketName", "Bucket name must be between 3 and 63 characters.", f"/{name}", 400)
    if not re.match(r'^[a-z0-9][a-z0-9\-.]*[a-z0-9]$', name) and len(name) > 1:
        return _error_xml("InvalidBucketName", "Bucket name can contain only lowercase letters, numbers, hyphens, and dots.", f"/{name}", 400)
    return None


# ---------------------------------------------------------------------------
# Versioning helpers
# ---------------------------------------------------------------------------


def _s3_bucket_versioning_status(bucket: str) -> str:
    status = buckets.get(bucket, {}).get("versioning", "Disabled")
    return status if status in {"Enabled", "Suspended", "Disabled"} else "Disabled"


def _s3_versioning_enabled(bucket: str) -> bool:
    return _s3_bucket_versioning_status(bucket) in {"Enabled", "Suspended"}


def _s3_new_version_id(bucket: str) -> str:
    return "null" if _s3_bucket_versioning_status(bucket) == "Suspended" else uuid.uuid4().hex


# ---------------------------------------------------------------------------
# Object entry / version helpers
# ---------------------------------------------------------------------------


def _s3_object_version_from_entry(entry: dict) -> dict:
    version = {
        "version_id": str(entry.get("version_id") or entry.get("current_version_id") or "null"),
        "is_delete_marker": bool(entry.get("is_delete_marker", False)),
        "data": entry.get("data", b"") if not entry.get("is_delete_marker") else b"",
        "size": int(entry.get("size", 0) or 0),
        "content_type": entry.get("content_type", "application/octet-stream"),
        "last_modified": entry.get("last_modified", _now()),
        "etag": entry.get("etag", ""),
        "storage_class": entry.get("storage_class", "STANDARD"),
        "metadata": copy.deepcopy(entry.get("metadata", {})),
        "tags": copy.deepcopy(entry.get("tags", {})),
    }
    version["is_latest"] = bool(entry.get("is_latest", False))
    return version


def _s3_ensure_object_entry(bucket: str, key: str, create: bool = False) -> dict | None:
    bucket_objects = objects.setdefault(bucket, {})
    entry = bucket_objects.get(key)
    if entry is None:
        if not create:
            return None
        entry = {"versions": []}
        bucket_objects[key] = entry
    if not isinstance(entry, dict):
        if not create:
            return None
        entry = {"versions": []}
        bucket_objects[key] = entry
    if "versions" not in entry or not isinstance(entry.get("versions"), list):
        entry["versions"] = [_s3_object_version_from_entry(entry)]
    entry["versions"] = [copy.deepcopy(v) for v in entry.get("versions", []) if isinstance(v, dict)]
    if entry["versions"]:
        _s3_refresh_object_entry(entry)
    return entry


def _s3_refresh_object_entry(entry: dict) -> None:
    versions = entry.get("versions", [])
    for idx, version in enumerate(versions):
        version["is_latest"] = idx == 0
    if not versions:
        entry["current_version_id"] = ""
        entry["is_delete_marker"] = False
        entry["data"] = b""
        entry["size"] = 0
        entry["content_type"] = "application/octet-stream"
        entry["last_modified"] = _now()
        entry["etag"] = ""
        entry["storage_class"] = "STANDARD"
        entry["metadata"] = {}
        entry["tags"] = {}
        return
    current = versions[0]
    entry["current_version_id"] = current.get("version_id", "null")
    entry["version_id"] = current.get("version_id", "null")
    entry["is_delete_marker"] = bool(current.get("is_delete_marker", False))
    entry["data"] = current.get("data", b"") if not current.get("is_delete_marker") else b""
    entry["size"] = int(current.get("size", 0) or 0)
    entry["content_type"] = current.get("content_type", "application/octet-stream")
    entry["last_modified"] = current.get("last_modified", _now())
    entry["etag"] = current.get("etag", "")
    entry["storage_class"] = current.get("storage_class", "STANDARD")
    entry["metadata"] = copy.deepcopy(current.get("metadata", {}))
    entry["tags"] = copy.deepcopy(current.get("tags", {}))


def _s3_make_version_record(
    *,
    data: bytes = b"",
    content_type: str = "application/octet-stream",
    storage_class: str = "STANDARD",
    metadata: dict | None = None,
    tags: dict | None = None,
    version_id: str | None = None,
    delete_marker: bool = False,
    last_modified: str | None = None,
    etag: str | None = None,
) -> dict:
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


def _s3_latest_visible_version(entry: dict | None) -> dict | None:
    if not entry:
        return None
    versions = entry.get("versions", []) if isinstance(entry, dict) else []
    if not versions:
        return None
    latest = versions[0]
    return None if latest.get("is_delete_marker") else latest


def _s3_find_version(entry: dict | None, version_id: str | None) -> dict | None:
    if not entry:
        return None
    versions = entry.get("versions", [])
    if not version_id:
        return versions[0] if versions else None
    for version in versions:
        if str(version.get("version_id")) == str(version_id):
            return version
    return None


def _s3_total_bytes() -> int:
    """Sum of all bucket+object data sizes in the active space."""
    total = 0
    try:
        for bk_objs in (objects or {}).values():
            for ent in (bk_objs or {}).values():
                versions = ent.get("versions") or [] if isinstance(ent, dict) else []
                for v in versions:
                    if isinstance(v, dict) and not v.get("is_delete_marker"):
                        total += int(v.get("size") or len(v.get("data") or b""))
    except Exception:
        pass
    return total


def _enforce_storage_cap(additional_bytes: int) -> None:
    """Raise HTTPException(403) if the active tier's total-storage-bytes cap
    would be exceeded by adding `additional_bytes` more."""
    _srv()._enforce_storage_cap(additional_bytes)


def _enforce_quantity_cap(resource_type: str) -> None:
    """Delegate to server.py for tier quantity enforcement."""
    _srv()._enforce_quantity_cap(resource_type)


def _s3_write_object_version(
    bucket: str,
    key: str,
    version: dict,
    replace_version_id: str | None = None,
    event_name: str | None = None,
    source: str = "",
) -> dict:
    # Tier storage cap
    if not version.get("is_delete_marker"):
        _enforce_storage_cap(int(version.get("size") or len(version.get("data") or b"")))
    entry = _s3_ensure_object_entry(bucket, key, create=True)
    versions = entry.setdefault("versions", [])
    if replace_version_id == "__overwrite__":
        versions = [version]
    elif replace_version_id is not None:
        for idx, existing in enumerate(versions):
            if str(existing.get("version_id")) == str(replace_version_id):
                versions[idx] = version
                break
        else:
            versions.insert(0, version)
    else:
        versions.insert(0, version)
    entry["versions"] = [copy.deepcopy(v) for v in versions]
    _s3_refresh_object_entry(entry)
    # Write-through to MinIO
    try:
        if not version.get("is_delete_marker") and version.get("data") is not None:
            from core import minio_mirror as _mm
            _mm.put_object(
                bucket, key, version["data"],
                content_type=version.get("content_type", "application/octet-stream"),
                metadata=version.get("metadata"),
            )
    except Exception:
        pass
    if event_name:
        _s3_emit_event(bucket, key, event_name, entry.get("versions", [version])[0] if entry.get("versions") else version, source=source)
    return entry


def _s3_insert_simple_delete_marker(bucket: str, key: str, source: str = "") -> dict:
    entry = _s3_ensure_object_entry(bucket, key, create=True)
    status = _s3_bucket_versioning_status(bucket)
    if status == "Disabled":
        objects.setdefault(bucket, {}).pop(key, None)
        _s3_emit_event(bucket, key, "s3:ObjectRemoved:Delete", None, source=source)
        return {}

    versions = entry.setdefault("versions", [])
    if status == "Suspended" and versions and str(versions[0].get("version_id", "null")) == "null":
        versions.pop(0)
    delete_marker = _s3_make_version_record(
        delete_marker=True,
        version_id=_s3_new_version_id(bucket) if status == "Enabled" else "null",
    )
    event_name = "s3:ObjectRemoved:DeleteMarkerCreated" if status in {"Enabled", "Suspended"} else "s3:ObjectRemoved:Delete"
    return _s3_write_object_version(bucket, key, delete_marker, event_name=event_name, source=source)


def _s3_delete_version(bucket: str, key: str, version_id: str) -> bool:
    entry = _s3_ensure_object_entry(bucket, key, create=False)
    if not entry:
        return False
    versions = entry.get("versions", [])
    deleted_version = next((copy.deepcopy(v) for v in versions if str(v.get("version_id")) == str(version_id)), None)
    next_versions = [v for v in versions if str(v.get("version_id")) != str(version_id)]
    if len(next_versions) == len(versions):
        return False
    if next_versions:
        entry["versions"] = next_versions
        _s3_refresh_object_entry(entry)
    else:
        objects.get(bucket, {}).pop(key, None)
    _s3_emit_event(bucket, key, "s3:ObjectRemoved:Delete", deleted_version, source="DeleteObject")
    return True


def _s3_list_versions(bucket: str, prefix: str = "") -> list[tuple[str, dict]]:
    result: list[tuple[str, dict]] = []
    for key in sorted(objects.get(bucket, {})):
        if prefix and not key.startswith(prefix):
            continue
        entry = _s3_ensure_object_entry(bucket, key, create=False)
        if not entry:
            continue
        versions = sorted(
            entry.get("versions", []),
            key=lambda v: (
                str(v.get("last_modified", "")),
                str(v.get("version_id", "")),
            ),
            reverse=True,
        )
        for version in versions:
            result.append((key, version))
    return result


# ---------------------------------------------------------------------------
# Notification helpers
# ---------------------------------------------------------------------------


def _s3_default_notifications() -> dict:
    return {
        "eventBridgeEnabled": False,
        "topicConfigurations": [],
        "queueConfigurations": [],
        "cloudFunctionConfigurations": [],
        "deliveries": [],
        "updatedAt": _now(),
    }


def _s3_bucket_notifications(bucket: str, create: bool = True) -> dict | None:
    b = buckets.get(bucket)
    if not b:
        return None
    notifications = b.get("notifications")
    if not isinstance(notifications, dict):
        if not create:
            return None
        notifications = _s3_default_notifications()
        b["notifications"] = notifications
    notifications.setdefault("eventBridgeEnabled", False)
    notifications.setdefault("topicConfigurations", [])
    notifications.setdefault("queueConfigurations", [])
    notifications.setdefault("cloudFunctionConfigurations", [])
    notifications.setdefault("deliveries", [])
    notifications.setdefault("updatedAt", _now())
    return notifications


def _s3_xml_name(elem: ET.Element | None) -> str:
    if elem is None:
        return ""
    return (elem.tag or "").rsplit("}", 1)[-1]


def _s3_xml_find_child(elem: ET.Element, name: str) -> ET.Element | None:
    for child in list(elem):
        if _s3_xml_name(child) == name:
            return child
    return None


def _s3_xml_find_children(elem: ET.Element, name: str) -> list[ET.Element]:
    return [child for child in list(elem) if _s3_xml_name(child) == name]


def _s3_xml_text(elem: ET.Element | None, name: str, default: str = "") -> str:
    child = _s3_xml_find_child(elem, name) if elem is not None else None
    return (child.text or default).strip() if child is not None else default


def _s3_event_pattern_matches(pattern: str, event_name: str) -> bool:
    escaped = re.escape(pattern).replace(r"\*", ".*")
    return re.fullmatch(escaped, event_name) is not None


def _s3_notification_rule_matches(rule: dict, event_name: str, key: str) -> bool:
    patterns = rule.get("events") or []
    if patterns and not any(_s3_event_pattern_matches(pattern, event_name) for pattern in patterns):
        return False
    prefix = (rule.get("prefix") or "").strip()
    suffix = (rule.get("suffix") or "").strip()
    if prefix and not key.startswith(prefix):
        return False
    if suffix and not key.endswith(suffix):
        return False
    return True


def _s3_build_notification_event(bucket: str, key: str, version: dict | None, event_name: str, source: str) -> dict:
    bucket_meta = buckets.get(bucket, {})
    version_id = (version or {}).get("version_id", "null")
    return {
        "Records": [
            {
                "eventVersion": "2.1",
                "eventSource": "aws:s3",
                "awsRegion": bucket_meta.get("region", "us-east-1"),
                "eventTime": _now(),
                "eventName": event_name.replace("s3:", ""),
                "userIdentity": {"principalId": "AWS:SIMULATOR"},
                "requestParameters": {"sourceIPAddress": "127.0.0.1"},
                "responseElements": {
                    "x-amz-request-id": _req_id(),
                    "x-amz-id-2": uuid.uuid4().hex,
                },
                "s3": {
                    "s3SchemaVersion": "1.0",
                    "configurationId": source or "cloudlearn-s3-notification",
                    "bucket": {
                        "name": bucket,
                        "arn": bucket_meta.get("arn", f"arn:aws:s3:::{bucket}"),
                    },
                    "object": {
                        "key": key,
                        "size": int((version or {}).get("size", 0) or 0),
                        "eTag": (version or {}).get("etag", ""),
                        "versionId": version_id,
                        "sequencer": uuid.uuid4().hex[:16],
                    },
                },
            }
        ]
    }


def _s3_notification_delivery_targets(bucket: str, event_name: str, key: str) -> list[dict]:
    notifications = _s3_bucket_notifications(bucket, create=False)
    if not notifications:
        return []
    deliveries: list[dict] = []
    for rule in notifications.get("topicConfigurations", []):
        if _s3_notification_rule_matches(rule, event_name, key):
            deliveries.append({
                "type": "TopicConfiguration",
                "destination": rule.get("topic", ""),
                "id": rule.get("id", ""),
            })
    for rule in notifications.get("queueConfigurations", []):
        if _s3_notification_rule_matches(rule, event_name, key):
            deliveries.append({
                "type": "QueueConfiguration",
                "destination": rule.get("queue", ""),
                "id": rule.get("id", ""),
            })
    for rule in notifications.get("cloudFunctionConfigurations", []):
        if _s3_notification_rule_matches(rule, event_name, key):
            deliveries.append({
                "type": "CloudFunctionConfiguration",
                "destination": rule.get("cloudFunction", ""),
                "id": rule.get("id", ""),
            })
    if notifications.get("eventBridgeEnabled"):
        deliveries.append({
            "type": "EventBridgeConfiguration",
            "destination": "eventbridge",
            "id": "eventbridge",
        })
    return deliveries


def _s3_notification_record_delivery(
    bucket: str,
    event_name: str,
    key: str,
    version_id: str = "",
    source: str = "",
    payload: dict | None = None,
    test_event: bool = False,
) -> list[dict]:
    notifications = _s3_bucket_notifications(bucket, create=True)
    if not notifications:
        return []
    records = []
    deliveries = _s3_notification_delivery_targets(bucket, event_name, key)
    for target in deliveries:
        record = {
            "id": _id("s3evt"),
            "at": _now(),
            "bucket": bucket,
            "key": key,
            "version_id": version_id or "null",
            "event_name": event_name,
            "source": source,
            "destination_type": target["type"],
            "destination": target["destination"],
            "rule_id": target.get("id", ""),
            "status": "delivered",
            "test_event": test_event,
            "payload": copy.deepcopy(payload or {}),
        }
        if target["type"] == "CloudFunctionConfiguration" and target.get("destination"):
            function = _srv()._lambda_resolve_function(target["destination"])
            if function:
                try:
                    _srv()._lambda_invoke_function(
                        function["function_name"],
                        payload or {},
                        invocation_type="Event",
                        source=source or "s3",
                        source_principal="s3.amazonaws.com",
                        source_arn=f"arn:aws:s3:::{bucket}",
                        source_account=AWS_ACCOUNT_ID,
                    )
                except Exception as exc:
                    record["status"] = "failed"
                    record["error"] = getattr(exc, "detail", None) or str(exc)
            else:
                record["status"] = "failed"
                record["error"] = "Lambda function not found"
        elif target["type"] == "QueueConfiguration" and target.get("destination"):
            queue = _srv()._sqs_queue_from_name_or_url(target["destination"])
            if queue:
                try:
                    _srv()._sqs_enqueue_message(
                        queue,
                        json.dumps(payload or {}, default=str),
                        attributes={"event_name": event_name, "bucket": bucket, "source": source or "s3"},
                        message_attributes={},
                        source=source or "s3",
                    )
                except Exception as exc:
                    record["status"] = "failed"
                    record["error"] = getattr(exc, "detail", None) or str(exc)
            else:
                record["status"] = "failed"
                record["error"] = "SQS queue not found"
        notifications["deliveries"].append(record)
        records.append(record)
    notifications["deliveries"] = notifications["deliveries"][-200:]
    notifications["updatedAt"] = _now()
    return records


def _s3_emit_event(bucket: str, key: str, event_name: str, version: dict | None = None, source: str = "") -> dict:
    payload = _s3_build_notification_event(bucket, key, version, event_name, source)
    _s3_notification_record_delivery(
        bucket=bucket,
        event_name=event_name,
        key=key,
        version_id=(version or {}).get("version_id", "null"),
        source=source,
        payload=payload,
        test_event=event_name == "s3:TestEvent",
    )
    return payload


def _s3_notification_xml_from_config(bucket: str) -> str:
    notifications = _s3_bucket_notifications(bucket, create=True) or _s3_default_notifications()
    root = ET.Element("NotificationConfiguration", xmlns=S3_NS)
    if notifications.get("eventBridgeEnabled"):
        ET.SubElement(root, "EventBridgeConfiguration")

    def add_filter(parent: ET.Element, rule: dict) -> None:
        if not rule.get("prefix") and not rule.get("suffix"):
            return
        filter_el = ET.SubElement(parent, "Filter")
        s3key = ET.SubElement(filter_el, "S3Key")
        if rule.get("prefix"):
            fr = ET.SubElement(s3key, "FilterRule")
            ET.SubElement(fr, "Name").text = "prefix"
            ET.SubElement(fr, "Value").text = rule.get("prefix", "")
        if rule.get("suffix"):
            fr = ET.SubElement(s3key, "FilterRule")
            ET.SubElement(fr, "Name").text = "suffix"
            ET.SubElement(fr, "Value").text = rule.get("suffix", "")

    for rule in notifications.get("topicConfigurations", []):
        item = ET.SubElement(root, "TopicConfiguration")
        if rule.get("id"):
            ET.SubElement(item, "Id").text = rule.get("id", "")
        for event in rule.get("events", []):
            ET.SubElement(item, "Event").text = event
        ET.SubElement(item, "Topic").text = rule.get("topic", "")
        add_filter(item, rule)

    for rule in notifications.get("queueConfigurations", []):
        item = ET.SubElement(root, "QueueConfiguration")
        if rule.get("id"):
            ET.SubElement(item, "Id").text = rule.get("id", "")
        for event in rule.get("events", []):
            ET.SubElement(item, "Event").text = event
        ET.SubElement(item, "Queue").text = rule.get("queue", "")
        add_filter(item, rule)

    for rule in notifications.get("cloudFunctionConfigurations", []):
        item = ET.SubElement(root, "CloudFunctionConfiguration")
        if rule.get("id"):
            ET.SubElement(item, "Id").text = rule.get("id", "")
        for event in rule.get("events", []):
            ET.SubElement(item, "Event").text = event
        ET.SubElement(item, "CloudFunction").text = rule.get("cloudFunction", "")
        add_filter(item, rule)

    return ET.tostring(root, encoding="utf-8", xml_declaration=True).decode("utf-8")


def _s3_parse_notification_xml(body: bytes) -> dict:
    config = _s3_default_notifications()
    if not body or not body.strip():
        return config
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise HTTPException(400, detail=f"MalformedXML: {exc}")
    if _s3_xml_name(root) != "NotificationConfiguration":
        raise HTTPException(400, detail="InvalidNotificationConfiguration")

    config["eventBridgeEnabled"] = _s3_xml_find_child(root, "EventBridgeConfiguration") is not None

    def parse_rule(el: ET.Element, dest_name: str) -> dict:
        rule = {
            "id": _s3_xml_text(el, "Id", _id("notif")),
            "events": [child.text.strip() for child in _s3_xml_find_children(el, "Event") if child.text and child.text.strip()],
            "prefix": "",
            "suffix": "",
        }
        if dest_name == "TopicConfiguration":
            rule["topic"] = _s3_xml_text(el, "Topic", "")
        elif dest_name == "QueueConfiguration":
            rule["queue"] = _s3_xml_text(el, "Queue", "")
        else:
            rule["cloudFunction"] = _s3_xml_text(el, "CloudFunction", "")
        filter_el = _s3_xml_find_child(el, "Filter")
        if filter_el is not None:
            s3_key = _s3_xml_find_child(filter_el, "S3Key")
            if s3_key is not None:
                for fr in _s3_xml_find_children(s3_key, "FilterRule"):
                    name = _s3_xml_text(fr, "Name", "").lower()
                    value = _s3_xml_text(fr, "Value", "")
                    if name == "prefix":
                        rule["prefix"] = value
                    elif name == "suffix":
                        rule["suffix"] = value
        return rule

    config["topicConfigurations"] = [parse_rule(el, "TopicConfiguration") for el in _s3_xml_find_children(root, "TopicConfiguration")]
    config["queueConfigurations"] = [parse_rule(el, "QueueConfiguration") for el in _s3_xml_find_children(root, "QueueConfiguration")]
    config["cloudFunctionConfigurations"] = [parse_rule(el, "CloudFunctionConfiguration") for el in _s3_xml_find_children(root, "CloudFunctionConfiguration")]
    config["updatedAt"] = _now()
    return config


def _s3_notification_summary(bucket: str) -> dict:
    notifications = _s3_bucket_notifications(bucket, create=False) or _s3_default_notifications()
    return {
        "bucket": bucket,
        "eventBridgeEnabled": bool(notifications.get("eventBridgeEnabled")),
        "rule_count": len(notifications.get("topicConfigurations", [])) + len(notifications.get("queueConfigurations", [])) + len(notifications.get("cloudFunctionConfigurations", [])),
        "delivery_count": len(notifications.get("deliveries", [])),
        "updatedAt": notifications.get("updatedAt", ""),
    }


# ---------------------------------------------------------------------------
# Tagging XML helpers
# ---------------------------------------------------------------------------


def _parse_tagging_xml(body: bytes) -> dict:
    tags = {}
    if not body:
        return tags
    try:
        root = ET.fromstring(body)
        for tag in root.iter("{http://s3.amazonaws.com/doc/2006-03-01/}Tag"):
            k = tag.find("{http://s3.amazonaws.com/doc/2006-03-01/}Key")
            v = tag.find("{http://s3.amazonaws.com/doc/2006-03-01/}Value")
            if k is not None and k.text:
                tags[k.text] = (v.text or "") if v is not None else ""
    except ET.ParseError:
        pass
    return tags


def _build_tagging_xml(tags: dict) -> str:
    tag_xml = "".join(
        f"<Tag><Key>{k}</Key><Value>{v}</Value></Tag>"
        for k, v in tags.items()
    )
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<Tagging xmlns="{S3_NS}"><TagSet>{tag_xml}</TagSet></Tagging>'
    )


# ---------------------------------------------------------------------------
# ListObjects helpers
# ---------------------------------------------------------------------------


def _list_objects_v1(bucket: str, params: dict) -> Response:
    prefix = params.get("prefix", "")
    delimiter = params.get("delimiter", "")
    marker = params.get("marker", "")
    max_keys = min(int(params.get("max-keys", 1000)), 1000)

    all_keys = []
    for k in sorted(objects[bucket]):
        if not k.startswith(prefix):
            continue
        entry = _s3_ensure_object_entry(bucket, k, create=False)
        if not entry or not entry.get("versions"):
            continue
        if entry["versions"][0].get("is_delete_marker"):
            continue
        all_keys.append(k)
    if marker:
        all_keys = [k for k in all_keys if k > marker]

    common_prefixes = set()
    result_keys = []
    for k in all_keys:
        if delimiter:
            suffix = k[len(prefix):]
            pos = suffix.find(delimiter)
            if pos >= 0:
                common_prefixes.add(prefix + suffix[: pos + len(delimiter)])
                continue
        result_keys.append(k)

    truncated = len(result_keys) > max_keys
    result_keys = result_keys[:max_keys]
    next_marker = result_keys[-1] if truncated else ""

    xml_parts = [
        f'<?xml version="1.0" encoding="UTF-8"?>',
        f'<ListBucketResult xmlns="{S3_NS}">',
        f"<Name>{bucket}</Name>",
        f"<Prefix>{prefix}</Prefix>",
        f"<Marker>{marker}</Marker>",
        f"<MaxKeys>{max_keys}</MaxKeys>",
        f"<IsTruncated>{'true' if truncated else 'false'}</IsTruncated>",
    ]
    if truncated:
        xml_parts.append(f"<NextMarker>{next_marker}</NextMarker>")
    if delimiter:
        xml_parts.append(f"<Delimiter>{delimiter}</Delimiter>")

    for k in result_keys:
        entry = _s3_ensure_object_entry(bucket, k, create=False)
        obj = entry["versions"][0] if entry and entry.get("versions") else None
        if not obj or obj.get("is_delete_marker"):
            continue
        xml_parts += [
            "<Contents>",
            f"<Key>{k}</Key>",
            f"<LastModified>{obj['last_modified']}</LastModified>",
            f"<ETag>{obj['etag']}</ETag>",
            f"<Size>{obj['size']}</Size>",
            f"<StorageClass>{obj.get('storage_class', 'STANDARD')}</StorageClass>",
            "<Owner><ID>simulator</ID><DisplayName>cloudlearn-simulator</DisplayName></Owner>",
            "</Contents>",
        ]
    for cp in sorted(common_prefixes):
        xml_parts.append(f"<CommonPrefixes><Prefix>{cp}</Prefix></CommonPrefixes>")
    xml_parts.append("</ListBucketResult>")
    return _xml_response("".join(xml_parts))


def _list_objects_v2(bucket: str, params: dict) -> Response:
    prefix = params.get("prefix", "")
    delimiter = params.get("delimiter", "")
    continuation_token = params.get("continuation-token", "")
    start_after = params.get("start-after", "")
    max_keys = min(int(params.get("max-keys", 1000)), 1000)
    fetch_owner = params.get("fetch-owner", "false").lower() == "true"

    start_key = continuation_token or start_after
    all_keys = []
    for k in sorted(objects[bucket]):
        if not k.startswith(prefix):
            continue
        entry = _s3_ensure_object_entry(bucket, k, create=False)
        if not entry or not entry.get("versions"):
            continue
        if entry["versions"][0].get("is_delete_marker"):
            continue
        all_keys.append(k)
    if start_key:
        all_keys = [k for k in all_keys if k > start_key]

    common_prefixes = set()
    result_keys = []
    for k in all_keys:
        if delimiter:
            suffix = k[len(prefix):]
            pos = suffix.find(delimiter)
            if pos >= 0:
                common_prefixes.add(prefix + suffix[: pos + len(delimiter)])
                continue
        result_keys.append(k)

    truncated = len(result_keys) > max_keys
    result_keys = result_keys[:max_keys]
    next_token = result_keys[-1] if truncated else ""

    xml_parts = [
        f'<?xml version="1.0" encoding="UTF-8"?>',
        f'<ListBucketResult xmlns="{S3_NS}">',
        f"<Name>{bucket}</Name>",
        f"<Prefix>{prefix}</Prefix>",
        f"<MaxKeys>{max_keys}</MaxKeys>",
        f"<KeyCount>{len(result_keys)}</KeyCount>",
        f"<IsTruncated>{'true' if truncated else 'false'}</IsTruncated>",
    ]
    if continuation_token:
        xml_parts.append(f"<ContinuationToken>{continuation_token}</ContinuationToken>")
    if truncated:
        xml_parts.append(f"<NextContinuationToken>{next_token}</NextContinuationToken>")
    if delimiter:
        xml_parts.append(f"<Delimiter>{delimiter}</Delimiter>")
    if start_after:
        xml_parts.append(f"<StartAfter>{start_after}</StartAfter>")

    for k in result_keys:
        entry = _s3_ensure_object_entry(bucket, k, create=False)
        obj = entry["versions"][0] if entry and entry.get("versions") else None
        if not obj or obj.get("is_delete_marker"):
            continue
        xml_parts += ["<Contents>", f"<Key>{k}</Key>",
                      f"<LastModified>{obj['last_modified']}</LastModified>",
                      f"<ETag>{obj['etag']}</ETag>",
                      f"<Size>{obj['size']}</Size>",
                      f"<StorageClass>{obj.get('storage_class', 'STANDARD')}</StorageClass>"]
        if fetch_owner:
            xml_parts += ["<Owner><ID>simulator</ID><DisplayName>cloudlearn-simulator</DisplayName></Owner>"]
        xml_parts.append("</Contents>")
    for cp in sorted(common_prefixes):
        xml_parts.append(f"<CommonPrefixes><Prefix>{cp}</Prefix></CommonPrefixes>")
    xml_parts.append("</ListBucketResult>")
    return _xml_response("".join(xml_parts))


# ---------------------------------------------------------------------------
# Tenant-scoped bucket helper (for GCS fallback)
# ---------------------------------------------------------------------------


def _tenant_scoped_bucket(name: str) -> str:
    return _srv()._tenant_scoped_bucket(name)


# ---------------------------------------------------------------------------
# AWS query-protocol root dispatch helpers
# ---------------------------------------------------------------------------

_AWS_CRED_SCOPE_RE = re.compile(r"Credential=[^/]*/[^/]*/[^/]*/([A-Za-z0-9_-]+)/aws4_request")


def _aws_query_target_service(request: Request) -> str:
    auth = request.headers.get("authorization", "") or ""
    match = _AWS_CRED_SCOPE_RE.search(auth)
    if match:
        return match.group(1).strip().lower()
    target = request.headers.get("x-amz-target", "") or ""
    if "dynamodb" in target.lower():
        return "dynamodb"
    if target.startswith("TrentService."):
        return "kms"
    if target.startswith("secretsmanager."):
        return "secretsmanager"
    if target.startswith("AWSEvents."):
        return "events"
    return ""


# ---------------------------------------------------------------------------
# Registration — MUST be called LAST
# ---------------------------------------------------------------------------


def register(app: FastAPI, *, aws_xamz_dispatchers: dict | None = None) -> None:
    """Register S3 REST API routes and the root AWS query-protocol dispatcher.

    CRITICAL: Call this LAST so the catch-all /{bucket} and
    /{bucket}/{key:path} routes don't shadow other routes.
    """

    _aws_xamz_dispatchers = aws_xamz_dispatchers or {}

    # Static dir reference for SPA serving
    import os
    STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
    _UI_HTML = os.path.join(STATIC_DIR, "index.html")
    _PRICING_HTML = os.path.join(STATIC_DIR, "pricing.html")

    # ── AWS query-protocol root dispatch ─────────────────────────────────

    _EC2_VPC_ACTIONS = {
        "CreateVpc", "DescribeVpcs", "DeleteVpc",
        "CreateSubnet", "DescribeSubnets", "DeleteSubnet",
        "CreateSecurityGroup", "AuthorizeSecurityGroupIngress", "AuthorizeSecurityGroupEgress",
        "CreateRouteTable", "DescribeRouteTables", "DeleteRouteTable",
        "CreateRoute", "AssociateRouteTable", "DisassociateRouteTable",
        "CreateInternetGateway", "DescribeInternetGateways", "AttachInternetGateway",
    }

    @app.post("/")
    async def aws_query_root(request: Request) -> Response:
        """Root dispatch for real AWS SDK/CLI query + JSON protocol requests."""
        service = _aws_query_target_service(request)
        if service == "ec2":
            params = await _srv()._ec2_query_params(request)
            if str(params.get("Action", "")).strip() in _EC2_VPC_ACTIONS:
                return await _srv().api_vpc_query(request)
            return await _srv().api_ec2_query(request)
        if service == "sqs":
            return await _srv().api_sqs_query(request)
        if service == "rds":
            return await _srv().api_rds_query(request)
        if service == "dynamodb":
            from routes.aws_dynamodb import api_dynamodb_aws as _ddb_handler
            return await _ddb_handler(request)
        if service == "iam":
            return await _srv().api_iam_query(request)
        if service == "sts":
            return await _srv().api_sts_query(request)
        if service in ("kms", "secretsmanager", "events"):
            target = request.headers.get("x-amz-target", "")
            prefix = target.split(".", 1)[0] if "." in target else ""
            dispatch = _aws_xamz_dispatchers.get(prefix)
            if dispatch is None:
                return Response(
                    content=json.dumps({"__type": "InvalidAction", "message": f"No dispatcher for X-Amz-Target prefix {prefix!r}"}),
                    status_code=400, media_type="application/x-amz-json-1.1",
                )
            body_raw = await request.body()
            try:
                body = json.loads(body_raw or b"{}")
            except Exception:
                body = {}
            spaces_state = _srv().PLATFORM.kernel.state.setdefault(
                "spaces", {"spaces": {}, "active_space_id": "", "settings": {}}
            )
            space = spaces_state.get("active_space_id", "default")
            resp = await dispatch(target, body, space)
            if resp is None:
                return Response(
                    content=json.dumps({"__type": "InternalFailure", "message": f"{service}/{target} unhandled or backend unavailable"}),
                    status_code=500, media_type="application/x-amz-json-1.1",
                )
            return Response(content=json.dumps(resp), media_type="application/x-amz-json-1.1")
        params = await _srv()._ec2_query_params(request)
        action = str(params.get("Action", "")).strip()
        return _error_xml("InvalidAction", f"Root dispatch could not route service={service or 'unknown'!r} action={action or 'unknown'!r}.", "/", 400)

    # ── S3 REST API — root level ────────────────────────────────────────

    @app.get("/")
    async def s3_list_buckets(request: Request) -> Response:
        """GET / -> ListBuckets (S3 wire) OR launch page = pricing.html (browser).

        / is now the appliance launch view (tier cards + SDK strip + compare
        table). The old /pricing route is retired and 302-redirects here.
        The SPA still lives at /ui for users who want to skip the launch.
        """
        accept = request.headers.get("accept", "")
        user_agent = request.headers.get("user-agent", "")
        if "text/html" in accept or "Mozilla" in user_agent:
            with open(_PRICING_HTML, "rb") as f:
                return Response(content=f.read(), media_type="text/html", headers={"Cache-Control": "no-store, max-age=0"})

        now = _now()
        xml_parts = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            f'<ListAllMyBucketsResult xmlns="{S3_NS}">',
            "<Owner><ID>simulator</ID><DisplayName>cloudlearn-simulator</DisplayName></Owner>",
            "<Buckets>",
        ]
        for name, meta in buckets.items():
            xml_parts.append(f"<Bucket><Name>{name}</Name><CreationDate>{meta['created']}</CreationDate></Bucket>")
        xml_parts += ["</Buckets>", "</ListAllMyBucketsResult>"]
        return _xml_response("".join(xml_parts))

    # ── S3 REST API — bucket level ──────────────────────────────────────

    @app.head("/{bucket}")
    async def s3_head_bucket(bucket: str, request: Request) -> Response:
        """HEAD /{bucket} -> HeadBucket"""
        # Skip if path collides with a reserved appliance prefix
        # (/api/*, /static/*, /console/*, etc.) — let FastAPI 404.
        if _is_reserved_bucket(bucket):
            raise HTTPException(status_code=404, detail="Not found")
        if not _bucket_exists(bucket):
            return _error_xml("NoSuchBucket", "The specified bucket does not exist.", f"/{bucket}", 404)
        return _empty_response(200)

    @app.put("/{bucket}")
    async def s3_put_bucket(bucket: str, request: Request) -> Response:
        """PUT /{bucket}[?versioning|?tagging|?cors|?lifecycle|?acl] -> Create/Configure Bucket"""
        # Skip if path collides with a reserved appliance prefix
        # (/api/*, /static/*, /console/*, etc.) — let FastAPI 404.
        if _is_reserved_bucket(bucket):
            raise HTTPException(status_code=404, detail="Not found")
        params = dict(request.query_params)

        # Versioning
        if "versioning" in params:
            if not _bucket_exists(bucket):
                return _error_xml("NoSuchBucket", "The specified bucket does not exist.", f"/{bucket}", 404)
            body = await request.body()
            status = "Suspended"
            if b"Enabled" in body:
                status = "Enabled"
            buckets[bucket]["versioning"] = status
            return _empty_response(200)

        if "notification" in params:
            if not _bucket_exists(bucket):
                return _error_xml("NoSuchBucket", "The specified bucket does not exist.", f"/{bucket}", 404)
            body = await request.body()
            buckets[bucket]["notifications"] = _s3_parse_notification_xml(body)
            if body.strip():
                _s3_notification_record_delivery(
                    bucket=bucket,
                    event_name="s3:TestEvent",
                    key="",
                    source="PutBucketNotificationConfiguration",
                    payload={"message": "TestEvent"},
                    test_event=True,
                )
            return _empty_response(200)

        # Tagging
        if "tagging" in params:
            if not _bucket_exists(bucket):
                return _error_xml("NoSuchBucket", "The specified bucket does not exist.", f"/{bucket}", 404)
            body = await request.body()
            tags = _parse_tagging_xml(body)
            buckets[bucket]["tags"] = tags
            return _empty_response(204)

        # ACL
        if "acl" in params:
            if not _bucket_exists(bucket):
                return _error_xml("NoSuchBucket", "The specified bucket does not exist.", f"/{bucket}", 404)
            body = await request.body()
            if body and body.strip():
                buckets[bucket]["acl"] = body.decode("utf-8", errors="replace")
            return _empty_response(200)

        # CORS
        if "cors" in params:
            if not _bucket_exists(bucket):
                return _error_xml("NoSuchBucket", "The specified bucket does not exist.", f"/{bucket}", 404)
            body = await request.body()
            if body and body.strip():
                try:
                    ET.fromstring(body)
                except ET.ParseError:
                    return _error_xml("MalformedXML", "The XML you provided was not well-formed.", f"/{bucket}", 400)
                buckets[bucket]["cors"] = body.decode("utf-8", errors="replace")
            return _empty_response(200)

        # Lifecycle
        if "lifecycle" in params:
            if not _bucket_exists(bucket):
                return _error_xml("NoSuchBucket", "The specified bucket does not exist.", f"/{bucket}", 404)
            body = await request.body()
            if body and body.strip():
                try:
                    ET.fromstring(body)
                except ET.ParseError:
                    return _error_xml("MalformedXML", "The XML you provided was not well-formed.", f"/{bucket}", 400)
                buckets[bucket]["lifecycle"] = body.decode("utf-8", errors="replace")
            return _empty_response(200)

        # Encryption
        if "encryption" in params:
            if not _bucket_exists(bucket):
                return _error_xml("NoSuchBucket", "The specified bucket does not exist.", f"/{bucket}", 404)
            return _empty_response(200)

        # CreateBucket
        err = _validate_bucket_name(bucket)
        if err:
            return err
        if _bucket_exists(bucket):
            return _error_xml("BucketAlreadyOwnedByYou", "Your previous request to create the named bucket succeeded.", f"/{bucket}", 409)

        body = await request.body()
        region = "us-east-1"
        if body:
            try:
                root = ET.fromstring(body)
                loc = root.find("{http://s3.amazonaws.com/doc/2006-03-01/}LocationConstraint")
                if loc is not None and loc.text:
                    region = loc.text
            except ET.ParseError:
                pass

        _enforce_quantity_cap("bucket")

        buckets[bucket] = {
            "region": region,
            "created": _now(),
            "access": "Bucket and objects not public",
            "versioning": "Disabled",
            "arn": f"arn:aws:s3:::{bucket}",
            "tags": {},
            "notifications": _s3_default_notifications(),
        }
        objects[bucket] = {}
        return _empty_response(200, {"Location": f"/{bucket}"})

    @app.get("/{bucket}")
    async def s3_get_bucket(bucket: str, request: Request) -> Response:
        """GET /{bucket}[?versioning|?tagging|?location|?list-type=2|...] -> List/Get Bucket Config"""
        # Skip if path collides with a reserved appliance prefix
        # (/api/*, /static/*, /console/*, etc.) — let FastAPI 404.
        if _is_reserved_bucket(bucket):
            raise HTTPException(status_code=404, detail="Not found")
        params = dict(request.query_params)

        if not _bucket_exists(bucket):
            return _error_xml("NoSuchBucket", "The specified bucket does not exist.", f"/{bucket}", 404)

        if "location" in params:
            region = buckets[bucket].get("region", "us-east-1")
            loc = "" if region == "us-east-1" else region
            xml = (
                f'<?xml version="1.0" encoding="UTF-8"?>'
                f'<LocationConstraint xmlns="{S3_NS}">{loc}</LocationConstraint>'
            )
            return _xml_response(xml)

        if "versioning" in params:
            status = buckets[bucket].get("versioning", "Disabled")
            status_xml = f"<Status>{status}</Status>" if status != "Disabled" else ""
            xml = (
                f'<?xml version="1.0" encoding="UTF-8"?>'
                f'<VersioningConfiguration xmlns="{S3_NS}">{status_xml}</VersioningConfiguration>'
            )
            return _xml_response(xml)

        if "notification" in params:
            return _xml_response(_s3_notification_xml_from_config(bucket))

        if "versions" in params:
            prefix = params.get("prefix", "")
            marker = params.get("key-marker", "")
            version_marker = params.get("version-id-marker", "")
            max_keys = min(int(params.get("max-keys", 1000)), 1000)
            all_versions = _s3_list_versions(bucket, prefix)
            if marker:
                filtered = []
                started = False
                for key_name, version in all_versions:
                    if not started:
                        if key_name < marker:
                            continue
                        if key_name > marker:
                            started = True
                            filtered.append((key_name, version))
                            continue
                        if version_marker:
                            if str(version.get("version_id", "")) == str(version_marker):
                                started = True
                            continue
                        continue
                    filtered.append((key_name, version))
                all_versions = filtered
            truncated = len(all_versions) > max_keys
            page = all_versions[:max_keys]
            xml_parts = [
                '<?xml version="1.0" encoding="UTF-8"?>',
                f'<ListVersionsResult xmlns="{S3_NS}">',
                f"<Name>{bucket}</Name>",
                f"<Prefix>{prefix}</Prefix>",
                f"<KeyMarker>{marker}</KeyMarker>",
                f"<VersionIdMarker>{version_marker}</VersionIdMarker>",
                f"<MaxKeys>{max_keys}</MaxKeys>",
                f"<IsTruncated>{'true' if truncated else 'false'}</IsTruncated>",
            ]
            if truncated and page:
                last_key, last_version = page[-1]
                xml_parts.append(f"<NextKeyMarker>{last_key}</NextKeyMarker>")
                xml_parts.append(f"<NextVersionIdMarker>{last_version.get('version_id', 'null')}</NextVersionIdMarker>")
            for key_name, version in page:
                tag_name = "DeleteMarker" if version.get("is_delete_marker") else "Version"
                xml_parts.append(f"<{tag_name}>")
                xml_parts.append(f"<Key>{key_name}</Key>")
                xml_parts.append(f"<VersionId>{version.get('version_id', 'null')}</VersionId>")
                xml_parts.append(f"<IsLatest>{'true' if version.get('is_latest') else 'false'}</IsLatest>")
                xml_parts.append(f"<LastModified>{version.get('last_modified')}</LastModified>")
                xml_parts.append("<Owner><ID>simulator</ID><DisplayName>cloudlearn-simulator</DisplayName></Owner>")
                if not version.get("is_delete_marker"):
                    xml_parts.append(f"<ETag>{version.get('etag', '')}</ETag>")
                    xml_parts.append(f"<Size>{version.get('size', 0)}</Size>")
                    xml_parts.append(f"<StorageClass>{version.get('storage_class', 'STANDARD')}</StorageClass>")
                xml_parts.append(f"</{tag_name}>")
            xml_parts.append("</ListVersionsResult>")
            return _xml_response("".join(xml_parts))

        if "tagging" in params:
            tags = buckets[bucket].get("tags", {})
            if not tags:
                return _error_xml("NoSuchTagSet", "The TagSet does not exist.", f"/{bucket}", 404)
            xml = _build_tagging_xml(tags)
            return _xml_response(xml)

        if "acl" in params:
            stored_acl = buckets[bucket].get("acl")
            if stored_acl:
                return _xml_response(stored_acl)
            xml = (
                f'<?xml version="1.0" encoding="UTF-8"?>'
                f'<AccessControlPolicy xmlns="{S3_NS}">'
                "<Owner><ID>simulator</ID><DisplayName>cloudlearn-simulator</DisplayName></Owner>"
                "<AccessControlList>"
                '<Grant><Grantee xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:type="CanonicalUser">'
                "<ID>simulator</ID><DisplayName>cloudlearn-simulator</DisplayName>"
                "</Grantee><Permission>FULL_CONTROL</Permission></Grant>"
                "</AccessControlList>"
                "</AccessControlPolicy>"
            )
            return _xml_response(xml)

        if "encryption" in params:
            return _error_xml("ServerSideEncryptionConfigurationNotFoundError",
                              "The server side encryption configuration was not found.", f"/{bucket}", 404)

        if "lifecycle" in params:
            stored_lifecycle = buckets[bucket].get("lifecycle")
            if stored_lifecycle:
                return _xml_response(stored_lifecycle)
            return _error_xml("NoSuchLifecycleConfiguration",
                              "The lifecycle configuration does not exist.", f"/{bucket}", 404)

        if "cors" in params:
            stored_cors = buckets[bucket].get("cors")
            if stored_cors:
                return _xml_response(stored_cors)
            return _error_xml("NoSuchCORSConfiguration",
                              "The CORS configuration does not exist.", f"/{bucket}", 404)

        if "uploads" in params:
            xml_parts = [
                f'<?xml version="1.0" encoding="UTF-8"?>',
                f'<ListMultipartUploadsResult xmlns="{S3_NS}">',
                f"<Bucket>{bucket}</Bucket>",
                "<KeyMarker></KeyMarker>",
                "<UploadIdMarker></UploadIdMarker>",
                "<NextKeyMarker></NextKeyMarker>",
                "<NextUploadIdMarker></NextUploadIdMarker>",
                "<MaxUploads>1000</MaxUploads>",
                "<IsTruncated>false</IsTruncated>",
            ]
            for uid, mp in multiparts.items():
                if mp["bucket"] == bucket:
                    xml_parts += [
                        "<Upload>",
                        f"<Key>{mp['key']}</Key>",
                        f"<UploadId>{uid}</UploadId>",
                        "<Initiator><ID>simulator</ID><DisplayName>cloudlearn-simulator</DisplayName></Initiator>",
                        "<Owner><ID>simulator</ID><DisplayName>cloudlearn-simulator</DisplayName></Owner>",
                        "<StorageClass>STANDARD</StorageClass>",
                        f"<Initiated>{mp['initiated']}</Initiated>",
                        "</Upload>",
                    ]
            xml_parts.append("</ListMultipartUploadsResult>")
            return _xml_response("".join(xml_parts))

        if params.get("list-type") == "2":
            return _list_objects_v2(bucket, params)

        return _list_objects_v1(bucket, params)

    @app.delete("/{bucket}")
    async def s3_delete_bucket(bucket: str, request: Request) -> Response:
        """DELETE /{bucket} -> DeleteBucket"""
        # Skip if path collides with a reserved appliance prefix
        # (/api/*, /static/*, /console/*, etc.) — let FastAPI 404.
        if _is_reserved_bucket(bucket):
            raise HTTPException(status_code=404, detail="Not found")
        params = dict(request.query_params)
        if not _bucket_exists(bucket):
            return _error_xml("NoSuchBucket", "The specified bucket does not exist.", f"/{bucket}", 404)
        if "notification" in params:
            buckets[bucket]["notifications"] = _s3_default_notifications()
            return _empty_response(204)
        if "cors" in params:
            buckets[bucket].pop("cors", None)
            return _empty_response(204)
        if "lifecycle" in params:
            buckets[bucket].pop("lifecycle", None)
            return _empty_response(204)
        if "tagging" in params:
            buckets[bucket].pop("tags", None)
            return _empty_response(204)
        if objects.get(bucket):
            return _error_xml("BucketNotEmpty", "The bucket you tried to delete is not empty.", f"/{bucket}", 409)
        del buckets[bucket]
        del objects[bucket]
        return _empty_response(204)

    # ── S3 REST API — object level ──────────────────────────────────────

    @app.head("/{bucket}/{key:path}")
    async def s3_head_object(bucket: str, key: str, request: Request) -> Response:
        """HEAD /{bucket}/{key} -> HeadObject"""
        # Skip if path collides with a reserved appliance prefix
        # (/api/*, /static/*, /console/*, etc.) — let FastAPI 404.
        if _is_reserved_bucket(bucket):
            raise HTTPException(status_code=404, detail="Not found")
        if not _bucket_exists(bucket):
            return _error_xml("NoSuchBucket", "The specified bucket does not exist.", f"/{bucket}/{key}", 404)
        entry = _s3_ensure_object_entry(bucket, key, create=False)
        version_id = request.query_params.get("versionId")
        obj = _s3_find_version(entry, version_id) if entry else None
        if obj and obj.get("is_delete_marker"):
            if version_id:
                return _delete_marker_response(f"/{bucket}/{key}", obj.get("last_modified", _now()))
            return _error_xml("NoSuchKey", "The specified key does not exist.", f"/{bucket}/{key}", 404)
        if not obj:
            return _error_xml("NoSuchKey", "The specified key does not exist.", f"/{bucket}/{key}", 404)
        headers = {
            "Content-Length": str(obj["size"]),
            "Content-Type": obj["content_type"],
            "ETag": obj["etag"],
            "Last-Modified": _iso_to_http_date(obj["last_modified"]),
            "x-amz-storage-class": obj.get("storage_class", "STANDARD"),
            "x-amz-version-id": obj.get("version_id", "null"),
        }
        for k, v in obj.get("metadata", {}).items():
            headers[f"x-amz-meta-{k}"] = v
        return _empty_response(200, headers)

    @app.put("/{bucket}/{key:path}")
    async def s3_put_object(bucket: str, key: str, request: Request) -> Response:
        """PUT /{bucket}/{key}[?tagging|?acl|?uploadId&partNumber] -> PutObject/UploadPart/CopyObject/Tagging"""
        # Skip if path collides with a reserved appliance prefix
        # (/api/*, /static/*, /console/*, etc.) — let FastAPI 404.
        if _is_reserved_bucket(bucket):
            raise HTTPException(status_code=404, detail="Not found")
        params = dict(request.query_params)

        if not _bucket_exists(bucket):
            return _error_xml("NoSuchBucket", "The specified bucket does not exist.", f"/{bucket}", 404)

        # UploadPart
        if "uploadId" in params and "partNumber" in params:
            upload_id = params["uploadId"]
            part_number = int(params["partNumber"])
            if upload_id not in multiparts:
                return _error_xml("NoSuchUpload", "The specified upload does not exist.", f"/{bucket}/{key}", 404)
            data = _decode_aws_chunked(await request.body(), request.headers)
            etag_val = _etag(data)
            multiparts[upload_id]["parts"][part_number] = {"data": data, "etag": etag_val, "size": len(data)}
            return _empty_response(200, {"ETag": etag_val})

        # Object tagging
        if "tagging" in params:
            entry = _s3_ensure_object_entry(bucket, key, create=False)
            if not entry or not entry.get("versions"):
                return _error_xml("NoSuchKey", "The specified key does not exist.", f"/{bucket}/{key}", 404)
            body = await request.body()
            tags = _parse_tagging_xml(body)
            entry["versions"][0]["tags"] = tags
            _s3_refresh_object_entry(entry)
            return _empty_response(200)

        # Object ACL
        if "acl" in params:
            entry = _s3_ensure_object_entry(bucket, key, create=False)
            if not entry or not entry.get("versions"):
                return _error_xml("NoSuchKey", "The specified key does not exist.", f"/{bucket}/{key}", 404)
            return _empty_response(200)

        # CopyObject (x-amz-copy-source header present)
        copy_source = request.headers.get("x-amz-copy-source")
        if copy_source:
            copy_source = copy_source.lstrip("/")
            parts = copy_source.split("/", 1)
            if len(parts) < 2:
                return _error_xml("InvalidArgument", "Invalid copy source.", f"/{bucket}/{key}", 400)
            src_bucket, src_key = parts[0], parts[1]
            if not _bucket_exists(src_bucket):
                return _error_xml("NoSuchBucket", "The source bucket does not exist.", f"/{src_bucket}", 404)
            src_entry = _s3_ensure_object_entry(src_bucket, src_key, create=False)
            src = _s3_find_version(src_entry, request.headers.get("x-amz-copy-source-version-id")) if src_entry else None
            if not src or src.get("is_delete_marker"):
                return _error_xml("NoSuchKey", "The source key does not exist.", f"/{src_bucket}/{src_key}", 404)
            now = _now()
            new_content_type = request.headers.get("x-amz-metadata-directive", "COPY") == "REPLACE" and request.headers.get("content-type", src["content_type"]) or src["content_type"]
            versioning_status = _s3_bucket_versioning_status(bucket)
            vid = _s3_new_version_id(bucket) if versioning_status == "Enabled" else "null"
            version = _s3_make_version_record(
                data=src["data"],
                content_type=new_content_type,
                storage_class="STANDARD",
                metadata=src.get("metadata", {}).copy(),
                tags=src.get("tags", {}).copy(),
                version_id=vid,
                delete_marker=False,
                last_modified=now,
                etag=_etag(src["data"]),
            )
            replace_vid = "__overwrite__" if versioning_status == "Disabled" else ("null" if versioning_status == "Suspended" else None)
            _s3_write_object_version(bucket, key, version, replace_version_id=replace_vid, event_name="s3:ObjectCreated:Copy", source="CopyObject")
            new_etag = version["etag"]
            xml = (
                f'<?xml version="1.0" encoding="UTF-8"?>'
                f'<CopyObjectResult xmlns="{S3_NS}">'
                f"<LastModified>{now}</LastModified>"
                f"<ETag>{new_etag}</ETag>"
                "</CopyObjectResult>"
            )
            return _xml_response(xml)

        # PutObject
        data = _decode_aws_chunked(await request.body(), request.headers)
        content_type = request.headers.get("content-type", "application/octet-stream")
        storage_class = request.headers.get("x-amz-storage-class", "STANDARD")

        user_meta = {}
        for h, v in request.headers.items():
            if h.lower().startswith("x-amz-meta-"):
                user_meta[h[11:]] = v

        versioning_status = _s3_bucket_versioning_status(bucket)
        vid = _s3_new_version_id(bucket) if versioning_status == "Enabled" else "null"
        version = _s3_make_version_record(
            data=data,
            content_type=content_type,
            storage_class=storage_class,
            metadata=user_meta,
            tags={},
            version_id=vid,
            delete_marker=False,
        )
        replace_vid = "__overwrite__" if versioning_status == "Disabled" else ("null" if versioning_status == "Suspended" else None)
        entry = _s3_write_object_version(bucket, key, version, replace_version_id=replace_vid, event_name="s3:ObjectCreated:Put", source="PutObject")
        return _empty_response(200, {"ETag": version["etag"], "x-amz-version-id": entry.get("current_version_id", vid)})

    @app.get("/{bucket}/{key:path}")
    async def s3_get_object(bucket: str, key: str, request: Request) -> Response:
        """GET /{bucket}/{key}[?tagging|?acl|?uploadId] -> GetObject/GetObjectTagging/ListParts"""
        # Skip if path collides with a reserved appliance prefix
        # (/api/*, /static/*, /console/*, etc.) — let FastAPI 404.
        if _is_reserved_bucket(bucket):
            raise HTTPException(status_code=404, detail="Not found")
        params = dict(request.query_params)

        if not _bucket_exists(bucket):
            if key and not ({"uploadId", "tagging", "acl", "versions", "uploads"} & set(params)):
                try:
                    from core import gcp_gcs_store as _gcs
                    if _gcs.available():
                        data, ctype = _gcs.download(_tenant_scoped_bucket(bucket), key)
                        return Response(content=data, media_type=ctype or "application/octet-stream")
                except Exception:
                    pass
            return _error_xml("NoSuchBucket", "The specified bucket does not exist.", f"/{bucket}", 404)

        # ListParts
        if "uploadId" in params:
            upload_id = params["uploadId"]
            if upload_id not in multiparts:
                return _error_xml("NoSuchUpload", "The specified upload does not exist.", f"/{bucket}/{key}", 404)
            mp = multiparts[upload_id]
            xml_parts = [
                f'<?xml version="1.0" encoding="UTF-8"?>',
                f'<ListPartsResult xmlns="{S3_NS}">',
                f"<Bucket>{bucket}</Bucket>",
                f"<Key>{key}</Key>",
                f"<UploadId>{upload_id}</UploadId>",
                "<Initiator><ID>simulator</ID><DisplayName>cloudlearn-simulator</DisplayName></Initiator>",
                "<Owner><ID>simulator</ID><DisplayName>cloudlearn-simulator</DisplayName></Owner>",
                "<StorageClass>STANDARD</StorageClass>",
                "<IsTruncated>false</IsTruncated>",
            ]
            for pn in sorted(mp["parts"]):
                p = mp["parts"][pn]
                xml_parts += [
                    "<Part>",
                    f"<PartNumber>{pn}</PartNumber>",
                    f"<LastModified>{_now()}</LastModified>",
                    f"<ETag>{p['etag']}</ETag>",
                    f"<Size>{p['size']}</Size>",
                    "</Part>",
                ]
            xml_parts.append("</ListPartsResult>")
            return _xml_response("".join(xml_parts))

        # GetObjectTagging
        if "tagging" in params:
            entry = _s3_ensure_object_entry(bucket, key, create=False)
            vid = params.get("versionId")
            obj = _s3_find_version(entry, vid) if entry else None
            if not obj or obj.get("is_delete_marker"):
                return _error_xml("NoSuchKey", "The specified key does not exist.", f"/{bucket}/{key}", 404)
            tags = obj.get("tags", {})
            xml = _build_tagging_xml(tags)
            return _xml_response(xml)

        # GetObjectAcl
        if "acl" in params:
            entry = _s3_ensure_object_entry(bucket, key, create=False)
            vid = params.get("versionId")
            obj = _s3_find_version(entry, vid) if entry else None
            if not obj or obj.get("is_delete_marker"):
                return _error_xml("NoSuchKey", "The specified key does not exist.", f"/{bucket}/{key}", 404)
            xml = (
                f'<?xml version="1.0" encoding="UTF-8"?>'
                f'<AccessControlPolicy xmlns="{S3_NS}">'
                "<Owner><ID>simulator</ID><DisplayName>cloudlearn-simulator</DisplayName></Owner>"
                "<AccessControlList>"
                '<Grant><Grantee xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:type="CanonicalUser">'
                "<ID>simulator</ID><DisplayName>cloudlearn-simulator</DisplayName>"
                "</Grantee><Permission>FULL_CONTROL</Permission></Grant>"
                "</AccessControlList>"
                "</AccessControlPolicy>"
            )
            return _xml_response(xml)

        # GetObject
        entry = _s3_ensure_object_entry(bucket, key, create=False)
        vid = params.get("versionId")
        obj = _s3_find_version(entry, vid) if entry else None
        if obj and obj.get("is_delete_marker"):
            if vid:
                return _delete_marker_response(f"/{bucket}/{key}", obj.get("last_modified", _now()))
            return _error_xml("NoSuchKey", "The specified key does not exist.", f"/{bucket}/{key}", 404)
        if not obj:
            return _error_xml("NoSuchKey", "The specified key does not exist.", f"/{bucket}/{key}", 404)
        data = obj["data"]
        status = 200
        content_range = None

        range_header = request.headers.get("range")
        if range_header:
            match = re.match(r"bytes=(\d+)-(\d*)", range_header)
            if match:
                start = int(match.group(1))
                end = int(match.group(2)) if match.group(2) else len(data) - 1
                end = min(end, len(data) - 1)
                data = data[start:end + 1]
                status = 206
                content_range = f"bytes {start}-{end}/{obj['size']}"

        headers = {
            "Content-Type": obj["content_type"],
            "ETag": obj["etag"],
            "Last-Modified": _iso_to_http_date(obj["last_modified"]),
            "Content-Length": str(len(data)),
            "x-amz-storage-class": obj.get("storage_class", "STANDARD"),
            "x-amz-version-id": obj.get("version_id", "null"),
            "x-amz-request-id": _req_id(),
            "x-amz-id-2": uuid.uuid4().hex,
        }
        if content_range:
            headers["Content-Range"] = content_range
        for k, v in obj.get("metadata", {}).items():
            headers[f"x-amz-meta-{k}"] = v

        return StreamingResponse(
            io.BytesIO(data),
            status_code=status,
            media_type=obj["content_type"],
            headers=headers,
        )

    @app.delete("/{bucket}/{key:path}")
    async def s3_delete_object(bucket: str, key: str, request: Request) -> Response:
        """DELETE /{bucket}/{key}[?tagging|?uploadId] -> DeleteObject/AbortMultipartUpload/DeleteObjectTagging"""
        # Skip if path collides with a reserved appliance prefix
        # (/api/*, /static/*, /console/*, etc.) — let FastAPI 404.
        if _is_reserved_bucket(bucket):
            raise HTTPException(status_code=404, detail="Not found")
        params = dict(request.query_params)

        if not _bucket_exists(bucket):
            return _error_xml("NoSuchBucket", "The specified bucket does not exist.", f"/{bucket}", 404)

        if "uploadId" in params:
            upload_id = params["uploadId"]
            if upload_id in multiparts:
                del multiparts[upload_id]
            return _empty_response(204)

        if "tagging" in params:
            entry = _s3_ensure_object_entry(bucket, key, create=False)
            vid = params.get("versionId")
            obj = _s3_find_version(entry, vid) if entry else None
            if not obj or obj.get("is_delete_marker"):
                return _error_xml("NoSuchKey", "The specified key does not exist.", f"/{bucket}/{key}", 404)
            obj["tags"] = {}
            if entry and entry.get("versions"):
                _s3_refresh_object_entry(entry)
            return _empty_response(204)

        entry = _s3_ensure_object_entry(bucket, key, create=False)
        vid = params.get("versionId")
        if vid:
            if not _s3_delete_version(bucket, key, vid):
                return _error_xml("NoSuchVersion", "The specified version does not exist.", f"/{bucket}/{key}", 404)
            return _empty_response(204, {"x-amz-version-id": vid})
        status = _s3_bucket_versioning_status(bucket)
        if status == "Disabled":
            if key in objects.get(bucket, {}):
                del objects[bucket][key]
            return _empty_response(204)
        entry = _s3_insert_simple_delete_marker(bucket, key, source="DeleteObject")
        vid = entry.get("current_version_id", "null") if isinstance(entry, dict) else "null"
        return _empty_response(204, {"x-amz-delete-marker": "true", "x-amz-version-id": vid})

    @app.post("/{bucket}")
    async def s3_post_bucket(bucket: str, request: Request) -> Response:
        """POST /{bucket}[?delete] -> DeleteObjects (batch)"""
        # Skip if path collides with a reserved appliance prefix
        # (/api/*, /static/*, /console/*, etc.) — let FastAPI 404.
        if _is_reserved_bucket(bucket):
            raise HTTPException(status_code=404, detail="Not found")
        params = dict(request.query_params)

        if not _bucket_exists(bucket):
            return _error_xml("NoSuchBucket", "The specified bucket does not exist.", f"/{bucket}", 404)

        if "delete" in params:
            body = await request.body()
            deleted = []
            errors = []
            try:
                root = ET.fromstring(body)
                for obj_el in root.findall("{http://s3.amazonaws.com/doc/2006-03-01/}Object"):
                    key_el = obj_el.find("{http://s3.amazonaws.com/doc/2006-03-01/}Key")
                    if key_el is not None and key_el.text:
                        k = key_el.text
                        if k in objects.get(bucket, {}):
                            if _s3_bucket_versioning_status(bucket) == "Disabled":
                                del objects[bucket][k]
                                _s3_emit_event(bucket, k, "s3:ObjectRemoved:Delete", None, source="DeleteObjects")
                            else:
                                _s3_insert_simple_delete_marker(bucket, k, source="DeleteObjects")
                        deleted.append(k)
            except ET.ParseError:
                return _error_xml("MalformedXML", "The XML you provided was not well-formed.", f"/{bucket}", 400)

            xml_parts = [
                f'<?xml version="1.0" encoding="UTF-8"?>',
                f'<DeleteResult xmlns="{S3_NS}">',
            ]
            for k in deleted:
                xml_parts += [f"<Deleted><Key>{k}</Key></Deleted>"]
            for e in errors:
                xml_parts += [f"<Error><Key>{e['key']}</Key><Code>{e['code']}</Code><Message>{e['message']}</Message></Error>"]
            xml_parts.append("</DeleteResult>")
            return _xml_response("".join(xml_parts))

        return _error_xml("MethodNotAllowed", "The specified method is not allowed against this resource.", f"/{bucket}", 405)

    @app.post("/{bucket}/{key:path}")
    async def s3_post_object(bucket: str, key: str, request: Request) -> Response:
        """POST /{bucket}/{key}?uploads -> CreateMultipartUpload
           POST /{bucket}/{key}?uploadId=... -> CompleteMultipartUpload"""
        # Skip if path collides with a reserved appliance prefix
        # (/api/*, /static/*, /console/*, etc.) — let FastAPI 404.
        if _is_reserved_bucket(bucket):
            raise HTTPException(status_code=404, detail="Not found")
        params = dict(request.query_params)

        if not _bucket_exists(bucket):
            return _error_xml("NoSuchBucket", "The specified bucket does not exist.", f"/{bucket}", 404)

        if "uploads" in params:
            upload_id = str(uuid.uuid4())
            content_type = request.headers.get("content-type", "application/octet-stream")
            user_meta = {}
            for h, v in request.headers.items():
                if h.lower().startswith("x-amz-meta-"):
                    user_meta[h[11:]] = v
            multiparts[upload_id] = {
                "bucket": bucket,
                "key": key,
                "parts": {},
                "content_type": content_type,
                "metadata": user_meta,
                "initiated": _now(),
            }
            xml = (
                f'<?xml version="1.0" encoding="UTF-8"?>'
                f'<InitiateMultipartUploadResult xmlns="{S3_NS}">'
                f"<Bucket>{bucket}</Bucket>"
                f"<Key>{key}</Key>"
                f"<UploadId>{upload_id}</UploadId>"
                "</InitiateMultipartUploadResult>"
            )
            return _xml_response(xml)

        if "uploadId" in params:
            upload_id = params["uploadId"]
            if upload_id not in multiparts:
                return _error_xml("NoSuchUpload", "The specified upload does not exist.", f"/{bucket}/{key}", 404)
            mp = multiparts[upload_id]
            body = await request.body()

            ordered_parts = []
            try:
                root = ET.fromstring(body)
                for part_el in root.findall("{http://s3.amazonaws.com/doc/2006-03-01/}Part"):
                    pn_el = part_el.find("{http://s3.amazonaws.com/doc/2006-03-01/}PartNumber")
                    if pn_el is not None and pn_el.text:
                        pn = int(pn_el.text)
                        if pn in mp["parts"]:
                            ordered_parts.append(pn)
            except ET.ParseError:
                ordered_parts = sorted(mp["parts"].keys())

            if not ordered_parts:
                ordered_parts = sorted(mp["parts"].keys())

            assembled = b"".join(mp["parts"][pn]["data"] for pn in ordered_parts)
            versioning_status = _s3_bucket_versioning_status(bucket)
            vid = _s3_new_version_id(bucket) if versioning_status == "Enabled" else "null"
            version = _s3_make_version_record(
                data=assembled,
                content_type=mp["content_type"],
                storage_class="STANDARD",
                metadata=mp["metadata"],
                tags={},
                version_id=vid,
                delete_marker=False,
            )
            replace_vid = "__overwrite__" if versioning_status == "Disabled" else ("null" if versioning_status == "Suspended" else None)
            _s3_write_object_version(bucket, key, version, replace_version_id=replace_vid, event_name="s3:ObjectCreated:CompleteMultipartUpload", source="CompleteMultipartUpload")
            del multiparts[upload_id]

            xml = (
                f'<?xml version="1.0" encoding="UTF-8"?>'
                f'<CompleteMultipartUploadResult xmlns="{S3_NS}">'
                f"<Location>http://localhost:9000/{bucket}/{key}</Location>"
                f"<Bucket>{bucket}</Bucket>"
                f"<Key>{key}</Key>"
                f"<ETag>{version['etag']}</ETag>"
                "</CompleteMultipartUploadResult>"
            )
            return _xml_response(xml)

        return _error_xml("MethodNotAllowed", "The specified method is not allowed against this resource.", f"/{bucket}/{key}", 405)
