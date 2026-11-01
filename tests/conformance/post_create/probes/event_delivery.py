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
import base64, http.server, io, json, os, sys, threading, time, urllib.request, urllib.error, zipfile

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


if __name__ == "__main__":
    {"aws": aws}.get(CLOUD, lambda: check(False, f"{CLOUD} not implemented"))()
    sys.exit(1 if fails else 0)
