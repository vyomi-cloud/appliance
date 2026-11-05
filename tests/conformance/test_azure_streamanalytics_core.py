"""Azure Stream Analytics: jobs/inputs/outputs/transformation validation, state machine, Blob->Blob query runner.
Run: PYTHONPATH=. python tests/conformance/test_azure_streamanalytics_core.py"""
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
    V = {"api-version": "2021-10-01-preview"}
    RG = f"/subscriptions/{SUB}/resourceGroups/sa-rg"
    J = f"{RG}/providers/Microsoft.StreamAnalytics/streamingjobs/job1"
    code = lambda r: (r["body"] or {}).get("error", {}).get("code") if isinstance(r["body"], dict) else None
    put = lambda p, b: a.handle("PUT", p, V, b)
    get = lambda p: a.handle("GET", p, V)
    post = lambda p, b=None: a.handle("POST", p, V, b or {})
    a.handle("PUT", RG, {"api-version": "2021-04-01"}, {"location": "eastus"})
    bs.create_container("acct1/in"); bs.create_container("acct1/out")
    rows = [{"device": "a", "temp": 20, "ts": "2024-01-01T00:00:10Z"}, {"device": "a", "temp": 30, "ts": "2024-01-01T00:00:50Z"},
            {"device": "b", "temp": 99, "ts": "2024-01-01T00:01:10Z"}, {"device": "a", "temp": 40, "ts": "2024-01-01T00:01:20Z"}]
    blob(bs, "PUT", "/in/data/1.json", {}, {"x-ms-blob-type": "BlockBlob"}, "\n".join(json.dumps(r) for r in rows).encode(), account="acct1")
    _check("bad compat level", code(put(J, {"location": "eastus", "properties": {"compatibilityLevel": "9"}})) == "InvalidParameter")
    _check("job created", put(J, {"location": "eastus", "sku": {"name": "Standard"}})["status"] == 201)
    _check("start needs inputs/outputs/transformation", code(post(J + "/start")) == "JobIncomplete")
    blob_in = {"properties": {"type": "Stream", "datasource": {"type": "Microsoft.Storage/Blob", "properties": {"storageAccounts": [{"accountName": "acct1"}], "container": "in", "pathPattern": "data/"}},
                              "serialization": {"type": "Json", "properties": {"encoding": "UTF8", "format": "LineSeparated"}}}}
    blob_out = {"properties": {"datasource": {"type": "Microsoft.Storage/Blob", "properties": {"storageAccounts": [{"accountName": "acct1"}], "container": "out"}}, "serialization": {"type": "Json", "properties": {"encoding": "UTF8", "format": "LineSeparated"}}}}
    _check("input: bad serialization rejected", code(put(J + "/inputs/in1", {"properties": {**blob_in["properties"], "serialization": {"type": "Xml"}}})) == "InvalidParameter")
    _check("input: bad datasource rejected", code(put(J + "/inputs/in1", {"properties": {**blob_in["properties"], "datasource": {"type": "Foo"}}})) == "InvalidParameter")
    _check("input created", put(J + "/inputs/in1", blob_in)["status"] == 201)
    _check("output created", put(J + "/outputs/out1", blob_out)["status"] == 201)
    _check("input connectivity test ok", post(J + "/inputs/in1/test")["body"]["status"] == "TestSucceeded")
    _check("query: undefined input rejected", code(put(J + "/transformations/t", {"properties": {"streamingUnits": 3, "query": "SELECT * INTO out1 FROM nope"}})) == "InvalidQuery")
    _check("query: undefined output rejected", code(put(J + "/transformations/t", {"properties": {"streamingUnits": 3, "query": "SELECT * INTO nope FROM in1"}})) == "InvalidQuery")
    _check("query: join unsupported", code(put(J + "/transformations/t", {"properties": {"streamingUnits": 3, "query": "SELECT * INTO out1 FROM in1 JOIN x ON 1=1"}})) == "UnsupportedQuery")
    _check("SU validated", code(put(J + "/transformations/t", {"properties": {"streamingUnits": 5, "query": "SELECT * INTO out1 FROM in1"}})) == "InvalidParameter")
    _check("testquery endpoint", post(J + "/testquery", {"query": "SELECT * INTO nope FROM in1"})["body"]["status"] == "TestFailed")
    q = "SELECT device, COUNT(*) AS n, AVG(temp) AS avgt, System.Timestamp() AS windowEnd INTO out1 FROM in1 TIMESTAMP BY ts WHERE temp < 90 GROUP BY device, TumblingWindow(minute, 1)"
    _check("transformation accepted", put(J + "/transformations/t", {"properties": {"streamingUnits": 3, "query": q}})["status"] == 200)
    _check("stop on a stopped job conflicts", code(post(J + "/stop")) == "JobStateConflict")
    _check("CustomTime needs a time", code(post(J + "/start", {"outputStartMode": "CustomTime"})) == "InvalidParameter")
    r = post(J + "/start", {"outputStartMode": "JobStartTime"})
    _check("start runs", r["status"] == 200 and get(J)["body"]["properties"]["jobState"] == "Running")
    run_ = get(J)["body"]["properties"]["vyomiRun"]
    _check("run summary", run_["inputEvents"] == 4 and run_["outputEvents"] == 2)
    blobs = list(bs.container_blobs("acct1/out"))
    _check("one output blob written", len(blobs) == 1)
    out = [json.loads(l) for l in blob(bs, "GET", "/out/" + blobs[0], {}, {}, b"", account="acct1").body.decode().splitlines()]
    got = sorted((o["device"], o["n"], o["avgt"], o["windowEnd"]) for o in out)
    _check("tumbling-window aggregates are correct", got == [("a", 1, 40.0, "2024-01-01T00:02:00Z"), ("a", 2, 25.0, "2024-01-01T00:01:00Z")])
    _check("start while running conflicts", code(post(J + "/start")) == "JobStateConflict")
    _check("edit while running conflicts", code(put(J + "/outputs/out1", blob_out)) == "JobMustBeStopped")
    _check("delete while running conflicts", a.handle("DELETE", J, V)["status"] == 409)
    _check("stop", post(J + "/stop")["status"] == 200 and get(J)["body"]["properties"]["jobState"] == "Stopped")
    # event hub input => honest failure
    put(J + "/inputs/eh", {"properties": {"type": "Stream", "datasource": {"type": "Microsoft.EventHub/EventHub", "properties": {"serviceBusNamespace": "ns", "eventHubName": "h"}}, "serialization": {"type": "Json", "properties": {"encoding": "UTF8"}}}})
    put(J + "/transformations/t", {"properties": {"streamingUnits": 3, "query": "SELECT * INTO out1 FROM eh"}})
    r = post(J + "/start")
    _check("Event Hub input fails honestly", code(r) == "InputNotSupported" and get(J)["body"]["properties"]["jobState"] == "Failed")
    _check("delete job", a.handle("DELETE", J, V)["status"] == 200 and get(J)["status"] == 404)
    print("PASS")


if __name__ == "__main__":
    run()
