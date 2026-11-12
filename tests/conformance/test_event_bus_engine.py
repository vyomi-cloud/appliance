"""Shared event-bus engine (core/event_bus_engine.py): retries with exponential backoff against a REAL local HTTP target,
dead-lettering after max attempts, per-ordering-key ordering, filters, delivery history.
Run: PYTHONPATH=. python tests/conformance/test_event_bus_engine.py"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from core import event_bus_engine as eb


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


class Receiver:
    """Real local HTTP server. `fail_first[path]` = number of initial 503s before it answers 200."""
    def __init__(self):
        self.got, self.fail_first, self.lock = [], {}, threading.Lock()
        outer = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("content-length", 0))) or b"{}")
                with outer.lock:
                    n = outer.fail_first.get(self.path, 0)
                    outer.got.append((self.path, body, self.headers.get("x-vyomi-delivery-attempt")))
                    if n > 0:
                        outer.fail_first[self.path] = n - 1
                        code = 503
                    else:
                        code = 200
                self.send_response(code)
                self.send_header("content-length", "0")
                self.end_headers()

            def log_message(self, *a):
                pass
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = "http://127.0.0.1:%d" % self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()


def eventarc_section(rx):
    """Eventarc routed through the engine, via the real wire router: Pub/Sub -> trigger -> real HTTP receiver."""
    import base64
    import time
    from core.aws_wire_router import AwsWireRouter
    AwsWireRouter.STRICT_GCP_PROJECT = False
    r = AwsWireRouter()
    P, L = "demo", "us-central1"

    def call(method, path, body=None, query=None):
        out = r.handle(method, path, query or {}, {}, json.dumps(body).encode() if body is not None else b"")
        return out["status"], json.loads(out["body"] or b"{}")
    T = f"/v1/projects/{P}/locations/{L}/triggers"
    flt = [{"attribute": "type", "value": "google.cloud.pubsub.topic.v1.messagePublished"}]
    rp = {"maxAttempts": 3, "minRetryDelay": "0.1s", "maxRetryDelay": "0.4s"}
    call("PUT", f"/v1/projects/{P}/topics/dead", {})
    s, e = call("POST", T, {"eventFilters": flt, "destination": {"httpEndpoint": {"uri": rx.url + "/ea-flaky"}}, "retryPolicy": rp}, {"triggerId": "flaky"})
    _check("eventarc trigger with httpEndpoint + retryPolicy created", s == 200)
    topic = e["response"]["transport"]["pubsub"]["topic"]
    rx.fail_first["/ea-flaky"] = 2
    s, _ = call("POST", f"/v1/{topic}:publish", {"messages": [{"data": base64.b64encode(b"x").decode()}]})
    s, d = call("GET", f"{T}/flaky/deliveries")
    _check("first attempt inline failed; delivery is RETRYING", d["deliveries"][0]["status"] == "RETRYING" and d["delivered"] == 0)
    for _ in range(40):
        time.sleep(0.1)
        s, d = call("GET", f"{T}/flaky/deliveries")
        if d["delivered"]:
            break
    _check("eventarc retried with backoff and delivered to the real receiver", d["delivered"] == 1 and d["deliveries"][0]["attemptCount"] == 3
           and [a["ok"] for a in d["deliveries"][0]["attempts"]] == [False, False, True])
    s, e = call("POST", T, {"eventFilters": flt, "destination": {"httpEndpoint": {"uri": rx.url + "/ea-dead"}}, "retryPolicy": {"maxAttempts": 2, "minRetryDelay": "0.1s"},
                            "deadLetterTopic": f"projects/{P}/topics/dead"}, {"triggerId": "dl"})
    rx.fail_first["/ea-dead"] = 99
    topic = e["response"]["transport"]["pubsub"]["topic"]
    call("POST", f"/v1/{topic}:publish", {"messages": [{"data": base64.b64encode(b"y").decode()}]})
    for _ in range(40):
        time.sleep(0.1)
        s, d = call("GET", f"{T}/dl/deliveries")
        if d["deadLettered"]:
            break
    _check("eventarc dead-letters to the Pub/Sub dead-letter topic after maxAttempts", d["deadLettered"] == 1 and d["deliveries"][0]["deadLetter"]["ok"] and d["deliveries"][0]["attemptCount"] == 2)
    _check("httpEndpoint destination must be an http(s) URL", call("POST", T, {"eventFilters": flt, "destination": {"httpEndpoint": {"uri": "ftp://x"}}}, {"triggerId": "bad"})[0] == 400)


def run() -> int:
    rx = Receiver()
    now = [1000.0]
    bus = eb.EventBus(eb.http_deliver, clock=lambda: now[0], sleep=lambda d: now.__setitem__(0, now[0] + d), auto_pump=False)

    # delivery to a REAL local HTTP receiver
    ev = eb.cloud_event("t.ok", "//src", {"a": 1}, subject="s/1")
    rec = bus.dispatch({"id": "s1", "target": {"url": rx.url + "/ok"}}, ev)
    _check("real HTTP receiver got the CloudEvent", rec["status"] == eb.DELIVERED and rx.got[0][1]["id"] == ev["id"] and rx.got[0][1]["specversion"] == "1.0")

    # retries: 2 failures (503) then success, exponential backoff 1s,2s on the injected clock
    rx.fail_first["/flaky"] = 2
    rec = bus.dispatch({"id": "s2", "target": {"url": rx.url + "/flaky"}, "retry": {"max_attempts": 5, "min_backoff": 1, "multiplier": 2}}, eb.cloud_event("t.f", "//src"))
    _check("first attempt failed and retry is scheduled with backoff", rec["status"] == eb.RETRYING and rec["next_at"] == 1000.0 + 1 and rec["attempts"][0]["status"] == "503")
    _check("not retried before its backoff elapsed", bus.tick(now[0] + 0.5) == 0)
    bus.tick(now[0] + 1)
    _check("second attempt failed, backoff doubled", rec["status"] == eb.RETRYING and abs(rec["next_at"] - (1001.0 + 2)) < 1e-6)
    bus.tick(now[0] + 3)
    _check("third attempt succeeded after retries", rec["status"] == eb.DELIVERED and [a["ok"] for a in rec["attempts"]] == [False, False, True])
    _check("receiver saw 3 attempts with attempt numbers", [g[2] for g in rx.got if g[0] == "/flaky"] == ["1", "2", "3"])
    v = bus.get(rec["id"])
    _check("attempt history exposed", v["attemptCount"] == 3 and v["attempts"][0]["error"] == "HTTP 503")

    # dead-letter after max attempts (target always 503), DLQ is another real HTTP endpoint
    rx.fail_first["/dead"] = 99
    rec = bus.dispatch({"id": "s3", "target": {"url": rx.url + "/dead"}, "dead_letter": {"url": rx.url + "/dlq"},
                        "retry": {"max_attempts": 3, "min_backoff": 1, "multiplier": 2}}, eb.cloud_event("t.d", "//src"))
    bus.drain()
    _check("dead-lettered after exactly max_attempts", rec["status"] == eb.DEAD_LETTERED and len(rec["attempts"]) == 3)
    _check("DLQ endpoint really received the event", any(g[0] == "/dlq" and g[1]["id"] == rec["eventId"] for g in rx.got))
    rec2 = bus.dispatch({"id": "s4", "target": {"url": rx.url + "/dead"}, "retry": {"max_attempts": 2, "min_backoff": 0.1}}, eb.cloud_event("t.d", "//src"))
    bus.drain()
    _check("no DLQ => FAILED (dropped) after max attempts", rec2["status"] == eb.FAILED and len(rec2["attempts"]) == 2)
    _check("unreachable target fails honestly", bus.dispatch({"id": "s5", "target": {"url": "http://127.0.0.1:1/x"}, "retry": {"max_attempts": 1}}, eb.cloud_event("t", "//s"))["status"] == eb.FAILED)

    # ordering per key: head fails -> same-key follower waits, other key / unordered are not blocked
    order, fail = [], {"k1-a": 1}

    def dl(target, event):
        tag = event["data"]["tag"]
        if fail.get(tag, 0) > 0:
            fail[tag] -= 1
            return False
        order.append(tag)
        return True
    ob = eb.EventBus(dl, clock=lambda: now[0], auto_pump=False)
    sub = {"id": "o", "target": "x", "ordered": True, "retry": {"max_attempts": 4, "min_backoff": 5}}
    r1 = ob.dispatch(sub, eb.cloud_event("t", "//s", {"tag": "k1-a"}), "k1")
    r2 = ob.dispatch(sub, eb.cloud_event("t", "//s", {"tag": "k1-b"}), "k1")
    r3 = ob.dispatch(sub, eb.cloud_event("t", "//s", {"tag": "k2-a"}), "k2")
    _check("other key delivered while k1 head is retrying", order == ["k2-a"] and r2["status"] == eb.PENDING and r1["status"] == eb.RETRYING)
    ob.tick(now[0] + 5)
    _check("same-key order preserved (a before b) after the retry", order == ["k2-a", "k1-a", "k1-b"] and r2["status"] == eb.DELIVERED and r3["status"] == eb.DELIVERED)

    # subscriptions + filters + fan-out
    fb = eb.EventBus(lambda t, e: True, auto_pump=False)
    fb.add_subscription("a", "t", [{"attribute": "type", "value": "x.created"}, {"attribute": "subject", "operator": "prefix", "value": "objects/"}])
    fb.add_subscription("b", "t", [{"attribute": "data.n", "operator": "any-of", "value": [1, 2]}])
    ids = fb.publish(eb.cloud_event("x.created", "//s", {"n": 2}, subject="objects/a"))
    _check("publish fans out to every matching subscription", len(ids) == 2)
    _check("filters exclude non-matching events", fb.publish(eb.cloud_event("x.deleted", "//s", {"n": 9}, subject="other")) == [])
    _check("stats/history by subscription", fb.stats("a")["delivered"] == 1 and len(fb.history("b")) == 1)

    # sync policy (EventBridge/Event Grid style): final outcome within the same call
    calls = []
    sb = eb.EventBus(lambda t, e: calls.append(1) or len(calls) >= 3, auto_pump=False)
    rec = sb.dispatch({"id": "q", "target": "x", "retry": {"max_attempts": 5, "sync": True, "min_backoff": 0}}, eb.cloud_event("t", "//s"))
    _check("sync retries resolve inline", rec["status"] == eb.DELIVERED and len(calls) == 3)
    eventarc_section(rx)
    json.dumps(bus.state)
    _check("state is JSON-serialisable (persistable)", True)
    rx.close()
    print("event bus engine: all green")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
