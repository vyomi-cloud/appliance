"""Nano trigger delivery + function data planes through the native-wire router (host CPython here; the same
modules run in Pyodide in the browser): Eventarc storage/Pub/Sub -> function, /gcf HTTP trigger, Event Grid ->
Storage Queue / function with WebHook an honest 'Unsupported', function-app zip deploy + invoke."""
import base64
import io
import os
import sys
import json
import types
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from core.aws_wire_router import AwsWireRouter
from core import nano_registry


def _check(name, cond, extra=""):
    if not cond:
        raise AssertionError(f"{name} {extra}")
    print(f"  ok  {name}")


def run():
    stores = dict(nano_registry.get())
    res = types.SimpleNamespace(collections={})
    stores["resources"] = res
    r = AwsWireRouter(stores=stores)

    def call(m, p, body=b"", headers=None, query=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        out = r.handle(m, p, query or {}, headers or {"content-type": "application/json"}, body)
        return out["status"], out.get("body", b""), out.get("headers", {})

    # ---- GCP: Eventarc + HTTP Cloud Function --------------------------------------------------
    evt = ("import functions_framework\n@functions_framework.cloud_event\ndef e(ce):\n"
           "    d = ce.data or {}\n    return {'type': ce['type'], 'name': d.get('name'), 'msg': d.get('message')}\n")
    http = ("import functions_framework\nfrom flask import jsonify\n@functions_framework.http\ndef h(request):\n"
            "    print('HLOG')\n    if request.method == 'GET':\n        return 'hi ' + request.args.get('who', '?')\n"
            "    return jsonify({'echo': request.get_json(), 'x': request.headers.get('X-Probe')}), 202\n")
    res.collections["gcp/acct/functions"] = {"fnE": {"name": "fnE", "code": evt, "entryPoint": "e", "runtime": "python312"},
                                             "fnH": {"name": "fnH", "code": http, "entryPoint": "h", "runtime": "python312"}}
    st, b, _ = call("GET", "/gcf/p/us-central1/fnH", query={"who": "sam"})
    _check("GET /gcf runs the handler (request.args)", st == 200 and b == b"hi sam", (st, b))
    st, b, h = call("POST", "/gcf/p/us-central1/fnH", {"a": 1}, {"content-type": "application/json", "x-probe": "yes"})
    _check("POST /gcf: get_json + headers; return value is the HTTP response", st == 202 and json.loads(b) == {"echo": {"a": 1}, "x": "yes"}, (st, b))

    call("POST", "/storage/v1/b", {"name": "b1"})
    res.collections["gcp/acct/eventarc"] = {"t1": {"name": "t1", "eventFilters": [
        {"attribute": "type", "value": "google.cloud.storage.object.v1.finalized"}, {"attribute": "bucket", "value": "b1"}],
        "destinationSpec": {"type": "cloud-function", "service": "fnE"}}}
    call("POST", "/upload/storage/v1/b/b1/o", b"hello", {"content-type": "text/plain"}, {"uploadType": "media", "name": "dir/a.txt"})
    invs = res.collections["gcp/acct/functions"]["fnE"].get("invocations", [])
    _check("storage upload fires the Eventarc trigger at the in-browser function",
           len(invs) == 1 and json.loads(invs[0]["response"])["name"] == "dir/a.txt", invs)
    call("POST", "/storage/v1/b", {"name": "other"})
    call("POST", "/upload/storage/v1/b/other/o", b"x", {"content-type": "text/plain"}, {"uploadType": "media", "name": "z.txt"})
    _check("another bucket does not fire it", len(res.collections["gcp/acct/functions"]["fnE"]["invocations"]) == 1)

    call("PUT", "/v1/projects/nano-project/topics/tp", {})
    res.collections["gcp/acct/eventarc"]["t2"] = {"name": "t2", "eventFilters": [
        {"attribute": "type", "value": "google.cloud.pubsub.topic.v1.messagePublished"}],
        "transport": {"pubsub": {"topic": "projects/p/topics/tp"}}, "destinationSpec": {"service": "fnE"}}
    call("POST", "/v1/projects/nano-project/topics/tp:publish", {"messages": [{"data": base64.b64encode(b"ping").decode(), "attributes": {"k": "v"}}]})
    invs = res.collections["gcp/acct/functions"]["fnE"]["invocations"]
    _check("Pub/Sub publish fires the messagePublished CloudEvent",
           len(invs) == 2 and json.loads(invs[1]["response"])["msg"]["attributes"] == {"k": "v"}, invs)

    # ---- Azure: Event Grid + function app -----------------------------------------------------
    sub = "/subscriptions/s/resourceGroups/rg/providers/Microsoft.EventGrid/topics/t1"
    arm = r.az_arm.state
    arm[sub.lower()] = {"id": sub, "name": "t1", "type": "Microsoft.EventGrid/topics", "properties": {}}
    arm[(sub + "/providers/Microsoft.EventGrid/eventSubscriptions/q").lower()] = {
        "id": sub + "/providers/Microsoft.EventGrid/eventSubscriptions/q", "name": "q", "type": "Microsoft.EventGrid/eventSubscriptions",
        "properties": {"destination": {"endpointType": "StorageQueue", "properties": {"queueName": "evq", "resourceId": "/x/acct"}},
                       "filter": {"includedEventTypes": ["A.B"]}}}
    arm[(sub + "/providers/Microsoft.EventGrid/eventSubscriptions/w").lower()] = {
        "id": sub + "/providers/Microsoft.EventGrid/eventSubscriptions/w", "name": "w", "type": "Microsoft.EventGrid/eventSubscriptions",
        "properties": {"destination": {"endpointType": "WebHook", "properties": {"endpointUrl": "http://example.invalid/h"}}}}
    arm["/subscriptions/s/resourcegroups/rg/providers/microsoft.web/sites/app1"] = {
        "id": "/subscriptions/s/resourceGroups/rg/providers/Microsoft.Web/sites/app1", "name": "app1", "type": "Microsoft.Web/sites",
        "kind": "functionapp", "properties": {}}
    ev = [{"id": "1", "eventType": "A.B", "subject": "/s", "eventTime": "2026-01-01T00:00:00Z", "data": {"k": 1}, "dataVersion": "1.0"},
          {"id": "2", "eventType": "C.D", "subject": "/s", "eventTime": "2026-01-01T00:00:00Z", "data": {}, "dataVersion": "1.0"}]
    st, b, _ = call("POST", "/azure-data/eventgrid/t1/api/events", ev)
    out = json.loads(b)
    _check("Event Grid publish via the shown endpoint", st == 200 and out["published"] == 2, (st, b))
    msgs = r.az_queue.messages("evq")
    _check("StorageQueue destination received exactly the matching event (filter applied)", len(msgs) == 1, msgs)
    _check("WebHook destination is an explicit 'Unsupported' (not silently dropped)",
           out["skippedUnsupported"] == 1 and arm[(sub + "/providers/Microsoft.EventGrid/eventSubscriptions/w").lower()]["_deliveries"][-1]["status"] == "Unsupported")
    st, b, _ = call("POST", "/azure-data/functions/app1/hello", {"n": 1})
    _check("function app without code -> clear 404", st == 404 and b"no code is deployed" in b, (st, b))
    z = io.BytesIO()
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("function_app.py", "import azure.functions as func\nimport json\napp = func.FunctionApp()\n"
                    "@app.route(route='hello')\ndef hello(req):\n    return func.HttpResponse(json.dumps({'got': req.get_json(), 'who': req.params.get('who')}), status_code=201, mimetype='application/json')\n")
    st, _, _ = call("POST", "/azure-data/functions/app1/api/zipdeploy", z.getvalue(), {"content-type": "application/zip"})
    _check("zip deploy", st == 200)
    st, b, _ = call("POST", "/azure-data/functions/app1/api/hello", {"n": 7}, query={"who": "me"})
    _check("deployed code runs in the in-browser sandbox; HttpResponse is the HTTP response",
           st == 201 and json.loads(b) == {"got": {"n": 7}, "who": "me"}, (st, b))
    print("\nNano trigger delivery: ALL GREEN")


if __name__ == "__main__":
    run()
