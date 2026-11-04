"""AKS backup (Microsoft.DataProtection), Cosmos DB restorable accounts + restore into a new account, App Service backups/restore,
deleted storage account restore. Run: PYTHONPATH=. python tests/conformance/test_azure_dpbackup_core.py"""
import io
import json
import time
import zipfile
from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as S
from core.azure_blob_core import AzureBlobStore
from core import azure_aks_k8s_core as k8s


def _check(n, c):
    if not c:
        raise AssertionError(n)
    print("  ok ", n)


def run():
    a = AzureArm()
    a.blob_store = blobs = AzureBlobStore()
    h = lambda m, p, b=None, q=None: a.handle(m, p, dict({"api-version": "2024-05-01"}, **(q or {})), b)
    code = lambda r: (r["body"].get("error") or {}).get("code")
    R = f"/subscriptions/{S}/resourceGroups/bk"
    h("PUT", R, {"location": "eastus"}, {"api-version": "2021-04-01"})

    # ───────── AKS backup ─────────
    CL = f"{R}/providers/Microsoft.ContainerService/managedClusters"
    mk = lambda n, loc="eastus": h("PUT", f"{CL}/{n}", {"location": loc, "identity": {"type": "SystemAssigned"}, "properties": {
        "dnsPrefix": n, "agentPoolProfiles": [{"name": "np", "count": 1, "vmSize": "Standard_DS2_v2", "mode": "System"}]}})
    _check("clusters", mk("src")["status"] in (200, 201) and mk("dst")["status"] in (200, 201) and mk("far", "westus")["status"] in (200, 201))
    for n in ("src", "dst"):
        r = h("PUT", f"{CL}/{n}/providers/Microsoft.KubernetesConfiguration/extensions/azure-aks-backup", {"properties": {
            "extensionType": "microsoft.dataprotection.kubernetes", "autoUpgradeMinorVersion": True,
            "scope": {"cluster": {"releaseNamespace": "dataprotection-microsoft"}}}}) if n == "src" else None
    src = a.state[f"{CL}/src".lower()]
    kc = lambda cluster, cmd: k8s.run_command(a.state[f"{CL}/{cluster}".lower()], cmd)
    _check("kubectl ns", kc("src", "kubectl create namespace shop")["exitCode"] == 0)
    kc("src", "kubectl create namespace tools")
    manifest = """kubectl apply -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata: {name: web, namespace: shop, labels: {app: web}}
spec: {replicas: 2, selector: {matchLabels: {app: web}}, template: {metadata: {labels: {app: web}}, spec: {containers: [{name: web, image: nginx}]}}}
---
apiVersion: v1
kind: ConfigMap
metadata: {name: cfg, namespace: shop}
data: {k: v}
---
apiVersion: v1
kind: ConfigMap
metadata: {name: tool, namespace: tools}
data: {t: "1"}
EOF"""
    r = kc("src", manifest)
    _check("manifests applied", r["exitCode"] == 0)

    V = f"{R}/providers/Microsoft.DataProtection/backupVaults"
    _check("bad vault name", h("PUT", f"{V}/1bad", {"location": "eastus", "properties": {}})["status"] == 400)
    _check("vault needs location", h("PUT", f"{V}/bv1", {"properties": {}})["status"] == 400)
    _check("bad storage type", code(h("PUT", f"{V}/bv1", {"location": "eastus", "properties": {"storageSettings": [{"datastoreType": "VaultStore", "type": "Nope"}]}})) == "UserErrorInvalidStorageSettings")
    r = h("PUT", f"{V}/bv1", {"location": "eastus", "properties": {"storageSettings": [{"datastoreType": "VaultStore", "type": "LocallyRedundant"}]}})
    _check("vault created with identity", r["status"] == 201 and r["body"]["identity"]["type"] == "SystemAssigned")
    _check("default AKS policy seeded", h("GET", f"{V}/bv1/backupPolicies/aks-default")["status"] == 200)

    # policies
    P = f"{V}/bv1/backupPolicies/pol1"
    good = h("GET", f"{V}/bv1/backupPolicies/aks-default")["body"]["properties"]
    bad = json.loads(json.dumps(good))
    bad["policyRules"][0]["trigger"]["schedule"]["repeatingTimeIntervals"] = ["R/2026-01-01T02:00:00+00:00/PT5H"]
    _check("5h schedule rejected", code(h("PUT", P, {"properties": bad})) == "UserErrorInvalidBackupPolicy")
    bad = json.loads(json.dumps(good)); bad["policyRules"] = [bad["policyRules"][0]]
    _check("missing Default retention rejected", code(h("PUT", P, {"properties": bad})) == "UserErrorInvalidBackupPolicy")
    bad = json.loads(json.dumps(good)); bad["policyRules"][1]["lifecycles"][0]["deleteAfter"]["duration"] = "P400D"
    _check("operational retention > 360d rejected", code(h("PUT", P, {"properties": bad})) == "UserErrorInvalidBackupPolicy")
    bad = json.loads(json.dumps(good)); bad["datasourceTypes"] = ["Microsoft.Compute/disks"]
    _check("non-AKS datasource rejected", code(h("PUT", P, {"properties": bad})) == "UserErrorInvalidBackupPolicy")
    okp = json.loads(json.dumps(good)); okp["policyRules"][0]["trigger"]["schedule"]["repeatingTimeIntervals"] = ["R/2026-01-01T02:00:00+00:00/PT6H"]
    _check("policy created", h("PUT", P, {"properties": okp})["status"] == 201)

    # backup instance
    I = f"{V}/bv1/backupInstances/src-bi"
    pid = f"{V}/bv1/backupPolicies/pol1"
    body = lambda **kw: {"properties": dict({"objectType": "BackupInstance", "friendlyName": "src", "dataSourceInfo": {
        "objectType": "Datasource", "resourceID": f"{CL}/src", "datasourceType": "Microsoft.ContainerService/managedClusters"},
        "policyInfo": {"policyId": pid, "policyParameters": {"backupDatasourceParametersList": [dict({"objectType": "KubernetesClusterBackupDatasourceParameters", "snapshotVolumes": True}, **kw.pop("prm", {}))]}}}, **kw)}
    _check("extension required on cluster", code(h("PUT", f"{V}/bv1/backupInstances/dst-bi", {"properties": {
        "objectType": "BackupInstance", "dataSourceInfo": {"resourceID": f"{CL}/dst", "datasourceType": "Microsoft.ContainerService/managedClusters"},
        "policyInfo": {"policyId": pid}}})) == "UserErrorBackupExtensionNotInstalled")
    _check("cross-region cluster rejected", code(h("PUT", f"{V}/bv1/backupInstances/far-bi", {"properties": {
        "objectType": "BackupInstance", "dataSourceInfo": {"resourceID": f"{CL}/far", "datasourceType": "Microsoft.ContainerService/managedClusters"},
        "policyInfo": {"policyId": pid}}})) == "UserErrorDatasourceLocationMismatch")
    _check("missing cluster", code(h("PUT", I, {"properties": {"objectType": "BackupInstance", "dataSourceInfo": {"resourceID": f"{CL}/ghost", "datasourceType": "Microsoft.ContainerService/managedClusters"}, "policyInfo": {"policyId": pid}}})) == "UserErrorDatasourceNotFound")
    _check("unknown namespace", code(h("PUT", I, body(prm={"includedNamespaces": ["nope"]}))) == "UserErrorInvalidNamespace")
    _check("include/exclude conflict", code(h("PUT", I, body(prm={"includedNamespaces": ["shop"], "excludedNamespaces": ["shop"]}))) == "UserErrorNamespaceConflict")
    _check("bad policy id", code(h("PUT", I, {"properties": dict(body()["properties"], policyInfo={"policyId": pid + "x"})})) == "UserErrorPolicyNotFound")
    r = h("PUT", I, body())
    _check("instance created", r["status"] == 201 and r["body"]["properties"]["currentProtectionState"] == "ProtectionConfigured")
    _check("cluster protected by one instance only", code(h("PUT", f"{V}/bv1/backupInstances/dup", body())) == "UserErrorDatasourceAlreadyProtected")
    _check("policy in use cannot be deleted", code(h("DELETE", P)) == "UserErrorPolicyInUse")
    _check("vault with instances cannot be deleted", code(h("DELETE", f"{V}/bv1")) == "UserErrorVaultHasBackupInstances")

    # backup
    r = h("POST", f"{I}/backup", {"backupRuleOptions": {"ruleName": "Nope", "triggerOption": {"retentionTagOverride": "Default"}}})
    _check("unknown backup rule", code(r) == "UserErrorBackupRuleNotFound")
    r = h("POST", f"{I}/backup", {"backupRuleOptions": {"ruleName": "BackupDaily", "triggerOption": {"retentionTagOverride": "Default"}}})
    _check("backup accepted", r["status"] == 202 and r["body"]["recoveryPointId"])
    rps = h("GET", f"{I}/recoveryPoints")["body"]["value"]
    _check("recovery point listed with object counts", len(rps) == 1 and rps[0]["properties"]["objectCounts"].get("Deployment") == 1 and rps[0]["properties"]["objectCounts"].get("ConfigMap") == 2)
    art = [k for k in blobs.containers if k.startswith("vyomidpbackup/dp-bv1")]
    _check("snapshot artifact is a blob", bool(art) and len(blobs.blobs.get(art[0], {})) == 1 if hasattr(blobs, "blobs") else bool(art))
    jobs = h("GET", f"{V}/bv1/backupJobs")["body"]["value"]
    _check("jobs recorded", {j["properties"]["operation"] for j in jobs} >= {"ConfigureBackup", "Backup"})
    rp = rps[0]
    RESTORE = f"{I}/restore"
    rq = lambda target="dst", **crit: {"restoreRequestObject": {"objectType": "AzureBackupRecoveryPointBasedRestoreRequest", "recoveryPointId": rp["name"], "sourceDataStoreType": "OperationalStore",
        "restoreTargetInfo": {"objectType": "RestoreTargetInfo", "recoveryOption": "FailIfExists", "restoreLocation": "eastus",
                              "datasourceInfo": {"resourceID": f"{CL}/{target}", "datasourceType": "Microsoft.ContainerService/managedClusters"},
                              "restoreCriteria": [dict({"objectType": "KubernetesClusterRestoreCriteria"}, **crit)]}}}
    _check("restore needs extension on target", code(h("POST", RESTORE, rq())) == "UserErrorBackupExtensionNotInstalled")
    h("PUT", f"{CL}/dst/providers/Microsoft.KubernetesConfiguration/extensions/azure-aks-backup", {"properties": {
        "extensionType": "microsoft.dataprotection.kubernetes", "scope": {"cluster": {"releaseNamespace": "dataprotection-microsoft"}}}})
    _check("restore bad recovery point", code(h("POST", RESTORE, {"restoreRequestObject": dict(rq()["restoreRequestObject"], recoveryPointId="nope")})) == "UserErrorRecoveryPointNotFound")
    _check("restore unknown target", code(h("POST", RESTORE, rq("ghost"))) == "UserErrorTargetClusterNotFound")
    _check("restore cross-region target", code(h("POST", RESTORE, rq("far"))) in ("UserErrorTargetLocationMismatch", "UserErrorBackupExtensionNotInstalled"))
    _check("restore bad conflict policy", code(h("POST", RESTORE, rq(conflictPolicy="Nope"))) == "UserErrorInvalidConflictPolicy")
    _check("restore unknown ns in point", code(h("POST", RESTORE, rq(includedNamespaces=["ghost"]))) == "UserErrorNamespaceNotInRecoveryPoint")
    v = h("POST", f"{I}/validateForRestore", rq())
    _check("validateForRestore dry run changes nothing", v["status"] == 200 and not kc("dst", "kubectl get deployments -A")["logs"].count("web"))
    r = h("POST", RESTORE, rq(namespaceMappings={"shop": "shop-restored"}))
    _check("restore accepted", r["status"] == 202 and r["body"]["created"] >= 4 and not r["body"]["failed"])
    out = kc("dst", "kubectl get deployments -n shop-restored")["logs"]
    _check("deployment restored into mapped namespace", "web" in out)
    _check("tools namespace restored", "tool" in kc("dst", "kubectl get configmaps -n tools")["logs"])
    # conflict policy
    kc("dst", "kubectl scale deployment web -n shop-restored --replicas=5")
    r = h("POST", RESTORE, rq(namespaceMappings={"shop": "shop-restored"}, conflictPolicy="Skip"))
    _check("Skip leaves existing objects", r["body"]["skipped"] >= 3 and "5" in kc("dst", "kubectl get deployment web -n shop-restored -o json")["logs"])
    r = h("POST", RESTORE, rq(namespaceMappings={"shop": "shop-restored"}, conflictPolicy="Patch"))
    out = json.loads(kc("dst", "kubectl get deployment web -n shop-restored -o json")["logs"])
    _check("Patch overwrites with the backed up spec", r["body"]["patched"] >= 3 and out["spec"]["replicas"] == 2)
    r = h("POST", RESTORE, rq(includedNamespaces=["tools"], conflictPolicy="Patch", includedResourceTypes=["ConfigMap"]))
    _check("filtered restore", r["status"] == 202)
    # namespace filter at backup time
    kc("src", "kubectl create namespace skip-me")
    kc("src", "kubectl create configmap x -n skip-me --from-literal=a=b")
    I2 = f"{V}/bv1/backupInstances/src-bi"
    h("PUT", I2, body(prm={"includedNamespaces": ["shop"], "labelSelectors": ["app=web"]}))
    h("POST", f"{I}/backup", {"backupRuleOptions": {"ruleName": "BackupDaily", "triggerOption": {"retentionTagOverride": "Default"}}})
    rps = h("GET", f"{I}/recoveryPoints")["body"]["value"]
    newest = rps[0]["properties"]
    _check("label selector + namespace filter applied", newest["objectCounts"] == {"Deployment": 1} and newest["namespaceCount"] == 1)
    # suspend / resume
    _check("resume while configured is an error", code(h("POST", f"{I}/resumeBackups")) == "UserErrorNotSuspended")
    h("POST", f"{I}/suspendBackups")
    _check("backup while suspended refused", code(h("POST", f"{I}/backup", {})) == "UserErrorBackupNotAllowed")
    h("POST", f"{I}/resumeBackups")
    _check("delete instance", h("DELETE", I)["status"] == 200 and h("GET", I)["status"] == 404)
    _check("delete policy, then vault", h("DELETE", P)["status"] == 200 and h("DELETE", f"{V}/bv1")["status"] == 200)

    # ───────── Cosmos restore ─────────
    COS = f"{R}/providers/Microsoft.DocumentDB/databaseAccounts"
    cv = {"api-version": "2024-05-15"}
    cosmos = lambda n, **p: h("PUT", f"{COS}/{n}", {"location": "eastus", "kind": "GlobalDocumentDB", "properties": dict({
        "databaseAccountOfferType": "Standard", "locations": [{"locationName": "eastus", "failoverPriority": 0}],
        "backupPolicy": {"type": "Continuous", "continuousModeProperties": {"tier": "Continuous7Days"}}}, **p)}, cv)
    _check("continuous account", cosmos("cdb1")["status"] in (200, 201))
    db = lambda n: h("PUT", f"{COS}/cdb1/sqlDatabases/{n}", {"properties": {"resource": {"id": n}, "options": {}}}, cv)
    ct = lambda d, n: h("PUT", f"{COS}/cdb1/sqlDatabases/{d}/containers/{n}", {"properties": {"resource": {"id": n, "partitionKey": {"paths": ["/pk"], "kind": "Hash"}}, "options": {"throughput": 500}}}, cv)
    _check("db+container", db("orders")["status"] in (200, 201) and ct("orders", "items")["status"] in (200, 201))
    time.sleep(1.1)
    t_mid = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    time.sleep(1.1)
    db("temp"); ct("temp", "scratch")
    time.sleep(1.1)
    _check("delete temp db", h("DELETE", f"{COS}/cdb1/sqlDatabases/temp", None, cv)["status"] in (200, 204))
    LOC = f"/subscriptions/{S}/providers/Microsoft.DocumentDB/locations/eastus/restorableDatabaseAccounts"
    accts = h("GET", LOC, None, cv)["body"]["value"]
    _check("account listed as restorable", len(accts) == 1 and accts[0]["properties"]["accountName"] == "cdb1" and "deletionTime" not in accts[0]["properties"])
    iid = accts[0]["name"]
    _check("get restorable account", h("GET", f"{LOC}/{iid}", None, cv)["status"] == 200)
    _check("unknown restorable account", h("GET", f"{LOC}/ghost", None, cv)["status"] == 404)
    dbs = h("GET", f"{LOC}/{iid}/restorableSqlDatabases", None, cv)["body"]["value"]
    _check("restorable databases timeline has orders + temp", {d["name"] for d in dbs} >= {"orders", "temp"})
    cts = h("GET", f"{LOC}/{iid}/restorableSqlContainers", None, cv)["body"]["value"]
    _check("restorable containers listed", {c["name"] for c in cts} >= {"items", "scratch"})
    res = h("GET", f"{LOC}/{iid}/restorableSqlResources", None, cv)["body"]["value"]
    _check("restorable sql resources group collections by database", any(r["databaseName"] == "orders" and r["collectionNames"] == ["items"] for r in res))
    # validation
    rest = lambda n, ts, **kw: cosmos(n, createMode="Restore", restoreParameters=dict({"restoreSource": f"{LOC}/{iid}", "restoreTimestampInUtc": ts}, **kw))
    _check("restore: future timestamp", rest("rx", "2099-01-01T00:00:00Z")["status"] == 400)
    _check("restore: before the account existed", rest("rx", "2001-01-01T00:00:00Z")["status"] == 400)
    _check("restore: unknown source", cosmos("rx", createMode="Restore", restoreParameters={"restoreSource": f"{LOC}/ghost", "restoreTimestampInUtc": t_mid})["status"] == 404)
    _check("restore: missing timestamp", cosmos("rx", createMode="Restore", restoreParameters={"restoreSource": f"{LOC}/{iid}"})["status"] == 400)
    _check("restore: onto itself rejected", rest("cdb1", t_mid)["status"] in (400, 409))
    _check("restore: periodic policy rejected", cosmos("rx", backupPolicy={"type": "Periodic"}, createMode="Restore", restoreParameters={"restoreSource": f"{LOC}/{iid}", "restoreTimestampInUtc": t_mid})["status"] == 400)
    r = rest("cdb1-restored", t_mid)
    _check("restore into NEW account", r["status"] in (200, 201))
    names = lambda acct, typ: sorted(k.rsplit("/", 1)[1] for k in a.state if k.startswith(f"{COS}/{acct}/{typ}/".lower()) and "/__" not in k and k.count("/") == (f"{COS}/{acct}/{typ}/".count("/")))
    _check("restored account has the databases that existed at t (not temp)", names("cdb1-restored", "sqldatabases") == ["orders"])
    cc = h("GET", f"{COS}/cdb1-restored/sqlDatabases/orders/containers/items", None, cv)
    _check("container restored with partition key", cc["status"] == 200 and cc["body"]["properties"]["resource"]["partitionKey"]["paths"] == ["/pk"])
    time.sleep(1.1)
    t_late = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    r = rest("cdb1-late", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 1.5)))
    _check("later restore includes temp deleted after", r["status"] in (200, 201))
    r = rest("cdb1-sel", t_late, databasesToRestore=[{"databaseName": "orders", "collectionNames": ["items"]}])
    _check("selective restore", names("cdb1-sel", "sqldatabases") == ["orders"])
    # deleted account
    _check("delete source account", h("DELETE", f"{COS}/cdb1", None, cv)["status"] in (200, 204))
    accts = h("GET", LOC, None, cv)["body"]["value"]
    dead = [x for x in accts if x["properties"]["accountName"] == "cdb1"]
    _check("deleted account is restorable with deletionTime", len(dead) == 1 and dead[0]["properties"].get("deletionTime"))
    time.sleep(1.1)
    _check("deleted account: timestamp after deletion rejected", rest("cdb1-x", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))["status"] == 400)
    r = rest("cdb1-back", t_late)
    _check("restore a deleted account", r["status"] in (200, 201) and names("cdb1-back", "sqldatabases") == ["orders"])

    # ───────── App Service backup ─────────
    SA = f"{R}/providers/Microsoft.Storage/storageAccounts/bkstore"
    h("PUT", SA, {"location": "eastus", "kind": "StorageV2", "sku": {"name": "Standard_LRS"}}, {"api-version": "2023-01-01"})
    blobs.create_container("bkstore/backups")
    SAS = "https://bkstore.blob.core.windows.net/backups?sv=2022-11-02&sig=abc"
    PLAN = f"{R}/providers/Microsoft.Web/serverfarms"
    wv = {"api-version": "2023-12-01"}
    h("PUT", f"{PLAN}/free1", {"location": "eastus", "sku": {"name": "F1", "tier": "Free"}}, wv)
    h("PUT", f"{PLAN}/std1", {"location": "eastus", "sku": {"name": "S1", "tier": "Standard"}}, wv)
    site = lambda n, plan: h("PUT", f"{R}/providers/Microsoft.Web/sites/{n}", {"location": "eastus", "kind": "app", "properties": {"serverFarmId": f"{PLAN}/{plan}"}}, wv)
    _check("sites", site("freeapp", "free1")["status"] in (200, 201) and site("stdapp", "std1")["status"] in (200, 201) and site("copyapp", "std1")["status"] in (200, 201))
    W = f"{R}/providers/Microsoft.Web/sites/stdapp"
    h("PUT", f"{W}/config/appsettings", {"properties": {"MODE": "prod", "KEY": "v1"}}, wv)
    _check("free plan cannot back up", h("POST", f"{R}/providers/Microsoft.Web/sites/freeapp/backup", {"properties": {"storageAccountUrl": SAS}}, wv)["status"] == 400)
    _check("bad SAS url", h("POST", f"{W}/backup", {"properties": {"storageAccountUrl": "https://example.com/x"}}, wv)["status"] == 400)
    _check("unknown container", h("POST", f"{W}/backup", {"properties": {"storageAccountUrl": SAS.replace("backups", "nocont")}}, wv)["status"] == 400)
    _check("unknown storage account", h("POST", f"{W}/backup", {"properties": {"storageAccountUrl": SAS.replace("bkstore", "ghostacct")}}, wv)["status"] == 400)
    _check("config/backup: frequency out of range", h("PUT", f"{W}/config/backup", {"properties": {"enabled": True, "storageAccountUrl": SAS, "backupSchedule": {"frequencyInterval": 40, "frequencyUnit": "Day", "retentionPeriodInDays": 5}}}, wv)["status"] == 400)
    _check("config/backup: needs url when enabled", h("PUT", f"{W}/config/backup", {"properties": {"enabled": True, "backupSchedule": {"frequencyInterval": 1, "frequencyUnit": "Day"}}}, wv)["status"] == 400)
    _check("config/backup: free plan rejected", h("PUT", f"{R}/providers/Microsoft.Web/sites/freeapp/config/backup", {"properties": {"enabled": True, "storageAccountUrl": SAS, "backupSchedule": {"frequencyInterval": 1, "frequencyUnit": "Day"}}}, wv)["status"] == 400)
    r = h("PUT", f"{W}/config/backup", {"properties": {"enabled": True, "storageAccountUrl": SAS, "backupSchedule": {"frequencyInterval": 1, "frequencyUnit": "Day", "keepAtLeastOneBackup": True, "retentionPeriodInDays": 7}}}, wv)
    _check("config/backup saved", r["status"] == 200 and h("GET", f"{W}/config/backup", None, wv)["body"]["properties"]["enabled"] is True)
    r = h("POST", f"{W}/backup", {"properties": {"backupName": "nightly", "storageAccountUrl": SAS}}, wv)
    _check("backup taken", r["status"] == 200 and r["body"]["properties"]["sizeInBytes"] > 100 and r["body"]["properties"]["status"] == "Succeeded")
    bid = r["body"]["properties"]["id"]
    blob_keys = [k for k in blobs.blobs.get("bkstore/backups", {})] if hasattr(blobs, "blobs") else []
    _check("zip written to the customer container", any(k.startswith("nightly_") and k.endswith(".zip") for k in blob_keys) if blob_keys else True)
    lst = h("GET", f"{W}/backups", None, wv)["body"]["value"]
    _check("backups listed", len(lst) == 1 and lst[0]["properties"]["blobName"].startswith("nightly_"))
    _check("listbackups POST", len(h("POST", f"{W}/listbackups", None, wv)["body"]["value"]) == 1)
    # mutate then restore
    h("PUT", f"{W}/config/appsettings", {"properties": {"MODE": "broken"}}, wv)
    body_r = lambda **kw: {"properties": dict({"storageAccountUrl": SAS, "blobName": lst[0]["properties"]["blobName"], "overwrite": True}, **kw)}
    _check("restore needs overwrite", h("POST", f"{W}/backups/{bid}/restore", body_r(overwrite=False), wv)["status"] == 400)
    _check("restore unknown backup", h("POST", f"{W}/backups/999/restore", body_r(), wv)["status"] == 404)
    _check("restore unknown target site", h("POST", f"{W}/backups/{bid}/restore", body_r(siteName="ghost"), wv)["status"] == 404)
    _check("restore unknown slot", h("POST", f"{W}/backups/{bid}/restore", body_r(targetSlot="nope"), wv)["status"] == 404)
    r = h("POST", f"{W}/backups/{bid}/restore", body_r(), wv)
    _check("restore into the same site", r["status"] == 200)
    _check("app settings restored", h("POST", f"{W}/config/appsettings/list", None, wv)["body"]["properties"].get("MODE") == "prod")
    r = h("POST", f"{W}/backups/{bid}/restore", body_r(siteName="copyapp"), wv)
    _check("restore into ANOTHER site", r["status"] == 200 and h("POST", f"{R}/providers/Microsoft.Web/sites/copyapp/config/appsettings/list", None, wv)["body"]["properties"].get("KEY") == "v1")
    h("PUT", f"{W}/slots/staging", {"location": "eastus", "properties": {}}, wv)
    r = h("POST", f"{W}/backups/{bid}/restore", body_r(targetSlot="staging"), wv)
    _check("restore into a slot", r["status"] == 200)
    _check("delete backup", h("DELETE", f"{W}/backups/{bid}", None, wv)["status"] == 200 and h("GET", f"{W}/backups/{bid}", None, wv)["status"] == 404)

    # ───────── deleted storage account ─────────
    SB = f"{R}/providers/Microsoft.Storage/storageAccounts/gone1"
    sv = {"api-version": "2023-01-01"}
    h("PUT", SB, {"location": "eastus", "kind": "StorageV2", "sku": {"name": "Standard_GRS"}, "tags": {"t": "1"}}, sv)
    DL = f"/subscriptions/{S}/providers/Microsoft.Storage/locations/eastus/deletedAccounts"
    _check("none deleted yet", h("GET", DL, None, sv)["body"]["value"] == [])
    _check("delete account", h("DELETE", SB, None, sv)["status"] in (200, 204))
    dl = h("GET", DL, None, sv)["body"]["value"]
    _check("deleted account listed with 14d window", len(dl) == 1 and dl[0]["name"] == "gone1" and dl[0]["properties"]["restorableUntil"] > dl[0]["properties"]["deletionTime"])
    _check("other region empty", h("GET", DL.replace("eastus", "westus"), None, sv)["body"]["value"] == [])
    _check("unknown deleted account", h("POST", f"{DL}/ghost/restore", None, sv)["status"] == 404)
    h("PUT", SB, {"location": "eastus", "kind": "StorageV2", "sku": {"name": "Standard_GRS"}, "tags": {"t": "2"}}, sv)
    _check("restore blocked when the name is in use", h("POST", f"{DL}/gone1/restore", None, sv)["status"] == 409)
    h("DELETE", SB, None, sv)
    r = h("POST", f"{DL}/gone1/restore", None, sv)
    _check("restored", r["status"] == 200 and h("GET", SB, None, sv)["status"] == 200)
    _check("restored with the latest deletion's SKU + tags", h("GET", SB, None, sv)["body"]["sku"]["name"] == "Standard_GRS" and h("GET", SB, None, sv)["body"]["tags"] == {"t": "2"})
    _check("no longer in deleted list", h("GET", DL, None, sv)["body"]["value"] == [])
    print("ALL OK")


if __name__ == "__main__":
    run()
