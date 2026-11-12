"""core/azure_devsimplified_core.py + the new Event Grid / resource group task templates, via AzureArm.
Run: PYTHONPATH=. python tests/conformance/test_azure_devsimplified.py"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from core.azure_arm_core import AzureArm  # noqa: E402

PASS = FAIL = 0
SUB = "00000000-0000-0000-0000-cloudlearn01"
RG = "dsrg"


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' - ' + str(detail)[:300] if detail and not ok else ''}")


arm = AzureArm()
h = lambda m, p, av, b=None: arm.handle(m, f"/subscriptions/{SUB}{p}", {"api-version": av}, b)
h("PUT", f"/resourceGroups/{RG}", "2021-04-01", {"location": "eastus"})
P = f"/resourceGroups/{RG}/providers"
INS = "/providers/Microsoft.Vyomi/defenderInsights"

# Defender insights computed from resources
r = h("GET", f"{INS}/dataSecurity", "2024-01-01")
check("data security empty with no resources", r["status"] == 200 and r["body"]["findings"] == [] and r["body"]["dataSource"] == "Dev Simplified", r)
h("PUT", f"{P}/Microsoft.Storage/storageAccounts/dssa1", "2023-01-01", {"location": "eastus", "kind": "StorageV2", "sku": {"name": "Standard_LRS"},
                                                                         "properties": {"allowBlobPublicAccess": True, "supportsHttpsTrafficOnly": False}})
h("PUT", f"{P}/Microsoft.KeyVault/vaults/dskv1", "2023-07-01", {"location": "eastus", "properties": {"tenantId": "t", "sku": {"family": "A", "name": "standard"}}})
f = h("GET", f"{INS}/dataSecurity", "2024-01-01")["body"]["findings"]
check("storage public blob + http findings computed", any(x["resourceName"] == "dssa1" and "public access" in x["finding"] for x in f)
      and any(x["resourceName"] == "dssa1" and "Secure transfer" in x["finding"] for x in f), f)
check("key vault finding computed", any(x["resourceName"] == "dskv1" for x in f), f)
h("PATCH", f"{P}/Microsoft.Storage/storageAccounts/dssa1", "2023-01-01", {"properties": {"allowBlobPublicAccess": False}})
f2 = h("GET", f"{INS}/dataSecurity", "2024-01-01")["body"]["findings"]
check("findings change when the resource changes", not any(x["resourceName"] == "dssa1" and "public access" in x["finding"] for x in f2), f2)
w = h("GET", f"{INS}/workloadProtections", "2024-01-01")["body"]["plans"]
check("workload protections count resources", next(p for p in w if p["plan"] == "Storage")["resources"] == 1, w)
h("PUT", f"{P}/Microsoft.Network/networkSecurityGroups/nsg1", "2023-09-01", {"location": "eastus", "properties": {"securityRules": [
    {"name": "allow-ssh", "properties": {"priority": 100, "direction": "Inbound", "access": "Allow", "protocol": "Tcp", "sourceAddressPrefix": "*",
                                          "sourcePortRange": "*", "destinationAddressPrefix": "*", "destinationPortRange": "22"}}]}})
n = h("GET", f"{INS}/firewallManager", "2024-01-01")["body"]["networkSecurityGroups"]
check("firewall manager flags open inbound rule", n and n[0]["openInboundRules"] == ["allow-ssh"], n)
check("unknown insight 404", h("GET", f"{INS}/nope", "2024-01-01")["status"] == 404)
check("insight is read-only", h("PUT", f"{INS}/dataSecurity", "2024-01-01", {})["status"] in (400, 405))

# Fabric mirroring record
h("PUT", f"{P}/Microsoft.Sql/servers/dssql", "2023-05-01-preview", {"location": "eastus", "properties": {"administratorLogin": "a", "administratorLoginPassword": "P@ssw0rd123!"}})
h("PUT", f"{P}/Microsoft.Sql/servers/dssql/databases/appdb", "2023-05-01-preview", {"location": "eastus"})
M = f"{P}/Microsoft.Vyomi/fabricMirrors"
body = {"location": "eastus", "properties": {"sqlServerName": "dssql", "databaseName": "appdb", "fabricWorkspace": "analytics-ws", "tables": ["dbo.orders"]}}
check("mirror for a missing database -> 404", h("PUT", f"{M}/m0", "2024-01-01", {"properties": {**body["properties"], "databaseName": "nope"}})["status"] == 404)
check("mirror without workspace -> 400", h("PUT", f"{M}/m0", "2024-01-01", {"properties": {"sqlServerName": "dssql", "databaseName": "appdb"}})["status"] == 400)
r = h("PUT", f"{M}/m1", "2024-01-01", body)
check("mirror config created Running with a default destination container", r["status"] == 201 and r["body"]["properties"]["state"] == "Running"
      and r["body"]["properties"]["destinationContainer"] == "fabric-mirror-m1", r["body"])
check("stop then start", h("POST", f"{M}/m1/stop", "2024-01-01")["body"]["properties"]["state"] == "Stopped" and h("POST", f"{M}/m1/start", "2024-01-01")["body"]["properties"]["state"] == "Running")
check("unknown action 404", h("POST", f"{M}/m1/sync", "2024-01-01")["status"] == 404)
check("mirror listed", len(h("GET", M, "2024-01-01")["body"]["value"]) == 1)
check("mirror deleted", h("DELETE", f"{M}/m1", "2024-01-01")["status"] == 200 and h("GET", f"{M}/m1", "2024-01-01")["status"] == 404)

# Tasks: Event Grid topic + resource group
h("PUT", f"{P}/Microsoft.EventGrid/topics/t1", "2022-06-15", {"location": "eastus"})
q = lambda rt: arm.handle("GET", f"/subscriptions/{SUB}/providers/Microsoft.Logic/vyomiTaskTemplates", {"api-version": "2019-05-01", "resourceType": rt}, None)["body"]["value"]
check("event grid templates listed", {"eventgrid-disable-public-access", "eventgrid-subscriptions-report"} <= {t["id"] for t in q("Microsoft.EventGrid/topics")})
check("resource group templates listed", {"rg-resources-report", "rg-set-tag"} <= {t["id"] for t in q("Microsoft.Resources/resourceGroups")})
tid = f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.EventGrid/topics/t1"
c = h("POST", f"{P}/Microsoft.Logic/vyomiCreateTask", "2019-05-01", {"templateId": "eventgrid-disable-public-access", "resourceId": tid, "name": "eg-off"})
check("event grid task created", c["status"] == 201, c)
rr = h("POST", f"{P}/Microsoft.Logic/workflows/eg-off/triggers/Recurrence/run", "2019-05-01")
check("event grid task run really disables public access", rr["status"] == 200 and rr["body"]["status"] == "Succeeded"
      and h("GET", f"{P}/Microsoft.EventGrid/topics/t1", "2022-06-15")["body"]["properties"]["publicNetworkAccess"] == "Disabled", rr)
rgid = f"/subscriptions/{SUB}/resourceGroups/{RG}"
c = h("POST", f"{P}/Microsoft.Logic/vyomiCreateTask", "2019-05-01", {"templateId": "rg-set-tag", "resourceId": rgid, "name": "rg-tag", "parameters": {"tagName": "reviewed", "tagValue": "yes"}})
check("resource group task created", c["status"] == 201, c)
rr = h("POST", f"{P}/Microsoft.Logic/workflows/rg-tag/triggers/Recurrence/run", "2019-05-01")
check("resource group task run really stamps the tag", rr["body"]["status"] == "Succeeded" and h("GET", f"/resourceGroups/{RG}", "2021-04-01")["body"]["tags"].get("reviewed") == "yes", rr)
c = h("POST", f"{P}/Microsoft.Logic/vyomiCreateTask", "2019-05-01", {"templateId": "rg-resources-report", "resourceId": rgid, "name": "rg-rep"})
rr = h("POST", f"{P}/Microsoft.Logic/workflows/rg-rep/triggers/Recurrence/run", "2019-05-01")
check("resource group report run succeeds", rr["body"]["status"] == "Succeeded", rr)
check("template/type mismatch rejected", h("POST", f"{P}/Microsoft.Logic/vyomiCreateTask", "2019-05-01", {"templateId": "rg-resources-report", "resourceId": tid, "name": "x"})["status"] == 400)

# Real container task execution (needs Docker + a local alpine image; skipped otherwise)
from core import container_runner  # noqa: E402
if container_runner.available() and container_runner.image_present("alpine:latest"):
    mk = lambda name, cmd: h("POST", f"{P}/Microsoft.Logic/vyomiCreateTask", "2019-05-01", {"templateId": "run-container-script", "resourceId": rgid, "name": name, "parameters": {"command": cmd}})
    run_t = lambda name: h("POST", f"{P}/Microsoft.Logic/workflows/{name}/triggers/Recurrence/run", "2019-05-01")
    lastrun = lambda name: h("GET", f"{P}/Microsoft.Logic/workflows/{name}/runs", "2019-05-01")["body"]["value"][0]["properties"]
    check("script task created", mk("sh-ok", 'echo hello-from-$VYOMI_TARGET_NAME; uname -s')["status"] == 201)
    rr = run_t("sh-ok")
    resp = lastrun("sh-ok")["vyomiActions"]["Run_container"]["response"]
    check("real container ran: exit 0 and real logs", rr["body"]["status"] == "Succeeded" and resp["body"]["exitCode"] == 0
          and f"hello-from-{RG}" in resp["body"]["logs"] and "Linux" in resp["body"]["logs"], resp)
    mk("sh-bad", "echo boom; exit 7")
    rr = run_t("sh-bad")
    resp = lastrun("sh-bad")["vyomiActions"]["Run_container"]["response"]
    check("non-zero exit fails the run with the real exit code and logs", rr["body"]["status"] == "Failed" and resp["body"]["exitCode"] == 7 and "boom" in resp["body"]["logs"], resp)
    mk("sh-net", "wget -q -T 3 -O- http://example.com >/dev/null 2>&1; echo net=$?")
    run_t("sh-net")
    check("the container has no network", "net=0" not in lastrun("sh-net")["vyomiActions"]["Run_container"]["response"]["body"]["logs"])
    mk("sh-slow", "sleep 30")
    h("POST", f"{P}/Microsoft.Logic/vyomiCreateTask", "2019-05-01", {"templateId": "run-container-script", "resourceId": rgid, "name": "sh-t", "parameters": {"command": "sleep 30", "timeoutSeconds": "2"}})
    run_t("sh-t")
    check("timeout kills the container", lastrun("sh-t")["vyomiActions"]["Run_container"]["response"]["body"].get("timedOut") is True)
    mk("sh-img", "true")
    h("POST", f"{P}/Microsoft.Logic/vyomiCreateTask", "2019-05-01", {"templateId": "run-container-script", "resourceId": rgid, "name": "sh-i", "parameters": {"command": "true", "image": "no-such/image:1"}})
    run_t("sh-i")
    check("a missing image is refused (no pulls)", lastrun("sh-i")["vyomiActions"]["Run_container"].get("code") == "ImageNotFound", lastrun("sh-i"))
else:
    print("[SKIP] Docker / alpine:latest not available: real container task checks skipped")

# REAL Trivy IaC scan of the exported ARM templates (needs Docker + aquasec/trivy locally; skipped otherwise)
if container_runner.available() and container_runner.image_present("aquasec/trivy:0.57.1"):
    h("PUT", f"{P}/Microsoft.Storage/storageAccounts/dssa1", "2023-01-01", {"location": "eastus", "kind": "StorageV2", "sku": {"name": "Standard_LRS"},
                                                                             "properties": {"supportsHttpsTrafficOnly": False, "minimumTlsVersion": "TLS1_0"}})
    r = h("POST", "/providers/Microsoft.Vyomi/defenderInsights/iacScan", "2024-01-01")
    fs = r["body"].get("findings", [])
    check("Trivy ran on the exported templates and found real misconfigurations", r["status"] == 200 and any(f["ruleId"] == "AVD-AZU-0008" for f in fs)
          and any(f["ruleId"] == "AVD-AZU-0011" for f in fs) and any(f["ruleId"] == "AVD-AZU-0016" for f in fs) and r["body"]["scanned"][0]["resourceGroup"] == RG, r["body"])
    h("PUT", f"{P}/Microsoft.Storage/storageAccounts/dssa1", "2023-01-01", {"location": "eastus", "kind": "StorageV2", "sku": {"name": "Standard_LRS"},
                                                                             "properties": {"supportsHttpsTrafficOnly": True, "minimumTlsVersion": "TLS1_2"}})
    fs2 = h("POST", "/providers/Microsoft.Vyomi/defenderInsights/iacScan", "2024-01-01")["body"]["findings"]
    check("fixing the resource removes its findings on the next scan", not any(f["ruleId"] in ("AVD-AZU-0008", "AVD-AZU-0011") for f in fs2), fs2)
    check("last result is retrievable", len(h("GET", "/providers/Microsoft.Vyomi/defenderInsights/iacScan", "2024-01-01")["body"]["findings"]) == len(fs2))
else:
    print("[SKIP] Docker / aquasec/trivy not available: IaC scan checks skipped")

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
