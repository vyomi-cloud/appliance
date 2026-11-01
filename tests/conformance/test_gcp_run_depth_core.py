"""Depth pass on core/gcp_run_core.py (run: python3 tests/conformance/test_gcp_run_depth_core.py).

Covers the WAVE 5b gap-sweep targets for gcp.functions: real request Observability
(metrics + logs fed by actual invocations, never synthetic), Eventarc Pub/Sub-sourced
triggers that really deliver, and continuous deployment (connect a repo, "push" a build
that only lands a new revision when it actually parses). Exercised through the SAME
AwsWireRouter the console/relay use, so the cross-store wiring in
core/aws_wire_router.py is proven too, not just the core in isolation.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from core.aws_wire_router import AwsWireRouter  # noqa: E402

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' — ' + str(detail) if detail and not ok else ''}")


router = AwsWireRouter()
P, L = "p1", "us-central1"
RUN = f"/v2/projects/{P}/locations/{L}"


def call(method, path, body=None, query=None):
    r = router.handle(method, path, query or {}, {}, json.dumps(body).encode() if body is not None else b"")
    try:
        return r["status"], json.loads(r["body"] or b"{}")
    except Exception:
        return r["status"], {"raw": (r["body"] or b"")[:300]}


# ── Observability: real invoke, real metrics, real logs ───────────────────────────────────
fn_ann = {"vyomi.dev/function-runtime": "Python 3.13", "vyomi.dev/function-entry-point": "handler",
          "vyomi.dev/function-source": "def handler(event):\n    return {'echo': event}\n"}
s, op = call("POST", RUN + "/services", {"template": {"containers": [{"image": "vyomi.dev/function-source/python-3-13:a"}]},
                                         "annotations": fn_ann}, {"serviceId": "obs-fn"})
check("deploy a python function service", s == 200, op)

s, out = call("POST", RUN + "/services/obs-fn:invoke", {"hello": "world"})
check("invoke runs the real handler", s == 200 and out == {"echo": {"hello": "world"}}, out)

s, m = call("GET", f"/v3/projects/{P}/timeSeries", None,
            {"filter": 'metric.type="run.googleapis.com/request_count" AND resource.labels.service_name="obs-fn"',
             "interval.startTime": "2000-01-01T00:00:00Z", "interval.endTime": "2100-01-01T00:00:00Z"})
series = m.get("timeSeries") or []
check("a real request_count time series exists after invoke", s == 200 and len(series) == 1
      and series[0]["points"][0]["value"]["int64Value"] == "1", m)

s, le = call("POST", "/v2/entries:list", {"resourceNames": [f"projects/{P}"],
                                          "filter": 'resource.type="cloud_run_revision"'})
check("a real Cloud Logging entry exists for the invocation", s == 200 and len(le.get("entries") or []) >= 1
      and "obs-fn" in le["entries"][0].get("textPayload", ""), le)

bad_ann = dict(fn_ann, **{"vyomi.dev/function-source": "def handler(event):\n    raise ValueError('boom')\n"})
call("PATCH", RUN + "/services/obs-fn", {"annotations": bad_ann}, {"updateMask": "annotations"})
s, out = call("POST", RUN + "/services/obs-fn:invoke", {})
check("a raised exception in the handler is a real 500, not swallowed", s == 500 and "boom" in out.get("error", ""), out)

s, op = call("POST", RUN + "/services", {"template": {"containers": [{"image": "gcr.io/x/y:1"}]}}, {"serviceId": "obs-container"})
s, out = call("POST", RUN + "/services/obs-container:invoke", {})
check("a container-image service's invoke is honestly 202, not a fake 200", s == 202, out)

s, m2 = call("GET", f"/v3/projects/{P}/timeSeries", None,
             {"filter": 'metric.type="run.googleapis.com/container/instance_count" AND resource.labels.service_name="obs-fn"',
              "interval.startTime": "2000-01-01T00:00:00Z", "interval.endTime": "2100-01-01T00:00:00Z"})
check("container instance count is a real derived series", s == 200 and len(m2.get("timeSeries") or []) == 1, m2)

# ── Eventarc triggers: Pub/Sub-sourced, really deliver ─────────────────────────────────────
s, op = call("POST", RUN + "/services", {"template": {"containers": [{"image": "vyomi.dev/function-source/python-3-13:a"}]},
                                         "annotations": fn_ann}, {"serviceId": "trg-fn"})
s, _ = call("PUT", f"/v1/projects/{P}/topics/orders", {})
check("create backing pub/sub topic", s == 200)

s, trig = call("POST", RUN + "/services/trg-fn/triggers",
               {"eventFilters": [{"attribute": "type", "value": "google.cloud.pubsub.topic.v1.messagePublished"}],
                "pubsubTopic": f"projects/{P}/topics/orders"}, {"triggerId": "on-order"})
check("create trigger", s == 200 and trig["state"] == "ACTIVE" and trig["destination"]["service"] == "trg-fn", trig)

s, bad = call("POST", RUN + "/services/trg-fn/triggers",
              {"eventFilters": [{"attribute": "type", "value": "google.cloud.storage.object.v1.finalized"}]},
              {"triggerId": "on-upload"})
check("an event type with no real source is rejected, not silently accepted", s == 400, bad)

s, lst = call("GET", RUN + "/services/trg-fn/triggers")
check("list triggers", s == 200 and len(lst["triggers"]) == 1)

s, before = call("GET", f"/v3/projects/{P}/timeSeries", None,
                  {"filter": 'metric.type="run.googleapis.com/request_count" AND resource.labels.service_name="trg-fn"',
                   "interval.startTime": "2000-01-01T00:00:00Z", "interval.endTime": "2100-01-01T00:00:00Z"})
before_count = int((before.get("timeSeries") or [{}])[0].get("points", [{}])[0].get("value", {}).get("int64Value", "0")) if before.get("timeSeries") else 0

call("POST", f"/v1/projects/{P}/topics/orders:publish",
     {"messages": [{"data": "eyJvcmRlcklkIjogNDJ9", "attributes": {}}]})   # base64 '{"orderId": 42}'

s, after = call("GET", f"/v3/projects/{P}/timeSeries", None,
                 {"filter": 'metric.type="run.googleapis.com/request_count" AND resource.labels.service_name="trg-fn"',
                  "interval.startTime": "2000-01-01T00:00:00Z", "interval.endTime": "2100-01-01T00:00:00Z"})
after_count = int(after["timeSeries"][0]["points"][-1]["value"]["int64Value"]) if after.get("timeSeries") else -1
check("publishing to the topic really invokes the destination service", after_count == before_count + 1,
      f"before={before_count} after={after_count}")

s, _ = call("DELETE", RUN + "/services/trg-fn/triggers/on-order")
check("delete trigger", s == 200 and call("GET", RUN + "/services/trg-fn/triggers/on-order")[0] == 404)

# ── continuous deployment: connect a repo, build only lands on success ────────────────────
s, op = call("POST", RUN + "/services", {"template": {"containers": [{"image": "vyomi.dev/function-source/python-3-13:a"}]},
                                         "annotations": fn_ann}, {"serviceId": "cd-fn"})
s, noconn = call("POST", RUN + "/services/cd-fn/builds", {})
check("build without a connected repo is rejected", s == 400, noconn)

s, svc = call("POST", RUN + "/services/cd-fn:connectRepo", {"repository": "octo/widgets", "branch": "main"})
check("connect repo stores the connection", s == 200 and json.loads(svc["annotations"]["vyomi.dev/repo-connection"])["repository"] == "octo/widgets", svc)

s, build = call("POST", RUN + "/services/cd-fn/builds", {"source": "def handler(event):\n    return 1\n"})
check("a good push builds and deploys a real new revision", s == 200 and build["status"] == "SUCCESS" and build.get("revision"), build)
revs = call("GET", RUN + "/services/cd-fn/revisions")[1]["revisions"]
check("the build's revision is really on the Revisions tab", any(r["name"].endswith(build["revision"]) for r in revs), revs)

s, build2 = call("POST", RUN + "/services/cd-fn/builds", {"source": "def handler(:\n"})
check("a broken push fails the build, not the service", s == 200 and build2["status"] == "FAILURE", build2)
revs2 = call("GET", RUN + "/services/cd-fn/revisions")[1]["revisions"]
check("a failed build does not cut a new revision", len(revs2) == len(revs), (len(revs), len(revs2)))

s, builds = call("GET", RUN + "/services/cd-fn/builds")
check("build history lists both builds", s == 200 and len(builds["builds"]) == 2, builds)

s, _ = call("POST", RUN + "/services/cd-fn:disconnectRepo", {})
check("disconnect repo", s == 200)
check("disconnecting a repo really blocks further builds", call("POST", RUN + "/services/cd-fn/builds", {})[0] == 400)

print(f"RESULT pass={PASS} fail={FAIL}")
sys.exit(1 if FAIL else 0)
