"""Azure Event Grid event subscriptions (Nano / dev_server / unified-ingress core).

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

Not modelled: delivery — matching a published event against the subscription's filters,
pushing it to the destination endpoint, retries and dead-lettering. Only the subscription's
configuration (destination, filters, retry policy, dead-letter settings) round-trips; that gap
is declared in ``core/capabilities/azure/eventgrid.json``.

``dispatch`` returns ``{"status", "headers", "body"}`` (``body`` is JSON-able or ``None``).
"""
from __future__ import annotations

import datetime

API_VERSION = "2022-06-15"


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
