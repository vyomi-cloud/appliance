"""Application Insights components (ARM) + telemetry from the OTLP / trace store. Hermetic."""
import json, time
from core import observability_core as O, azure_monitor_core as M

F = []
def ck(n, c):
    print(("PASS " if c else "FAIL ") + n)
    if not c: F.append(n)
state = {}
SUB, RG = "s1", "rg"
r = M.dispatch(state, "PUT", SUB, RG, ["components", "ai1"], None, {"location": "eastus", "kind": "web", "properties": {"Application_Type": "web"}})
ck("component created 201 with ikey/appid/connection string", r["status"] == 201 and r["body"]["properties"]["InstrumentationKey"] and "InstrumentationKey=" in r["body"]["properties"]["ConnectionString"])
ik = r["body"]["properties"]["InstrumentationKey"]
r2 = M.dispatch(state, "PUT", SUB, RG, ["components", "ai1"], None, {"location": "eastus", "properties": {"Application_Type": "other", "RetentionInDays": 120}})
ck("update keeps ikey", r2["body"]["properties"]["InstrumentationKey"] == ik and r2["body"]["properties"]["RetentionInDays"] == 120)
ck("bad retention 400", M.dispatch(state, "PUT", SUB, RG, ["components", "ai2"], None, {"properties": {"RetentionInDays": 5}})["status"] == 400)
ck("bad type 400", M.dispatch(state, "PUT", SUB, RG, ["components", "ai3"], None, {"properties": {"Application_Type": "mobile"}})["status"] == 400)
ck("list", len(M.dispatch(state, "GET", SUB, RG, ["components"], None)["body"]["value"]) == 1)

obs = O.ObsStore()
now = time.time()
def span(kind, name, svc, fail=False, events=None, attrs=None):
    t = int(now * 1e9)
    return {"traceId": "ab" * 16, "spanId": "cd" * 8, "name": name, "kind": kind, "startTimeUnixNano": t - 5_000_000, "endTimeUnixNano": t,
            "attributes": attrs or {}, "status": {"code": 2 if fail else 0}, "service": svc, "events": events or []}
O._add_span(obs, span(2, "GET /", "shop"))
O._add_span(obs, span(2, "POST /pay", "shop", fail=True, events=[{"name": "exception", "timeUnixNano": str(int(now * 1e9)), "attributes": []}, {"name": "cart.checkout", "timeUnixNano": str(int(now * 1e9)), "attributes": []}]))
O._add_span(obs, span(3, "SELECT", "shop"))
O._add_span(obs, span(2, "other", "unrelated"))
O._add_span(obs, span(2, "by key", "x", attrs={"ai.instrumentationKey": ik}))
q = O.appinsights_query(obs, ["ai1", "shop"], ik)
s = q["summary"]
ck("requests (server spans incl. ikey match)", s["requests"] == 3 and s["failedRequests"] == 1)
ck("dependency", s["dependencies"] == 1)
ck("exceptions = error span + exception event", s["exceptions"] == 2)
ck("custom event separated", s["events"] == 1 and q["events"][0]["name"] == "cart.checkout")
ck("unrelated service excluded", all(r["name"] != "other" for r in q["requests"]))
ck("idle component empty", O.appinsights_query(obs, ["nothing"], "")["summary"]["requests"] == 0)
d = O.dispatch(obs, "GET", "/_obs/appinsights/query", {"names": "shop"})
ck("dispatch route", d.status == 200 and json.loads(d.body)["summary"]["requests"] == 2)
O.ingest_logs(obs, {"resourceLogs": [{"resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "shop"}}]}, "scopeLogs": [{"logRecords": [{"severityText": "INFO", "body": {"stringValue": "hello"}}]}]}]})
ck("log -> trace", O.appinsights_query(obs, ["shop"])["summary"]["traces"] == 1)
print("FAILED:", F) if F else print("ALL PASS")
raise SystemExit(1 if F else 0)
