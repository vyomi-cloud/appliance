#!/usr/bin/env python3
"""Post-create probe: events are DELIVERED and uploaded function code RUNS (offline appliance).

  python3 event_delivery.py aws|gcp|azure http://localhost:9000

aws  : Lambda CreateFunction(ZipFile) runs the uploaded handler (+ LogType=Tail, FunctionError);
       EventBridge rule with SQS + Lambda targets (pattern language incl. numeric/prefix/anything-but/exists,
       InputTransformer); Step Functions Lambda Task completes with the Lambda's output.
gcp  : Eventarc storage-finalized trigger -> function fired with a CloudEvent after a real object upload;
       HTTP Cloud Function gets a Flask-like request and returns its own body/status.
azure: Event Grid webhook subscription called with the published event.
Uses the official SDK where installed (boto3), REST otherwise. One [PASS]/[FAIL] line per check, exit 1 on any failure.
"""
import base64, http.server as hs, io, json, os, sys, threading, time, urllib.request, urllib.error, uuid, zipfile

CLOUD = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] in ("aws", "gcp", "azure") else "aws"
BASE = (sys.argv[-1] if sys.argv[-1].startswith("http") else os.environ.get("VYOMI_ENDPOINT", "http://localhost:9000")).rstrip("/")
fails = 0


def check(ok, name, why=""):
    global fails
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + ("" if ok else f" :: {why}"), flush=True)
    fails += 0 if ok else 1
    return ok


def http(method, url, body=None, headers=None, raw=False):
    data = body if isinstance(body, (bytes, type(None))) else json.dumps(body).encode()
    h = {"content-type": "application/json", **(headers or {})}
    req = urllib.request.Request(url if url.startswith("http") else BASE + url, method=method, data=data, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            d = r.read()
            return r.status, (d if raw else (json.loads(d) if d[:1] in (b"{", b"[") else d.decode(errors="replace")))
    except urllib.error.HTTPError as e:
        d = e.read()
        try:
            return e.code, json.loads(d)
        except Exception:
            return e.code, d.decode(errors="replace")


def until(fn, secs=15):
    end = time.time() + secs
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.5)
    return None


def aws():
    import boto3
    kw = dict(endpoint_url=BASE, region_name="us-east-1", aws_access_key_id="test", aws_secret_access_key="test")
    lam, ev, sqs, sfn = (boto3.client(x, **kw) for x in ("lambda", "events", "sqs", "stepfunctions"))
    tag = f"pc{int(time.time()) % 100000}"
    fn, q, rule, sm = f"{tag}-fn", f"{tag}-q", f"{tag}-rule", f"{tag}-sm"
    src = ("import json\ndef handler(event, context):\n    print('LOGLINE-' + context.function_name)\n"
           "    if event.get('boom'):\n        raise ValueError('boom')\n"
           "    return {'echo': event, 'fn': context.function_name}\n")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("index.py", src)
    qurl = None
    try:
        lam.create_function(FunctionName=fn, Runtime="python3.12", Role="arn:aws:iam::123456789012:role/x",
                            Handler="index.handler", Code={"ZipFile": buf.getvalue()})
        r = lam.invoke(FunctionName=fn, Payload=json.dumps({"n": 3}), LogType="Tail")
        out = json.loads(r["Payload"].read())
        check(out.get("echo") == {"n": 3} and out.get("fn") == fn, "Lambda: create_function(ZipFile) runs the uploaded handler", out)
        check("LOGLINE-" + fn in base64.b64decode(r.get("LogResult", "")).decode(), "Lambda: LogType=Tail returns the handler's print", r.get("LogResult"))
        r = lam.invoke(FunctionName=fn, Payload=json.dumps({"boom": 1}))
        body = json.loads(r["Payload"].read())
        check(r.get("FunctionError") and body.get("errorType") == "ValueError", "Lambda: handler exception -> FunctionError + errorType", (r.get("FunctionError"), body))

        qurl = sqs.create_queue(QueueName=q)["QueueUrl"]
        qarn = sqs.get_queue_attributes(QueueUrl=qurl, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]
        farn = lam.get_function(FunctionName=fn).get("Configuration", {}).get("FunctionArn") or f"arn:aws:lambda:us-east-1:123456789012:function:{fn}"
        ev.put_rule(Name=rule, EventPattern=json.dumps({"source": [tag], "detail": {
            "price": [{"numeric": [">", 10]}], "kind": [{"prefix": "ord"}], "env": [{"anything-but": "test"}],
            "ok": [{"exists": True}]}}), State="ENABLED")
        ev.put_targets(Rule=rule, Targets=[
            {"Id": "q", "Arn": qarn},
            {"Id": "l", "Arn": farn, "InputTransformer": {"InputPathsMap": {"p": "$.detail.price"}, "InputTemplate": '{"price": <p>, "via": "events"}'}}])

        def put(detail):
            return ev.put_events(Entries=[{"Source": tag, "DetailType": "t", "Detail": json.dumps(detail)}])["FailedEntryCount"]
        put({"price": 5, "kind": "order", "env": "prod", "ok": 1})        # numeric fails
        put({"price": 50, "kind": "order", "env": "test", "ok": 1})       # anything-but fails
        put({"price": 50, "kind": "xorder", "env": "prod", "ok": 1})      # prefix fails
        put({"price": 50, "kind": "order", "env": "prod"})                # exists fails
        put({"price": 50, "kind": "order-1", "env": "prod", "ok": 1})     # matches
        msgs = until(lambda: sqs.receive_message(QueueUrl=qurl, MaxNumberOfMessages=10, WaitTimeSeconds=1).get("Messages"), 15) or []
        bodies = [json.loads(m["Body"]) for m in msgs]
        check(len(bodies) == 1 and bodies[0].get("detail", {}).get("price") == 50,
              "EventBridge: only the matching event reaches the SQS target (numeric/prefix/anything-but/exists)", bodies)

        def lam_calls():
            try:
                return http("GET", f"/api/lambda/functions/{fn}/invocations")[1].get("invocations") or []
            except Exception:
                return []
        inv = until(lambda: [i for i in lam_calls() if (i.get("request_payload") or {}).get("via") == "events"], 15)
        check(bool(inv) and len(inv) == 1 and inv[0]["request_payload"].get("price") == 50,
              "EventBridge: Lambda target invoked once with the InputTransformer payload", inv)

        defn = json.dumps({"StartAt": "L", "States": {"L": {"Type": "Task", "Resource": farn, "End": True}}})
        sm_arn = sfn.create_state_machine(name=sm, definition=defn, roleArn="arn:aws:iam::123456789012:role/x")["stateMachineArn"]
        ex = sfn.start_execution(stateMachineArn=sm_arn, input=json.dumps({"n": 9}))["executionArn"]
        d = until(lambda: (lambda x: x if x["status"] != "RUNNING" else None)(sfn.describe_execution(executionArn=ex)), 20) or {}
        out = json.loads(d.get("output") or "{}") if d.get("status") == "SUCCEEDED" else d
        check(d.get("status") == "SUCCEEDED" and out.get("echo") == {"n": 9}, "Step Functions: Lambda Task completes with the Lambda's output", out)
        try:
            sfn.delete_state_machine(stateMachineArn=sm_arn)
        except Exception:
            pass
    finally:
        for f in (lambda: ev.remove_targets(Rule=rule, Ids=["q", "l"]), lambda: ev.delete_rule(Name=rule),
                  lambda: sqs.delete_queue(QueueUrl=qurl), lambda: lam.delete_function(FunctionName=fn)):
            try:
                f()
            except Exception:
                pass


GP = "vyomi-project"
GL = "us-central1"


def gcp():
    tag = f"pc{int(time.time()) % 100000}"
    bucket, hfn, efn, trig, ptrig, topic = f"{tag}-b", f"{tag}-http", f"{tag}-evt", f"{tag}-trig", f"{tag}-ptrig", f"{tag}-topic"
    fbase = f"/api/gcp/cloudfunctions/v2/projects/{GP}/locations/{GL}/functions"
    http_src = ("import functions_framework\nfrom flask import jsonify\n\n@functions_framework.http\n"
                "def h(request):\n    print('HTTPLOG')\n    if request.method == 'GET':\n        return 'hello ' + request.args.get('who', 'anon')\n"
                "    body = request.get_json(silent=True) or {}\n"
                "    return jsonify({'echo': body, 'method': request.method, 'ua': request.headers.get('X-Probe')}), 202\n")
    # the event function returns what it received; the platform records it in the function's invocations
    evt_src = ("import functions_framework\n\n@functions_framework.cloud_event\n"
               "def e(ce):\n    d = ce.data or {}\n"
               "    return {'type': ce['type'], 'subject': ce.get('subject'), 'bucket': d.get('bucket'), 'name': d.get('name'), 'msg': d.get('message')}\n")

    def seen(kind):
        for inv in (http("GET", fbase + "/" + efn)[1].get("invocations") or []):
            try:
                r = json.loads(inv.get("response") or "null")
            except Exception:
                continue
            if isinstance(r, dict) and r.get("type") == kind:
                return r
        return None
    try:
        # ---- item 6: HTTP-triggered function behaves like the real one -------------------------
        st, op = http("POST", fbase + f"?functionId={hfn}", {"name": hfn, "runtime": "python312", "entryPoint": "h", "code": http_src, "httpsTrigger": {}})
        view = http("GET", fbase + "/" + hfn)[1]
        url = (view.get("httpsTrigger") or {}).get("url") or (view.get("serviceConfig") or {}).get("uri") or ""
        check(bool(url) and not url.endswith(":call"), "Cloud Functions: shown trigger URL is a plain invoke URL", url)
        s1, b1 = http("GET", url + "?who=sam")
        check(s1 == 200 and b1 == "hello sam", "Cloud Functions: GET on the trigger URL runs the handler (request.args)", (s1, b1))
        s2, b2 = http("POST", url, {"a": 1}, {"X-Probe": "yes"})
        check(s2 == 202 and b2 == {"echo": {"a": 1}, "method": "POST", "ua": "yes"},
              "Cloud Functions: POST handler gets get_json()/headers; return value is the HTTP body+status (no envelope)", (s2, b2))
        s3, b3 = http("POST", f"{fbase}/{hfn}:call", {"a": 1})
        check(s3 == 200 and isinstance(b3, dict) and "executionId" in b3, "Cloud Functions: ':call' management route keeps the execution envelope", (s3, b3))

        # ---- item 4: Eventarc storage-finalized + pubsub -> function --------------------------
        http("POST", "/storage/v1/b", {"name": bucket})
        http("POST", fbase + f"?functionId={efn}", {"name": efn, "runtime": "python312", "entryPoint": "e", "code": evt_src,
                                                      "eventTrigger": {"eventType": STORAGE}})
        efn_name = f"projects/{GP}/locations/{GL}/functions/{efn}"
        s4, t = http("POST", f"/v1/projects/{GP}/locations/{GL}/triggers?triggerId={trig}", {
            "eventFilters": [{"attribute": "type", "value": STORAGE}, {"attribute": "bucket", "value": bucket}],
            "destination": {"cloudFunction": efn_name}})
        check(s4 < 300 and str(t.get("name", "")).endswith("/triggers/" + trig), "Eventarc: triggerId is honoured on create", t)
        http("POST", f"/upload/storage/v1/b/{bucket}/o?uploadType=media&name=dir%2Fhello.txt", b"hi there", {"content-type": "text/plain"})
        got = until(lambda: seen(STORAGE), 20)
        check(isinstance(got, dict) and got.get("type") == STORAGE and got.get("bucket") == bucket and got.get("name") == "dir/hello.txt",
              "Eventarc: object upload fires the storage-finalized CloudEvent at the function", got)
        # pubsub
        http("PUT", f"/v1/projects/{GP}/topics/{topic}", {})
        http("POST", f"/v1/projects/{GP}/locations/{GL}/triggers?triggerId={ptrig}", {
            "eventFilters": [{"attribute": "type", "value": PUBSUB}], "transport": {"pubsub": {"topic": f"projects/{GP}/topics/{topic}"}},
            "destination": {"cloudFunction": efn_name}})
        http("POST", f"/v1/projects/{GP}/topics/{topic}:publish", {"messages": [{"data": base64.b64encode(b"ping").decode(), "attributes": {"k": "v"}}]})
        got = until(lambda: seen(PUBSUB), 20)
        check(isinstance(got, dict) and got.get("type") == PUBSUB and (got.get("msg") or {}).get("attributes") == {"k": "v"},
              "Eventarc: Pub/Sub publish fires the messagePublished CloudEvent at the function", got)
    finally:
        for m, u in (("DELETE", f"/v1/projects/{GP}/locations/{GL}/triggers/{trig}"), ("DELETE", f"/v1/projects/{GP}/locations/{GL}/triggers/{ptrig}"),
                     ("DELETE", fbase + "/" + hfn), ("DELETE", fbase + "/" + efn), ("DELETE", f"/v1/projects/{GP}/topics/{topic}")):
            try:
                http(m, u)
            except Exception:
                pass


STORAGE = "google.cloud.storage.object.v1.finalized"
PUBSUB = "google.cloud.pubsub.topic.v1.messagePublished"


SUBID = "00000000-0000-0000-0000-cloudlearn01"


def azure():
    tag = f"pc{int(time.time()) % 100000}"
    rg, topic, app = f"{tag}-rg", f"{tag}-topic", f"{tag}-app"
    arm = f"/subscriptions/{SUBID}/resourceGroups/{rg}/providers"
    got, lock = [], threading.Lock()

    class H(hs.BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers.get("content-length") or 0)
            with lock:
                got.append((self.headers.get("content-type"), self.headers.get("aeg-event-type"), json.loads(self.rfile.read(n) or b"null")))
            self.send_response(200); self.end_headers()
        def log_message(self, *a): pass
    srv = hs.ThreadingHTTPServer(("0.0.0.0", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    hook = f"http://{os.environ.get('VYOMI_HOOK_HOST', 'host.docker.internal')}:{srv.server_port}/hook"   # host as seen from the appliance container
    try:
        http("PUT", f"/subscriptions/{SUBID}/resourcegroups/{rg}?api-version=2021-04-01", {"location": "eastus"})
        st, t = http("PUT", f"{arm}/Microsoft.EventGrid/topics/{topic}?api-version=2024-06-01-preview", {"location": "eastus", "properties": {}})
        endpoint = (t.get("properties") or {}).get("endpoint", "")
        for name, schema in (("sub-eg", "EventGridSchema"), ("sub-ce", "CloudEventSchemaV1_0")):
            http("PUT", f"{arm}/Microsoft.EventGrid/topics/{topic}/providers/Microsoft.EventGrid/eventSubscriptions/{name}?api-version=2024-06-01-preview",
                 {"properties": {"destination": {"endpointType": "WebHook", "properties": {"endpointUrl": hook}}, "eventDeliverySchema": schema,
                                 "filter": {"includedEventTypes": ["App.Thing.Created"], "subjectBeginsWith": "/things/"}}})
        ev = lambda t_, subj: [{"id": uuid.uuid4().hex, "eventType": t_, "subject": subj, "eventTime": "2026-01-01T00:00:00Z", "data": {"k": 1}, "dataVersion": "1.0"}]
        s1, _ = http("POST", endpoint, ev("App.Thing.Created", "/things/1"), {"aeg-sas-key": "x"})
        check(s1 == 200, "Event Grid: publishing to the endpoint shown on the topic works (no /api 404)", (endpoint, s1))
        http("POST", endpoint, ev("Other.Type", "/things/2"))
        http("POST", endpoint, ev("App.Thing.Created", "/other/3"))
        until(lambda: len(got) >= 2, 20)
        time.sleep(1.5)
        eg = [g for g in got if g[1] == "Notification"]
        ce = [g for g in got if "cloudevents" in (g[0] or "")]
        check(len(got) == 2 and len(eg) == 1 and len(ce) == 1, "Event Grid: webhook subscriptions called once each; filters drop the non-matching events", [(g[0], g[1]) for g in got])
        check(bool(eg) and eg[0][2][0].get("eventType") == "App.Thing.Created" and eg[0][2][0].get("data") == {"k": 1},
              "Event Grid: EventGridSchema payload delivered", eg[:1])
        check(bool(ce) and ce[0][2][0].get("type") == "App.Thing.Created" and ce[0][2][0].get("specversion") == "1.0",
              "Event Grid: CloudEvents payload delivered for a CloudEvents-schema subscription", ce[:1])

        # ---- item 7: function app runs uploaded code; data plane works whatever space is active ----
        http("PUT", f"{arm}/Microsoft.Web/sites/{app}?api-version=2023-12-01", {"location": "eastus", "kind": "functionapp", "properties": {}})
        s2, b2 = http("POST", f"/azure-data/functions/{app}/hello", {"n": 1})
        check(s2 == 404 and "no code is deployed" in json.dumps(b2), "Function app: no code -> clear 404, not a canned FALLBACK success", (s2, b2))
        z = io.BytesIO()
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("function_app.py", "import azure.functions as func\nimport json\napp = func.FunctionApp()\n\n"
                        "@app.route(route='hello', auth_level=func.AuthLevel.ANONYMOUS)\n"
                        "def hello(req: func.HttpRequest) -> func.HttpResponse:\n"
                        "    b = req.get_json() if req.method == 'POST' else {}\n"
                        "    return func.HttpResponse(json.dumps({'got': b, 'who': req.params.get('who')}), status_code=201, mimetype='application/json')\n")
        s3, _ = http("POST", f"/azure-data/functions/{app}/api/zipdeploy", z.getvalue(), {"content-type": "application/zip"})
        check(s3 == 200, "Function app: zip deploy accepted", s3)
        s4, b4 = http("POST", f"/azure-data/functions/{app}/api/hello?who=me", {"n": 7})
        check(s4 == 201 and b4 == {"got": {"n": 7}, "who": "me"}, "Function app: uploaded code runs; handler's HttpResponse is the HTTP response", (s4, b4))
    finally:
        srv.shutdown()
        try:
            http("DELETE", f"/subscriptions/{SUBID}/resourcegroups/{rg}?api-version=2021-04-01")
        except Exception:
            pass


if __name__ == "__main__":
    {"aws": aws, "gcp": gcp, "azure": azure}.get(CLOUD, lambda: check(False, f"{CLOUD} not implemented"))()
    sys.exit(1 if fails else 0)
