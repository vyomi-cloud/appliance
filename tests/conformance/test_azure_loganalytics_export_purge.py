"""Log Analytics: data export rules write real blobs, purge really deletes rows, usage reflects real ingestion
volume and the daily cap drops data. Run: PYTHONPATH=. python tests/conformance/test_azure_loganalytics_export_purge.py"""
import json
from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as SUB
from core.azure_blob_core import AzureBlobStore, dispatch as blob
AzureArm.STRICT_SUBSCRIPTION = False


def _check(n, c):
    if not c:
        raise AssertionError(n)
    print("  ok ", n)


def run():
    a = AzureArm()
    a.blob_store = bs = AzureBlobStore()
    RG = f"/subscriptions/{SUB}/resourceGroups/la-rg"
    W = f"{RG}/providers/Microsoft.OperationalInsights/workspaces/law1"
    SA = f"{RG}/providers/Microsoft.Storage/storageAccounts/exportacct"
    V = {"api-version": "2022-10-01"}
    code = lambda r: (r["body"] or {}).get("error", {}).get("code") if isinstance(r["body"], dict) else None
    a.handle("PUT", RG, {"api-version": "2021-04-01"}, {"location": "eastus"})
    _check("workspace created", a.handle("PUT", W, V, {"location": "eastus"})["status"] in (200, 201))
    X = W + "/dataExports/exp-rule"
    body = {"properties": {"tableNames": ["Heartbeat"], "destination": {"resourceId": SA}, "enable": True}}
    _check("export to a missing storage account rejected", code(a.handle("PUT", X, V, body)) == "InvalidDestination")
    a.handle("PUT", SA, {"api-version": "2023-01-01"}, {"location": "eastus", "kind": "StorageV2", "sku": {"name": "Standard_LRS"}})
    _check("unknown table rejected", a.handle("PUT", X, V, {"properties": {**body["properties"], "tableNames": ["Nope"]}})["status"] == 400)
    _check("event hub destination rejected honestly", a.handle("PUT", X, V, {"properties": {**body["properties"], "destination": {"resourceId": RG + "/providers/Microsoft.EventHub/namespaces/eh"}}})["status"] == 400)
    r = a.handle("PUT", X, V, body)
    _check("rule created", r["status"] == 201 and r["body"]["properties"]["dataExportId"])
    _check("overlapping enabled rule conflicts", a.handle("PUT", W + "/dataExports/other-rule", V, body)["status"] == 409)
    _check("rule listed", len(a.handle("GET", W + "/dataExports", V)["body"]["value"]) == 1)

    recs = [{"computer": "vm1", "n": 1}, {"computer": "vm2", "n": 2}, {"computer": "vm1", "n": 3}]
    # Custom table export: create the rule for a table that appears on first ingest via a table PUT.
    T = W + "/tables/Orders_CL"
    a.handle("PUT", T, V, {"properties": {"schema": {"columns": [{"name": "TimeGenerated", "type": "dateTime"}, {"name": "computer_s", "type": "string"}, {"name": "n_d", "type": "real"}]}}})
    a.handle("PUT", W + "/dataExports/orders-rule", V, {"properties": {"tableNames": ["Orders_CL"], "destination": {"resourceId": SA}}})
    ing = a.handle("POST", W + "/api/logs", {"api-version": "2022-10-01", "logType": "Orders"}, recs)
    _check("ingest accepted", ing["status"] == 200)
    cont = [c for c in bs.containers if c.startswith("exportacct/")] if hasattr(bs, "containers") else None
    key = "exportacct/am-orders-cl"
    _check("export container created in the storage account", bs.container_exists(key))
    names = list(bs.container_blobs(key))
    _check("one export blob under WorkspaceResourceId=…/y=/m=/d=/h=/m=/PT05M.json", len(names) == 1 and names[0].startswith("WorkspaceResourceId=") and names[0].endswith("/PT05M.json"))
    lines = blob(bs, "GET", f"/am-orders-cl/{names[0]}", {}, {}, b"", account="exportacct").body.decode().splitlines()
    _check("every ingested row exported as a JSON line", len(lines) == 3 and json.loads(lines[1])["computer_s"] == "vm2" and json.loads(lines[0])["Type"] == "Orders_CL")
    a.handle("POST", W + "/api/logs", {"api-version": "2022-10-01", "logType": "Orders"}, [{"computer": "vm9", "n": 9}])
    lines = blob(bs, "GET", f"/am-orders-cl/{names[0]}", {}, {}, b"", account="exportacct").body.decode().splitlines()
    _check("later ingest appends to the same 5-minute blob", len(lines) == 4)
    # disabled rule stops exporting
    a.handle("PUT", W + "/dataExports/orders-rule", V, {"properties": {"tableNames": ["Orders_CL"], "destination": {"resourceId": SA}, "enable": False}})
    a.handle("POST", W + "/api/logs", {"api-version": "2022-10-01", "logType": "Orders"}, [{"computer": "vm10", "n": 10}])
    lines = blob(bs, "GET", f"/am-orders-cl/{names[0]}", {}, {}, b"", account="exportacct").body.decode().splitlines()
    _check("disabled rule exports nothing", len(lines) == 4)
    _check("delete rule", a.handle("DELETE", W + "/dataExports/orders-rule", V)["status"] == 200)

    q = lambda t: a.handle("POST", W + "/api/query", V, {"query": t})["body"]["tables"][0]["rows"]
    _check("rows queryable before purge", len(q("Orders_CL")) == 5)
    P = W + "/purge"
    _check("purge without filters rejected", a.handle("POST", P, V, {"table": "Orders_CL"})["status"] == 400)
    _check("purge on unknown column rejected", a.handle("POST", P, V, {"table": "Orders_CL", "filters": [{"column": "zzz", "operator": "==", "value": "x"}]})["status"] == 400)
    pr = a.handle("POST", P, V, {"table": "Orders_CL", "filters": [{"column": "computer_s", "operator": "==", "value": "vm1"}]})
    _check("purge accepted with operationId", pr["status"] == 202 and pr["body"]["operationId"].startswith("purge-"))
    _check("purge status completed", a.handle("GET", f"{W}/operations/{pr['body']['operationId']}", V)["body"]["status"] == "completed")
    left = q("Orders_CL | project computer_s")
    _check("purged rows are really gone", sorted(r[0] for r in left) == ["vm10", "vm2", "vm9"])

    u = {m["name"]["value"]: m for m in a.handle("POST" if False else "GET", W + "/usages", V)["body"]["value"]}
    _check("DataAnalyzed reflects real ingested bytes", u["DataAnalyzed"]["currentValue"] > 100)
    # daily cap: tiny cap drops further data silently
    a.handle("PATCH", W, V, {"properties": {"workspaceCapping": {"dailyQuotaGb": 0.023}}})
    from core import azure_operationalinsights_core as _oi
    a.state[W.lower()].setdefault("_ingest", {})[_oi._today()] = 30 * 1024 * 1024   # 30 MB already ingested today (> the 0.023 GB cap)
    before = len(q("Orders_CL"))
    a.handle("POST", W + "/api/logs", {"api-version": "2022-10-01", "logType": "Orders"}, [{"computer": "late", "n": 1}] * 50)
    _check("after the daily cap is hit, ingestion is dropped", len(q("Orders_CL")) == before)
    print("PASS")


if __name__ == "__main__":
    run()
