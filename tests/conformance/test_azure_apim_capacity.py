"""APIM `Capacity` as an Azure Monitor metric (Microsoft.Insights metricDefinitions + metrics on a service): an honest derived load
estimate from the REAL gateway request log (core/azure_apim_gateway_core.py), the same model as the Overview analytics gauge.
Run: PYTHONPATH=. python3 tests/conformance/test_azure_apim_capacity.py"""
import time
from datetime import datetime, timedelta, timezone

from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as SUB
from core import azure_apim_gateway_core as gw

BAD = []


def ck(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  {str(detail)[:200]}"))
    if not cond:
        BAD.append(name)


a = AzureArm()
Q = {"api-version": "2022-08-01"}
S = f"/subscriptions/{SUB}/resourceGroups/cap-rg"
put = lambda p, b: a.handle("PUT", S + p, Q, b)
put("", {"location": "eastus"})
base = "/providers/Microsoft.ApiManagement/service"
for n, sku in (("capdev", {"name": "Developer", "capacity": 1}), ("capprem", {"name": "Premium", "capacity": 2}), ("capcons", {"name": "Consumption", "capacity": 0})):
    put(f"{base}/{n}", {"location": "eastus", "sku": sku, "properties": {"publisherEmail": "a@b.c", "publisherName": "p"}})
put(f"{base}/capdev/apis/open", {"properties": {"displayName": "o", "path": "open", "serviceUrl": "http://backend.local", "subscriptionRequired": False}})
put(f"{base}/capdev/apis/open/operations/g", {"properties": {"displayName": "g", "method": "GET", "urlTemplate": "/r/{id}"}})
dev = gw.find_service(a.state, "capdev")
fetch = lambda m, url, h, d: (200, {"content-type": "application/json"}, b"{}")
MD = lambda n: f"/subscriptions/{SUB}/resourceGroups/cap-rg{base}/{n}/providers/microsoft.insights/metricDefinitions"
MT = lambda n: f"/subscriptions/{SUB}/resourceGroups/cap-rg{base}/{n}/providers/microsoft.insights/metrics"
mq = {"api-version": "2018-01-01"}

names = [d["name"]["value"] for d in a.handle("GET", MD("capdev"), mq)["body"]["value"]]
ck("metricDefinitions lists Capacity (native route)", "Capacity" in names, names)
cd = [d for d in a.handle("GET", MD("capdev"), mq)["body"]["value"] if d["name"]["value"] == "Capacity"][0]
ck("Capacity unit is Percent and says estimate, not CPU", cd["unit"] == "Percent" and "not measured" in cd["displayDescription"].lower())
ck("Consumption tier has no Capacity", "Capacity" not in [d["name"]["value"] for d in a.handle("GET", MD("capcons"), mq)["body"]["value"]])
ck("Consumption Capacity query is 400", a.handle("GET", MT("capcons"), dict(mq, metricnames="Capacity"))["status"] == 400)


def cap(n="capdev", start=None, end=None, agg="Maximum"):
    now = datetime.now(timezone.utc)
    start, end = start or now - timedelta(minutes=10), end or now + timedelta(minutes=1)
    ts = start.strftime("%Y-%m-%dT%H:%M:%SZ") + "/" + end.strftime("%Y-%m-%dT%H:%M:%SZ")
    r = a.handle("GET", MT(n), dict(mq, metricnames="Capacity", aggregation=agg, interval="PT1M", timespan=ts))
    assert r["status"] == 200, r
    return r["body"]["value"][0]["timeseries"][0]["data"]


idle = cap()
ck("no traffic -> honest 0 % (every bucket present, all zero)", idle and all(p["maximum"] == 0 for p in idle), idle[:2])
N = 300
for _ in range(N):
    gw.handle(a.state, dev, "GET", "/open/r/1", {}, {}, b"", fetch=fetch)
loaded = cap()
peak = max(p["maximum"] for p in loaded)
nominal = gw.NOMINAL_RPS["developer"]
lo = 100.0 * (N / 60.0) / nominal / 2          # all N in one minute bucket at best, split over two at worst
hi = 100.0 * (N / 60.0) / nominal
ck("Capacity rises above 0 after real gateway traffic", peak > 0, loaded)
ck("Capacity = requests / (60 s x nominal rps)", lo - 0.01 <= peak <= hi + 0.01, (peak, lo, hi))
ck("another service's Capacity is untouched", max(p["maximum"] for p in cap("capprem")) == 0)
now = datetime.now(timezone.utc)
ck("Capacity decays to 0 once the burst is out of the window",
   all(p["maximum"] == 0 for p in cap(start=now + timedelta(minutes=2), end=now + timedelta(minutes=6))))
prem = gw.find_service(a.state, "capprem")
for _ in range(N):
    gw.handle(a.state, prem, "GET", "/nope/x", {}, {}, b"", fetch=fetch)
pp = max(p["maximum"] for p in cap("capprem"))
ck("Premium x2 loads less than Developer for the same count", 0 < pp < peak, (pp, peak))
ck("capped at 100 %", max(p["maximum"] for p in cap()) <= 100.0)
ck("average aggregation also served", "average" in cap(agg="Average")[0])
ck("unknown metric still 400", a.handle("GET", MT("capdev"), dict(mq, metricnames="NoSuch"))["status"] == 400)
print("FAILED:", BAD) if BAD else print("ALL PASS")
raise SystemExit(1 if BAD else 0)
