"""Azure Event Grid conformance — topics (generic ARM catalog CRUD) + event subscriptions
(core/azure_eventgrid_core.py, the extension-resource shape scoped to a topic).

Run: PYTHONPATH=. python3 tests/conformance/test_azure_eventgrid_core.py
"""
try:
    from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION
except ImportError:  # pragma: no cover - Pyodide flat layout
    from azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION  # type: ignore

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

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(run())
