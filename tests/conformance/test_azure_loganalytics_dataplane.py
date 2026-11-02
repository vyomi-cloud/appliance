"""Log Analytics ingest + KQL subset, through the ARM entrypoint Nano uses too
(run: python3 tests/conformance/test_azure_loganalytics_dataplane.py)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from core.azure_arm_core import AzureArm  # noqa: E402

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' — ' + str(detail) if detail and not ok else ''}")


arm = AzureArm()
W = "/subscriptions/00000000-0000-0000-0000-cloudlearn01/resourceGroups/rg1/providers/Microsoft.OperationalInsights/workspaces/law-dp"
V = {"api-version": "2022-10-01"}
arm.handle("PUT", "/subscriptions/00000000-0000-0000-0000-cloudlearn01/resourcegroups/rg1", {"api-version": "2021-04-01"}, {"location": "eastus"})
arm.handle("PUT", W, V, {"location": "eastus", "properties": {}})


def q(kql):
    return arm.handle("POST", W + "/api/query", {"api-version": "2017-01-01-preview"}, {"query": kql})


r = q("MyApp_CL | take 1")
check("query before any ingest: unknown table -> 400 SemanticError", r["status"] == 400 and r["body"]["error"]["code"] == "SemanticError", r)
rows = [{"level": "error", "msg": "disk full", "latency": 120, "ok": False},
        {"level": "info", "msg": "started", "latency": 15, "ok": True},
        {"level": "error", "msg": "timeout talking to db", "latency": 900, "ok": False},
        {"level": "warn", "msg": "slow", "latency": 300, "ok": True}]
r = arm.handle("POST", W + "/api/logs", {"api-version": "2016-04-01", "logType": "MyApp"}, rows)
check("Data Collector accepts a JSON array (200)", r["status"] == 200, r)
r = q("MyApp_CL")
t = r["body"]["tables"][0]
cols = [c["name"] for c in t["columns"]]
check("shape: tables[0].name PrimaryResult + typed columns, suffixed fields",
      t["name"] == "PrimaryResult" and "TimeGenerated" in cols and "level_s" in cols and "latency_d" in cols and "ok_b" in cols and len(t["rows"]) == 4, cols)
check("where ==", len(q("MyApp_CL | where level_s == 'error'")["body"]["tables"][0]["rows"]) == 2)
check("where numeric >", len(q("MyApp_CL | where latency_d > 200")["body"]["tables"][0]["rows"]) == 2)
check("where contains + and", len(q("MyApp_CL | where msg_s contains 'DB' and level_s == 'error'")["body"]["tables"][0]["rows"]) == 1)
check("where or / in", len(q("MyApp_CL | where level_s in ('warn','info') or latency_d > 800")["body"]["tables"][0]["rows"]) == 3)
check("project", [c["name"] for c in q("MyApp_CL | project level_s, latency_d")["body"]["tables"][0]["columns"]] == ["level_s", "latency_d"])
check("take / limit", len(q("MyApp_CL | take 2")["body"]["tables"][0]["rows"]) == 2 and len(q("MyApp_CL | limit 3")["body"]["tables"][0]["rows"]) == 3)
check("count", q("MyApp_CL | where level_s == 'error' | count")["body"]["tables"][0]["rows"] == [[2]])
o = q("MyApp_CL | order by latency_d desc | project latency_d | take 2")["body"]["tables"][0]["rows"]
check("order by desc", o == [[900], [300]], o)
check("summarize count() by", sorted(q("MyApp_CL | summarize count() by level_s")["body"]["tables"][0]["rows"]) == [["error", 2], ["info", 1], ["warn", 1]])
check("unknown column -> 400", q("MyApp_CL | where nope == 1")["status"] == 400)
check("unsupported operator is a clear 400, not a fake result", q("MyApp_CL | join kind=inner (X) on a")["status"] == 400)
check("GET ?query= form works", arm.handle("GET", W + "/api/query", {"api-version": "2017-01-01-preview", "query": "MyApp_CL | count"})["body"]["tables"][0]["rows"] == [[4]])
r = arm.handle("POST", W + "/dataCollectionRules/dcr-1/streams/Custom-Orders_CL", {"api-version": "2023-01-01"}, [{"TimeGenerated": "2026-11-02T00:00:00Z", "Id": 7}])
check("Logs Ingestion API -> 204", r["status"] == 204, r)
check("DCR rows queryable by exact column", q("Orders_CL | where Id == 7")["body"]["tables"][0]["rows"][0][1] == 7)
check("custom table shows up in the tables list", any(t["name"] == "MyApp_CL" for t in arm.handle("GET", W + "/tables", V)["body"]["value"]))
check("built-in table queries cleanly (empty)", q("Heartbeat | count")["body"]["tables"][0]["rows"] == [[0]])
print(f"{PASS} passed, {FAIL} failed")



# RunKql (core run_kql): the engine entry the /api/query route calls, exercised directly.
from core import azure_operationalinsights_core as _oi  # noqa: E402
_ws = next(r for k, r in arm.state.items() if k.lower().endswith("/workspaces/law-dp"))
_t = q("MyApp_CL | count")["body"]["tables"][0]
try:
    _r = _oi.run_kql(_ws, "MyApp_CL | count")
    _rows = (_r.get("tables") or [{}])[0].get("rows")
    check("RunKql returns the same table as the /api/query route", _rows == _t["rows"], _r)
except Exception as e:  # noqa: BLE001
    check("RunKql returns the same table as the /api/query route", False, e)
try:
    _oi.run_kql(_ws, "NoSuchTable_CL | count"); check("RunKql unknown table -> SemanticError", False)
except _oi.KqlError as e:
    check("RunKql unknown table -> SemanticError", e.semantic, e)

def test_all_checks_pass():
    assert FAIL == 0


if __name__ == "__main__":
    sys.exit(1 if FAIL else 0)
