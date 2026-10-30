"""AWS SQS queue CRUD, message send/receive/delete, query API.

Extracted from server.py — contains both the REST API route handlers and
the underlying helper / business-logic functions.
"""
from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response

from core import app_context as ctx
from core.models import (
    SQSMessageSendRequest,
    SQSQueueCreateRequest,
    SQSQueueUpdateRequest,
    SQSReceiveRequest,
    SQSVisibilityRequest,
)

# ---------------------------------------------------------------------------
# Lazy back-reference to server.py
# ---------------------------------------------------------------------------


def _srv():
    import server as _s
    return _s


# ---------------------------------------------------------------------------
# Helper proxies — delegate to server.py
# ---------------------------------------------------------------------------

def _sqs_state() -> dict:
    return ctx.sqs_state


def _sqs_find_queue(queue_name: str):
    return _srv()._sqs_find_queue(queue_name)


def _sqs_list_queues() -> list[dict]:
    return _srv()._sqs_list_queues()


def _sqs_queue_view(queue: dict, include_messages: bool = True) -> dict:
    return _srv()._sqs_queue_view(queue, include_messages)


def _sqs_queue_list_view(queue: dict) -> dict:
    return _srv()._sqs_queue_list_view(queue)


def _sqs_create_queue_record(req) -> dict:
    return _srv()._sqs_create_queue_record(req)


def _sqs_update_queue_attributes(queue: dict, payload: dict) -> dict:
    return _srv()._sqs_update_queue_attributes(queue, payload)


def _sqs_delete_queue(queue_name: str):
    return _srv()._sqs_delete_queue(queue_name)


def _sqs_enqueue_message(queue, body, attributes=None, message_attributes=None, group_id="", dedup_id="", source=""):
    return _srv()._sqs_enqueue_message(queue, body, attributes, message_attributes, group_id, dedup_id, source)


def _sqs_extract_messages_for_delivery(queue: dict, max_messages: int) -> list[dict]:
    return _srv()._sqs_extract_messages_for_delivery(queue, max_messages)


def _sqs_delete_message(queue: dict, receipt_handle: str) -> bool:
    return _srv()._sqs_delete_message(queue, receipt_handle)


def _sqs_change_message_visibility(queue: dict, receipt_handle: str, visibility_timeout: int) -> bool:
    return _srv()._sqs_change_message_visibility(queue, receipt_handle, visibility_timeout)


def _sqs_purge_queue(queue: dict):
    return _srv()._sqs_purge_queue(queue)


def _sqs_view_message(queue: dict, message: dict, include_body: bool = True) -> dict:
    return _srv()._sqs_view_message(queue, message, include_body)


def _sqs_tags_view(queue: dict) -> dict:
    return _srv()._sqs_tags_view(queue)


def _sqs_set_tags(queue: dict, tags: dict[str, str]):
    return _srv()._sqs_set_tags(queue, tags)


def _sqs_queue_from_name_or_url(name_or_url: str):
    return _srv()._sqs_queue_from_name_or_url(name_or_url)


def _sqs_queue_attributes(queue: dict) -> dict[str, str]:
    return _srv()._sqs_queue_attributes(queue)


# ---------------------------------------------------------------------------
# Query-protocol handler (XML / JSON-RPC)
# ---------------------------------------------------------------------------

async def api_sqs_query(request: Request):
    return await _srv().api_sqs_query(request)


# ---------------------------------------------------------------------------
# Console REST API route handlers
# ---------------------------------------------------------------------------

def api_sqs_list_queues():
    queues = [_sqs_queue_list_view(queue) for queue in _sqs_list_queues()]
    return {"queues": queues, "count": len(queues)}


def api_sqs_create_queue(req: SQSQueueCreateRequest):
    queue = _sqs_create_queue_record(req)
    ctx.record_usage("sqs.create_queue", {"queue_name": queue.get("queue_name", "")})
    return _sqs_queue_view(queue)


def api_sqs_get_queue(queue_name: str):
    queue = _sqs_find_queue(queue_name)
    if not queue:
        raise HTTPException(404, detail="QueueNotFound")
    return _sqs_queue_view(queue)


def api_sqs_update_queue(queue_name: str, req: SQSQueueUpdateRequest):
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
        "SqsManagedSseEnabled": req.sqs_managed_sse,
        "KmsMasterKeyId": req.kms_master_key_id,
        "KmsDataKeyReusePeriodSeconds": req.kms_data_key_reuse_period,
    }
    if req.tags is not None:
        queue["tags"] = copy.deepcopy(req.tags)
    _sqs_update_queue_attributes(queue, {k: v for k, v in payload.items() if v is not None})
    ctx.record_usage("sqs.update_queue", {"queue_name": queue_name})
    return _sqs_queue_view(queue)


def api_sqs_delete_queue(queue_name: str):
    _sqs_delete_queue(queue_name)
    ctx.record_usage("sqs.delete_queue", {"queue_name": queue_name})
    return {"deleted": True, "queue_name": queue_name}


def api_sqs_list_messages(queue_name: str):
    queue = _sqs_find_queue(queue_name)
    if not queue:
        raise HTTPException(404, detail="QueueNotFound")
    return {"queue_name": queue["queue_name"], "messages": [_sqs_view_message(queue, msg) for msg in queue.get("messages", []) if not msg.get("deleted")], "count": len(queue.get("messages", []))}


def api_sqs_send_message(queue_name: str, req: SQSMessageSendRequest):
    queue = _sqs_find_queue(queue_name)
    if not queue:
        raise HTTPException(404, detail="QueueNotFound")
    message = _sqs_enqueue_message(queue, req.message_body, req.message_attributes or req.message_attributes_map or {}, req.message_attributes_map or {}, req.message_group_id, req.message_deduplication_id, source="api_send_message")
    return {"message": _sqs_view_message(queue, message), "queue_name": queue["queue_name"], "queue_url": queue.get("queue_url")}


def api_sqs_receive_message(queue_name: str, req: SQSReceiveRequest):
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


def api_sqs_change_visibility(queue_name: str, receipt_handle: str, req: SQSVisibilityRequest):
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


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def register(app: FastAPI) -> None:
    """Register SQS routes on the FastAPI app.

    NOTE: SQS routes are currently registered via providers/aws_routes.py
    using the dynamic _proxy/_add_route mechanism.  This register() function
    is provided for future use when the migration is complete.
    """
    pass  # Routes registered via providers/aws_routes.py spec table
