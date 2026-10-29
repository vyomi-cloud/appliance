"""Azure resource blades backed by real ARM state — the data each console blade reads.

Runs the SAME shared engine both consoles use (core/azure_arm_ext_core via the Nano
``AzureArm``; the offline dispatcher calls the identical functions), so what is proven
here is what the blade shows offline and in Nano:

  Virtual Machines — Networking (NIC private IP allocated from the subnet, public IP,
  NSG and the NIC↔VM back-reference), Connect (instanceView power + agent state),
  Identity (system-assigned principal allocated / dropped), Locks (CanNotDelete /
  ReadOnly enforced with 409 ScopeLocked, inherited from the resource group),
  Diagnose (Resource Health follows the power state), Auto-shutdown (DevTestLab
  schedule), Backup (restore points capture the VM config), Extensions (child list
  scoped to this VM), Run command (recorded with its instance view; no output is
  invented without a guest runtime), Alerts (metric alert scoped to the VM),
  and delete cascades (NIC/PIP with deleteOption=Delete, schedule, children).

Run on host:    python3 tests/conformance/test_azure_real_blades_core.py
"""
try:
    from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION
except ImportError:  # pragma: no cover - Pyodide flat layout
    from azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION  # type: ignore

SUB = DEFAULT_SUBSCRIPTION
RG = "cloudlearn-rg"
P = f"/subscriptions/{SUB}/resourceGroups/{RG}/providers"


def _check(name, cond, extra=""):
    if not cond:
        raise AssertionError(f"{name} {extra}")
    print(f"  ok  {name}")


def call(arm, method, path, body=None, av="2023-11-01"):
    r = arm.handle(method, path + ("&" if "?" in path else "?") + "api-version=" + av, {"api-version": av}, body)
    return r["status"], r["body"]


def test_vm_blades():
    arm = AzureArm()
    vm = f"{P}/Microsoft.Compute/virtualMachines/vm1"
    s, b = call(arm, "PUT", f"{P}/Microsoft.Network/virtualNetworks/vnet1",
                {"location": "eastus", "properties": {"addressSpace": {"addressPrefixes": ["10.4.0.0/16"]},
                 "subnets": [{"name": "default", "properties": {"addressPrefix": "10.4.1.0/24"}}]}})
    _check("vnet created", s in (200, 201), s)
    s, nsg = call(arm, "PUT", f"{P}/Microsoft.Network/networkSecurityGroups/nsg1",
                  {"location": "eastus", "properties": {"securityRules": [{"name": "SSH", "properties": {
                      "priority": 300, "direction": "Inbound", "access": "Allow", "protocol": "Tcp",
                      "destinationPortRange": "22", "sourceAddressPrefix": "*", "destinationAddressPrefix": "*"}}]}})
    s, pip = call(arm, "PUT", f"{P}/Microsoft.Network/publicIPAddresses/pip1", {"location": "eastus", "sku": {"name": "Standard"}})
    _check("public IP allocated", s == 201 and pip["properties"]["ipAddress"].count(".") == 3, pip)
    sub_id = f"{P}/Microsoft.Network/virtualNetworks/vnet1/subnets/default"
    nic_body = {"location": "eastus", "properties": {
        "networkSecurityGroup": {"id": nsg["id"]},
        "ipConfigurations": [{"name": "ipconfig1", "properties": {
            "subnet": {"id": sub_id}, "publicIPAddress": {"id": pip["id"], "properties": {"deleteOption": "Delete"}}}}]}}
    s, nic = call(arm, "PUT", f"{P}/Microsoft.Network/networkInterfaces/nic1", nic_body)
    ip = nic["properties"]["ipConfigurations"][0]["properties"]["privateIPAddress"]
    _check("NIC private IP allocated from the subnet (Azure reserves .0-.3)", s == 201 and ip == "10.4.1.4", ip)
    s, nic2 = call(arm, "PUT", f"{P}/Microsoft.Network/networkInterfaces/nic2",
                   {"location": "eastus", "properties": {"ipConfigurations": [{"name": "c", "properties": {"subnet": {"id": sub_id}}}]}})
    _check("second NIC gets the next free address", nic2["properties"]["ipConfigurations"][0]["properties"]["privateIPAddress"] == "10.4.1.5")
    s, b = call(arm, "PUT", f"{P}/Microsoft.Network/networkInterfaces/bad",
                {"location": "eastus", "properties": {"ipConfigurations": [{"name": "c", "properties": {"subnet": {"id": sub_id + "x"}}}]}})
    _check("NIC on a missing subnet is rejected", s == 400, b)
    s, pipv = call(arm, "GET", pip["id"])
    _check("public IP knows its NIC ip configuration", pipv["properties"]["ipConfiguration"]["id"].lower().startswith(nic["id"].lower()))
    s, nsgv = call(arm, "GET", nsg["id"])
    _check("NSG lists the NIC", any(x["id"] == nic["id"] for x in nsgv["properties"]["networkInterfaces"]))

    s, b = call(arm, "PUT", vm, {"location": "eastus", "properties": {"hardwareProfile": {"vmSize": "Standard_B1s"},
                "networkProfile": {"networkInterfaces": [{"id": nic["id"] + "-missing"}]}}}, "2023-09-01")
    _check("VM referencing a missing NIC is rejected", s == 400, b)
    s, b = call(arm, "PUT", vm, {"location": "eastus", "identity": {"type": "SystemAssigned"},
                "properties": {"hardwareProfile": {"vmSize": "Standard_B1s"}, "osProfile": {"adminUsername": "azureuser"},
                "networkProfile": {"networkInterfaces": [{"id": nic["id"], "properties": {"primary": True, "deleteOption": "Delete"}}]}}},
                "2023-09-01")
    _check("VM created", s in (200, 201), b)
    _check("system-assigned identity gets a principal", len(b["identity"]["principalId"]) == 36 and b["identity"]["tenantId"])
    s, idd = call(arm, "GET", vm + "/providers/Microsoft.ManagedIdentity/identities/default", av="2023-01-31")
    _check("identities/default returns that principal", idd["properties"]["principalId"] == b["identity"]["principalId"])
    s, nicv = call(arm, "GET", nic["id"])
    _check("NIC back-references the VM", nicv["properties"]["virtualMachine"]["id"] == vm)
    s, b = call(arm, "DELETE", nic["id"])
    _check("attached NIC cannot be deleted", s == 400 and b["error"]["code"] == "NicInUse")

    s, iv = call(arm, "GET", vm + "/instanceView", av="2023-09-01")
    _check("instanceView reports power state", any(x["code"] == "PowerState/running" for x in iv["statuses"]), iv)
    _check("no guest runtime → VM agent Not Ready", iv["vmAgent"]["statuses"][0]["displayStatus"] == "Not Ready")
    s, h = call(arm, "GET", vm + "/providers/Microsoft.ResourceHealth/availabilityStatuses/current", av="2023-07-01-preview")
    _check("health Available while running", h["properties"]["availabilityState"] == "Available")
    call(arm, "POST", vm + "/powerOff", {}, "2023-09-01")
    s, h = call(arm, "GET", vm + "/providers/Microsoft.ResourceHealth/availabilityStatuses/current", av="2023-07-01-preview")
    _check("health Unavailable (Customer Initiated) after power off",
           h["properties"]["availabilityState"] == "Unavailable" and h["properties"]["reasonType"] == "Customer Initiated")
    s, b = call(arm, "PUT", vm + "/runCommands/r0", {"location": "eastus", "properties": {"source": {"script": "id"}}}, "2024-03-01")
    _check("run command refused while the VM is stopped", s == 409 and b["error"]["code"] == "OperationNotAllowed")
    call(arm, "POST", vm + "/start", {}, "2023-09-01")
    s, rc = call(arm, "PUT", vm + "/runCommands/r1", {"location": "eastus", "properties": {"source": {"script": "uname -a"}}}, "2024-03-01")
    ivr = rc["properties"]["instanceView"]
    _check("run command recorded; nothing invented without a guest runtime",
           s == 201 and ivr["executionState"] == "Failed" and ivr["output"] == "" and "guest" in ivr["executionMessage"], ivr)
    s, lst = call(arm, "GET", vm + "/runCommands", av="2024-03-01")
    _check("run history lists the run", [x["name"] for x in lst["value"]] == ["r1"])
    executed = []
    ok = __import__("core.azure_arm_ext_core", fromlist=["x"])
    st = arm.state
    res = ok.route(st, "PUT", SUB, RG, ["Microsoft.Compute", "virtualMachines", "vm1", "runCommands", "r2"],
                   {"properties": {"source": {"script": "echo hi"}}}, {},
                   executor=lambda v, sc: executed.append(sc) or (0, "hi\n", ""))
    _check("with a guest runtime the script runs and its output is stored",
           executed == ["echo hi"] and res["body"]["properties"]["instanceView"]["output"] == "hi\n")

    s, b = call(arm, "PUT", vm + "/extensions/CustomScript", {"location": "eastus", "properties": {
        "publisher": "Microsoft.Azure.Extensions", "type": "CustomScript", "typeHandlerVersion": "2.1"}}, "2023-09-01")
    call(arm, "PUT", f"{P}/Microsoft.Compute/virtualMachines/vm2", {"location": "eastus", "properties": {}}, "2023-09-01")
    call(arm, "PUT", f"{P}/Microsoft.Compute/virtualMachines/vm2/extensions/Other", {"location": "eastus", "properties": {"type": "X"}}, "2023-09-01")
    s, ex = call(arm, "GET", vm + "/extensions", av="2023-09-01")
    _check("extensions list is scoped to this VM", [x["name"] for x in ex["value"]] == ["CustomScript"], ex)

    sched = f"{P}/Microsoft.DevTestLab/schedules/shutdown-computevm-vm1"
    s, b = call(arm, "PUT", sched, {"location": "eastus", "properties": {"status": "Enabled", "dailyRecurrence": {"time": "2530"},
                                     "targetResourceId": vm}}, "2018-09-15")
    _check("invalid shutdown time rejected", s == 400)
    s, b = call(arm, "PUT", sched, {"location": "eastus", "properties": {"status": "Enabled", "dailyRecurrence": {"time": "1930"},
                                     "timeZoneId": "UTC", "targetResourceId": vm}}, "2018-09-15")
    _check("auto-shutdown schedule stored", s == 201 and b["properties"]["taskType"] == "ComputeVmShutdownTask")

    rpc = f"{P}/Microsoft.Compute/restorePointCollections/vm1-rp"
    call(arm, "PUT", rpc, {"location": "eastus", "properties": {"source": {"id": vm}}}, "2024-03-01")
    s, rp = call(arm, "PUT", rpc + "/restorePoints/rp1", {}, "2024-03-01")
    _check("restore point captures the VM size", rp["properties"]["sourceMetadata"]["hardwareProfile"]["vmSize"] == "Standard_B1s")
    s, c = call(arm, "GET", rpc, av="2024-03-01")
    _check("collection lists its restore points", [x["name"] for x in c["properties"]["restorePoints"]] == ["rp1"])

    s, al = call(arm, "PUT", f"{P}/Microsoft.Insights/metricAlerts/cpu-high", {"location": "global", "properties": {
        "severity": 2, "enabled": True, "scopes": [vm], "evaluationFrequency": "PT1M", "windowSize": "PT5M",
        "criteria": {"odata.type": "Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria", "allOf": [
            {"name": "Metric1", "criterionType": "StaticThresholdCriterion", "metricName": "Percentage CPU",
             "timeAggregation": "Average", "operator": "GreaterThan", "threshold": 80}]}}}, "2018-03-01")
    _check("metric alert scoped to the VM", s in (200, 201) and al["properties"]["scopes"] == [vm], al)

    # Locks
    s, b = call(arm, "PUT", vm + "/providers/Microsoft.Authorization/locks/keep", {"properties": {"level": "Nope"}}, "2016-09-01")
    _check("invalid lock level rejected", s == 400)
    s, lk = call(arm, "PUT", vm + "/providers/Microsoft.Authorization/locks/keep",
                 {"properties": {"level": "CanNotDelete", "notes": "prod"}}, "2016-09-01")
    _check("lock created", s == 201 and lk["properties"]["level"] == "CanNotDelete")
    s, b = call(arm, "DELETE", vm, av="2023-09-01")
    _check("CanNotDelete blocks delete with 409 ScopeLocked", s == 409 and b["error"]["code"] == "ScopeLocked")
    s, b = call(arm, "PATCH", vm, {"tags": {"a": "1"}}, "2023-09-01")
    _check("CanNotDelete still allows updates", s == 200)
    s, rgl = call(arm, "PUT", f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.Authorization/locks/rg-ro",
                  {"properties": {"level": "ReadOnly"}}, "2016-09-01")
    s, b = call(arm, "PATCH", vm, {"tags": {"a": "2"}}, "2023-09-01")
    _check("ReadOnly lock on the resource group blocks writes to the VM", s == 409)
    s, b = call(arm, "POST", vm + "/restart", {}, "2023-09-01")
    _check("ReadOnly blocks actions too", s == 409)
    s, ll = call(arm, "GET", vm + "/providers/Microsoft.Authorization/locks", av="2016-09-01")
    _check("locks list includes the inherited RG lock", sorted(x["name"] for x in ll["value"]) == ["keep", "rg-ro"])
    call(arm, "DELETE", rgl["id"], av="2016-09-01")
    call(arm, "DELETE", lk["id"], av="2016-09-01")

    s, b = call(arm, "PATCH", vm, {"identity": {"type": "None"}}, "2023-09-01")
    _check("disabling the identity drops the principal", b["identity"] == {"type": "None"})

    s, b = call(arm, "DELETE", vm, av="2023-09-01")
    _check("VM deleted once unlocked", s == 200)
    _check("NIC with deleteOption=Delete removed with the VM", call(arm, "GET", nic["id"])[0] == 404)
    _check("its public IP (deleteOption=Delete) removed too", call(arm, "GET", pip["id"])[0] == 404)
    _check("shutdown schedule removed with the VM", call(arm, "GET", sched, av="2018-09-15")[0] == 404)
    _check("run commands / extensions removed with the VM", call(arm, "GET", vm + "/runCommands/r1", av="2024-03-01")[0] == 404)
    _check("NIC without deleteOption survives", call(arm, "GET", nic2["id"])[0] == 200)


def test_storage_blades():
    import base64, hashlib, hmac
    from urllib.parse import parse_qs
    arm = AzureArm()
    acct = f"{P}/Microsoft.Storage/storageAccounts/stblades"
    s, a = call(arm, "PUT", acct, {"location": "eastus", "sku": {"name": "Standard_LRS"}, "kind": "StorageV2"}, "2023-01-01")
    p = a["properties"]
    _check("account reports encryption, network ACLs and primary location",
           p["encryption"]["services"]["blob"]["enabled"] and p["networkAcls"]["defaultAction"] == "Allow"
           and p["primaryLocation"] == "eastus" and "secondaryLocation" not in p)
    s, k = call(arm, "POST", acct + "/listKeys", {}, "2023-01-01")
    seed = hashlib.sha256(b"cloudlearn-azure-stblades").digest()
    _check("listKeys returns the account's two keys (same derivation as the data plane)",
           [x["keyName"] for x in k["keys"]] == ["key1", "key2"] and k["keys"][0]["value"] == base64.b64encode(seed).decode())
    s, k2 = call(arm, "POST", acct + "/regenerateKey", {"keyName": "key2"}, "2023-01-01")
    _check("regenerateKey rotates only that key", k2["keys"][0]["value"] == k["keys"][0]["value"]
           and k2["keys"][1]["value"] != k["keys"][1]["value"])
    s, k3 = call(arm, "POST", acct + "/listKeys", {}, "2023-01-01")
    _check("the rotated key persists", k3["keys"][1]["value"] == k2["keys"][1]["value"])
    body = {"signedServices": "b", "signedResourceTypes": "sco", "signedPermission": "rl",
            "signedExpiry": "2030-01-01T00:00:00Z", "signedProtocol": "https"}
    s, sas = call(arm, "POST", acct + "/ListAccountSas", body, "2023-01-01")
    q = parse_qs(sas["accountSasToken"])
    sts = "\n".join(["stblades", "rl", "b", "sco", "", "2030-01-01T00:00:00Z", "", "https", "2022-11-02", "", ""])
    want = base64.b64encode(hmac.new(base64.b64decode(k["keys"][0]["value"]), sts.encode(), hashlib.sha256).digest()).decode()
    _check("account SAS is signed with key1 per the Storage SAS spec", q["sig"][0] == want and q["sv"][0] == "2022-11-02")
    s, b = call(arm, "POST", acct + "/ListAccountSas", dict(body, signedPermission="zz"), "2023-01-01")
    _check("invalid SAS permission rejected", s == 400)
    s, b = call(arm, "POST", acct + "/failover", {}, "2023-01-01")
    _check("failover refused for a locally-redundant account", s == 400)
    s, a = call(arm, "PATCH", acct, {"sku": {"name": "Standard_RAGRS"}}, "2023-01-01")
    _check("RA-GRS gets the paired secondary region", a["properties"]["secondaryLocation"] == "westus")
    s, b = call(arm, "POST", acct + "/failover", {}, "2023-01-01")
    s, a = call(arm, "GET", acct, av="2023-01-01")
    _check("failover makes the secondary primary and the account LRS",
           a["location"] == "westus" and a["sku"]["name"] == "Standard_LRS" and a["properties"]["lastGeoFailoverTime"])
    s, sh = call(arm, "PUT", acct + "/fileServices/default/shares/docs", {"properties": {"shareQuota": 100}}, "2023-01-01")
    _check("file share stored with ARM defaults", sh["properties"]["shareQuota"] == 100
           and sh["properties"]["accessTier"] == "TransactionOptimized" and sh["properties"]["lastModifiedTime"])
    s, ls = call(arm, "GET", acct + "/fileServices/default/shares", av="2023-01-01")
    _check("file shares list", [x["name"] for x in ls["value"]] == ["docs"])
    s, t = call(arm, "PUT", acct + "/tableServices/default/tables/orders", {}, "2023-01-01")
    _check("table reports its tableName", t["properties"]["tableName"] == "orders")
    s, es = call(arm, "PUT", acct + "/encryptionScopes/scope1", {"properties": {"source": "Microsoft.Storage"}}, "2023-01-01")
    _check("encryption scope enabled with a creation time", es["properties"]["state"] == "Enabled" and es["properties"]["creationTime"])
    s, mp = call(arm, "GET", acct + "/managementPolicies", av="2023-01-01")
    _check("management policies list (empty until saved)", s == 200 and mp["value"] == [])
    call(arm, "PUT", acct + "/managementPolicies/default", {"properties": {"policy": {"rules": [{"name": "r1"}]}}}, "2023-01-01")
    s, mp = call(arm, "GET", acct + "/managementPolicies", av="2023-01-01")
    _check("saved lifecycle policy listed", [x["name"] for x in mp["value"]] == ["default"])
    call(arm, "PUT", acct + "/providers/Microsoft.Authorization/locks/ro", {"properties": {"level": "ReadOnly"}}, "2016-09-01")
    s, b = call(arm, "POST", acct + "/listKeys", {}, "2023-01-01")
    _check("ReadOnly lock blocks listKeys (as in Azure)", s == 409)


TESTS = [test_vm_blades, test_storage_blades]

if __name__ == "__main__":
    for t in TESTS:
        print(t.__name__)
        t()
    print("all passed")
