"""Azure Backup (Recovery Services vaults, policies, protected VMs + file shares, recovery points as Blob artifacts, restores)
and Site Recovery (VM replication + failover). Run: PYTHONPATH=. python tests/conformance/test_azure_backup_core.py"""
try:
    from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as S
    from core.azure_blob_core import AzureBlobStore
except ImportError:  # pragma: no cover
    from azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as S  # type: ignore
    from azure_blob_core import AzureBlobStore  # type: ignore


def _check(n, c):
    if not c:
        raise AssertionError(n)
    print("  ok ", n)


def run():
    a = AzureArm()
    a.blob_store = store = AzureBlobStore()
    h = lambda m, p, b=None, q=None: a.handle(m, p, dict({"api-version": "2024-04-01"}, **(q or {})), b)
    code = lambda r: (r["body"].get("error") or {}).get("code")
    R = f"/subscriptions/{S}/resourceGroups"
    for rg in ("app", "dr"):
        h("PUT", f"{R}/{rg}", {"location": "eastus"}, {"api-version": "2021-04-01"})
    vm = f"{R}/app/providers/Microsoft.Compute/virtualMachines/web1"
    _check("vm", h("PUT", vm, {"location": "eastus", "tags": {"env": "prod"}, "properties": {"hardwareProfile": {"vmSize": "Standard_B1s"}}}, {"api-version": "2023-09-01"})["status"] in (200, 201))
    sa = f"{R}/app/providers/Microsoft.Storage/storageAccounts/files1"
    h("PUT", sa, {"location": "eastus", "kind": "StorageV2", "sku": {"name": "Standard_LRS"}}, {"api-version": "2023-01-01"})
    sh = f"{sa}/fileServices/default/shares/docs"
    h("PUT", sh, {"properties": {"shareQuota": 5}}, {"api-version": "2023-01-01"})
    a.state[sa.lower()].setdefault("_files_shares", {})
    tree = a.state[sa.lower()]["_files_shares"]["docs"]["_tree"]
    import base64
    tree["a.txt"] = {"type": "file", "_b64": base64.b64encode(b"alpha").decode(), "size": 5, "modified": "x", "contentType": "text/plain"}
    tree["d"] = {"type": "directory", "modified": "x"}
    tree["d/b.txt"] = {"type": "file", "_b64": base64.b64encode(b"beta").decode(), "size": 4, "modified": "x", "contentType": "text/plain"}

    # vault
    V = f"{R}/app/providers/Microsoft.RecoveryServices/vaults/rsv1"
    _check("bad vault name", h("PUT", V.replace("rsv1", "1bad"), {"location": "eastus"})["status"] == 400)
    _check("bad sku", h("PUT", V, {"location": "eastus", "sku": {"name": "X"}})["status"] == 400)
    r = h("PUT", V, {"location": "eastus", "sku": {"name": "RS0", "tier": "Standard"}})
    _check("vault created", r["status"] == 201 and r["body"]["properties"]["provisioningState"] == "Succeeded")
    _check("default policies seeded", {p["name"] for p in h("GET", f"{V}/backupPolicies")["body"]["value"]} == {"DefaultPolicy", "EnhancedPolicy", "HourlyLogBackup"})
    # policy validation
    pol = lambda **kw: {"properties": dict({"backupManagementType": "AzureIaasVM", "schedulePolicy": {"schedulePolicyType": "SimpleSchedulePolicy", "scheduleRunFrequency": "Daily", "scheduleRunTimes": ["2026-01-01T03:00:00Z"]},
                        "retentionPolicy": {"retentionPolicyType": "LongTermRetentionPolicy", "dailySchedule": {"retentionTimes": ["2026-01-01T03:00:00Z"], "retentionDuration": {"count": 14, "durationType": "Days"}}}}, **kw)}
    bad = pol()
    bad["properties"]["retentionPolicy"]["dailySchedule"]["retentionDuration"]["count"] = 3
    _check("VM daily retention < 7 rejected", h("PUT", f"{V}/backupPolicies/p1", bad)["status"] == 400)
    _check("weekly needs run days", h("PUT", f"{V}/backupPolicies/p1", pol(schedulePolicy={"schedulePolicyType": "SimpleSchedulePolicy", "scheduleRunFrequency": "Weekly", "scheduleRunTimes": ["2026-01-01T03:00:00Z"]}))["status"] == 400)
    _check("instant RP range", h("PUT", f"{V}/backupPolicies/p1", pol(instantRpRetentionRangeInDays=9))["status"] == 400)
    _check("policy created", h("PUT", f"{V}/backupPolicies/p1", pol(instantRpRetentionRangeInDays=2))["status"] == 201)
    share_pol = {"properties": {"backupManagementType": "AzureStorage", "workLoadType": "AzureFileShare", "schedulePolicy": {"schedulePolicyType": "SimpleSchedulePolicy", "scheduleRunFrequency": "Daily", "scheduleRunTimes": ["2026-01-01T03:00:00Z"]},
                 "retentionPolicy": {"retentionPolicyType": "LongTermRetentionPolicy", "dailySchedule": {"retentionTimes": ["2026-01-01T03:00:00Z"], "retentionDuration": {"count": 30, "durationType": "Days"}}}}}
    _check("file share policy", h("PUT", f"{V}/backupPolicies/fp", share_pol)["status"] == 201)

    # protect a VM
    C = "iaasvmcontainer;iaasvmcontainerv2;app;web1"
    I = "vm;iaasvmcontainerv2;app;web1"
    IP = f"{V}/backupFabrics/Azure/protectionContainers/{C}/protectedItems/{I}"
    body = {"properties": {"protectedItemType": "Microsoft.Compute/virtualMachines", "policyId": f"{V}/backupPolicies/p1", "sourceResourceId": vm}}
    _check("wrong policy type", h("PUT", IP, {"properties": dict(body["properties"], policyId=f"{V}/backupPolicies/fp")})["status"] == 400)
    _check("missing vm", h("PUT", IP, {"properties": dict(body["properties"], sourceResourceId=vm.replace("web1", "ghost"))})["status"] == 404)
    _check("unknown policy", h("PUT", IP, {"properties": dict(body["properties"], policyId=f"{V}/backupPolicies/nope")})["status"] == 400)
    r = h("PUT", IP, body)
    _check("vm protected (IRPending)", r["status"] == 200 and r["body"]["properties"]["protectionState"] == "IRPending")
    _check("policy in use", code(h("DELETE", f"{V}/backupPolicies/p1")) == "BMSUserErrorPolicyInUse")
    _check("vault delete blocked", h("DELETE", V)["status"] == 409)
    h("PUT", f"{R}/dr/providers/Microsoft.RecoveryServices/vaults/rsvwest", {"location": "westus"})
    wv = f"{R}/dr/providers/Microsoft.RecoveryServices/vaults/rsvwest"
    h("PUT", f"{wv}/backupPolicies/p", pol())
    _check("region mismatch", code(h("PUT", f"{wv}/backupFabrics/Azure/protectionContainers/{C}/protectedItems/{I}", {"properties": dict(body["properties"], policyId=f"{wv}/backupPolicies/p")})) == "BMSUserErrorSourceVaultRegionMismatch")
    r = h("POST", f"{IP}/backup", {"properties": {"objectType": "IaasVMBackupRequest"}})
    _check("backup accepted 202 w/ async headers", r["status"] == 202 and "Azure-AsyncOperation" in r["headers"])
    op = h("GET", r["headers"]["Azure-AsyncOperation"].split("?")[0])
    _check("operation succeeded", op["body"]["status"] == "Succeeded")
    rps = h("GET", f"{IP}/recoveryPoints")["body"]["value"]
    _check("recovery point listed", len(rps) == 1 and rps[0]["properties"]["objectType"] == "IaasVMRecoveryPoint")
    blobs = store.container_blobs("vyomirsvault/rsv-rsv1")
    _check("artifact is a REAL blob in the simulator", len(blobs) == 1 and next(iter(blobs)).endswith(".json"))
    _check("item now Protected", h("GET", IP)["body"]["properties"]["protectionState"] == "Protected")
    rp = rps[0]["name"]
    # restore: validations
    RS = f"{IP}/recoveryPoints/{rp}/restore"
    _check("restore bad type", h("POST", RS, {"properties": {"recoveryType": "Nope"}})["status"] == 400)
    _check("alt location: existing VM", code(h("POST", RS, {"properties": {"objectType": "IaasVMRestoreRequest", "recoveryType": "AlternateLocation", "targetVirtualMachineId": vm, "targetResourceGroupId": f"{R}/app"}})) == "BMSUserErrorTargetVmExists")
    # restore disks
    r = h("POST", RS, {"properties": {"objectType": "IaasVMRestoreRequest", "recoveryType": "RestoreDisks", "storageAccountId": sa, "targetResourceGroupId": f"{R}/dr"}})
    _check("restore disks accepted", r["status"] == 202)
    jobs = h("GET", f"{V}/backupJobs")["body"]["value"]
    _check("jobs recorded", {j["properties"]["operation"] for j in jobs} >= {"ConfigureBackup", "Backup", "Restore"})
    # alternate location: needs vnet
    vn = f"{R}/dr/providers/Microsoft.Network/virtualNetworks/vn1"
    h("PUT", vn, {"location": "eastus", "properties": {"addressSpace": {"addressPrefixes": ["10.0.0.0/16"]}, "subnets": [{"name": "s1", "properties": {"addressPrefix": "10.0.1.0/24"}}]}}, {"api-version": "2023-09-01"})
    alt = {"properties": {"objectType": "IaasVMRestoreRequest", "recoveryType": "AlternateLocation", "targetVirtualMachineId": f"{R}/dr/providers/Microsoft.Compute/virtualMachines/web1-restored",
                          "targetResourceGroupId": f"{R}/dr", "virtualNetworkId": vn, "subnetId": f"{vn}/subnets/s1"}}
    r = h("POST", RS, alt)
    _check("alternate-location restore creates a NEW VM", r["status"] == 202 and a.state[alt["properties"]["targetVirtualMachineId"].lower()]["tags"]["vyomi:restoredFrom"] == "web1")
    # original location resets config
    a.state[vm.lower()]["properties"]["hardwareProfile"]["vmSize"] = "Standard_D2s_v3"
    h("POST", RS, {"properties": {"objectType": "IaasVMRestoreRequest", "recoveryType": "OriginalLocation"}})
    _check("original-location restore reverts config", a.state[vm.lower()]["properties"]["hardwareProfile"]["vmSize"] == "Standard_B1s")

    # file share
    FC, FI = "storagecontainer;Storage;app;files1", "azurefileshare;docs"
    FP = f"{V}/backupFabrics/Azure/protectionContainers/{FC}/protectedItems/{FI}"
    fb = {"properties": {"protectedItemType": "AzureFileShareProtectedItem", "policyId": f"{V}/backupPolicies/fp", "sourceResourceId": sa}}
    _check("missing share", h("PUT", FP.replace("docs", "ghost"), fb)["status"] == 404)
    _check("share protected", h("PUT", FP, fb)["status"] == 200)
    h("POST", f"{FP}/backup", {"properties": {"objectType": "AzureFileShareBackupRequest"}})
    frp = h("GET", f"{FP}/recoveryPoints")["body"]["value"][0]["name"]
    tree.pop("a.txt")
    tree["d/b.txt"]["_b64"] = base64.b64encode(b"CHANGED").decode()
    FR = f"{FP}/recoveryPoints/{frp}/restore"
    rq = lambda **k: h("POST", FR, {"properties": dict({"objectType": "AzureFileShareRestoreRequest", "recoveryType": "OriginalLocation", "restoreRequestType": "FullShareRestore", "copyOptions": "Skip"}, **k)})
    _check("Skip restores missing file only", rq()["status"] == 202 and "a.txt" in tree and base64.b64decode(tree["d/b.txt"]["_b64"]) == b"CHANGED")
    _check("FailOnConflict", code(rq(copyOptions="FailOnConflict")) == "BMSUserErrorFileConflict")
    rq(copyOptions="Overwrite")
    _check("Overwrite restores bytes", base64.b64decode(tree["d/b.txt"]["_b64"]) == b"beta")
    rq(copyOptions="CreateCopy")
    _check("CreateCopy keeps both", any("_restored_" in k for k in tree))
    tree.pop("a.txt")
    _check("item-level needs specs", rq(restoreRequestType="ItemLevelRestore")["status"] == 400)
    rq(restoreRequestType="ItemLevelRestore", restoreFileSpecs=[{"path": "a.txt", "fileSpecType": "File", "targetFolderPath": "recovered"}])
    _check("item-level to folder", "recovered/a.txt" in tree)
    sh2 = f"{sa}/fileServices/default/shares/copy"
    h("PUT", sh2, {"properties": {"shareQuota": 5}}, {"api-version": "2023-01-01"})
    rq(recoveryType="AlternateLocation", targetDetails={"name": "copy", "targetResourceId": sa})
    _check("alternate share restore", "d/b.txt" in a.state[sa.lower()]["_files_shares"]["copy"]["_tree"])

    # vault config + soft delete + immutability
    _check("storage type", h("PUT", f"{V}/backupstorageconfig/vaultstorageconfig", {"properties": {"storageModelType": "LocallyRedundant"}})["status"] == 400)  # items exist
    _check("soft delete config", h("PUT", f"{V}/backupconfig/vaultconfig", {"properties": {"softDeleteFeatureState": "Disabled"}})["body"]["properties"]["softDeleteFeatureState"] == "Disabled")
    h("PUT", f"{V}/backupconfig/vaultconfig", {"properties": {"softDeleteFeatureState": "Enabled"}})
    r = h("DELETE", FP)
    _check("delete = soft delete", r["status"] == 200 and h("GET", FP)["body"]["properties"]["isScheduledForDeferredDelete"] is True)
    _check("undelete via PUT", h("PUT", FP, fb)["body"]["properties"]["isScheduledForDeferredDelete"] is False)
    _check("backupStatus", a.handle("POST", f"/subscriptions/{S}/providers/Microsoft.RecoveryServices/locations/eastus/backupStatus", {"api-version": "2024-04-01"}, {"resourceId": vm, "resourceType": "VM"})["body"]["protectionStatus"] == "Protected")
    _check("usage summary", len(h("GET", f"{V}/backupUsageSummaries")["body"]["value"]) == 2)
    h("PUT", V, {"location": "eastus", "properties": {"securitySettings": {"immutabilitySettings": {"state": "Locked"}}}})
    _check("locked immutability cannot relax", h("PUT", V, {"location": "eastus", "properties": {"securitySettings": {"immutabilitySettings": {"state": "Disabled"}}}})["status"] == 400)
    _check("immutable: RP delete blocked", code(h("DELETE", f"{IP}/recoveryPoints/{rp}")) == "BMSUserErrorImmutableVault")
    _check("immutable: delete data blocked", code(h("DELETE", IP)) == "BMSUserErrorImmutableVault")

    # Site Recovery
    h("PUT", f"{R}/dr/providers/Microsoft.RecoveryServices/vaults/asr", {"location": "eastus"})
    AV = f"{R}/dr/providers/Microsoft.RecoveryServices/vaults/asr"
    h("PUT", f"{AV}/replicationFabrics/east", {"properties": {"customDetails": {"instanceType": "Azure", "location": "eastus"}}})
    RI = f"{AV}/replicationFabrics/east/replicationProtectionContainers/default/replicationProtectedItems/web1-repl"
    ra = lambda **k: {"properties": {"providerSpecificDetails": dict({"instanceType": "A2A", "fabricObjectId": vm, "recoveryAzureLocation": "westus", "recoveryResourceGroupId": f"{R}/dr"}, **k)}}
    _check("replication needs different region", code(h("PUT", RI, ra(recoveryAzureLocation="eastus"))) == "ReplicationTargetSameAsSource")
    _check("replication target rg must exist", code(h("PUT", RI, ra(recoveryResourceGroupId=f"{R}/ghost"))) == "InvalidRecoveryResourceGroup")
    r = h("PUT", RI, ra())
    _check("replication enabled", r["status"] == 200 and r["body"]["properties"]["replicationHealth"] == "Normal")
    _check("duplicate replication", h("PUT", RI + "2", ra())["status"] == 409)
    _check("vault delete blocked by replication", h("DELETE", AV)["status"] == 409)
    tf = lambda act, body=None: h("POST", f"{RI}/{act}", body or {"properties": {"providerSpecificDetails": {"instanceType": "A2A", "recoveryAzureNetworkId": vn}}})
    _check("test failover needs network", tf("testFailover", {"properties": {}})["status"] == 400)
    _check("test failover creates replica VM", tf("testFailover")["status"] == 200 and a.state[f"{R}/dr/providers/Microsoft.Compute/virtualMachines/web1-test".lower()]["tags"]["vyomi:drMode"] == "test")
    _check("failover blocked during test", tf("unplannedFailover")["status"] == 400)
    tf("testFailoverCleanup")
    _check("cleanup removes replica", f"{R}/dr/providers/Microsoft.Compute/virtualMachines/web1-test".lower() not in a.state)
    _check("unplanned failover", tf("unplannedFailover")["status"] == 200 and h("GET", RI)["body"]["properties"]["activeLocation"] == "Recovery")
    _check("commit", tf("commit")["status"] == 200)
    _check("reprotect", tf("reProtect")["status"] == 200 and h("GET", RI)["body"]["properties"]["protectionState"] == "Protected")
    _check("replication jobs", len(h("GET", f"{AV}/replicationJobs")["body"]["value"]) >= 5)
    _check("disable replication", h("DELETE", RI)["status"] == 200)
    # cascade
    pre = len([k for k in a.state if k.startswith(AV.lower() + "/")])
    _check("vault delete cascades children", h("DELETE", AV)["status"] == 200 and not [k for k in a.state if k.startswith(AV.lower())])
    print("azure backup core: all checks passed")


if __name__ == "__main__":
    run()
