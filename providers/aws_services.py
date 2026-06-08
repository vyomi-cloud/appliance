from __future__ import annotations

import base64
import copy
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
import textwrap
import threading
import traceback
from pathlib import Path
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException, Request, Response
from fastapi.responses import JSONResponse
from urllib.error import HTTPError, URLError
from urllib.request import Request as URLRequest, urlopen


from core.app_context import (
    AWS_ACCOUNT_ID as _AWS_ACCOUNT_ID,
    id_gen as _id_gen,
    now as _now,
    parse_utc_timestamp as _parse_ts,
    persist_state as _persist_state,
    record_usage as _record_usage,
    sqs_state as _sqs_state_proxy,
    ddb_state as _ddb_state_proxy,
    lambda_state as _lambda_state_proxy,
    apigw_state as _apigw_state_proxy,
)


def _server():
    import server as server_module

    return server_module


def _aws_account_id() -> str:
    return _AWS_ACCOUNT_ID


def _sqs_state() -> dict:
    return _sqs_state_proxy


def _sqs_queue_key(queue_name: str) -> str:
    return (queue_name or "").strip()


def _sqs_validate_queue_name(queue_name: str) -> None:
    if not queue_name:
        raise HTTPException(400, detail="MissingParameter: queue_name is required.")
    if len(queue_name) < 1 or len(queue_name) > 80:
        raise HTTPException(400, detail="InvalidParameterValue: queue_name must be 1-80 characters.")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", queue_name):
        raise HTTPException(400, detail="InvalidParameterValue: queue_name can contain letters, numbers, periods, underscores, and hyphens.")


def _sqs_queue_url(queue_name: str) -> str:
    return f"http://127.0.0.1:9000/api/sqs/queues/{queue_name}"


def _sqs_queue_arn(queue_name: str) -> str:
    return f"arn:aws:sqs:us-east-1:{_aws_account_id()}:{queue_name}"


def _sqs_find_queue(queue_name: str) -> dict | None:
    key = _sqs_queue_key(queue_name)
    if not key:
        return None
    queues = _sqs_state().setdefault("queues", {})
    if key in queues:
        return queues[key]
    lowered = key.lower()
    for existing_name, queue in queues.items():
        if existing_name.lower() == lowered:
            return queue
    return None


def _sqs_set_queue(queue: dict) -> dict:
    _sqs_state().setdefault("queues", {})[queue["queue_name"]] = queue
    return queue


def _sqs_list_queues() -> list[dict]:
    queues = list(_sqs_state().setdefault("queues", {}).values())
    queues.sort(key=lambda item: (item.get("created", ""), item.get("queue_name", "")))
    return queues


def _sqs_normalize_queue(queue: dict) -> dict:
    queue.setdefault("queue_name", "")
    queue.setdefault("queue_type", "standard")
    queue.setdefault("fifo_queue", bool(str(queue.get("queue_name", "")).endswith(".fifo")))
    queue.setdefault("content_based_deduplication", False)
    queue.setdefault("visibility_timeout", 30)
    queue.setdefault("receive_wait_time_seconds", 0)
    queue.setdefault("message_retention_period", 345600)
    queue.setdefault("max_message_size", 262144)
    queue.setdefault("delay_seconds", 0)
    queue.setdefault("redrive_policy", {})
    queue.setdefault("tags", {})
    queue.setdefault("attributes", {})
    queue.setdefault("messages", [])
    queue.setdefault("created", _now())
    queue.setdefault("last_modified", _now())
    return queue


def _sqs_timestamp(value: str | None) -> int:
    parsed = _parse_ts(value)
    return int(parsed.timestamp()) if parsed else 0


def _sqs_message_is_visible(message: dict) -> bool:
    if message.get("deleted"):
        return False
    visible_at = message.get("visible_at") or ""
    if not visible_at:
        return True
    parsed = _parse_ts(visible_at)
    return True if parsed is None else parsed <= datetime.now(timezone.utc)


def _sqs_sweep_queue(queue: dict) -> None:
    now = datetime.now(timezone.utc)
    retention = int(queue.get("message_retention_period", 345600) or 345600)
    messages = []
    for message in queue.get("messages", []):
        if not isinstance(message, dict):
            continue
        sent_at = message.get("sent_at", "")
        if sent_at:
            try:
                parsed_sent = _parse_ts(sent_at)
                if parsed_sent and now - parsed_sent > timedelta(seconds=retention):
                    continue
            except Exception:
                pass
        if message.get("in_flight") and message.get("visible_at"):
            try:
                parsed_visible = _parse_ts(message["visible_at"])
                if parsed_visible and parsed_visible <= now:
                    message["in_flight"] = False
                    message["receipt_handle"] = ""
            except Exception:
                message["in_flight"] = False
                message["receipt_handle"] = ""
        if not message.get("deleted"):
            messages.append(message)
    queue["messages"] = messages


def _sqs_dedup_key(queue: dict, body: str, dedup_id: str) -> str:
    if dedup_id:
        return dedup_id
    if queue.get("content_based_deduplication"):
        return hashlib.sha256(body.encode("utf-8")).hexdigest()
    return ""


def _sqs_message_is_blocked_by_fifo(queue: dict, message: dict) -> bool:
    if not queue.get("fifo_queue"):
        return False
    group_id = message.get("group_id", "") or "__default__"
    for candidate in queue.get("messages", []):
        if candidate is message:
            break
        if candidate.get("deleted"):
            continue
        if (candidate.get("group_id", "") or "__default__") != group_id:
            continue
        if candidate.get("in_flight"):
            return True
    return False


def _sqs_view_message(queue: dict, message: dict, include_body: bool = True) -> dict:
    view = {
        "message_id": message.get("message_id", ""),
        "receipt_handle": message.get("receipt_handle", ""),
        "receive_count": int(message.get("receive_count", 0) or 0),
        "sent_at": message.get("sent_at", ""),
        "visible_at": message.get("visible_at", ""),
        "group_id": message.get("group_id", ""),
        "dedup_id": message.get("dedup_id", ""),
        "in_flight": bool(message.get("in_flight", False)),
        "md5_of_body": message.get("md5_of_body", ""),
        "sequence_number": message.get("sequence_number", ""),
    }
    if include_body:
        view["body"] = message.get("body", "")
        view["attributes"] = copy.deepcopy(message.get("attributes", {}))
        view["message_attributes"] = copy.deepcopy(message.get("message_attributes", {}))
    return view


def _sqs_queue_attributes(queue: dict) -> dict[str, str]:
    attrs = {
        "ApproximateNumberOfMessages": str(sum(1 for m in queue.get("messages", []) if not m.get("deleted") and not m.get("in_flight") and _sqs_message_is_visible(m))),
        "ApproximateNumberOfMessagesNotVisible": str(sum(1 for m in queue.get("messages", []) if not m.get("deleted") and m.get("in_flight"))),
        "VisibilityTimeout": str(int(queue.get("visibility_timeout", 30) or 30)),
        "CreatedTimestamp": str(_sqs_timestamp(queue.get("created"))),
        "LastModifiedTimestamp": str(_sqs_timestamp(queue.get("last_modified"))),
        "DelaySeconds": str(int(queue.get("delay_seconds", 0) or 0)),
        "ReceiveMessageWaitTimeSeconds": str(int(queue.get("receive_wait_time_seconds", 0) or 0)),
        "MessageRetentionPeriod": str(int(queue.get("message_retention_period", 345600) or 345600)),
        "MaximumMessageSize": str(int(queue.get("max_message_size", 262144) or 262144)),
        "QueueArn": queue.get("queue_arn", _sqs_queue_arn(queue.get("queue_name", ""))),
        "FifoQueue": "true" if queue.get("fifo_queue") else "false",
        "ContentBasedDeduplication": "true" if queue.get("content_based_deduplication") else "false",
    }
    redrive_policy = queue.get("redrive_policy") or {}
    if redrive_policy:
        attrs["RedrivePolicy"] = json.dumps(redrive_policy, separators=(",", ":"), default=str)
    return attrs


def _sqs_queue_view(queue: dict, include_messages: bool = True) -> dict:
    queue = _sqs_normalize_queue(queue)
    _sqs_sweep_queue(queue)
    view = copy.deepcopy(queue)
    view["queue_url"] = queue.get("queue_url") or _sqs_queue_url(queue["queue_name"])
    view["queue_arn"] = queue.get("queue_arn") or _sqs_queue_arn(queue["queue_name"])
    view["attributes"] = _sqs_queue_attributes(queue)
    view["message_count"] = len(queue.get("messages", []))
    view["visible_message_count"] = sum(1 for m in queue.get("messages", []) if not m.get("deleted") and not m.get("in_flight") and _sqs_message_is_visible(m))
    view["in_flight_count"] = sum(1 for m in queue.get("messages", []) if not m.get("deleted") and m.get("in_flight"))
    view["messages"] = [_sqs_view_message(queue, message) for message in queue.get("messages", []) if include_messages and not message.get("deleted")]
    if not include_messages:
        view["messages"] = []
    return view


def _sqs_queue_list_view(queue: dict) -> dict:
    view = _sqs_queue_view(queue, include_messages=False)
    view["latest_message_at"] = max((m.get("sent_at", "") for m in queue.get("messages", []) if m.get("sent_at")), default="")
    return view


def _sqs_redrive_queue_name(queue: dict) -> str:
    policy = queue.get("redrive_policy") or {}
    target = policy.get("deadLetterTargetArn") or policy.get("deadLetterTargetQueueArn") or ""
    if ":queue/" in target:
        return target.rsplit(":", 1)[-1]
    if ":sqs:" in target:
        return target.rsplit(":", 1)[-1]
    return ""


def _sqs_enqueue_message(queue: dict, body: str, attributes: dict | None = None, message_attributes: dict | None = None, group_id: str = "", dedup_id: str = "", source: str = "") -> dict:
    queue = _sqs_normalize_queue(queue)
    _sqs_sweep_queue(queue)
    body = body if isinstance(body, str) else json.dumps(body, default=str)
    if len(body.encode("utf-8")) > int(queue.get("max_message_size", 262144) or 262144):
        raise HTTPException(400, detail="InvalidParameterValue: message body exceeds MaximumMessageSize.")
    if queue.get("fifo_queue") and not group_id:
        raise HTTPException(400, detail="MissingParameter: MessageGroupId is required for FIFO queues.")
    dedup_key = _sqs_dedup_key(queue, body, dedup_id)
    if queue.get("fifo_queue") and dedup_key:
        dedup_window_start = datetime.now(timezone.utc) - timedelta(minutes=5)
        for existing in reversed(queue.get("messages", [])):
            if existing.get("dedup_id") == dedup_key:
                sent_at = existing.get("sent_at", "")
                parsed_sent = _parse_ts(sent_at)
                if parsed_sent and parsed_sent >= dedup_window_start:
                    return existing
    message = {
        "message_id": _id_gen("msg"),
        "body": body,
        "attributes": copy.deepcopy(attributes or {}),
        "message_attributes": copy.deepcopy(message_attributes or {}),
        "md5_of_body": hashlib.md5(body.encode("utf-8")).hexdigest(),
        "sent_at": _now(),
        "visible_at": _now(),
        "receive_count": 0,
        "receipt_handle": "",
        "in_flight": False,
        "deleted": False,
        "group_id": group_id,
        "dedup_id": dedup_key,
        "sequence_number": str(len(queue.get("messages", [])) + 1),
        "source": source,
    }
    delay = int(queue.get("delay_seconds", 0) or 0)
    if delay > 0:
        message["visible_at"] = (datetime.now(timezone.utc) + timedelta(seconds=delay)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    queue.setdefault("messages", []).append(message)
    queue["last_modified"] = _now()
    _persist_state()
    return message


def _sqs_create_queue_record(req) -> dict:
    queue_name = _sqs_queue_key(req.queue_name)
    _sqs_validate_queue_name(queue_name)
    if _sqs_find_queue(queue_name):
        raise HTTPException(409, detail="QueueAlreadyExists")
    fifo = bool(req.fifo_queue or queue_name.endswith(".fifo"))
    if fifo and not queue_name.endswith(".fifo"):
        queue_name = f"{queue_name}.fifo"
    queue = {
        "queue_name": queue_name,
        "queue_url": _sqs_queue_url(queue_name),
        "queue_arn": _sqs_queue_arn(queue_name),
        "queue_type": "fifo" if fifo else "standard",
        "fifo_queue": fifo,
        "content_based_deduplication": bool(req.content_based_deduplication),
        "visibility_timeout": max(0, int(req.visibility_timeout or 30)),
        "receive_wait_time_seconds": max(0, int(req.receive_wait_time_seconds or 0)),
        "message_retention_period": max(60, int(req.message_retention_period or 345600)),
        "max_message_size": max(1024, int(req.max_message_size or 262144)),
        "delay_seconds": max(0, int(req.delay_seconds or 0)),
        "redrive_policy": copy.deepcopy(req.redrive_policy or {}),
        "tags": copy.deepcopy(req.tags or {}),
        "attributes": {},
        "messages": [],
        "created": _now(),
        "last_modified": _now(),
    }
    if queue["redrive_policy"] and not isinstance(queue["redrive_policy"], dict):
        raise HTTPException(400, detail="InvalidParameterValue: redrive_policy must be an object.")
    _sqs_set_queue(queue)
    _record_usage("sqs.create_queue", {"queue_name": queue["queue_name"]})
    return queue


def _sqs_queue_from_name_or_url(name_or_url: str) -> dict | None:
    if not name_or_url:
        return None
    if name_or_url.startswith("http://") or name_or_url.startswith("https://"):
        if "/queues/" in name_or_url:
            candidate = name_or_url.rsplit("/queues/", 1)[-1]
            return _sqs_find_queue(candidate)
    if ":queue/" in name_or_url:
        candidate = name_or_url.rsplit(":", 1)[-1]
        return _sqs_find_queue(candidate)
    return _sqs_find_queue(name_or_url)


def _sqs_get_queue(queue_name: str) -> dict:
    queue = _sqs_find_queue(queue_name)
    if not queue:
        raise HTTPException(404, detail="AWS.SimpleQueueService.NonExistentQueue")
    return _sqs_queue_view(queue)


def _sqs_update_queue_attributes(queue: dict, payload: dict) -> dict:
    queue = _sqs_normalize_queue(queue)
    if "VisibilityTimeout" in payload:
        queue["visibility_timeout"] = max(0, int(payload.get("VisibilityTimeout", queue["visibility_timeout"])))
    if "ReceiveMessageWaitTimeSeconds" in payload:
        queue["receive_wait_time_seconds"] = max(0, int(payload.get("ReceiveMessageWaitTimeSeconds", queue["receive_wait_time_seconds"])))
    if "MessageRetentionPeriod" in payload:
        queue["message_retention_period"] = max(60, int(payload.get("MessageRetentionPeriod", queue["message_retention_period"])))
    if "MaximumMessageSize" in payload:
        queue["max_message_size"] = max(1024, int(payload.get("MaximumMessageSize", queue["max_message_size"])))
    if "DelaySeconds" in payload:
        queue["delay_seconds"] = max(0, int(payload.get("DelaySeconds", queue["delay_seconds"])))
    if "RedrivePolicy" in payload:
        redrive = payload.get("RedrivePolicy") or {}
        if isinstance(redrive, str):
            try:
                redrive = json.loads(redrive)
            except Exception:
                raise HTTPException(400, detail="InvalidParameterValue: RedrivePolicy must be JSON.")
        queue["redrive_policy"] = copy.deepcopy(redrive or {})
    if "ContentBasedDeduplication" in payload:
        queue["content_based_deduplication"] = str(payload.get("ContentBasedDeduplication")).lower() == "true"
    queue["last_modified"] = _now()
    _persist_state()
    return queue


def _sqs_delete_queue(queue_name: str) -> None:
    queue = _sqs_find_queue(queue_name)
    if not queue:
        raise HTTPException(404, detail="AWS.SimpleQueueService.NonExistentQueue")
    _sqs_state().setdefault("queues", {}).pop(queue["queue_name"], None)
    _record_usage("sqs.delete_queue", {"queue_name": queue["queue_name"]})


def _sqs_extract_messages_for_delivery(queue: dict, max_messages: int) -> list[dict]:
    queue = _sqs_normalize_queue(queue)
    _sqs_sweep_queue(queue)
    now = datetime.now(timezone.utc)
    available = []
    group_locks: set[str] = set()
    for message in queue.get("messages", []):
        if message.get("deleted") or message.get("in_flight") or not _sqs_message_is_visible(message):
            continue
        if queue.get("fifo_queue"):
            group_id = message.get("group_id", "") or "__default__"
            if group_id in group_locks:
                continue
            if _sqs_message_is_blocked_by_fifo(queue, message):
                continue
            group_locks.add(group_id)
        available.append(message)
        if len(available) >= max_messages:
            break
    deliveries = []
    visibility = int(queue.get("visibility_timeout", 30) or 30)
    for message in available:
        message["receive_count"] = int(message.get("receive_count", 0) or 0) + 1
        redrive_policy = queue.get("redrive_policy") or {}
        max_receive = int(redrive_policy.get("maxReceiveCount", 0) or 0)
        if max_receive and message["receive_count"] > max_receive:
            dlq_name = _sqs_redrive_queue_name(queue)
            dlq = _sqs_find_queue(dlq_name) if dlq_name else None
            if dlq:
                _sqs_enqueue_message(dlq, message.get("body", ""), message.get("attributes", {}), message.get("message_attributes", {}), message.get("group_id", ""), message.get("dedup_id", ""), source=f"redrive:{queue['queue_name']}")
            message["deleted"] = True
            continue
        message["in_flight"] = True
        message["receipt_handle"] = _id_gen("rhdl")
        message["visible_at"] = (now + timedelta(seconds=visibility)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        deliveries.append(message)
    queue["last_modified"] = _now()
    _persist_state()
    return deliveries


def _sqs_delete_message(queue: dict, receipt_handle: str) -> bool:
    for message in queue.get("messages", []):
        if message.get("receipt_handle") == receipt_handle and message.get("in_flight"):
            message["deleted"] = True
            queue["messages"] = [m for m in queue.get("messages", []) if not m.get("deleted")]
            queue["last_modified"] = _now()
            _persist_state()
            return True
    return False


def _sqs_change_message_visibility(queue: dict, receipt_handle: str, visibility_timeout: int) -> bool:
    for message in queue.get("messages", []):
        if message.get("receipt_handle") == receipt_handle and message.get("in_flight"):
            message["visible_at"] = (datetime.now(timezone.utc) + timedelta(seconds=max(0, int(visibility_timeout)))).strftime("%Y-%m-%dT%H:%M:%S.000Z")
            queue["last_modified"] = _now()
            _persist_state()
            return True
    return False


def _sqs_purge_queue(queue: dict) -> None:
    queue["messages"] = []
    queue["last_modified"] = _now()
    _persist_state()


def _sqs_tags_view(queue: dict) -> dict:
    return copy.deepcopy(queue.get("tags", {}))


def _sqs_set_tags(queue: dict, tags: dict[str, str]) -> None:
    queue["tags"] = {str(k): str(v) for k, v in tags.items()}
    queue["last_modified"] = _now()
    _persist_state()


def _sqs_query_bool(value: str | None) -> bool:
    return str(value or "").lower() in {"true", "1", "yes", "on"}


def _req_id() -> str:
    return uuid.uuid4().hex.upper()[:16]


def _fmt_size(n: int) -> str:
    orig = float(n)
    for unit in ["B", "KB", "MB", "GB"]:
        if orig < 1024:
            return f"{orig:.1f} {unit}"
        orig /= 1024
    return f"{orig:.1f} TB"


def _ddb_state() -> dict:
    return _ddb_state_proxy


def _ddb_tables() -> dict:
    return _ddb_state().setdefault("tables", {})


def _ddb_table_arn(table_name: str) -> str:
    return f"arn:aws:dynamodb:us-east-1:{_aws_account_id()}:table/{table_name}"


def _ddb_is_typed_value(value: Any) -> bool:
    return isinstance(value, dict) and len(value) == 1 and next(iter(value.keys())) in {"S", "N", "BOOL", "NULL", "M", "L", "SS", "NS", "BS", "B"}


def _ddb_json_to_native(value: Any) -> Any:
    if isinstance(value, dict):
        if _ddb_is_typed_value(value):
            type_key, raw = next(iter(value.items()))
            if type_key == "S":
                return str(raw)
            if type_key == "N":
                raw_text = str(raw)
                try:
                    return int(raw_text) if re.fullmatch(r"-?\d+", raw_text) else float(raw_text)
                except Exception:
                    return raw_text
            if type_key == "BOOL":
                return bool(raw)
            if type_key == "NULL":
                return None
            if type_key == "B":
                return raw
            if type_key == "SS":
                return [str(item) for item in (raw or [])]
            if type_key == "NS":
                values = []
                for item in raw or []:
                    try:
                        item_text = str(item)
                        values.append(int(item_text) if re.fullmatch(r"-?\d+", item_text) else float(item_text))
                    except Exception:
                        values.append(str(item))
                return values
            if type_key == "BS":
                return list(raw or [])
            if type_key == "L":
                return [_ddb_json_to_native(item) for item in (raw or [])]
            if type_key == "M":
                return {k: _ddb_json_to_native(v) for k, v in (raw or {}).items()}
        return {k: _ddb_json_to_native(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_ddb_json_to_native(v) for v in value]
    return copy.deepcopy(value)


def _ddb_native_to_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {"M": {k: _ddb_native_to_json(v) for k, v in value.items()}}
    if isinstance(value, list):
        if all(isinstance(item, str) for item in value):
            return {"SS": [str(item) for item in value]}
        if all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in value):
            return {"NS": [str(item) for item in value]}
        return {"L": [_ddb_native_to_json(item) for item in value]}
    if isinstance(value, bool):
        return {"BOOL": value}
    if value is None:
        return {"NULL": True}
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return {"N": str(value)}
    return {"S": str(value)}


def _ddb_native_item_to_json(item: dict[str, Any]) -> dict[str, Any]:
    return {k: _ddb_native_to_json(v) for k, v in (item or {}).items()}


def _ddb_item_to_native_item(item: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise HTTPException(400, detail="ValidationException: Item must be an object.")
    return {k: _ddb_json_to_native(v) for k, v in item.items()}


def _ddb_table_key_fields(table: dict) -> tuple[str, str]:
    return str(table.get("partition_key_name", "id")), str(table.get("sort_key_name", "") or "")


def _ddb_item_key_tuple(table: dict, item: dict[str, Any]) -> tuple[Any, Any | None]:
    pk_name, sk_name = _ddb_table_key_fields(table)
    if pk_name not in item:
        raise HTTPException(400, detail=f"ValidationException: Missing partition key '{pk_name}'.")
    pk = item.get(pk_name)
    sk = item.get(sk_name) if sk_name else None
    if sk_name and sk is None:
        raise HTTPException(400, detail=f"ValidationException: Missing sort key '{sk_name}'.")
    return pk, sk


def _ddb_item_key_string(table: dict, item: dict[str, Any]) -> str:
    return json.dumps(_ddb_item_key_tuple(table, item), default=str, separators=(",", ":"))


def _ddb_normalize_table(table_name: str, table: dict) -> dict:
    table.setdefault("table_name", table_name)
    table.setdefault("table_arn", _ddb_table_arn(table_name))
    table.setdefault("table_status", "ACTIVE")
    table.setdefault("partition_key_name", "id")
    table.setdefault("partition_key_type", "S")
    table.setdefault("sort_key_name", "")
    table.setdefault("sort_key_type", "S")
    table.setdefault("billing_mode", "PAY_PER_REQUEST")
    table.setdefault("provisioned_throughput", {"ReadCapacityUnits": 5, "WriteCapacityUnits": 5})
    table.setdefault("tags", {})
    table.setdefault("indexes", [])
    table.setdefault("streams", {"enabled": False, "latest_stream_label": ""})
    table.setdefault("items", {})
    table.setdefault("created", _now())
    table.setdefault("last_modified", _now())
    return table


def _ddb_find_table(table_name: str) -> dict | None:
    table = _ddb_tables().get(table_name)
    if isinstance(table, dict):
        return _ddb_normalize_table(table_name, table)
    return None


def _ddb_refresh_table_metrics(table: dict) -> None:
    records = list((table.get("items") or {}).values())
    table["item_count"] = len(records)
    try:
        table["table_size_bytes"] = sum(len(json.dumps(rec.get("item", {}), sort_keys=True, default=str).encode("utf-8")) for rec in records)
    except Exception:
        table["table_size_bytes"] = 0
    table["last_modified"] = _now()


def _ddb_item_record_view(table: dict, key: str, record: dict) -> dict:
    native = copy.deepcopy(record.get("item", {}))
    pk_name, sk_name = _ddb_table_key_fields(table)
    key_obj = {pk_name: native.get(pk_name)}
    if sk_name:
        key_obj[sk_name] = native.get(sk_name)
    return {
        "key": key_obj,
        "item": native,
        "item_json": _ddb_native_item_to_json(native),
        "created": record.get("created", ""),
        "updated": record.get("updated", ""),
        "size_bytes": int(record.get("size_bytes", 0) or 0),
        "size_human": _fmt_size(int(record.get("size_bytes", 0) or 0)),
    }


def _ddb_table_view(table: dict, include_items: bool = True, native_items: bool = True) -> dict:
    table = _ddb_normalize_table(table.get("table_name", ""), table)
    _ddb_refresh_table_metrics(table)
    records = sorted((table.get("items") or {}).items(), key=lambda kv: json.dumps(_ddb_item_key_tuple(table, kv[1].get("item", {})), default=str))
    view = {
        "table_name": table.get("table_name", ""),
        "table_arn": table.get("table_arn", ""),
        "table_status": table.get("table_status", "ACTIVE"),
        "partition_key_name": table.get("partition_key_name", "id"),
        "partition_key_type": table.get("partition_key_type", "S"),
        "sort_key_name": table.get("sort_key_name", ""),
        "sort_key_type": table.get("sort_key_type", "S"),
        "billing_mode": table.get("billing_mode", "PAY_PER_REQUEST"),
        "provisioned_throughput": copy.deepcopy(table.get("provisioned_throughput", {})),
        "tags": copy.deepcopy(table.get("tags", {})),
        "indexes": copy.deepcopy(table.get("indexes", [])),
        "streams": copy.deepcopy(table.get("streams", {"enabled": False, "latest_stream_label": ""})),
        "created": table.get("created", ""),
        "last_modified": table.get("last_modified", ""),
        "item_count": int(table.get("item_count", 0) or 0),
        "table_size_bytes": int(table.get("table_size_bytes", 0) or 0),
        "table_size_human": _fmt_size(int(table.get("table_size_bytes", 0) or 0)),
    }
    if include_items:
        items = [_ddb_item_record_view(table, key, record) for key, record in records]
        view["items"] = [item["item"] if native_items else item["item_json"] for item in items]
        view["item_rows"] = items
    return view


def _ddb_create_table_record(payload: dict[str, Any]) -> dict:
    table_name = str(payload.get("table_name") or payload.get("TableName") or "").strip()
    if not table_name:
        raise HTTPException(400, detail="ValidationException: TableName is required.")
    tables = _ddb_tables()
    if table_name in tables:
        raise HTTPException(409, detail="ResourceInUseException: Table already exists.")
    pk_name = str(payload.get("partition_key_name") or payload.get("PartitionKeyName") or "id").strip() or "id"
    pk_type = str(payload.get("partition_key_type") or payload.get("PartitionKeyType") or "S").strip().upper() or "S"
    sk_name = str(payload.get("sort_key_name") or payload.get("SortKeyName") or "").strip()
    sk_type = str(payload.get("sort_key_type") or payload.get("SortKeyType") or "S").strip().upper() or "S"
    billing_mode = str(payload.get("billing_mode") or payload.get("BillingMode") or "PAY_PER_REQUEST").strip().upper() or "PAY_PER_REQUEST"
    throughput = payload.get("provisioned_throughput") or payload.get("ProvisionedThroughput") or {}
    tags = payload.get("tags") or payload.get("Tags") or {}
    if isinstance(tags, list):
        tags = {str(tag.get("Key", tag.get("key", ""))): str(tag.get("Value", tag.get("value", ""))) for tag in tags if isinstance(tag, dict)}
    table = {
        "table_name": table_name,
        "table_arn": _ddb_table_arn(table_name),
        "table_status": "ACTIVE",
        "partition_key_name": pk_name,
        "partition_key_type": pk_type,
        "sort_key_name": sk_name,
        "sort_key_type": sk_type,
        "billing_mode": billing_mode,
        "provisioned_throughput": {
            "ReadCapacityUnits": int(throughput.get("ReadCapacityUnits", payload.get("read_capacity_units", 5)) or 5),
            "WriteCapacityUnits": int(throughput.get("WriteCapacityUnits", payload.get("write_capacity_units", 5)) or 5),
        },
        "tags": copy.deepcopy(tags or {}),
        "indexes": [],
        "streams": {"enabled": False, "latest_stream_label": ""},
        "items": {},
        "created": _now(),
        "last_modified": _now(),
    }
    table["attribute_definitions"] = [{"AttributeName": pk_name, "AttributeType": pk_type}]
    table["key_schema"] = [{"AttributeName": pk_name, "KeyType": "HASH"}]
    if sk_name:
        table["attribute_definitions"].append({"AttributeName": sk_name, "AttributeType": sk_type})
        table["key_schema"].append({"AttributeName": sk_name, "KeyType": "RANGE"})
    tables[table_name] = table
    _persist_state()
    _record_usage("dynamodb.create_table", {"table_name": table_name})
    return table


def _ddb_delete_table_record(table_name: str) -> None:
    tables = _ddb_tables()
    if table_name not in tables:
        raise HTTPException(404, detail="ResourceNotFoundException: Table not found.")
    tables.pop(table_name, None)
    _persist_state()
    _record_usage("dynamodb.delete_table", {"table_name": table_name})


def _ddb_put_item_record(table: dict, payload: dict[str, Any]) -> dict:
    native_item = _ddb_item_to_native_item(payload.get("item") or payload.get("Item") or {})
    key = _ddb_item_key_string(table, native_item)
    items = table.setdefault("items", {})
    existing = items.get(key)
    items[key] = {
        "item": native_item,
        "created": existing.get("created", _now()) if existing else _now(),
        "updated": _now(),
        "size_bytes": len(json.dumps(native_item, sort_keys=True, default=str).encode("utf-8")),
    }
    _ddb_refresh_table_metrics(table)
    _persist_state()
    _record_usage("dynamodb.put_item", {"table_name": table["table_name"]})
    return existing or {}


def _ddb_get_item_record(table: dict, payload: dict[str, Any]) -> dict | None:
    native_key = _ddb_item_to_native_item(payload.get("key") or payload.get("Key") or {})
    key = _ddb_item_key_string(table, native_key)
    return table.get("items", {}).get(key)


def _ddb_delete_item_record(table: dict, payload: dict[str, Any]) -> dict:
    native_key = _ddb_item_to_native_item(payload.get("key") or payload.get("Key") or {})
    key = _ddb_item_key_string(table, native_key)
    removed = table.get("items", {}).pop(key, None)
    _ddb_refresh_table_metrics(table)
    _persist_state()
    _record_usage("dynamodb.delete_item", {"table_name": table["table_name"]})
    return removed or {}


def _ddb_update_item_record(table: dict, payload: dict[str, Any]) -> dict:
    native_key = _ddb_item_to_native_item(payload.get("key") or payload.get("Key") or {})
    key = _ddb_item_key_string(table, native_key)
    current = copy.deepcopy(table.get("items", {}).get(key, {}).get("item", {}))
    updates = payload.get("attribute_updates") or payload.get("AttributeUpdates") or {}
    if not current:
        current = copy.deepcopy(native_key)
    if updates:
        for name, spec in updates.items():
            if not isinstance(spec, dict):
                continue
            action = str(spec.get("Action", "PUT")).upper()
            value = spec.get("Value")
            if action == "DELETE":
                current.pop(name, None)
            elif value is not None:
                current[name] = _ddb_json_to_native(value)
    else:
        expr = str(payload.get("update_expression") or payload.get("UpdateExpression") or "").strip()
        values = payload.get("expression_attribute_values") or payload.get("ExpressionAttributeValues") or {}
        if expr.upper().startswith("SET "):
            for clause in expr[4:].split(","):
                if "=" not in clause:
                    continue
                left, right = clause.split("=", 1)
                attr_name = left.strip()
                token = right.strip()
                current[attr_name] = _ddb_json_to_native(values.get(token, token))
    items = table.setdefault("items", {})
    items[key] = {
        "item": current,
        "created": items.get(key, {}).get("created", _now()),
        "updated": _now(),
        "size_bytes": len(json.dumps(current, sort_keys=True, default=str).encode("utf-8")),
    }
    _ddb_refresh_table_metrics(table)
    _persist_state()
    _record_usage("dynamodb.update_item", {"table_name": table["table_name"]})
    return items[key]


def _ddb_sort_key(table: dict, native_item: dict[str, Any]) -> tuple[str, str]:
    pk_name, sk_name = _ddb_table_key_fields(table)
    return (str(native_item.get(pk_name, "")), str(native_item.get(sk_name, "")) if sk_name else "")


def _ddb_sorted_records(table: dict) -> list[dict]:
    records = list((table.get("items") or {}).values())
    records.sort(key=lambda rec: _ddb_sort_key(table, rec.get("item", {})))
    return records


def _ddb_expr_value(raw: Any) -> Any:
    return _ddb_json_to_native(raw)


def _ddb_query_filter(table: dict, payload: dict[str, Any]) -> tuple[list[dict], int]:
    records = _ddb_sorted_records(table)
    if not records:
        return [], 0
    pk_name, sk_name = _ddb_table_key_fields(table)
    pk_value = payload.get("partition_key_value")
    sk_equals = payload.get("sort_key_equals")
    sk_begins = str(payload.get("sort_key_begins_with") or "")
    sk_between = payload.get("sort_key_between") or []
    expr = str(payload.get("key_condition_expression") or payload.get("KeyConditionExpression") or "").strip()
    names = payload.get("expression_attribute_names") or payload.get("ExpressionAttributeNames") or {}
    values = payload.get("expression_attribute_values") or payload.get("ExpressionAttributeValues") or {}
    if expr:
        for alias, actual in (names or {}).items():
            expr = expr.replace(str(alias), str(actual))
        if pk_value is None:
            m = re.search(rf"\b{re.escape(pk_name)}\s*=\s*(:\w+)", expr, flags=re.I)
            if m:
                pk_value = _ddb_expr_value(values.get(m.group(1)))
        if sk_name and not sk_equals and not sk_begins and not sk_between:
            m = re.search(rf"\b{re.escape(sk_name)}\s*=\s*(:\w+)", expr, flags=re.I)
            if m:
                sk_equals = _ddb_expr_value(values.get(m.group(1)))
            m = re.search(rf"begins_with\s*\(\s*{re.escape(sk_name)}\s*,\s*(:\w+)\s*\)", expr, flags=re.I)
            if m:
                sk_begins = str(_ddb_expr_value(values.get(m.group(1))) or "")
            m = re.search(rf"\b{re.escape(sk_name)}\s+BETWEEN\s+(:\w+)\s+AND\s+(:\w+)", expr, flags=re.I)
            if m:
                sk_between = [_ddb_expr_value(values.get(m.group(1))), _ddb_expr_value(values.get(m.group(2)))]
    matched = []
    for rec in records:
        item = rec.get("item", {})
        if pk_value is not None and item.get(pk_name) != pk_value:
            continue
        if sk_name:
            current_sk = item.get(sk_name)
            if sk_equals is not None and current_sk != sk_equals:
                continue
            if sk_begins and not str(current_sk or "").startswith(sk_begins):
                continue
            if isinstance(sk_between, list) and len(sk_between) == 2:
                low, high = sk_between
                if not (str(low) <= str(current_sk) <= str(high)):
                    continue
        matched.append(rec)
    limit = max(1, min(int(payload.get("limit") or payload.get("Limit") or 100), 1000))
    return matched[:limit], len(matched)


def _ddb_scan_filter(table: dict, payload: dict[str, Any]) -> tuple[list[dict], int]:
    records = _ddb_sorted_records(table)
    limit = max(1, min(int(payload.get("limit") or payload.get("Limit") or 100), 1000))
    return records[:limit], len(records)


def _ddb_table_response(table: dict, include_items: bool = True) -> dict:
    view = _ddb_table_view(table, include_items=include_items, native_items=True)
    if include_items:
        view["items"] = [copy.deepcopy(item["item"]) for item in view.get("item_rows", [])]
    return {"table": view}


def _ddb_list_tables_response() -> dict:
    tables = [_ddb_table_view(table, include_items=False) for _, table in sorted(_ddb_tables().items(), key=lambda kv: kv[0])]
    return {"table_names": [table["table_name"] for table in tables], "tables": tables, "count": len(tables)}


def _ddb_tags_view(table: dict) -> dict[str, str]:
    tags = table.setdefault("tags", {})
    if isinstance(tags, list):
        tags = {str(tag.get("Key", "")): str(tag.get("Value", "")) for tag in tags if isinstance(tag, dict)}
        table["tags"] = tags
    return copy.deepcopy(tags)


def _ddb_set_tags(table: dict, tags: dict[str, str]) -> None:
    table["tags"] = {str(k): str(v) for k, v in (tags or {}).items()}
    table["last_modified"] = _now()
    _persist_state()


def _ddb_json_response(payload: dict[str, Any], status: int = 200) -> Response:
    return JSONResponse(status_code=status, content=payload, headers={"x-amzn-requestid": _req_id()})


def _ddb_error_response(code: str, message: str, status: int = 400) -> Response:
    return _ddb_json_response({"__type": code, "message": message}, status=status)


async def _ddb_api_aws(request: Request):
    target = request.headers.get("x-amz-target", "")
    action = target.rsplit(".", 1)[-1] if target else ""
    if not action:
        return _ddb_error_response("MissingAction", "The request must include X-Amz-Target.", 400)
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    payload = payload if isinstance(payload, dict) else {}

    def table_name_from_payload() -> str:
        return str(payload.get("TableName") or payload.get("table_name") or "").strip()

    if action == "ListTables":
        return _ddb_json_response(_ddb_list_tables_response())
    if action == "CreateTable":
        table = _ddb_create_table_record(payload)
        return _ddb_json_response({"TableDescription": _ddb_table_view(table, include_items=False)})
    if action == "DescribeTable":
        table = _ddb_find_table(table_name_from_payload())
        if not table:
            return _ddb_error_response("ResourceNotFoundException", f"Table {table_name_from_payload()} not found.", 404)
        return _ddb_json_response({"Table": _ddb_table_view(table, include_items=True)})
    if action == "DeleteTable":
        name = table_name_from_payload()
        _ddb_delete_table_record(name)
        return _ddb_json_response({"TableDescription": {"TableName": name, "TableStatus": "DELETED"}})
    if action == "PutItem":
        table = _ddb_find_table(table_name_from_payload())
        if not table:
            return _ddb_error_response("ResourceNotFoundException", "Table not found.", 404)
        old = _ddb_put_item_record(table, payload)
        return _ddb_json_response({"Attributes": _ddb_native_item_to_json(copy.deepcopy(old.get("item", {}))) if old and payload.get("ReturnValues", "NONE").upper() in {"ALL_OLD", "UPDATED_OLD"} else {}})
    if action == "GetItem":
        table = _ddb_find_table(table_name_from_payload())
        if not table:
            return _ddb_error_response("ResourceNotFoundException", "Table not found.", 404)
        record = _ddb_get_item_record(table, payload)
        return _ddb_json_response({"Item": _ddb_native_item_to_json(record.get("item", {}))} if record else {})
    if action == "DeleteItem":
        table = _ddb_find_table(table_name_from_payload())
        if not table:
            return _ddb_error_response("ResourceNotFoundException", "Table not found.", 404)
        removed = _ddb_delete_item_record(table, payload)
        return _ddb_json_response({"Attributes": _ddb_native_item_to_json(removed.get("item", {}))} if removed else {})
    if action == "UpdateItem":
        table = _ddb_find_table(table_name_from_payload())
        if not table:
            return _ddb_error_response("ResourceNotFoundException", "Table not found.", 404)
        updated = _ddb_update_item_record(table, payload)
        return _ddb_json_response({"Attributes": _ddb_native_item_to_json(updated.get("item", {}))})
    if action == "Query":
        table = _ddb_find_table(table_name_from_payload())
        if not table:
            return _ddb_error_response("ResourceNotFoundException", "Table not found.", 404)
        matched, scanned = _ddb_query_filter(table, payload)
        return _ddb_json_response({"Items": [_ddb_native_item_to_json(rec.get("item", {})) for rec in matched], "Count": len(matched), "ScannedCount": scanned})
    if action == "Scan":
        table = _ddb_find_table(table_name_from_payload())
        if not table:
            return _ddb_error_response("ResourceNotFoundException", "Table not found.", 404)
        matched, scanned = _ddb_scan_filter(table, payload)
        return _ddb_json_response({"Items": [_ddb_native_item_to_json(rec.get("item", {})) for rec in matched], "Count": len(matched), "ScannedCount": scanned})
    if action == "BatchGetItem":
        responses = {}
        request_items = payload.get("RequestItems") or {}
        for tname, req in request_items.items():
            table = _ddb_find_table(str(tname))
            if not table:
                continue
            keys = req.get("Keys") or []
            rows = []
            for key in keys:
                record = _ddb_get_item_record(table, {"key": key})
                if record:
                    rows.append(_ddb_native_item_to_json(record.get("item", {})))
            responses[tname] = rows
        return _ddb_json_response({"Responses": responses})
    if action == "BatchWriteItem":
        request_items = payload.get("RequestItems") or {}
        for tname, ops in request_items.items():
            table = _ddb_find_table(str(tname))
            if not table:
                continue
            for op in ops or []:
                if "PutRequest" in op:
                    _ddb_put_item_record(table, {"item": op["PutRequest"].get("Item", {})})
                elif "DeleteRequest" in op:
                    _ddb_delete_item_record(table, {"key": op["DeleteRequest"].get("Key", {})})
        return _ddb_json_response({"UnprocessedItems": {}})
    if action == "TagResource":
        table = _ddb_find_table(table_name_from_payload())
        if not table:
            return _ddb_error_response("ResourceNotFoundException", "Table not found.", 404)
        tags = payload.get("Tags") or payload.get("tags") or {}
        if isinstance(tags, list):
            tags = {str(tag.get("Key", "")): str(tag.get("Value", "")) for tag in tags if isinstance(tag, dict)}
        _ddb_set_tags(table, tags if isinstance(tags, dict) else {})
        return _ddb_json_response({})
    if action == "UntagResource":
        table = _ddb_find_table(table_name_from_payload())
        if not table:
            return _ddb_error_response("ResourceNotFoundException", "Table not found.", 404)
        keys = payload.get("TagKeys") or payload.get("tag_keys") or []
        tags = _ddb_tags_view(table)
        for key in keys:
            tags.pop(str(key), None)
        _ddb_set_tags(table, tags)
        return _ddb_json_response({})
    if action == "ListTagsOfResource":
        table = _ddb_find_table(table_name_from_payload())
        if not table:
            return _ddb_error_response("ResourceNotFoundException", "Table not found.", 404)
        return _ddb_json_response({"Tags": [{"Key": k, "Value": v} for k, v in _ddb_tags_view(table).items()]})
    if action == "DescribeStream":
        stream_arn = payload.get("StreamArn", "")
        # Find table by stream ARN
        target_table = None
        for tname, tbl in _ddb_tables().items():
            tbl = _ddb_find_table(tname)
            if tbl and tbl.get("streams", {}).get("stream_arn") == stream_arn:
                target_table = tbl
                break
        if not target_table:
            return _ddb_error_response("ResourceNotFoundException", "Stream not found.", 404)
        streams = target_table.get("streams", {})
        stream_desc = {
            "StreamArn": streams.get("stream_arn", ""),
            "StreamLabel": streams.get("latest_stream_label", ""),
            "StreamStatus": "ENABLED" if streams.get("enabled") else "DISABLED",
            "StreamViewType": streams.get("stream_view_type", "NEW_AND_OLD_IMAGES"),
            "TableName": target_table.get("table_name", ""),
            "KeySchema": target_table.get("key_schema", []),
            "Shards": [
                {
                    "ShardId": "shardId-00000001",
                    "SequenceNumberRange": {
                        "StartingSequenceNumber": "000000000000000000001",
                    },
                }
            ],
        }
        return _ddb_json_response({"StreamDescription": stream_desc})

    if action == "GetShardIterator":
        stream_arn = payload.get("StreamArn", "")
        shard_id = payload.get("ShardId", "")
        iterator_type = payload.get("ShardIteratorType", "TRIM_HORIZON")
        # Encode the stream ARN and position into the iterator
        import base64
        iterator_data = json.dumps({"stream_arn": stream_arn, "shard_id": shard_id, "type": iterator_type, "position": 0})
        shard_iterator = base64.b64encode(iterator_data.encode()).decode()
        return _ddb_json_response({"ShardIterator": shard_iterator})

    if action == "GetRecords":
        shard_iterator = payload.get("ShardIterator", "")
        limit = min(int(payload.get("Limit", 1000)), 1000)
        import base64
        try:
            iterator_data = json.loads(base64.b64decode(shard_iterator).decode())
        except Exception:
            return _ddb_error_response("TrimmedDataAccessException", "Invalid shard iterator.", 400)
        stream_arn = iterator_data.get("stream_arn", "")
        position = int(iterator_data.get("position", 0))
        # Find table
        target_table = None
        for tname, tbl in _ddb_tables().items():
            tbl = _ddb_find_table(tname)
            if tbl and tbl.get("streams", {}).get("stream_arn") == stream_arn:
                target_table = tbl
                break
        if not target_table:
            return _ddb_json_response({"Records": [], "NextShardIterator": None})
        all_records = target_table.get("stream_records", [])
        page = all_records[position:position + limit]
        next_position = position + len(page)
        next_iterator = None
        if next_position < len(all_records):
            next_data = json.dumps({"stream_arn": stream_arn, "shard_id": iterator_data.get("shard_id", ""), "type": "AT_SEQUENCE_NUMBER", "position": next_position})
            next_iterator = base64.b64encode(next_data.encode()).decode()
        return _ddb_json_response({"Records": page, "NextShardIterator": next_iterator})

    if action == "ListStreams":
        table_name = payload.get("TableName", "")
        streams_list = []
        for tname, tbl in _ddb_tables().items():
            if table_name and tname != table_name:
                continue
            tbl = _ddb_find_table(tname)
            if tbl and tbl.get("streams", {}).get("enabled"):
                streams_list.append({
                    "StreamArn": tbl["streams"].get("stream_arn", ""),
                    "StreamLabel": tbl["streams"].get("latest_stream_label", ""),
                    "TableName": tname,
                })
        return _ddb_json_response({"Streams": streams_list})

    return _ddb_error_response("UnknownOperationException", f"The action {action} is not implemented.", 400)


TARGETS = [
    "api_sqs_query",
    "api_sqs_list_queues",
    "api_sqs_create_queue",
    "api_sqs_get_queue",
    "api_sqs_update_queue",
    "api_sqs_delete_queue",
    "api_sqs_list_messages",
    "api_sqs_send_message",
    "api_sqs_receive_message",
    "api_sqs_delete_message",
    "api_sqs_change_visibility",
    "api_sqs_purge",
    "api_sqs_list_tags",
    "api_sqs_tag_queue",
    "api_sqs_untag_queue",
    "api_dynamodb_aws",
    "api_dynamodb_list_tables",
    "api_dynamodb_create_table",
    "api_dynamodb_get_table",
    "api_dynamodb_delete_table",
    "api_dynamodb_list_items",
    "api_dynamodb_put_item",
    "api_dynamodb_update_item",
    "api_dynamodb_delete_item",
    "api_dynamodb_query_items",
    "api_dynamodb_scan_items",
    "api_dynamodb_list_tags",
    "api_dynamodb_tag_table",
    "api_dynamodb_untag_table",
    "api_apigateway_list_apis",
    "api_apigateway_create_api",
    "api_apigateway_get_api",
    "api_apigateway_delete_api",
    "api_apigateway_list_resources",
    "api_apigateway_create_resource",
    "api_apigateway_put_method",
    "api_apigateway_put_integration",
    "api_apigateway_create_deployment",
    "api_apigateway_list_deployments",
    "api_apigateway_create_stage",
    "api_apigateway_list_stages",
    "api_apigateway_list_logs",
    "api_apigateway_invoke_path",
    "api_apigateway_invoke_root",
    "api_lambda_list_functions",
    "api_lambda_create_function",
    "api_lambda_get_function",
    "api_lambda_update_function_code",
    "api_lambda_update_function_configuration",
    "api_lambda_delete_function",
    "api_lambda_get_policy",
    "api_lambda_add_permission",
    "api_lambda_remove_permission",
    "api_lambda_list_invocations",
    "api_lambda_list_versions",
    "api_lambda_publish_version",
    "api_lambda_invoke_function",
    "api_lambda_list_functions_aws",
    "api_lambda_create_function_aws",
    "api_lambda_get_function_aws",
    "api_lambda_delete_function_aws",
    "api_lambda_get_policy_aws",
    "api_lambda_add_permission_aws",
    "api_lambda_remove_permission_aws",
    "api_lambda_update_function_code_aws",
    "api_lambda_update_function_configuration_aws",
    "api_lambda_publish_version_aws",
    "api_lambda_list_versions_aws",
    "api_lambda_invoke_function_aws",
]


async def api_sqs_query(request: Request):
    return await _server().api_sqs_query(request)


def api_sqs_list_queues():
    queues = [_sqs_queue_list_view(queue) for queue in _sqs_list_queues()]
    return {"queues": queues, "count": len(queues)}


def api_sqs_create_queue(req):
    return _sqs_queue_view(_sqs_create_queue_record(req))


def api_sqs_get_queue(queue_name: str):
    queue = _sqs_find_queue(queue_name)
    if not queue:
        raise HTTPException(404, detail="QueueNotFound")
    return _sqs_queue_view(queue)


def api_sqs_update_queue(queue_name: str, req):
    queue = _sqs_find_queue(queue_name)
    if not queue:
        raise HTTPException(404, detail="QueueNotFound")
    payload = {
        "VisibilityTimeout": req.visibility_timeout,
        "ReceiveMessageWaitTimeSeconds": req.receive_wait_time_seconds,
        "MessageRetentionPeriod": req.message_retention_period,
        "MaximumMessageSize": req.max_message_size,
        "DelaySeconds": req.delay_seconds,
        "ContentBasedDeduplication": req.content_based_deduplication,
        "RedrivePolicy": req.redrive_policy,
    }
    if req.tags is not None:
        queue["tags"] = dict(req.tags)
    _sqs_update_queue_attributes(queue, {k: v for k, v in payload.items() if v is not None})
    return _sqs_queue_view(queue)


def api_sqs_delete_queue(queue_name: str):
    _sqs_delete_queue(queue_name)
    return {"deleted": True, "queue_name": queue_name}


def api_sqs_list_messages(queue_name: str):
    queue = _sqs_find_queue(queue_name)
    if not queue:
        raise HTTPException(404, detail="QueueNotFound")
    return {
        "queue_name": queue["queue_name"],
        "messages": [_sqs_view_message(queue, msg) for msg in queue.get("messages", []) if not msg.get("deleted")],
        "count": len(queue.get("messages", [])),
    }


def api_sqs_send_message(queue_name: str, req):
    queue = _sqs_find_queue(queue_name)
    if not queue:
        raise HTTPException(404, detail="QueueNotFound")
    message = _sqs_enqueue_message(
        queue,
        req.message_body,
        req.message_attributes or req.message_attributes_map or {},
        req.message_attributes_map or {},
        req.message_group_id,
        req.message_deduplication_id,
        source="api_send_message",
    )
    return {"message": _sqs_view_message(queue, message), "queue_name": queue["queue_name"], "queue_url": queue.get("queue_url")}


def api_sqs_receive_message(queue_name: str, req):
    queue = _sqs_find_queue(queue_name)
    if not queue:
        raise HTTPException(404, detail="QueueNotFound")
    deliveries = _sqs_extract_messages_for_delivery(queue, max(1, min(int(req.max_number_of_messages or 1), 10)))
    if req.visibility_timeout is not None:
        for message in deliveries:
            message["visible_at"] = (datetime.now(timezone.utc) + timedelta(seconds=max(0, int(req.visibility_timeout)))).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    return {"queue_name": queue["queue_name"], "messages": [_sqs_view_message(queue, msg) for msg in deliveries], "count": len(deliveries)}


def api_sqs_delete_message(queue_name: str, receipt_handle: str):
    queue = _sqs_find_queue(queue_name)
    if not queue:
        raise HTTPException(404, detail="QueueNotFound")
    if not _sqs_delete_message(queue, receipt_handle):
        raise HTTPException(400, detail="ReceiptHandleIsInvalid")
    return {"deleted": True, "queue_name": queue["queue_name"], "receipt_handle": receipt_handle}


def api_sqs_change_visibility(queue_name: str, receipt_handle: str, req):
    queue = _sqs_find_queue(queue_name)
    if not queue:
        raise HTTPException(404, detail="QueueNotFound")
    if not _sqs_change_message_visibility(queue, receipt_handle, req.visibility_timeout):
        raise HTTPException(400, detail="ReceiptHandleIsInvalid")
    return {"updated": True, "queue_name": queue["queue_name"], "receipt_handle": receipt_handle, "visibility_timeout": req.visibility_timeout}


def api_sqs_purge(queue_name: str):
    queue = _sqs_find_queue(queue_name)
    if not queue:
        raise HTTPException(404, detail="QueueNotFound")
    _sqs_purge_queue(queue)
    return {"purged": True, "queue_name": queue["queue_name"]}


def api_sqs_list_tags(queue_name: str):
    queue = _sqs_find_queue(queue_name)
    if not queue:
        raise HTTPException(404, detail="QueueNotFound")
    return {"queue_name": queue["queue_name"], "tags": _sqs_tags_view(queue)}


def api_sqs_tag_queue(queue_name: str, payload: dict[str, str]):
    queue = _sqs_find_queue(queue_name)
    if not queue:
        raise HTTPException(404, detail="QueueNotFound")
    current = _sqs_tags_view(queue)
    current.update({str(k): str(v) for k, v in payload.items()})
    _sqs_set_tags(queue, current)
    return {"tagged": True, "queue_name": queue["queue_name"], "tags": _sqs_tags_view(queue)}


def api_sqs_untag_queue(queue_name: str, payload: dict[str, Any]):
    queue = _sqs_find_queue(queue_name)
    if not queue:
        raise HTTPException(404, detail="QueueNotFound")
    keys = payload.get("keys") if isinstance(payload, dict) else []
    current = _sqs_tags_view(queue)
    for key in keys or []:
        current.pop(str(key), None)
    _sqs_set_tags(queue, current)
    return {"untagged": True, "queue_name": queue["queue_name"], "tags": _sqs_tags_view(queue)}


async def api_dynamodb_aws(request: Request):
    return await _ddb_api_aws(request)


def api_dynamodb_list_tables():
    return _ddb_list_tables_response()


def api_dynamodb_create_table(req):
    table = _ddb_create_table_record(
        {
            "table_name": req.table_name,
            "partition_key_name": req.partition_key_name,
            "partition_key_type": req.partition_key_type,
            "sort_key_name": req.sort_key_name,
            "sort_key_type": req.sort_key_type,
            "billing_mode": req.billing_mode,
            "read_capacity_units": req.read_capacity_units,
            "write_capacity_units": req.write_capacity_units,
            "tags": req.tags or {},
        }
    )
    return _ddb_table_response(table, include_items=False)


def api_dynamodb_get_table(table_name: str):
    table = _ddb_find_table(table_name)
    if not table:
        raise HTTPException(404, detail="TableNotFound")
    return _ddb_table_response(table, include_items=True)


def api_dynamodb_delete_table(table_name: str):
    _ddb_delete_table_record(table_name)
    return {"deleted": True, "table_name": table_name}


def api_dynamodb_list_items(table_name: str):
    table = _ddb_find_table(table_name)
    if not table:
        raise HTTPException(404, detail="TableNotFound")
    rows = _ddb_table_view(table, include_items=True)["item_rows"]
    return {"table_name": table_name, "items": rows, "count": len(rows)}


def api_dynamodb_put_item(table_name: str, req):
    table = _ddb_find_table(table_name)
    if not table:
        raise HTTPException(404, detail="TableNotFound")
    old = _ddb_put_item_record(table, {"item": req.item})
    native_item = _ddb_item_to_native_item(req.item)
    key = _ddb_item_key_string(table, native_item)
    record = table.get("items", {}).get(key, {})
    return {"table_name": table_name, "item": _ddb_item_record_view(table, key, record), "previous": old.get("item", {}) if old else {}}


def api_dynamodb_update_item(table_name: str, req):
    table = _ddb_find_table(table_name)
    if not table:
        raise HTTPException(404, detail="TableNotFound")
    updated = _ddb_update_item_record(
        table,
        {
            "key": req.key,
            "attribute_updates": req.attribute_updates or {},
            "update_expression": req.update_expression,
            "expression_attribute_values": req.expression_attribute_values or {},
        },
    )
    return {"table_name": table_name, "item": updated.get("item", {})}


def api_dynamodb_delete_item(table_name: str, req):
    table = _ddb_find_table(table_name)
    if not table:
        raise HTTPException(404, detail="TableNotFound")
    removed = _ddb_delete_item_record(table, {"key": req.key})
    return {"table_name": table_name, "deleted": True, "item": removed.get("item", {})}


def api_dynamodb_query_items(table_name: str, req):
    table = _ddb_find_table(table_name)
    if not table:
        raise HTTPException(404, detail="TableNotFound")
    payload = {
        "partition_key_value": req.partition_key_value,
        "sort_key_equals": req.sort_key_equals,
        "sort_key_begins_with": req.sort_key_begins_with,
        "sort_key_between": req.sort_key_between or [],
        "limit": req.limit,
        "key_condition_expression": req.key_condition_expression,
        "expression_attribute_values": req.expression_attribute_values or {},
        "expression_attribute_names": req.expression_attribute_names or {},
    }
    rows, count = _ddb_query_filter(table, payload)
    return {"table_name": table_name, "items": [_ddb_item_record_view(table, row.get("key", ""), row) for row in rows], "count": len(rows), "scanned_count": count}


def api_dynamodb_scan_items(table_name: str, req):
    table = _ddb_find_table(table_name)
    if not table:
        raise HTTPException(404, detail="TableNotFound")
    rows, count = _ddb_scan_filter(table, {"limit": req.limit})
    return {"table_name": table_name, "items": [_ddb_item_record_view(table, row.get("key", ""), row) for row in rows], "count": len(rows), "scanned_count": count}


def api_dynamodb_list_tags(table_name: str):
    table = _ddb_find_table(table_name)
    if not table:
        raise HTTPException(404, detail="TableNotFound")
    return {"table_name": table_name, "tags": _ddb_tags_view(table)}


def api_dynamodb_tag_table(table_name: str, req):
    table = _ddb_find_table(table_name)
    if not table:
        raise HTTPException(404, detail="TableNotFound")
    tags = _ddb_tags_view(table)
    tags.update({str(k): str(v) for k, v in (req.tags or {}).items()})
    _ddb_set_tags(table, tags)
    return {"table_name": table_name, "tags": _ddb_tags_view(table)}


def api_dynamodb_untag_table(table_name: str, payload: dict[str, Any]):
    table = _ddb_find_table(table_name)
    if not table:
        raise HTTPException(404, detail="TableNotFound")
    tags = _ddb_tags_view(table)
    for key in payload.get("keys", []) if isinstance(payload, dict) else []:
        tags.pop(str(key), None)
    _ddb_set_tags(table, tags)
    return {"table_name": table_name, "tags": _ddb_tags_view(table)}


def _lambda_state() -> dict:
    return _lambda_state_proxy


def _lambda_function_key(function_name: str) -> str:
    return (function_name or "").strip()


def _lambda_find_function(function_name: str) -> dict | None:
    key = _lambda_function_key(function_name)
    if not key:
        return None
    functions = _lambda_state().setdefault("functions", {})
    if key in functions:
        return functions[key]
    lowered = key.lower()
    for existing_name, function in functions.items():
        if existing_name.lower() == lowered:
            return function
    return None


def _lambda_list_functions() -> list[dict]:
    functions = list(_lambda_state().setdefault("functions", {}).values())
    functions.sort(key=lambda item: (item.get("created", ""), item.get("function_name", "")))
    return functions


def _lambda_invocations_view(function: dict) -> list[dict]:
    invocations = list(function.get("invocations", []))
    invocations.sort(key=lambda item: item.get("at", ""), reverse=True)
    return invocations


def _lambda_versions_view(function: dict) -> list[dict]:
    versions = list(function.get("versions", []))
    versions.sort(key=lambda item: item.get("created", ""), reverse=True)
    return versions


def _lambda_permissions_view(function: dict) -> list[dict]:
    permissions = list(function.get("permissions", []))
    permissions.sort(key=lambda item: (item.get("created", ""), item.get("statement_id", "")))
    return permissions


def _lambda_permission_matches(permission: dict, action: str, principal: str, source_arn: str, source_account: str) -> bool:
    perm_action = (permission.get("action") or "lambda:InvokeFunction").strip()
    if perm_action not in {"*", "lambda:*"} and action not in {perm_action, "*"}:
        return False
    perm_principal = (permission.get("principal") or "").strip()
    if perm_principal and perm_principal != "*":
        if not principal:
            return False
        if not fnmatch.fnmatchcase(principal, perm_principal):
            return False
    perm_source_arn = (permission.get("source_arn") or "").strip()
    if perm_source_arn:
        if not source_arn or not fnmatch.fnmatchcase(source_arn, perm_source_arn):
            return False
    perm_source_account = (permission.get("source_account") or "").strip()
    if perm_source_account:
        if not source_account or perm_source_account != source_account:
            return False
    return True


def _lambda_can_invoke_from_source(function: dict, principal: str = "", source_arn: str = "", source_account: str = "", action: str = "lambda:InvokeFunction") -> tuple[bool, str]:
    principal = (principal or "").strip()
    source_arn = (source_arn or "").strip()
    source_account = (source_account or "").strip()
    if not principal and not source_arn and not source_account:
        return True, ""
    permissions = _lambda_permissions_view(function)
    if not permissions:
        return False, "AccessDeniedException: Lambda policy does not allow this invocation source."
    for permission in permissions:
        if _lambda_permission_matches(permission, action, principal, source_arn, source_account):
            return True, ""
    return False, "AccessDeniedException: Lambda policy does not allow this invocation source."


def _lambda_function_dir(function_name: str) -> Path:
    return Path(__file__).resolve().parents[1] / "lambda_functions" / function_name


def _lambda_handler_module(handler: str) -> str:
    handler = (handler or "").strip()
    return handler.rsplit(".", 1)[0] if "." in handler else "lambda_function"


def _lambda_handler_name(handler: str) -> str:
    handler = (handler or "").strip()
    return handler.rsplit(".", 1)[1] if "." in handler else "lambda_handler"


def _lambda_sync_code_artifact(function: dict) -> None:
    function_dir = _lambda_function_dir(function["function_name"])
    function_dir.mkdir(parents=True, exist_ok=True)
    module_name = _lambda_handler_module(function.get("handler", "lambda_function.lambda_handler")) or "lambda_function"
    code_path = function_dir / f"{module_name}.py"
    code = function.get("code") or _server()._lambda_default_code(function["function_name"])
    code_path.write_text(code, encoding="utf-8")
    function["code_path"] = str(code_path)
    function["workdir"] = str(function_dir)


def _lambda_run_handler(function: dict, event_payload: Any) -> dict:
    workdir = _lambda_function_dir(function["function_name"])
    module_name = _lambda_handler_module(function.get("handler", "lambda_function.lambda_handler")) or "lambda_function"
    handler_name = _lambda_handler_name(function.get("handler", "lambda_function.lambda_handler")) or "lambda_handler"
    code_path = workdir / f"{module_name}.py"
    if not code_path.exists():
        _lambda_sync_code_artifact(function)
    helper_code = textwrap.dedent(
        """
        import contextlib
        import importlib.util
        import io
        import json
        import os
        import sys
        import traceback

        workdir = sys.argv[1]
        module_name = sys.argv[2]
        handler_name = sys.argv[3]
        payload = json.loads(sys.stdin.read() or "{}")

        sys.path.insert(0, workdir)
        module_path = os.path.join(workdir, module_name + ".py")
        spec = importlib.util.spec_from_file_location(module_name, module_path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Unable to load module {module_name}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        handler = getattr(module, handler_name)

        class Context:
            function_name = ""
            memory_limit_in_mb = 0
            invoked_function_arn = ""
            aws_request_id = ""

        stdout = io.StringIO()
        stderr = io.StringIO()
        ctx = Context()
        try:
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                result = handler(payload, ctx)
            print(json.dumps({
                "ok": True,
                "result": result,
                "stdout": stdout.getvalue(),
                "stderr": stderr.getvalue(),
            }, default=str))
        except Exception as exc:
            print(json.dumps({
                "ok": False,
                "error": str(exc),
                "traceback": traceback.format_exc(),
                "stdout": stdout.getvalue(),
                "stderr": stderr.getvalue(),
            }, default=str))
        """
    ).strip()
    proc = subprocess.run(
        [sys.executable, "-c", helper_code, str(workdir), module_name, handler_name],
        input=json.dumps(event_payload or {}, default=str),
        capture_output=True,
        text=True,
        timeout=max(int(function.get("timeout", 3) or 3), 1) + 1,
        env={
            **os.environ,
            **(function.get("environment") or {}),
            "PYTHONPATH": str(workdir) + (os.pathsep + os.environ.get("PYTHONPATH", "") if os.environ.get("PYTHONPATH") else ""),
        },
    )
    output_lines = [line for line in (proc.stdout or "").splitlines() if line.strip()]
    if output_lines:
        try:
            payload = json.loads(output_lines[-1])
        except Exception:
            payload = {"ok": False, "error": proc.stdout or proc.stderr or "Lambda runtime error"}
    else:
        payload = {"ok": False, "error": proc.stderr or "Lambda runtime error"}
    return {
        "returncode": proc.returncode,
        "ok": bool(payload.get("ok")) and proc.returncode == 0,
        "result": payload.get("result"),
        "stdout": payload.get("stdout", ""),
        "stderr": payload.get("stderr", ""),
        "error": payload.get("error", ""),
        "traceback": payload.get("traceback", ""),
    }


def _lambda_record_invocation(function: dict, invocation_type: str, event_payload: Any, run_result: dict, source: str = "", source_principal: str = "", source_arn: str = "", source_account: str = "") -> dict:
    record = {
        "id": _id_gen("laminv"),
        "at": _now(),
        "function_name": function.get("function_name", ""),
        "function_arn": function.get("function_arn", ""),
        "invocation_type": invocation_type,
        "status": "success" if run_result.get("ok") else "error",
        "source": source,
        "source_principal": source_principal,
        "source_arn": source_arn,
        "source_account": source_account,
        "request_payload": copy.deepcopy(event_payload),
        "response_payload": copy.deepcopy(run_result.get("result")),
        "stdout": run_result.get("stdout", ""),
        "stderr": run_result.get("stderr", ""),
        "error": run_result.get("error", ""),
        "traceback": run_result.get("traceback", ""),
    }
    function.setdefault("invocations", []).append(record)
    function["invocations"] = function["invocations"][-200:]
    function["last_modified"] = _now()
    _persist_state()
    return record


def _lambda_invoke_function(function_name: str, event_payload: Any, invocation_type: str = "RequestResponse", source: str = "", source_principal: str = "", source_arn: str = "", source_account: str = "") -> dict:
    function = _lambda_find_function(function_name)
    if not function:
        raise HTTPException(404, detail="ResourceNotFoundException")
    allowed, reason = _lambda_can_invoke_from_source(function, source_principal, source_arn, source_account)
    if not allowed:
        raise HTTPException(403, detail=reason)
    normalized = (invocation_type or "RequestResponse").strip().lower()
    if normalized == "event":
        record = {
            "id": _id_gen("laminv"),
            "at": _now(),
            "function_name": function.get("function_name", ""),
            "function_arn": function.get("function_arn", ""),
            "invocation_type": "Event",
            "status": "accepted",
            "source": source,
            "source_principal": source_principal,
            "source_arn": source_arn,
            "source_account": source_account,
            "request_payload": copy.deepcopy(event_payload),
            "response_payload": None,
            "stdout": "",
            "stderr": "",
            "error": "",
            "traceback": "",
        }
        function.setdefault("invocations", []).append(record)
        function["invocations"] = function["invocations"][-200:]
        function["last_modified"] = _now()
        _persist_state()

        def _worker():
            try:
                run_result = _lambda_run_handler(function, event_payload)
                record.update({
                    "status": "success" if run_result.get("ok") else "error",
                    "response_payload": copy.deepcopy(run_result.get("result")),
                    "stdout": run_result.get("stdout", ""),
                    "stderr": run_result.get("stderr", ""),
                    "error": run_result.get("error", ""),
                    "traceback": run_result.get("traceback", ""),
                    "completed_at": _now(),
                })
                function["last_modified"] = _now()
                _persist_state()
            except Exception:
                record.update({
                    "status": "error",
                    "error": "Lambda invocation failed",
                    "traceback": traceback.format_exc(),
                    "completed_at": _now(),
                })
                function["last_modified"] = _now()
                _persist_state()

        threading.Thread(target=_worker, daemon=True).start()
        return record

    run_result = _lambda_run_handler(function, event_payload)
    return _lambda_record_invocation(function, "RequestResponse", event_payload, run_result, source=source, source_principal=source_principal, source_arn=source_arn, source_account=source_account)


def _lambda_invoke_response(function_name: str, event_payload: Any, invocation_type: str = "RequestResponse", source: str = "", source_principal: str = "", source_arn: str = "", source_account: str = "") -> dict:
    record = _lambda_invoke_function(function_name, event_payload, invocation_type=invocation_type, source=source, source_principal=source_principal, source_arn=source_arn, source_account=source_account)
    return {
        "function_name": record["function_name"],
        "function_arn": record["function_arn"],
        "invocation_type": record["invocation_type"],
        "status": record["status"],
        "payload": record.get("response_payload"),
        "stdout": record.get("stdout", ""),
        "stderr": record.get("stderr", ""),
        "error": record.get("error", ""),
        "traceback": record.get("traceback", ""),
        "at": record.get("at", ""),
    }


def _apigw_state() -> dict:
    return _apigw_state_proxy


def _apigw_api(api_id: str) -> dict | None:
    return _apigw_state().setdefault("apis", {}).get(api_id)


def _apigw_route_key(resource_id: str, method: str) -> str:
    return f"{resource_id}::{method.upper()}"


def _apigw_path_regex(path: str) -> str:
    escaped = re.escape(path or "/")
    escaped = escaped.replace(r"\{proxy\+\}", r".*")
    return "^" + escaped.replace(r"\{", "{").replace(r"\}", "}") + "$"


def _apigw_find_resource(api_view: dict, path: str) -> dict | None:
    resources = list((api_view or {}).get("resources", {}).values())
    for resource in sorted(resources, key=lambda item: len(item.get("path", "")), reverse=True):
        resource_path = resource.get("path", "/") or "/"
        pattern = _apigw_path_regex(resource_path)
        if re.match(pattern, path or "/"):
            return resource
    return None


async def _apigw_invoke(api_id: str, stage_name: str, proxy_path: str, request: Request) -> Response:
    api = _apigw_api(api_id)
    if not api:
        raise HTTPException(404, detail="RestApiNotFound")
    stage = api.get("stages", {}).get(stage_name)
    if not stage:
        raise HTTPException(404, detail="StageNotFound")
    deployment = api["deployments"].get(stage.get("deployment_id", ""))
    if not deployment:
        raise HTTPException(404, detail="DeploymentNotFound")
    snapshot = deployment.get("snapshot", {})
    path = "/" + proxy_path.lstrip("/") if proxy_path else "/"
    resolved_resource = _apigw_find_resource(snapshot, path)
    if not resolved_resource:
        raise HTTPException(404, detail="ResourceNotFound")
    method = request.method.upper()
    method_def = snapshot.get("methods", {}).get(_apigw_route_key(resolved_resource["resource_id"], method)) or snapshot.get("methods", {}).get(_apigw_route_key(resolved_resource["resource_id"], "ANY"))
    if not method_def:
        raise HTTPException(405, detail="MethodNotAllowed")
    integration = snapshot.get("integrations", {}).get(_apigw_route_key(resolved_resource["resource_id"], method)) or snapshot.get("integrations", {}).get(_apigw_route_key(resolved_resource["resource_id"], "ANY"))
    if not integration:
        raise HTTPException(409, detail="IntegrationMissing")

    status_code = int(integration.get("status_code", 200))
    content_type = integration.get("content_type", "application/json")
    headers = {"Content-Type": content_type}
    body_bytes = await request.body()
    result = {"api_id": api_id, "stage": stage_name, "path": path, "method": method, "resource_path": resolved_resource.get("path", path)}

    if integration.get("type", "MOCK").upper() == "MOCK":
        payload = integration.get("response_body") or json.dumps({"message": "Mock integration response", **result})
        api_log = {"at": _now(), "api_id": api_id, "stage": stage_name, "path": path, "method": method, "status": status_code, "integration_type": "MOCK"}
        api.setdefault("logs", []).append(api_log)
        _apigw_state().setdefault("logs", []).append(api_log)
        return Response(content=payload, status_code=status_code, media_type=content_type, headers=headers)

    if integration.get("uri"):
        req = URLRequest(integration["uri"], data=body_bytes or None, method=method)
        if body_bytes and "content-type" not in {k.lower() for k in req.headers}:
            req.add_header("Content-Type", request.headers.get("content-type", "application/json"))
        try:
            with urlopen(req, timeout=30) as resp:
                payload = resp.read()
                status_code = getattr(resp, "status", 200) or 200
                content_type = resp.headers.get("content-type", content_type)
        except HTTPError as exc:
            payload = exc.read()
            status_code = exc.code or 502
            content_type = exc.headers.get("content-type", content_type) if exc.headers else content_type
        except URLError as exc:
            raise HTTPException(502, detail=f"IntegrationError: {exc.reason}")
        api_log = {"at": _now(), "api_id": api_id, "stage": stage_name, "path": path, "method": method, "status": status_code, "integration_type": integration.get("type", "HTTP")}
        api.setdefault("logs", []).append(api_log)
        _apigw_state().setdefault("logs", []).append(api_log)
        return Response(content=payload, status_code=status_code, media_type=content_type, headers={"Content-Type": content_type})

    raise HTTPException(409, detail="IntegrationMissing")


def _apigw_invoke_root(api_id: str, stage_name: str, request: Request) -> Response:
    return _apigw_invoke(api_id, stage_name, "", request)


def api_apigateway_list_apis():
    s = _server()
    apis = [s._apigw_api_view(api) for api in s._apigw_state().get("apis", {}).values()]
    return {"apis": apis, "count": len(apis)}


def api_apigateway_create_api(req):
    return _server()._apigw_api_view(_server()._apigw_create_api_record(req))


def api_apigateway_get_api(api_id: str):
    s = _server()
    api = s._apigw_api(api_id)
    if not api:
        raise HTTPException(404, detail="NotFound")
    return s._apigw_api_view(api)


def api_apigateway_delete_api(api_id: str):
    _server()._apigw_delete_api_record(api_id)
    return {"deleted": True, "api_id": api_id}


def api_apigateway_list_resources(api_id: str):
    s = _server()
    api = s._apigw_api(api_id)
    if not api:
        raise HTTPException(404, detail="NotFound")
    return {"api_id": api_id, "resources": s._apigw_route_views(api), "count": len(api.get("resources", {}))}


def api_apigateway_create_resource(api_id: str, req):
    return _server()._apigw_api_view(_server()._apigw_create_resource_record(api_id, req))


def api_apigateway_put_method(api_id: str, req):
    return _server()._apigw_api_view(_server()._apigw_put_method_record(api_id, req))


def api_apigateway_put_integration(api_id: str, req):
    return _server()._apigw_api_view(_server()._apigw_put_integration_record(api_id, req))


def api_apigateway_create_deployment(api_id: str, req):
    return _server()._apigw_api_view(_server()._apigw_create_deployment_record(api_id, req))


def api_apigateway_list_deployments(api_id: str):
    s = _server()
    api = s._apigw_api(api_id)
    if not api:
        raise HTTPException(404, detail="NotFound")
    return {"api_id": api_id, "deployments": s._apigw_api_view(api).get("deployments", []), "count": len(api.get("deployments", {}))}


def api_apigateway_create_stage(api_id: str, req):
    return _server()._apigw_api_view(_server()._apigw_create_stage_record(api_id, req))


def api_apigateway_list_stages(api_id: str):
    s = _server()
    api = s._apigw_api(api_id)
    if not api:
        raise HTTPException(404, detail="NotFound")
    return {"api_id": api_id, "stages": s._apigw_api_view(api).get("stages", []), "count": len(api.get("stages", {}))}


def api_apigateway_list_logs(api_id: str):
    s = _server()
    api = s._apigw_api(api_id)
    if not api:
        raise HTTPException(404, detail="NotFound")
    logs = s._apigw_api_view(api).get("logs", [])
    return {"api_id": api_id, "logs": logs, "count": len(logs)}


async def api_apigateway_invoke_path(api_id: str, stage_name: str, proxy_path: str, request: Request):
    return await _apigw_invoke(api_id, stage_name, proxy_path, request)


async def api_apigateway_invoke_root(api_id: str, stage_name: str, request: Request):
    return await _apigw_invoke(api_id, stage_name, "", request)


def api_lambda_list_functions():
    s = _server()
    functions = [s._lambda_function_view(function) for function in s._lambda_list_functions()]
    return {"functions": functions, "count": len(functions)}


def api_lambda_create_function(req):
    s = _server()
    function = s._lambda_create_function_record(req)
    bundle = s._cloudsim_runtime_bundle("lambda")
    function["runtime_bundle_id"] = bundle.get("id", "")
    function["runtime_bundle_name"] = bundle.get("name", "")
    function["runtime_bundle_kind"] = bundle.get("kind", "")
    s._record_usage("lambda.create_function", {"function_name": function.get("function_name", "")})
    return s._lambda_function_view(function)


def api_lambda_get_function(function_name: str):
    s = _server()
    function = s._lambda_find_function(function_name)
    if not function:
        raise HTTPException(404, detail="ResourceNotFoundException")
    return s._lambda_function_view(function)


def api_lambda_update_function_code(function_name: str, payload: dict[str, Any]):
    s = _server()
    function = s._lambda_find_function(function_name)
    if not function:
        raise HTTPException(404, detail="ResourceNotFoundException")
    updated = s._lambda_update_function_code(function, str(payload.get("code", "")))
    s._record_usage("lambda.update_function_code", {"function_name": function_name})
    return s._lambda_function_view(updated)


def api_lambda_update_function_configuration(function_name: str, req):
    s = _server()
    function = s._lambda_find_function(function_name)
    if not function:
        raise HTTPException(404, detail="ResourceNotFoundException")
    updated = s._lambda_update_function_configuration(function, req)
    s._record_usage("lambda.update_function_configuration", {"function_name": function_name})
    return s._lambda_function_view(updated)


def api_lambda_delete_function(function_name: str):
    s = _server()
    s._lambda_delete_function(function_name)
    s._record_usage("lambda.delete_function", {"function_name": function_name})
    return {"deleted": True, "function_name": function_name}


def api_lambda_get_policy(function_name: str):
    s = _server()
    function = s._lambda_find_function(function_name)
    if not function:
        raise HTTPException(404, detail="ResourceNotFoundException")
    policy = s._lambda_get_policy(function)
    return {"function_name": function["function_name"], "function_arn": function["function_arn"], **policy}


def api_lambda_add_permission(function_name: str, req):
    s = _server()
    function = s._lambda_find_function(function_name)
    if not function:
        raise HTTPException(404, detail="ResourceNotFoundException")
    permission = s._lambda_add_permission(function, req)
    policy = s._lambda_get_policy(function)
    return {"function_name": function["function_name"], "function_arn": function["function_arn"], "statement": permission, **policy}


def api_lambda_remove_permission(function_name: str, statement_id: str):
    s = _server()
    function = s._lambda_find_function(function_name)
    if not function:
        raise HTTPException(404, detail="ResourceNotFoundException")
    s._lambda_remove_permission(function, statement_id)
    return {"deleted": True, "function_name": function["function_name"], "statement_id": statement_id}


def api_lambda_list_invocations(function_name: str):
    s = _server()
    function = s._lambda_find_function(function_name)
    if not function:
        raise HTTPException(404, detail="ResourceNotFoundException")
    invocations = s._lambda_invocations_view(function)
    return {"function_name": function["function_name"], "function_arn": function["function_arn"], "invocations": invocations, "count": len(invocations)}


def api_lambda_list_versions(function_name: str):
    s = _server()
    function = s._lambda_find_function(function_name)
    if not function:
        raise HTTPException(404, detail="ResourceNotFoundException")
    versions = s._lambda_versions_view(function)
    return {"function_name": function["function_name"], "function_arn": function["function_arn"], "versions": versions, "count": len(versions)}


def api_lambda_publish_version(function_name: str, payload):
    s = _server()
    function = s._lambda_find_function(function_name)
    if not function:
        raise HTTPException(404, detail="ResourceNotFoundException")
    version = s._lambda_publish_version(function, payload.description)
    return {"function_name": function["function_name"], "function_arn": function["function_arn"], "version": version}


def api_lambda_invoke_function(function_name: str, req):
    return _lambda_invoke_response(function_name, req.payload, invocation_type=req.invocation_type)


def api_lambda_list_functions_aws():
    return api_lambda_list_functions()


def api_lambda_create_function_aws(req):
    return api_lambda_create_function(req)


def api_lambda_get_function_aws(function_name: str):
    return api_lambda_get_function(function_name)


def api_lambda_delete_function_aws(function_name: str):
    return api_lambda_delete_function(function_name)


def api_lambda_get_policy_aws(function_name: str):
    return api_lambda_get_policy(function_name)


def api_lambda_add_permission_aws(function_name: str, req):
    return api_lambda_add_permission(function_name, req)


def api_lambda_remove_permission_aws(function_name: str, statement_id: str):
    return api_lambda_remove_permission(function_name, statement_id)


def api_lambda_update_function_code_aws(function_name: str, payload: dict[str, Any]):
    return api_lambda_update_function_code(function_name, payload)


def api_lambda_update_function_configuration_aws(function_name: str, req):
    return api_lambda_update_function_configuration(function_name, req)


def api_lambda_publish_version_aws(function_name: str, payload):
    return api_lambda_publish_version(function_name, payload)


def api_lambda_list_versions_aws(function_name: str):
    return api_lambda_list_versions(function_name)


async def api_lambda_invoke_function_aws(function_name: str, request: Request):
    function = _lambda_find_function(function_name)
    if not function:
        raise HTTPException(404, detail="ResourceNotFoundException")
    invocation_type = request.headers.get("x-amz-invocation-type") or request.query_params.get("InvocationType", "RequestResponse")
    body = await request.body()
    payload = {}
    if body:
        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception:
            payload = {"body": body.decode("utf-8", errors="replace")}
    record = _lambda_invoke_function(function_name, payload, invocation_type=invocation_type)
    if invocation_type and invocation_type.lower() == "event":
        return Response(status_code=202)
    response_payload = record.get("response_payload")
    if isinstance(response_payload, (dict, list)):
        body_bytes = json.dumps(response_payload, default=str).encode("utf-8")
        media_type = "application/json"
    elif isinstance(response_payload, bytes):
        body_bytes = response_payload
        media_type = "application/octet-stream"
    elif response_payload is None:
        body_bytes = b""
        media_type = "application/json"
    else:
        body_bytes = str(response_payload).encode("utf-8")
        media_type = "text/plain"
    headers = {
        "X-Amz-Executed-Version": "$LATEST",
        "X-Amz-Function-Error": "Handled" if record.get("status") == "error" else "",
    }
    if not headers["X-Amz-Function-Error"]:
        headers.pop("X-Amz-Function-Error", None)
    return Response(content=body_bytes, media_type=media_type, headers=headers)
