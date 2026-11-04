"""App Hub applications/services/workloads (Application monitoring) + Memorystore Monitoring metrics
(run: PYTHONPATH=. python3 tests/conformance/test_gcp_apphub_redis_metrics.py)."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from core.aws_wire_router import AwsWireRouter  # noqa: E402

AwsWireRouter.STRICT_GCP_PROJECT = False   # engine test: ad-hoc project ids
R = AwsWireRouter()
PASS = FAIL = 0
P = "hub-proj-1"


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' - ' + str(detail)[:300] if detail and not ok else ''}")


def call(method, path, body=None, query=None):
    out = R.handle(method, path, query or {}, {}, json.dumps(body).encode() if body is not None else b"")
    try:
        return out["status"], json.loads(out["body"] or b"{}")
    except Exception:
        return out["status"], {}


A = f"/v1/projects/{P}/locations/us-central1/applications"
check("bad id", call("POST", A, {"scope": {"type": "REGIONAL"}}, {"applicationId": "Bad"})[0] == 400)
check("scope required", call("POST", A, {}, {"applicationId": "shop"})[0] == 400)
check("global scope in region rejected", call("POST", A, {"scope": {"type": "GLOBAL"}}, {"applicationId": "shop"})[0] == 400)
check("bad criticality", call("POST", A, {"scope": {"type": "REGIONAL"}, "attributes": {"criticality": {"type": "HUGE"}}}, {"applicationId": "shop"})[0] == 400)
check("bad owner email", call("POST", A, {"scope": {"type": "REGIONAL"}, "attributes": {"developerOwners": [{"email": "nope"}]}}, {"applicationId": "shop"})[0] == 400)
st, o = call("POST", A, {"displayName": "Shop", "scope": {"type": "REGIONAL"}, "attributes": {"criticality": {"type": "HIGH"}, "environment": {"type": "PRODUCTION"}}}, {"applicationId": "shop"})
check("create app (LRO done)", st == 200 and o["done"] and o["response"]["name"].endswith("/applications/shop"), o)
check("duplicate", call("POST", A, {"scope": {"type": "REGIONAL"}}, {"applicationId": "shop"})[0] == 409)
check("get", call("GET", A + "/shop")[1]["attributes"]["criticality"]["type"] == "HIGH")
st, o = call("PATCH", A + "/shop", {"displayName": "Shop 2"}, {"updateMask": "displayName"})
check("patch", o["response"]["displayName"] == "Shop 2")
check("scope immutable", call("PATCH", A + "/shop", {"scope": {"type": "GLOBAL"}}, {"updateMask": "scope"})[0] == 400)

# discovery is real: a Cloud Run service shows up as a discovered service
check("nothing discovered yet", call("GET", f"/v1/projects/{P}/locations/us-central1/discoveredServices")[1] == {"discoveredServices": []})
st, o = call("POST", f"/v2/projects/{P}/locations/us-central1/services", {"template": {"containers": [{"image": "gcr.io/x/app:1"}]}}, {"serviceId": "api"})
check("run service created", st == 200, o)
st, d = call("GET", f"/v1/projects/{P}/locations/us-central1/discoveredServices")
check("run service discovered", st == 200 and len(d["discoveredServices"]) == 1 and d["discoveredServices"][0]["serviceReference"]["uri"].endswith("/services/api"), d)
dn = d["discoveredServices"][0]["name"]
check("register unknown discovered service", call("POST", A + "/shop/services", {"discoveredService": dn + "x"}, {"serviceId": "api"})[0] == 404)
st, o = call("POST", A + "/shop/services", {"discoveredService": dn, "attributes": {"environment": {"type": "STAGING"}}}, {"serviceId": "api"})
check("register service", st == 200 and o["response"]["serviceProperties"]["location"] == "us-central1", o)
check("same discovered service twice", call("POST", A + "/shop/services", {"discoveredService": dn}, {"serviceId": "api2"})[0] == 409)
check("list services", len(call("GET", A + "/shop/services")[1]["services"]) == 1)
check("delete app with services blocked", call("DELETE", A + "/shop")[0] == 400)
check("unregister", call("DELETE", A + "/shop/services/api")[0] == 200)
check("delete app", call("DELETE", A + "/shop")[0] == 200 and call("GET", A + "/shop")[0] == 404)

# Memorystore monitoring metrics derive from real instance state
st, o = call("POST", f"/v1/projects/{P}/locations/us-central1/instances", {"tier": "STANDARD_HA", "memorySizeGb": 2, "replicaCount": 1}, {"instanceId": "cache1"})
check("redis instance created", st == 200, o)
st, ts = call("GET", f"/v3/projects/{P}/timeSeries", None, {"filter": 'metric.type="redis.googleapis.com/stats/memory/maxmemory"',
                                                          "interval.endTime": "2099-01-01T00:00:00Z", "interval.startTime": "2000-01-01T00:00:00Z"})
series = ts.get("timeSeries", [])
check("maxmemory per node (2 nodes, 2 GiB)", st == 200 and len(series) == 2 and all(s["points"][0]["value"]["int64Value"] == str(2 * 1024 ** 3) for s in series), ts)
st, ts = call("GET", f"/v3/projects/{P}/timeSeries", None, {"filter": 'metric.type="redis.googleapis.com/replication/role"',
                                                          "interval.endTime": "2099-01-01T00:00:00Z", "interval.startTime": "2000-01-01T00:00:00Z"})
roles = sorted((s["metric"]["labels"]["role"], s["points"][0]["value"]["int64Value"]) for s in ts.get("timeSeries", []))
check("primary=1 replica=0", roles == [("primary", "1"), ("replica", "0")], roles)
st, md = call("GET", f"/v3/projects/{P}/metricDescriptors", None, {"filter": 'metric.type = starts_with("redis.googleapis.com")'})
check("redis metric descriptors listed", st == 200 and len(md.get("metricDescriptors", [])) == 3, md)
st, ts = call("GET", f"/v3/projects/{P}/timeSeries", None, {"filter": 'metric.type="redis.googleapis.com/clients/connected"',
                                                          "interval.endTime": "2099-01-01T00:00:00Z", "interval.startTime": "2000-01-01T00:00:00Z"})
check("no fabricated client/usage series", ts.get("timeSeries", []) == [])
print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
