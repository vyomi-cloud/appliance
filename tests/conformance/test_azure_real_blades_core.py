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


def test_sql_blades():
    arm = AzureArm()
    av = "2023-05-01-preview"
    srv = f"{P}/Microsoft.Sql/servers/sqlb"
    call(arm, "PUT", srv, {"location": "eastus", "properties": {"administratorLogin": "sqladmin"}}, av)
    call(arm, "PUT", f"{P}/Microsoft.Sql/servers/sqlb2", {"location": "westus", "properties": {}}, av)
    s, db = call(arm, "PUT", srv + "/databases/app", {"location": "eastus"}, av)
    _check("database reports status, sku and earliest restore point",
           db["properties"]["status"] == "Online" and db["sku"]["tier"] and db["properties"]["earliestRestoreDate"])
    s, ep = call(arm, "GET", srv + "/encryptionProtector", av=av)
    _check("server TDE protector is service-managed", ep["value"][0]["properties"]["serverKeyType"] == "ServiceManaged")
    s, tde = call(arm, "GET", srv + "/databases/app/transparentDataEncryption", av=av)
    _check("database TDE enabled by default", tde["value"][0]["properties"]["state"] == "Enabled")
    call(arm, "PUT", srv + "/databases/app/transparentDataEncryption/current", {"properties": {"state": "Disabled"}}, av)
    s, tde = call(arm, "GET", srv + "/databases/app/transparentDataEncryption", av=av)
    _check("TDE state persists", tde["value"][0]["properties"]["state"] == "Disabled")
    s, st = call(arm, "GET", srv + "/databases/app/backupShortTermRetentionPolicies", av=av)
    _check("PITR retention defaults to 7 days", st["value"][0]["properties"]["retentionDays"] == 7)
    s, b = call(arm, "PUT", srv + "/databases/app/backupShortTermRetentionPolicies/default", {"properties": {"retentionDays": 90}}, av)
    _check("PITR retention outside 1-35 days rejected", s == 400)
    s, b = call(arm, "PUT", srv + "/databases/app/backupShortTermRetentionPolicies/default", {"properties": {"retentionDays": 14, "diffBackupIntervalInHours": 24}}, av)
    _check("PITR retention saved", b["properties"]["retentionDays"] == 14)
    s, au = call(arm, "GET", srv + "/auditingSettings", av=av)
    _check("auditing off by default with the default action groups",
           au["value"][0]["properties"]["state"] == "Disabled" and "BATCH_COMPLETED_GROUP" in au["value"][0]["properties"]["auditActionsAndGroups"])
    s, b = call(arm, "PUT", srv + "/auditingSettings/default", {"properties": {"state": "Enabled"}}, av)
    _check("enabling auditing without a destination is rejected", s == 400)
    s, b = call(arm, "PUT", srv + "/auditingSettings/default", {"properties": {"state": "Enabled", "isAzureMonitorTargetEnabled": True}}, av)
    _check("auditing enabled to Azure Monitor", b["properties"]["state"] == "Enabled")
    s, sa = call(arm, "GET", srv + "/securityAlertPolicies", av=av)
    _check("Defender for SQL policy present (off)", sa["value"][0]["properties"]["state"] == "Disabled")
    s, b = call(arm, "PUT", srv + "/failoverGroups/fg1", {"properties": {"partnerServers": [{"id": srv}]}}, av)
    _check("failover group partner must be another server", s == 400)
    s, fg = call(arm, "PUT", srv + "/failoverGroups/fg1", {"properties": {"partnerServers": [{"id": f"{P}/Microsoft.Sql/servers/sqlb2"}],
                                                                           "databases": [db["id"]]}}, av)
    _check("failover group: primary role, partner location filled",
           fg["properties"]["replicationRole"] == "Primary" and fg["properties"]["partnerServers"][0]["location"] == "westus")
    s, cap = call(arm, "GET", f"/subscriptions/{SUB}/providers/Microsoft.Sql/locations/eastus/capabilities", av=av)
    eds = [e["name"] for e in cap["supportedServerVersions"][0]["supportedEditions"]]
    _check("capabilities list the SQL editions", "GeneralPurpose" in eds and "Basic" in eds)
    s, b = call(arm, "PATCH", db["id"], {"sku": {"name": "S1", "tier": "Standard", "capacity": 20}}, av)
    _check("database tier change persists", b["sku"]["name"] == "S1")
    call(arm, "DELETE", db["id"], av=av)
    s, dd = call(arm, "GET", srv + "/restorableDroppedDatabases", av=av)
    _check("deleted database listed as restorable dropped database",
           [x["properties"]["databaseName"] for x in dd["value"]] == ["app"] and dd["value"][0]["properties"]["deletionDate"])


def test_cosmos_blades():
    arm = AzureArm()
    av = "2024-05-15"
    acct = f"{P}/Microsoft.DocumentDB/databaseAccounts/cosb"
    s, a = call(arm, "PUT", acct, {"location": "eastus", "kind": "GlobalDocumentDB", "properties": {}}, av)
    p = a["properties"]
    _check("account reports its region, consistency and periodic backup policy",
           p["locations"][0]["locationName"] == "East US" and p["consistencyPolicy"]["defaultConsistencyLevel"] == "Session"
           and p["backupPolicy"]["periodicModeProperties"]["backupIntervalInMinutes"] == 240)
    s, b = call(arm, "PATCH", acct, {"properties": {"consistencyPolicy": {"defaultConsistencyLevel": "Wrong"}}}, av)
    _check("invalid consistency level rejected", s == 400)
    s, b = call(arm, "PATCH", acct, {"properties": {"consistencyPolicy": {"defaultConsistencyLevel": "BoundedStaleness",
                                                                          "maxStalenessPrefix": 1000, "maxIntervalInSeconds": 300}}}, av)
    _check("bounded staleness saved", b["properties"]["consistencyPolicy"]["maxIntervalInSeconds"] == 300)
    s, b = call(arm, "PATCH", acct, {"properties": {"locations": [{"locationName": "East US", "failoverPriority": 0},
                                                                  {"locationName": "westus", "failoverPriority": 1}]}}, av)
    _check("added read region; writes stay in the priority-0 region",
           [l["locationName"] for l in b["properties"]["readLocations"]] == ["East US", "West US"]
           and [l["locationName"] for l in b["properties"]["writeLocations"]] == ["East US"])
    s, rest = call(arm, "GET", f"/subscriptions/{SUB}/providers/Microsoft.DocumentDB/restorableDatabaseAccounts", av=av)
    _check("periodic account is not point-in-time restorable", all(x["properties"]["accountName"] != "cosb" for x in rest["value"]))
    s, b = call(arm, "PATCH", acct, {"properties": {"backupPolicy": {"type": "Continuous"}}}, av)
    s, rest = call(arm, "GET", f"/subscriptions/{SUB}/providers/Microsoft.DocumentDB/restorableDatabaseAccounts", av=av)
    _check("continuous backup makes it restorable",
           b["properties"]["backupPolicy"]["type"] == "Continuous" and any(x["properties"]["accountName"] == "cosb" for x in rest["value"]))
    s, db = call(arm, "PUT", acct + "/sqlDatabases/shop", {"properties": {"resource": {"id": "shop"}, "options": {"throughput": 400}}}, av)
    _check("database resource id set", db["properties"]["resource"]["id"] == "shop")
    s, ts = call(arm, "GET", acct + "/sqlDatabases/shop/throughputSettings", av=av)
    _check("database created with shared 400 RU/s", ts["value"][0]["properties"]["resource"]["throughput"] == 400)
    s, b = call(arm, "PUT", acct + "/sqlDatabases/shop/throughputSettings/default", {"properties": {"resource": {"throughput": 450}}}, av)
    _check("450 RU/s (not a multiple of 100) rejected", s == 400)
    s, b = call(arm, "PUT", acct + "/sqlDatabases/shop/throughputSettings/default", {"properties": {"resource": {"throughput": 500}}}, av)
    _check("manual 500 RU/s saved", s == 200 and b["properties"]["resource"]["throughput"] == 500)
    s, b = call(arm, "PUT", acct + "/sqlDatabases/shop/throughputSettings/default", {"properties": {"resource": {"autoscaleSettings": {"maxThroughput": 1500}}}}, av)
    _check("autoscale max must be a multiple of 1000", s == 400)
    s, b = call(arm, "PUT", acct + "/sqlDatabases/shop/throughputSettings/default", {"properties": {"resource": {"autoscaleSettings": {"maxThroughput": 4000}}}}, av)
    _check("autoscale 4000 → baseline 400", b["properties"]["resource"]["throughput"] == 400)
    call(arm, "PUT", acct + "/sqlDatabases/logs", {"properties": {"resource": {"id": "logs"}}}, av)
    s, c = call(arm, "PUT", acct + "/sqlDatabases/logs/containers/events", {"properties": {"resource": {"id": "events"}}}, av)
    s, ct = call(arm, "GET", acct + "/sqlDatabases/logs/containers/events/throughputSettings", av=av)
    _check("container in a database without shared throughput gets dedicated 400 RU/s",
           ct["value"][0]["properties"]["resource"]["throughput"] == 400 and c["properties"]["resource"]["partitionKey"]["paths"] == ["/id"])
    s, loc = call(arm, "GET", f"/subscriptions/{SUB}/locations", av="2022-12-01")
    _check("subscription locations list regions with their pairs",
           any(x["name"] == "eastus" and x["metadata"]["pairedRegion"][0]["name"] == "westus" for x in loc["value"]))
    s, d = call(arm, "PUT", acct + "/providers/Microsoft.Security/advancedThreatProtectionSettings/current", {"properties": {"isEnabled": True}}, "2019-01-01")
    s, dl = call(arm, "GET", acct + "/providers/Microsoft.Security/advancedThreatProtectionSettings", av="2019-01-01")
    _check("Defender setting stored on the account", dl["value"][0]["properties"]["isEnabled"] is True)


def test_function_app_blades():
    arm = AzureArm()
    av = "2023-12-01"
    site = f"{P}/Microsoft.Web/sites/fnb"
    s, a = call(arm, "PUT", site, {"location": "eastus", "kind": "functionapp", "properties": {"runtime": "python"}}, av)
    plan_id = a["properties"]["serverFarmId"]
    s, plan = call(arm, "GET", plan_id, av=av)
    _check("site gets a Consumption (Y1) plan that counts it", plan["sku"]["name"] == "Y1" and plan["properties"]["numberOfSites"] == 1)
    s, b = call(arm, "PATCH", plan_id, {"sku": {"name": "Z9"}}, av)
    _check("unknown pricing tier rejected", s == 400)
    s, b = call(arm, "PATCH", plan_id, {"sku": {"name": "EP1"}}, av)
    _check("scale up to Elastic Premium", b["sku"]["tier"] == "ElasticPremium")
    _check("plan with apps can't be deleted", call(arm, "DELETE", plan_id, av=av)[0] == 409)
    s, cfg = call(arm, "GET", site + "/config/web", av=av)
    _check("site config has TLS 1.2 / FTPS only / no source control",
           cfg["properties"]["minTlsVersion"] == "1.2" and cfg["properties"]["scmType"] == "None")
    s, b = call(arm, "PATCH", site + "/config/web", {"properties": {"minTlsVersion": "0.9"}}, av)
    _check("invalid TLS version rejected", s == 400)
    s, st = call(arm, "POST", site + "/config/appsettings/list", {}, av)
    _check("app settings carry the worker runtime", st["properties"]["FUNCTIONS_WORKER_RUNTIME"] == "python")
    call(arm, "PUT", site + "/config/appsettings", {"properties": {"FUNCTIONS_WORKER_RUNTIME": "python", "MODE": "prod"}}, av)
    s, st = call(arm, "POST", site + "/config/appsettings/list", {}, av)
    _check("app settings replaced by PUT", st["properties"] == {"FUNCTIONS_WORKER_RUNTIME": "python", "MODE": "prod"})
    s, au = call(arm, "GET", site + "/config/authsettingsV2", av=av)
    _check("authentication off by default", au["properties"]["platform"]["enabled"] is False)
    s, k = call(arm, "POST", site + "/host/default/listkeys", {}, av)
    _check("host keys: master + default", k["masterKey"] and "default" in k["functionKeys"])
    call(arm, "PUT", site + "/host/default/functionKeys/ci", {"properties": {"value": "abc123"}}, av)
    s, k2 = call(arm, "POST", site + "/host/default/listkeys", {}, av)
    _check("new host key persisted, master unchanged", k2["functionKeys"]["ci"] == "abc123" and k2["masterKey"] == k["masterKey"])
    s, fn = call(arm, "PUT", site + "/functions/hello", {"properties": {}}, av)
    _check("function gets an HTTP trigger and invoke URL", fn["properties"]["config"]["bindings"][0]["type"] == "httpTrigger"
           and fn["properties"]["invoke_url_template"].endswith("/api/hello"))
    call(arm, "PUT", site + "/deployments/d1", {"properties": {"message": "v1"}}, av)
    call(arm, "PUT", site + "/deployments/d2", {"properties": {"message": "v2"}}, av)
    s, ds = call(arm, "GET", site + "/deployments", av=av)
    act = {d["name"]: d["properties"]["active"] for d in ds["value"]}
    _check("latest deployment is the active one", act == {"d1": False, "d2": True})
    call(arm, "POST", site + "/stop", {}, av)
    s, h = call(arm, "GET", site + "/providers/Microsoft.ResourceHealth/availabilityStatuses/current", av="2023-07-01-preview")
    _check("stopped app is Unavailable in Resource Health", h["properties"]["availabilityState"] == "Unavailable")
    s, lg = call(arm, "GET", site + "/extensions/api/logs", av=av)
    msgs = [x["message"] for x in lg["value"]]
    _check("log stream records stop, deployments and config changes",
           any("stopped" in m for m in msgs) and any("d2" in m for m in msgs) and any("appsettings" in m for m in msgs))


def test_key_vault_blades():
    arm = AzureArm()
    av = "2023-07-01"
    kv = f"{P}/Microsoft.KeyVault/vaults/kvb"
    s, v = call(arm, "PUT", kv, {"location": "eastus", "properties": {"sku": {"name": "standard"}, "enableRbacAuthorization": False}}, av)
    _check("vault reports network ACLs and its URI", v["properties"]["networkAcls"]["defaultAction"] == "Allow"
           and v["properties"]["vaultUri"].startswith("https://kvb."))
    s, v = call(arm, "PATCH", kv, {"properties": {"enableRbacAuthorization": True, "enabledForDeployment": True}}, av)
    _check("access configuration persists", v["properties"]["enableRbacAuthorization"] is True and v["properties"]["enabledForDeployment"] is True)
    ra = f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.Authorization/roleAssignments/11111111-2222-3333-4444-555555555555"
    call(arm, "PUT", ra, {"properties": {"roleDefinitionId": "/providers/Microsoft.Authorization/roleDefinitions/reader",
                                         "principalId": "p1", "scope": f"/subscriptions/{SUB}/resourceGroups/{RG}"}}, "2022-04-01")
    s, lst = call(arm, "GET", kv + "/providers/Microsoft.Authorization/roleAssignments", av="2022-04-01")
    _check("role assignments inherited from the resource group apply to the vault", [x["properties"]["principalId"] for x in lst["value"]] == ["p1"])
    call(arm, "PUT", kv + "/providers/Microsoft.Authorization/roleAssignments/aaaa", {"properties": {
        "roleDefinitionId": "/providers/Microsoft.Authorization/roleDefinitions/kv-admin", "principalId": "p2"}}, "2022-04-01")
    s, lst = call(arm, "GET", kv + "/providers/Microsoft.Authorization/roleAssignments", av="2022-04-01")
    _check("a role assignment at the vault scope is listed", sorted(x["properties"]["principalId"] for x in lst["value"]) == ["p1", "p2"])


def test_vnet_blades():
    arm = AzureArm()
    v = f"{P}/Microsoft.Network/virtualNetworks/vnb"
    s, b = call(arm, "PUT", v, {"location": "eastus", "properties": {"addressSpace": {"addressPrefixes": ["10.5.0.0/16"]},
                                "subnets": [{"name": "web", "properties": {"addressPrefix": "10.6.0.0/24"}}]}})
    _check("subnet outside the address space rejected", s == 400 and b["error"]["code"] == "NetcfgSubnetRangeOutsideVnet")
    s, b = call(arm, "PUT", v, {"location": "eastus", "properties": {"addressSpace": {"addressPrefixes": ["10.5.0.0/16"]},
                                "subnets": [{"name": "web", "properties": {"addressPrefix": "10.5.1.0/24"}}]}})
    _check("vnet created", s in (200, 201))
    s, sn = call(arm, "PUT", v + "/subnets/db", {"properties": {"addressPrefix": "10.5.1.128/25"}})
    _check("overlapping subnet rejected", s == 400 and sn["error"]["code"] == "NetcfgSubnetRangesOverlap")
    s, sn = call(arm, "PUT", v + "/subnets/db", {"properties": {"addressPrefix": "10.5.2.0/24"}})
    _check("subnet added through the subnets child API", s == 201 and sn["id"].endswith("/subnets/db"))
    s, ls = call(arm, "GET", v + "/subnets")
    _check("subnets list", [x["name"] for x in ls["value"]] == ["web", "db"])
    s, nic = call(arm, "PUT", f"{P}/Microsoft.Network/networkInterfaces/n1", {"location": "eastus", "properties": {
        "ipConfigurations": [{"name": "c1", "properties": {"subnet": {"id": v + "/subnets/db"}}}]}})
    s, ls = call(arm, "GET", v + "/subnets/db")
    _check("subnet reports its connected NIC ip configuration", ls["properties"]["ipConfigurations"][0]["id"].startswith(nic["id"]))
    _check("subnet in use can't be deleted", call(arm, "DELETE", v + "/subnets/db")[0] == 400)
    s, b = call(arm, "PATCH", v, {"properties": {"addressSpace": {"addressPrefixes": ["10.7.0.0/16"]}}})
    _check("address space change that orphans subnets rejected", s == 400)
    s, b = call(arm, "PATCH", v, {"properties": {"addressSpace": {"addressPrefixes": ["10.5.0.0/16", "10.8.0.0/16"]}}})
    _check("address range added", b["properties"]["addressSpace"]["addressPrefixes"] == ["10.5.0.0/16", "10.8.0.0/16"])
    s, b = call(arm, "PATCH", v, {"properties": {"dhcpOptions": {"dnsServers": ["10.5.1.4", "bad"]}}})
    _check("invalid DNS server rejected", s == 400)
    s, b = call(arm, "PATCH", v, {"properties": {"dhcpOptions": {"dnsServers": ["10.5.1.4"]}}})
    _check("custom DNS saved", b["properties"]["dhcpOptions"]["dnsServers"] == ["10.5.1.4"])
    s, b = call(arm, "PATCH", v, {"properties": {"enableDdosProtection": True}})
    _check("DDoS protection needs a plan", s == 400)
    s, plan = call(arm, "PUT", f"{P}/Microsoft.Network/ddosProtectionPlans/plan1", {"location": "eastus"})
    s, b = call(arm, "PATCH", v, {"properties": {"enableDdosProtection": True, "ddosProtectionPlan": {"id": plan["id"]}}})
    s, plan = call(arm, "GET", plan["id"])
    _check("DDoS plan lists the protected vnet", b["properties"]["enableDdosProtection"] is True
           and plan["properties"]["virtualNetworks"][0]["id"] == v)
    _check("plan in use can't be deleted", call(arm, "DELETE", plan["id"])[0] == 400)
    s, b = call(arm, "PUT", v + "/providers/Microsoft.Insights/diagnosticSettings/d1", {"properties": {"logs": [{"category": "VMProtectionAlerts", "enabled": True}]}}, "2021-05-01-preview")
    _check("diagnostic setting without a destination rejected", s == 400)
    s, ws = call(arm, "PUT", f"{P}/Microsoft.OperationalInsights/workspaces/law1", {"location": "eastus"}, "2022-10-01")
    s, b = call(arm, "PUT", v + "/providers/Microsoft.Insights/diagnosticSettings/d1", {"properties": {
        "workspaceId": ws["id"], "logs": [{"category": "VMProtectionAlerts", "enabled": True}]}}, "2021-05-01-preview")
    s, ds = call(arm, "GET", v + "/providers/Microsoft.Insights/diagnosticSettings", av="2021-05-01-preview")
    _check("diagnostic setting to a workspace stored", [x["name"] for x in ds["value"]] == ["d1"])


def test_messaging_apim_rbac_blades():
    arm = AzureArm()
    av = "2022-10-01-preview"
    ns = f"{P}/Microsoft.ServiceBus/namespaces/sbb"
    call(arm, "PUT", ns, {"location": "eastus", "sku": {"name": "Standard"}}, av)
    s, rules = call(arm, "GET", ns + "/authorizationRules", av=av)
    _check("namespace has RootManageSharedAccessKey", [r["name"] for r in rules["value"]] == ["RootManageSharedAccessKey"])
    s, k = call(arm, "POST", ns + "/authorizationRules/RootManageSharedAccessKey/listKeys", {}, av)
    _check("SAS keys + connection string", k["primaryConnectionString"].startswith("Endpoint=sb://sbb.servicebus.windows.net/;SharedAccessKeyName=RootManageSharedAccessKey;SharedAccessKey=" + k["primaryKey"]))
    s, k2 = call(arm, "POST", ns + "/authorizationRules/RootManageSharedAccessKey/regenerateKeys", {"keyType": "SecondaryKey"}, av)
    _check("regenerate secondary only", k2["primaryKey"] == k["primaryKey"] and k2["secondaryKey"] != k["secondaryKey"])
    s, b = call(arm, "PUT", ns + "/authorizationRules/send", {"properties": {"rights": ["Manage"]}}, av)
    _check("Manage without Listen+Send rejected", s == 400)
    call(arm, "PUT", f"{P}/Microsoft.ServiceBus/namespaces/sbb2", {"location": "westus", "sku": {"name": "Standard"}}, av)
    s, b = call(arm, "PUT", ns + "/disasterRecoveryConfigs/alias1", {"properties": {"partnerNamespace": f"{P}/Microsoft.ServiceBus/namespaces/sbb2"}}, av)
    _check("geo-recovery needs Premium namespaces", s == 400 and "Premium" in b["error"]["message"])
    call(arm, "PATCH", ns, {"sku": {"name": "Premium"}}, av)
    call(arm, "PATCH", f"{P}/Microsoft.ServiceBus/namespaces/sbb2", {"sku": {"name": "Premium"}}, av)
    s, dr = call(arm, "PUT", ns + "/disasterRecoveryConfigs/alias1", {"properties": {"partnerNamespace": f"{P}/Microsoft.ServiceBus/namespaces/sbb2"}}, av)
    _check("alias paired as Primary", dr["properties"]["role"] == "Primary")
    call(arm, "POST", ns + "/disasterRecoveryConfigs/alias1/failover", {}, av)
    s, moved = call(arm, "GET", f"{P}/Microsoft.ServiceBus/namespaces/sbb2/disasterRecoveryConfigs", av=av)
    _check("failover moves the alias to the secondary", [x["name"] for x in moved["value"]] == ["alias1"])

    tp = f"{P}/Microsoft.EventGrid/topics/egb"
    call(arm, "PUT", tp, {"location": "eastus"}, "2024-06-01-preview")
    s, k = call(arm, "POST", tp + "/listKeys", {}, "2024-06-01-preview")
    s, k2 = call(arm, "POST", tp + "/regenerateKey", {"keyName": "key1"}, "2024-06-01-preview")
    _check("Event Grid keys rotate key1 only", k2["key1"] != k["key1"] and k2["key2"] == k["key2"])

    av2 = "2023-05-01-preview"
    svc = f"{P}/Microsoft.ApiManagement/service/apimb"
    s, a = call(arm, "PUT", svc, {"location": "eastus", "sku": {"name": "Developer", "capacity": 1}}, av2)
    _check("gateway host name configured", a["properties"]["hostnameConfigurations"][0]["hostName"] == "apimb.azure-api.net")
    s, b = call(arm, "PATCH", svc, {"properties": {"hostnameConfigurations": a["properties"]["hostnameConfigurations"] + [{"type": "Proxy", "hostName": "bad host"}]}}, av2)
    _check("invalid custom domain rejected", s == 400)
    s, b = call(arm, "PATCH", svc, {"properties": {"hostnameConfigurations": a["properties"]["hostnameConfigurations"] + [{"type": "Proxy", "hostName": "api.contoso.com", "certificateSource": "Managed"}]}}, av2)
    _check("custom domain added", [h["hostName"] for h in b["properties"]["hostnameConfigurations"]] == ["apimb.azure-api.net", "api.contoso.com"])
    call(arm, "PUT", svc + "/namedValues/dbpass", {"properties": {"displayName": "dbpass", "value": "s3cret", "secret": True}}, av2)
    s, nv = call(arm, "GET", svc + "/namedValues", av=av2)
    _check("secret named value hides its value", "value" not in nv["value"][0]["properties"])
    s, v = call(arm, "POST", svc + "/namedValues/dbpass/listValue", {}, av2)
    _check("listValue returns the secret", v["value"] == "s3cret")

    class Blob:
        def __init__(self): self.d = {}
        def exists(self, a, c): return c == "backups"
        def put(self, a, c, n, data, ct): self.d[(a, c, n)] = data
        def get(self, a, c, n): return self.d.get((a, c, n))
    from core import azure_arm_ext_core as ext
    blob = Blob()
    acct = f"{P}/Microsoft.Storage/storageAccounts/stbk"
    call(arm, "PUT", acct, {"location": "eastus", "sku": {"name": "Standard_LRS"}}, "2023-01-01")
    s, keys = call(arm, "POST", acct + "/listKeys", {}, "2023-01-01")
    body = {"storageAccount": "stbk", "containerName": "backups", "backupName": "b1.apimbackup", "accessType": "AccessKey", "accessKey": "wrong"}
    r = ext.route(arm.state, "POST", SUB, RG, ["Microsoft.ApiManagement", "service", "apimb", "backup"], body, {}, blob=blob)
    _check("backup with a wrong storage key rejected", r["status"] == 400)
    body["accessKey"] = keys["keys"][0]["value"]
    r = ext.route(arm.state, "POST", SUB, RG, ["Microsoft.ApiManagement", "service", "apimb", "backup"], body, {}, blob=blob)
    _check("backup written to the storage blob", r["status"] == 200 and ("stbk", "backups", "b1.apimbackup") in blob.d)
    call(arm, "DELETE", svc + "/namedValues/dbpass", av=av2)
    r = ext.route(arm.state, "POST", SUB, RG, ["Microsoft.ApiManagement", "service", "apimb", "restore"], body, {}, blob=blob)
    s, v = call(arm, "POST", svc + "/namedValues/dbpass/listValue", {}, av2)
    _check("restore brings the named value back", r["status"] == 200 and v["value"] == "s3cret")

    ra = f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.Authorization/roleAssignments/abc"
    s, b = call(arm, "PUT", ra, {"properties": {"roleDefinitionId": "r", "principalId": "p", "condition": "((x)"}}, "2022-04-01")
    _check("malformed condition rejected", s == 400)
    cond = "(@Resource[Microsoft.Storage/storageAccounts/blobServices/containers:name] StringEquals 'public')"
    s, b = call(arm, "PUT", ra, {"properties": {"roleDefinitionId": "r", "principalId": "p", "condition": cond}}, "2022-04-01")
    _check("condition stored with version 2.0", b["properties"]["condition"] == cond and b["properties"]["conditionVersion"] == "2.0")


def test_key_vault_certificates():
    import base64
    from core import azure_keyvault_certificates_core as kvc
    st = kvc.CertStore()
    s, op = kvc.dispatch(st, "kv1", "POST", "/certificates/web/create", {"policy": {"issuer": {"name": "Self"},
        "x509_props": {"subject": "CN=web.contoso.com", "sans": {"dns_names": ["web.contoso.com"]}, "validity_months": 6}}})
    _check("self-signed certificate created", s == 202 and op["status"] == "completed")
    s, b = kvc.dispatch(st, "kv1", "GET", "/certificates/web")
    der = base64.b64decode(b["cer"])
    _check("cer is a DER X.509 certificate with the subject", der[:1] == b"\x30" and b"web.contoso.com" in der)
    _check("secret holds the PEM private key + certificate", "BEGIN PRIVATE KEY" in kvc.secret_value(st, "kv1", "web"))
    _check("other issuers are not faked", kvc.dispatch(st, "kv1", "POST", "/certificates/x/create", {"policy": {"issuer": {"name": "DigiCert"}}})[0] == 400)
    s, lst = kvc.dispatch(st, "kv1", "GET", "/certificates")
    _check("certificate listed", [x["id"].rsplit("/", 1)[1] for x in lst["value"]] == ["web"])
    kvc.dispatch(st, "kv1", "PATCH", "/certificates/web", {"attributes": {"enabled": False}})
    _check("disable persists", kvc.dispatch(st, "kv1", "GET", "/certificates/web")[1]["attributes"]["enabled"] is False)
    _check("delete", kvc.dispatch(st, "kv1", "DELETE", "/certificates/web")[0] == 200 and kvc.dispatch(st, "kv1", "GET", "/certificates/web")[0] == 404)


def test_vm_disks():
    arm = AzureArm()
    vm = f"{P}/Microsoft.Compute/virtualMachines/vmd"
    s, b = call(arm, "PUT", vm, {"location": "eastus", "properties": {"hardwareProfile": {"vmSize": "Standard_B1s"}}}, "2023-09-01")
    od = b["properties"]["storageProfile"]["osDisk"]
    _check("OS disk named, sized and typed by ARM", od["name"].startswith("vmd_OsDisk_1_") and od["diskSizeGB"] == 30 and od["osType"] == "Linux")
    s, b = call(arm, "PATCH", vm, {"properties": {"storageProfile": {"dataDisks": [{"lun": 0, "createOption": "Empty"}]}}}, "2023-09-01")
    _check("empty data disk without a size rejected", s == 400)
    s, b = call(arm, "PATCH", vm, {"properties": {"storageProfile": {"dataDisks": [{"lun": 0, "diskSizeGB": 64, "createOption": "Empty"}]}}}, "2023-09-01")
    _check("data disk attached", b["properties"]["storageProfile"]["dataDisks"][0]["name"] == "vmd_DataDisk_0")


TESTS = [test_vm_disks, test_vm_blades, test_storage_blades, test_sql_blades, test_cosmos_blades, test_function_app_blades, test_key_vault_blades, test_vnet_blades,
         test_messaging_apim_rbac_blades, test_key_vault_certificates]

if __name__ == "__main__":
    for t in TESTS:
        print(t.__name__)
        t()
    print("all passed")
