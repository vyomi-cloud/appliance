"""App Service operations: WebJobs, Service Connector, quotas, certificates, config-backed panels
(run: PYTHONPATH=. python tests/conformance/test_azure_webapp_ops.py)."""
import os, sys, base64
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from core import azure_webapp_core as w  # noqa: E402

PASS = FAIL = 0
def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' — ' + str(detail)[:300] if not ok else ''}")

st = {}
def call(m, chain, body=None, rg="rg1"):
    return w.dispatch(st, m, "sub1", rg, chain, [], body or {})

call("PUT", ["sites", "app1"], {"location": "eastus", "properties": {}})
S = ["sites", "app1"]
# config-backed panels
r = call("PUT", S + ["config", "web"], {"properties": {"defaultDocuments": ["home.html"], "healthCheckPath": "/health",
        "apiDefinition": {"url": "https://x/swagger.json"}, "virtualApplications": [{"virtualPath": "/", "physicalPath": "site\\wwwroot", "preloadEnabled": True}, {"virtualPath": "/api", "physicalPath": "site\\api"}]}})
g = call("GET", S + ["config", "web"])["body"]["properties"]
check("default docs / health check / api definition / virtual apps persist", g["defaultDocuments"] == ["home.html"] and g["healthCheckPath"] == "/health"
      and g["apiDefinition"]["url"].endswith("swagger.json") and len(g["virtualApplications"]) == 2, g)
# webjobs
r = call("PUT", S + ["triggeredwebjobs", "j1"], {"properties": {"script": "print('hi', 1+2)"}})
check("webjob create 201", r["status"] == 201, r)
call("POST", S + ["triggeredwebjobs", "j1", "run"])
h = call("GET", S + ["triggeredwebjobs", "j1", "history"])["body"]["value"]
check("triggered run really executes the script", h and h[0]["properties"]["status"] == "Success" and h[0]["properties"]["output"] == "hi 3", h)
call("PUT", S + ["triggeredwebjobs", "bad"], {"properties": {"script": "raise ValueError('boom')"}})
call("POST", S + ["triggeredwebjobs", "bad", "run"])
h = call("GET", S + ["triggeredwebjobs", "bad", "history"])["body"]["value"]
check("failing script is recorded Failed", h[0]["properties"]["status"] == "Failed" and "boom" in h[0]["properties"]["error"], h)
call("PUT", S + ["continuouswebjobs", "c1"], {"properties": {"script": "x=1"}})
call("POST", S + ["continuouswebjobs", "c1", "start"])
check("continuous start sets Running", call("GET", S + ["continuouswebjobs", "c1"])["body"]["properties"]["status"] == "Running")
# service connector
st["/subscriptions/sub1/resourcegroups/rg1/providers/microsoft.storage/storageaccounts/stg1"] = {
    "id": "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.Storage/storageAccounts/stg1", "name": "stg1", "_type": "Microsoft.Storage/storageAccounts"}
L = S + ["providers", "Microsoft.ServiceLinker", "linkers", "l1"]
r = call("PUT", L, {"properties": {"targetService": {"type": "AzureResource", "id": "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.Storage/storageAccounts/stg1"}, "authInfo": {"authType": "secret"}}})
a = call("GET", S + ["config", "appsettings"])["body"]["properties"]
check("linker injects connection app settings", r["status"] == 201 and a.get("AZURE_STORAGEBLOB_RESOURCEENDPOINT") == "https://stg1.blob.core.windows.net" and "AZURE_STORAGEBLOB_SECRET" in a, (r, a))
check("linker to a missing target is rejected", call("PUT", S + ["providers", "Microsoft.ServiceLinker", "linkers", "l2"], {"properties": {"targetService": {"id": "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.Storage/storageAccounts/nope"}}})["status"] == 400)
check("validate succeeds", call("POST", L + ["validate"])["body"]["isConnectionAvailable"] is True)
call("DELETE", L)
check("delete linker removes its settings", "AZURE_STORAGEBLOB_RESOURCEENDPOINT" not in call("GET", S + ["config", "appsettings"])["body"]["properties"])
# usages
u = call("GET", S + ["usages"])["body"]["value"]
check("usages report file system storage with the tier limit", u[0]["name"]["value"] == "FileSystemStorage" and u[0]["currentValue"] > 0 and u[0]["limit"] == 10240 * 1048576, u)
# certificates
pfx = base64.b64encode(b"fake-pfx-bytes").decode()
r = call("PUT", ["certificates", "c1"], {"location": "eastus", "properties": {"pfxBlob": pfx, "password": "x", "hostNames": ["a.example.com"]}})
check("certificate upload", r["status"] == 201 and len(r["body"]["properties"]["thumbprint"]) == 40, r)
check("certificate list scoped to rg", len(call("GET", ["certificates"])["body"]["value"]) == 1)
check("certificate without pfx or canonicalName rejected", call("PUT", ["certificates", "c2"], {"properties": {}})["status"] == 400)
r = call("PUT", ["certificates", "m1"], {"location": "eastus", "properties": {"canonicalName": "www.example.com"}})
check("managed certificate", r["status"] == 201 and r["body"]["properties"]["issuer"].startswith("Vyomi"))
call("DELETE", ["certificates", "c1"])
check("delete certificate", call("GET", ["certificates", "c1"])["status"] == 404)
# function bindings + invocations
call("PUT", ["sites", "fn1"], {"location": "eastus", "kind": "functionapp", "properties": {}})
F = ["sites", "fn1", "functions", "f1"]
call("PUT", F, {"properties": {"files": {"__init__.py": "def main(req):\n    return {'ok': 1}"}}})
cfg = {"bindings": [{"type": "httpTrigger", "direction": "in", "name": "req"}, {"type": "queue", "direction": "out", "name": "out1", "queueName": "q"}]}
call("PUT", F, {"properties": {"config": cfg}})
g = call("GET", F)["body"]["properties"]
check("bindings editor persists and keeps the code", len(g["config"]["bindings"]) == 2 and "def main" in str(g.get("files")), g)
call("POST", F + ["invoke"], {"method": "GET"})
log = call("GET", ["sites", "fn1", "invocationlogs"])["body"]["value"]
check("invocation log lists the real run", log and log[0]["function"] == "f1" and log[0]["ok"] and log[0]["durationMs"] >= 0, log)
print(f"\n{PASS} passed, {FAIL} failed"); sys.exit(1 if FAIL else 0)
