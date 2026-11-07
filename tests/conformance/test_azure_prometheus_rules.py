"""Prometheus rule groups are REALLY evaluated (core/azure_promql.py + core/azure_alerts_core.py).
Run: PYTHONPATH=. python3 tests/conformance/test_azure_prometheus_rules.py
Proves: samples ingested into a workspace store are queried by a PromQL subset, recording rules write new series that can be
queried, alert rules fire after their `for` duration (through the shared alert pipeline -> webhook POST) and auto-resolve."""
import json, os, sys, threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
import core.azure_arm_core as _a
_a.AzureArm.STRICT_SUBSCRIPTION = False
from core.azure_arm_core import AzureArm
from core import azure_alerts_core as al

PASS = FAIL = 0
SUB = "00000000-0000-0000-0000-cloudlearn01"


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' — ' + str(detail)[:300] if detail and not ok else ''}")


HITS = []


class H(BaseHTTPRequestHandler):
    def do_POST(self):
        HITS.append(json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}"))
        self.send_response(200); self.end_headers()

    def log_message(self, *a):
        pass


srv = HTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
arm = AzureArm()
P = f"/subscriptions/{SUB}"
RG = f"{P}/resourceGroups/rg1"
WS = f"{RG}/providers/Microsoft.Monitor/accounts/m1"


def call(m, path, body=None, q=None, v="2023-03-01"):
    return arm.handle(m, path, dict({"api-version": v}, **(q or {})), body)


call("PUT", RG, {"location": "eastus"}, v="2021-04-01")
ag = call("PUT", f"{RG}/providers/Microsoft.Insights/actionGroups/ops", {"location": "Global", "properties": {
    "groupShortName": "ops", "enabled": True,
    "webhookReceivers": [{"name": "hook", "serviceUri": f"http://127.0.0.1:{srv.server_port}/h", "useCommonAlertSchema": True}]}}, v="2023-01-01")
AG = ag["body"]["id"]
NOW = datetime.now(timezone.utc)
T0 = NOW.timestamp() - 600

# 10 minutes of a counter: 'api' ramps 5 errors/s (300/min), 'web' stays flat -> error rate only on api
samples = []
for i in range(0, 21):
    t = T0 + i * 30
    samples.append({"metric": "http_errors_total", "labels": {"job": "api"}, "value": i * 150, "timestamp": t})
    samples.append({"metric": "http_errors_total", "labels": {"job": "web"}, "value": 7, "timestamp": t})
r = call("POST", f"{P}/providers/Microsoft.AlertsManagement/vyomiProm/ingest", {"scope": WS, "samples": samples}, v="2023-03-01")
check("ingest samples", r["status"] == 200 and r["body"]["ingested"] == 42, r)
q = call("POST", f"{P}/providers/Microsoft.AlertsManagement/vyomiProm/query", {"scope": WS, "query": "sum by (job) (rate(http_errors_total[2m]))", "time": NOW.timestamp()})
res = {x["metric"]["job"]: float(x["value"][1]) for x in q["body"]["result"]} if q["status"] == 200 else {}
check("PromQL rate()/sum by over stored samples (api=5/s, web=0)", abs(res.get("api", -1) - 5) < 0.2 and res.get("web") == 0, q)

body = {"location": "eastus", "properties": {"scopes": [WS], "interval": "PT1M", "rules": [
    {"record": "job:http_errors:rate2m", "expression": "sum by (job) (rate(http_errors_total[2m]))", "labels": {"team": "sre"}},
    {"alert": "HighErrorRate", "expression": "job:http_errors:rate2m > 1", "for": "PT0S", "severity": 1,
     "annotations": {"description": "error rate is high"}, "actions": [{"actionGroupId": AG}]},
    {"alert": "NeverFires", "expression": "rate(http_errors_total{job=\"web\"}[2m]) > 1", "severity": 3, "actions": []}]}}
check("rule group created", call("PUT", f"{RG}/providers/Microsoft.AlertsManagement/prometheusRuleGroups/pg1", body)["status"] == 201)
check("invalid PromQL -> 400", call("PUT", f"{RG}/providers/Microsoft.AlertsManagement/prometheusRuleGroups/pg2",
      {"location": "eastus", "properties": {"scopes": [WS], "rules": [{"record": "x", "expression": "sum by (job (up)"}]}})["status"] == 400)

state = arm.state
ev = al.evaluate(state, SUB, None, force=True, now=NOW)
rec = al.prom_query(state, SUB, WS, 'job:http_errors:rate2m{team="sre"}', NOW.timestamp())
check("recording rule produced a real queryable series", any(x["metric"].get("job") == "api" and float(x["value"][1]) > 4 for x in rec["result"]), rec)
check("alert rule fired once for the offending series only", ev["fired"] == 1, ev)
alerts = call("GET", f"{P}/providers/Microsoft.AlertsManagement/alerts", v="2019-03-01")["body"]["value"]
a = [x for x in alerts if x["properties"]["essentials"]["monitorService"] == "Prometheus"]
check("alert is in the alerts list (Sev1, Fired, labels in context)", len(a) == 1 and a[0]["properties"]["essentials"]["severity"] == "Sev1"
      and a[0]["properties"]["context"]["labels"].get("job") == "api" and a[0]["properties"]["essentials"]["monitorCondition"] == "Fired", a)
check("action group webhook REALLY POSTed", len(HITS) >= 1, HITS)
ev2 = al.evaluate(state, SUB, None, force=True, now=NOW + timedelta(seconds=30))
check("no duplicate alert while still firing", ev2["fired"] == 0, ev2)
# the counter stops growing -> rate falls to 0 -> alert auto-resolves
prev = 20 * 150
al.prom_ingest(state, SUB, WS, [{"metric": "http_errors_total", "labels": {"job": "api"}, "value": prev, "timestamp": NOW.timestamp() + 31 + 30 * k} for k in range(0, 8)])
ev3 = al.evaluate(state, SUB, None, force=True, now=NOW + timedelta(seconds=31 + 30 * 7))
check("alert resolves when the expression stops returning the series", ev3["resolved"] == 1, ev3)
# `for` duration is honoured
body["properties"]["rules"] = [{"alert": "Slow", "expression": "vector(1) > 0", "for": "PT2M", "severity": 4, "actions": []}]
call("PUT", f"{RG}/providers/Microsoft.AlertsManagement/prometheusRuleGroups/pg1", body)
n0 = al.evaluate(state, SUB, None, force=True, now=NOW + timedelta(minutes=10))["fired"]
n1 = al.evaluate(state, SUB, None, force=True, now=NOW + timedelta(minutes=11))["fired"]
n2 = al.evaluate(state, SUB, None, force=True, now=NOW + timedelta(minutes=12, seconds=1))["fired"]
check("alert stays pending until `for` elapsed, then fires", (n0, n1, n2) == (0, 0, 1), (n0, n1, n2))
print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
