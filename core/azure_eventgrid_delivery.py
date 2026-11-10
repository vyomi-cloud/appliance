"""Azure Event Grid delivery (offline appliance): a published event is matched against the topic's
event subscriptions and delivered to their destination, in the subscription's delivery schema.

Destinations: WebHook (HTTP POST), StorageQueue (the simulator's storage queue), AzureFunction
(runs the function app's deployed code). Filters: includedEventTypes, subjectBeginsWith/EndsWith.
Not modelled: the WebHook validation handshake, retry/dead-lettering, advanced filters.
Delivery runs in a background thread: a dead destination never fails the publish.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.request
import uuid


def _all_arm_resources() -> list:
    """Every ARM resource record across ALL spaces (the data plane must not depend on which space is active)."""
    out = []
    try:
        import server
        for sp in (server._spaces_state().get("spaces") or {}).values():
            for k, st in ((sp or {}).get("service_states") or {}).items():
                if isinstance(st, dict) and isinstance(st.get("resources"), dict) and k.endswith("arm"):
                    out.extend(r for r in st["resources"].values() if isinstance(r, dict))
    except Exception:
        pass
    return out


def subscriptions_for(topic: str) -> list:
    t = topic.lower()
    subs = []
    for rec in _all_arm_resources():
        rid = str(rec.get("id", "")).lower()
        if "/eventsubscriptions/" in rid and f"/topics/{t}/" in rid:
            subs.append(rec)
    return subs


def _passes_filter(props: dict, ev: dict) -> bool:
    f = props.get("filter") or {}
    types = f.get("includedEventTypes") or []
    if types and ev.get("eventType") not in types:
        return False
    subj = ev.get("subject") or ""
    if f.get("subjectBeginsWith") and not subj.startswith(f["subjectBeginsWith"]):
        return False
    if f.get("subjectEndsWith") and not subj.endswith(f["subjectEndsWith"]):
        return False
    return True


def _as_cloudevent(ev: dict, topic_id: str) -> dict:
    return {"specversion": "1.0", "id": ev.get("id"), "source": topic_id, "type": ev.get("eventType"),
            "subject": ev.get("subject"), "time": ev.get("eventTime"), "datacontenttype": "application/json",
            "data": ev.get("data")}


def _deliver(sub: dict, events: list, topic: str) -> None:
    try:
        from core.app_context import REQUEST_PROVIDER
        REQUEST_PROVIDER.set("azure")
    except Exception:
        pass
    props = sub.get("properties") or {}
    dest = props.get("destination") or {}
    etype = str(dest.get("endpointType") or "")
    dp = dest.get("properties") or {}
    events = [e for e in events if _passes_filter(props, e)]
    if not events:
        return
    topic_id = str(sub.get("id", "")).split("/providers/Microsoft.EventGrid/eventSubscriptions")[0] or topic
    cloud = str(props.get("eventDeliverySchema") or "EventGridSchema").lower().startswith("cloudevent")
    payload = [_as_cloudevent(e, topic_id) for e in events] if cloud else [
        {**e, "topic": e.get("topic") or topic_id} for e in events]
    try:
        if etype.lower() == "webhook" and dp.get("endpointUrl"):
            hdrs = {"content-type": "application/cloudevents-batch+json; charset=utf-8" if cloud else "application/json; charset=utf-8",
                    "aeg-subscription-name": str(sub.get("name", "")).upper(), "aeg-delivery-count": "0",
                    "aeg-data-version": "", "aeg-metadata-version": "1"}
            if not cloud:
                hdrs["aeg-event-type"] = "Notification"
            req = urllib.request.Request(dp["endpointUrl"], data=json.dumps(payload).encode(), method="POST", headers=hdrs)
            urllib.request.urlopen(req, timeout=15).read()
        elif etype.lower() == "storagequeue":
            from core import azure_dataplane as dpl
            store = dpl._queue_store()
            acct = str(dp.get("resourceId", "")).rsplit("/", 1)[-1]
            if store and dp.get("queueName") and acct:
                for item in payload:
                    store.send_message(dpl._sid(), acct, dp["queueName"], json.dumps(item))
        elif etype.lower() == "azurefunction":
            from core import azure_dataplane as dpl
            app = str(dp.get("resourceId", "")).split("/functions/")[0].rsplit("/", 1)[-1]
            fname = str(dp.get("resourceId", "")).rsplit("/", 1)[-1]
            dpl.run_function_sync(app, fname, "POST", payload)
    except Exception:
        pass   # a dead destination never fails the publish (real Event Grid retries then dead-letters)


def deliver(topic: str, events: list) -> int:
    n = 0
    for sub in subscriptions_for(topic):
        threading.Thread(target=_deliver, args=(sub, events, topic), daemon=True).start()
        n += 1
    return n


def normalize_published(body, content_type: str, topic: str) -> list:
    """Accept EventGridSchema (array/object) and CloudEvents (structured JSON, single/batch) input."""
    items = body if isinstance(body, list) else [body]
    out = []
    for ev in items:
        if not isinstance(ev, dict):
            continue
        if "specversion" in ev:   # CloudEvents input
            out.append({"id": ev.get("id") or uuid.uuid4().hex, "topic": topic, "subject": ev.get("subject", ""),
                        "eventType": ev.get("type", ""), "eventTime": ev.get("time") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "data": ev.get("data", {}), "dataVersion": "1.0", "metadataVersion": "1"})
        else:
            out.append({"id": ev.get("id") or uuid.uuid4().hex, "topic": ev.get("topic", topic), "subject": ev.get("subject", ""),
                        "eventType": ev.get("eventType", "Default"),
                        "eventTime": ev.get("eventTime") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "data": ev.get("data", {}), "dataVersion": ev.get("dataVersion", "1.0"), "metadataVersion": "1"})
    return out
