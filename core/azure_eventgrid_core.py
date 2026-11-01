"""Azure Event Grid event subscriptions + publish/delivery (Nano / dev_server /
unified-ingress core).

``Microsoft.EventGrid/topics`` rides the generic ARM CRUD (``core/azure_arm_data.CATALOG``,
dispatched by ``AzureArm``). Event subscriptions are a real ARM *extension resource*: they are
scoped to a parent resource's id rather than nested under the namespace/type chain, so
azure-mgmt-eventgrid / az CLI address them at

    PUT {scope}/providers/Microsoft.EventGrid/eventSubscriptions/{name}?api-version=2022-06-15

where ``scope`` is the topic's own resource id — the URL re-enters "providers" instead of
alternating type/name, which ``AzureArm._arm``'s generic chain splitter cannot parse. This
module owns that shape for topic-scoped subscriptions and keeps the records in the SAME flat
``AzureArm.state`` map (keyed by the subscription's own canonical, lower-cased id) so they
persist and are swept by the rest of ARM.

One piece of a subscription's configuration IS enforced independent of delivery:
``expirationTimeUtc``. Real Event Grid auto-deletes a subscription once it passes, so every
dispatch here sweeps the topic's subscriptions for expired ones first (``_sweep_expired``) — a
GET/list never sees one, the same as the real service.

``publish``/``deliver`` (below) are the data-plane half: matching a published event against
every live subscription's filter and attempting delivery. Delivery is REAL for ServiceBusQueue
/ ServiceBusTopic destinations (an injected ``core.azure_servicebus_core`` store — pure
in-memory, no external emulator) — the message actually lands in that entity's backlog. Every
other destination type (WebHook, EventHub, StorageQueue, HybridConnection, AzureFunction,
NamespaceTopic) has no reachable simulator backend wired yet, so delivery to them fails exactly
like an unreachable real endpoint would. There is no background retry scheduler (same
simplification as EventBridge Scheduler's lazy firing): a failed attempt is resolved immediately
to dead-lettered (``deadLetterDestination`` configured) or dropped, instead of being retried
``maxDeliveryAttempts`` times over wall-clock minutes. That gap is declared in
``core/capabilities/azure/eventgrid.json``.

``dispatch`` returns ``{"status", "headers", "body"}`` (``body`` is JSON-able or ``None``).
"""
from __future__ import annotations

import datetime
import json
import uuid

API_VERSION = "2022-06-15"

# Real Azure Event Grid topic metric names (Microsoft.EventGrid/topics metric namespace).
METRIC_NAMES = ("PublishSuccessCount", "PublishFailCount", "MatchedEventCount",
                "DeliverySuccessCount", "DeliveryAttemptFailCount", "DeadLetteredCount",
                "DroppedEventCount")


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _view(rec: dict) -> dict:
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def _merge(base: dict, overlay: dict) -> dict:
    out = dict(base)
    for k, v in (overlay or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def _parse_iso(ts) -> "datetime.datetime | None":
    if not ts:
        return None
    try:
        return datetime.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None


def _sweep_expired(state: dict, topic_rid: str) -> None:
    """Drop every event subscription on this topic whose ``expirationTimeUtc`` has passed —
    real Event Grid auto-deletes the subscription at that point, so a GET/list must not see it."""
    now = datetime.datetime.now(datetime.timezone.utc)
    parent = topic_rid.lower()
    for key in [k for k, r in state.items() if r.get("_parent") == parent]:
        exp = _parse_iso((state[key].get("properties") or {}).get("expirationTimeUtc"))
        if exp is not None and exp <= now:
            del state[key]


def handles(chain) -> bool:
    """``chain`` is ``AzureArm._arm``'s split of everything after the FIRST
    ``providers/Microsoft.EventGrid/`` — e.g. for a subscription on topic "t1":
    ``["topics", "t1", "providers", "Microsoft.EventGrid", "eventSubscriptions", "sub1"]``."""
    return (len(chain) >= 4 and chain[0].lower() == "topics" and chain[2].lower() == "providers"
            and chain[3].lower() == "microsoft.eventgrid")


def _ok(body=None, status=200, headers=None):
    return {"status": status, "headers": headers or {}, "body": body}


def _err(status, code, message):
    return {"status": status, "headers": {}, "body": {"error": {"code": code, "message": message}}}


def dispatch(state: dict, method: str, sub: str, rg, chain, names, payload, query, base: str = ""):
    topic_name = chain[1]
    topic_rid = f"/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.EventGrid/topics/{topic_name}"
    if topic_rid.lower() not in state:
        return _err(404, "ResourceNotFound", f"Topic '{topic_name}' was not found.")
    _sweep_expired(state, topic_rid)

    rest = chain[4:]
    if not rest or rest[0].lower() != "eventsubscriptions":
        return _err(400, "BadRequest", f"Unrecognized Event Grid path segment '{rest[0] if rest else ''}'.")

    if len(rest) == 1:                            # GET .../eventSubscriptions (list on the topic)
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        items = [_view(r) for r in state.values() if r.get("_parent") == topic_rid.lower()]
        return _ok({"value": items})

    name = rest[1]
    rid = f"{topic_rid}/providers/Microsoft.EventGrid/eventSubscriptions/{name}"
    key = rid.lower()

    if len(rest) >= 3:                            # POST action verb, e.g. getFullUrl / getDeliveryAttributes
        rec = state.get(key)
        if not rec:
            return _err(404, "ResourceNotFound", f"Event subscription '{name}' was not found.")
        action = rest[2].lower()
        if action == "getfullurl":
            dest = (rec.get("properties") or {}).get("destination", {}).get("properties", {})
            return _ok({"endpointUrl": dest.get("endpointUrl", "")})
        if action == "deliverystatus":
            # Simulator-internal read of this subscription's REAL delivery counters
            # (bumped by deliver()/_attempt_delivery — never synthetic).
            return _ok(rec.get("_delivery", {"matched": 0, "delivered": 0, "failed": 0, "deadLettered": 0, "dropped": 0}))
        return _ok({})

    if method == "GET":
        rec = state.get(key)
        if not rec:
            return _err(404, "ResourceNotFound", f"Event subscription '{name}' was not found.")
        return _ok(_view(rec))

    if method in ("PUT", "PATCH"):
        payload = payload if isinstance(payload, dict) else {}
        existed = key in state
        if method == "PATCH" and existed:
            rec = state[key]
        else:
            rec = {
                "id": rid, "name": name, "type": "Microsoft.EventGrid/eventSubscriptions",
                "properties": {
                    "eventDeliverySchema": "EventGridSchema",
                    "retryPolicy": {"maxDeliveryAttempts": 30, "eventTimeToLiveInMinutes": 1440},
                    "provisioningState": "Succeeded",
                },
                "systemData": {"createdAt": _now()},
                "_parent": topic_rid.lower(), "_sub": sub, "_rg": rg, "_created": _now(),
            }
        if isinstance(payload.get("properties"), dict):
            rec["properties"] = _merge(rec.get("properties", {}), payload["properties"])
        rec["properties"].setdefault("provisioningState", "Succeeded")
        state[key] = rec
        return _ok(_view(rec), status=200 if existed else 201)

    if method == "DELETE":
        rec = state.pop(key, None)
        return _ok(None, status=200 if rec is not None else 204)

    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


# ── Publish / delivery (data plane) ─────────────────────────────────────────────────────
def _bump(metrics: dict, name: str, n: int = 1) -> None:
    metrics[name] = metrics.get(name, 0) + n


def _topic_metrics(state: dict, topic_rid: str) -> dict:
    rec = state.get(topic_rid.lower())
    if rec is None:
        return {}
    return rec.setdefault("_metrics", {})


def find_topic_rid(state: dict, sub: str, topic_name: str) -> "str | None":
    """A topic is published to by name only (the data-plane endpoint carries no resource
    group) — scan for the first topic owned by this subscription with that name, the same
    ambiguity a real Event Grid data-plane hostname resolves by being unique per topic."""
    tn = topic_name.lower()
    for key, rec in state.items():
        if (rec.get("type") or "").lower() == "microsoft.eventgrid/topics" and \
                (rec.get("name") or "").lower() == tn and rec.get("_sub", sub) == sub:
            return rec["id"]
    return None


def _str_eq(a, b, case_sensitive) -> bool:
    return a == b if case_sensitive else str(a).lower() == str(b).lower()


def _advanced_match(op: str, value, flt: dict) -> bool:
    key = (flt.get("key") or "").lower()
    vals = flt.get("values")
    val = flt.get("value")
    if key == "subject":
        value = value
    if op == "StringIn":
        return str(value) in [str(v) for v in (vals or [])]
    if op == "StringNotIn":
        return str(value) not in [str(v) for v in (vals or [])]
    if op == "StringContains":
        return any(str(v) in str(value) for v in (vals or []))
    if op == "StringBeginsWith":
        return any(str(value).startswith(str(v)) for v in (vals or []))
    if op == "StringEndsWith":
        return any(str(value).endswith(str(v)) for v in (vals or []))
    if op == "NumberIn":
        return value in (vals or [])
    if op == "NumberNotIn":
        return value not in (vals or [])
    if op == "NumberGreaterThan":
        return isinstance(value, (int, float)) and value > val
    if op == "NumberGreaterThanOrEquals":
        return isinstance(value, (int, float)) and value >= val
    if op == "NumberLessThan":
        return isinstance(value, (int, float)) and value < val
    if op == "NumberLessThanOrEquals":
        return isinstance(value, (int, float)) and value <= val
    if op == "BoolEquals":
        return bool(value) == bool(val)
    if op == "IsNullOrUndefined":
        return value is None
    if op == "IsNotNull":
        return value is not None
    return True   # an operator we don't model is not treated as a reason to drop the event


def matches_filter(event: dict, flt: dict) -> bool:
    """Real Event Grid subscription filter evaluation: subject prefix/suffix (+ case
    sensitivity), included event types, and a bounded subset of advanced filter operators
    (string/number/bool comparisons against top-level event fields and ``data.*``)."""
    if not flt:
        return True
    subject = str(event.get("subject") or "")
    case_sensitive = bool(flt.get("isSubjectCaseSensitive"))
    begins = flt.get("subjectBeginsWith")
    if begins and not (subject.startswith(begins) if case_sensitive else subject.lower().startswith(begins.lower())):
        return False
    ends = flt.get("subjectEndsWith")
    if ends and not (subject.endswith(ends) if case_sensitive else subject.lower().endswith(ends.lower())):
        return False
    included = flt.get("includedEventTypes")
    if included and "all" not in [str(t).lower() for t in included] and event.get("eventType") not in included:
        return False
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    for af in (flt.get("advancedFilters") or []):
        key = str(af.get("key") or "")
        field = key.split(".", 1)[1] if key.lower().startswith("data.") else key
        value = data.get(field) if field in data else event.get(field)
        if not _advanced_match(af.get("operatorType", ""), value, af):
            return False
    return True


def _cloud_event(event: dict, props: dict) -> dict:
    return {
        "id": event.get("id") or uuid.uuid4().hex,
        "topic": event.get("topic", ""),
        "subject": event.get("subject", ""),
        "eventType": event.get("eventType", "Default"),
        "eventTime": event.get("eventTime") or _now(),
        "data": event.get("data", {}),
        "dataVersion": event.get("dataVersion", "1.0"),
        "metadataVersion": "1",
    }


def _attempt_delivery(rec: dict, event: dict, *, sb_store=None) -> str:
    """Try to deliver ``event`` to one event subscription's destination. Returns
    'delivered', 'dead-lettered' or 'dropped' — never raises; an unreachable/unmodelled
    destination resolves straight to the terminal outcome (no retry scheduler, see the
    module docstring)."""
    props = rec.get("properties") or {}
    dest = props.get("destination") or {}
    etype = (dest.get("endpointType") or "").lower()
    dprops = dest.get("properties") or {}
    delivered = False
    if etype in ("servicebusqueue", "servicebustopic") and sb_store is not None:
        entity = dprops.get("queueName") or dprops.get("topicName") or \
            str(dprops.get("resourceId") or "").rsplit("/", 1)[-1]
        if entity:
            try:
                from core import azure_servicebus_core as sb
                body = json.dumps(_cloud_event(event, props)).encode()
                resp = sb.dispatch(sb_store, "POST", f"{entity}/messages", {}, {"content-type": "application/json"}, body)
                delivered = resp.status == 201
            except Exception:
                delivered = False
    counters = rec.setdefault("_delivery", {"matched": 0, "delivered": 0, "failed": 0, "deadLettered": 0, "dropped": 0})
    if delivered:
        counters["delivered"] += 1
        return "delivered"
    counters["failed"] += 1
    if props.get("deadLetterDestination"):
        counters["deadLettered"] += 1
        return "dead-lettered"
    counters["dropped"] += 1
    return "dropped"


def deliver(state: dict, topic_rid: str, event: dict, *, sb_store=None) -> list:
    """Fan the event out to every live (non-expired) event subscription on ``topic_rid``
    whose filter matches it. Returns one outcome dict per matching subscription and bumps
    the topic's real, activity-derived metric counters (never synthetic)."""
    _sweep_expired(state, topic_rid)
    metrics = _topic_metrics(state, topic_rid)
    outcomes = []
    for rec in [r for r in state.values() if r.get("_parent") == topic_rid.lower()]:
        flt = (rec.get("properties") or {}).get("filter") or {}
        if not matches_filter(event, flt):
            continue
        _bump(metrics, "MatchedEventCount")
        rec.setdefault("_delivery", {"matched": 0, "delivered": 0, "failed": 0, "deadLettered": 0, "dropped": 0})["matched"] += 1
        result = _attempt_delivery(rec, event, sb_store=sb_store)
        _bump(metrics, {"delivered": "DeliverySuccessCount", "dead-lettered": "DeliveryAttemptFailCount",
                        "dropped": "DeliveryAttemptFailCount"}[result])
        if result == "dead-lettered":
            _bump(metrics, "DeadLetteredCount")
        elif result == "dropped":
            _bump(metrics, "DroppedEventCount")
        outcomes.append({"subscription": rec["name"], "result": result})
    return outcomes


def publish(state: dict, sub: str, topic_name: str, events: list, *, sb_store=None) -> dict:
    """Data-plane publish: ``POST {topicEndpoint}``. Looks the topic up by name (the
    endpoint carries no resource group, same as the real hostname), matches + delivers each
    event to every live subscription, and records real PublishSuccessCount /
    PublishFailCount — never a silent no-op."""
    topic_rid = find_topic_rid(state, sub, topic_name)
    if topic_rid is None:
        return {"published": 0, "error": "TopicNotFound"}
    metrics = _topic_metrics(state, topic_rid)
    results = []
    for ev in events:
        _bump(metrics, "PublishSuccessCount")
        results.append({"event": ev.get("id"), "deliveries": deliver(state, topic_rid, ev, sb_store=sb_store)})
    return {"published": len(events), "results": results}
