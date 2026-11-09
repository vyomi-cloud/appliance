"""APIM `Capacity` metric: an honest derived load estimate from REAL gateway request counters.
Everything goes through the native routes: ARM PUTs, the /azure-data/apim gateway, and
Microsoft.ApiManagement/service/<n>/providers/microsoft.insights/{metricDefinitions,metrics}.
Run: PYTHONPATH=. python3 tests/conformance/test_azure_apim_capacity.py"""
import json
import time
from datetime import datetime, timedelta, timezone

from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION
from core.aws_wire_router import AwsWireRouter
from core import observability_core as O

FAILS = []


def ck(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  {detail}"))
    if not cond:
        FAILS.append(name)


SUB, RG = DEFAULT_SUBSCRIPTION, "cap-rg"
arm = AzureArm()
router = AwsWireRouter(stores={"az_arm": arm})
def R(m, p, q=None, h=None, b=b""):
    if p.startswith("/subscriptions/"):   # ARM is not in AwsWireRouter: dev_server / Nano send it to the shared AzureArm core
        return {"status": (r := arm.handle(m, p, q or {}, json.loads(b) if b else None))["status"], "body": json.dumps(r["body"]).encode() if r.get("body") is not None else b""}
    return router.handle(m, p, q or {}, h or {}, b)


J = lambda r: json.loads(r["body"] or b"{}")
base = f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.ApiManagement/service"


def put(path, body, av="2023-05-01-preview"):
    return R("PUT", path, {"api-version": av}, {"content-type": "application/json"}, json.dumps(body).encode())


R("PUT", f"/subscriptions/{SUB}/resourcegroups/{RG}", {"api-version": "2021-04-01"}, {}, json.dumps({"location": "eastus"}).encode())
put(f"{base}/capdev", {"location": "eastus", "sku": {"name": "Developer", "capacity": 1}, "properties": {"publisherEmail": "a@b.c", "publisherName": "p"}})
put(f"{base}/capprem", {"location": "eastus", "sku": {"name": "Premium", "capacity": 2}, "properties": {"publisherEmail": "a@b.c", "publisherName": "p"}})
put(f"{base}/capcons", {"location": "eastus", "sku": {"name": "Consumption", "capacity": 0}, "properties": {"publisherEmail": "a@b.c", "publisherName": "p"}})
put(f"{base}/capdev/apis/echo", {"properties": {"displayName": "echo", "path": "echo", "protocols": ["https"], "mockResponse": {"hello": "world"}}})
sub = put(f"{base}/capdev/subscriptions/s1", {"properties": {"displayName": "s1", "scope": f"{base}/capdev/apis", "primaryKey": "pk-cap-1", "secondaryKey": "sk-cap-1"}})
key = (J(R("GET", f"{base}/capdev/subscriptions/s1", {"api-version": "2023-05-01-preview"})).get("properties") or {}).get("primaryKey") or ""
ck("subscription has a key", bool(key), J(sub))

MD = f"{base}/capdev/providers/microsoft.insights/metricDefinitions"
MT = f"{base}/capdev/providers/microsoft.insights/metrics"
names = [d["name"]["value"] for d in J(R("GET", MD, {"api-version": "2018-01-01"}))["value"]]
ck("metricDefinitions lists Capacity (native route)", "Capacity" in names, names)
cd = [d for d in J(R("GET", MD, {"api-version": "2018-01-01"}))["value"] if d["name"]["value"] == "Capacity"][0]
ck("Capacity unit is Percent and says estimate not CPU", cd["unit"] == "Percent" and "not measured" in cd["displayDescription"].lower())
ck("Consumption tier has no Capacity",
   "Capacity" not in [d["name"]["value"] for d in J(R("GET", f"{base}/capcons/providers/microsoft.insights/metricDefinitions", {"api-version": "2018-01-01"}))["value"]])
ck("Consumption Capacity query is 400",
   R("GET", f"{base}/capcons/providers/microsoft.insights/metrics", {"api-version": "2018-01-01", "metricnames": "Capacity"})["status"] == 400)


def cap(path=MT, start=None, end=None, agg="Maximum", interval="PT1M"):
    now = datetime.now(timezone.utc)
    start, end = start or now - timedelta(minutes=10), end or now + timedelta(minutes=1)
    ts = start.strftime("%Y-%m-%dT%H:%M:%SZ") + "/" + end.strftime("%Y-%m-%dT%H:%M:%SZ")
    r = R("GET", path, {"api-version": "2018-01-01", "metricnames": "Capacity", "aggregation": agg, "interval": interval, "timespan": ts})
    assert r["status"] == 200, r
    return J(r)["value"][0]["timeseries"][0]["data"]


idle = cap()
ck("no traffic -> honest 0 % (every bucket present, all zero)", idle and all(p["maximum"] == 0 for p in idle), idle[:2])

GW = "/azure-data/apim/capdev/echo/ping"
ck("gateway: missing key is 401", R("GET", GW)["status"] == 401)
ck("gateway: bad key is 401", R("GET", GW, {}, {"ocp-apim-subscription-key": "nope"})["status"] == 401)
N = 120
ok = sum(R("GET", GW, {}, {"ocp-apim-subscription-key": key})["status"] == 200 for _ in range(N))
ck(f"gateway served {N} authorised requests", ok == N, ok)
loaded = cap()
peak = max(p["maximum"] for p in loaded)
# 120 + 2 rejected requests in <=2 one-minute buckets against Developer x1 = 10 req/s nominal
exp_min = 100.0 * (N / 60.0) / 10.0 / 2
ck("Capacity rises above 0 after traffic", peak > 0, loaded)
ck("Capacity matches requests / (60 s x nominal rps)", exp_min <= peak <= 100.0 * ((N + 2) / 60.0) / 10.0 + 0.01, (peak, exp_min))
ck("control-plane ARM calls do not count as gateway load",
   max(p["maximum"] for p in cap(f"{base}/capprem/providers/microsoft.insights/metrics")) == 0)
# decay: a window that starts after the burst reads 0 again
now = datetime.now(timezone.utc)
ck("Capacity decays to 0 once the burst is out of the window",
   all(p["maximum"] == 0 for p in cap(start=now + timedelta(minutes=2), end=now + timedelta(minutes=6))))
# SKU / unit scaling: same count of requests loads Premium x2 (200 req/s) far less
t = time.time()
for i in range(120):
    O.record(router.obs, "azure", "az-apim", "capprem", "Gateway:GET", 200, 1.0, ts=t - 5)
    O.record(router.obs, "azure", "az-apim", "capdev", "Gateway:GET", 200, 1.0, ts=t - 5)
pp = max(p["maximum"] for p in cap(f"{base}/capprem/providers/microsoft.insights/metrics"))
ck("Premium x2 (nominal 200 req/s) loads far less than Developer for the same count", 0 < pp < peak, (pp, peak))
ck("cap at 100 %", max(p["maximum"] for p in cap()) <= 100.0)
ck("average aggregation also served", cap(agg="Average") and "average" in cap(agg="Average")[0])
bad = R("GET", f"{base}/capdev/providers/microsoft.insights/metrics", {"api-version": "2018-01-01", "metricnames": "NoSuch"})
ck("unknown metric still 400", bad["status"] == 400)
ck("unknown service gateway is 404", R("GET", "/azure-data/apim/ghost/x", {}, {"ocp-apim-subscription-key": key})["status"] == 404)
print("FAILED:", FAILS) if FAILS else print("ALL PASS")
raise SystemExit(1 if FAILS else 0)
