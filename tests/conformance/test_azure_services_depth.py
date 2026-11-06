"""Azure v4 depth batch: Diagnose detectors for SQL/Cosmos/Key Vault/Storage/Service Bus/ACR, scheduled Tasks for
VM/Storage/Cosmos/Key Vault/Service Bus/SQL, and Key Vault soft-delete (Manage deleted keys / secrets). Hermetic.
Run: PYTHONPATH=. python tests/conformance/test_azure_services_depth.py"""
import json

from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as SUB
from core.aws_wire_router import AwsWireRouter

AzureArm.STRICT_SUBSCRIPTION = False


def _check(n, c):
    if not c:
        raise AssertionError(n)
    print("  ok ", n)


def run():
    a = AzureArm()
    RG = f"/subscriptions/{SUB}/resourceGroups/dp-rg"
    P = RG + "/providers"
    h = lambda m, p, b=None, v="2023-05-01-preview": a.handle(m, p, {"api-version": v}, b)
    h("PUT", RG, {"location": "eastus"}, "2021-04-01")
    res = {
        "sql": ("/Microsoft.Sql/servers/s1", {"location": "eastus", "properties": {"administratorLogin": "a", "administratorLoginPassword": "Passw0rd!x1"}}, "2023-05-01-preview"),
        "sqldb": ("/Microsoft.Sql/servers/s1/databases/d1", {"location": "eastus", "sku": {"name": "GP_Gen5_2"}}, "2023-05-01-preview"),
        "kv": ("/Microsoft.KeyVault/vaults/kv1", {"location": "eastus", "properties": {"tenantId": "t", "sku": {"family": "A", "name": "standard"}}}, "2023-07-01"),
        "st": ("/Microsoft.Storage/storageAccounts/sa1", {"location": "eastus", "kind": "StorageV2", "sku": {"name": "Standard_LRS"}}, "2023-01-01"),
        "cos": ("/Microsoft.DocumentDB/databaseAccounts/c1", {"location": "eastus", "kind": "GlobalDocumentDB", "properties": {"databaseAccountOfferType": "Standard", "locations": [{"locationName": "eastus", "failoverPriority": 0}]}}, "2023-11-15"),
        "sb": ("/Microsoft.ServiceBus/namespaces/n1", {"location": "eastus", "sku": {"name": "Standard"}}, "2022-10-01-preview"),
        "acr": ("/Microsoft.ContainerRegistry/registries/acr1", {"location": "eastus", "sku": {"name": "Basic"}}, "2023-07-01"),
    }
    for k, (p, b, v) in res.items():
        _check(f"create {k}", h("PUT", P + p, b, v)["status"] in (200, 201))
    # ── Diagnose ──
    dg = lambda p: h("GET", P + p + "/providers/Microsoft.Vyomi/diagnostics", None, "2024-01-01")
    for k, want in (("sql", "tls"), ("sqldb", "tde"), ("kv", "purgeprotection"), ("st", "blobpublic"), ("cos", "failover"), ("sb", "auth"), ("acr", "admin")):
        r = dg(res[k][0])
        ids = [d["id"] for d in r["body"].get("detectors", [])]
        _check(f"{k}: service detectors run", r["status"] == 200 and want in ids and "provisioning" in ids)
    d = {x["id"]: x for x in dg(res["acr"][0])["body"]["detectors"]}
    _check("acr admin detector healthy while admin user is off", d["admin"]["status"] == "Healthy")
    h("PATCH", P + res["acr"][0], {"properties": {"adminUserEnabled": True}}, "2023-07-01")
    d = {x["id"]: x for x in dg(res["acr"][0])["body"]["detectors"]}
    _check("changing the registry changes the finding", d["admin"]["status"] == "Warning")
    # ── Tasks ──
    wf = lambda t, rid, **kw: h("POST", P + "/Microsoft.Logic/vyomiCreateTask", {"templateId": t, "resourceId": rid, "name": "t-" + t, **kw}, "2019-05-01")
    for t, k in (("storage-rotate-key", "st"), ("storage-keys-report", "st"), ("cosmos-rotate-key", "cos"), ("keyvault-config-report", "kv"),
                 ("servicebus-queues-report", "sb"), ("sql-databases-report", "sql"), ("sqldb-report", "sqldb")):
        rid = P + res[k][0]
        r = wf(t, rid)
        ok = r["status"] == 201
        if ok:
            run_ = h("POST", P + f"/Microsoft.Logic/workflows/t-{t}/triggers/Recurrence/run", None, "2019-05-01")
            ok = run_["body"].get("status") == "Succeeded"
        _check(f"task {t} creates and runs", ok)
    _check("a template refuses the wrong resource type", wf("storage-rotate-key", P + res["kv"][0])["status"] == 400)
    old = h("POST", P + res["st"][0] + "/listKeys", None, "2023-01-01")["body"]["keys"][0]["value"]
    wf("storage-rotate-key", P + res["st"][0], name="rot2")
    h("POST", P + "/Microsoft.Logic/workflows/rot2/triggers/Recurrence/run", None, "2019-05-01")
    new = h("POST", P + res["st"][0] + "/listKeys", None, "2023-01-01")["body"]["keys"][0]["value"]
    _check("the scheduled task really rotated key1", old != new)
    # ── VM extensions ──
    V = P + "/Microsoft.Compute/virtualMachines/vm1"
    h("PUT", V, {"location": "eastus", "properties": {"hardwareProfile": {"vmSize": "Standard_B1s"}, "osProfile": {"computerName": "vm1", "adminUsername": "u", "adminPassword": "Passw0rd!x1"}, "networkProfile": {"networkInterfaces": []}}}, "2024-03-01")
    _check("extension install", h("PUT", V + "/extensions/CustomScript", {"location": "eastus", "properties": {"publisher": "Microsoft.Azure.Extensions", "type": "CustomScript", "typeHandlerVersion": "2.1", "settings": {"commandToExecute": "echo hi"}}}, "2024-03-01")["status"] in (200, 201))
    ex = h("GET", V + "/extensions", None, "2024-03-01")["body"]["value"]
    _check("extension listed with settings", [e["name"] for e in ex] == ["CustomScript"] and ex[0]["properties"]["settings"]["commandToExecute"] == "echo hi")
    h("DELETE", V + "/extensions/CustomScript", None, "2024-03-01")
    _check("extension uninstall", h("GET", V + "/extensions", None, "2024-03-01")["body"]["value"] == [])
    wfv = wf("vm-deallocate", V)
    _check("vm task creates", wfv["status"] == 201)
    h("POST", P + "/Microsoft.Logic/workflows/t-vm-deallocate/triggers/Recurrence/run", None, "2019-05-01")
    _check("vm task really deallocates", "deallocated" in json.dumps(h("GET", V, None, "2024-03-01")["body"]["properties"]).lower())
    # ── Key Vault soft delete ──
    r = AwsWireRouter()

    def kv(m, p, b=None):
        o = r.handle(m, p, {"api-version": "7.4"}, {"content-type": "application/json"}, json.dumps(b).encode() if b is not None else b"")
        body = o.get("body") or b""
        return o["status"], (json.loads(body) if body else None)

    kv("PUT", "/secrets/sd1", {"value": "v1"})
    kv("DELETE", "/secrets/sd1")
    st, ls = kv("GET", "/deletedsecrets")
    _check("deleted secret is listed with purge date", st == 200 and [x["id"].split("/")[-1] for x in ls["value"]] == ["sd1"] and ls["value"][0]["scheduledPurgeDate"] > ls["value"][0]["deletedDate"])
    _check("deleted secret is gone from /secrets", kv("GET", "/secrets/sd1")[0] == 404)
    _check("recover brings it back", kv("POST", "/deletedsecrets/sd1/recover")[0] == 200 and kv("GET", "/secrets/sd1")[1]["value"] == "v1")
    kv("DELETE", "/secrets/sd1")
    _check("purge removes it for good", kv("DELETE", "/deletedsecrets/sd1")[0] == 204 and kv("GET", "/deletedsecrets/sd1")[0] == 404 and kv("GET", "/secrets/sd1")[0] == 404)
    kv("POST", "/keys/kd1/create", {"kty": "RSA"})
    kv("DELETE", "/keys/kd1")
    st, ls = kv("GET", "/deletedkeys")
    _check("deleted key is listed", st == 200 and len(ls["value"]) == 1 and kv("GET", "/keys")[1]["value"] == [])
    _check("recover restores key material", kv("POST", "/deletedkeys/kd1/recover")[0] == 200 and len(kv("GET", "/keys")[1]["value"]) == 1)
    kv("DELETE", "/keys/kd1")
    _check("purge of a key", kv("DELETE", "/deletedkeys/kd1")[0] == 204 and kv("GET", "/deletedkeys")[1]["value"] == [])
    _check("unknown deleted key is a native 404", kv("POST", "/deletedkeys/nope/recover")[0] == 404)
    print("ALL OK")


if __name__ == "__main__":
    run()
