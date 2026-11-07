"""Queue/Table service properties are ENFORCED by the data plane, exercised with the REAL azure-storage-queue SDK over HTTP:
set/get service properties (logging, metrics, retention, CORS), CORS preflight allow/deny, request logging + metrics recorded,
retention purge, and ARM queueServices CORS shared with the data plane.
Run: PYTHONPATH=. python tests/conformance/test_azure_storage_service_props_sdk.py"""
import json
import time
import urllib.request

from azure.core.credentials import AzureNamedKeyCredential
from azure.storage.queue import QueueServiceClient, CorsRule, Metrics, RetentionPolicy, QueueAnalyticsLogging

from core.azure_arm_core import DEFAULT_SUBSCRIPTION as S
from tests.conformance._az_http_bridge import start


def _check(n, c):
    if not c:
        raise AssertionError(n)
    print("  ok ", n)


def run():
    router, srv, base = start()
    arm = router.az_arm
    RG = f"/subscriptions/{S}/resourceGroups/q-rg"
    arm.handle("PUT", RG, {"api-version": "2021-04-01"}, {"location": "eastus"})
    sa = RG + "/providers/Microsoft.Storage/storageAccounts/qacct"
    arm.handle("PUT", sa, {"api-version": "2023-01-01"}, {"location": "eastus", "kind": "StorageV2", "sku": {"name": "Standard_LRS"}})
    cred = AzureNamedKeyCredential("qacct", "a2V5")
    hdr = {"x-vyomi-service": "queue", "x-vyomi-account": "qacct"}
    from azure.core.pipeline.policies import HeadersPolicy
    qs = QueueServiceClient(account_url=base + "/qacct", credential=cred, headers=hdr, api_version="2021-08-06")
    props = qs.get_service_properties()
    _check("default properties: logging off, cors empty", not props["analytics_logging"].write and props["cors"] == [])
    qs.set_service_properties(
        analytics_logging=QueueAnalyticsLogging(read=True, write=True, delete=False, retention_policy=RetentionPolicy(enabled=True, days=2)),
        hour_metrics=Metrics(enabled=True, include_apis=True, retention_policy=RetentionPolicy(enabled=True, days=3)),
        minute_metrics=Metrics(enabled=True, include_apis=False),
        cors=[CorsRule(allowed_origins=["https://app.example.com"], allowed_methods=["GET", "PUT"], allowed_headers=["x-ms-*"],
                       exposed_headers=["x-ms-request-id"], max_age_in_seconds=120)])
    p = qs.get_service_properties()
    _check("properties round-trip through the SDK", p["analytics_logging"].read and p["analytics_logging"].retention_policy.days == 2
           and p["hour_metrics"].include_apis and p["cors"][0].allowed_origins in ("https://app.example.com", ["https://app.example.com"]) and p["cors"][0].max_age_in_seconds == 120)

    def preflight(origin, method="PUT"):
        req = urllib.request.Request(base + "/qacct/q1/messages", method="OPTIONS",
                                     headers={**hdr, "Origin": origin, "Access-Control-Request-Method": method, "x-ms-version": "2021-08-06"})
        try:
            r = urllib.request.urlopen(req)
            return r.status, dict(r.headers)
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers)
    st, h = preflight("https://app.example.com")
    _check("CORS preflight allowed for matching origin", st == 200 and h["Access-Control-Allow-Origin"] == "https://app.example.com" and h["Access-Control-Max-Age"] == "120")
    st, _ = preflight("https://evil.example.com")
    _check("CORS preflight denied for other origin", st == 403)
    st, _ = preflight("https://app.example.com", "DELETE")
    _check("CORS preflight denied for method not in rule", st == 403)

    qc = qs.get_queue_client("q1"); qc.create_queue(); qc.send_message("hello")
    logs = json.loads(urllib.request.urlopen(urllib.request.Request(base + "/qacct/?restype=service&comp=vyomi-logs", headers={**hdr, "x-ms-version": "2021-08-06"})).read())["value"]
    _check("write requests are logged per the Logging flags", any(e["operation"] == "write" for e in logs) and not any(e["operation"] == "delete" for e in logs))
    mets = json.loads(urllib.request.urlopen(urllib.request.Request(base + "/qacct/?restype=service&comp=vyomi-metrics", headers={**hdr, "x-ms-version": "2021-08-06"})).read())["value"]
    _check("hour + minute metrics counted, API-level only when includeAPIs", any(m["interval"] == "hourMetrics" and m["api"] for m in mets)
           and not any(m["interval"] == "minuteMetrics" and m["api"] for m in mets) and any(m["TotalRequests"] >= 2 for m in mets))
    # retention purge
    from core import azure_storage_svc_core as svc
    pr = svc.props_of(arm.state[sa.lower()], "queue")
    pr["_log"].append({"ts": time.time() - 5 * 86400, "operation": "write", "request": "old", "status": 200})
    svc.purge(pr)
    _check("retention policy purges old log entries", not any(e["request"] == "old" for e in pr["_log"]))
    # ARM <-> data plane CORS share
    r = arm.handle("PUT", sa + "/queueServices/default", {"api-version": "2023-01-01"},
                   {"properties": {"cors": {"corsRules": [{"allowedOrigins": ["https://arm.example.com"], "allowedMethods": ["GET"], "maxAgeInSeconds": 5,
                                                           "exposedHeaders": ["*"], "allowedHeaders": ["*"]}]}}})
    _check("ARM queueServices CORS accepted", r["status"] == 200)
    st, _ = preflight("https://arm.example.com", "GET")
    _check("CORS set via ARM is enforced by the data plane", st == 200)
    # Table service: same enforcement through the real azure-data-tables SDK
    from azure.data.tables import TableServiceClient, TableCorsRule, TableMetrics, TableAnalyticsLogging, TableRetentionPolicy
    ts = TableServiceClient(endpoint=base, credential=cred, headers={"x-vyomi-service": "table", "x-vyomi-account": "qacct"})
    ts.set_service_properties(analytics_logging=TableAnalyticsLogging(read=True, write=True, delete=True, retention_policy=TableRetentionPolicy(enabled=True, days=1)),
                              cors=[TableCorsRule(allowed_origins=["https://t.example.com"], allowed_methods=["GET"], allowed_headers=["*"], exposed_headers=["*"], max_age_in_seconds=30)])
    tp = ts.get_service_properties()
    _check("table service properties round-trip via azure-data-tables", tp["analytics_logging"].delete and tp["cors"][0].max_age_in_seconds == 30)
    ts.create_table("t1")
    tlogs = json.loads(urllib.request.urlopen(urllib.request.Request(base + "/?restype=service&comp=vyomi-logs", headers={"x-vyomi-service": "table", "x-vyomi-account": "qacct", "x-ms-version": "2021-08-06"})).read())["value"]
    _check("table requests logged", any("Tables" in e["request"] for e in tlogs))
    srv.shutdown()
    print("PASS test_azure_storage_service_props_sdk")


if __name__ == "__main__":
    run()
