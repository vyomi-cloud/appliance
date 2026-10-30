"""v4 C0e — AWS SQS + SNS + EventBridge (+ EventBridge Scheduler) on the offline appliance,
ONE engine and ONE messaging store.

The native wire is served by the shared cores Nano and dev_server use (core/sqs_core.py,
core/sns_core.py, core/eventbridge_core.py, core/scheduler_core.py) through
core.wire_ingress.dispatch_service, over core/appliance_stores.AppStateMessagingStore — the
space-scoped, persisted state that SQS, SNS and EventBridge SHARE (as Nano's AwsWireRouter
shares `self.msg`). So an EventBridge rule's SQS / SNS / Lambda targets and an SNS topic's SQS
subscriptions are real, receivable deliveries. Before v4 the offline EventBridge wire was a
process-local dict in core/nats_routes.py that only published to NATS: PutEvents returned 200
and the rule's SQS target stayed empty.

  POST / and /_wire/ (JSON `AmazonSQS.*` / `AWSEvents.*`, Query SQS / SNS)
                                    → routes/aws_s3.aws_query_root → dispatch_service
  POST /<account>/<queue>           → the SQS queue URL itself (SDKs that post to it), via
                                      routes/aws_s3's catch-all (`queue_path_request`)
  /schedules, /schedule-groups      → EventBridge Scheduler (this module)

The classic console REST is re-implemented here on the SAME store by calling the cores:
  /api/sqs/queues*                       (providers/aws_routes.py SQS table)
  /api/eventbridge/rules*                (core/nats_routes.py REST)
  /api/aws/extras/eventbridge/{rules,event-buses,archives,replays}
                                          (the classic console's EventBridge pages)
  /api/aws/sns/*                          (routes/aws_sns.py, switched onto the same store)

Registered BEFORE the provider / nats / extras routes so these paths win. Opt-out:
VYOMI_UNIFIED_INGRESS_SERVICES without sqs / sns / events / scheduler (or VYOMI_LEGACY_WIRE=1)
registers nothing here and restores the pre-v4 handlers.
"""
from __future__ import annotations

import datetime as _dt
import json
import re

from fastapi import Request
from fastapi.responses import JSONResponse, Response

from core import wire_ingress as _wi

_CRED_RE = re.compile(r"Credential=[^/]*/[^/]*/[^/]*/([A-Za-z0-9_-]+)/aws4_request")


def _iso(ts) -> str:
    if ts in (None, ""):
        return ""
    if isinstance(ts, str):
        return ts
    try:
        return _dt.datetime.fromtimestamp(float(ts), _dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    except Exception:
        return str(ts)


def _hdrs(request: Request | None) -> dict:
    return {"host": request.headers.get("host", "")} if request is not None else {}


def _call(service: str, action: str, body: dict, request: Request | None = None) -> tuple[int, dict]:
    prefix = {"sqs": "AmazonSQS.", "events": "AWSEvents."}[service]
    ct = "application/x-amz-json-1.0" if service == "sqs" else "application/x-amz-json-1.1"
    out = _wi.dispatch_service(service, "POST", "/", {},
                               {"x-amz-target": prefix + action, "content-type": ct, **_hdrs(request)},
                               json.dumps(body).encode())
    try:
        data = json.loads(out["body"] or b"{}")
    except Exception:
        data = {}
    return out["status"], data


def _store():
    return _wi.appliance_router().msg


def _detail(status: int, data: dict) -> JSONResponse:
    code = str((data or {}).get("__type", "Error")).split("#")[-1]
    return JSONResponse(status_code=status, content={"detail": f"{code}: {(data or {}).get('message', '')}"})


async def _json_body(request: Request) -> dict:
    try:
        d = await request.json()
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


# ── SQS classic console (/api/sqs/queues*) ───────────────────────────────────────────
def _queue(name: str) -> dict | None:
    st = _store()
    st.adopt()
    q = st.get_queue(name)
    if q is None:
        for k, v in st.queues.items():
            if k.lower() == str(name).lower():
                return v
    return q


def _msg_view(m: dict, include_body: bool = True) -> dict:
    v = {"message_id": m.get("message_id", ""), "receipt_handle": m.get("receipt_handle", ""),
         "receive_count": int(m.get("receive_count", 0) or 0), "sent_at": m.get("sent_at", ""),
         "visible_at": _iso(m.get("visible_at")), "group_id": m.get("message_group_id") or "",
         "dedup_id": m.get("message_dedup_id") or "", "in_flight": bool(m.get("in_flight")),
         "md5_of_body": m.get("md5_of_body", ""), "sequence_number": m.get("sequence_number", "")}
    if include_body:
        v.update(body=m.get("body", ""), attributes={}, message_attributes=m.get("message_attributes") or {})
    return v


def _queue_view(q: dict, request: Request | None, include_messages: bool = True) -> dict:
    from core import sqs_core
    st = _store()
    url = sqs_core._queue_url(st, q["queue_name"])
    status, data = _call("sqs", "GetQueueAttributes", {"QueueUrl": url, "AttributeNames": ["All"]}, request)
    attrs = data.get("Attributes") or {}
    now = st.now()
    live = [m for m in q.get("messages") or [] if not m.get("deleted")]
    try:
        rp = json.loads(attrs.get("RedrivePolicy") or "{}")
    except Exception:
        rp = {}

    def _i(k, d):
        try:
            return int(attrs.get(k, d))
        except (TypeError, ValueError):
            return d
    return {
        "queue_name": q["queue_name"], "queue_url": url, "queue_arn": q.get("queue_arn", ""),
        "queue_type": "fifo" if q.get("fifo") else "standard", "fifo_queue": bool(q.get("fifo")),
        "content_based_deduplication": bool(q.get("content_based_dedup")),
        "visibility_timeout": _i("VisibilityTimeout", 30), "receive_wait_time_seconds": _i("ReceiveMessageWaitTimeSeconds", 0),
        "message_retention_period": _i("MessageRetentionPeriod", 345600), "max_message_size": _i("MaximumMessageSize", 262144),
        "delay_seconds": _i("DelaySeconds", 0), "redrive_policy": rp, "tags": dict(q.get("tags") or {}),
        "attributes": attrs, "created": q.get("created", ""), "last_modified": _iso(q.get("last_modified_epoch")),
        "message_count": len(live),
        "visible_message_count": sum(1 for m in live if float(m.get("visible_at") or 0) <= now),
        "in_flight_count": sum(1 for m in live if m.get("in_flight") and float(m.get("visible_at") or 0) > now),
        "messages": [_msg_view(m) for m in live] if include_messages else [],
        "latest_message_at": max((m.get("sent_at", "") for m in live), default=""),
    }


def _attrs_from_console(body: dict) -> dict:
    out = {}
    for k, attr in (("visibility_timeout", "VisibilityTimeout"), ("receive_wait_time_seconds", "ReceiveMessageWaitTimeSeconds"),
                    ("message_retention_period", "MessageRetentionPeriod"), ("max_message_size", "MaximumMessageSize"),
                    ("delay_seconds", "DelaySeconds")):
        if body.get(k) is not None:
            out[attr] = str(int(body[k]))
    if body.get("content_based_deduplication") is not None:
        out["ContentBasedDeduplication"] = "true" if body["content_based_deduplication"] else "false"
    rp = body.get("redrive_policy")
    if rp is not None:
        if isinstance(rp, str):
            out["RedrivePolicy"] = rp
        elif rp:
            out["RedrivePolicy"] = json.dumps(rp, separators=(",", ":"))
        else:
            out["RedrivePolicy"] = ""
    return out


def _console_msg_attrs(raw) -> dict:
    out = {}
    for k, v in (raw or {}).items():
        if isinstance(v, dict) and ("DataType" in v or "StringValue" in v or "BinaryValue" in v):
            out[str(k)] = v
        else:
            out[str(k)] = {"DataType": "String", "StringValue": str(v)}
    return out


def _register_sqs_console(app) -> None:
    nf = lambda: JSONResponse(status_code=404, content={"detail": "QueueNotFound"})   # noqa: E731

    @app.get("/api/sqs/queues", include_in_schema=False)
    async def sqs_console_list(request: Request):
        st = _store()
        st.adopt()
        rows = [_queue_view(q, request, include_messages=False)
                for q in sorted(st.queues.values(), key=lambda q: (q.get("created", ""), q.get("queue_name", "")))
                if isinstance(q, dict)]
        return {"queues": rows, "count": len(rows)}

    @app.post("/api/sqs/queues", include_in_schema=False)
    async def sqs_console_create(request: Request):
        body = await _json_body(request)
        name = str(body.get("queue_name") or body.get("QueueName") or body.get("queueName") or body.get("name") or "").strip()
        if not name:
            return JSONResponse(status_code=400, content={"detail": "MissingParameter: queue_name is required."})
        fifo = bool(body.get("fifo_queue")) or str(body.get("queue_type", "")).lower() == "fifo" or name.endswith(".fifo")
        if fifo and not name.endswith(".fifo"):
            name += ".fifo"
        if _queue(name) is not None:
            return JSONResponse(status_code=409, content={"detail": "QueueAlreadyExists"})
        attrs = _attrs_from_console(body)
        if not attrs.get("RedrivePolicy"):
            attrs.pop("RedrivePolicy", None)
        if fifo:
            attrs["FifoQueue"] = "true"
        req = {"QueueName": name, "Attributes": attrs}
        if body.get("tags"):
            req["tags"] = {str(k): str(v) for k, v in body["tags"].items()}
        status, data = _call("sqs", "CreateQueue", req, request)
        if status != 200:
            return _detail(status, data)
        return _queue_view(_queue(name), request)

    @app.get("/api/sqs/queues/{queue_name}", include_in_schema=False)
    async def sqs_console_get(queue_name: str, request: Request):
        q = _queue(queue_name)
        return _queue_view(q, request) if q else nf()

    @app.put("/api/sqs/queues/{queue_name}", include_in_schema=False)
    async def sqs_console_update(queue_name: str, request: Request):
        q = _queue(queue_name)
        if not q:
            return nf()
        body = await _json_body(request)
        attrs = _attrs_from_console(body)
        if attrs:
            status, data = _call("sqs", "SetQueueAttributes", {"QueueUrl": q["queue_name"], "Attributes": attrs}, request)
            if status != 200:
                return _detail(status, data)
        if body.get("tags") is not None:
            q["tags"] = {str(k): str(v) for k, v in (body.get("tags") or {}).items()}
        return _queue_view(q, request)

    @app.delete("/api/sqs/queues/{queue_name}", include_in_schema=False)
    async def sqs_console_delete(queue_name: str, request: Request):
        q = _queue(queue_name)
        if not q:
            return JSONResponse(status_code=404, content={"detail": "AWS.SimpleQueueService.NonExistentQueue"})
        _call("sqs", "DeleteQueue", {"QueueUrl": q["queue_name"]}, request)
        return {"deleted": True, "queue_name": q["queue_name"]}

    @app.get("/api/sqs/queues/{queue_name}/messages", include_in_schema=False)
    async def sqs_console_peek(queue_name: str):
        q = _queue(queue_name)
        if not q:
            return nf()
        live = [m for m in q.get("messages") or [] if not m.get("deleted")]
        return {"queue_name": q["queue_name"], "messages": [_msg_view(m) for m in live], "count": len(live)}

    async def _send(queue_name: str, request: Request):
        q = _queue(queue_name)
        if not q:
            return nf()
        body = await _json_body(request)
        req = {"QueueUrl": q["queue_name"], "MessageBody": str(body.get("message_body") or body.get("MessageBody") or "")}
        ma = _console_msg_attrs(body.get("message_attributes") or body.get("message_attributes_map"))
        if ma:
            req["MessageAttributes"] = ma
        if body.get("message_group_id"):
            req["MessageGroupId"] = str(body["message_group_id"])
        if body.get("message_deduplication_id"):
            req["MessageDeduplicationId"] = str(body["message_deduplication_id"])
        status, data = _call("sqs", "SendMessage", req, request)
        if status != 200:
            return _detail(status, data)
        msg = next((m for m in q.get("messages") or [] if m.get("message_id") == data.get("MessageId")), None)
        view = _msg_view(msg) if msg else {"message_id": data.get("MessageId", ""), "md5_of_body": data.get("MD5OfMessageBody", "")}
        from core import sqs_core
        return {"message": view, "queue_name": q["queue_name"], "queue_url": sqs_core._queue_url(_store(), q["queue_name"])}

    app.add_api_route("/api/sqs/queues/{queue_name}/messages", _send, methods=["POST"], include_in_schema=False)
    app.add_api_route("/api/sqs/queues/{queue_name}/send", _send, methods=["POST"], include_in_schema=False)

    @app.post("/api/sqs/queues/{queue_name}/receive", include_in_schema=False)
    async def sqs_console_receive(queue_name: str, request: Request):
        q = _queue(queue_name)
        if not q:
            return nf()
        body = await _json_body(request)
        req = {"QueueUrl": q["queue_name"], "MaxNumberOfMessages": max(1, min(int(body.get("max_number_of_messages") or 1), 10)),
               "MessageAttributeNames": ["All"], "AttributeNames": ["All"]}
        if body.get("visibility_timeout") is not None:
            req["VisibilityTimeout"] = max(0, int(body["visibility_timeout"]))
        status, data = _call("sqs", "ReceiveMessage", req, request)
        if status != 200:
            return _detail(status, data)
        ids = {m["MessageId"] for m in data.get("Messages") or []}
        got = [_msg_view(m) for m in q.get("messages") or [] if m.get("message_id") in ids]
        return {"queue_name": q["queue_name"], "messages": got, "count": len(got)}

    @app.delete("/api/sqs/queues/{queue_name}/messages/{receipt_handle}", include_in_schema=False)
    async def sqs_console_delete_message(queue_name: str, receipt_handle: str, request: Request):
        q = _queue(queue_name)
        if not q:
            return nf()
        status, data = _call("sqs", "DeleteMessage", {"QueueUrl": q["queue_name"], "ReceiptHandle": receipt_handle}, request)
        if status != 200:
            return JSONResponse(status_code=400, content={"detail": "ReceiptHandleIsInvalid"})
        return {"deleted": True, "queue_name": q["queue_name"], "receipt_handle": receipt_handle}

    @app.post("/api/sqs/queues/{queue_name}/messages/{receipt_handle}/visibility", include_in_schema=False)
    async def sqs_console_visibility(queue_name: str, receipt_handle: str, request: Request):
        q = _queue(queue_name)
        if not q:
            return nf()
        body = await _json_body(request)
        vt = int(body.get("visibility_timeout", 30) if body.get("visibility_timeout") is not None else 30)
        status, data = _call("sqs", "ChangeMessageVisibility",
                             {"QueueUrl": q["queue_name"], "ReceiptHandle": receipt_handle, "VisibilityTimeout": vt}, request)
        if status != 200:
            return JSONResponse(status_code=400, content={"detail": "ReceiptHandleIsInvalid"})
        return {"updated": True, "queue_name": q["queue_name"], "receipt_handle": receipt_handle, "visibility_timeout": vt}

    @app.post("/api/sqs/queues/{queue_name}/purge", include_in_schema=False)
    async def sqs_console_purge(queue_name: str, request: Request):
        q = _queue(queue_name)
        if not q:
            return nf()
        _call("sqs", "PurgeQueue", {"QueueUrl": q["queue_name"]}, request)
        return {"purged": True, "queue_name": q["queue_name"]}

    @app.get("/api/sqs/queues/{queue_name}/tags", include_in_schema=False)
    async def sqs_console_tags(queue_name: str):
        q = _queue(queue_name)
        return {"queue_name": q["queue_name"], "tags": dict(q.get("tags") or {})} if q else nf()

    @app.post("/api/sqs/queues/{queue_name}/tags", include_in_schema=False)
    async def sqs_console_tag(queue_name: str, request: Request):
        q = _queue(queue_name)
        if not q:
            return nf()
        body = await _json_body(request)
        _call("sqs", "TagQueue", {"QueueUrl": q["queue_name"], "Tags": {str(k): str(v) for k, v in body.items()}}, request)
        return {"tagged": True, "queue_name": q["queue_name"], "tags": dict(q.get("tags") or {})}

    @app.delete("/api/sqs/queues/{queue_name}/tags", include_in_schema=False)
    async def sqs_console_untag(queue_name: str, request: Request):
        q = _queue(queue_name)
        if not q:
            return nf()
        body = await _json_body(request)
        _call("sqs", "UntagQueue", {"QueueUrl": q["queue_name"], "TagKeys": [str(k) for k in body.get("keys") or []]}, request)
        return {"untagged": True, "queue_name": q["queue_name"], "tags": dict(q.get("tags") or {})}


# ── EventBridge classic REST (/api/eventbridge/rules*, core/nats_routes.py shapes) ───
def _find_rule(name: str) -> dict | None:
    from core import eventbridge_core as ebc
    st = _store()
    st.adopt()
    return next((r for r in ebc._rules(st).values() if r.get("name") == name), None)


def _legacy_rule(r: dict) -> dict:
    from core import app_context as ctx
    pat = r.get("pattern")
    return {"Name": r["name"], "Arn": r["arn"], "State": r.get("state", "ENABLED"),
            "EventBusName": r.get("bus", "default"), "EventPattern": json.dumps(pat) if pat else None,
            "ScheduleExpression": r.get("schedule", ""), "Description": r.get("description", ""),
            "CreatedBy": ctx.AWS_ACCOUNT_ID}


def _rule_req(name: str, body: dict) -> dict:
    req = {"Name": name, "EventBusName": body.get("EventBusName") or "default",
           "State": body.get("State") or "ENABLED", "Description": body.get("Description") or ""}
    pat = body.get("EventPattern")
    if pat:
        req["EventPattern"] = pat if isinstance(pat, str) else json.dumps(pat)
    if body.get("ScheduleExpression"):
        req["ScheduleExpression"] = body["ScheduleExpression"]
    return req


def _register_eventbridge_rest(app) -> None:
    nf = lambda n: JSONResponse(status_code=404, content={"error": f"Rule {n} not found"})   # noqa: E731

    @app.put("/api/eventbridge/rules/{rule_name}", include_in_schema=False)
    async def eb_rest_put_rule(rule_name: str, request: Request):
        status, data = _call("events", "PutRule", _rule_req(rule_name, await _json_body(request)), request)
        if status != 200:
            return JSONResponse(status_code=status, content={"error": data.get("message", ""), "code": data.get("__type", "")})
        return _legacy_rule(_find_rule(rule_name))

    @app.get("/api/eventbridge/rules", include_in_schema=False)
    async def eb_rest_list_rules():
        from core import eventbridge_core as ebc
        st = _store()
        st.adopt()
        return {"Rules": [_legacy_rule(r) for r in ebc._rules(st).values()]}

    @app.get("/api/eventbridge/rules/{rule_name}", include_in_schema=False)
    async def eb_rest_get_rule(rule_name: str):
        r = _find_rule(rule_name)
        return _legacy_rule(r) if r else nf(rule_name)

    @app.delete("/api/eventbridge/rules/{rule_name}", include_in_schema=False)
    async def eb_rest_delete_rule(rule_name: str, request: Request):
        r = _find_rule(rule_name)
        if not r:
            return nf(rule_name)
        r["targets"].clear()
        _call("events", "DeleteRule", {"Name": rule_name, "EventBusName": r.get("bus", "default")}, request)
        return {"deleted": True, "rule_name": rule_name}

    @app.put("/api/eventbridge/rules/{rule_name}/targets", include_in_schema=False)
    async def eb_rest_put_targets(rule_name: str, request: Request):
        r = _find_rule(rule_name)
        if not r:
            return nf(rule_name)
        body = await _json_body(request)
        status, data = _call("events", "PutTargets", {"Rule": rule_name, "EventBusName": r.get("bus", "default"),
                                                      "Targets": body.get("Targets") or []}, request)
        return data if status == 200 else JSONResponse(status_code=status, content={"error": data.get("message", "")})

    @app.get("/api/eventbridge/rules/{rule_name}/targets", include_in_schema=False)
    async def eb_rest_list_targets(rule_name: str):
        r = _find_rule(rule_name)
        return {"Targets": list(r["targets"].values())} if r else nf(rule_name)


# ── EventBridge classic console pages (/api/aws/extras/eventbridge/*) ─────────────
def _schema(stub: str) -> dict:
    from core.aws_rail_extras import EXTRAS
    s = EXTRAS.get(stub) or {}
    return {"category": s.get("category"), "columns": s.get("columns")}


def _extras_rows(kind: str) -> list[dict]:
    from core import eventbridge_core as ebc
    st = _store()
    st.adopt()
    if kind == "rules":
        rows = []
        for r in ebc._rules(st).values():
            tg = list(r.get("targets", {}).values())
            rows.append({"name": r["name"], "event_bus_name": r.get("bus", "default"),
                         "rule_type": "Schedule" if r.get("schedule") else "EventPattern",
                         "state": r.get("state", "ENABLED"), "target_count": len(tg),
                         "target_arn": tg[0]["Arn"] if tg else "", "arn": r["arn"],
                         "description": r.get("description", ""),
                         "event_pattern": json.dumps(r["pattern"]) if r.get("pattern") else "",
                         "schedule_expression": r.get("schedule", ""), "created": r.get("created", "")})
        return rows
    if kind == "event-buses":
        rules = list(ebc._rules(st).values())
        return [{"name": b["name"], "type": "AWS" if b["name"] == "default" else "Custom", "arn": b["arn"],
                 "rules_count": sum(1 for r in rules if r.get("bus", "default") == b["name"]),
                 "description": b.get("description", ""), "created": b.get("created", "")}
                for b in ebc._buses(st).values()]
    if kind == "archives":
        out = []
        for a in ebc._archives(st).values():
            evs = ebc._archived_events(st, a)
            out.append({"name": a["name"], "event_source": a["source_arn"], "state": a.get("state", "ENABLED"),
                        "event_count": len(evs), "size_mb": round(sum(len(json.dumps(e)) for e in evs) / 1048576, 3),
                        "retention_days": a.get("retention_days", 0), "arn": a["arn"], "created": a.get("created", "")})
        return out
    out = []
    for r in ebc._replays(st).values():
        arch = next((a["name"] for a in ebc._archives(st).values() if a["arn"] == r.get("source_arn")), r.get("source_arn", ""))
        out.append({"name": r["name"], "archive": arch, "state": r.get("state", ""), "progress": "100%",
                    "started": r.get("started", ""), "event_count": r.get("event_count", 0), "arn": r.get("arn", "")})
    return out


def _register_eventbridge_extras(app) -> None:
    kinds = ("rules", "event-buses", "archives", "replays")

    def _list(kind):
        async def h():
            return {"items": _extras_rows(kind), "derived": False, "schema": _schema(f"eventbridge/{kind}")}
        return h

    def _create(kind):
        async def h(request: Request):
            from core import eventbridge_core as ebc
            body = await _json_body(request)
            name = str(body.get("name") or body.get("id") or "").strip()
            if not name:
                return JSONResponse(status_code=400, content={"detail": "name is required"})
            st = _store()
            if kind == "rules":
                bus = str(body.get("event_bus_name") or "default")
                req = {"Name": name, "EventBusName": bus, "State": str(body.get("state") or "ENABLED"),
                       "Description": str(body.get("description") or "")}
                if req["State"] not in ("ENABLED", "DISABLED"):
                    req["State"] = "ENABLED"
                if str(body.get("rule_type")) == "Schedule":
                    req["ScheduleExpression"] = str(body.get("schedule_expression") or "rate(1 day)")
                elif body.get("event_pattern"):
                    p = body["event_pattern"]
                    req["EventPattern"] = p if isinstance(p, str) else json.dumps(p)
                status, data = _call("events", "PutRule", req, request)
                if status == 200 and body.get("target_arn"):
                    status, data = _call("events", "PutTargets", {"Rule": name, "EventBusName": bus,
                                                                  "Targets": [{"Id": "Target0", "Arn": str(body["target_arn"])}]}, request)
            elif kind == "event-buses":
                status, data = _call("events", "CreateEventBus", {"Name": name, "Description": str(body.get("description") or "")}, request)
            elif kind == "archives":
                src = str(body.get("event_source") or "default")
                if not src.startswith("arn:"):
                    src = ebc._bus_arn(st, src)
                status, data = _call("events", "CreateArchive", {"ArchiveName": name, "EventSourceArn": src,
                                                                 "RetentionDays": int(body.get("retention_days") or 0)}, request)
            else:
                arch = str(body.get("archive") or "")
                a = next((a for a in ebc._archives(st).values() if arch in (a["name"], a["arn"])), None)
                if a is None:
                    return JSONResponse(status_code=404, content={"detail": f"Archive {arch} does not exist."})
                status, data = _call("events", "StartReplay", {"ReplayName": name, "EventSourceArn": a["arn"],
                                                               "Destination": {"Arn": ebc._bus_arn(st, a["bus"])}}, request)
            if status != 200:
                return _detail(status, data)
            return next((r for r in _extras_rows(kind) if r["name"] == name), {"name": name})
        return h

    def _delete(kind):
        async def h(name: str, request: Request):
            from core import eventbridge_core as ebc
            st = _store()
            if kind == "rules":
                r = _find_rule(name)
                if r:
                    r["targets"].clear()
                    _call("events", "DeleteRule", {"Name": name, "EventBusName": r.get("bus", "default")}, request)
            elif kind == "event-buses":
                status, data = _call("events", "DeleteEventBus", {"Name": name}, request)
                if status != 200:
                    return _detail(status, data)
            elif kind == "archives":
                _call("events", "DeleteArchive", {"ArchiveName": name}, request)
            else:
                ebc._replays(st).pop(name, None)
            return {"deleted": True, "name": name}
        return h

    for kind in kinds:
        base = f"/api/aws/extras/eventbridge/{kind}"
        app.add_api_route(base, _list(kind), methods=["GET"], include_in_schema=False)
        app.add_api_route(base, _create(kind), methods=["POST"], include_in_schema=False)
        app.add_api_route(base + "/{name}", _delete(kind), methods=["DELETE"], include_in_schema=False)


# ── EventBridge Scheduler native REST (/schedules, /schedule-groups) ───────────────
def _scope(request: Request) -> str:
    m = _CRED_RE.search(request.headers.get("authorization", "") or "")
    return m.group(1).lower() if m else ""


def _register_scheduler(app) -> None:
    async def _sched(request: Request):
        scope = _scope(request)
        if scope and scope != "scheduler" and _wi.is_unified("s3"):
            # signed for another service (an S3 bucket named "schedules"): not Scheduler
            return await _wi.serve_service("s3", request)
        return await _wi.serve_service("scheduler", request, path=request.url.path)

    methods = ["GET", "POST", "PUT", "DELETE"]
    for p in ("/schedules", "/schedules/{name}", "/schedule-groups", "/schedule-groups/{name}"):
        app.add_route(p, _sched, methods=methods)


# ── the SQS queue URL itself (`POST /<account>/<queue>`) ──────────────────────────
def queue_path_request(request: Request) -> bool:
    """A request an SDK POSTed to a queue URL this appliance handed out
    (`<endpoint>/<account>/<queue>`): signed for sqs, or an AmazonSQS.* target."""
    if request.method != "POST" or not _wi.is_unified("sqs"):
        return False
    segs = [x for x in request.url.path.split("/") if x]
    if len(segs) != 2:
        return False
    target = request.headers.get("x-amz-target", "") or ""
    return _scope(request) == "sqs" or target.startswith("AmazonSQS.")


async def serve_queue_path(request: Request) -> Response:
    return await _wi.serve_service("sqs", request, path=request.url.path)


def register(app) -> None:
    """Mount whichever of the classic console surfaces is unified (BEFORE the provider /
    nats / extras routes — Starlette matches in registration order)."""
    if _wi.is_unified("sqs"):
        _register_sqs_console(app)
    if _wi.is_unified("events"):
        _register_eventbridge_rest(app)
        _register_eventbridge_extras(app)
    if _wi.is_unified("scheduler"):
        _register_scheduler(app)


def inventory(space: dict) -> dict:
    """{(svc, kind): {id: created}} of a space's core-backed EventBridge rules / custom
    buses / archives and Scheduler schedules (for the cost / inventory collectors)."""
    ss = (space or {}).get("service_states") or {}
    eb = ss.get("eventbridge") or {}
    out = {("eventbridge", "rule"): {}, ("eventbridge", "event-bus"): {}, ("scheduler", "schedule"): {}}
    for key, r in (eb.get("rules") or {}).items():
        if isinstance(r, dict):
            out[("eventbridge", "rule")][key] = r.get("created", "")
    for name, b in (eb.get("buses") or {}).items():
        if isinstance(b, dict) and name != "default":
            out[("eventbridge", "event-bus")][name] = b.get("created", "")
    for key, s in ((ss.get("scheduler") or {}).get("schedules") or {}).items():
        if isinstance(s, dict):
            out[("scheduler", "schedule")][key] = s.get("CreationDate") or s.get("created", "")
    return out
