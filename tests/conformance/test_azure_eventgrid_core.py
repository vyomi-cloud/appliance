"""Azure Event Grid conformance — topics (generic ARM catalog CRUD) + event subscriptions
(core/azure_eventgrid_core.py, the extension-resource shape scoped to a topic).

Run: PYTHONPATH=. python3 tests/conformance/test_azure_eventgrid_core.py
"""
try:
    from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION
    from core import azure_eventgrid_core as eg
    from core import azure_servicebus_core as sb
    from core.messaging_store import InMemoryMessagingStore
except ImportError:  # pragma: no cover - Pyodide flat layout
    from azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION  # type: ignore
    import azure_eventgrid_core as eg  # type: ignore
    import azure_servicebus_core as sb  # type: ignore
    from messaging_store import InMemoryMessagingStore  # type: ignore

SUB = DEFAULT_SUBSCRIPTION
RG = "cloudlearn-rg"
AV = "2024-06-01-preview"
ESAV = "2022-06-15"

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if cond else 0), FAIL + (0 if cond else 1)
    print(f"[{'PASS' if cond else 'FAIL'}] {name}{'' if cond else ' — ' + str(detail)}")


def topic_path(name, rg=RG):
    return f"/subscriptions/{SUB}/resourceGroups/{rg}/providers/Microsoft.EventGrid/topics/{name}"


def sub_path(topic, name, rg=RG):
    return f"{topic_path(topic, rg)}/providers/Microsoft.EventGrid/eventSubscriptions/{name}"


def run() -> int:
    arm = AzureArm()

    # ── Topics: generic ARM catalog CRUD ────────────────────────────────────────────────
    r = arm.handle("PUT", topic_path("t1"), {"api-version": AV}, {"location": "eastus"})
    check("create topic -> 200 (LRO wrapped)", r["status"] == 200 and "Azure-AsyncOperation" in r["headers"], r)
    p = r["body"]["properties"]
    check("topic defaults (input schema, network access, TLS, local auth)",
          p["inputSchema"] == "EventGridSchema" and p["publicNetworkAccess"] == "Enabled"
          and p["minimumTlsVersionAllowed"] == "1.2" and p["disableLocalAuth"] is False, p)
    check("topic gets an endpoint", p.get("endpoint", "").endswith("/azure-data/eventgrid/t1/api/events"), p.get("endpoint"))

    r = arm.handle("POST", topic_path("t1") + "/listKeys", {"api-version": AV})
    check("listKeys -> two keys", r["status"] == 200 and len(r["body"]["keys"]) == 2, r)

    r = arm.handle("GET", f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.EventGrid/topics", {"api-version": AV})
    check("list topics in rg", r["status"] == 200 and any(x["name"] == "t1" for x in r["body"]["value"]), r)

    # ── Event subscriptions before the topic exists -> honest 404 ──────────────────────
    r = arm.handle("PUT", sub_path("ghost", "es0"), {"api-version": ESAV}, {"properties": {}})
    check("subscription on missing topic -> 404", r["status"] == 404, r)

    # ── Event subscriptions: create / defaults / round-trip ────────────────────────────
    body = {"properties": {
        "destination": {"endpointType": "WebHook", "properties": {"endpointUrl": "https://example.com/hook"}},
        "filter": {"subjectBeginsWith": "/blobServices", "includedEventTypes": ["Microsoft.Storage.BlobCreated"]},
        "deadLetterDestination": {"endpointType": "StorageBlob"},
        "retryPolicy": {"maxDeliveryAttempts": 10, "eventTimeToLiveInMinutes": 60},
    }}
    r = arm.handle("PUT", sub_path("t1", "es1"), {"api-version": ESAV}, body)
    check("create event subscription -> 201", r["status"] == 201, r)
    ep = r["body"]["properties"]
    check("destination + filter stored verbatim",
          ep["destination"]["properties"]["endpointUrl"] == "https://example.com/hook"
          and ep["filter"]["subjectBeginsWith"] == "/blobServices"
          and ep["filter"]["includedEventTypes"] == ["Microsoft.Storage.BlobCreated"], ep)
    check("retry policy + dead-letter config round-trip (stored, not enforced)",
          ep["retryPolicy"]["maxDeliveryAttempts"] == 10 and ep["retryPolicy"]["eventTimeToLiveInMinutes"] == 60
          and ep["deadLetterDestination"]["endpointType"] == "StorageBlob", ep)
    check("provisioning state defaults to Succeeded", ep["provisioningState"] == "Succeeded")
    check("subscription id is scoped under the topic", r["body"]["id"] == sub_path("t1", "es1"))

    r = arm.handle("GET", sub_path("t1", "es1"), {"api-version": ESAV})
    check("get event subscription", r["status"] == 200 and r["body"]["name"] == "es1", r)

    r = arm.handle("PATCH", sub_path("t1", "es1"), {"api-version": ESAV}, {"properties": {"retryPolicy": {"maxDeliveryAttempts": 5}}})
    check("patch merges without wiping destination",
          r["body"]["properties"]["retryPolicy"]["maxDeliveryAttempts"] == 5
          and r["body"]["properties"]["destination"]["properties"]["endpointUrl"] == "https://example.com/hook", r)

    # ── A second subscription + a second topic: listing is isolated per topic ─────────
    arm.handle("PUT", sub_path("t1", "es2"), {"api-version": ESAV}, {"properties": {"destination": {"endpointType": "WebHook"}}})
    arm.handle("PUT", topic_path("t2"), {"api-version": AV}, {"location": "eastus"})
    arm.handle("PUT", sub_path("t2", "other"), {"api-version": ESAV}, {"properties": {"destination": {"endpointType": "WebHook"}}})

    r = arm.handle("GET", topic_path("t1") + "/providers/Microsoft.EventGrid/eventSubscriptions", {"api-version": ESAV})
    names = sorted(x["name"] for x in r["body"]["value"])
    check("list on t1 has exactly its two subscriptions", names == ["es1", "es2"], names)

    r = arm.handle("GET", topic_path("t2") + "/providers/Microsoft.EventGrid/eventSubscriptions", {"api-version": ESAV})
    check("list on t2 is isolated from t1", [x["name"] for x in r["body"]["value"]] == ["other"], r["body"])

    # ── Delete ───────────────────────────────────────────────────────────────────────
    r = arm.handle("DELETE", sub_path("t1", "es2"), {"api-version": ESAV})
    check("delete -> 200", r["status"] == 200, r)
    r = arm.handle("DELETE", sub_path("t1", "es2"), {"api-version": ESAV})
    check("delete missing -> 204", r["status"] == 204, r)
    r = arm.handle("GET", topic_path("t1") + "/providers/Microsoft.EventGrid/eventSubscriptions", {"api-version": ESAV})
    check("deleted subscription is gone from the list", [x["name"] for x in r["body"]["value"]] == ["es1"], r["body"])

    # ── Deleting the topic doesn't crash subsequent calls against orphans ──────────────
    arm.handle("DELETE", topic_path("t2"), {"api-version": AV})
    r = arm.handle("PUT", sub_path("t2", "new"), {"api-version": ESAV}, {"properties": {}})
    check("subscription create on a deleted topic -> 404", r["status"] == 404, r)

    # ── Sibling resource types: namespaces/system topics/domains/partner* ride the SAME
    # generic ARM catalog CRUD as topics — just a different (namespace, type) entry ──────
    def rtype_path(typ, name, rg=RG):
        return f"/subscriptions/{SUB}/resourceGroups/{rg}/providers/Microsoft.EventGrid/{typ}/{name}"

    for typ, name in (("namespaces", "ns1"), ("systemTopics", "st1"), ("domains", "d1"),
                       ("partnerConfigurations", "pc1"), ("partnerTopics", "pt1"),
                       ("partnerRegistrations", "pr1"), ("partnerNamespaces", "pn1")):
        r = arm.handle("PUT", rtype_path(typ, name), {"api-version": "2022-06-15"}, {"location": "eastus"})
        check(f"create {typ} -> 2xx", r["status"] in (200, 201), r)
        check(f"{typ} provisioningState Succeeded", r["body"]["properties"]["provisioningState"] == "Succeeded", r["body"])
        r = arm.handle("GET", rtype_path(typ, name).rsplit("/", 1)[0], {"api-version": "2022-06-15"})
        check(f"list {typ} contains {name}", any(x["name"] == name for x in r["body"]["value"]), r["body"])
        r = arm.handle("DELETE", rtype_path(typ, name), {"api-version": "2022-06-15"})
        check(f"delete {typ} -> 200", r["status"] == 200, r)

    # ── Management locks: a real ARM extension resource scoped to the topic's own id ───
    def lock_path(topic, name=None, rg=RG):
        p = f"{topic_path(topic, rg)}/providers/Microsoft.Authorization/locks"
        return f"{p}/{name}" if name else p

    r = arm.handle("GET", lock_path("t1"), {"api-version": "2016-09-01"})
    check("no locks on t1 yet", r["status"] == 200 and r["body"]["value"] == [], r)

    r = arm.handle("PUT", lock_path("t1", "lk1"), {"api-version": "2016-09-01"},
                    {"properties": {"level": "CanNotDelete", "notes": "protect the demo topic"}})
    check("create lock -> 201", r["status"] == 201, r)
    check("lock scoped under the topic id", r["body"]["id"] == lock_path("t1", "lk1"), r["body"])
    check("lock level + notes round-trip", r["body"]["properties"]["level"] == "CanNotDelete"
          and r["body"]["properties"]["notes"] == "protect the demo topic", r["body"])

    r = arm.handle("GET", lock_path("t1"), {"api-version": "2016-09-01"})
    check("list locks on t1 has lk1", [x["name"] for x in r["body"]["value"]] == ["lk1"], r["body"])

    r = arm.handle("GET", lock_path("t2", "lk1"), {"api-version": "2016-09-01"})
    check("t2 doesn't see t1's lock (scoped, not global)", r["status"] == 404, r)

    r = arm.handle("DELETE", lock_path("t1", "lk1"), {"api-version": "2016-09-01"})
    check("delete lock -> 200", r["status"] == 200, r)
    r = arm.handle("GET", lock_path("t1"), {"api-version": "2016-09-01"})
    check("lock gone after delete", r["body"]["value"] == [], r["body"])

    # ── Lock ENFORCEMENT: a CanNotDelete lock blocks delete but not writes; a ReadOnly
    # lock blocks both — on its own topic (t3), so it doesn't disturb t1's later
    # event-subscription/activity-log assertions ───────────────────────────────────────
    arm.handle("PUT", topic_path("t3"), {"api-version": AV}, {"location": "eastus"})
    arm.handle("PUT", lock_path("t3", "cnd"), {"api-version": "2016-09-01"}, {"properties": {"level": "CanNotDelete"}})
    r = arm.handle("PATCH", topic_path("t3"), {"api-version": AV}, {"tags": {"env": "prod"}})
    check("CanNotDelete lock still allows a write", r["status"] == 200 and r["body"]["tags"]["env"] == "prod", r)
    r = arm.handle("DELETE", topic_path("t3"), {"api-version": AV})
    check("CanNotDelete lock blocks delete -> 409 ScopeLocked", r["status"] == 409 and r["body"]["error"]["code"] == "ScopeLocked", r)

    arm.handle("DELETE", lock_path("t3", "cnd"), {"api-version": "2016-09-01"})
    arm.handle("PUT", lock_path("t3", "ro"), {"api-version": "2016-09-01"}, {"properties": {"level": "ReadOnly"}})
    r = arm.handle("PATCH", topic_path("t3"), {"api-version": AV}, {"tags": {"env": "staging"}})
    check("ReadOnly lock blocks writes too -> 409", r["status"] == 409, r)
    r = arm.handle("DELETE", topic_path("t3"), {"api-version": AV})
    check("ReadOnly lock blocks delete -> 409", r["status"] == 409, r)

    arm.handle("DELETE", lock_path("t3", "ro"), {"api-version": "2016-09-01"})
    r = arm.handle("DELETE", topic_path("t3"), {"api-version": AV})
    check("delete succeeds once the lock is removed", r["status"] == 200, r)

    # ── Expiration time: enforced even without a delivery runtime (real Event Grid
    # auto-deletes a subscription once expirationTimeUtc passes) ───────────────────────
    arm.handle("PUT", sub_path("t1", "es-future"), {"api-version": ESAV},
               {"properties": {"destination": {"endpointType": "WebHook"}, "expirationTimeUtc": "2999-01-01T00:00:00.000Z"}})
    r = arm.handle("PUT", sub_path("t1", "es-expired"), {"api-version": ESAV},
                   {"properties": {"destination": {"endpointType": "WebHook"}, "expirationTimeUtc": "2000-01-01T00:00:00.000Z"}})
    check("create with a past expirationTimeUtc still round-trips on the write itself", r["status"] == 201, r)
    r = arm.handle("GET", sub_path("t1", "es-expired"), {"api-version": ESAV})
    check("GET on an already-expired subscription -> 404 (auto-deleted)", r["status"] == 404, r)
    r = arm.handle("GET", topic_path("t1") + "/providers/Microsoft.EventGrid/eventSubscriptions", {"api-version": ESAV})
    names = sorted(x["name"] for x in r["body"]["value"])
    check("list sweeps the expired subscription but keeps the future one and the unexpiring one",
          names == ["es-future", "es1"], names)

    # ── Publish / delivery (data plane): filter matching + REAL delivery to a Service Bus
    # queue destination, metrics derived from actual activity (never synthetic) ───────────
    arm.handle("PUT", topic_path("t4"), {"api-version": AV}, {"location": "eastus"})
    sbstore = InMemoryMessagingStore()
    sb.dispatch(sbstore, "PUT", "eg-dest-q")   # provision the Service Bus queue entity first

    arm.handle("PUT", sub_path("t4", "deliverable"), {"api-version": ESAV}, {"properties": {
        "destination": {"endpointType": "ServiceBusQueue", "properties": {"queueName": "eg-dest-q"}},
        "filter": {"subjectBeginsWith": "/blobServices"},
    }})
    arm.handle("PUT", sub_path("t4", "nomatch"), {"api-version": ESAV}, {"properties": {
        "destination": {"endpointType": "ServiceBusQueue", "properties": {"queueName": "does-not-exist-q"}},
        "filter": {"subjectBeginsWith": "/completely/different"},
    }})
    arm.handle("PUT", sub_path("t4", "undeliverable"), {"api-version": ESAV}, {"properties": {
        "destination": {"endpointType": "WebHook", "properties": {"endpointUrl": "https://example.com/hook"}},
        "deadLetterDestination": {"endpointType": "StorageBlob"},
    }})
    arm.handle("PUT", sub_path("t4", "dropped"), {"api-version": ESAV}, {"properties": {
        "destination": {"endpointType": "WebHook", "properties": {"endpointUrl": "https://example.com/hook2"}},
    }})

    event = {"id": "ev1", "subject": "/blobServices/default/containers/c1/blobs/f.txt",
             "eventType": "Microsoft.Storage.BlobCreated", "data": {"url": "https://x/f.txt"}}
    r = eg.publish(arm.state, SUB, "t4", [event], sb_store=sbstore)
    check("publish -> 1 event accepted", r["published"] == 1, r)
    outcomes = {o["subscription"]: o["result"] for o in r["results"][0]["deliveries"]}
    check("matching ServiceBusQueue subscription -> delivered", outcomes.get("deliverable") == "delivered", outcomes)
    check("non-matching filter -> not in outcomes (never evaluated past the filter)", "nomatch" not in outcomes, outcomes)
    check("WebHook + dead-letter configured -> dead-lettered (no reachable simulator backend)", outcomes.get("undeliverable") == "dead-lettered", outcomes)
    check("WebHook with no dead-letter -> dropped", outcomes.get("dropped") == "dropped", outcomes)

    peek = sb.dispatch(sbstore, "GET", "eg-dest-q/messages")
    import json as _json
    msgs = _json.loads(peek.body or b"{}").get("messages", [])
    check("the event really landed in the Service Bus queue's backlog", len(msgs) == 1 and "BlobCreated" in msgs[0]["Body"], msgs)

    t4 = arm.state[topic_path("t4").lower()]
    metrics = t4.get("_metrics", {})
    check("PublishSuccessCount bumped once", metrics.get("PublishSuccessCount") == 1, metrics)
    check("MatchedEventCount counts only the 3 subscriptions whose filter actually matched", metrics.get("MatchedEventCount") == 3, metrics)
    check("DeliverySuccessCount reflects the one real delivery", metrics.get("DeliverySuccessCount") == 1, metrics)
    check("DeadLetteredCount + DroppedEventCount reflect the two unreachable destinations",
          metrics.get("DeadLetteredCount") == 1 and metrics.get("DroppedEventCount") == 1, metrics)

    r = eg.publish(arm.state, SUB, "ghost-topic", [event], sb_store=sbstore)
    check("publish to an unknown topic -> honest 0-published error, not a silent success", r["published"] == 0 and r.get("error") == "TopicNotFound", r)

    # ── listEventGridMetrics / deliveryStatus action verbs: the UI's read of the above,
    # over the real counters (not a second synthetic source) ───────────────────────────
    r = arm.handle("POST", topic_path("t4") + "/listEventGridMetrics", {"api-version": AV})
    check("listEventGridMetrics -> the same real counters", r["status"] == 200 and r["body"]["metrics"]["PublishSuccessCount"] == 1
          and r["body"]["metrics"]["MatchedEventCount"] == 3, r)
    r = arm.handle("POST", sub_path("t4", "deliverable") + "/deliveryStatus", {"api-version": ESAV})
    check("deliveryStatus on the delivered subscription", r["status"] == 200 and r["body"]["delivered"] == 1, r)

    # ── Activity log: every PUT/DELETE above left a real event behind ──────────────────
    r = arm.handle("GET", f"/subscriptions/{SUB}/providers/Microsoft.Insights/eventtypes/management/values",
                    {"api-version": "2015-04-01", "$filter": f"resourceUri eq '{topic_path('t1')}'"})
    check("activity log 200", r["status"] == 200, r)
    ops = [e["operationName"]["value"] for e in r["body"]["value"]]
    check("activity log sees t1's Create", "Microsoft.EventGrid/topics/write" in ops, ops)

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(run())
