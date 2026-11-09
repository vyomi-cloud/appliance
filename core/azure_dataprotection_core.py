"""Azure Backup for AKS (Microsoft.DataProtection) -- backup vaults, policies, backup instances, ad-hoc backup, recovery points,
restore and jobs for managed clusters (substrate-free; state lives in the flat ARM state map).

Resources under ``.../providers/Microsoft.DataProtection``:

* ``backupVaults/{v}`` (PUT/GET/DELETE, list at subscription / resource-group scope) -- storageSettings, system identity.
  Delete is blocked while backup instances exist.
* ``backupVaults/{v}/backupPolicies/{p}`` -- datasourceTypes must be ``Microsoft.ContainerService/managedClusters``; the rules are
  STORED (no scheduler runs them -- see limits). A policy in use cannot be deleted.
* ``backupVaults/{v}/backupInstances/{i}`` -- protects ONE managed cluster (``properties.dataSourceInfo.resourceID``); one instance
  per cluster per vault. ``/backup`` (ad-hoc backup), ``/validateRestore`` (+ alias ``/validateForRestore``), ``/restore``,
  ``/recoveryPoints[/{rp}]``.
* ``backupVaults/{v}/backupJobs[/{id}]`` and ``locations/{loc}/operationStatus|operationResults/{id}`` -- ad-hoc backup and restore are
  ASYNC: the POST answers 202 with the job id, the job is InProgress for ``JOB_SECONDS`` (wall clock), and completes lazily on the
  next read (any DataProtection request or AKS runCommand calls ``tick``).

What a backup is: at trigger time the cluster's user namespaces and their namespaced objects (Namespaces, Deployments, Pods, Services,
ConfigMaps, Secrets, ...; ``core/kube_state_core.py`` snapshot format) are serialised; when the job completes the document is written
as a JSON blob to the simulator's OWN Blob store (account ``vyomiaksbackup``, container ``aksbackup-{vault}``) and a recovery point
is recorded. A restore reads that blob and re-injects the objects into the cluster (server-side apply: missing objects come back,
existing ones are patched; original cluster or another managed cluster in the vault's subscription).

NOT modelled (honest limits): persistent-volume DATA and disk snapshots, CustomResourceDefinitions / custom resources, cluster-scoped
RBAC, the system namespaces; policy schedule/retention rules are stored but nothing runs scheduled backups or expires recovery
points; Pods are restored as objects only (Vyomi runs no kubelet, so they stay Pending); the Backup Extension / trusted-access
role assignments Azure requires are not enforced; cross-region restore and vault immutability are not modelled.
"""
from __future__ import annotations

import datetime
import json
import re
import time
import uuid

try:
    from core import kube_state_core as kube
    from core import azure_aks_k8s_core as k8s
except ImportError:                      # Pyodide flat layout
    import kube_state_core as kube       # type: ignore
    import azure_aks_k8s_core as k8s     # type: ignore

NS = "Microsoft.DataProtection"
AKS = "Microsoft.ContainerService/managedClusters"
VAULT_T = f"{NS}/backupVaults".lower()
ART_ACCOUNT = "vyomiaksbackup"
JOB_SECONDS = 3.0
NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9\-]{1,49}$")
REDUNDANCY = ("LocallyRedundant", "GeoRedundant", "ZoneRedundant")


class _LazyBlob:
    def __getattr__(self, name):
        try:
            from core import azure_blob_core as m
        except ImportError:
            import azure_blob_core as m           # type: ignore
        return getattr(m, name)


_blob = _LazyBlob()


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _err(status, code, msg):
    return {"status": status, "body": {"error": {"code": code, "message": msg}}}


def _ok(body, status=200, headers=None):
    r = {"status": status, "body": body}
    if headers:
        r["headers"] = headers
    return r


def _view(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def handles(namespace):
    return namespace.lower() == "microsoft.dataprotection"


def _children(state, parent_id, seg):
    pre = parent_id.lower() + "/" + seg + "/"
    return [r for k, r in state.items() if isinstance(r, dict) and k.startswith(pre) and "/" not in k[len(pre):]]


def _backend(cluster_rec):
    """The cluster's KubeBackend (core/kube_state_core.py): the backup engine only exports/applies manifests through it."""
    return kube.backend_for({}, "azure", cluster_rec["id"], cluster_rec, kube.BACKEND_FACTORY)


def _container(vault):
    return "aksbackup-" + re.sub(r"[^a-z0-9-]", "-", vault.lower())


# ── blob artifacts ───────────────────────────────────────────────────────────────────
def _art_put(blob_store, vault, path, doc):
    data = json.dumps(doc, sort_keys=True).encode()
    if blob_store is None:
        return {"inline": doc}
    cont = _container(vault)
    key = f"{ART_ACCOUNT}/{cont}"
    if not blob_store.container_exists(key):
        blob_store.create_container(key)
    r = _blob.dispatch(blob_store, "PUT", f"/{cont}/{path}", {}, {"x-ms-blob-type": "BlockBlob", "content-type": "application/json"}, data, account=ART_ACCOUNT)
    if r.status >= 300:
        return {"inline": doc}
    return {"blob": f"https://{ART_ACCOUNT}.blob.core.windows.net/{cont}/{path}", "account": ART_ACCOUNT, "container": cont, "path": path, "size": len(data)}


def _art_get(blob_store, art):
    if "inline" in art:
        return art["inline"]
    if blob_store is None:
        return None
    r = _blob.dispatch(blob_store, "GET", f"/{art['container']}/{art['path']}", {}, {}, b"", account=ART_ACCOUNT)
    return json.loads(r.body) if r.status == 200 else None


def _art_delete(blob_store, art):
    if blob_store is not None and "path" in art:
        _blob.dispatch(blob_store, "DELETE", f"/{art['container']}/{art['path']}", {}, {}, b"", account=ART_ACCOUNT)


# ── async jobs ───────────────────────────────────────────────────────────────────────
def _job_view(job):
    return _view(job)


def _new_job(state, vault, instance, operation, extra):
    jid = uuid.uuid4().hex
    now = time.time()
    cluster_id = instance["properties"]["dataSourceInfo"]["resourceID"]
    job = {"id": f"{vault['id']}/backupJobs/{jid}", "name": jid, "type": f"{NS}/backupVaults/backupJobs",
           "properties": {"activityID": str(uuid.uuid4()), "backupInstanceFriendlyName": f"{instance['name']}",
                          "dataSourceId": cluster_id, "dataSourceName": cluster_id.rsplit("/", 1)[-1], "dataSourceType": AKS,
                          "dataSourceLocation": vault.get("location"), "operation": operation, "operationCategory": operation,
                          "status": "InProgress", "startTime": _now(), "isUserTriggered": True, "progressEnabled": True,
                          "sourceResourceGroup": cluster_id.split("/")[4], "sourceSubscriptionID": cluster_id.split("/")[2],
                          "vaultName": vault["name"], "subTasks": []},
           "_kind": "job", "_due": now + JOB_SECONDS, "_instance": instance["id"], "_extra": extra}
    state[job["id"].lower()] = job
    vault["_pending"] = True
    return job


def _finish(state, blob_store, job):
    """Complete one due job: backup -> write the blob + record the recovery point; restore -> re-inject into the cluster."""
    p = job["properties"]
    inst = state.get(job["_instance"].lower())
    vault = state.get(job["_instance"].lower().split("/backupinstances/")[0])
    p["endTime"] = _now()
    try:
        if inst is None or vault is None:
            raise RuntimeError("The backup instance was deleted while the job was running.")
        ex = job["_extra"]
        if job["properties"]["operation"] == "Backup":
            rpid = ex["rpid"]
            doc = ex["snapshot"]
            art = _art_put(blob_store, vault["name"], f"{inst['name']}/{rpid}.json", doc)
            rp = {"id": f"{inst['id']}/recoveryPoints/{rpid}", "name": rpid, "type": f"{NS}/backupVaults/backupInstances/recoveryPoints",
                  "properties": {"objectType": "AzureBackupDiscreteRecoveryPoint", "recoveryPointId": rpid, "recoveryPointTime": ex["taken"],
                                 "recoveryPointType": "Full", "friendlyName": ex.get("name") or rpid,
                                 "recoveryPointDataStoresDetails": [{"type": "VaultStore", "id": rpid, "creationTime": ex["taken"], "state": "COMMITTED", "visible": True}],
                                 "policyName": inst["properties"].get("policyInfo", {}).get("policyId", "").rsplit("/", 1)[-1],
                                 "policyVersion": "", "retentionTagName": "Default",
                                 "vyomiContents": doc.get("counts") or {}, "vyomiArtifact": {k: v for k, v in art.items() if k != "inline"}},
                  "_kind": "rp", "_art": art}
            state[rp["id"].lower()] = rp
            p["extendedInfo"] = {"recoveryDestination": "Vault", "sourceRecoverPoint": {"id": rpid, "time": ex["taken"]}}
            inst["properties"]["currentProtectionState"] = "ProtectionConfigured"
        else:
            rp = state.get(ex["rp"].lower())
            doc = _art_get(blob_store, rp["_art"]) if rp else None
            if doc is None:
                raise RuntimeError("The recovery point's blob could not be read from the simulator Blob store.")
            target = state.get(ex["target"].lower())
            if target is None:
                raise RuntimeError(f"Restore target cluster '{ex['target']}' does not exist.")
            verbs = _backend(target).apply((doc.get("namespaces") and [{"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": n["name"], "labels": n.get("labels") or {}}} for n in doc["namespaces"]] or []) + list(doc.get("objects") or []))
            p["extendedInfo"] = {"restoredObjects": verbs, "targetResourceId": target["id"]}
        p["status"] = "Completed"
    except Exception as e:                # k8s.KubectlError included
        p["status"] = "Failed"
        p["errorDetails"] = [{"code": "UserError" if isinstance(e, k8s.KubectlError) else "InternalError", "message": str(e)}]
    p["duration"] = f"PT{JOB_SECONDS:g}S"
    job.pop("_extra", None)
    job.pop("_due", None)


def tick(state, blob_store=None, force=False):
    """Complete every due InProgress job. Cheap: only vaults flagged ``_pending`` are visited."""
    now = time.time()
    for v in [r for r in list(state.values()) if isinstance(r, dict) and r.get("_pending")]:
        left = False
        for j in _children(state, v["id"], "backupjobs"):
            if j.get("properties", {}).get("status") != "InProgress":
                continue
            if force or now >= j.get("_due", 0):
                _finish(state, blob_store, j)
            else:
                left = True
        if not left:
            v.pop("_pending", None)


def _async(vault, job, sub, base):
    loc = (vault.get("location") or "eastus").lower().replace(" ", "")
    root = f"{base}/subscriptions/{sub}/providers/{NS}/locations/{loc}"
    q = "?api-version=2024-04-01"
    return _ok({"jobId": job["id"], "objectType": "OperationJobExtendedInfo"}, 202,
               {"Azure-AsyncOperation": f"{root}/operationStatus/{job['name']}{q}", "Location": f"{root}/operationResults/{job['name']}{q}", "Retry-After": "1"})


def _op_status(state, sub, jid, results=False):
    job = next((r for k, r in state.items() if isinstance(r, dict) and r.get("_kind") == "job" and r.get("name") == jid and f"/subscriptions/{sub}/".lower() in k), None)
    if job is None:
        return _err(404, "ResourceNotFound", f"Operation '{jid}' was not found.")
    st = job["properties"]["status"]
    mapped = {"InProgress": "InProgress", "Completed": "Succeeded", "Failed": "Failed"}[st]
    if results:
        return _ok(None, 202) if st == "InProgress" else _ok({"jobId": job["id"], "objectType": "OperationJobExtendedInfo"})
    body = {"id": f"/subscriptions/{sub}/providers/{NS}/locations/x/operationStatus/{jid}", "name": jid, "status": mapped,
            "startTime": job["properties"]["startTime"], "properties": {"jobId": job["id"]}}
    if job["properties"].get("endTime"):
        body["endTime"] = job["properties"]["endTime"]
    if st == "Failed":
        body["error"] = {"code": job["properties"]["errorDetails"][0]["code"], "message": job["properties"]["errorDetails"][0]["message"]}
    return _ok(body)


# ── vault / policy / instance ────────────────────────────────────────────────────────
def _vault(state, method, sub, rg, name, rid, rec, payload):
    if method == "GET":
        return _ok(_view(rec)) if rec else _err(404, "ResourceNotFound", f"The Resource '{NS}/backupVaults/{name}' under resource group '{rg}' was not found.")
    if method == "DELETE":
        if rec is None:
            return _ok(None, 204)
        if _children(state, rid, "backupinstances"):
            return _err(409, "VaultHasBackupInstances", f"Backup vault '{name}' still has backup instances. Delete them first.")
        for k in [k for k in state if k.startswith(rid.lower() + "/")]:
            del state[k]
        del state[rid.lower()]
        return _ok(None, 200)
    if method not in ("PUT", "PATCH"):
        return _err(405, "MethodNotAllowed", "Unsupported method.")
    payload = payload or {}
    if rec is None and method == "PATCH":
        return _err(404, "ResourceNotFound", f"The Resource '{NS}/backupVaults/{name}' under resource group '{rg}' was not found.")
    if not NAME_RE.match(name):
        return _err(400, "InvalidResourceName", "Backup vault name must be 2-50 characters: letters, digits and hyphens, starting with a letter.")
    loc = payload.get("location") or (rec or {}).get("location")
    if not loc:
        return _err(400, "LocationRequired", "The location property is required for a backup vault.")
    if f"/subscriptions/{sub}/resourcegroups/{rg}".lower() not in state:
        return _err(404, "ResourceGroupNotFound", f"Resource group '{rg}' could not be found.")
    ss = ((payload.get("properties") or {}).get("storageSettings")) or ((rec or {}).get("properties") or {}).get("storageSettings") or [{"datastoreType": "VaultStore", "type": "LocallyRedundant"}]
    for s in ss:
        if s.get("type") not in REDUNDANCY or s.get("datastoreType") not in ("VaultStore", "OperationalStore", "ArchiveStore"):
            return _err(400, "InvalidParameter", f"storageSettings must use a datastoreType of VaultStore|OperationalStore|ArchiveStore and a type of {'|'.join(REDUNDANCY)}.")
    new = rec is None
    rec = rec or {"id": rid, "name": name, "type": f"{NS}/backupVaults", "_type": VAULT_T, "_sub": sub, "_rg": rg}
    rec["location"] = loc
    rec["tags"] = payload.get("tags", rec.get("tags", {}))
    rec["identity"] = payload.get("identity") or rec.get("identity") or {"type": "SystemAssigned", "principalId": str(uuid.uuid5(uuid.NAMESPACE_URL, rid)), "tenantId": "00000000-0000-0000-0000-000000000000"}
    rec["properties"] = {"provisioningState": "Succeeded", "storageSettings": ss, "isVaultProtectedByResourceGuard": False,
                         "bcdrSecurityLevel": "NotSupported", "resourceMoveState": "Unknown",
                         "securitySettings": {"softDeleteSettings": {"state": "Off", "retentionDurationInDays": 14}, "immutabilitySettings": {"state": "Disabled"}},
                         "featureSettings": {"crossRegionRestoreSettings": {"state": "Disabled"}}}
    state[rid.lower()] = rec
    return _ok(_view(rec), 201 if new else 200)


def _policies(state, method, vault, rest, payload):
    if not rest:
        return _ok({"value": [_view(p) for p in _children(state, vault["id"], "backuppolicies")]}) if method == "GET" else _err(405, "MethodNotAllowed", "Unsupported.")
    pid = f"{vault['id']}/backupPolicies/{rest[0]}"
    cur = state.get(pid.lower())
    if method == "GET":
        return _ok(_view(cur)) if cur else _err(404, "ResourceNotFound", f"Backup policy '{rest[0]}' was not found.")
    if method == "DELETE":
        if cur is None:
            return _ok(None, 204)
        if any((i["properties"].get("policyInfo") or {}).get("policyId", "").lower() == pid.lower() for i in _children(state, vault["id"], "backupinstances")):
            return _err(409, "PolicyInUse", f"Backup policy '{rest[0]}' is used by a backup instance.")
        del state[pid.lower()]
        return _ok(None, 200)
    if method != "PUT":
        return _err(405, "MethodNotAllowed", "Unsupported.")
    p = (payload or {}).get("properties") or {}
    if p.get("objectType", "BackupPolicy") != "BackupPolicy" or p.get("datasourceTypes") != [AKS]:
        return _err(400, "InvalidParameter", f"properties.objectType must be BackupPolicy and datasourceTypes must be [\"{AKS}\"].")
    if not isinstance(p.get("policyRules"), list) or not p["policyRules"]:
        return _err(400, "InvalidParameter", "properties.policyRules must contain at least one rule.")
    rec = {"id": pid, "name": rest[0], "type": f"{NS}/backupVaults/backupPolicies", "properties": {"objectType": "BackupPolicy", "datasourceTypes": [AKS], "policyRules": p["policyRules"]}, "_kind": "policy"}
    new = cur is None
    state[pid.lower()] = rec
    return _ok(_view(rec), 201 if new else 200)


def _recovery_points(state, instance, rest):
    rps = sorted(_children(state, instance["id"], "recoverypoints"), key=lambda r: r["properties"]["recoveryPointTime"], reverse=True)
    if not rest:
        return _ok({"value": [_view(r) for r in rps]})
    rp = state.get(f"{instance['id']}/recoveryPoints/{rest[0]}".lower())
    return _ok(_view(rp)) if rp else _err(404, "ResourceNotFound", f"Recovery point '{rest[0]}' was not found.")


def _rp_for(state, instance, payload):
    ro = (payload or {}).get("restoreRequestObject") or payload or {}
    if ro.get("objectType") not in (None, "AzureBackupRecoveryPointBasedRestoreRequest"):
        return None, None, _err(400, "UnsupportedRestoreType", "Only AzureBackupRecoveryPointBasedRestoreRequest is supported (no point-in-time or item-level restore).")
    rpid = ro.get("recoveryPointId")
    rp = state.get(f"{instance['id']}/recoveryPoints/{rpid}".lower()) if rpid else None
    if rp is None:
        return None, None, _err(404, "RecoveryPointNotFound", f"Recovery point '{rpid}' was not found for backup instance '{instance['name']}'.")
    tgt = ((ro.get("restoreTargetInfo") or {}).get("datasourceInfo") or {}).get("resourceID") or instance["properties"]["dataSourceInfo"]["resourceID"]
    if state.get(tgt.lower()) is None or (state[tgt.lower()].get("_type") or "").lower() != AKS.lower():
        return None, None, _err(400, "TargetNotFound", f"Restore target '{tgt}' is not an existing managed cluster.")
    return rp, tgt, None


def _instance(state, method, sub, vault, rest, payload, query, blob_store, base):
    if not rest:
        return _ok({"value": [_view(i) for i in _children(state, vault["id"], "backupinstances")]}) if method == "GET" else _err(405, "MethodNotAllowed", "Unsupported.")
    iid = f"{vault['id']}/backupInstances/{rest[0]}"
    cur = state.get(iid.lower())
    sub_res = rest[1].lower() if len(rest) > 1 else None
    if sub_res is None:
        if method == "GET":
            return _ok(_view(cur)) if cur else _err(404, "ResourceNotFound", f"Backup instance '{rest[0]}' was not found.")
        if method == "DELETE":
            if cur is None:
                return _ok(None, 204)
            for k in [k for k, r in state.items() if k.startswith(iid.lower() + "/")]:
                r = state[k]
                if r.get("_kind") == "rp":
                    _art_delete(blob_store, r.get("_art") or {})
                del state[k]
            del state[iid.lower()]
            return _ok(None, 200)
        if method != "PUT":
            return _err(405, "MethodNotAllowed", "Unsupported.")
        p = (payload or {}).get("properties") or {}
        ds = p.get("dataSourceInfo") or {}
        cid = ds.get("resourceID") or ""
        cl = state.get(cid.lower())
        if not cid or cl is None or (cl.get("_type") or "").lower() != AKS.lower():
            return _err(404, "ResourceNotFound", f"dataSourceInfo.resourceID '{cid}' is not an existing managed cluster.")
        if ds.get("datasourceType") not in (None, AKS):
            return _err(400, "InvalidParameter", f"dataSourceInfo.datasourceType must be {AKS}.")
        pol = (p.get("policyInfo") or {}).get("policyId") or ""
        if state.get(pol.lower()) is None or not pol.lower().startswith(vault["id"].lower() + "/backuppolicies/"):
            return _err(404, "ResourceNotFound", f"policyInfo.policyId '{pol}' is not a backup policy of vault '{vault['name']}'.")
        for o in _children(state, vault["id"], "backupinstances"):
            if o["id"].lower() != iid.lower() and o["properties"]["dataSourceInfo"]["resourceID"].lower() == cid.lower():
                return _err(409, "BackupInstanceAlreadyExists", f"Cluster '{cl['name']}' is already protected by backup instance '{o['name']}' in this vault.")
        rec = {"id": iid, "name": rest[0], "type": f"{NS}/backupVaults/backupInstances",
               "properties": {"friendlyName": p.get("friendlyName") or rest[0], "objectType": "BackupInstance",
                              "dataSourceInfo": {"objectType": "Datasource", "resourceID": cl["id"], "resourceName": cl["name"], "resourceType": AKS,
                                                 "resourceLocation": cl.get("location"), "datasourceType": AKS},
                              "policyInfo": {"policyId": state[pol.lower()]["id"]}, "protectionStatus": {"status": "ProtectionConfigured"},
                              "currentProtectionState": "ProtectionConfigured", "protectionErrorDetails": None, "provisioningState": "Succeeded"},
               "_kind": "instance"}
        new = cur is None
        state[iid.lower()] = rec
        return _ok(_view(rec), 201 if new else 200)
    if cur is None:
        return _err(404, "ResourceNotFound", f"Backup instance '{rest[0]}' was not found.")
    if sub_res == "recoverypoints" and method == "GET":
        return _recovery_points(state, cur, rest[2:])
    if method != "POST":
        return _err(405, "MethodNotAllowed", "Unsupported.")
    sub_id = vault["id"].split("/")[2]
    cl = state.get(cur["properties"]["dataSourceInfo"]["resourceID"].lower())
    if sub_res == "backup":
        if cl is None:
            return _err(404, "ResourceNotFound", "The protected cluster no longer exists.")
        if (cl.get("properties") or {}).get("powerState", {}).get("code") == "Stopped":
            return _err(409, "ClusterNotRunning", "The cluster is stopped; start it before taking a backup.")
        taken = _now()
        rpid = uuid.uuid4().hex
        snap = _backend(cl).export_resources()
        job = _new_job(state, vault, cur, "Backup", {"rpid": rpid, "taken": taken, "snapshot": snap, "name": ((payload or {}).get("backupRuleOptions") or {}).get("ruleName")})
        return _async(vault, job, sub_id, base)
    if sub_res in ("validaterestore", "validateforrestore", "restore"):
        rp, tgt, e = _rp_for(state, cur, payload)
        if e:
            return e
        if sub_res != "restore":
            return _ok({"objectType": "ValidateRestoreOperationResponse", "status": "Succeeded", "targetResourceId": tgt, "recoveryPointId": rp["name"]})
        job = _new_job(state, vault, cur, "Restore", {"rp": rp["id"], "target": tgt})
        return _async(vault, job, sub_id, base)
    return _err(404, "ResourceNotFound", f"Unknown backup instance action '{rest[1]}'.")


def dispatch(state, method, sub, rg, chain, payload, query, blob_store=None, base=""):
    """chain after 'providers/Microsoft.DataProtection'."""
    tick(state, blob_store)
    if not chain:
        return _err(404, "ResourceNotFound", "Unknown Microsoft.DataProtection resource type.")
    low = chain[0].lower()
    if low == "locations" and len(chain) == 4 and method == "GET" and chain[2].lower() in ("operationstatus", "operationresults"):
        return _op_status(state, sub, chain[3], results=chain[2].lower() == "operationresults")
    if low != "backupvaults":
        return _err(404, "ResourceNotFound", "Unknown Microsoft.DataProtection resource type.")
    if len(chain) == 1:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        return _ok({"value": [_view(r) for r in state.values() if isinstance(r, dict) and r.get("_type") == VAULT_T and r.get("_sub") == sub
                              and (rg is None or (r.get("_rg") or "").lower() == rg.lower())]})
    if rg is None:
        return _err(400, "InvalidRequest", "A backup vault path needs a resource group.")
    rid = f"/subscriptions/{sub}/resourceGroups/{rg}/providers/{NS}/backupVaults/{chain[1]}"
    vault = state.get(rid.lower())
    if len(chain) == 2:
        return _vault(state, method, sub, rg, chain[1], rid, vault, payload)
    if vault is None:
        return _err(404, "ResourceNotFound", f"The Resource '{NS}/backupVaults/{chain[1]}' under resource group '{rg}' was not found.")
    rest = chain[2:]
    k = rest[0].lower()
    if k == "backuppolicies":
        return _policies(state, method, vault, rest[1:], payload)
    if k == "backupinstances":
        return _instance(state, method, sub, vault, rest[1:], payload, query, blob_store, base)
    if k == "backupjobs" and method == "GET":
        if len(rest) == 1:
            return _ok({"value": [_job_view(j) for j in _children(state, vault["id"], "backupjobs")]})
        j = state.get(f"{vault['id']}/backupJobs/{rest[1]}".lower())
        return _ok(_job_view(j)) if j else _err(404, "ResourceNotFound", f"Job '{rest[1]}' was not found.")
    return _err(404, "ResourceNotFound", f"Unknown backup vault child '{rest[0]}'.")
