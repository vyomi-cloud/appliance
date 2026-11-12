"""Tasks blades: Logic-App-backed task engine (templates, create, validation, run, schedule tick). Hermetic.
Run: PYTHONPATH=. python tests/conformance/test_azure_tasks_core.py"""
from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as SUB
from core import azure_tasks_core as tasks, schedule_core as sched

AzureArm.STRICT_SUBSCRIPTION = False


def _check(n, c):
    if not c:
        raise AssertionError(n)
    print("  ok ", n)


class R:   # the slice of the router tick() needs
    def __init__(self, arm):
        self.az_arm = arm
        self.s3 = type("S", (), {"account": {}})()


def run():
    a = AzureArm()
    S = f"/subscriptions/{SUB}/resourceGroups/tk-rg"
    P = f"/subscriptions/{SUB}/resourceGroups/tk-rg/providers"
    h = lambda m, p, b=None, q=None: a.handle(m, p, q or {"api-version": "2019-05-01"}, b)
    h("PUT", S, {"location": "eastus"})
    h("PUT", P + "/Microsoft.ContainerService/managedClusters/k1", {"location": "eastus", "properties": {"kubernetesVersion": "1.29.0", "dnsPrefix": "k", "agentPoolProfiles": [{"name": "np", "count": 2, "vmSize": "Standard_D2s_v3"}]}})
    h("PUT", P + "/Microsoft.Web/serverfarms/p1", {"location": "eastus", "sku": {"name": "B1"}})
    h("PUT", P + "/Microsoft.Web/sites/w1", {"location": "eastus", "properties": {"serverFarmId": P + "/Microsoft.Web/serverfarms/p1"}})
    h("PUT", P + "/Microsoft.CognitiveServices/accounts/cs1", {"location": "eastus", "kind": "OpenAI", "sku": {"name": "S0"}, "properties": {}})
    h("PUT", P + "/Microsoft.AppConfiguration/configurationStores/appcfg-store1", {"location": "eastus", "sku": {"name": "standard"}})
    h("PUT", P + "/Microsoft.ApiManagement/service/gwsvc", {"location": "eastus", "sku": {"name": "Developer", "capacity": 1}, "properties": {"publisherEmail": "a@b.c", "publisherName": "x"}})
    # templates per resource type
    r = h("GET", f"/subscriptions/{SUB}/providers/Microsoft.Logic/vyomiTaskTemplates", q={"resourceType": "Microsoft.Web/sites"})
    ids = [t["id"] for t in r["body"]["value"]]
    _check("templates filtered by resource type", ids == ["webapp-restart", "webapp-stop", "webapp-start"])
    for rt in ("Microsoft.ContainerService/managedClusters", "Microsoft.ApiManagement/service", "Microsoft.AppConfiguration/configurationStores", "Microsoft.CognitiveServices/accounts"):
        _check(f"templates exist for {rt}", len(h("GET", f"/subscriptions/{SUB}/providers/Microsoft.Logic/vyomiTaskTemplates", q={"resourceType": rt})["body"]["value"]) >= 1)
    mk = lambda body: h("POST", P + "/Microsoft.Logic/vyomiCreateTask", body)
    k1 = P + "/Microsoft.ContainerService/managedClusters/k1"
    _check("unknown template rejected", mk({"templateId": "nope", "resourceId": k1})["status"] == 400)
    _check("missing target rejected", mk({"templateId": "aks-stop-cluster", "resourceId": k1 + "x"})["status"] == 404)
    _check("template/resource type mismatch rejected", mk({"templateId": "webapp-restart", "resourceId": k1})["status"] == 400)
    _check("bad recurrence rejected", mk({"templateId": "aks-stop-cluster", "resourceId": k1, "recurrence": {"frequency": "Month", "interval": 1}})["status"] == 400)
    _check("required parameter enforced", mk({"templateId": "appconfig-rotate-key", "resourceId": P + "/Microsoft.AppConfiguration/configurationStores/appcfg-store1"})["status"] == 400)
    c = mk({"templateId": "aks-stop-cluster", "resourceId": k1, "name": "stop-k1"})
    _check("create task -> Microsoft.Logic/workflows record", c["status"] == 201 and c["body"]["type"] == "Microsoft.Logic/workflows"
           and c["body"]["properties"]["definition"]["actions"]["Stop_cluster"]["inputs"]["uri"].endswith("/stop?api-version=2024-02-01"))
    _check("duplicate task name -> 409", mk({"templateId": "aks-stop-cluster", "resourceId": k1, "name": "stop-k1"})["status"] == 409)
    g = h("GET", P + "/Microsoft.Logic/workflows/stop-k1")
    _check("GET workflow", g["status"] == 200 and g["body"]["tags"]["vyomi-task-target"] == k1)
    _check("list workflows in rg", len(h("GET", P + "/Microsoft.Logic/workflows")["body"]["value"]) == 1)
    # manual run really stops the cluster
    rr = h("POST", P + "/Microsoft.Logic/workflows/stop-k1/triggers/Recurrence/run")
    _check("run now succeeds", rr["status"] == 200 and rr["body"]["status"] == "Succeeded")
    cl = h("GET", k1)["body"]
    _check("the cluster really stopped", cl["properties"]["powerState"]["code"] == "Stopped")
    runs = h("GET", P + "/Microsoft.Logic/workflows/stop-k1/runs")["body"]["value"]
    _check("run record with per-action result", runs[0]["properties"]["status"] == "Succeeded" and runs[0]["properties"]["vyomiActions"]["Stop_cluster"]["response"]["statusCode"] == 200)
    # failing action fails the run (stop a cluster that is gone)
    bad = mk({"templateId": "webapp-restart", "resourceId": P + "/Microsoft.Web/sites/w1", "name": "wr"})
    _check("webapp task created", bad["status"] == 201)
    h("DELETE", P + "/Microsoft.Web/sites/w1")
    rr = h("POST", P + "/Microsoft.Logic/workflows/wr/triggers/Recurrence/run")
    _check("action failing against a deleted target fails the run", rr["body"]["status"] == "Failed")
    fr = h("GET", P + "/Microsoft.Logic/workflows/wr/runs")["body"]["value"][0]
    _check("failed run carries the error", fr["properties"]["error"]["code"] and fr["properties"]["status"] == "Failed")
    # key rotation really changes keys
    cs = P + "/Microsoft.CognitiveServices/accounts/cs1"
    before = h("POST", cs + "/listKeys")["body"]
    mk({"templateId": "cogsvc-rotate-key", "resourceId": cs, "name": "rot", "parameters": {"keyName": "Key1"}})
    h("POST", P + "/Microsoft.Logic/workflows/rot/triggers/Recurrence/run")
    after = h("POST", cs + "/listKeys")["body"]
    _check("rotation task regenerated Key1 only", after["key1"] != before["key1"] and after["key2"] == before["key2"])
    # APIM usage report lands in the run output
    ap = P + "/Microsoft.ApiManagement/service/gwsvc"
    mk({"templateId": "apim-gateway-usage-report", "resourceId": ap, "name": "rep"})
    h("POST", P + "/Microsoft.Logic/workflows/rep/triggers/Recurrence/run")
    out = h("GET", P + "/Microsoft.Logic/workflows/rep/runs")["body"]["value"][0]["properties"]["vyomiActions"]["Get_gateway_usage"]
    _check("usage report captured in run output", out["response"]["body"]["capacity"]["units"] == 1)
    # enable/disable + scheduled firing through schedule_core
    h("POST", P + "/Microsoft.Logic/workflows/stop-k1/disable")
    _check("disabled workflow refuses trigger run", h("POST", P + "/Microsoft.Logic/workflows/stop-k1/triggers/Recurrence/run")["status"] == 400)
    h("POST", P + "/Microsoft.Logic/workflows/stop-k1/enable")
    h("POST", k1 + "/start")
    router = R(a)
    t0 = 1_700_000_000.0
    sched.tick(router, t0)                     # first sighting = baseline, nothing runs
    n0 = len(h("GET", P + "/Microsoft.Logic/workflows/stop-k1/runs")["body"]["value"])
    sched.tick(router, t0 + 86400 * 2)         # two days later the daily trigger is due
    n1 = len(h("GET", P + "/Microsoft.Logic/workflows/stop-k1/runs")["body"]["value"])
    _check("scheduler fires the recurrence (and only once for missed fires)", n1 == n0 + 1)
    _check("the scheduled run really stopped the cluster again", h("GET", k1)["body"]["properties"]["powerState"]["code"] == "Stopped")
    # raw PUT of a non-recurrence trigger is refused; unsupported action type fails honestly
    _check("non-Recurrence trigger refused", h("PUT", P + "/Microsoft.Logic/workflows/x1", {"location": "eastus", "properties": {"definition": {"triggers": {"manual": {"type": "Request"}}, "actions": {}}}})["status"] == 400)
    h("PUT", P + "/Microsoft.Logic/workflows/x2", {"location": "eastus", "properties": {"definition": {"triggers": {"Recurrence": {"type": "Recurrence", "recurrence": {"frequency": "Hour", "interval": 1}}}, "actions": {"Mail": {"type": "ApiConnection", "inputs": {}}}}}})
    h("POST", P + "/Microsoft.Logic/workflows/x2/triggers/Recurrence/run")
    xr = h("GET", P + "/Microsoft.Logic/workflows/x2/runs")["body"]["value"][0]
    _check("unsupported action type fails with ActionNotSupported", xr["properties"]["error"]["code"] == "ActionNotSupported")
    _check("delete task", h("DELETE", P + "/Microsoft.Logic/workflows/x2")["status"] == 200 and h("GET", P + "/Microsoft.Logic/workflows/x2")["status"] == 404)
    print("ALL OK")


if __name__ == "__main__":
    run()
