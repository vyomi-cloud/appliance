#!/usr/bin/env python3
"""Post-create probe (offline): a Log Analytics workspace must accept data and answer KQL.
  python3 azure_loganalytics.py http://localhost:9000
Create workspace -> HTTP Data Collector ingest -> query via the ARM-proxied path AND the SDK-style
/azure-data/loganalytics/v1/workspaces/{customerId}/query path -> Logs Ingestion API (204) -> delete."""
import json, os, sys, urllib.error, urllib.request

BASE = (sys.argv[-1] if sys.argv[-1].startswith("http") else os.environ.get("VYOMI_ENDPOINT", "http://localhost:9000")).rstrip("/")
SUB, RG, WS = "00000000-0000-0000-0000-cloudlearn01", "probe-la-rg", "probe-la-ws"
fails = 0


def check(ok, name, why=""):
    global fails
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + ("" if ok else f" :: {why}"), flush=True)
    fails += 0 if ok else 1


def call(method, path, body=None, headers=None):
    req = urllib.request.Request(BASE + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"content-type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            d = r.read()
            return r.status, (json.loads(d) if d else {})
    except urllib.error.HTTPError as e:
        d = e.read()
        return e.code, (json.loads(d) if d else {})


call("PUT", f"/subscriptions/{SUB}/resourcegroups/{RG}?api-version=2021-04-01", {"location": "eastus"})
W = f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.OperationalInsights/workspaces/{WS}"
try:
    _, ws = call("PUT", W + "?api-version=2022-10-01", {"location": "eastus", "properties": {}})
    cid = ws["properties"]["customerId"]
    s, _ = call("POST", W + "/api/logs?api-version=2016-04-01", [{"level": "error", "n": 3}, {"level": "info", "n": 1}], {"Log-Type": "Probe"})
    check(s == 200, "Data Collector ingest (Log-Type header) -> 200", s)
    s, r = call("POST", W + "/api/query?api-version=2017-01-01-preview", {"query": "Probe_CL | where level_s == 'error' | project level_s, n_d"})
    check(s == 200 and r["tables"][0]["rows"] == [["error", 3]], "ARM-proxied query returns the matching row", r)
    s, r = call("POST", f"/azure-data/loganalytics/v1/workspaces/{cid}/query", {"query": "Probe_CL | count"})
    check(s == 200 and r["tables"][0]["rows"] == [[2]], "SDK-style /v1/workspaces/{id}/query works from this machine", (s, r))
    s, _ = call("POST", f"/azure-data/loganalytics/{WS}/dataCollectionRules/dcr-x/streams/Custom-Orders_CL?api-version=2023-01-01", [{"Id": 1}])
    check(s == 204, "Logs Ingestion API -> 204", s)
    s, r = call("POST", f"/azure-data/loganalytics/v1/workspaces/{WS}/query", {"query": "Orders_CL | count"})
    check(r.get("tables", [{}])[0].get("rows") == [[1]], "ingested DCR row is queryable", r)
    s, r = call("POST", f"/azure-data/loganalytics/v1/workspaces/{cid}/query", {"query": "Nope | take 1"})
    check(s == 400, "unknown table -> 400 (no fake result)", s)
finally:
    call("DELETE", W + "?api-version=2022-10-01")
    call("DELETE", f"/subscriptions/{SUB}/resourcegroups/{RG}?api-version=2021-04-01")
sys.exit(1 if fails else 0)
