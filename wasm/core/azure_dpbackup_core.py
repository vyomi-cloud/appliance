# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Azure data-protection backups beyond VMs/files: AKS (Microsoft.DataProtection), Cosmos DB restore, App Service backups and
deleted storage account restore (Nano / dev_server / unified-ingress core, substrate-free; state in the flat ARM state map,
artifacts in the simulator's Blob store).

* ``Microsoft.DataProtection/backupVaults/{v}`` (+ ``backupPolicies``, ``backupInstances``, ``backupJobs``) for AKS clusters
  (datasourceType ``Microsoft.ContainerService/managedClusters``). A backup instance needs the cluster to exist in the vault's
  region, the backup extension (``microsoft.dataprotection.kubernetes``) installed on it, a policy whose schedule is one of the
  intervals AKS backup supports (4/6/8/12/24 h) with a ``Default`` retention rule, existing included namespaces and no namespace
  in both include and exclude. A backup takes a REAL snapshot of the cluster's Kubernetes object store
  (core/azure_aks_k8s_core.py: namespaces + every stored object, filtered by namespace / kind / label selector, Events never
  captured) written as a JSON artifact into the Blob store (account ``vyomidpbackup``); ``restore`` re-applies those objects into
  the same or another cluster with namespace mapping and ``Skip`` | ``Patch`` conflict policy.
* Cosmos DB: ``locations/{loc}/restorableDatabaseAccounts`` (live continuous-backup accounts AND deleted accounts, with the
  oldest restorable time derived from the Continuous7Days/30Days tier), ``restorableSqlDatabases`` / ``restorableSqlContainers`` /
  ``restorableSqlResources`` (a real timeline of database/container create+delete events kept on the ARM state), and account PUT
  with ``createMode: Restore`` + ``restoreParameters`` recreating the databases and containers that existed at the timestamp in a
  NEW account.
* App Service: ``config/backup`` (needs a Standard+ plan and a reachable blob container SAS URL), ``backup`` (a real ``.zip``
  containing site config, app settings, connection strings, slots and function code written to the customer container),
  ``backups`` / ``listbackups`` / ``backups/{id}/restore`` into the same site, a deployment slot or another site, and
  ``discoverbackup`` for a blob zip.
* Deleted storage accounts: ``locations/{loc}/deletedAccounts`` list/get and the restore action (14-day window, name must be free).

NOT modelled (honest limits): AKS PersistentVolume ``snapshotVolumes`` records the volumes in the artifact but Vyomi PVs hold no
block bytes, so a restore re-creates PV/PVC objects, not disk contents; nothing is scheduled by wall clock -- schedules/retention
are validated and stored, backups run on demand (``backup`` action) and expired recovery points are removed lazily on listing;
Cosmos restores recreate account metadata (databases, containers, throughput, indexing) but NOT documents, because the Cosmos data
plane is a single shared store with no per-account partition or write-ahead log; the App Service archive holds configuration and
function code, not a file-system image or databases (Vyomi sites have no content share); deleted storage accounts come back with
their configuration and the containers still present in the Blob store.
"""
from __future__ import annotations

import datetime
import io
import json
import re
import uuid
import zipfile

DP = "Microsoft.DataProtection"
VAULT_T = "microsoft.dataprotection/backupvaults"
ART_ACCOUNT = "vyomidpbackup"
AKS_T = "microsoft.containerservice/managedclusters"
AKS_DS = "Microsoft.ContainerService/managedClusters"
EXT_TYPE = "microsoft.dataprotection.kubernetes"
COSMOS_T = "microsoft.documentdb/databaseaccounts"
SITE_T = "microsoft.web/sites"
STORAGE_T = "microsoft.storage/storageaccounts"
BLOB_CONTAINER_T = "microsoft.storage/storageaccounts/blobservices/containers"
NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9\-]{1,49}$")
STORAGE_TYPES = ("LocallyRedundant", "GeoRedundant", "ZoneRedundant")
AKS_INTERVAL_HOURS = (4, 6, 8, 12, 24)
SKIP_KINDS = ("Event",)
SYSTEM_NS = ("kube-system", "kube-public", "kube-node-lease")
BLOB = {"store": None}            # set by AzureArm before each dispatch (the substrate's AzureBlobStore)


class _LazyBlob:
    def __getattr__(self, name):
        try:
            from core import azure_blob_core as m
        except ImportError:
            import azure_blob_core as m           # type: ignore
        return getattr(m, name)


_blob = _LazyBlob()


def _k8s():
    try:
        from core import azure_aks_k8s_core as m
    except ImportError:
        import azure_aks_k8s_core as m            # type: ignore
    return m


def _now(delta_days: float = 0, delta_s: float = 0):
    t = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=delta_days, seconds=delta_s)
    return t.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _parse_ts(s):
    if not isinstance(s, str):
        return None
    try:
        t = datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=datetime.timezone.utc)


def _err(status, code, msg):
    return {"status": status, "body": {"error": {"code": code, "message": msg}}}


def _ok(body, status=200):
    return {"status": status, "body": body}


def _view(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def _kids(state, parent_id, kind):
    pre = parent_id.lower() + "/" + kind + "/"
    return [r for k, r in state.items() if isinstance(r, dict) and k.startswith(pre) and "/" not in k[len(pre):]]


def _rg_of(rid):
    p = [x for x in rid.split("/") if x]
    low = [x.lower() for x in p]
    return p[low.index("resourcegroups") + 1] if "resourcegroups" in low else None


# ── artifacts ────────────────────────────────────────────────────────────────────────────
def _art_put(container, path, data, ctype="application/json"):
    bs = BLOB["store"]
    if isinstance(data, (dict, list)):
        data = json.dumps(data).encode()
    if bs is None:
        return None
    key = f"{ART_ACCOUNT}/{container}"
    if not bs.container_exists(key):
        bs.create_container(key)
    r = _blob.dispatch(bs, "PUT", f"/{container}/{path}", {}, {"x-ms-blob-type": "BlockBlob", "content-type": ctype}, data, account=ART_ACCOUNT)
    return None if r.status >= 300 else {"container": container, "path": path, "account": ART_ACCOUNT}


def _art_get(art):
    bs = BLOB["store"]
    if not art or bs is None:
        return None
    r = _blob.dispatch(bs, "GET", f"/{art['container']}/{art['path']}", {}, {}, b"", account=art.get("account") or ART_ACCOUNT)
    return r.body if r.status == 200 else None


def _art_del(art):
    bs = BLOB["store"]
    if art and bs is not None:
        _blob.dispatch(bs, "DELETE", f"/{art['container']}/{art['path']}", {}, {}, b"", account=art.get("account") or ART_ACCOUNT)


# ═══════════════════════════ Microsoft.DataProtection (AKS) ═══════════════════════════════
def handles(namespace, chain=None):
    n = namespace.lower()
    if n == "microsoft.dataprotection":
        return True
    c = [x.lower() for x in (chain or [])]
    if n == "microsoft.documentdb" and len(c) >= 3 and c[0] == "locations" and c[2] == "restorabledatabaseaccounts":
        return True
    if n == "microsoft.storage" and len(c) >= 3 and c[0] == "locations" and c[2] == "deletedaccounts":
        return True
    return False


def dispatch(state, method, sub, rg, namespace, chain, payload, query, arm_put=None, arm_get=None):
    n = namespace.lower()
    if n == "microsoft.documentdb":
        return cosmos_locations(state, method, sub, chain, payload)
    if n == "microsoft.storage":
        return deleted_accounts(state, method, sub, chain, payload, arm_put)
    return _dp(state, method, sub, rg, chain, payload, query)


def _dp(state, method, sub, rg, chain, payload, query):
    if not chain or chain[0].lower() != "backupvaults":
        return _err(404, "ResourceTypeNotSupported", "Unknown Microsoft.DataProtection resource type.")
    if len(chain) == 1:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        return _ok({"value": [_view(r) for r in state.values() if isinstance(r, dict) and r.get("_type") == VAULT_T and r.get("_sub") == sub
                              and (rg is None or (r.get("_rg") or "").lower() == rg.lower())]})
    if rg is None:
        return _err(400, "InvalidRequest", "A backup vault path needs a resource group.")
    vid = f"/subscriptions/{sub}/resourceGroups/{rg}/providers/{DP}/backupVaults/{chain[1]}"
    vault = state.get(vid.lower())
    if len(chain) == 2:
        return _vault(state, method, sub, rg, chain[1], vid, vault, payload)
    if vault is None:
        return _err(404, "ResourceNotFound", f"The Resource '{DP}/backupVaults/{chain[1]}' under resource group '{rg}' was not found.")
    k = chain[2].lower()
    if k == "backuppolicies":
        return _policies(state, method, vault, chain[3:], payload)
    if k == "backupinstances":
        return _instances(state, method, sub, vault, chain[3:], payload, query)
    if k == "backupjobs":
        jobs = sorted(_kids(state, vault["id"], "backupjobs"), key=lambda j: j["properties"]["startTime"], reverse=True)
        if len(chain) == 3:
            return _ok({"value": [_view(j) for j in jobs]})
        j = state.get(f"{vault['id']}/backupJobs/{chain[3]}".lower())
        return _ok(_view(j)) if j else _err(404, "ResourceNotFound", f"The job '{chain[3]}' was not found.")
    return _err(404, "ResourceNotFound", f"Unknown backup vault operation '{'/'.join(chain[2:])}'.")


def _vault(state, method, sub, rg, name, vid, rec, payload):
    if method == "GET":
        return _ok(_view(rec)) if rec else _err(404, "ResourceNotFound", f"The Resource '{DP}/backupVaults/{name}' under resource group '{rg}' was not found.")
    if method == "DELETE":
        if rec is None:
            return _ok(None, 204)
        if _kids_deep(state, vid, "backupinstances"):
            return _err(409, "UserErrorVaultHasBackupInstances", f"The vault '{name}' cannot be deleted while it has backup instances; stop protection and delete them first.")
        for k in [k for k in state if k.startswith(vid.lower() + "/")]:
            state.pop(k, None)
        state.pop(vid.lower(), None)
        return _ok(None, 200)
    if method not in ("PUT", "PATCH"):
        return _err(405, "MethodNotAllowed", f"{method} is not supported on a backup vault.")
    p = (payload or {}).get("properties") or {}
    if rec is None:
        if method == "PATCH":
            return _err(404, "ResourceNotFound", f"The Resource '{DP}/backupVaults/{name}' under resource group '{rg}' was not found.")
        if not NAME_RE.match(name):
            return _err(400, "InvalidResourceName", "A backup vault name is 2-50 characters: letters, digits and hyphens, starting with a letter.")
        if not (payload or {}).get("location"):
            return _err(400, "LocationRequired", "The location property is required for a backup vault.")
    ss = p.get("storageSettings")
    if ss is not None:
        if not isinstance(ss, list) or not ss or any(s.get("datastoreType") != "VaultStore" or s.get("type") not in STORAGE_TYPES for s in ss):
            return _err(400, "UserErrorInvalidStorageSettings", f"storageSettings must be [{{datastoreType: VaultStore, type: one of {', '.join(STORAGE_TYPES)}}}].")
        if rec and rec["properties"].get("storageSettings") != ss and _kids_deep(state, vid, "backupinstances"):
            return _err(400, "UserErrorStorageRedundancyLocked", "Storage redundancy cannot change once a backup instance has been protected.")
    if rec is None:
        rec = {"id": vid, "name": name, "type": f"{DP}/backupVaults", "location": payload["location"], "tags": dict(payload.get("tags") or {}),
               "identity": payload.get("identity") or {"type": "SystemAssigned", "principalId": str(uuid.uuid4()), "tenantId": "00000000-0000-0000-0000-000000000000"},
               "properties": {"provisioningState": "Succeeded", "storageSettings": ss or [{"datastoreType": "VaultStore", "type": "GeoRedundant"}],
                              "isVaultProtectedByResourceGuard": False, "securitySettings": {"softDeleteSettings": {"state": "On", "retentionDurationInDays": 14}}},
               "_type": VAULT_T, "_sub": sub, "_rg": rg, "_created": _now()}
        state[vid.lower()] = rec
        _seed_policies(state, rec)
        return _ok(_view(rec), 201)
    if ss is not None:
        rec["properties"]["storageSettings"] = ss
    sd = (p.get("securitySettings") or {}).get("softDeleteSettings")
    if sd:
        if sd.get("state") not in ("On", "Off", "AlwaysOn"):
            return _err(400, "UserErrorInvalidSoftDelete", "softDeleteSettings.state must be On, Off or AlwaysOn.")
        if rec["properties"]["securitySettings"]["softDeleteSettings"]["state"] == "AlwaysOn" and sd["state"] != "AlwaysOn":
            return _err(400, "UserErrorSoftDeleteAlwaysOn", "Soft delete is AlwaysOn and cannot be relaxed.")
        rec["properties"]["securitySettings"]["softDeleteSettings"].update(sd)
    if payload.get("tags") is not None:
        rec["tags"] = dict(payload["tags"])
    return _ok(_view(rec))


def _kids_deep(state, vid, kind):
    return _kids(state, vid, kind)


def _iso_dur(d):
    m = re.fullmatch(r"P(\d+)([DWMY])", str(d or ""))
    return (int(m.group(1)), m.group(2)) if m else None


def _dur_days(d):
    n, u = _iso_dur(d)
    return n * {"D": 1, "W": 7, "M": 30, "Y": 365}[u]


def _seed_policies(state, vault):
    pol = default_aks_policy(vault)
    state[pol["id"].lower()] = pol


def default_aks_policy(vault):
    return {"id": f"{vault['id']}/backupPolicies/aks-default", "name": "aks-default", "type": f"{DP}/backupVaults/backupPolicies",
            "properties": {"objectType": "BackupPolicy", "datasourceTypes": [AKS_DS], "policyRules": [
                {"objectType": "AzureBackupRule", "name": "BackupDaily", "backupParameters": {"objectType": "AzureBackupParams", "backupType": "Incremental"},
                 "dataStore": {"dataStoreType": "OperationalStore", "objectType": "DataStoreInfoBase"},
                 "trigger": {"objectType": "ScheduleBasedTriggerContext", "schedule": {"repeatingTimeIntervals": ["R/2026-01-01T02:00:00+00:00/PT24H"]},
                             "taggingCriteria": [{"isDefault": True, "taggingPriority": 99, "tagInfo": {"tagName": "Default"}}]}},
                {"objectType": "AzureRetentionRule", "name": "Default", "isDefault": True,
                 "lifecycles": [{"deleteAfter": {"objectType": "AbsoluteDeleteOption", "duration": "P7D"},
                                 "sourceDataStore": {"dataStoreType": "OperationalStore", "objectType": "DataStoreInfoBase"}}]}]},
            "_kind": "policy"}


def _validate_policy(p):
    rules = p.get("policyRules")
    if p.get("objectType") != "BackupPolicy":
        return "properties.objectType must be 'BackupPolicy'."
    if p.get("datasourceTypes") != [AKS_DS]:
        return f"datasourceTypes must be ['{AKS_DS}'] -- only AKS backup policies are modelled by this engine."
    if not isinstance(rules, list) or not rules:
        return "policyRules must contain at least one AzureBackupRule and the Default AzureRetentionRule."
    names = [r.get("name") for r in rules]
    if len(set(names)) != len(names):
        return "policyRules names must be unique."
    ret = [r for r in rules if r.get("objectType") == "AzureRetentionRule"]
    bk = [r for r in rules if r.get("objectType") == "AzureBackupRule"]
    if not bk:
        return "A policy needs at least one AzureBackupRule."
    if not any(r.get("isDefault") and r.get("name") == "Default" for r in ret):
        return "A policy needs a retention rule named 'Default' with isDefault true."
    for r in ret:
        for lc in r.get("lifecycles") or []:
            d = (lc.get("deleteAfter") or {}).get("duration")
            if _iso_dur(d) is None:
                return f"Retention duration '{d}' is not a valid ISO-8601 duration (P7D, P4W, P3M, P1Y)."
            days = _dur_days(d)
            store = (lc.get("sourceDataStore") or {}).get("dataStoreType")
            if store == "OperationalStore" and not 1 <= days <= 360:
                return "Operational-tier retention must be between 1 and 360 days."
            if store not in ("OperationalStore", "VaultStore"):
                return "sourceDataStore.dataStoreType must be OperationalStore or VaultStore."
    for r in bk:
        if (r.get("backupParameters") or {}).get("backupType") not in ("Incremental", "Full"):
            return f"Backup rule '{r.get('name')}' needs backupParameters.backupType Incremental or Full."
        sched = ((r.get("trigger") or {}).get("schedule") or {}).get("repeatingTimeIntervals") or []
        if not sched:
            return f"Backup rule '{r.get('name')}' needs trigger.schedule.repeatingTimeIntervals."
        for iv in sched:
            m = re.fullmatch(r"R/(\d{4}-\d\d-\d\dT[\d:.]+(?:Z|[+-]\d\d:\d\d))/PT(\d+)H", iv) or re.fullmatch(r"R/(\d{4}-\d\d-\d\dT[\d:.]+(?:Z|[+-]\d\d:\d\d))/P(\d+)D", iv)
            if not m:
                return f"Schedule '{iv}' is not valid; use R/<start>/PT<n>H (hours) or R/<start>/P<n>D."
            n = int(m.group(2))
            ok = (n in AKS_INTERVAL_HOURS) if iv.endswith("H") else (n in (1, 7))
            if not ok:
                return f"AKS backup supports schedules every 4, 6, 8, 12 or 24 hours (or weekly, P7D); '{iv}' is not supported."
        for tc in (r.get("trigger") or {}).get("taggingCriteria") or []:
            if (tc.get("tagInfo") or {}).get("tagName") not in names + ["Default"]:
                return f"taggingCriteria tag '{(tc.get('tagInfo') or {}).get('tagName')}' has no matching retention rule."
    return None


def _policies(state, method, vault, rest, payload):
    base = f"{vault['id']}/backupPolicies"
    if not rest:
        return _ok({"value": [_view(r) for r in _kids(state, vault["id"], "backuppolicies")]}) if method == "GET" else _err(405, "MethodNotAllowed", "Collection supports GET only.")
    name = rest[0]
    key = f"{base}/{name}".lower()
    rec = state.get(key)
    if method == "GET":
        return _ok(_view(rec)) if rec else _err(404, "ResourceNotFound", f"The backup policy '{name}' was not found.")
    if method == "DELETE":
        if rec is None:
            return _ok(None, 204)
        users = [i["name"] for i in _kids(state, vault["id"], "backupinstances") if i["properties"]["policyInfo"]["policyId"].lower() == rec["id"].lower()]
        if users:
            return _err(409, "UserErrorPolicyInUse", f"The backup policy '{name}' is used by backup instance(s) {', '.join(users)} and cannot be deleted.")
        state.pop(key, None)
        return _ok(None, 200)
    if method != "PUT":
        return _err(405, "MethodNotAllowed", f"{method} is not supported on a backup policy.")
    p = (payload or {}).get("properties") or {}
    bad = _validate_policy(p)
    if bad:
        return _err(400, "UserErrorInvalidBackupPolicy", bad)
    new = {"id": f"{base}/{name}", "name": name, "type": f"{DP}/backupVaults/backupPolicies", "properties": p, "_kind": "policy"}
    state[key] = new
    return _ok(_view(new), 200 if rec else 201)


def _ns_names(cluster):
    return [n.get("name") for n in (cluster.get("properties") or {}).get("namespaces") or []] or ["default", "kube-system"]


def _extension_ok(state, cluster):
    pre = cluster["id"].lower() + "/providers/microsoft.kubernetesconfiguration/extensions/"
    return any(k.startswith(pre) and str((r.get("properties") or {}).get("extensionType", "")).lower() == EXT_TYPE
               and (r.get("properties") or {}).get("provisioningState", "Succeeded") == "Succeeded" for k, r in state.items() if isinstance(r, dict))


def _params(p):
    lst = p.get("backupDatasourceParametersList") or []
    if not lst:
        return {"includedNamespaces": [], "excludedNamespaces": [], "includedResourceTypes": [], "excludedResourceTypes": [],
                "labelSelectors": [], "snapshotVolumes": True, "includeClusterScopeResources": True, "objectType": "KubernetesClusterBackupDatasourceParameters"}
    d = dict(lst[0])
    d.setdefault("objectType", "KubernetesClusterBackupDatasourceParameters")
    for k in ("includedNamespaces", "excludedNamespaces", "includedResourceTypes", "excludedResourceTypes", "labelSelectors"):
        d.setdefault(k, [])
    d.setdefault("snapshotVolumes", True)
    d.setdefault("includeClusterScopeResources", True)
    return d


def _instances(state, method, sub, vault, rest, payload, query):
    vid = vault["id"]
    if not rest:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        return _ok({"value": [_view(r) for r in _kids(state, vid, "backupinstances")]})
    name = rest[0]
    iid = f"{vid}/backupInstances/{name}"
    rec = state.get(iid.lower())
    tail = [t.lower() for t in rest[1:]]
    if not tail:
        return _instance_crud(state, method, sub, vault, name, iid, rec, payload)
    if rec is None:
        return _err(404, "ResourceNotFound", f"The backup instance '{name}' was not found.")
    if tail == ["backup"] and method == "POST":
        return _adhoc_backup(state, vault, rec, payload)
    if tail == ["recoverypoints"] and method == "GET":
        _expire(state, vault, rec)
        return _ok({"value": [_view(r) for r in sorted(_kids(state, iid, "recoverypoints"), key=lambda x: x["properties"]["recoveryPointTime"], reverse=True)]})
    if len(tail) == 2 and tail[0] == "recoverypoints" and method in ("GET", "DELETE"):
        rp = state.get(f"{iid}/recoveryPoints/{rest[2]}".lower())
        if rp is None:
            return _err(404, "ResourceNotFound", f"The recovery point '{rest[2]}' was not found.")
        if method == "GET":
            return _ok(_view(rp))
        return _err(400, "UserErrorRecoveryPointDeleteNotAllowed", "A recovery point cannot be deleted directly; it expires with the policy retention.")
    if tail in (["validateforrestore"], ["restore"]) and method == "POST":
        return _restore(state, sub, vault, rec, payload, validate_only=tail[0] == "validateforrestore")
    if tail in (["suspendbackups"], ["resumebackups"], ["stopprotection"], ["resumeprotection"]) and method == "POST":
        st = rec["properties"]
        if tail[0] == "suspendbackups":
            st["currentProtectionState"] = "BackupSchedulesSuspended"
        elif tail[0] == "stopprotection":
            st["currentProtectionState"] = "ProtectionStopped"
        else:
            if st["currentProtectionState"] not in ("BackupSchedulesSuspended", "ProtectionStopped"):
                return _err(400, "UserErrorNotSuspended", f"Protection is '{st['currentProtectionState']}'; there is nothing to resume.")
            st["currentProtectionState"] = "ProtectionConfigured"
        _job(state, vault, rec, tail[0], "Completed")
        return _ok(None, 202)
    if tail == ["validateforbackup"] and method == "POST":
        return _ok({"objectType": "OperationJobExtendedInfo", "jobId": None})
    return _err(404, "ResourceNotFound", f"Unknown backup instance operation '{'/'.join(rest[1:])}'.")


def _instance_crud(state, method, sub, vault, name, iid, rec, payload):
    if method == "GET":
        return _ok(_view(rec)) if rec else _err(404, "ResourceNotFound", f"The backup instance '{name}' was not found.")
    if method == "DELETE":
        if rec is None:
            return _ok(None, 204)
        for rp in _kids(state, iid, "recoverypoints"):
            _art_del(rp.get("_artifact"))
        for k in [k for k in state if k.startswith(iid.lower() + "/")]:
            state.pop(k, None)
        state.pop(iid.lower(), None)
        _job(state, vault, rec, "DeleteBackupInstance", "Completed")
        return _ok(None, 200)
    if method != "PUT":
        return _err(405, "MethodNotAllowed", f"{method} is not supported on a backup instance.")
    p = (payload or {}).get("properties") or {}
    if p.get("objectType") != "BackupInstance":
        return _err(400, "UserErrorInvalidObjectType", "properties.objectType must be 'BackupInstance'.")
    di = p.get("dataSourceInfo") or {}
    if di.get("datasourceType") != AKS_DS:
        return _err(400, "UserErrorUnsupportedDatasourceType", f"datasourceType '{di.get('datasourceType')}' is not supported; this engine protects '{AKS_DS}'.")
    cluster = state.get(str(di.get("resourceID") or "").lower())
    if cluster is None or (cluster.get("_type") or "").lower() != AKS_T:
        return _err(404, "UserErrorDatasourceNotFound", f"The datasource '{di.get('resourceID')}' was not found.")
    if str(cluster.get("location", "")).lower().replace(" ", "") != str(vault.get("location", "")).lower().replace(" ", ""):
        return _err(400, "UserErrorDatasourceLocationMismatch", f"The cluster is in '{cluster.get('location')}' but the vault is in '{vault.get('location')}'; AKS backup is same-region only.")
    pid = str((p.get("policyInfo") or {}).get("policyId") or "")
    pol = state.get(pid.lower())
    if pol is None or pol.get("_kind") != "policy" or not pid.lower().startswith(vault["id"].lower() + "/backuppolicies/"):
        return _err(404, "UserErrorPolicyNotFound", f"The backup policy '{pid}' was not found in vault '{vault['name']}'.")
    if not _extension_ok(state, cluster):
        return _err(400, "UserErrorBackupExtensionNotInstalled",
                    f"The AKS backup extension ({EXT_TYPE}) is not installed on cluster '{cluster['name']}'. Install it (Backup blade > Install extension) before configuring protection.")
    prm = _params(p.get("policyInfo", {}).get("policyParameters") or {})
    ns = set(_ns_names(cluster))
    for n in prm["includedNamespaces"] + prm["excludedNamespaces"]:
        if n not in ns:
            return _err(400, "UserErrorInvalidNamespace", f"Namespace '{n}' does not exist on cluster '{cluster['name']}'.")
    both = set(prm["includedNamespaces"]) & set(prm["excludedNamespaces"])
    if both:
        return _err(400, "UserErrorNamespaceConflict", f"Namespace(s) {', '.join(sorted(both))} are in both includedNamespaces and excludedNamespaces.")
    for sel in prm["labelSelectors"]:
        if not re.fullmatch(r"[\w./-]+=[\w./-]*", str(sel)):
            return _err(400, "UserErrorInvalidLabelSelector", f"Label selector '{sel}' must be key=value.")
    for r2 in state.values():
        if isinstance(r2, dict) and r2.get("_kind") == "dpinstance" and r2["properties"]["dataSourceInfo"]["resourceID"].lower() == cluster["id"].lower() \
                and r2["id"].lower() != iid.lower():
            return _err(409, "UserErrorDatasourceAlreadyProtected", f"Cluster '{cluster['name']}' is already protected by backup instance '{r2['name']}'.")
    props = {"friendlyName": p.get("friendlyName") or f"{cluster['name']}", "objectType": "BackupInstance",
             "dataSourceInfo": {"objectType": "Datasource", "resourceID": cluster["id"], "resourceName": cluster["name"], "resourceType": AKS_DS,
                                "resourceUri": cluster["id"], "resourceLocation": cluster.get("location"), "datasourceType": AKS_DS},
             "policyInfo": {"policyId": pol["id"], "policyParameters": {"backupDatasourceParametersList": [prm]}},
             "currentProtectionState": (rec or {}).get("properties", {}).get("currentProtectionState", "ProtectionConfigured"),
             "protectionStatus": {"status": "ProtectionConfigured"}, "provisioningState": "Succeeded"}
    new = {"id": iid, "name": name, "type": f"{DP}/backupVaults/backupInstances", "properties": props, "_kind": "dpinstance", "_sub": sub}
    state[iid.lower()] = new
    if rec is None:
        _job(state, vault, new, "ConfigureBackup", "Completed")
    return _ok(_view(new), 200 if rec else 201)


def _job(state, vault, inst, operation, status, extra=None, error=None):
    jid = str(uuid.uuid4())
    t = _now()
    props = {"activityID": str(uuid.uuid4()), "backupInstanceFriendlyName": inst["properties"]["friendlyName"], "backupInstanceId": inst["id"],
             "dataSourceId": inst["properties"]["dataSourceInfo"]["resourceID"], "dataSourceName": inst["properties"]["dataSourceInfo"]["resourceName"],
             "dataSourceType": AKS_DS, "dataSourceLocation": inst["properties"]["dataSourceInfo"]["resourceLocation"],
             "operation": operation, "status": status, "startTime": t, "endTime": t, "isUserTriggered": True,
             "policyName": inst["properties"]["policyInfo"]["policyId"].rsplit("/", 1)[-1], "vaultName": vault["name"], "subscriptionId": vault["_sub"],
             "sourceResourceGroup": _rg_of(inst["id"]), "supportedActions": [], "extendedInfo": extra or {}}
    if error:
        props["errorDetails"] = [{"code": error[0], "message": error[1]}]
    rec = {"id": f"{vault['id']}/backupJobs/{jid}", "name": jid, "type": f"{DP}/backupVaults/backupJobs", "properties": props, "_kind": "dpjob"}
    state[rec["id"].lower()] = rec
    return rec


def _matches(obj, labels):
    ol = (obj.get("metadata") or {}).get("labels") or {}
    for sel in labels:
        k, _, v = str(sel).partition("=")
        if ol.get(k) != v:
            return False
    return True


def snapshot_cluster(cluster, prm):
    """Capture the cluster's stored Kubernetes objects subject to the datasource parameters."""
    k8s = _k8s()
    inc, exc = set(prm["includedNamespaces"]), set(prm["excludedNamespaces"])
    inc_t, exc_t = set(prm["includedResourceTypes"]), set(prm["excludedResourceTypes"])
    objs, nss = [], []
    for ns in (cluster.get("properties") or {}).get("namespaces") or []:
        n = ns.get("name")
        if (inc and n not in inc) or n in exc or n in SYSTEM_NS:
            continue
        nss.append({"name": n, "labels": dict(ns.get("labels") or {})})
    keep_ns = {n["name"] for n in nss}
    for o in k8s.export_objects(cluster):
        kind = o.get("kind")
        if kind == "Namespace" or kind in SKIP_KINDS:
            continue
        mdn = (o.get("metadata") or {}).get("namespace")
        if mdn is None:
            if not prm["includeClusterScopeResources"] and inc:
                continue
            if inc and not prm["includeClusterScopeResources"]:
                continue
        elif mdn not in keep_ns:
            continue
        if inc_t and kind not in inc_t:
            continue
        if kind in exc_t:
            continue
        if not _matches(o, prm["labelSelectors"]):
            continue
        objs.append(o)
    pvs = [o["metadata"]["name"] for o in objs if o["kind"] == "PersistentVolume"]
    return {"namespaces": nss, "objects": objs, "volumeSnapshots": ([{"persistentVolume": n, "snapshot": "metadata-only"} for n in pvs] if prm["snapshotVolumes"] else [])}


def _adhoc_backup(state, vault, inst, payload):
    st = inst["properties"]["currentProtectionState"]
    if st != "ProtectionConfigured":
        return _err(400, "UserErrorBackupNotAllowed", f"Backups cannot run while protection is '{st}'.")
    cluster = state.get(inst["properties"]["dataSourceInfo"]["resourceID"].lower())
    if cluster is None:
        _job(state, vault, inst, "OnDemandBackup", "Failed", error=("UserErrorDatasourceNotFound", "The AKS cluster no longer exists."))
        return _err(404, "UserErrorDatasourceNotFound", "The AKS cluster no longer exists.")
    opt = ((payload or {}).get("backupRuleOptions") or {})
    rule = opt.get("ruleName") or "BackupDaily"
    pol = state.get(inst["properties"]["policyInfo"]["policyId"].lower())
    rules = {r["name"]: r for r in (pol["properties"]["policyRules"] if pol else [])}
    if rule not in rules or rules[rule].get("objectType") != "AzureBackupRule":
        return _err(400, "UserErrorBackupRuleNotFound", f"The policy has no backup rule '{rule}'.")
    tag = ((opt.get("triggerOption") or {}).get("retentionTagOverride")) or "Default"
    ret = next((r for r in rules.values() if r.get("objectType") == "AzureRetentionRule" and r["name"] == tag), None)
    if ret is None:
        return _err(400, "UserErrorRetentionTagNotFound", f"The policy has no retention rule '{tag}'.")
    prm = inst["properties"]["policyInfo"]["policyParameters"]["backupDatasourceParametersList"][0]
    snap = snapshot_cluster(cluster, prm)
    rpid = uuid.uuid4().hex
    doc = {"kind": "aks", "cluster": cluster["name"], "clusterId": cluster["id"], "kubernetesVersion": (cluster.get("properties") or {}).get("kubernetesVersion"),
           "takenAt": _now(), "parameters": prm, **snap}
    art = _art_put("dp-" + re.sub(r"[^a-z0-9-]", "-", vault["name"].lower()), f"{inst['name']}/{rpid}.json", doc)
    days = _dur_days(ret["lifecycles"][0]["deleteAfter"]["duration"])
    counts = {}
    for o in snap["objects"]:
        counts[o["kind"]] = counts.get(o["kind"], 0) + 1
    rp = {"id": f"{inst['id']}/recoveryPoints/{rpid}", "name": rpid, "type": f"{DP}/backupVaults/backupInstances/recoveryPoints",
          "properties": {"objectType": "AzureBackupDiscreteRecoveryPoint", "recoveryPointTime": _now(), "recoveryPointType": "Full",
                         "friendlyName": f"{cluster['name']}-{rpid[:8]}", "policyName": pol["name"] if pol else None, "retentionTagName": tag,
                         "expiryTime": _now(days), "recoveryPointDataStoresDetails": [{"type": "Snapshot", "id": rpid, "creationTime": _now(), "expiryTime": _now(days)}],
                         "sizeBytes": len(json.dumps(doc)), "namespaceCount": len(snap["namespaces"]), "objectCounts": counts,
                         "artifact": (art or {}).get("path")},
          "_kind": "dprp", "_artifact": art, "_doc": None if art else doc}
    state[rp["id"].lower()] = rp
    _job(state, vault, inst, "Backup", "Completed", {"recoveryPointId": rpid, "objectCount": len(snap["objects"])})
    inst["properties"]["protectionStatus"] = {"status": "ProtectionConfigured", "lastBackupTime": rp["properties"]["recoveryPointTime"]}
    return _ok({"objectType": "OperationJobExtendedInfo", "jobId": state_job_id(state, vault), "recoveryPointId": rpid}, 202)


def state_job_id(state, vault):
    js = sorted(_kids(state, vault["id"], "backupjobs"), key=lambda j: j["properties"]["startTime"])
    return js[-1]["name"] if js else None


def _expire(state, vault, inst):
    now = _parse_ts(_now())
    for rp in _kids(state, inst["id"], "recoverypoints"):
        t = _parse_ts(rp["properties"].get("expiryTime"))
        if t and t < now:
            _art_del(rp.get("_artifact"))
            state.pop(rp["id"].lower(), None)


def _restore(state, sub, vault, inst, payload, validate_only=False):
    pl = (payload or {}).get("restoreRequestObject") or payload or {}
    rpid = pl.get("recoveryPointId")
    rp = state.get(f"{inst['id']}/recoveryPoints/{rpid}".lower()) if rpid else None
    if pl.get("objectType") != "AzureBackupRecoveryPointBasedRestoreRequest":
        return _err(400, "UserErrorInvalidRestoreRequest", "restoreRequestObject.objectType must be AzureBackupRecoveryPointBasedRestoreRequest.")
    if rp is None:
        return _err(404, "UserErrorRecoveryPointNotFound", f"The recovery point '{rpid}' was not found.")
    tgt = pl.get("restoreTargetInfo") or {}
    if tgt.get("objectType") != "RestoreTargetInfo":
        return _err(400, "UserErrorInvalidRestoreTarget", "restoreTargetInfo.objectType must be RestoreTargetInfo.")
    if tgt.get("recoveryOption") != "FailIfExists":
        return _err(400, "UserErrorInvalidRecoveryOption", "recoveryOption must be FailIfExists (AKS backup restores into a target cluster; conflicts are resolved by conflictPolicy).")
    target = state.get(str((tgt.get("datasourceInfo") or {}).get("resourceID") or "").lower())
    if target is None or (target.get("_type") or "").lower() != AKS_T:
        return _err(404, "UserErrorTargetClusterNotFound", "The target AKS cluster was not found.")
    if str(target.get("location", "")).lower() != str(vault.get("location", "")).lower():
        return _err(400, "UserErrorTargetLocationMismatch", f"The target cluster is in '{target.get('location')}' but the vault is in '{vault.get('location')}'.")
    if not _extension_ok(state, target):
        return _err(400, "UserErrorBackupExtensionNotInstalled", f"The backup extension is not installed on target cluster '{target['name']}'.")
    crit = (tgt.get("restoreCriteria") or [{}])[0]
    policy = crit.get("conflictPolicy", "Skip")
    if policy not in ("Skip", "Patch"):
        return _err(400, "UserErrorInvalidConflictPolicy", "conflictPolicy must be Skip or Patch.")
    mode = crit.get("persistentVolumeRestoreMode", "RestoreWithVolumeData")
    if mode not in ("RestoreWithVolumeData", "RestoreWithoutVolumeData"):
        return _err(400, "UserErrorInvalidVolumeMode", "persistentVolumeRestoreMode must be RestoreWithVolumeData or RestoreWithoutVolumeData.")
    doc = rp.get("_doc") or json.loads(_art_get(rp.get("_artifact")) or "null")
    if not doc:
        return _err(500, "InternalError", "The recovery point artifact could not be read from the Blob store.")
    mapping = crit.get("namespaceMappings") or {}
    inc = set(crit.get("includedNamespaces") or [])
    exc = set(crit.get("excludedNamespaces") or [])
    inc_t, exc_t = set(crit.get("includedResourceTypes") or []), set(crit.get("excludedResourceTypes") or [])
    have = {n["name"] for n in doc["namespaces"]}
    for n in inc | exc | set(mapping):
        if n not in have:
            return _err(400, "UserErrorNamespaceNotInRecoveryPoint", f"Namespace '{n}' is not part of this recovery point.")
    plan = []
    for n in doc["namespaces"]:
        if (inc and n["name"] not in inc) or n["name"] in exc:
            continue
        plan.append(("ns", mapping.get(n["name"], n["name"]), n))
    kept = {p[2]["name"] for p in plan}
    for o in doc["objects"]:
        mdn = o["metadata"].get("namespace")
        if mdn is not None and mdn not in kept:
            continue
        if mdn is None and inc and not crit.get("includeClusterScopeResources", True):
            continue
        if (inc_t and o["kind"] not in inc_t) or o["kind"] in exc_t:
            continue
        if mode == "RestoreWithoutVolumeData" and o["kind"] in ("PersistentVolume", "PersistentVolumeClaim"):
            continue
        if not _matches(o, crit.get("labelSelectors") or []):
            continue
        plan.append(("obj", mapping.get(mdn, mdn), o))
    if validate_only:
        return _ok({"objectType": "OperationJobExtendedInfo", "validated": True, "objectsToRestore": sum(1 for p in plan if p[0] == "obj")})
    k8s = _k8s()
    existing_ns = {n.get("name") for n in (target.get("properties") or {}).get("namespaces") or []}
    created, skipped, patched, failed = [], [], [], []
    tprops = target.setdefault("properties", {})
    for kind, ns, item in plan:
        if kind == "ns":
            if ns not in existing_ns:
                tprops.setdefault("namespaces", []).append({"name": ns, "labels": item.get("labels") or {}})
                existing_ns.add(ns)
                created.append(f"namespace/{ns}")
            elif policy == "Patch":
                for n in tprops["namespaces"]:
                    if n.get("name") == ns:
                        n["labels"] = dict(item.get("labels") or {})
                patched.append(f"namespace/{ns}")
            else:
                skipped.append(f"namespace/{ns}")
    objs = [p for p in plan if p[0] == "obj"]
    ordered = sorted(objs, key=lambda p: 0 if p[2]["kind"] in ("StorageClass", "PersistentVolume", "CustomResourceDefinition") else 1)
    for _, ns, o in ordered:
        md = o["metadata"]
        name = md["name"]
        have_obj = [x for x in k8s.list_objects(target, o["kind"], ns if md.get("namespace") else None) if x["metadata"]["name"] == name]
        label = f"{o['kind'].lower()}/{name}"
        if have_obj and policy == "Skip":
            skipped.append(label)
            continue
        manifest = json.loads(json.dumps({k: v for k, v in o.items() if k != "status"}))
        for junk in ("uid", "resourceVersion", "creationTimestamp", "generation", "selfLink", "managedFields"):
            manifest["metadata"].pop(junk, None)
        if md.get("namespace"):
            manifest["metadata"]["namespace"] = ns
        try:
            k8s.apply_manifests(target, [manifest], default_ns=ns or "default")
            (patched if have_obj else created).append(label)
        except Exception as e:                      # one bad object does not abort the rest (Velero partial failure)
            failed.append(f"{label}: {e}")
    status = "Completed" if not failed else "CompletedWithWarnings"
    job = _job(state, vault, inst, "Restore", status, {"recoveryPointId": rpid, "created": created, "patched": patched, "skipped": skipped, "failed": failed,
                                                       "targetCluster": target["name"]})
    return _ok({"objectType": "OperationJobExtendedInfo", "jobId": job["name"], "created": len(created), "patched": len(patched),
                "skipped": len(skipped), "failed": failed}, 202)


# ═══════════════════════════ Cosmos DB: restorable accounts + restore ═════════════════════
def cosmos_tier_days(acct):
    bp = (acct.get("properties") or {}).get("backupPolicy") or {}
    return 30 if (bp.get("continuousModeProperties") or {}).get("tier") == "Continuous30Days" else 7


def _acct_instance(acct):
    return (acct.get("properties") or {}).get("instanceId") or str(uuid.uuid5(uuid.NAMESPACE_URL, acct["id"].lower()))


def cosmos_before_delete(state, rec):
    """Called with the account (or database/container) record right after it left the ARM state, BEFORE children cascade."""
    t = str(rec.get("_type", "")).lower()
    if t == COSMOS_T:
        bp = (rec.get("properties") or {}).get("backupPolicy") or {}
        if bp.get("type") != "Continuous":
            return
        dbs = []
        pre = rec["id"].lower() + "/"
        for k, r in list(state.items()):
            if isinstance(r, dict) and k.startswith(pre) and "/__event__/" not in k and str(r.get("_type", "")).lower() in (
                    COSMOS_T + "/sqldatabases", COSMOS_T + "/sqldatabases/containers", COSMOS_T + "/sqldatabases/containers/throughputsettings", COSMOS_T + "/sqldatabases/throughputsettings"):
                dbs.append(json.loads(json.dumps(_view_full(r))))
        state[f"/subscriptions/{rec.get('_sub')}/__cosmosdeleted__/{_acct_instance(rec)}".lower()] = {
            "_kind": "cosmos_deleted", "_s": rec.get("_sub"), "account": json.loads(json.dumps(_view_full(rec))), "children": dbs,
            "deletionTime": _now(), "instanceId": _acct_instance(rec)}
    elif t in (COSMOS_T + "/sqldatabases", COSMOS_T + "/sqldatabases/containers"):
        acct = rec["id"].lower().split("/sqldatabases/")[0]
        a = state.get(acct)
        if a is not None and ((a.get("properties") or {}).get("backupPolicy") or {}).get("type") == "Continuous":
            now = _now()
            for r in [rec] + [r for k, r in list(state.items()) if isinstance(r, dict) and k.startswith(rec["id"].lower() + "/") and "/__" not in k]:
                state[f"/subscriptions/{a.get('_sub')}/__cosmostomb__/{uuid.uuid4().hex}"] = {"_kind": "cosmos_tomb", "_acct": acct, "rid": r["id"], "deletedAt": now,
                                                                 "snapshot": json.loads(json.dumps(_view_full(r)))}


def _view_full(r):
    return {k: v for k, v in r.items() if not k.startswith("_") or k in ("_type", "_sub", "_rg", "_created")}


def _events_for(state, acct_low):
    ev = []
    for k, r in state.items():
        if isinstance(r, dict) and r.get("_kind") == "cosmos_tomb" and r["_acct"] == acct_low:
            ev.append(r)
    return ev


def _resources_at(state, acct, when):
    """Databases and containers that existed in ``acct`` at instant ``when`` (a datetime): live ones created before it, plus tombstoned ones
    deleted after it."""
    out = {}
    pre = acct["id"].lower() + "/"
    for k, r in state.items():
        if isinstance(r, dict) and k.startswith(pre) and str(r.get("_type", "")).lower() in (COSMOS_T + "/sqldatabases", COSMOS_T + "/sqldatabases/containers") \
                and "/__" not in k:
            c = _parse_ts(r.get("_created") or "") or _parse_ts("2000-01-01T00:00:00Z")
            if c <= when:
                out[k] = r
    for tb in _events_for(state, acct["id"].lower()):
        snap = tb["snapshot"]
        if str(snap.get("_type", "")).lower() not in (COSMOS_T + "/sqldatabases", COSMOS_T + "/sqldatabases/containers"):
            continue
        c = _parse_ts(snap.get("_created") or "") or _parse_ts("2000-01-01T00:00:00Z")
        if c <= when < _parse_ts(tb["deletedAt"]):
            out[snap["id"].lower()] = snap
    return out


def _restorable_view(sub, loc, iid, name, created, deleted, tier_days, apitype="Sql"):
    created_t = _parse_ts(created) or _parse_ts("2000-01-01T00:00:00Z")
    horizon = _parse_ts(_now(-tier_days))
    oldest = max(created_t, horizon) if not deleted else max(created_t, _parse_ts(deleted) - datetime.timedelta(days=tier_days))
    props = {"accountName": name, "apiType": apitype, "creationTime": created, "oldestRestorableTime": oldest.strftime("%Y-%m-%dT%H:%M:%SZ"),
             "restorableLocations": [{"locationName": loc.replace(" ", "").lower(), "regionalDatabaseAccountInstanceId": iid, "creationTime": created}]}
    if deleted:
        props["deletionTime"] = deleted
        props["restorableLocations"][0]["deletionTime"] = deleted
    return {"id": f"/subscriptions/{sub}/providers/Microsoft.DocumentDB/locations/{loc}/restorableDatabaseAccounts/{iid}", "name": iid,
            "type": "Microsoft.DocumentDB/locations/restorableDatabaseAccounts", "location": loc, "properties": props}


def restorable_accounts(state, sub, loc=None):
    out = []
    for k, r in state.items():
        if not isinstance(r, dict) or (r.get("_sub") or r.get("_s")) != sub:
            continue
        t = str(r.get("_type", "")).lower()
        if t == COSMOS_T and ((r.get("properties") or {}).get("backupPolicy") or {}).get("type") == "Continuous":
            l = str(r.get("location", "")).replace(" ", "").lower()
            if loc is None or l == loc.lower():
                out.append(_restorable_view(sub, l, _acct_instance(r), r["name"], r.get("_created") or _now(), None, cosmos_tier_days(r)))
        elif r.get("_kind") == "cosmos_deleted":
            a = r["account"]
            l = str(a.get("location", "")).replace(" ", "").lower()
            if loc is None or l == loc.lower():
                out.append(_restorable_view(sub, l, r["instanceId"], a["name"], a.get("_created") or _now(), r["deletionTime"], cosmos_tier_days(a)))
    return out


def _source_by_instance(state, sub, iid):
    for r in state.values():
        if not isinstance(r, dict) or (r.get("_sub") or r.get("_s")) != sub:
            continue
        if str(r.get("_type", "")).lower() == COSMOS_T and _acct_instance(r) == iid:
            return r, None
        if r.get("_kind") == "cosmos_deleted" and r["instanceId"] == iid:
            return r["account"], r
    return None, None


def cosmos_locations(state, method, sub, chain, payload):
    """.../providers/Microsoft.DocumentDB/locations/{loc}/restorableDatabaseAccounts[/{id}[/restorableSqlDatabases|restorableSqlContainers|restorableSqlResources]]"""
    if method != "GET":
        return _err(405, "MethodNotAllowed", "Restorable resources support GET only.")
    loc = chain[1]
    accts = restorable_accounts(state, sub, loc)
    if len(chain) == 3:
        return _ok({"value": accts})
    iid = chain[3]
    acct_view = next((a for a in accts if a["name"] == iid), None)
    if acct_view is None:
        return _err(404, "NotFound", f"The restorable database account '{iid}' was not found in '{loc}'.")
    if len(chain) == 4:
        return _ok(acct_view)
    src, dead = _source_by_instance(state, sub, iid)
    sub_kind = chain[4].lower()
    end = _parse_ts(dead["deletionTime"]) if dead else _parse_ts(_now())
    start = _parse_ts(acct_view["properties"]["oldestRestorableTime"])
    items = []
    if dead:
        pool = [(c, None) for c in dead["children"]]
    else:
        pool = [(r, None) for k, r in state.items() if isinstance(r, dict) and k.startswith(src["id"].lower() + "/") and "/__" not in k]
        pool += [(tb["snapshot"], tb["deletedAt"]) for tb in _events_for(state, src["id"].lower())
                 if str(tb["snapshot"].get("_type", "")).lower() in (COSMOS_T + "/sqldatabases", COSMOS_T + "/sqldatabases/containers")]
    for r, deleted in pool:
        t = str(r.get("_type", "")).lower()
        created = r.get("_created") or acct_view["properties"]["creationTime"]
        res = (r.get("properties") or {}).get("resource") or {}
        base = {"id": f"{acct_view['id']}/restorableSqlDatabases/{r['name']}" if t.endswith("sqldatabases") else f"{acct_view['id']}/restorableSqlContainers/{r['name']}",
                "name": r["name"], "properties": {"resource": {"_rid": res.get("_rid"), "operationType": "Create", "eventTimestamp": created,
                                                                "ownerId": res.get("id", r["name"]), "ownerResourceId": res.get("_rid")}}}
        if t.endswith("sqldatabases") and sub_kind in ("restorablesqldatabases", "restorablesqlresources"):
            base["properties"]["resource"]["database"] = {"id": res.get("id", r["name"])}
            if sub_kind == "restorablesqlresources":
                base = {"databaseName": r["name"], "collectionNames": [c["name"] for c, _ in pool if str(c.get("_type", "")).lower().endswith("containers") and "/sqldatabases/" + r["name"].lower() + "/" in c["id"].lower()]}
            items.append(base)
            if deleted:
                items.append({**base, "properties": {"resource": dict(base["properties"]["resource"], operationType="Delete", eventTimestamp=deleted)}} if sub_kind != "restorablesqlresources" else base)
        elif t.endswith("containers") and sub_kind == "restorablesqlcontainers":
            base["properties"]["resource"]["container"] = {"id": res.get("id", r["name"]), "partitionKey": res.get("partitionKey")}
            items.append(base)
    if sub_kind not in ("restorablesqldatabases", "restorablesqlcontainers", "restorablesqlresources"):
        return _err(404, "NotFound", f"Unknown restorable resource '{chain[4]}'.")
    return _ok({"value": items})


def cosmos_validate_restore(state, sub, rg, name, payload):
    """Account PUT with createMode Restore -> error response or None."""
    p = (payload or {}).get("properties") or {}
    if str(p.get("createMode") or "Default") != "Restore":
        return None
    rp = p.get("restoreParameters") or {}
    if rp.get("restoreSource") is None or not rp.get("restoreTimestampInUtc"):
        return _err(400, "BadRequest", "createMode Restore needs restoreParameters.restoreSource and restoreParameters.restoreTimestampInUtc.")
    if (p.get("backupPolicy") or {}).get("type") not in (None, "Continuous"):
        return _err(400, "BadRequest", "A restored account must use the Continuous backup policy.")
    m = re.search(r"/locations/([^/]+)/restorableDatabaseAccounts/([^/]+)$", str(rp["restoreSource"]), re.I)
    if not m:
        return _err(400, "BadRequest", "restoreSource must be /subscriptions/{sub}/providers/Microsoft.DocumentDB/locations/{loc}/restorableDatabaseAccounts/{instanceId}.")
    src, dead = _source_by_instance(state, sub, m.group(2))
    if src is None:
        return _err(404, "NotFound", f"The restorable database account '{m.group(2)}' was not found.")
    ts = _parse_ts(rp["restoreTimestampInUtc"])
    if ts is None:
        return _err(400, "BadRequest", "restoreTimestampInUtc must be an ISO-8601 UTC timestamp.")
    now = _parse_ts(_now())
    if ts > now:
        return _err(400, "BadRequest", "restoreTimestampInUtc cannot be in the future.")
    days = cosmos_tier_days(src)
    created = _parse_ts(src.get("_created") or "") or _parse_ts("2000-01-01T00:00:00Z")
    end = _parse_ts(dead["deletionTime"]) if dead else now
    oldest = max(created, end - datetime.timedelta(days=days))
    if ts < oldest or ts > end:
        return _err(400, "BadRequest", f"restoreTimestampInUtc must be between {oldest.strftime('%Y-%m-%dT%H:%M:%SZ')} (oldest restorable time, {days}-day tier) and {end.strftime('%Y-%m-%dT%H:%M:%SZ')}.")
    if not dead and name.lower() == str(src["name"]).lower():
        return _err(409, "BadRequest", "A live account cannot be restored over itself; restore into a new account name.")
    for d in rp.get("databasesToRestore") or []:
        if not d.get("databaseName"):
            return _err(400, "BadRequest", "databasesToRestore entries need databaseName.")
    return None


def cosmos_after_restore(state, sub, rg, rec, payload):
    """Recreate the databases/containers that existed at the restore timestamp inside the new account."""
    p = (payload or {}).get("properties") or {}
    if str(p.get("createMode") or "") != "Restore":
        return
    rp = p["restoreParameters"]
    iid = re.search(r"/restorableDatabaseAccounts/([^/]+)$", rp["restoreSource"], re.I).group(1)
    src, dead = _source_by_instance(state, sub, iid)
    ts = _parse_ts(rp["restoreTimestampInUtc"])
    if dead:
        pool = {}
        for c in dead["children"]:
            cr = _parse_ts(c.get("_created") or "") or _parse_ts("2000-01-01T00:00:00Z")
            if cr <= ts and "/throughputsettings" not in c["id"].lower() and str(c.get("_type", "")).lower() in (COSMOS_T + "/sqldatabases", COSMOS_T + "/sqldatabases/containers"):
                pool[c["id"].lower()] = c
        for tb in _events_for(state, dead["account"]["id"].lower()):
            sn = tb["snapshot"]
            cr = _parse_ts(sn.get("_created") or "") or _parse_ts("2000-01-01T00:00:00Z")
            if cr <= ts < _parse_ts(tb["deletedAt"]) and str(sn.get("_type", "")).lower() in (COSMOS_T + "/sqldatabases", COSMOS_T + "/sqldatabases/containers"):
                pool[sn["id"].lower()] = sn
        srcid = dead["account"]["id"]
    else:
        pool = dict(_resources_at(state, src, ts))
        srcid = src["id"]
    want = rp.get("databasesToRestore") or []
    wdb = {d["databaseName"]: set(d.get("collectionNames") or []) for d in want}
    restored = []
    for k, r in sorted(pool.items(), key=lambda kv: kv[0].count("/")):
        rel = r["id"][len(srcid):]
        parts = [x for x in rel.split("/") if x]
        dbname = parts[1] if len(parts) > 1 else None
        if wdb and dbname not in wdb:
            continue
        if wdb and len(parts) >= 4 and wdb[dbname] and parts[3] not in wdb[dbname]:
            continue
        nid = rec["id"] + rel
        new = json.loads(json.dumps({kk: vv for kk, vv in r.items() if not kk.startswith("_")}))
        new["id"] = nid
        new.update({"_type": r.get("_type") or ("microsoft.documentdb/databaseaccounts/sqldatabases" if len(parts) == 2 else "microsoft.documentdb/databaseaccounts/sqldatabases/containers"),
                    "_sub": sub, "_rg": rg, "_created": _now()})
        if "properties" in new and "resource" in new["properties"]:
            new["properties"]["resource"].pop("_rid", None)
        state[nid.lower()] = new
        restored.append(nid)
        # throughput settings of the source resource, if any
        tkey = (srcid + rel + "/throughputSettings/default").lower()
        tomb_t = next((tb["snapshot"] for tb in _events_for(state, srcid.lower()) if tb["snapshot"]["id"].lower() == tkey), None)
        if tkey in state or tomb_t or (dead and any(c["id"].lower() == tkey for c in dead["children"])):
            t = state.get(tkey) or tomb_t or next(c for c in dead["children"] if c["id"].lower() == tkey)
            nt = json.loads(json.dumps({kk: vv for kk, vv in t.items() if not kk.startswith("_")}))
            nt["id"] = nid + "/throughputSettings/default"
            nt["_type"] = t.get("_type") or new["_type"] + "/throughputSettings"
            nt["_sub"], nt["_rg"] = sub, rg
            state[nt["id"].lower()] = nt
    rec["_restore"] = {"source": rp["restoreSource"], "timestamp": rp["restoreTimestampInUtc"], "restoredResources": restored}
    rec.setdefault("properties", {})["restoreParameters"] = dict(rp, restoreSource=rp["restoreSource"])
    rec["properties"]["createMode"] = "Restore"


# ═══════════════════════════ deleted storage accounts ═══════════════════════════════════
def storage_before_delete(state, rec):
    if str(rec.get("_type", "")).lower() != STORAGE_T:
        return
    loc = str(rec.get("location", "")).replace(" ", "").lower()
    state[f"/subscriptions/{rec.get('_sub')}/locations/{loc}/deletedaccounts/{rec['name']}".lower()] = {
        "_kind": "deleted_storage", "_s": rec.get("_sub"), "_loc": loc, "name": rec["name"], "deletionTime": _now(),
        "account": json.loads(json.dumps(_view_full(rec))), "_blobs": sorted(_blob_containers(rec["name"]))}


def _blob_containers(acct):
    bs = BLOB["store"]
    out = []
    if bs is None:
        return out
    try:
        for c in getattr(bs, "containers", {}) or {}:
            if str(c).startswith(acct + "/"):
                out.append(str(c))
    except Exception:
        pass
    return out


def _deleted_view(d):
    a = d["account"]
    return {"id": f"/subscriptions/{d['_s']}/providers/Microsoft.Storage/locations/{d['_loc']}/deletedAccounts/{d['name']}", "name": d["name"],
            "type": "Microsoft.Storage/deletedAccounts",
            "properties": {"storageAccountResourceId": a["id"], "location": d["_loc"], "restoreReference": a["id"] + "/deleted", "creationTime": a.get("_created"),
                           "deletionTime": d["deletionTime"], "restorableUntil": _iso(_parse_ts(d["deletionTime"]) + datetime.timedelta(days=14)),
                           "sku": a.get("sku"), "kind": a.get("kind"), "containers": d["_blobs"]}}


def _iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def deleted_accounts(state, method, sub, chain, payload, arm_put):
    loc = chain[1].lower()
    rows = [r for r in state.values() if isinstance(r, dict) and r.get("_kind") == "deleted_storage" and r["_s"] == sub and r["_loc"] == loc]
    now = _parse_ts(_now())
    rows = [r for r in rows if _parse_ts(r["deletionTime"]) + datetime.timedelta(days=14) > now]
    if len(chain) == 3:
        return _ok({"value": [_deleted_view(r) for r in rows]}) if method == "GET" else _err(405, "MethodNotAllowed", "GET only.")
    d = next((r for r in rows if r["name"].lower() == chain[3].lower()), None)
    if d is None:
        return _err(404, "DeletedAccountNotFound", f"No deleted storage account '{chain[3]}' within its 14-day retention window exists in '{loc}'.")
    if len(chain) == 4:
        return _ok(_deleted_view(d)) if method == "GET" else _err(405, "MethodNotAllowed", "GET only.")
    if len(chain) == 5 and chain[4].lower() == "restore" and method == "POST":
        a = d["account"]
        if (state.get(a["id"].lower())) is not None:
            return _err(409, "StorageAccountAlreadyExists", f"A storage account named '{a['name']}' already exists; delete it before restoring the deleted one.")
        for r in state.values():
            if isinstance(r, dict) and str(r.get("_type", "")).lower() == STORAGE_T and r.get("name", "").lower() == a["name"].lower():
                return _err(409, "StorageAccountAlreadyTaken", f"The storage account name '{a['name']}' is already taken.")
        rg_id = a["id"].split("/providers/")[0]
        if rg_id.lower() not in state:
            return _err(404, "ResourceGroupNotFound", f"The original resource group '{_rg_of(a['id'])}' no longer exists; recreate it to restore the account.")
        body = {"location": a.get("location"), "sku": a.get("sku"), "kind": a.get("kind"), "tags": a.get("tags") or {},
                "properties": {k: v for k, v in (a.get("properties") or {}).items() if k in (
                    "accessTier", "allowBlobPublicAccess", "minimumTlsVersion", "supportsHttpsTrafficOnly", "allowSharedKeyAccess", "isHnsEnabled")}}
        r = arm_put(a["id"], "2023-01-01", body) if arm_put else _err(500, "InternalError", "no ARM writer")
        if r["status"] >= 300:
            return r
        state.pop(f"/subscriptions/{sub}/locations/{loc}/deletedaccounts/{d['name']}".lower(), None)
        new = state.get(a["id"].lower())
        if new is not None:
            new["_restored_from_deleted"] = d["deletionTime"]
        return _ok({"id": a["id"], "name": a["name"], "type": "Microsoft.Storage/storageAccounts", "restoredFromDeletionTime": d["deletionTime"],
                    "containersRetained": d["_blobs"]})
    return _err(404, "NotFound", "Unknown deleted account operation.")


# ═══════════════════════════ App Service backups ════════════════════════════════════════
DEFAULT_APP_BACKUP = {"enabled": False, "storageAccountUrl": "", "backupName": None,
                      "backupSchedule": {"frequencyInterval": 1, "frequencyUnit": "Day", "keepAtLeastOneBackup": True, "retentionPeriodInDays": 30}, "databases": []}


def _split_sas(url):
    m = re.fullmatch(r"https://([a-z0-9]{3,24})\.blob\.core\.windows\.net/([a-z0-9-]{3,63})/?\?(.+)", str(url or ""))
    return (m.group(1), m.group(2), m.group(3)) if m else None


def _check_container(state, url):
    parts = _split_sas(url)
    if not parts:
        return None, _err(400, "BadRequest", "storageAccountUrl must be a container SAS URL: https://{account}.blob.core.windows.net/{container}?{sas}.")
    acct, cont, sas = parts
    if "sig=" not in sas:
        return None, _err(400, "BadRequest", "storageAccountUrl SAS token has no signature (sig=).")
    if not any(isinstance(r, dict) and str(r.get("_type", "")).lower() == STORAGE_T and r.get("name", "").lower() == acct for r in state.values()):
        return None, _err(400, "BadRequest", f"The storage account '{acct}' referenced by storageAccountUrl does not exist.")
    bs = BLOB["store"]
    if bs is not None and not bs.container_exists(f"{acct}/{cont}"):
        arm_cont = any(isinstance(r, dict) and str(r.get("_type", "")).lower() == BLOB_CONTAINER_T and f"/storageaccounts/{acct}/" in k and k.endswith("/containers/" + cont)
                       for k, r in state.items())
        if not arm_cont:
            return None, _err(400, "BadRequest", f"The container '{cont}' does not exist in storage account '{acct}'.")
        bs.create_container(f"{acct}/{cont}")      # created through ARM: materialise it in the data plane on first use
    return (acct, cont), None


def _plan_tier(state, site):
    pid = str((site.get("properties") or {}).get("serverFarmId") or "").lower()
    plan = state.get(pid)
    return str(((plan or {}).get("sku") or {}).get("tier") or "").lower(), (plan or {}).get("sku", {}).get("name")


def app_config_backup(state, rec, method, payload):
    """PUT/PATCH sites/{s}/config/backup validation. Returns error response or None."""
    p = (payload or {}).get("properties") or {}
    cur = dict(rec.get("_backupconfig") or DEFAULT_APP_BACKUP)
    merged = {**cur, **p}
    merged["backupSchedule"] = {**(cur.get("backupSchedule") or {}), **(p.get("backupSchedule") or {})}
    if not merged.get("enabled") and "enabled" not in p and not p:
        return None
    tier, sku = _plan_tier(state, rec)
    if tier in ("free", "shared", "basic", "dynamic", "elasticpremium") and (merged.get("enabled") or p.get("storageAccountUrl")):
        return _err(400, "BadRequest", f"Backup and restore are available for Standard, Premium and Isolated App Service plans; the plan SKU '{sku or tier}' does not support it.")
    sch = merged.get("backupSchedule") or {}
    if merged.get("enabled"):
        if not merged.get("storageAccountUrl"):
            return _err(400, "BadRequest", "storageAccountUrl is required to enable backups.")
        if not isinstance(sch, dict) or not sch:
            return _err(400, "BadRequest", "backupSchedule is required when backups are enabled.")
    if merged.get("storageAccountUrl"):
        _, e = _check_container(state, merged["storageAccountUrl"])
        if e:
            return e
    if sch:
        unit = sch.get("frequencyUnit")
        iv = sch.get("frequencyInterval")
        if unit not in ("Day", "Hour"):
            return _err(400, "BadRequest", "backupSchedule.frequencyUnit must be Day or Hour.")
        if not isinstance(iv, int) or iv < 1 or (unit == "Day" and iv > 30) or (unit == "Hour" and iv > 23):
            return _err(400, "BadRequest", "backupSchedule.frequencyInterval must be 1-30 for Day or 1-23 for Hour.")
        ret = sch.get("retentionPeriodInDays", 30)
        if not isinstance(ret, int) or not 0 <= ret <= 9999:
            return _err(400, "BadRequest", "backupSchedule.retentionPeriodInDays must be 0-9999 (0 keeps backups indefinitely).")
        if sch.get("startTime") and _parse_ts(sch["startTime"]) is None:
            return _err(400, "BadRequest", "backupSchedule.startTime must be an ISO-8601 timestamp.")
    return None


def _site_content(rec):
    fns = {}
    for n, f in (rec.get("_functions") or {}).items():
        fns[n] = {"code": f.get("_code"), "config": (f.get("properties") or {}).get("config"), "entryPoint": f.get("_entry"), "isDisabled": (f.get("properties") or {}).get("isDisabled")}
    return {"siteConfig": (rec.get("properties") or {}).get("siteConfig") or {}, "appsettings": dict(rec.get("_appsettings") or {}),
            "connectionstrings": dict(rec.get("_connectionstrings") or {}), "functions": fns, "slots": json.loads(json.dumps(rec.get("_slots") or {})),
            "hostNames": (rec.get("properties") or {}).get("hostNames") or [], "kind": rec.get("kind")}


def _zip(entries):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for n, data in entries.items():
            z.writestr(n, data if isinstance(data, (bytes, str)) else json.dumps(data, indent=1))
    return buf.getvalue()


def app_take_backup(state, rec, payload, scheduled=False):
    p = (payload or {}).get("properties") or {}
    cfg = rec.get("_backupconfig") or DEFAULT_APP_BACKUP
    url = p.get("storageAccountUrl") or cfg.get("storageAccountUrl")
    if not url:
        return None, _err(400, "BadRequest", "storageAccountUrl is required: pass it in the request or configure it in config/backup.")
    target, e = _check_container(state, url)
    if e:
        return None, e
    tier, sku = _plan_tier(state, rec)
    if tier in ("free", "shared", "basic", "dynamic", "elasticpremium"):
        return None, _err(400, "BadRequest", f"Backup and restore are available for Standard, Premium and Isolated App Service plans; the plan SKU '{sku or tier}' does not support it.")
    if (rec.get("properties") or {}).get("state") == "Stopped":
        pass       # a stopped app can still be backed up (real behaviour)
    bname = p.get("backupName") or cfg.get("backupName") or f"{rec['name']}_{_now()[:19].replace('-', '').replace(':', '').replace('T', '')}"
    ts = _now()
    stamp = ts[:19].replace("-", "").replace(":", "").replace("T", "")
    blob = f"{bname}_{stamp}.zip"
    content = _site_content(rec)
    entries = {"siteconfig.json": content["siteConfig"], "appsettings.json": content["appsettings"], "connectionstrings.json": content["connectionstrings"],
               "slots.json": content["slots"], "metadata.json": {"site": rec["name"], "id": rec["id"], "kind": rec.get("kind"), "hostNames": content["hostNames"],
                                                                 "takenAt": ts, "databases": p.get("databases") or cfg.get("databases") or []}}
    for n, f in content["functions"].items():
        entries[f"site/wwwroot/{n}/function.json"] = f["config"] or {}
        entries[f"site/wwwroot/{n}/__init__.py"] = f["code"] or ""
    data = _zip(entries)
    acct, cont = target
    bs = BLOB["store"]
    if bs is not None:
        r = _blob.dispatch(bs, "PUT", f"/{cont}/{blob}", {}, {"x-ms-blob-type": "BlockBlob", "content-type": "application/zip"}, data, account=acct)
        if r.status >= 300:
            return None, _err(500, "InternalError", "Writing the backup to the container failed.")
    bid = uuid.uuid4().int % 100000 + 1
    while str(bid) in (rec.get("_backups") or {}):
        bid += 1
    b = {"id": str(bid), "name": blob, "status": "Succeeded", "created": ts, "finished": ts, "sizeInBytes": len(data), "storageAccountUrl": url.split("?")[0],
         "blobName": blob, "scheduled": scheduled, "log": f"Backup of '{rec['name']}' written to {acct}/{cont}/{blob}: {len(content['functions'])} function(s), "
                                                           f"{len(content['appsettings'])} app setting(s), {len(content['slots'])} slot(s).", "databases": p.get("databases") or cfg.get("databases") or []}
    rec.setdefault("_backups", {})[b["id"]] = b
    _prune_app(state, rec, cfg)
    return b, None


def _prune_app(state, rec, cfg):
    ret = ((cfg or {}).get("backupSchedule") or {}).get("retentionPeriodInDays", 30)
    if not ret:
        return
    now = _parse_ts(_now())
    keep_one = ((cfg or {}).get("backupSchedule") or {}).get("keepAtLeastOneBackup", True)
    items = sorted(rec["_backups"].values(), key=lambda x: x["created"])
    for i, b in enumerate(items):
        if keep_one and i == len(items) - 1:
            break
        if (now - _parse_ts(b["created"])).days >= ret:
            rec["_backups"].pop(b["id"], None)


def app_backup_view(rec_id, b):
    return {"id": f"{rec_id}/backups/{b['id']}", "name": b["name"], "type": "Microsoft.Web/sites/backups",
            "properties": {"id": int(b["id"]), "backupId": int(b["id"]), "storageAccountUrl": b.get("storageAccountUrl", ""), "blobName": b["blobName"],
                           "name": b["name"], "status": b["status"], "sizeInBytes": b["sizeInBytes"], "created": b["created"], "finishedTimeStamp": b["finished"],
                           "log": b.get("log", ""), "databases": b.get("databases", []), "scheduled": b.get("scheduled", False), "correlationId": str(uuid.uuid5(uuid.NAMESPACE_OID, b["id"] + rec_id)),
                           "websiteSizeInBytes": b["sizeInBytes"]}}


def app_restore(state, rec, b_or_blob, payload):
    """Restore a backup (record or blob discovered by name) into the same site, a slot, or another site. -> response"""
    p = (payload or {}).get("properties") or {}
    url = p.get("storageAccountUrl") or (b_or_blob or {}).get("storageAccountUrl")
    blob = p.get("blobName") or (b_or_blob or {}).get("blobName")
    # the container URL may arrive without SAS in a stored backup; the request must carry it
    full = p.get("storageAccountUrl") or ""
    if not _split_sas(full):
        cfg = rec.get("_backupconfig") or {}
        full = cfg.get("storageAccountUrl") or ""
    target, e = _check_container(state, full)
    if e:
        return e
    if not blob:
        return _err(400, "BadRequest", "blobName is required.")
    if p.get("overwrite") is not True:
        return _err(400, "BadRequest", "overwrite must be true: a restore replaces the target app's content and configuration.")
    acct, cont = target
    bs = BLOB["store"]
    raw = None
    if bs is not None:
        r = _blob.dispatch(bs, "GET", f"/{cont}/{blob}", {}, {}, b"", account=acct)
        if r.status != 200:
            return _err(404, "BackupNotFound", f"The backup blob '{blob}' was not found in container '{cont}'.")
        raw = r.body
    try:
        z = zipfile.ZipFile(io.BytesIO(raw)) if raw else None
        names = set(z.namelist()) if z else set()
        if "siteconfig.json" not in names or "metadata.json" not in names:
            raise ValueError("not a Vyomi/App Service backup archive")
        cfg = json.loads(z.read("siteconfig.json"))
        app = json.loads(z.read("appsettings.json"))
        conn = json.loads(z.read("connectionstrings.json"))
        slots = json.loads(z.read("slots.json"))
        funcs = {}
        for n in names:
            m = re.fullmatch(r"site/wwwroot/([^/]+)/function\.json", n)
            if m:
                funcs[m.group(1)] = (json.loads(z.read(n)), z.read(f"site/wwwroot/{m.group(1)}/__init__.py").decode() if f"site/wwwroot/{m.group(1)}/__init__.py" in names else "")
    except Exception as ex:
        return _err(400, "BadRequest", f"The blob is not a valid backup archive: {ex}")
    # target selection: another site (siteName), a slot (targetSlot) or this site
    tgt = rec
    tname = p.get("siteName")
    if tname and tname.lower() != rec["name"].lower():
        tgt = next((r for r in state.values() if isinstance(r, dict) and str(r.get("_type", "")).lower() == SITE_T and r.get("name", "").lower() == tname.lower()
                    and r.get("_sub") == rec.get("_sub") and (r.get("_rg") or "").lower() == (rec.get("_rg") or "").lower()), None)
        if tgt is None:
            return _err(404, "ResourceNotFound", f"The target site '{tname}' was not found in resource group '{rec.get('_rg')}'.")
    slot = p.get("targetSlot")
    if slot and slot.lower() != "production":
        sl = (tgt.get("_slots") or {}).get(slot)
        if sl is None:
            return _err(404, "ResourceNotFound", f"The deployment slot '{slot}' does not exist on site '{tgt['name']}'.")
        sl["siteConfig"], sl["appsettings"], sl["connectionstrings"] = cfg, app, conn
    else:
        tprops = tgt.setdefault("properties", {})
        tprops["siteConfig"] = {**(tprops.get("siteConfig") or {}), **cfg}
        tgt["_appsettings"], tgt["_connectionstrings"] = dict(app), dict(conn)
        if not p.get("ignoreConflictingHostNames"):
            pass
        fnrecs = tgt.setdefault("_functions", {})
        for n, (fcfg, code) in funcs.items():
            if n in fnrecs:
                fnrecs[n]["_code"] = code
                fnrecs[n].setdefault("properties", {})["config"] = fcfg
            else:
                fnrecs[n] = {"id": f"{tgt['id']}/functions/{n}", "name": n, "type": "Microsoft.Web/sites/functions",
                             "properties": {"config": fcfg, "language": "python", "isDisabled": False, "trigger": "httpTrigger"}, "_code": code, "_entry": "main",
                             "_invocations": 0, "_keys": {"default": uuid.uuid4().hex}}
    return _ok({"id": f"{tgt['id']}/restore", "name": "restore", "properties": {"status": "Succeeded", "restoredTo": tgt["name"], "slot": slot or "production",
                                                                               "functions": sorted(funcs), "appSettings": len(app), "connectionStrings": len(conn)}})


def app_ops(state, rec, rest, method, payload):
    """sites/{s}/backups[...] , listbackups, backup, discoverbackup. ``rest`` = tokens after the site name. -> response or None."""
    r0 = rest[0].lower()
    if r0 == "config":
        return None
    backups = rec.setdefault("_backups", {})
    if r0 == "backup" and method == "POST" and len(rest) == 1:
        b, e = app_take_backup(state, rec, payload)
        return e or _ok(app_backup_view(rec["id"], b))
    if r0 == "listbackups" and method == "POST":
        return _ok({"value": [app_backup_view(rec["id"], b) for b in reversed(list(backups.values()))]})
    if r0 == "discoverbackup" and method == "POST":
        p = (payload or {}).get("properties") or {}
        target, e = _check_container(state, p.get("storageAccountUrl"))
        if e:
            return e
        return _ok({"id": f"{rec['id']}/discoverbackup", "name": "discoverbackup", "properties": {"blobName": p.get("blobName"), "storageAccountUrl": p.get("storageAccountUrl", "").split("?")[0],
                                                                                                  "operationType": "Default", "overwrite": False}})
    if r0 != "backups":
        return None
    if len(rest) == 1:
        if method == "GET":
            return _ok({"value": [app_backup_view(rec["id"], b) for b in reversed(list(backups.values()))]})
        if method == "POST":
            b, e = app_take_backup(state, rec, payload)
            return e or _ok(app_backup_view(rec["id"], b))
        return _err(405, "MethodNotAllowed", "Collection supports GET/POST only.")
    b = backups.get(rest[1])
    if b is None:
        return _err(404, "NotFound", f"Backup '{rest[1]}' was not found.")
    if len(rest) == 2:
        if method == "GET":
            return _ok(app_backup_view(rec["id"], b))
        if method == "DELETE":
            parts = None
            if b.get("storageAccountUrl"):
                m = re.fullmatch(r"https://([a-z0-9]+)\.blob\.core\.windows\.net/([a-z0-9-]+)", b["storageAccountUrl"])
                if m and BLOB["store"] is not None:
                    _blob.dispatch(BLOB["store"], "DELETE", f"/{m.group(2)}/{b['blobName']}", {}, {}, b"", account=m.group(1))
            backups.pop(rest[1], None)
            return _ok(None, 200)
        return _err(405, "MethodNotAllowed", f"{method} not allowed.")
    if len(rest) == 3 and rest[2].lower() == "restore" and method == "POST":
        return app_restore(state, rec, b, payload)
    return _err(404, "ResourceTypeNotSupported", f"backups/{'/'.join(rest[1:])} is not supported.")


# ═══════════════════════════ VM boot diagnostics ═══════════════════════════════════════════
VM_T = "microsoft.compute/virtualmachines"
GUEST_LOG = {"fn": None}          # host-injected: fn(vm_record) -> str | None  (offline appliance: the container's real dmesg)


def _png(width=640, height=480, rgb=(24, 28, 36)):
    import struct
    import zlib
    raw = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))

    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def boot_diag_handles(namespace, chain):
    return namespace.lower() == "microsoft.compute" and len(chain) == 3 and chain[0].lower() == "virtualmachines" and chain[2].lower() == "retrievebootdiagnosticsdata"


def boot_diag(state, method, sub, rg, chain, query):
    """POST .../virtualMachines/{vm}/retrieveBootDiagnosticsData -> serial log + screenshot blob URIs (written to the vyomibootdiag account)."""
    if method != "POST":
        return _err(405, "MethodNotAllowed", "Use POST.")
    if rg is None:
        return _err(400, "InvalidRequest", "A VM path needs a resource group.")
    rid = f"/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Compute/virtualMachines/{chain[1]}"
    vm = state.get(rid.lower())
    if vm is None:
        return _err(404, "ResourceNotFound", f"The Resource 'Microsoft.Compute/virtualMachines/{chain[1]}' under resource group '{rg}' was not found.")
    bd = (((vm.get("properties") or {}).get("diagnosticsProfile") or {}).get("bootDiagnostics") or {})
    if not bd.get("enabled"):
        return _err(400, "BootDiagnosticsNotEnabled", f"Boot diagnostics is not enabled for virtual machine '{vm['name']}'. Enable it in Configuration or create the VM with diagnosticsProfile.bootDiagnostics.enabled.")
    sas_h = (query or {}).get("sasUriExpirationTimeInMinutes")
    if sas_h is not None and not (str(sas_h).isdigit() and 1 <= int(sas_h) <= 1440):
        return _err(400, "InvalidParameter", "sasUriExpirationTimeInMinutes must be between 1 and 1440.")
    vmid = (vm.get("properties") or {}).get("vmId") or str(uuid.uuid5(uuid.NAMESPACE_URL, vm["id"].lower()))
    guest = None
    try:
        guest = GUEST_LOG["fn"](vm) if GUEST_LOG["fn"] else None
    except Exception:
        guest = None
    state_txt = ((vm.get("properties") or {}).get("instanceView") or {}).get("powerState") or (vm.get("properties") or {}).get("provisioningState")
    if guest:
        log, source = guest, "guest"
    else:
        log = (f"[vyomi] Platform log for {vm['name']} (vmId {vmid})\n[vyomi] provisioningState={(vm.get('properties') or {}).get('provisioningState')} powerState={state_txt}\n"
               f"[vyomi] created {vm.get('_created') or 'unknown'}\n[vyomi] No guest console is reachable on this substrate; this file holds Vyomi's own lifecycle record, not the guest's serial output.\n")
        source = "platform"
    cont = f"bootdiagnostics-{re.sub(r'[^a-z0-9]', '', vm['name'].lower())[:10]}-{vmid}"
    art_log = _art_put_acct("vyomibootdiag", cont, f"{vm['name']}.{vmid}.serialconsole.log", log.encode(), "text/plain")
    art_png = _art_put_acct("vyomibootdiag", cont, f"{vm['name']}.{vmid}.screenshot.png", _png(), "image/png")
    exp = _now(0, int(sas_h or 60) * 60)
    base = f"https://vyomibootdiag.blob.core.windows.net/{cont}"
    sas = f"?sv=2022-11-02&se={exp[:19]}Z&sp=r&sig=vyomi"
    return _ok({"consoleScreenshotBlobUri": f"{base}/{vm['name']}.{vmid}.screenshot.png{sas}", "serialConsoleLogBlobUri": f"{base}/{vm['name']}.{vmid}.serialconsole.log{sas}",
                "properties": {"serialLogSource": source, "screenshotIsPlaceholder": True, "stored": bool(art_log and art_png)}})


def _art_put_acct(account, container, path, data, ctype):
    bs = BLOB["store"]
    if bs is None:
        return None
    key = f"{account}/{container}"
    if not bs.container_exists(key):
        bs.create_container(key)
    r = _blob.dispatch(bs, "PUT", f"/{container}/{path}", {}, {"x-ms-blob-type": "BlockBlob", "content-type": ctype}, data, account=account)
    return None if r.status >= 300 else {"container": container, "path": path, "account": account}
