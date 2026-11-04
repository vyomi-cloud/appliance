"""Event Grid delivery to StorageQueue and WebHook destinations through the substrate seams.
Run: PYTHONPATH=. python tests/conformance/test_azure_eventgrid_destinations.py"""
import json
try:
    from core import azure_eventgrid_core as eg, azure_queue_core as aq
except ImportError:  # pragma: no cover
    import azure_eventgrid_core as eg, azure_queue_core as aq  # type: ignore


def _check(n, c):
    if not c:
        raise AssertionError(n)
    print("  ok ", n)


def run():
    T = "/subscriptions/s/resourcegroups/rg/providers/microsoft.eventgrid/topics/t1"
    state = {T: {"id": T, "name": "t1", "_type": "Microsoft.EventGrid/topics", "properties": {}}}
    def sub(name, dest, **extra):
        state[f"{T}/es/{name}"] = {"name": name, "_parent": T, "properties": {"destination": dest, **extra}}
    sub("q", {"endpointType": "StorageQueue", "properties": {"queueName": "events", "resourceId": "/subscriptions/s/x"}})
    sub("w", {"endpointType": "WebHook", "properties": {"endpointUrl": "http://127.0.0.1:9/hook"}}, deadLetterDestination={"endpointType": "StorageBlob"})
    ev = [{"id": "1", "eventType": "app.created", "subject": "/a", "data": {"x": 1}, "dataVersion": "1.0"}]
    store = aq.AzureQueueStore()
    eg.bind_destinations(None, None)
    out = eg.deliver(state, T, ev[0])
    _check("no seams -> queue dropped, webhook dead-lettered", {o["subscription"]: o["result"] for o in out} == {"q": "dropped", "w": "dead-lettered"})
    eg.bind_destinations(lambda: store, None)
    out = {o["subscription"]: o["result"] for o in eg.deliver(state, T, ev[0])}
    _check("missing queue fails delivery", out["q"] == "dropped")
    aq.dispatch(store, "PUT", "/events", {}, {}, b"")
    out = {o["subscription"]: o["result"] for o in eg.deliver(state, T, ev[0])}
    _check("existing queue receives the event", out["q"] == "delivered")
    peek = aq.dispatch(store, "GET", "/events/messages", {"peekonly": "true"}, {}, b"")
    _check("queue message carries the event JSON", b"app.created" in peek.body)
    calls = []
    eg.bind_destinations(lambda: store, lambda url, body, h: (calls.append((url, json.loads(body), h)), 200)[1])
    out = {o["subscription"]: o["result"] for o in eg.deliver(state, T, ev[0])}
    _check("webhook delivered", out["w"] == "delivered" and calls and calls[0][1][0]["eventType"] == "app.created" and calls[0][2]["aeg-event-type"] == "Notification")
    eg.bind_destinations(lambda: store, lambda url, body, h: 500)
    _check("webhook 500 fails delivery", {o["subscription"]: o["result"] for o in eg.deliver(state, T, ev[0])}["w"] == "dead-lettered")
    eg.bind_destinations(None, None)
    print("eventgrid destinations: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
