from __future__ import annotations

import json
import time
from typing import Any

from fastapi import HTTPException, Request


def _server():
    import server as server_module

    return server_module


def _gcp_vpc_enforce_reconcile(s) -> None:
    """Re-apply VPC firewall enforcement after a rule change (no-op unless the
    active space has enforce_vpc on)."""
    try:
        if s._gcp_active_space_dict().get("enforce_vpc"):
            s._gcp_vpc_reconcile()
    except Exception:
        pass


def _strip_action_suffix(value: str, *suffixes: str) -> str:
    text = str(value or "")
    for suffix in suffixes:
        if suffix and text.endswith(suffix):
            return text[: -len(suffix)]
    return text


TARGETS = [
    "api_gcp_storage_list_buckets",
    "api_gcp_storage_create_bucket",
    "api_gcp_storage_get_bucket",
    "api_gcp_storage_delete_bucket",
    "api_gcp_storage_list_objects",
    "api_gcp_storage_create_object",
    "api_gcp_storage_get_object",
    "api_gcp_storage_delete_object",
    "api_gcp_sql_list_instances",
    "api_gcp_sql_create_instance",
    "api_gcp_sql_get_instance",
    "api_gcp_sql_delete_instance",
    "api_gcp_sql_restart_instance",
    "api_gcp_pubsub_list_topics",
    "api_gcp_pubsub_create_topic",
    "api_gcp_pubsub_get_topic",
    "api_gcp_pubsub_update_topic",
    "api_gcp_pubsub_list_topic_messages",
    "api_gcp_pubsub_delete_topic",
    "api_gcp_pubsub_publish",
    "api_gcp_pubsub_list_subscriptions",
    "api_gcp_pubsub_create_subscription",
    "api_gcp_pubsub_get_subscription",
    "api_gcp_pubsub_patch_subscription",
    "api_gcp_pubsub_list_subscription_messages",
    "api_gcp_pubsub_purge_subscription",
    "api_gcp_pubsub_delete_subscription",
    "api_gcp_pubsub_pull",
    "api_gcp_pubsub_ack",
    "api_gcp_pubsub_modify_ack_deadline",
    "api_gcp_pubsub_list_topic_subscriptions",
    "api_gcp_pubsub_list_schemas",
    "api_gcp_pubsub_create_schema",
    "api_gcp_pubsub_delete_schema",
    "api_gcp_firestore_list_root_documents",
    "api_gcp_firestore_list_documents",
    "api_gcp_firestore_create_document",
    "api_gcp_firestore_get_document",
    "api_gcp_firestore_delete_document",
    "api_gcp_firestore_update_document",
    "api_gcp_firestore_doc_get",
    "api_gcp_firestore_doc_post",
    "api_gcp_firestore_doc_delete",
    "api_gcp_firestore_doc_put",
    "api_gcp_firestore_run_query",
    "api_gcp_firestore_list_indexes",
    "api_gcp_firestore_create_index",
    "api_gcp_firestore_delete_index",
    "api_gcp_functions_list",
    "api_gcp_functions_create",
    "api_gcp_functions_update",
    "api_gcp_functions_publish_version",
    "api_gcp_functions_list_versions",
    "api_gcp_functions_list_invocations",
    "api_gcp_functions_get_policy",
    "api_gcp_functions_set_policy",
    "api_gcp_functions_get",
    "api_gcp_functions_delete",
    "api_gcp_functions_call",
    "api_gcp_apigw_list_apis",
    "api_gcp_apigw_create_api",
    "api_gcp_apigw_get_api",
    "api_gcp_apigw_delete_api",
    "api_gcp_apigw_list_configs",
    "api_gcp_apigw_create_config",
    "api_gcp_apigw_list_gateways",
    "api_gcp_apigw_create_gateway",
    "api_gcp_vpc_list_networks",
    "api_gcp_vpc_create_network",
    "api_gcp_vpc_get_network",
    "api_gcp_vpc_delete_network",
    "api_gcp_vpc_list_subnetworks",
    "api_gcp_vpc_create_subnetwork",
    "api_gcp_vpc_list_firewalls",
    "api_gcp_vpc_create_firewall",
    "api_gcp_vpc_update_firewall",
    "api_gcp_vpc_delete_firewall",
]


def api_gcp_storage_list_buckets(request: Request):
    s = _server()
    project = s._gcp_project_name(request.query_params.get("project"))
    buckets = []
    for bucket in s.gcp_storage_state.get("buckets", {}).values():
        if str(bucket.get("project") or project) != project:
            continue
        buckets.append(s._gcp_storage_bucket_view(project, bucket))
    buckets.sort(key=lambda item: item.get("name", ""))
    return {"kind": "storage#buckets", "items": buckets, "prefixes": [], "nextPageToken": ""}


async def api_gcp_storage_create_bucket(request: Request):
    s = _server()
    payload = await request.json() if request is not None else {}
    payload = payload if isinstance(payload, dict) else {}
    project = s._gcp_project_name(request.query_params.get("project") or payload.get("project") or payload.get("projectId"))
    name = str(payload.get("name") or payload.get("bucket") or "").strip()
    if not name:
        raise HTTPException(400, detail="Bucket name is required")
    bucket = s._gcp_storage_bucket_record(project, name, payload)
    s.gcp_storage_state.setdefault("buckets", {})[name] = bucket
    s.gcp_storage_state.setdefault("objects", {}).setdefault(name, {})
    # Mirror the bucket into the byte store so object uploads have a home.
    try:
        from core import gcp_gcs_store as gcs
        if gcs.available():
            gcs.ensure_bucket(name)
    except Exception:
        pass
    return s._gcp_storage_bucket_view(project, bucket)


def api_gcp_storage_get_bucket(bucket: str):
    s = _server()
    bucket_rec = s.gcp_storage_state.get("buckets", {}).get(bucket)
    if not bucket_rec:
        raise HTTPException(404, detail="Bucket not found")
    project = str(bucket_rec.get("project") or "cloudlearn")
    return s._gcp_storage_bucket_view(project, bucket_rec)


def api_gcp_storage_delete_bucket(bucket: str):
    s = _server()
    if bucket not in s.gcp_storage_state.get("buckets", {}):
        raise HTTPException(404, detail="Bucket not found")
    s.gcp_storage_state.setdefault("buckets", {}).pop(bucket, None)
    s.gcp_storage_state.setdefault("objects", {}).pop(bucket, None)
    return {"kind": "storage#empty", "deleted": True, "bucket": bucket}


def api_gcp_storage_list_objects(bucket: str, request: Request):
    s = _server()
    bucket_rec = s.gcp_storage_state.get("buckets", {}).get(bucket)
    if not bucket_rec:
        raise HTTPException(404, detail="Bucket not found")
    prefix = str(request.query_params.get("prefix") or "")
    objects = []
    for name, obj in s.gcp_storage_state.get("objects", {}).get(bucket, {}).items():
        if prefix and not name.startswith(prefix):
            continue
        objects.append(s._gcp_storage_object_view(str(bucket_rec.get("project") or "cloudlearn"), bucket, name, obj))
    objects.sort(key=lambda item: item.get("name", ""))
    return {"kind": "storage#objects", "items": objects, "prefixes": [], "nextPageToken": ""}


async def api_gcp_storage_create_object(bucket: str, request: Request):
    s = _server()
    bucket_rec = s.gcp_storage_state.get("buckets", {}).get(bucket)
    if not bucket_rec:
        raise HTTPException(404, detail="Bucket not found")
    project = str(bucket_rec.get("project") or "cloudlearn")
    ctype = request.headers.get("content-type", "") if request is not None else ""
    qp = request.query_params if request is not None else {}
    upload_type = str(qp.get("uploadType") or "")
    raw = await request.body() if request is not None else b""
    try:
        from core import gcp_gcs_store as gcs
        gcs_ok = gcs.available()
    except Exception:
        gcs_ok = False
    meta: dict = {}
    name = ""
    is_sdk_upload = upload_type in ("media", "multipart", "resumable") or "multipart/" in ctype or bool(qp.get("name"))
    if gcs_ok and is_sdk_upload:
        # Real SDK / gsutil upload: proxy the raw bytes to the byte store, which
        # handles media/multipart and returns the GCS object metadata.
        try:
            _status, body = gcs.upload(bucket, str(request.url.query), raw, ctype)
            meta = json.loads(body.decode("utf-8")) if body else {}
            name = str(meta.get("name") or qp.get("name") or "")
        except Exception as exc:
            raise HTTPException(502, detail=f"Object upload failed: {str(exc)[:160]}")
    else:
        # Console / Terraform JSON-body upload: {name, data, contentType}.
        try:
            payload = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        name = str(payload.get("name") or payload.get("object") or (qp.get("name") if qp else "") or "").strip()
        if not name:
            raise HTTPException(400, detail="Object name is required")
        data = payload.get("data", payload.get("content", ""))
        if not isinstance(data, str):
            data = json.dumps(data, default=str)
        ct = str(payload.get("contentType") or "text/plain")
        if gcs_ok:
            try:
                gcs.put_text(bucket, name, data, ct)
            except Exception:
                pass
        meta = {"size": str(len(data.encode("utf-8"))), "contentType": ct}
    rec = s._gcp_storage_object_record(bucket, name, {
        "contentType": meta.get("contentType") or "application/octet-stream",
        "size": meta.get("size"),
        "md5Hash": meta.get("md5Hash", ""),
        "crc32c": meta.get("crc32c", ""),
    })
    s.gcp_storage_state.setdefault("objects", {}).setdefault(bucket, {})[name] = rec
    return s._gcp_storage_object_view(project, bucket, name, rec)


def api_gcp_storage_get_object(bucket: str, object_name: str, request: Request = None):
    s = _server()
    bucket_rec = s.gcp_storage_state.get("buckets", {}).get(bucket)
    if not bucket_rec:
        raise HTTPException(404, detail="Object not found")
    qp = request.query_params if request is not None else {}
    if str(qp.get("alt") or "") == "media":
        # Stream the real object bytes back from the byte store.
        try:
            from core import gcp_gcs_store as gcs
            from starlette.responses import Response
            data, ctype = gcs.download(bucket, object_name)
            return Response(content=data, media_type=ctype)
        except Exception as exc:
            raise HTTPException(404, detail=f"Object media not available: {str(exc)[:120]}")
    obj = s.gcp_storage_state.get("objects", {}).get(bucket, {}).get(object_name)
    if not obj:
        raise HTTPException(404, detail="Object not found")
    return s._gcp_storage_object_view(str(bucket_rec.get("project") or "cloudlearn"), bucket, object_name, obj)


def api_gcp_storage_delete_object(bucket: str, object_name: str):
    s = _server()
    if bucket not in s.gcp_storage_state.get("objects", {}) or object_name not in s.gcp_storage_state["objects"][bucket]:
        raise HTTPException(404, detail="Object not found")
    try:
        from core import gcp_gcs_store as gcs
        gcs.delete(bucket, object_name)
    except Exception:
        pass
    del s.gcp_storage_state["objects"][bucket][object_name]
    return {"kind": "storage#empty", "deleted": True, "bucket": bucket, "object": object_name}


def api_gcp_sql_list_instances(project: str, request: Request):
    s = _server()
    project = s._gcp_project_name(project)
    instances = []
    for inst in s.gcp_sql_state.get("instances", {}).values():
        if str(inst.get("project") or project) != project:
            continue
        instances.append(s._gcp_sql_instance_view(project, inst))
    instances.sort(key=lambda item: item.get("name", ""))
    return {"kind": "sql#instancesList", "items": instances, "warnings": []}


async def api_gcp_sql_create_instance(project: str, request: Request):
    s = _server()
    project = s._gcp_project_name(project)
    payload = await request.json() if request is not None else {}
    payload = payload if isinstance(payload, dict) else {}
    instance = s._gcp_sql_instance_record(project, payload)
    if instance["name"] in s.gcp_sql_state.get("instances", {}):
        raise HTTPException(409, detail="Instance already exists")
    # Provision a real database on the backing OSS engine so applications can
    # connect over the normal wire protocol. Degrade to metadata-only if the
    # engine is unreachable (mirrors Compute Engine's simulated fallback).
    try:
        from core import gcp_sql_engine
        space_id = s._spaces_state().get("active_space_id", "")
        host = request.headers.get("host", "") if request is not None else ""
        endpoint = gcp_sql_engine.provision(
            space_id, project, instance["name"], instance.get("databaseVersion", ""),
            instance.get("masterUsername", "dbadmin"), instance.get("masterUserPassword", ""),
            host,
        )
        instance["_backend"] = endpoint
        instance["ipAddresses"] = [{"type": "PRIMARY", "ipAddress": endpoint["host"]}]
        instance["state"] = "RUNNABLE"
    except Exception as exc:
        instance["_backend"] = None
        instance["_backend_error"] = str(exc)[:200]
    s.gcp_sql_state.setdefault("instances", {})[instance["name"]] = instance
    return s._gcp_sql_instance_view(project, instance)


def api_gcp_sql_get_instance(project: str, instance: str):
    s = _server()
    project = s._gcp_project_name(project)
    rec = s.gcp_sql_state.get("instances", {}).get(instance)
    if not rec or str(rec.get("project") or project) != project:
        raise HTTPException(404, detail="Instance not found")
    return s._gcp_sql_instance_view(project, rec)


def api_gcp_sql_delete_instance(project: str, instance: str):
    s = _server()
    project = s._gcp_project_name(project)
    rec = s.gcp_sql_state.get("instances", {}).get(instance)
    if not rec or str(rec.get("project") or project) != project:
        raise HTTPException(404, detail="Instance not found")
    try:
        from core import gcp_sql_engine
        space_id = s._spaces_state().get("active_space_id", "")
        gcp_sql_engine.deprovision(space_id, project, instance, rec.get("databaseVersion", ""))
    except Exception:
        pass
    del s.gcp_sql_state["instances"][instance]
    return {"kind": "sql#operation", "operationType": "DELETE", "status": "DONE", "targetLink": f"{s._gcp_sql_root()}/projects/{project}/instances/{instance}"}


def api_gcp_sql_restart_instance(project: str, instance: str):
    s = _server()
    project = s._gcp_project_name(project)
    rec = s.gcp_sql_state.get("instances", {}).get(instance)
    if not rec or str(rec.get("project") or project) != project:
        raise HTTPException(404, detail="Instance not found")
    rec["state"] = "RUNNABLE"
    rec["updateTime"] = s._now()
    return {"kind": "sql#operation", "operationType": "RESTART", "status": "DONE", "targetLink": f"{s._gcp_sql_root()}/projects/{project}/instances/{instance}"}


def api_gcp_pubsub_list_topics(project: str):
    s = _server()
    project = s._gcp_project_name(project)
    topics = [s._gcp_pubsub_topic_view(project, topic) for topic in s.gcp_pubsub_state.get("topics", {}).values() if str(topic.get("project") or project) == project]
    topics.sort(key=lambda item: item.get("topicId", ""))
    return {"topics": topics, "nextPageToken": "", "kind": "pubsub#topicList"}


async def api_gcp_pubsub_create_topic(project: str, request: Request):
    s = _server()
    project = s._gcp_project_name(project)
    payload = await request.json() if request is not None else {}
    payload = payload if isinstance(payload, dict) else {}
    topic_id = str(payload.get("topicId") or payload.get("name") or payload.get("topic") or "").split("/")[-1].strip()
    if not topic_id:
        raise HTTPException(400, detail="Topic id is required")
    topic = s._gcp_pubsub_topic_record(project, topic_id, payload)
    s.gcp_pubsub_state.setdefault("topics", {})[topic_id] = topic
    default_sub_id = str(payload.get("subscriptionId") or topic_id).split("/")[-1].strip()
    if default_sub_id and default_sub_id not in s.gcp_pubsub_state.setdefault("subscriptions", {}):
        default_sub = s._gcp_pubsub_subscription_record(project, default_sub_id, {"topic": f"projects/{project}/topics/{topic_id}", "labels": payload.get("labels", {}) if isinstance(payload.get("labels"), dict) else {}, "ackDeadlineSeconds": payload.get("ackDeadlineSeconds", 10)})
        s.gcp_pubsub_state.setdefault("subscriptions", {})[default_sub_id] = default_sub
    return s._gcp_pubsub_topic_view(project, topic)


def api_gcp_pubsub_get_topic(project: str, topic: str):
    s = _server()
    project = s._gcp_project_name(project)
    topic = _strip_action_suffix(topic, ":publish")
    rec = s.gcp_pubsub_state.get("topics", {}).get(topic)
    if not rec or str(rec.get("project") or project) != project:
        raise HTTPException(404, detail="Topic not found")
    return s._gcp_pubsub_topic_view(project, rec)


async def api_gcp_pubsub_update_topic(project: str, topic: str, request: Request):
    s = _server()
    project = s._gcp_project_name(project)
    topic = _strip_action_suffix(topic, ":publish")
    rec = s.gcp_pubsub_state.get("topics", {}).get(topic)
    if not rec or str(rec.get("project") or project) != project:
        raise HTTPException(404, detail="Topic not found")
    payload = await request.json() if request is not None else {}
    payload = payload if isinstance(payload, dict) else {}
    if isinstance(payload.get("labels"), dict):
        rec["labels"] = payload["labels"]
    if "messageRetentionDuration" in payload:
        rec["messageRetentionDuration"] = str(payload.get("messageRetentionDuration") or rec.get("messageRetentionDuration") or "604800s")
    if "kmsKeyName" in payload:
        rec["kmsKeyName"] = str(payload.get("kmsKeyName") or "")
    rec["updateTime"] = s._now()
    s.gcp_pubsub_state.setdefault("topics", {})[topic] = rec
    return s._gcp_pubsub_topic_view(project, rec)


def api_gcp_pubsub_list_topic_messages(project: str, topic: str):
    s = _server()
    project = s._gcp_project_name(project)
    topic = _strip_action_suffix(topic, ":publish")
    rec = s.gcp_pubsub_state.get("topics", {}).get(topic)
    if not rec or str(rec.get("project") or project) != project:
        raise HTTPException(404, detail="Topic not found")
    messages = list(s.gcp_pubsub_state.setdefault("messages", {}).get(topic, []))
    return {"messages": messages, "kind": "pubsub#messageList"}


def api_gcp_pubsub_delete_topic(project: str, topic: str):
    s = _server()
    project = s._gcp_project_name(project)
    topic = _strip_action_suffix(topic, ":publish")
    rec = s.gcp_pubsub_state.get("topics", {}).get(topic)
    if not rec or str(rec.get("project") or project) != project:
        raise HTTPException(404, detail="Topic not found")
    del s.gcp_pubsub_state["topics"][topic]
    for sub_id, sub in list(s.gcp_pubsub_state.get("subscriptions", {}).items()):
        if str(sub.get("project") or project) == project and str(sub.get("topic") or "") == f"projects/{project}/topics/{topic}":
            del s.gcp_pubsub_state["subscriptions"][sub_id]
            s.gcp_pubsub_state.get("messages", {}).pop(sub_id, None)
    s.gcp_pubsub_state.get("messages", {}).pop(topic, None)
    return {"done": True}


async def api_gcp_pubsub_publish(project: str, topic: str, request: Request):
    s = _server()
    project = s._gcp_project_name(project)
    topic = _strip_action_suffix(topic, ":publish")
    rec = s.gcp_pubsub_state.get("topics", {}).get(topic)
    if not rec or str(rec.get("project") or project) != project:
        raise HTTPException(404, detail="Topic not found")
    payload = await request.json() if request is not None else {}
    payload = payload if isinstance(payload, dict) else {}
    messages = payload.get("messages", []) if isinstance(payload, dict) else []
    if not isinstance(messages, list):
        messages = []
    message_ids = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        message_id = s._id("msg")
        entry = {"messageId": message_id, "data": str(message.get("data") or ""), "attributes": message.get("attributes", {}) if isinstance(message.get("attributes"), dict) else {}, "publishTime": s._now(), "topic": topic, "orderingKey": str(message.get("orderingKey") or ""), "_publishedAt": time.time()}
        message_ids.append(message_id)
        s.gcp_pubsub_state.setdefault("messages", {}).setdefault(topic, []).append(entry)
        for sub in s.gcp_pubsub_state.get("subscriptions", {}).values():
            if str(sub.get("project") or project) != project or str(sub.get("topic") or "") != f"projects/{project}/topics/{topic}":
                continue
            s.gcp_pubsub_state.setdefault("messages", {}).setdefault(str(sub.get("subscriptionId")), []).append({**entry, "ackId": s._id("ack"), "subscription": str(sub.get("subscriptionId"))})
    return {"messageIds": message_ids}


def api_gcp_pubsub_list_subscriptions(project: str):
    s = _server()
    project = s._gcp_project_name(project)
    subs = [s._gcp_pubsub_subscription_view(project, sub) for sub in s.gcp_pubsub_state.get("subscriptions", {}).values() if str(sub.get("project") or project) == project]
    subs.sort(key=lambda item: item.get("subscriptionId", ""))
    return {"subscriptions": subs, "nextPageToken": "", "kind": "pubsub#subscriptionList"}


async def api_gcp_pubsub_create_subscription(project: str, request: Request, queue_name: str = ""):
    s = _server()
    project = s._gcp_project_name(project)
    payload = await request.json() if request is not None else {}
    payload = payload if isinstance(payload, dict) else {}
    sub_id = str(payload.get("subscriptionId") or payload.get("name") or queue_name or "").split("/")[-1].strip()
    if not sub_id:
        raise HTTPException(400, detail="Subscription id is required")
    sub = s._gcp_pubsub_subscription_record(project, sub_id, payload)
    if not sub.get("topic"):
        raise HTTPException(400, detail="Topic is required")
    s.gcp_pubsub_state.setdefault("subscriptions", {})[sub_id] = sub
    return s._gcp_pubsub_subscription_view(project, sub)


def api_gcp_pubsub_get_subscription(project: str, subscription: str):
    s = _server()
    project = s._gcp_project_name(project)
    subscription = _strip_action_suffix(subscription, ":purge", ":pull", ":acknowledge", ":modifyAckDeadline")
    rec = s.gcp_pubsub_state.get("subscriptions", {}).get(subscription)
    if not rec or str(rec.get("project") or project) != project:
        raise HTTPException(404, detail="Subscription not found")
    return s._gcp_pubsub_subscription_view(project, rec)


async def api_gcp_pubsub_patch_subscription(project: str, subscription: str, request: Request):
    """PATCH .../subscriptions/{sub} — update delivery settings on an existing subscription."""
    s = _server()
    project = s._gcp_project_name(project)
    subscription = _strip_action_suffix(subscription, ":purge", ":pull", ":acknowledge", ":modifyAckDeadline")
    rec = s.gcp_pubsub_state.get("subscriptions", {}).get(subscription)
    if not rec or str(rec.get("project") or project) != project:
        raise HTTPException(404, detail="Subscription not found")
    payload = await request.json() if request is not None else {}
    payload = payload if isinstance(payload, dict) else {}
    # Real GCP wraps the changes under "subscription" alongside an updateMask.
    body = payload.get("subscription") if isinstance(payload.get("subscription"), dict) else payload
    if "ackDeadlineSeconds" in body:
        try:
            rec["ackDeadlineSeconds"] = int(body.get("ackDeadlineSeconds"))
        except (TypeError, ValueError):
            pass
    if "messageRetentionDuration" in body and body.get("messageRetentionDuration"):
        rec["messageRetentionDuration"] = str(body.get("messageRetentionDuration"))
    if "retainAckedMessages" in body:
        rec["retainAckedMessages"] = bool(body.get("retainAckedMessages"))
    if isinstance(body.get("labels"), dict):
        rec["labels"] = body["labels"]
    rec["updateTime"] = s._now()
    s.gcp_pubsub_state.setdefault("subscriptions", {})[subscription] = rec
    return s._gcp_pubsub_subscription_view(project, rec)


def api_gcp_pubsub_list_subscription_messages(project: str, subscription: str):
    s = _server()
    project = s._gcp_project_name(project)
    subscription = _strip_action_suffix(subscription, ":purge", ":pull", ":acknowledge", ":modifyAckDeadline")
    rec = s.gcp_pubsub_state.get("subscriptions", {}).get(subscription)
    if not rec or str(rec.get("project") or project) != project:
        raise HTTPException(404, detail="Subscription not found")
    messages = list(s.gcp_pubsub_state.setdefault("messages", {}).get(subscription, []))
    return {"receivedMessages": messages, "kind": "pubsub#receivedMessageList"}


def api_gcp_pubsub_purge_subscription(project: str, subscription: str):
    s = _server()
    project = s._gcp_project_name(project)
    subscription = _strip_action_suffix(subscription, ":purge", ":pull", ":acknowledge", ":modifyAckDeadline")
    rec = s.gcp_pubsub_state.get("subscriptions", {}).get(subscription)
    if not rec or str(rec.get("project") or project) != project:
        raise HTTPException(404, detail="Subscription not found")
    s.gcp_pubsub_state.setdefault("messages", {})[subscription] = []
    return {"done": True}


def api_gcp_pubsub_delete_subscription(project: str, subscription: str):
    s = _server()
    project = s._gcp_project_name(project)
    subscription = _strip_action_suffix(subscription, ":purge", ":pull", ":acknowledge", ":modifyAckDeadline")
    rec = s.gcp_pubsub_state.get("subscriptions", {}).get(subscription)
    if not rec or str(rec.get("project") or project) != project:
        raise HTTPException(404, detail="Subscription not found")
    del s.gcp_pubsub_state["subscriptions"][subscription]
    s.gcp_pubsub_state.get("messages", {}).pop(subscription, None)
    return {"done": True}


def _parse_duration_seconds(dur: str) -> int:
    dur = str(dur or "").strip()
    if not dur:
        return 0
    try:
        return int(float(dur[:-1] if dur.endswith("s") else dur))
    except Exception:
        return 0


def _gcp_pubsub_retention_seconds(s, sub_rec: dict) -> int:
    """Resolve message retention (seconds) from the subscription, else its topic.
    0 = no expiry (default), so retention only applies when explicitly set."""
    dur = str(sub_rec.get("messageRetentionDuration") or "")
    if not dur:
        topic_path = str(sub_rec.get("topic") or "")
        topic_id = topic_path.split("/")[-1]
        topics = s.gcp_pubsub_state.get("topics", {})
        topic = topics.get(topic_id) or topics.get(topic_path) or {}
        dur = str(topic.get("messageRetentionDuration") or "")
    return _parse_duration_seconds(dur)


async def api_gcp_pubsub_pull(project: str, subscription: str, request: Request):
    s = _server()
    project = s._gcp_project_name(project)
    subscription = _strip_action_suffix(subscription, ":purge", ":pull", ":acknowledge", ":modifyAckDeadline")
    rec = s.gcp_pubsub_state.get("subscriptions", {}).get(subscription)
    if not rec or str(rec.get("project") or project) != project:
        raise HTTPException(404, detail="Subscription not found")
    payload = await request.json() if request is not None else {}
    payload = payload if isinstance(payload, dict) else {}
    max_messages = int(payload.get("maxMessages") or payload.get("max_messages") or 10)
    # Lease messages for the ack deadline: a pulled-but-unacked message is hidden
    # until its deadline expires, then redelivered (with an incremented delivery
    # attempt). Acked messages are removed entirely. This gives real at-least-once
    # delivery with deadline-based redelivery instead of returning the same set.
    now = time.time()
    deadline = int(rec.get("ackDeadlineSeconds") or 10)
    queue = s.gcp_pubsub_state.get("messages", {}).get(subscription, [])
    # Retention: drop messages older than the topic's messageRetentionDuration.
    retention = _gcp_pubsub_retention_seconds(s, rec)
    if retention > 0:
        kept = [m for m in queue if not (m.get("_publishedAt") and (now - float(m["_publishedAt"])) > retention)]
        if len(kept) != len(queue):
            queue[:] = kept
    received = []
    blocked_keys: set[str] = set()
    for item in queue:
        if len(received) >= max_messages:
            break
        # Ordering: per orderingKey deliver one-at-a-time in publish order — a
        # later message for a key is held until the earlier one is acked.
        key = str(item.get("orderingKey") or "")
        if key and key in blocked_keys:
            continue
        if float(item.get("_visibleAt") or 0) > now:
            if key:
                blocked_keys.add(key)  # head is leased -> hold the rest of this key
            continue
        item["_visibleAt"] = now + deadline
        item["_deliveryAttempt"] = int(item.get("_deliveryAttempt") or 0) + 1
        if key:
            blocked_keys.add(key)
        received.append({
            "ackId": item.get("ackId") or s._id("ack"),
            "deliveryAttempt": item["_deliveryAttempt"],
            "message": {
                "data": item.get("data", ""),
                "messageId": item.get("messageId") or s._id("msg"),
                "publishTime": item.get("publishTime") or s._now(),
                "attributes": item.get("attributes", {}),
                "orderingKey": key,
            },
        })
    return {"receivedMessages": received}


async def api_gcp_pubsub_ack(project: str, subscription: str, request: Request, receipt_handle: str = ""):
    s = _server()
    project = s._gcp_project_name(project)
    subscription = _strip_action_suffix(subscription, ":purge", ":pull", ":acknowledge", ":modifyAckDeadline")
    if subscription not in s.gcp_pubsub_state.get("subscriptions", {}):
        raise HTTPException(404, detail="Subscription not found")
    body = await request.json() if request is not None else {}
    body = body if isinstance(body, dict) else {}
    ack_ids = body.get("ackIds") if isinstance(body, dict) else []
    if not isinstance(ack_ids, list):
        ack_ids = []
    queue = s.gcp_pubsub_state.setdefault("messages", {}).get(subscription, [])
    s.gcp_pubsub_state.setdefault("messages", {})[subscription] = [item for item in queue if item.get("ackId") not in set(map(str, ack_ids)) and item.get("ackId") != receipt_handle]
    return {"acknowledged": True}


async def api_gcp_pubsub_modify_ack_deadline(project: str, subscription: str, request: Request):
    s = _server()
    project = s._gcp_project_name(project)
    subscription = _strip_action_suffix(subscription, ":purge", ":pull", ":acknowledge", ":modifyAckDeadline")
    if subscription not in s.gcp_pubsub_state.get("subscriptions", {}):
        raise HTTPException(404, detail="Subscription not found")
    payload = await request.json() if request is not None else {}
    payload = payload if isinstance(payload, dict) else {}
    ack_ids = payload.get("ackIds") if isinstance(payload, dict) else []
    if not isinstance(ack_ids, list):
        ack_ids = []
    ack_ids = [str(ack_id) for ack_id in ack_ids if ack_id]
    deadline = int(payload.get("ackDeadlineSeconds") or 0) if isinstance(payload, dict) else 0
    queue = s.gcp_pubsub_state.setdefault("messages", {}).get(subscription, [])
    # Re-lease the named messages: deadline>0 extends the lease, deadline==0 makes
    # them immediately visible again (nack -> instant redelivery).
    now = time.time()
    for item in queue:
        if item.get("ackId") in ack_ids:
            item["_visibleAt"] = now + deadline
    return {}


def api_gcp_pubsub_list_topic_subscriptions(project: str, topic: str):
    s = _server()
    project = s._gcp_project_name(project)
    topic_name = f"projects/{project}/topics/{topic}"
    subscriptions = []
    for sub in s.gcp_pubsub_state.get("subscriptions", {}).values():
        if str(sub.get("project") or project) != project:
            continue
        if str(sub.get("topic") or "") != topic_name:
            continue
        subscriptions.append(f"projects/{project}/subscriptions/{sub.get('subscriptionId') or sub.get('name')}")
    subscriptions.sort()
    return {"subscriptions": subscriptions, "nextPageToken": ""}


def api_gcp_pubsub_list_schemas(project: str):
    return _server().api_gcp_pubsub_list_schemas(project)


async def api_gcp_pubsub_create_schema(project: str, request: Request):
    return await _server().api_gcp_pubsub_create_schema(project, request)


def api_gcp_pubsub_delete_schema(project: str, schema: str):
    return _server().api_gcp_pubsub_delete_schema(project, schema)


def api_gcp_firestore_list_root_documents(project: str, database: str):
    s = _server()
    project = s._gcp_project_name(project)
    database = str(database or "(default)")
    docs = s._gcp_firestore_engine().list_root_documents(project, database)
    return {"documents": docs, "nextPageToken": "", "kind": "firestore#documents"}


def api_gcp_firestore_list_documents(project: str, database: str, collection: str):
    s = _server()
    project = s._gcp_project_name(project)
    database = str(database or "(default)")
    docs = s._gcp_firestore_engine().list_documents(project, database, collection)
    return {"documents": docs, "nextPageToken": "", "kind": "firestore#documents"}


async def api_gcp_firestore_create_document(project: str, database: str, collection: str, request: Request):
    s = _server()
    project = s._gcp_project_name(project)
    database = str(database or "(default)")
    payload = await request.json() if request is not None else {}
    payload = payload if isinstance(payload, dict) else {}
    query_doc_id = request.query_params.get("documentId") if request is not None else ""
    doc_id = str(payload.get("name") or payload.get("documentId") or query_doc_id or s._id("doc"))
    if "/" in doc_id:
        doc_id = doc_id.rsplit("/", 1)[-1]
    fields = payload.get("fields", {}) if isinstance(payload.get("fields"), dict) else {}
    return s._gcp_firestore_engine().create_document(project, database, collection, s._gcp_firestore_normalize_fields(fields), doc_id)


def api_gcp_firestore_get_document(project: str, database: str, collection: str, doc_id: str):
    s = _server()
    project = s._gcp_project_name(project)
    database = str(database or "(default)")
    doc = s._gcp_firestore_engine().get_document(project, database, collection, doc_id)
    if not doc:
        raise HTTPException(404, detail="Document not found")
    return doc


def api_gcp_firestore_delete_document(project: str, database: str, collection: str, doc_id: str):
    s = _server()
    project = s._gcp_project_name(project)
    database = str(database or "(default)")
    try:
        s._gcp_firestore_engine().delete_document(project, database, collection, doc_id)
    except KeyError:
        raise HTTPException(404, detail="Document not found")
    return {"done": True}


async def api_gcp_firestore_update_document(project: str, database: str, collection: str, doc_id: str, request: Request):
    s = _server()
    project = s._gcp_project_name(project)
    database = str(database or "(default)")
    payload = await request.json() if request is not None else {}
    payload = payload if isinstance(payload, dict) else {}
    fields = payload.get("fields") if isinstance(payload.get("fields"), dict) else {}
    try:
        doc = s._gcp_firestore_engine().update_document(project, database, collection, doc_id, s._gcp_firestore_normalize_fields(fields))
    except KeyError:
        raise HTTPException(404, detail="Document not found")
    return doc


def _fs_path_parts(fs_path: str) -> list[str]:
    return [p for p in str(fs_path or "").split("/") if p]


def api_gcp_firestore_doc_get(project: str, database: str, fs_path: str):
    """GET a Firestore path: odd segment count = collection (list), even = document.
    Supports subcollections, e.g. users/alice/orders (list) or users/alice (get)."""
    parts = _fs_path_parts(fs_path)
    if not parts:
        return api_gcp_firestore_list_root_documents(project, database)
    if len(parts) % 2 == 1:
        return api_gcp_firestore_list_documents(project, database, "/".join(parts))
    return api_gcp_firestore_get_document(project, database, "/".join(parts[:-1]), parts[-1])


async def api_gcp_firestore_doc_post(project: str, database: str, fs_path: str, request: Request):
    """POST to a collection path creates a document (handles nested subcollections)."""
    if str(fs_path or "").endswith(":runQuery"):
        return await api_gcp_firestore_run_query(project, database, request, collection="/".join(_fs_path_parts(fs_path[:-len(":runQuery")])))
    parts = _fs_path_parts(fs_path)
    if parts and len(parts) % 2 == 1:
        return await api_gcp_firestore_create_document(project, database, "/".join(parts), request)
    # even path -> treat as an update of that document
    return await api_gcp_firestore_update_document(project, database, "/".join(parts[:-1]), parts[-1], request)


def api_gcp_firestore_doc_delete(project: str, database: str, fs_path: str):
    parts = _fs_path_parts(fs_path)
    if len(parts) >= 2 and len(parts) % 2 == 0:
        return api_gcp_firestore_delete_document(project, database, "/".join(parts[:-1]), parts[-1])
    raise HTTPException(400, detail="Path does not address a document")


async def api_gcp_firestore_doc_put(project: str, database: str, fs_path: str, request: Request):
    parts = _fs_path_parts(fs_path)
    if len(parts) >= 2 and len(parts) % 2 == 0:
        return await api_gcp_firestore_update_document(project, database, "/".join(parts[:-1]), parts[-1], request)
    raise HTTPException(400, detail="Path does not address a document")


async def api_gcp_firestore_run_query(project: str, database: str, request: Request, collection: str = ""):
    s = _server()
    project = s._gcp_project_name(project)
    database = str(database or "(default)")
    payload = await request.json() if request is not None else {}
    payload = payload if isinstance(payload, dict) else {}
    query = payload.get("structuredQuery", {}) if isinstance(payload, dict) else {}
    query = query if isinstance(query, dict) else {}
    selectors = query.get("from", [])
    if collection:
        collection_id = collection
    elif isinstance(selectors, list) and selectors and isinstance(selectors[0], dict):
        collection_id = str(selectors[0].get("collectionId") or "")
    else:
        collection_id = ""
    limit = int(query.get("limit") or payload.get("limit") or 50)
    where = query.get("where") if isinstance(query.get("where"), dict) else {}
    filters: list = []

    def _add_field_filter(ff):
        if not isinstance(ff, dict):
            return
        field = ff.get("field") if isinstance(ff.get("field"), dict) else {}
        fpath = str(field.get("fieldPath") or "")
        if not fpath:
            return
        filters.append({"field": fpath, "op": str(ff.get("op") or "EQUAL"),
                        "value": s._gcp_firestore_plain_value(ff.get("value"))})

    if isinstance(where, dict):
        _add_field_filter(where.get("fieldFilter"))
        composite = where.get("compositeFilter") if isinstance(where.get("compositeFilter"), dict) else {}
        for sub in (composite.get("filters") or []):
            if isinstance(sub, dict):
                _add_field_filter(sub.get("fieldFilter"))
    order_by = None
    order_dir = "ASCENDING"
    order_specs = query.get("orderBy")
    if isinstance(order_specs, list) and order_specs and isinstance(order_specs[0], dict):
        of = order_specs[0].get("field") if isinstance(order_specs[0].get("field"), dict) else {}
        order_by = str(of.get("fieldPath") or "") or None
        order_dir = str(order_specs[0].get("direction") or "ASCENDING")
    field_name = filters[0]["field"] if filters else ""
    result = s._gcp_firestore_engine().run_query(project, database, collection_id, limit=limit,
                                                 filters=filters, order_by=order_by, order_dir=order_dir)
    if collection_id and field_name:
        index_key = f"{project}:{database}:{collection_id}:{field_name}:{query.get('orderBy', 'ASCENDING')}"
        s.gcp_firestore_state.setdefault("indexes", {}).setdefault(index_key, s._gcp_firestore_index_record(project, database, collection_id, {
            "name": index_key.split(":")[-1],
            "fields": [{"fieldPath": field_name, "order": str(query.get("orderBy") or "ASCENDING")}],
            "queryScope": "COLLECTION",
            "description": f"Auto-generated from query on {collection_id}.{field_name}",
        }))
    return result


def api_gcp_firestore_list_indexes(project: str, database: str, collection: str = ""):
    s = _server()
    project = s._gcp_project_name(project)
    database = str(database or "(default)")
    indexes = []
    for index in s.gcp_firestore_state.get("indexes", {}).values():
        if str(index.get("project") or project) != project or str(index.get("database") or database) != database:
            continue
        if collection and str(index.get("collection") or "") != collection:
            continue
        indexes.append(s._gcp_firestore_index_view(index))
    indexes.sort(key=lambda item: item.get("name", ""))
    return {"indexes": indexes, "kind": "firestore#indexList"}


async def api_gcp_firestore_create_index(project: str, database: str, collection: str, request: Request):
    s = _server()
    project = s._gcp_project_name(project)
    database = str(database or "(default)")
    payload = await request.json() if request is not None else {}
    payload = payload if isinstance(payload, dict) else {}
    index = s._gcp_firestore_index_record(project, database, collection, payload)
    s.gcp_firestore_state.setdefault("indexes", {})[f"{project}:{database}:{collection}:{index['name']}"] = index
    return s._gcp_firestore_index_view(index)


def api_gcp_firestore_delete_index(project: str, database: str, collection: str, index_name: str):
    s = _server()
    project = s._gcp_project_name(project)
    database = str(database or "(default)")
    key = f"{project}:{database}:{collection}:{index_name}"
    if key not in s.gcp_firestore_state.get("indexes", {}):
        raise HTTPException(404, detail="Index not found")
    del s.gcp_firestore_state["indexes"][key]
    return {"kind": "firestore#index", "deleted": True, "name": index_name}


def api_gcp_functions_list(project: str, location: str = "us-central1"):
    s = _server()
    project = s._gcp_project_name(project)
    location = s._gcp_location_name(location)
    functions = []
    for fn in s.gcp_functions_state.get("functions", {}).values():
        if str(fn.get("project") or project) != project or str(fn.get("location") or location) != location:
            continue
        functions.append(s._gcp_functions_view(project, location, fn))
    functions.sort(key=lambda item: item.get("name", ""))
    return {"functions": functions, "nextPageToken": "", "kind": "cloudfunctions#listFunctionsResponse"}


async def api_gcp_functions_create(project: str, request: Request, location: str = "us-central1"):
    s = _server()
    project = s._gcp_project_name(project)
    location = s._gcp_location_name(location)
    payload = await request.json() if request is not None else {}
    payload = payload if isinstance(payload, dict) else {}
    fn = s._gcp_functions_record(project, location, payload)
    s.gcp_functions_state.setdefault("functions", {})[fn["name"]] = fn
    return s._gcp_functions_view(project, location, fn)


async def api_gcp_functions_update(project: str, location: str, function: str, request: Request):
    s = _server()
    project = s._gcp_project_name(project)
    location = s._gcp_location_name(location)
    fn = s.gcp_functions_state.get("functions", {}).get(function)
    if not fn or str(fn.get("project") or project) != project or str(fn.get("location") or location) != location:
        raise HTTPException(404, detail="Function not found")
    payload = await request.json() if request is not None else {}
    payload = payload if isinstance(payload, dict) else {}
    if "code" in payload:
        fn["code"] = str(payload.get("code") or "")
    if "runtime" in payload:
        fn["runtime"] = str(payload.get("runtime") or fn.get("runtime") or "python311")
        fn.setdefault("buildConfig", {})["runtime"] = fn["runtime"]
    if "handler" in payload:
        fn["entryPoint"] = str(payload.get("handler") or payload.get("entryPoint") or fn.get("entryPoint") or "handler")
        fn.setdefault("buildConfig", {})["entryPoint"] = fn["entryPoint"]
    if "description" in payload:
        fn["description"] = str(payload.get("description") or "")
    if "role" in payload:
        fn["role"] = str(payload.get("role") or "")
    if "timeout" in payload or "timeoutSeconds" in payload:
        timeout = int(payload.get("timeout") or payload.get("timeoutSeconds") or fn.get("serviceConfig", {}).get("timeoutSeconds") or 60)
        fn.setdefault("serviceConfig", {})["timeoutSeconds"] = timeout
        fn["timeout"] = timeout
    if "memory_size" in payload or "availableMemory" in payload:
        memory = str(payload.get("memory_size") or payload.get("availableMemory") or fn.get("serviceConfig", {}).get("availableMemory") or "256M")
        fn.setdefault("serviceConfig", {})["availableMemory"] = memory if memory.endswith("M") or memory.endswith("Mi") else f"{memory}M"
        fn["memory_size"] = int(str(memory).rstrip("MmIi")) if str(memory).rstrip("MmIi").isdigit() else 256
    if isinstance(payload.get("environmentVariables"), dict):
        fn["environmentVariables"] = payload["environmentVariables"]
    if isinstance(payload.get("labels"), dict):
        fn["labels"] = payload["labels"]
    fn["updateTime"] = s._now()
    s.gcp_functions_state.setdefault("functions", {})[function] = fn
    return s._gcp_functions_view(project, location, fn)


async def api_gcp_functions_publish_version(project: str, location: str, function: str, request: Request):
    s = _server()
    project = s._gcp_project_name(project)
    location = s._gcp_location_name(location)
    fn = s.gcp_functions_state.get("functions", {}).get(function)
    if not fn or str(fn.get("project") or project) != project or str(fn.get("location") or location) != location:
        raise HTTPException(404, detail="Function not found")
    payload = await request.json() if request is not None else {}
    payload = payload if isinstance(payload, dict) else {}
    version_id = str(len(fn.get("versions", [])) + 1)
    version = {"version": version_id, "state": "Active", "description": str(payload.get("description") or ""), "created": s._now(), "code_sha256": s._id("sha"), "is_latest": True}
    versions = [v for v in fn.get("versions", []) if isinstance(v, dict)]
    for item in versions:
        item["is_latest"] = False
    versions.append(version)
    fn["versions"] = versions
    fn["updateTime"] = s._now()
    s.gcp_functions_state.setdefault("functions", {})[function] = fn
    return {"version": version}


def api_gcp_functions_list_versions(project: str, location: str, function: str):
    s = _server()
    project = s._gcp_project_name(project)
    location = s._gcp_location_name(location)
    fn = s.gcp_functions_state.get("functions", {}).get(function)
    if not fn or str(fn.get("project") or project) != project or str(fn.get("location") or location) != location:
        raise HTTPException(404, detail="Function not found")
    return {"versions": list(fn.get("versions", []) if isinstance(fn.get("versions"), list) else [])}


def api_gcp_functions_list_invocations(project: str, location: str, function: str):
    s = _server()
    project = s._gcp_project_name(project)
    location = s._gcp_location_name(location)
    fn = s.gcp_functions_state.get("functions", {}).get(function)
    if not fn or str(fn.get("project") or project) != project or str(fn.get("location") or location) != location:
        raise HTTPException(404, detail="Function not found")
    return {"invocations": list(fn.get("invocations", []) if isinstance(fn.get("invocations"), list) else [])}


def api_gcp_functions_get_policy(project: str, location: str, function: str):
    s = _server()
    project = s._gcp_project_name(project)
    location = s._gcp_location_name(location)
    function = _strip_action_suffix(function, ":getIamPolicy", ":setIamPolicy", ":call")
    fn = s.gcp_functions_state.get("functions", {}).get(function)
    if not fn or str(fn.get("project") or project) != project or str(fn.get("location") or location) != location:
        raise HTTPException(404, detail="Function not found")
    return {"version": 1, "etag": "", "bindings": fn.get("permissions", []) if isinstance(fn.get("permissions"), list) else []}


async def api_gcp_functions_set_policy(project: str, location: str, function: str, request: Request):
    s = _server()
    project = s._gcp_project_name(project)
    location = s._gcp_location_name(location)
    function = _strip_action_suffix(function, ":getIamPolicy", ":setIamPolicy", ":call")
    fn = s.gcp_functions_state.get("functions", {}).get(function)
    if not fn or str(fn.get("project") or project) != project or str(fn.get("location") or location) != location:
        raise HTTPException(404, detail="Function not found")
    payload = await request.json() if request is not None else {}
    payload = payload if isinstance(payload, dict) else {}
    bindings = payload.get("bindings", []) if isinstance(payload.get("bindings"), list) else []
    fn["permissions"] = bindings
    fn["updateTime"] = s._now()
    return {"version": int(payload.get("version") or 1), "etag": str(payload.get("etag") or ""), "bindings": bindings}


def api_gcp_functions_get(project: str, location: str, function: str):
    s = _server()
    project = s._gcp_project_name(project)
    location = s._gcp_location_name(location)
    function = _strip_action_suffix(function, ":getIamPolicy", ":setIamPolicy", ":call")
    fn = s.gcp_functions_state.get("functions", {}).get(function)
    if not fn or str(fn.get("project") or project) != project or str(fn.get("location") or location) != location:
        raise HTTPException(404, detail="Function not found")
    return s._gcp_functions_view(project, location, fn)


def api_gcp_functions_delete(project: str, location: str, function: str):
    s = _server()
    project = s._gcp_project_name(project)
    location = s._gcp_location_name(location)
    function = _strip_action_suffix(function, ":getIamPolicy", ":setIamPolicy", ":call")
    fn = s.gcp_functions_state.get("functions", {}).get(function)
    if not fn or str(fn.get("project") or project) != project or str(fn.get("location") or location) != location:
        raise HTTPException(404, detail="Function not found")
    del s.gcp_functions_state["functions"][function]
    return {"done": True}


async def api_gcp_functions_call(project: str, location: str, function: str, request: Request):
    s = _server()
    project = s._gcp_project_name(project)
    location = s._gcp_location_name(location)
    function = _strip_action_suffix(function, ":getIamPolicy", ":setIamPolicy", ":call")
    fn = s.gcp_functions_state.get("functions", {}).get(function)
    if not fn or str(fn.get("project") or project) != project or str(fn.get("location") or location) != location:
        raise HTTPException(404, detail="Function not found")
    payload = await request.json() if request is not None else {}
    payload = payload if isinstance(payload, dict) else {}
    # Actually execute the uploaded source with the request payload.
    event = payload.get("data") if isinstance(payload.get("data"), (dict, list)) else payload
    try:
        from core import gcp_function_runtime
        timeout = int(fn.get("serviceConfig", {}).get("timeoutSeconds") or fn.get("timeout") or 30)
        outcome = gcp_function_runtime.execute(
            fn.get("code", ""), fn.get("entryPoint", "handler"), fn.get("runtime", "python311"),
            event, timeout=min(max(timeout, 1), 120),
        )
    except Exception as exc:
        outcome = {"status": "ERROR", "error": str(exc)[:300], "result": None, "logs": ""}
    invocation = {
        "id": s._id("inv"), "timestamp": s._now(), "request": payload,
        "response": outcome.get("result"), "status": outcome.get("status", "SUCCESS"),
        "error": outcome.get("error", ""), "logs": outcome.get("logs", ""),
    }
    fn.setdefault("invocations", []).append(invocation)
    return {"executionId": invocation["id"], "status": invocation["status"],
            "result": invocation["response"], "error": invocation["error"], "logs": invocation["logs"]}


def api_gcp_apigw_list_apis(project: str, location: str = "global"):
    s = _server()
    project = s._gcp_project_name(project)
    location = s._gcp_location_name(location, "global")
    apis = [s._gcp_apigateway_api_view(project, location, api) for api in s.gcp_apigw_state.get("apis", {}).values() if str(api.get("project") or project) == project and str(api.get("location") or location) == location]
    apis.sort(key=lambda item: item.get("name", ""))
    return {"apis": apis, "nextPageToken": "", "kind": "apigateway#listApisResponse"}


async def api_gcp_apigw_create_api(project: str, request: Request, location: str = "global"):
    s = _server()
    project = s._gcp_project_name(project)
    location = s._gcp_location_name(location, "global")
    payload = await request.json() if request is not None else {}
    payload = payload if isinstance(payload, dict) else {}
    api = s._gcp_apigw_api_record(project, location, payload)
    s.gcp_apigw_state.setdefault("apis", {})[api["name"]] = api
    return s._gcp_apigateway_api_view(project, location, api)


def api_gcp_apigw_get_api(project: str, location: str, api: str):
    s = _server()
    project = s._gcp_project_name(project)
    location = s._gcp_location_name(location, "global")
    rec = s.gcp_apigw_state.get("apis", {}).get(api)
    if not rec or str(rec.get("project") or project) != project or str(rec.get("location") or location) != location:
        raise HTTPException(404, detail="API not found")
    return s._gcp_apigateway_api_view(project, location, rec)


def api_gcp_apigw_delete_api(project: str, location: str, api: str):
    s = _server()
    project = s._gcp_project_name(project)
    location = s._gcp_location_name(location, "global")
    rec = s.gcp_apigw_state.get("apis", {}).get(api)
    if not rec or str(rec.get("project") or project) != project or str(rec.get("location") or location) != location:
        raise HTTPException(404, detail="API not found")
    del s.gcp_apigw_state["apis"][api]
    return {"done": True}


def api_gcp_apigw_list_configs(project: str, location: str = "global", api: str = ""):
    s = _server()
    project = s._gcp_project_name(project)
    location = s._gcp_location_name(location, "global")
    cfgs = [s._gcp_apigateway_config_view(project, location, cfg) for cfg in s.gcp_apigw_state.get("configs", {}).values() if str(cfg.get("project") or project) == project and str(cfg.get("location") or location) == location and (not api or str(cfg.get("api") or "") == api)]
    cfgs.sort(key=lambda item: item.get("name", ""))
    return {"apiConfigs": cfgs, "nextPageToken": ""}


async def api_gcp_apigw_create_config(project: str, request: Request, location: str = "global", api: str = ""):
    s = _server()
    project = s._gcp_project_name(project)
    location = s._gcp_location_name(location, "global")
    payload = await request.json() if request is not None else {}
    payload = payload if isinstance(payload, dict) else {}
    if api and not payload.get("api"):
        payload["api"] = api
    cfg = s._gcp_apigw_cfg_record(project, location, payload)
    s.gcp_apigw_state.setdefault("configs", {})[cfg["name"]] = cfg
    return s._gcp_apigateway_config_view(project, location, cfg)


def api_gcp_apigw_list_gateways(project: str, location: str = "global", api: str = ""):
    s = _server()
    project = s._gcp_project_name(project)
    location = s._gcp_location_name(location, "global")
    gws = [s._gcp_apigateway_gateway_view(project, location, gw) for gw in s.gcp_apigw_state.get("gateways", {}).values() if str(gw.get("project") or project) == project and str(gw.get("location") or location) == location and (not api or str(gw.get("apiConfig") or "") == api)]
    gws.sort(key=lambda item: item.get("name", ""))
    return {"gateways": gws, "nextPageToken": ""}


async def api_gcp_apigw_create_gateway(project: str, request: Request, location: str = "global", api: str = ""):
    s = _server()
    project = s._gcp_project_name(project)
    location = s._gcp_location_name(location, "global")
    payload = await request.json() if request is not None else {}
    payload = payload if isinstance(payload, dict) else {}
    if api and not payload.get("apiConfig"):
        payload["apiConfig"] = api
    gw = s._gcp_apigw_gateway_record(project, location, payload)
    s.gcp_apigw_state.setdefault("gateways", {})[gw["name"]] = gw
    return s._gcp_apigateway_gateway_view(project, location, gw)


def api_gcp_vpc_list_networks(project: str):
    s = _server()
    project = s._gcp_project_name(project)
    networks = []
    for network in s.gcp_vpc_state.get("networks", {}).values():
        if str(network.get("project") or project) != project:
            continue
        network_name = str(network.get("name") or "")
        networks.append({"kind": "compute#network", "id": str(network.get("id") or s._gcp_compute_numeric_id(f"{project}:{network_name}")), "creationTimestamp": network.get("createTime", s._now()), "name": network_name, "description": network.get("description", ""), "IPv4Range": network.get("IPv4Range", ""), "gatewayIPv4": network.get("gatewayIPv4", ""), "selfLink": f"{s._gcp_compute_network_root()}/projects/{project}/global/networks/{network_name}", "selfLinkWithId": network.get("selfLinkWithId", f"{s._gcp_compute_network_root()}/projects/{project}/global/networks/{network_name}?id={network.get('id') or s._gcp_compute_numeric_id(f'{project}:{network_name}')}"), "autoCreateSubnetworks": bool(network.get("autoCreateSubnetworks", True)), "subnetworks": network.get("subnetworks", []), "peerings": network.get("peerings", []), "routingConfig": {"routingMode": network.get("routingMode", "REGIONAL")}})
    return {"kind": "compute#networkList", "items": networks}


async def api_gcp_vpc_create_network(project: str, request: Request):
    s = _server()
    project = s._gcp_project_name(project)
    payload = await request.json() if request is not None else {}
    payload = payload if isinstance(payload, dict) else {}
    name = str(payload.get("name") or payload.get("network") or "").strip()
    if not name:
        raise HTTPException(400, detail="Network name is required")
    rec = {"id": s._gcp_compute_numeric_id(f"{project}:{name}"), "name": name, "project": project, "description": str(payload.get("description") or ""), "IPv4Range": str(payload.get("IPv4Range") or ""), "gatewayIPv4": str(payload.get("gatewayIPv4") or ""), "autoCreateSubnetworks": bool(payload.get("autoCreateSubnetworks", True)), "routingMode": str(payload.get("routingMode") or "REGIONAL"), "subnetworks": payload.get("subnetworks", []) if isinstance(payload.get("subnetworks"), list) else [], "peerings": payload.get("peerings", []) if isinstance(payload.get("peerings"), list) else [], "createTime": s._now()}
    s.gcp_vpc_state.setdefault("networks", {})[name] = rec
    return {"kind": "compute#network", "id": rec["id"], "creationTimestamp": rec["createTime"], "name": name, "description": rec["description"], "IPv4Range": rec["IPv4Range"], "gatewayIPv4": rec["gatewayIPv4"], "selfLink": f"{s._gcp_compute_network_root()}/projects/{project}/global/networks/{name}", "selfLinkWithId": f"{s._gcp_compute_network_root()}/projects/{project}/global/networks/{name}?id={rec['id']}", "autoCreateSubnetworks": rec["autoCreateSubnetworks"], "subnetworks": rec["subnetworks"], "peerings": rec["peerings"], "routingConfig": {"routingMode": rec["routingMode"]}}


def api_gcp_vpc_get_network(project: str, network: str):
    s = _server()
    project = s._gcp_project_name(project)
    rec = s.gcp_vpc_state.get("networks", {}).get(network)
    if not rec or str(rec.get("project") or project) != project:
        raise HTTPException(404, detail="Network not found")
    return {"kind": "compute#network", "id": rec.get("id", s._gcp_compute_numeric_id(f"{project}:{network}")), "creationTimestamp": rec.get("createTime", s._now()), "name": rec["name"], "description": rec.get("description", ""), "IPv4Range": rec.get("IPv4Range", ""), "gatewayIPv4": rec.get("gatewayIPv4", ""), "selfLink": f"{s._gcp_compute_network_root()}/projects/{project}/global/networks/{network}", "selfLinkWithId": f"{s._gcp_compute_network_root()}/projects/{project}/global/networks/{network}?id={rec.get('id', s._gcp_compute_numeric_id(f'{project}:{network}'))}", "autoCreateSubnetworks": bool(rec.get("autoCreateSubnetworks", True)), "subnetworks": rec.get("subnetworks", []), "peerings": rec.get("peerings", []), "routingConfig": {"routingMode": rec.get("routingMode", "REGIONAL")}}


def api_gcp_vpc_delete_network(project: str, network: str):
    s = _server()
    project = s._gcp_project_name(project)
    rec = s.gcp_vpc_state.get("networks", {}).get(network)
    if not rec or str(rec.get("project") or project) != project:
        raise HTTPException(404, detail="Network not found")
    del s.gcp_vpc_state["networks"][network]
    return {"done": True}


def api_gcp_vpc_list_subnetworks(project: str, region: str):
    s = _server()
    project = s._gcp_project_name(project)
    subnetworks = []
    for subnet in s.gcp_vpc_state.get("subnetworks", {}).values():
        if str(subnet.get("project") or project) != project or str(subnet.get("region") or region) != region:
            continue
        subnetworks.append({"kind": "compute#subnetwork", "id": str(subnet.get("id") or s._gcp_compute_numeric_id(f"{project}:{subnet['name']}")), "creationTimestamp": subnet.get("createTime", s._now()), "name": subnet["name"], "description": subnet.get("description", ""), "region": region, "network": f"{s._gcp_compute_network_root()}/projects/{project}/global/networks/{subnet.get('network','default')}", "ipCidrRange": subnet.get("ipCidrRange", "10.0.0.0/24"), "reservedInternalRange": subnet.get("reservedInternalRange", ""), "gatewayAddress": subnet.get("gatewayAddress", ""), "privateIpGoogleAccess": bool(subnet.get("privateIpGoogleAccess", False)), "secondaryIpRanges": subnet.get("secondaryIpRanges", []), "purpose": subnet.get("purpose", ""), "role": subnet.get("role", ""), "stackType": subnet.get("stackType", "IPV4_ONLY"), "state": subnet.get("state", "READY"), "selfLink": f"{s._gcp_compute_network_root()}/projects/{project}/regions/{region}/subnetworks/{subnet['name']}"})
    return {"kind": "compute#subnetworkList", "items": subnetworks}


async def api_gcp_vpc_create_subnetwork(project: str, region: str, request: Request):
    s = _server()
    project = s._gcp_project_name(project)
    payload = await request.json() if request is not None else {}
    payload = payload if isinstance(payload, dict) else {}
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, detail="Subnetwork name is required")
    rec = {"id": s._gcp_compute_numeric_id(f"{project}:{name}"), "name": name, "description": str(payload.get("description") or ""), "project": project, "region": region, "network": str(payload.get("network") or "default").split("/")[-1], "ipCidrRange": str(payload.get("ipCidrRange") or "10.0.0.0/24"), "reservedInternalRange": str(payload.get("reservedInternalRange") or ""), "gatewayAddress": str(payload.get("gatewayAddress") or ""), "privateIpGoogleAccess": bool(payload.get("privateIpGoogleAccess", False)), "secondaryIpRanges": payload.get("secondaryIpRanges", []) if isinstance(payload.get("secondaryIpRanges"), list) else [], "purpose": str(payload.get("purpose") or ""), "role": str(payload.get("role") or ""), "stackType": str(payload.get("stackType") or "IPV4_ONLY"), "state": str(payload.get("state") or "READY"), "createTime": s._now()}
    s.gcp_vpc_state.setdefault("subnetworks", {})[name] = rec
    return {"kind": "compute#subnetwork", "id": rec["id"], "creationTimestamp": rec["createTime"], "name": name, "description": rec["description"], "region": region, "network": f"{s._gcp_compute_network_root()}/projects/{project}/global/networks/{rec['network']}", "ipCidrRange": rec["ipCidrRange"], "reservedInternalRange": rec["reservedInternalRange"], "gatewayAddress": rec["gatewayAddress"], "privateIpGoogleAccess": rec["privateIpGoogleAccess"], "secondaryIpRanges": rec["secondaryIpRanges"], "purpose": rec["purpose"], "role": rec["role"], "stackType": rec["stackType"], "state": rec["state"], "selfLink": f"{s._gcp_compute_network_root()}/projects/{project}/regions/{region}/subnetworks/{name}"}


def api_gcp_vpc_list_firewalls(project: str):
    s = _server()
    project = s._gcp_project_name(project)
    firewalls = []
    for fw in s.gcp_vpc_state.get("firewalls", {}).values():
        if str(fw.get("project") or project) != project:
            continue
        firewalls.append({"kind": "compute#firewall", "id": str(fw.get("id") or s._gcp_compute_numeric_id(f"{project}:{fw['name']}")), "creationTimestamp": fw.get("createTime", s._now()), "name": fw["name"], "description": fw.get("description", ""), "network": f"{s._gcp_compute_network_root()}/projects/{project}/global/networks/{fw.get('network','default')}", "priority": int(fw.get("priority") or 1000), "direction": fw.get("direction", "INGRESS"), "allowed": fw.get("allowed", [{"IPProtocol": "tcp", "ports": ["22"]}]), "denied": fw.get("denied", []), "sourceRanges": fw.get("sourceRanges", ["0.0.0.0/0"]), "destinationRanges": fw.get("destinationRanges", []), "sourceTags": fw.get("sourceTags", []), "targetTags": fw.get("targetTags", []), "sourceServiceAccounts": fw.get("sourceServiceAccounts", []), "targetServiceAccounts": fw.get("targetServiceAccounts", []), "disabled": bool(fw.get("disabled", False)), "logConfig": fw.get("logConfig", {}), "selfLink": f"{s._gcp_compute_network_root()}/projects/{project}/global/firewalls/{fw['name']}"})
    return {"kind": "compute#firewallList", "items": firewalls}


async def api_gcp_vpc_create_firewall(project: str, request: Request):
    s = _server()
    project = s._gcp_project_name(project)
    payload = await request.json() if request is not None else {}
    payload = payload if isinstance(payload, dict) else {}
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, detail="Firewall name is required")
    rec = {"id": s._gcp_compute_numeric_id(f"{project}:{name}"), "name": name, "description": str(payload.get("description") or ""), "project": project, "network": str(payload.get("network") or "default").split("/")[-1], "priority": int(payload.get("priority") or 1000), "direction": str(payload.get("direction") or "INGRESS"), "allowed": payload.get("allowed") if isinstance(payload.get("allowed"), list) else [{"IPProtocol": "tcp", "ports": ["22"]}], "denied": payload.get("denied") if isinstance(payload.get("denied"), list) else [], "sourceRanges": payload.get("sourceRanges") if isinstance(payload.get("sourceRanges"), list) else ["0.0.0.0/0"], "destinationRanges": payload.get("destinationRanges") if isinstance(payload.get("destinationRanges"), list) else [], "sourceTags": payload.get("sourceTags") if isinstance(payload.get("sourceTags"), list) else [], "targetTags": payload.get("targetTags") if isinstance(payload.get("targetTags"), list) else [], "sourceServiceAccounts": payload.get("sourceServiceAccounts") if isinstance(payload.get("sourceServiceAccounts"), list) else [], "targetServiceAccounts": payload.get("targetServiceAccounts") if isinstance(payload.get("targetServiceAccounts"), list) else [], "disabled": bool(payload.get("disabled", False)), "logConfig": payload.get("logConfig") if isinstance(payload.get("logConfig"), dict) else {}, "createTime": s._now()}
    s.gcp_vpc_state.setdefault("firewalls", {})[name] = rec
    _gcp_vpc_enforce_reconcile(s)
    return _gcp_firewall_view(s, project, rec)


def _gcp_firewall_view(s, project: str, rec: dict) -> dict:
    name = rec["name"]
    return {"kind": "compute#firewall", "id": rec["id"], "creationTimestamp": rec.get("createTime"), "name": name, "description": rec.get("description", ""), "network": f"{s._gcp_compute_network_root()}/projects/{project}/global/networks/{rec.get('network', 'default')}", "priority": rec.get("priority", 1000), "direction": rec.get("direction", "INGRESS"), "allowed": rec.get("allowed", []), "denied": rec.get("denied", []), "sourceRanges": rec.get("sourceRanges", []), "destinationRanges": rec.get("destinationRanges", []), "sourceTags": rec.get("sourceTags", []), "targetTags": rec.get("targetTags", []), "sourceServiceAccounts": rec.get("sourceServiceAccounts", []), "targetServiceAccounts": rec.get("targetServiceAccounts", []), "disabled": rec.get("disabled", False), "logConfig": rec.get("logConfig", {}), "selfLink": f"{s._gcp_compute_network_root()}/projects/{project}/global/firewalls/{name}"}


def _gcp_firewall_lookup(s, project: str, firewall: str):
    """Resolve a firewall record in the active project by name (last path segment)."""
    fw_id = str(firewall or "").split("/")[-1].strip()
    firewalls = s.gcp_vpc_state.setdefault("firewalls", {})
    rec = firewalls.get(fw_id)
    if rec and str(rec.get("project") or project) == project:
        return fw_id, rec, firewalls
    return fw_id, None, firewalls


def api_gcp_vpc_delete_firewall(project: str, firewall: str):
    s = _server()
    project = s._gcp_project_name(project)
    fw_id, rec, firewalls = _gcp_firewall_lookup(s, project, firewall)
    if not rec:
        raise HTTPException(404, detail="Firewall not found")
    del firewalls[fw_id]
    _gcp_vpc_enforce_reconcile(s)
    return {"kind": "compute#operation", "operationType": "delete", "status": "DONE", "targetLink": f"{s._gcp_compute_network_root()}/projects/{project}/global/firewalls/{fw_id}", "name": f"operation-delete-{fw_id}"}


async def api_gcp_vpc_update_firewall(project: str, firewall: str, request: Request):
    s = _server()
    project = s._gcp_project_name(project)
    fw_id, rec, firewalls = _gcp_firewall_lookup(s, project, firewall)
    if not rec:
        raise HTTPException(404, detail="Firewall not found")
    payload = await request.json() if request is not None else {}
    payload = payload if isinstance(payload, dict) else {}
    if "description" in payload:
        rec["description"] = str(payload.get("description") or "")
    if "network" in payload and payload.get("network"):
        rec["network"] = str(payload.get("network")).split("/")[-1]
    if "priority" in payload:
        try:
            rec["priority"] = int(payload.get("priority"))
        except (TypeError, ValueError):
            pass
    if "direction" in payload and payload.get("direction"):
        rec["direction"] = str(payload.get("direction")).upper()
    for key in ("allowed", "denied", "sourceRanges", "destinationRanges", "sourceTags", "targetTags", "sourceServiceAccounts", "targetServiceAccounts"):
        if key in payload and isinstance(payload.get(key), list):
            rec[key] = payload[key]
    if "disabled" in payload:
        rec["disabled"] = bool(payload.get("disabled"))
    if isinstance(payload.get("logConfig"), dict):
        rec["logConfig"] = payload["logConfig"]
    rec["updateTime"] = s._now()
    firewalls[fw_id] = rec
    _gcp_vpc_enforce_reconcile(s)
    return _gcp_firewall_view(s, project, rec)
