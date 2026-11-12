"""Azure Backup + Site Recovery (Microsoft.RecoveryServices) -- control plane over REAL artifacts in the simulator's own Blob
store (Nano / dev_server / unified-ingress core, substrate-free; state lives in the flat ARM state map).

Resources (all under ``.../providers/Microsoft.RecoveryServices/vaults/{vault}``):

* the vault itself: name 2-50 chars (letter first), ``sku`` (RS0/Standard), ``securitySettings.immutabilitySettings.state``
  (Disabled|Unlocked|Locked -- Locked cannot be relaxed), delete is blocked while protected items (including soft-deleted
  ones) or replicated items still exist. Three default backup policies are seeded like a new vault.
* ``backupPolicies/{p}`` -- AzureIaasVM (SimpleSchedulePolicy / V2, daily 7-9999 d, weekly 1-5163 w, monthly 1-1188 m,
  yearly 1-99 y, instant-RP range 1-5 d) and AzureStorage (file share, daily 1-200 d) policies are validated; a policy in
  use cannot be deleted.
* ``backupFabrics/Azure/protectionContainers/{c}/protectedItems/{i}`` -- a VM (``iaasvmcontainer;iaasvmcontainerv2;rg;vm`` /
  ``vm;iaasvmcontainerv2;rg;vm``) or Azure Files share (``storagecontainer;Storage;rg;acct`` / ``azurefileshare;share``).
  The source must exist, be in the vault's region, and the policy type must match. Stop protection (retain data) and soft-delete
  (14 days, un-delete by re-PUT) are modelled.
* ``.../protectedItems/{i}/backup`` -- takes a recovery point: the source's configuration (VM + its managed disks) or the
  whole file-share tree is written as a JSON ARTIFACT into the simulator's Blob store (account ``vyomirsvault``, container
  ``rsv-{vault}``) and a ``recoveryPoints/{id}`` record points at it.
* ``.../recoveryPoints/{rp}/restore`` -- a REAL restore: VM -> restore disks (managed disks + config blob in a storage account),
  alternate location (a NEW VM + NIC in the target subnet) or original location (the VM is reset to the point's
  configuration); file share -> full-share or item-level restore with CreateCopy|Overwrite|Skip|FailOnConflict into the original
  or another share.
* ``backupJobs``, ``backupOperations`` (async status), ``backupProtectedItems`` / ``backupProtectionContainers`` /
  ``backupUsageSummaries`` listings, ``backupstorageconfig/vaultstorageconfig``, ``backupconfig/vaultconfig`` (soft delete),
  ``/locations/{loc}/backupStatus`` and ``backupPreValidateProtection``.
* Site Recovery for VM disaster recovery: ``replicationFabrics/{f}/replicationProtectionContainers/{c}/replicationProtectedItems/{i}``
  (A2A: the target region/resource group are required, source VM must exist), ``testFailover`` / ``unplannedFailover``
  create the replica VM in the target region from the replicated configuration, ``testFailoverCleanup`` removes it,
  ``commit`` / ``reProtect`` move the state machine, plus ``replicationJobs``.

NOT modelled (honest limits): recovery points capture the VM CONFIGURATION and disk metadata, not block-level disk bytes
(Vyomi VMs are not backed by VHD blobs); a restored VM boots with the configuration, not the original disk contents. File
share restores ARE byte-for-byte. Vyomi simulates one data plane, so the "secondary region" of geo-redundant storage /
cross-region restore / Site Recovery replication is a second set of records and artifacts, not a physically separate region.
There is no RPO/replication lag: replication health is always ``Normal`` with RPO 0 until a failover is run. Workload (SQL
Server in VM, SAP HANA) backup and MARS/MABS agents are not modelled.
"""
from __future__ import annotations

import base64
import datetime
import json
import re
import uuid

NS = "Microsoft.RecoveryServices"
VAULT = "microsoft.recoveryservices/vaults"
ART_ACCOUNT = "vyomirsvault"
NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9\-]{1,49}$")
STORAGE_TYPES = ("GeoRedundant", "LocallyRedundant", "ZoneRedundant", "ReadAccessGeoZoneRedundant")
IMMUTABILITY = ("Disabled", "Unlocked", "Locked")
SOFT_DELETE = ("Enabled", "Disabled", "AlwaysON")
RESTORE_COPY = ("CreateCopy", "Overwrite", "Skip", "FailOnConflict")
A2A_ACTIONS = ("testfailover", "testfailovercleanup", "unplannedfailover", "plannedfailover", "commit", "reprotect")


class _LazyBlob:
    def __getattr__(self, name):
        try:
            from core import azure_blob_core as m
        except ImportError:
            import azure_blob_core as m           # type: ignore
        return getattr(m, name)


_blob = _LazyBlob()


def _now(delta_days: float = 0):
    t = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=delta_days)
    return t.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _err(status, code, msg):
    return {"status": status, "body": {"error": {"code": code, "message": msg}}}


def _ok(body, status=200, headers=None):
    r = {"status": status, "body": body}
    if headers:
        r["headers"] = headers
    return r


def _view(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def handles(namespace, chain=None):
    return namespace.lower() == "microsoft.recoveryservices"


def _children(state, parent_id, kind):
    pre = parent_id.lower() + "/" + kind + "/"
    return [r for k, r in state.items() if isinstance(r, dict) and k.startswith(pre) and "/" not in k[len(pre):]]


def _vault_items(state, vault_id, include_deleted=True):
    pre = vault_id.lower() + "/backupfabrics/"
    return [r for k, r in state.items() if isinstance(r, dict) and k.startswith(pre) and r.get("_kind") == "item"]


def _vault_repl(state, vault_id):
    pre = vault_id.lower() + "/replicationfabrics/"
    return [r for k, r in state.items() if isinstance(r, dict) and k.startswith(pre) and r.get("_kind") == "repl"]


# ── artifacts in the simulator's Blob store ───────────────────────────────────────────
def _art_container(vault_name):
    return "rsv-" + re.sub(r"[^a-z0-9-]", "-", vault_name.lower())


def _art_put(blob_store, vault_name, path, doc):
    """Write a JSON artifact; returns (ok, blob url or inline doc)."""
    data = json.dumps(doc).encode()
    if blob_store is None:
        return {"inline": doc}, len(data)
    cont = _art_container(vault_name)
    key = f"{ART_ACCOUNT}/{cont}"
    if not blob_store.container_exists(key):
        blob_store.create_container(key)
    r = _blob.dispatch(blob_store, "PUT", f"/{cont}/{path}", {}, {"x-ms-blob-type": "BlockBlob", "content-type": "application/json"},
                       data, account=ART_ACCOUNT)
    if r.status >= 300:
        return {"inline": doc}, len(data)
    return {"blob": f"https://{ART_ACCOUNT}.blob.core.windows.net/{cont}/{path}", "container": cont, "path": path}, len(data)


def _art_get(blob_store, art):
    if "inline" in art:
        return art["inline"]
    if blob_store is None:
        return None
    r = _blob.dispatch(blob_store, "GET", f"/{art['container']}/{art['path']}", {}, {}, b"", account=ART_ACCOUNT)
    if r.status != 200:
        return None
    return json.loads(r.body)


def _art_delete(blob_store, art):
    if blob_store is not None and "blob" in art:
        _blob.dispatch(blob_store, "DELETE", f"/{art['container']}/{art['path']}", {}, {}, b"", account=ART_ACCOUNT)


# ── vault ──────────────────────────────────────────────────────────────────────────────
def _default_policies(vault_id, vault_loc):
    def pol(name, mtype, sched, ret, extra=None):
        p = {"backupManagementType": mtype, "schedulePolicy": sched, "retentionPolicy": ret, "protectedItemsCount": 0}
        p.update(extra or {})
        return {"id": f"{vault_id}/backupPolicies/{name}", "name": name, "type": f"{NS}/vaults/backupPolicies",
                "location": vault_loc, "properties": p, "_kind": "policy"}
    daily = lambda n: {"retentionPolicyType": "LongTermRetentionPolicy", "dailySchedule": {"retentionTimes": ["2026-01-01T02:00:00Z"],
                       "retentionDuration": {"count": n, "durationType": "Days"}}}
    return [
        pol("DefaultPolicy", "AzureIaasVM", {"schedulePolicyType": "SimpleSchedulePolicy", "scheduleRunFrequency": "Daily",
            "scheduleRunTimes": ["2026-01-01T02:00:00Z"]}, daily(30), {"instantRpRetentionRangeInDays": 2, "timeZone": "UTC", "policyType": "V1"}),
        pol("EnhancedPolicy", "AzureIaasVM", {"schedulePolicyType": "SimpleSchedulePolicyV2", "scheduleRunFrequency": "Hourly",
            "hourlySchedule": {"interval": 4, "scheduleWindowStartTime": "2026-01-01T08:00:00Z", "scheduleWindowDuration": 12}},
            daily(30), {"instantRpRetentionRangeInDays": 2, "timeZone": "UTC", "policyType": "V2"}),
        pol("HourlyLogBackup", "AzureWorkload", {"schedulePolicyType": "LogSchedulePolicy", "scheduleFrequencyInMins": 60},
            {"retentionPolicyType": "SimpleRetentionPolicy", "retentionDuration": {"count": 30, "durationType": "Days"}}),
    ]


def _vault(state, method, sub, rg, name, rid, rec, payload, blob_store):
    if method == "GET":
        return _ok(_view(rec)) if rec else _err(404, "ResourceNotFound", f"The Resource '{NS}/vaults/{name}' under resource group '{rg}' was not found.")
    if method in ("PUT", "PATCH"):
        payload = payload or {}
        p = payload.get("properties") or {}
        if rec is None:
            if method == "PATCH":
                return _err(404, "ResourceNotFound", f"The Resource '{NS}/vaults/{name}' under resource group '{rg}' was not found.")
            if not NAME_RE.match(name):
                return _err(400, "InvalidResourceName", "Recovery Services vault names are 2-50 characters: letters, digits and '-', starting with a letter.")
            if not payload.get("location"):
                return _err(400, "InvalidRequestContent", "location is required.")
            sku = payload.get("sku") or {"name": "RS0", "tier": "Standard"}
            if sku.get("name") != "RS0" or sku.get("tier", "Standard") != "Standard":
                return _err(400, "InvalidSku", "The vault sku must be name 'RS0', tier 'Standard'.")
            rec = {"id": rid, "name": name, "type": f"{NS}/vaults", "location": payload["location"], "tags": payload.get("tags") or {},
                   "sku": sku, "etag": f'W/"datetime\'{_now()}\'"',
                   "properties": {"provisioningState": "Succeeded", "privateEndpointStateForBackup": "None",
                                  "privateEndpointStateForSiteRecovery": "None", "publicNetworkAccess": "Enabled",
                                  "backupStorageType": "GeoRedundant",
                                  "securitySettings": {"immutabilitySettings": {"state": "Disabled"}, "softDeleteSettings":
                                                       {"softDeleteState": "Enabled", "softDeleteRetentionPeriodInDays": 14}},
                                  "monitoringSettings": {"azureMonitorAlertSettings": {"alertsForAllJobFailures": "Enabled"}}},
                   "_type": VAULT, "_sub": sub, "_rg": rg, "_vault_cfg": {"crossRegionRestoreFlag": False, "enhancedSecurityState": "Enabled"}}
            state[rid.lower()] = rec
            for pol in _default_policies(rid, rec["location"]):
                state[pol["id"].lower()] = pol
            status = 201
        else:
            status = 200
            if payload.get("location") and payload["location"].lower() != rec["location"].lower():
                return _err(400, "LocationCannotBeChanged", "The location of an existing vault cannot be changed.")
        sec = (p.get("securitySettings") or {})
        imm = (sec.get("immutabilitySettings") or {}).get("state")
        if imm is not None:
            if imm not in IMMUTABILITY:
                return _err(400, "InvalidRequestContent", f"immutabilitySettings.state must be one of {', '.join(IMMUTABILITY)}.")
            cur = rec["properties"]["securitySettings"]["immutabilitySettings"]["state"]
            if cur == "Locked" and imm != "Locked":
                return _err(400, "BMSUserErrorImmutabilityLocked", "Immutability is Locked on this vault and cannot be disabled or made unlocked.")
            rec["properties"]["securitySettings"]["immutabilitySettings"]["state"] = imm
        sd = (sec.get("softDeleteSettings") or {})
        if sd:
            st = sd.get("softDeleteState", rec["properties"]["securitySettings"]["softDeleteSettings"]["softDeleteState"])
            days = sd.get("softDeleteRetentionPeriodInDays", rec["properties"]["securitySettings"]["softDeleteSettings"]["softDeleteRetentionPeriodInDays"])
            if st not in SOFT_DELETE:
                return _err(400, "InvalidRequestContent", f"softDeleteState must be one of {', '.join(SOFT_DELETE)}.")
            if not isinstance(days, int) or not 14 <= days <= 180:
                return _err(400, "InvalidRequestContent", "softDeleteRetentionPeriodInDays must be 14-180.")
            if rec["properties"]["securitySettings"]["softDeleteSettings"]["softDeleteState"] == "AlwaysON" and st != "AlwaysON":
                return _err(400, "BMSUserErrorSoftDeleteAlwaysOn", "Soft delete is AlwaysON for this vault and cannot be turned off.")
            rec["properties"]["securitySettings"]["softDeleteSettings"] = {"softDeleteState": st, "softDeleteRetentionPeriodInDays": days}
        if p.get("publicNetworkAccess") in ("Enabled", "Disabled"):
            rec["properties"]["publicNetworkAccess"] = p["publicNetworkAccess"]
        if isinstance(payload.get("tags"), dict):
            rec["tags"] = payload["tags"]
        return _ok(_view(rec), status)
    if method == "DELETE":
        if rec is None:
            return {"status": 204, "body": None}
        if _vault_items(state, rid):
            return _err(409, "VaultDeleteFailed", "Vault cannot be deleted as there are existing resources within the vault. Please delete "
                        "all protected items (including soft-deleted items) and registered servers first.")
        if _vault_repl(state, rid):
            return _err(409, "VaultDeleteFailed", "Vault cannot be deleted as there are replicated items. Disable replication first.")
        pre = rid.lower() + "/"
        for k in [k for k in state if k.startswith(pre)]:
            state.pop(k)
        state.pop(rid.lower())
        return _ok(None)
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


# ── policies ───────────────────────────────────────────────────────────────────────────
def _ret_count(block, lo, hi, what, units=("Days",)):
    rd = (block or {}).get("retentionDuration") or {}
    c = rd.get("count")
    if not isinstance(c, int) or not lo <= c <= hi:
        return f"{what} retention count must be {lo}-{hi}."
    if rd.get("durationType") not in units:
        return f"{what} durationType must be {' or '.join(units)}."
    return None


def _validate_policy(p):
    t = p.get("backupManagementType")
    if t not in ("AzureIaasVM", "AzureStorage", "AzureWorkload"):
        return "backupManagementType must be AzureIaasVM, AzureStorage or AzureWorkload."
    sp, rp = p.get("schedulePolicy") or {}, p.get("retentionPolicy") or {}
    if t == "AzureWorkload":
        return None
    if sp.get("schedulePolicyType") not in ("SimpleSchedulePolicy", "SimpleSchedulePolicyV2"):
        return "schedulePolicy.schedulePolicyType must be SimpleSchedulePolicy or SimpleSchedulePolicyV2."
    freq = sp.get("scheduleRunFrequency")
    if freq not in ("Daily", "Weekly", "Hourly"):
        return "scheduleRunFrequency must be Hourly, Daily or Weekly."
    if t == "AzureIaasVM" and freq == "Hourly" and sp["schedulePolicyType"] != "SimpleSchedulePolicyV2":
        return "Hourly backups need the Enhanced policy (SimpleSchedulePolicyV2)."
    if freq == "Hourly":
        h = sp.get("hourlySchedule") or {}
        if h.get("interval") not in (4, 6, 8, 12) and t == "AzureIaasVM":
            return "hourlySchedule.interval must be 4, 6, 8 or 12 hours."
        if not 4 <= int(h.get("scheduleWindowDuration") or 0) <= 24:
            return "hourlySchedule.scheduleWindowDuration must be 4-24 hours."
    else:
        times = sp.get("scheduleRunTimes") or []
        if len(times) != 1:
            return "scheduleRunTimes must hold exactly one time."
        if freq == "Weekly" and not sp.get("scheduleRunDays"):
            return "scheduleRunDays is required for a Weekly schedule."
    if rp.get("retentionPolicyType") != "LongTermRetentionPolicy":
        return "retentionPolicy.retentionPolicyType must be LongTermRetentionPolicy."
    ranges = {"dailySchedule": (7 if t == "AzureIaasVM" else 1, 9999 if t == "AzureIaasVM" else 200, ("Days",)),
              "weeklySchedule": (1, 5163, ("Weeks",)), "monthlySchedule": (1, 1188, ("Months",)), "yearlySchedule": (1, 99, ("Years",))}
    seen = False
    for k, (lo, hi, units) in ranges.items():
        if rp.get(k):
            seen = True
            bad = _ret_count(rp[k], lo, hi, k[:-8].capitalize(), units)
            if bad:
                return bad
    if not seen:
        return "retentionPolicy needs at least one of dailySchedule, weeklySchedule, monthlySchedule, yearlySchedule."
    ir = p.get("instantRpRetentionRangeInDays")
    if t == "AzureIaasVM" and ir is not None and not 1 <= ir <= (30 if p.get("policyType") == "V2" or sp.get("schedulePolicyType") == "SimpleSchedulePolicyV2" else 5):
        return "instantRpRetentionRangeInDays must be 1-5 (1-30 for an Enhanced policy)."
    return None


def _policies(state, method, vault, rest, payload):
    if not rest:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        rows = []
        for p in _children(state, vault["id"], "backuppolicies"):
            v = _view(p)
            v["properties"] = dict(v["properties"], protectedItemsCount=sum(1 for i in _vault_items(state, vault["id"])
                                   if (i["properties"].get("policyId") or "").lower() == p["id"].lower() and not i["properties"].get("isScheduledForDeferredDelete")))
            rows.append(v)
        return _ok({"value": rows})
    name = rest[0]
    rid = f"{vault['id']}/backupPolicies/{name}"
    rec = state.get(rid.lower())
    if method == "GET":
        return _ok(_view(rec)) if rec else _err(404, "ResourceNotFound", f"The backup policy '{name}' was not found.")
    if method in ("PUT", "PATCH"):
        p = (payload or {}).get("properties") or {}
        bad = _validate_policy(p)
        if bad:
            return _err(400, "BMSUserErrorInvalidPolicyInput" if "retention" in bad.lower() else "InvalidRequestContent", bad)
        if rec is not None and rec["properties"].get("backupManagementType") != p.get("backupManagementType"):
            return _err(400, "BMSUserErrorInvalidPolicyInput", "backupManagementType of an existing policy cannot be changed.")
        if name in ("DefaultPolicy", "EnhancedPolicy", "HourlyLogBackup") and rec is not None and rec.get("_default"):
            pass
        newrec = {"id": rid, "name": name, "type": f"{NS}/vaults/backupPolicies", "location": vault["location"],
                  "properties": dict(p, protectedItemsCount=0), "_kind": "policy"}
        state[rid.lower()] = newrec
        return _ok(_view(newrec), 200 if rec else 201)
    if method == "DELETE":
        if rec is None:
            return {"status": 204, "body": None}
        used = [i for i in _vault_items(state, vault["id"]) if (i["properties"].get("policyId") or "").lower() == rid.lower()]
        if used:
            return _err(400, "BMSUserErrorPolicyInUse", f"The backup policy '{name}' is in use by {len(used)} protected item(s). Change their policy first.")
        state.pop(rid.lower())
        return _ok(None, 200)
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


# ── protected items / backup / restore ─────────────────────────────────────────────────
def _job(state, vault, operation, entity, mtype, status="Completed", extra=None, error=None):
    jid = str(uuid.uuid4())
    props = {"jobType": "AzureIaaSVMJob" if mtype == "AzureIaasVM" else "AzureStorageJob", "entityFriendlyName": entity,
             "backupManagementType": mtype, "operation": operation, "status": status, "startTime": _now(), "endTime": _now(),
             "duration": "00:00:03", "activityId": str(uuid.uuid4()), "actionsInfo": ["Cancellable"] if status == "InProgress" else [],
             "extendedInfo": extra or {}}
    if error:
        props["errorDetails"] = [{"errorCode": error[0], "errorString": error[1]}]
    rec = {"id": f"{vault['id']}/backupJobs/{jid}", "name": jid, "type": f"{NS}/vaults/backupJobs", "properties": props, "_kind": "job"}
    state[rec["id"].lower()] = rec
    return rec


def _split_rid(rid):
    parts = [x for x in (rid or "").split("/") if x]
    low = [x.lower() for x in parts]
    try:
        return parts[low.index("resourcegroups") + 1], parts[-1]
    except (ValueError, IndexError):
        return None, None


def _snapshot_vm(state, vm):
    props = json.loads(json.dumps(vm.get("properties") or {}))
    sp = props.get("storageProfile") or {}
    disks = []
    for d in [(sp.get("osDisk") or {})] + list(sp.get("dataDisks") or []):
        did = ((d.get("managedDisk") or {}).get("id") or "").lower()
        drec = state.get(did)
        if drec:
            disks.append({"name": drec["name"], "id": drec["id"], "sku": drec.get("sku"), "properties": json.loads(json.dumps(drec.get("properties") or {}))})
    return {"kind": "vm", "name": vm["name"], "id": vm["id"], "location": vm.get("location"), "tags": dict(vm.get("tags") or {}),
            "properties": props, "disks": disks, "zones": vm.get("zones")}


def _snapshot_share(state, acct_rec, share):
    return {"kind": "share", "name": share.get("name"), "quota": share["properties"].get("shareQuota", 5120), "tree": json.loads(json.dumps(share.get("_tree") or {}))}


def _find_source(state, item):
    rid = item["properties"].get("sourceResourceId") or ""
    return state.get(rid.lower())


def _item_id_parts(chain):
    return chain[2], chain[4]          # container, item


def _items(state, method, sub, vault, chain, payload, query, blob_store, arm_put):
    """chain after 'vaults/{v}': ['backupFabrics','Azure','protectionContainers',c,'protectedItems',i, ...]"""
    if len(chain) < 5 or chain[0].lower() != "backupfabrics" or chain[1].lower() != "azure" or chain[2].lower() != "protectioncontainers":
        return _err(404, "ResourceNotFound", "Unknown backup fabric path.")
    cont = chain[3]
    if len(chain) == 4 or chain[4].lower() != "protecteditems":
        return _err(404, "ResourceNotFound", "Unknown protection container path.")
    if len(chain) == 5:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        pre = f"{vault['id']}/backupFabrics/Azure/protectionContainers/{cont}/protectedItems/".lower()
        return _ok({"value": [_view(r) for k, r in state.items() if isinstance(r, dict) and k.startswith(pre) and r.get("_kind") == "item"]})
    iname = chain[5]
    rid = f"{vault['id']}/backupFabrics/Azure/protectionContainers/{cont}/protectedItems/{iname}"
    rec = state.get(rid.lower())
    rest = chain[6:]
    if not rest:
        return _item_crud(state, method, sub, vault, cont, iname, rid, rec, payload, query, blob_store)
    if rec is None:
        return _err(404, "ResourceNotFound", f"The protected item '{iname}' was not found.")
    r0 = rest[0].lower()
    if r0 == "backup" and method == "POST":
        return _backup_now(state, vault, rec, payload, blob_store)
    if r0 == "recoverypoints":
        if len(rest) == 1:
            return _ok({"value": [_view(r) for r in sorted(_children(state, rid, "recoverypoints"), key=lambda x: x["properties"]["recoveryPointTime"], reverse=True)]})
        rp = state.get(f"{rid}/recoveryPoints/{rest[1]}".lower())
        if rp is None:
            return _err(404, "ResourceNotFound", f"The recovery point '{rest[1]}' was not found.")
        if len(rest) == 2:
            if method == "GET":
                return _ok(_view(rp))
            if method == "DELETE":
                return _delete_rp(state, vault, rec, rp, blob_store)
        if len(rest) == 3 and rest[2].lower() == "restore" and method == "POST":
            return _restore(state, sub, vault, rec, rp, payload, blob_store, arm_put)
    return _err(404, "ResourceNotFound", f"Unknown protected item operation '{'/'.join(rest)}'.")


def _item_crud(state, method, sub, vault, cont, iname, rid, rec, payload, query, blob_store):
    if method == "GET":
        return _ok(_view(rec)) if rec else _err(404, "ResourceNotFound", f"The protected item '{iname}' was not found.")
    if method in ("PUT", "PATCH"):
        p = (payload or {}).get("properties") or {}
        is_vm = cont.lower().startswith("iaasvmcontainer;")
        is_share = cont.lower().startswith("storagecontainer;")
        if not (is_vm or is_share):
            return _err(400, "BMSUserErrorUnsupportedContainer", "Only Azure VM ('iaasvmcontainer;iaasvmcontainerv2;<rg>;<vm>') and Azure Files "
                        "('storagecontainer;Storage;<rg>;<account>') protection containers are supported.")
        mtype = "AzureIaasVM" if is_vm else "AzureStorage"
        if rec is not None and rec["properties"].get("isScheduledForDeferredDelete"):
            if not p.get("policyId"):
                return _err(400, "BMSUserErrorInvalidInput", "The item is soft-deleted; PUT it with a policyId to restore (undelete) it.")
            rec["properties"].update({"isScheduledForDeferredDelete": False, "deferredDeleteTimeInUTC": None, "deferredDeleteTimeRemaining": None,
                                      "isRehydrate": True, "protectionState": "IRPending" if not _children(state, rid, "recoverypoints") else "Protected",
                                      "policyId": p["policyId"], "policyName": p["policyId"].rsplit("/", 1)[-1]})
            _job(state, vault, "Undelete", rec["properties"]["friendlyName"], mtype)
            return _ok(_view(rec))
        if rec is not None and p.get("policyId") in ("", None) and (payload or {}).get("properties", {}).get("protectionState") == "ProtectionStopped":
            rec["properties"].update({"protectionState": "ProtectionStopped", "policyId": "", "policyName": None})
            _job(state, vault, "StopProtection", rec["properties"]["friendlyName"], mtype)
            return _ok(_view(rec))
        parts = cont.split(";")
        if len(parts) != 4:
            return _err(400, "BMSUserErrorInvalidContainer", "Container name must have 4 ';'-separated parts.")
        c_rg, c_res = parts[2], parts[3]
        source_id = p.get("sourceResourceId") or ""
        src = state.get(source_id.lower())
        pid = p.get("policyId") or ""
        pol = state.get(pid.lower())
        if pol is None or pol.get("_kind") != "policy" or not pid.lower().startswith(vault["id"].lower() + "/backuppolicies/"):
            return _err(400, "BMSUserErrorPolicyNotFound", f"policyId '{pid}' is not a backup policy of this vault.")
        if pol["properties"].get("backupManagementType") != mtype:
            return _err(400, "BMSUserErrorInvalidPolicyType", f"The policy '{pol['name']}' is a {pol['properties'].get('backupManagementType')} policy and cannot protect this {mtype} item.")
        if is_vm:
            if iname.lower() != f"vm;iaasvmcontainerv2;{c_rg};{c_res}".lower():
                return _err(400, "BMSUserErrorInvalidItem", f"Item name must be 'vm;iaasvmcontainerv2;{c_rg};{c_res}'.")
            if src is None or (src.get("_type") or "").lower() != "microsoft.compute/virtualmachines" or src["name"].lower() != c_res.lower() or (src.get("_rg") or "").lower() != c_rg.lower():
                return _err(404, "UserErrorVmNotFound", f"The virtual machine '{c_res}' in resource group '{c_rg}' (sourceResourceId '{source_id}') was not found.")
            friendly, ptype = src["name"], "Microsoft.Compute/virtualMachines"
        else:
            share_name = iname.split(";", 1)[1] if ";" in iname else ""
            if not iname.lower().startswith("azurefileshare;") or not share_name:
                return _err(400, "BMSUserErrorInvalidItem", "Item name must be 'azurefileshare;<share>'.")
            if src is None or (src.get("_type") or "").lower() != "microsoft.storage/storageaccounts" or src["name"].lower() != c_res.lower():
                return _err(404, "ResourceNotFound", f"The storage account '{c_res}' (sourceResourceId '{source_id}') was not found.")
            share = (src.get("_files_shares") or {}).get(share_name.lower())
            if not share or share.get("_deleted"):
                return _err(404, "BMSUserErrorFileShareNotFound", f"The file share '{share_name}' does not exist in storage account '{c_res}'.")
            friendly, ptype = share_name, "AzureFileShare"
        if str(src.get("location", "")).lower().replace(" ", "") != str(vault.get("location", "")).lower().replace(" ", ""):
            return _err(400, "BMSUserErrorSourceVaultRegionMismatch", f"The Recovery Services vault ({vault['location']}) and the source ({src.get('location')}) must be in the same region.")
        for v in state.values():
            if isinstance(v, dict) and v.get("_kind") == "item" and v is not rec and (v["properties"].get("sourceResourceId") or "").lower() == source_id.lower() \
                    and v["properties"].get("friendlyName") == friendly and not v["properties"].get("isScheduledForDeferredDelete"):
                return _err(409, "BMSUserErrorObjectAlreadyProtected", f"'{friendly}' is already protected by vault '{v['id'].split('/vaults/')[1].split('/')[0]}'.")
        props = {"protectedItemType": ptype, "backupManagementType": mtype, "workloadType": "VM" if is_vm else "AzureFileShare",
                 "containerName": cont, "sourceResourceId": source_id, "policyId": pid, "policyName": pol["name"],
                 "friendlyName": friendly, "virtualMachineId": source_id if is_vm else None, "protectionState": "IRPending",
                 "protectionStatus": "Healthy", "healthStatus": "Passed", "lastBackupStatus": None, "lastBackupTime": None,
                 "isScheduledForDeferredDelete": False, "backupSetName": friendly, "createMode": "Default"}
        newrec = {"id": rid, "name": iname, "type": f"{NS}/vaults/backupFabrics/protectionContainers/protectedItems", "location": vault["location"],
                  "etag": f'W/"datetime\'{_now()}\'"', "properties": props, "_kind": "item"}
        if rec is not None:
            newrec["properties"].update({k: rec["properties"][k] for k in ("lastBackupStatus", "lastBackupTime", "protectionState") if k in rec["properties"]})
            if rec["properties"].get("protectionState") == "ProtectionStopped":
                newrec["properties"]["protectionState"] = "IRPending" if not _children(state, rid, "recoverypoints") else "Protected"
        state[rid.lower()] = newrec
        _job(state, vault, "ConfigureBackup", friendly, mtype)
        return _ok(_view(newrec), 200)
    if method == "DELETE":
        if rec is None:
            return {"status": 204, "body": None}
        imm = vault["properties"]["securitySettings"]["immutabilitySettings"]["state"]
        mtype = rec["properties"]["backupManagementType"]
        rps = _children(state, rid, "recoverypoints")
        if imm == "Locked" and any(rp["_expiry"] > _now() for rp in rps):
            return _err(400, "BMSUserErrorImmutableVault", "The vault is immutable (Locked): backup data with unexpired recovery points cannot be deleted.")
        sd = vault["properties"]["securitySettings"]["softDeleteSettings"]
        if sd["softDeleteState"] in ("Enabled", "AlwaysON") and rps and not rec["properties"].get("isScheduledForDeferredDelete"):
            rec["properties"].update({"isScheduledForDeferredDelete": True, "protectionState": "ProtectionStopped",
                                      "deferredDeleteTimeInUTC": _now(sd["softDeleteRetentionPeriodInDays"]),
                                      "deferredDeleteTimeRemaining": f"P{sd['softDeleteRetentionPeriodInDays']}D", "policyId": "", "policyName": None})
            _job(state, vault, "DeleteBackupData", rec["properties"]["friendlyName"], mtype, extra={"softDeleted": True})
            return _ok(None, 200)
        for rp in rps:
            _art_delete(blob_store, rp["_artifact"])
            state.pop(rp["id"].lower(), None)
        state.pop(rid.lower())
        _job(state, vault, "DeleteBackupData", rec["properties"]["friendlyName"], mtype)
        return _ok(None, 200)
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


def _delete_rp(state, vault, item, rp, blob_store):
    if vault["properties"]["securitySettings"]["immutabilitySettings"]["state"] == "Locked" and rp["_expiry"] > _now():
        return _err(400, "BMSUserErrorImmutableVault", "The vault is immutable (Locked): an unexpired recovery point cannot be deleted.")
    _art_delete(blob_store, rp["_artifact"])
    state.pop(rp["id"].lower(), None)
    return _ok(None)


def _retention_days(pol):
    d = ((pol or {}).get("properties", {}).get("retentionPolicy") or {}).get("dailySchedule") or {}
    return (d.get("retentionDuration") or {}).get("count") or 30


def _backup_now(state, vault, item, payload, blob_store):
    ip = item["properties"]
    mtype = ip["backupManagementType"]
    if ip.get("isScheduledForDeferredDelete"):
        return _err(400, "BMSUserErrorSoftDeleted", "The item is soft-deleted; undelete it before taking a backup.")
    if ip["protectionState"] == "ProtectionStopped":
        return _err(400, "UserErrorBackupDisabled", "Protection is stopped for this item; resume protection before backing it up.")
    src = _find_source(state, item)
    if src is None:
        job = _job(state, vault, "Backup", ip["friendlyName"], mtype, "Failed", error=("UserErrorVmNotFound" if mtype == "AzureIaasVM" else "BMSUserErrorFileShareNotFound",
                   "The backup source no longer exists."))
        ip["lastBackupStatus"], ip["healthStatus"] = "Failed", "ActionRequired"
        return _err(400, "UserErrorSourceNotFound", "The backup source no longer exists.")
    exp = (payload or {}).get("properties", {}).get("recoveryPointExpiryTimeInUTC")
    pol = state.get((ip.get("policyId") or "").lower())
    if exp is not None and exp <= _now():
        return _err(400, "BMSUserErrorInvalidExpiry", "recoveryPointExpiryTimeInUTC must be in the future.")
    exp = exp or _now(_retention_days(pol))
    rid = str(uuid.uuid4().int)[:14]
    if mtype == "AzureIaasVM":
        doc = _snapshot_vm(state, src)
    else:
        share = (src.get("_files_shares") or {}).get(ip["friendlyName"].lower())
        doc = _snapshot_share(state, src, share)
    art, size = _art_put(blob_store, vault["name"], f"{ip['containerName'].replace(';', '_')}/{ip['friendlyName']}/{rid}.json", doc)
    when = _now()
    props = ({"objectType": "IaasVMRecoveryPoint", "recoveryPointType": "CrashConsistent", "recoveryPointTime": when, "sourceVMStorageType": "StandardHDD",
              "isSourceVMEncrypted": False, "isInstantIlrSessionActive": False, "recoveryPointTierDetails": [{"type": 1, "status": 1}],
              "originalStorageAccountOption": False, "osType": ((doc["properties"].get("storageProfile") or {}).get("osDisk") or {}).get("osType", "Linux"),
              "recoveryPointDiskConfiguration": {"numberOfDisksIncludedInBackup": len(doc["disks"]), "numberOfDisksAttachedToVm": len(doc["disks"])}}
             if mtype == "AzureIaasVM" else
             {"objectType": "AzureFileShareRecoveryPoint", "recoveryPointType": "FileSystemConsistent", "recoveryPointTime": when,
              "fileShareSnapshotUri": art.get("blob", ""), "recoveryPointSizeInGB": max(1, size // 1024 ** 3)})
    rprec = {"id": f"{item['id']}/recoveryPoints/{rid}", "name": rid, "type": f"{NS}/vaults/backupFabrics/protectionContainers/protectedItems/recoveryPoints",
             "properties": props, "_artifact": art, "_size": size, "_expiry": exp, "_kind": "rp"}
    state[rprec["id"].lower()] = rprec
    ip.update({"lastBackupStatus": "Completed", "lastBackupTime": when, "protectionState": "Protected", "healthStatus": "Passed",
               "lastRecoveryPoint": when})
    job = _job(state, vault, "Backup", ip["friendlyName"], mtype, extra={"recoveryPointId": rid, "backupSizeInBytes": size, "artifact": art.get("blob", "inline")})
    return _ok(None, 202, {"Location": f"{vault['id']}/backupOperations/{job['name']}?api-version=2024-04-01",
                           "Azure-AsyncOperation": f"{vault['id']}/backupOperations/{job['name']}?api-version=2024-04-01", "Retry-After": "0"})


def _restore(state, sub, vault, item, rp, payload, blob_store, arm_put):
    p = (payload or {}).get("properties") or {}
    ip = item["properties"]
    mtype = ip["backupManagementType"]
    doc = _art_get(blob_store, rp["_artifact"])
    if doc is None:
        return _err(500, "BMSUserErrorArtifactMissing", "The recovery point's backup artifact could not be read from the vault's storage.")
    rtype = p.get("recoveryType")
    if mtype == "AzureIaasVM":
        if p.get("objectType") not in (None, "IaasVMRestoreRequest", "IaasVMRestoreWithRehydrationRequest"):
            return _err(400, "InvalidRequestContent", "objectType must be IaasVMRestoreRequest.")
        if rtype not in ("OriginalLocation", "AlternateLocation", "RestoreDisks"):
            return _err(400, "InvalidRequestContent", "recoveryType must be OriginalLocation, AlternateLocation or RestoreDisks.")
        return _restore_vm(state, sub, vault, item, doc, p, rtype, blob_store, arm_put)
    if p.get("objectType") not in (None, "AzureFileShareRestoreRequest"):
        return _err(400, "InvalidRequestContent", "objectType must be AzureFileShareRestoreRequest.")
    if rtype not in ("OriginalLocation", "AlternateLocation"):
        return _err(400, "InvalidRequestContent", "recoveryType must be OriginalLocation or AlternateLocation.")
    return _restore_share(state, vault, item, doc, p, rtype)


def _job_resp(vault, job, extra_hdr=None):
    h = {"Location": f"{vault['id']}/backupOperations/{job['name']}?api-version=2024-04-01",
         "Azure-AsyncOperation": f"{vault['id']}/backupOperations/{job['name']}?api-version=2024-04-01", "Retry-After": "0"}
    return _ok(None, 202, h)


def _restore_vm(state, sub, vault, item, doc, p, rtype, blob_store, arm_put):
    name = doc["name"]
    short = uuid.uuid4().hex[:8]
    if rtype == "RestoreDisks":
        acct_id = p.get("storageAccountId") or ""
        acct = state.get(acct_id.lower())
        if acct is None or (acct.get("_type") or "").lower() != "microsoft.storage/storageaccounts":
            return _err(400, "BMSUserErrorStorageAccountNotFound", f"storageAccountId '{acct_id}' is not a storage account in this subscription.")
        trg = p.get("targetResourceGroupId") or ""
        if (state.get(trg.lower()) or {}).get("_type", "").lower() != "microsoft.resources/resourcegroups":
            return _err(400, "BMSUserErrorTargetResourceGroupNotFound", f"targetResourceGroupId '{trg}' does not exist.")
        trg_name = trg.rstrip("/").rsplit("/", 1)[-1]
        created = []
        for i, d in enumerate(doc["disks"]):
            dname = f"{name}-restored-{'os' if i == 0 else 'data' + str(i)}-{short}"
            dprops = {k: v for k, v in d["properties"].items() if k in ("diskSizeGB", "osType", "hyperVGeneration")}
            dprops["creationData"] = {"createOption": "Empty"}
            dprops.setdefault("diskSizeGB", 30)
            r = arm_put(f"/subscriptions/{sub}/resourceGroups/{trg_name}/providers/Microsoft.Compute/disks/{dname}", "2023-04-02",
                        {"location": doc["location"], "sku": d.get("sku") or {"name": "Standard_LRS"}, "properties": dprops,
                         "tags": {"vyomi:restoredFromVault": vault["name"], "vyomi:restoredVm": name}})
            if r["status"] >= 300:
                return _err(r["status"], (r["body"].get("error") or {}).get("code", "RestoreFailed"), (r["body"].get("error") or {}).get("message", "Creating a restored disk failed."))
            created.append(dname)
        cont = f"vmrestore-{short}"
        key = f"{acct['name']}/{cont}"
        if blob_store is not None:
            if not blob_store.container_exists(key):
                blob_store.create_container(key)
            _blob.dispatch(blob_store, "PUT", f"/{cont}/config{short}.json", {}, {"x-ms-blob-type": "BlockBlob", "content-type": "application/json"},
                           json.dumps({"vmName": name, "location": doc["location"], "properties": doc["properties"], "disks": created}).encode(), account=acct["name"])
        job = _job(state, vault, "Restore", name, "AzureIaasVM", extra={"restoreType": "RestoreDisks", "targetStorageAccount": acct["name"],
                   "restoredDisks": created, "configContainer": cont})
        return _job_resp(vault, job)
    target_id = p.get("targetVirtualMachineId") or ""
    t_rg, t_name = _split_rid(target_id)
    if rtype == "OriginalLocation":
        tgt = state.get(item["properties"]["sourceResourceId"].lower())
        if tgt is None:
            return _err(400, "UserErrorVmNotFound", "The original virtual machine no longer exists; restore to an alternate location or restore disks instead.")
        if str(((tgt.get("properties") or {}).get("extended") or {}).get("instanceView", {}).get("powerState", {}).get("code", "")) == "PowerState/running" and False:
            pass
        props = json.loads(json.dumps(doc["properties"]))
        tgt["properties"].update({k: v for k, v in props.items() if k in ("hardwareProfile", "osProfile", "diagnosticsProfile", "securityProfile")})
        tgt["tags"] = dict(doc.get("tags") or {}, **{"vyomi:restoredFromVault": vault["name"]})
        job = _job(state, vault, "Restore", name, "AzureIaasVM", extra={"restoreType": "OriginalLocation", "restoredVm": tgt["id"]})
        return _job_resp(vault, job)
    # AlternateLocation: a new VM + NIC
    if not t_name:
        return _err(400, "InvalidRequestContent", "targetVirtualMachineId is required for an alternate-location restore.")
    if state.get(target_id.lower()):
        return _err(409, "BMSUserErrorTargetVmExists", f"The virtual machine '{t_name}' already exists; choose a new name or restore to the original location.")
    trg = p.get("targetResourceGroupId") or f"/subscriptions/{sub}/resourceGroups/{t_rg}"
    trg_name = trg.rstrip("/").rsplit("/", 1)[-1]
    if (state.get(trg.lower()) or {}).get("_type", "").lower() != "microsoft.resources/resourcegroups":
        return _err(400, "BMSUserErrorTargetResourceGroupNotFound", f"targetResourceGroupId '{trg}' does not exist.")
    subnet_id = p.get("subnetId") or ""
    vnet_id = p.get("virtualNetworkId") or ""
    if not state.get(vnet_id.lower()):
        return _err(400, "BMSUserErrorVnetNotFound", f"virtualNetworkId '{vnet_id}' does not exist.")
    if not subnet_id.lower().startswith(vnet_id.lower() + "/subnets/") or not state.get(subnet_id.lower()):
        # subnets may live inside the vnet record only
        vn = state.get(vnet_id.lower())
        names = [s.get("name", "").lower() for s in ((vn.get("properties") or {}).get("subnets") or [])]
        if subnet_id.rsplit("/", 1)[-1].lower() not in names:
            return _err(400, "BMSUserErrorSubnetNotFound", f"subnetId '{subnet_id}' is not a subnet of the virtual network.")
    nic_name = f"{t_name}-nic-{short}"
    r = arm_put(f"/subscriptions/{sub}/resourceGroups/{trg_name}/providers/Microsoft.Network/networkInterfaces/{nic_name}", "2023-09-01",
                {"location": doc["location"], "properties": {"ipConfigurations": [{"name": "ipconfig1", "properties": {"subnet": {"id": subnet_id}, "privateIPAllocationMethod": "Dynamic"}}]}})
    if r["status"] >= 300:
        return _err(r["status"], (r["body"].get("error") or {}).get("code", "RestoreFailed"), (r["body"].get("error") or {}).get("message", "Creating the NIC failed."))
    nic_id = (r["body"] or {}).get("id") or f"/subscriptions/{sub}/resourceGroups/{trg_name}/providers/Microsoft.Network/networkInterfaces/{nic_name}"
    props = json.loads(json.dumps(doc["properties"]))
    props["networkProfile"] = {"networkInterfaces": [{"id": nic_id, "properties": {"primary": True}}]}
    props.pop("vmId", None)
    props.pop("provisioningState", None)
    (props.get("osProfile") or {}).pop("adminPassword", None)
    sp = props.get("storageProfile") or {}
    for d in [(sp.get("osDisk") or {})] + list(sp.get("dataDisks") or []):
        d.pop("managedDisk", None)
        d.pop("name", None)
        d["createOption"] = "FromImage" if d is sp.get("osDisk") else "Empty"
    r = arm_put(f"/subscriptions/{sub}/resourceGroups/{trg_name}/providers/Microsoft.Compute/virtualMachines/{t_name}", "2023-09-01",
                {"location": doc["location"], "tags": dict(doc.get("tags") or {}, **{"vyomi:restoredFromVault": vault["name"], "vyomi:restoredFrom": name}),
                 "zones": doc.get("zones"), "properties": props})
    if r["status"] >= 300:
        job = _job(state, vault, "Restore", name, "AzureIaasVM", "Failed", error=((r["body"].get("error") or {}).get("code", "RestoreFailed"), (r["body"].get("error") or {}).get("message", "")))
        return _err(r["status"], (r["body"].get("error") or {}).get("code", "RestoreFailed"), (r["body"].get("error") or {}).get("message", "Creating the VM failed."))
    job = _job(state, vault, "Restore", name, "AzureIaasVM", extra={"restoreType": "AlternateLocation", "restoredVm": target_id, "restoredNic": nic_id})
    return _job_resp(vault, job)


def _restore_share(state, vault, item, doc, p, rtype):
    src_acct = state.get(item["properties"]["sourceResourceId"].lower())
    tree = doc["tree"]
    copy_opt = p.get("copyOptions", "CreateCopy")
    if copy_opt not in RESTORE_COPY:
        return _err(400, "InvalidRequestContent", f"copyOptions must be one of {', '.join(RESTORE_COPY)}.")
    kind = p.get("restoreRequestType", "FullShareRestore")
    if kind not in ("FullShareRestore", "ItemLevelRestore"):
        return _err(400, "InvalidRequestContent", "restoreRequestType must be FullShareRestore or ItemLevelRestore.")
    if rtype == "OriginalLocation":
        acct, share_name = src_acct, item["properties"]["friendlyName"]
    else:
        td = p.get("targetDetails") or {}
        acct = state.get((td.get("targetResourceId") or "").lower())
        share_name = td.get("name")
        if acct is None or (acct.get("_type") or "").lower() != "microsoft.storage/storageaccounts" or not share_name:
            return _err(400, "BMSUserErrorInvalidTarget", "targetDetails.targetResourceId (storage account) and targetDetails.name (share) are required and must exist.")
    if acct is None:
        return _err(400, "BMSUserErrorFileShareNotFound", "The restore target storage account no longer exists.")
    share = (acct.get("_files_shares") or {}).get(str(share_name).lower())
    if share is None or share.get("_deleted"):
        return _err(400, "BMSUserErrorFileShareNotFound", f"The target file share '{share_name}' does not exist.")
    ttree = share.setdefault("_tree", {})
    specs = p.get("restoreFileSpecs") or []
    if kind == "ItemLevelRestore" and not specs:
        return _err(400, "InvalidRequestContent", "restoreFileSpecs is required for an item-level restore.")
    wanted = {}
    if kind == "FullShareRestore":
        wanted = {k: (k, v) for k, v in tree.items()}
    else:
        for sp in specs:
            path = (sp.get("path") or "").strip("/")
            tf = (sp.get("targetFolderPath") or "").strip("/")
            hit = {k: v for k, v in tree.items() if k == path or k.startswith(path + "/")}
            if not hit:
                return _err(400, "BMSUserErrorItemNotFound", f"'{path}' does not exist in the recovery point.")
            for k, v in hit.items():
                dest = (tf + "/" + k).strip("/") if tf else k
                wanted[k] = (dest, v)
    restored = skipped = 0
    conflicts = [d for d, v in wanted.values() if v["type"] == "file" and d in ttree and ttree[d]["type"] == "file"]
    if copy_opt == "FailOnConflict" and conflicts:
        job = _job(state, vault, "Restore", item["properties"]["friendlyName"], "AzureStorage", "Failed",
                   error=("BMSUserErrorFileConflict", f"{len(conflicts)} file(s) already exist in the target and copyOptions is FailOnConflict."))
        return _err(409, "BMSUserErrorFileConflict", f"{len(conflicts)} file(s) already exist in the target (e.g. '{conflicts[0]}') and copyOptions is FailOnConflict.")
    for src_path, (dest, node) in sorted(wanted.items()):
        parts = dest.split("/")
        for i in range(1, len(parts)):
            ttree.setdefault("/".join(parts[:i]), {"type": "directory", "modified": _now()})
        if node["type"] == "directory":
            ttree.setdefault(dest, dict(node))
            continue
        if dest in ttree and ttree[dest]["type"] == "file":
            if copy_opt == "Skip":
                skipped += 1
                continue
            if copy_opt == "CreateCopy":
                stem, dot, ext = dest.rpartition(".")
                dest = f"{stem}_restored_{uuid.uuid4().hex[:6]}.{ext}" if dot and "/" not in ext else f"{dest}_restored_{uuid.uuid4().hex[:6]}"
        ttree[dest] = dict(node, modified=_now())
        restored += 1
    job = _job(state, vault, "Restore", item["properties"]["friendlyName"], "AzureStorage",
               extra={"restoreType": kind, "filesRestored": restored, "filesSkipped": skipped, "target": f"{acct['name']}/{share_name}"})
    return _job_resp(vault, job)


# ── vault-level views ──────────────────────────────────────────────────────────────────
def _vault_views(state, method, sub, vault, chain, payload, query):
    k0 = chain[0].lower()
    if k0 == "backupjobs":
        jobs = sorted(_children(state, vault["id"], "backupjobs"), key=lambda j: j["properties"]["startTime"], reverse=True)
        if len(chain) == 1:
            return _ok({"value": [_view(j) for j in jobs]})
        j = state.get(f"{vault['id']}/backupJobs/{chain[1]}".lower())
        if j is None:
            return _err(404, "ResourceNotFound", f"The job '{chain[1]}' was not found.")
        return _ok(_view(j))
    if k0 == "backupoperations" and len(chain) == 2:
        j = state.get(f"{vault['id']}/backupJobs/{chain[1]}".lower())
        if j is None:
            return _err(404, "ResourceNotFound", "Operation not found.")
        st = "Succeeded" if j["properties"]["status"] == "Completed" else j["properties"]["status"]
        return _ok({"id": f"{vault['id']}/backupOperations/{chain[1]}", "name": chain[1], "status": st, "startTime": j["properties"]["startTime"],
                    "endTime": j["properties"]["endTime"], "properties": {"objectType": "OperationStatusJobExtendedInfo", "jobId": chain[1]}})
    if k0 == "backupoperationresults" and len(chain) == 2:
        return {"status": 204, "body": None}
    if k0 == "backupprotecteditems":
        rows = [_view(i) for i in _vault_items(state, vault["id"])]
        flt = (query or {}).get("$filter", "")
        mt = re.search(r"backupManagementType eq '([^']+)'", flt)
        if mt:
            rows = [r for r in rows if r["properties"]["backupManagementType"] == mt.group(1)]
        return _ok({"value": rows})
    if k0 == "backupprotectioncontainers":
        seen = {}
        for i in _vault_items(state, vault["id"]):
            c = i["properties"]["containerName"]
            seen.setdefault(c, {"id": f"{vault['id']}/backupFabrics/Azure/protectionContainers/{c}", "name": c,
                                "type": f"{NS}/vaults/backupFabrics/protectionContainers",
                                "properties": {"containerType": "IaasVMContainer" if c.lower().startswith("iaasvm") else "StorageContainer",
                                               "friendlyName": c.split(";")[-1], "backupManagementType": i["properties"]["backupManagementType"],
                                               "registrationStatus": "Registered", "healthStatus": "Healthy"}})
        return _ok({"value": list(seen.values())})
    if k0 == "backupusagesummaries":
        items = [i for i in _vault_items(state, vault["id"]) if not i["properties"].get("isScheduledForDeferredDelete")]
        by = {}
        for i in items:
            by[(i["properties"]["backupManagementType"], i["properties"]["workloadType"])] = by.get((i["properties"]["backupManagementType"], i["properties"]["workloadType"]), 0) + 1
        return _ok({"value": [{"unit": "Count", "currentValue": n, "limit": 0, "name": {"value": f"ProtectedItems_{m}_{w}", "localizedValue": f"{m} {w} protected items"}} for (m, w), n in by.items()]})
    if k0 == "backupstorageconfig" or k0 == "backupconfig":
        key = "vaultstorageconfig" if k0 == "backupstorageconfig" else "vaultconfig"
        cfg = vault["_vault_cfg"]
        sec = vault["properties"]["securitySettings"]["softDeleteSettings"]
        if method == "GET":
            if k0 == "backupstorageconfig":
                props = {"storageModelType": vault["properties"].get("backupStorageType", "GeoRedundant"), "storageType": vault["properties"].get("backupStorageType", "GeoRedundant"),
                         "storageTypeState": "Locked" if _vault_items(state, vault["id"]) else "Unlocked", "crossRegionRestoreFlag": cfg["crossRegionRestoreFlag"]}
            else:
                props = {"enhancedSecurityState": cfg["enhancedSecurityState"], "softDeleteFeatureState": "Enabled" if sec["softDeleteState"] == "AlwaysON" else sec["softDeleteState"],
                         "softDeleteRetentionPeriodInDays": sec["softDeleteRetentionPeriodInDays"], "isSoftDeleteFeatureStateEditable": sec["softDeleteState"] != "AlwaysON"}
            return _ok({"id": f"{vault['id']}/backup{'storage' if k0 == 'backupstorageconfig' else ''}config/{key}", "name": key, "type": f"{NS}/vaults/backup{'storage' if k0 == 'backupstorageconfig' else ''}config", "properties": props})
        if method in ("PUT", "PATCH"):
            p = (payload or {}).get("properties") or {}
            if k0 == "backupstorageconfig":
                st = p.get("storageModelType") or p.get("storageType")
                if st is not None:
                    if st not in STORAGE_TYPES:
                        return _err(400, "InvalidRequestContent", f"storageModelType must be one of {', '.join(STORAGE_TYPES)}.")
                    if st != vault["properties"].get("backupStorageType") and _vault_items(state, vault["id"]):
                        return _err(400, "BMSUserErrorStorageTypeLocked", "The storage replication type cannot be changed once items are protected in the vault.")
                    vault["properties"]["backupStorageType"] = st
                if "crossRegionRestoreFlag" in p:
                    if p["crossRegionRestoreFlag"] and vault["properties"].get("backupStorageType") != "GeoRedundant":
                        return _err(400, "BMSUserErrorCrrNeedsGrs", "Cross Region Restore requires GeoRedundant storage.")
                    cfg["crossRegionRestoreFlag"] = bool(p["crossRegionRestoreFlag"])
            else:
                st = p.get("softDeleteFeatureState")
                if st is not None:
                    if st not in SOFT_DELETE:
                        return _err(400, "InvalidRequestContent", f"softDeleteFeatureState must be one of {', '.join(SOFT_DELETE)}.")
                    if sec["softDeleteState"] == "AlwaysON" and st != "AlwaysON":
                        return _err(400, "BMSUserErrorSoftDeleteAlwaysOn", "Soft delete is AlwaysON and cannot be changed.")
                    sec["softDeleteState"] = st
                if p.get("softDeleteRetentionPeriodInDays") is not None:
                    d = p["softDeleteRetentionPeriodInDays"]
                    if not isinstance(d, int) or not 14 <= d <= 180:
                        return _err(400, "InvalidRequestContent", "softDeleteRetentionPeriodInDays must be 14-180.")
                    sec["softDeleteRetentionPeriodInDays"] = d
                if p.get("enhancedSecurityState") in ("Enabled", "Disabled"):
                    cfg["enhancedSecurityState"] = p["enhancedSecurityState"]
            return _vault_views(state, "GET", sub, vault, chain, None, query)
    return _err(404, "ResourceNotFound", f"Unknown vault operation '{'/'.join(chain)}'.")


# ── Site Recovery (VM disaster recovery) ───────────────────────────────────────────────
def _repl(state, method, sub, vault, chain, payload, arm_put):
    """chain after vault: replicationFabrics/{f}[/replicationProtectionContainers/{c}/replicationProtectedItems/{i}[/action]] | replicationJobs"""
    k0 = chain[0].lower()
    if k0 == "replicationjobs":
        rows = [_view(j) for j in _children(state, vault["id"], "replicationjobs")]
        return _ok({"value": sorted(rows, key=lambda j: j["properties"]["startTime"], reverse=True)})
    if k0 == "replicationprotecteditems" and len(chain) == 1:
        return _ok({"value": [_view(r) for r in _vault_repl(state, vault["id"])]})
    if k0 != "replicationfabrics":
        return _err(404, "ResourceNotFound", "Unknown replication path.")
    if len(chain) == 1:
        return _ok({"value": [_view(r) for r in _children(state, vault["id"], "replicationfabrics")]})
    fab_name = chain[1]
    fid = f"{vault['id']}/replicationFabrics/{fab_name}"
    if len(chain) == 2:
        if method == "GET":
            f = state.get(fid.lower())
            return _ok(_view(f)) if f else _err(404, "ResourceNotFound", f"Fabric '{fab_name}' was not found.")
        if method == "PUT":
            loc = ((payload or {}).get("properties") or {}).get("customDetails", {}).get("location") or vault["location"]
            f = {"id": fid, "name": fab_name, "type": f"{NS}/vaults/replicationFabrics", "location": vault["location"],
                 "properties": {"friendlyName": loc, "internalIdentifier": str(uuid.uuid4()), "bcdrState": "Valid", "customDetails": {"instanceType": "Azure", "location": loc}},
                 "_kind": "fabric"}
            state[fid.lower()] = f
            state[f"{fid}/replicationProtectionContainers/default".lower()] = {
                "id": f"{fid}/replicationProtectionContainers/default", "name": "default", "type": f"{NS}/vaults/replicationFabrics/replicationProtectionContainers",
                "properties": {"fabricFriendlyName": loc, "friendlyName": "default", "fabricType": "Azure", "protectedItemCount": 0, "pairingStatus": "Paired", "role": "Primary"}, "_kind": "container"}
            return _ok(_view(f), 200)
    if state.get(fid.lower()) is None:
        return _err(404, "ResourceNotFound", f"Fabric '{fab_name}' was not found.")
    if len(chain) >= 4 and chain[2].lower() == "replicationprotectioncontainers":
        cont = chain[3]
        if len(chain) == 4:
            c = state.get(f"{fid}/replicationProtectionContainers/{cont}".lower())
            return _ok(_view(c)) if c else _err(404, "ResourceNotFound", f"Container '{cont}' was not found.")
        if chain[4].lower() == "replicationprotecteditems":
            return _repl_items(state, method, sub, vault, fid, cont, chain[5:], payload, arm_put)
    return _err(404, "ResourceNotFound", "Unknown replication path.")


def _rjob(state, vault, name, entity, status="Succeeded", errors=None):
    jid = str(uuid.uuid4())
    rec = {"id": f"{vault['id']}/replicationJobs/{jid}", "name": jid, "type": f"{NS}/vaults/replicationJobs",
           "properties": {"activityId": str(uuid.uuid4()), "scenarioName": name, "friendlyName": name, "state": status, "targetObjectName": entity,
                          "startTime": _now(), "endTime": _now(), "errors": errors or [], "allowedActions": [], "targetInstanceType": "ReplicationProtectedItem"}, "_kind": "rjob"}
    state[rec["id"].lower()] = rec
    return rec


def _repl_items(state, method, sub, vault, fid, cont, rest, payload, arm_put):
    base = f"{fid}/replicationProtectionContainers/{cont}/replicationProtectedItems"
    if not rest:
        return _ok({"value": [_view(r) for r in state.values() if isinstance(r, dict) and r.get("_kind") == "repl" and r["id"].lower().startswith(base.lower() + "/")]})
    iname = rest[0]
    rid = f"{base}/{iname}"
    rec = state.get(rid.lower())
    if len(rest) == 1:
        if method == "GET":
            return _ok(_view(rec)) if rec else _err(404, "ResourceNotFound", f"Replicated item '{iname}' was not found.")
        if method == "PUT":
            if rec is not None:
                return _err(409, "ReplicationAlreadyEnabled", f"Replication is already enabled for '{iname}'.")
            p = (payload or {}).get("properties") or {}
            det = p.get("providerSpecificDetails") or {}
            if det.get("instanceType") != "A2A":
                return _err(400, "InvalidRequestContent", "providerSpecificDetails.instanceType must be A2A (Azure to Azure).")
            fab = state[fid.lower()]
            src_vm_id = det.get("fabricObjectId") or p.get("fabricObjectId") or ""
            src = state.get(src_vm_id.lower())
            if src is None or (src.get("_type") or "").lower() != "microsoft.compute/virtualmachines":
                return _err(404, "ResourceNotFound", f"The source virtual machine '{src_vm_id}' does not exist.")
            if str(src.get("location", "")).lower().replace(" ", "") != str(vault["location"]).lower().replace(" ", "") and False:
                pass
            tloc = (det.get("recoveryAzureLocation") or "").lower().replace(" ", "")
            trg = det.get("recoveryResourceGroupId") or ""
            if not tloc:
                return _err(400, "InvalidRequestContent", "recoveryAzureLocation is required.")
            if tloc == str(src.get("location", "")).lower().replace(" ", ""):
                return _err(400, "ReplicationTargetSameAsSource", "The target region must differ from the source VM's region.")
            if (state.get(trg.lower()) or {}).get("_type", "").lower() != "microsoft.resources/resourcegroups":
                return _err(400, "InvalidRecoveryResourceGroup", f"recoveryResourceGroupId '{trg}' does not exist.")
            for r in _vault_repl(state, vault["id"]):
                if r["properties"]["providerSpecificDetails"].get("fabricObjectId", "").lower() == src_vm_id.lower():
                    return _err(409, "ReplicationAlreadyEnabled", f"Replication is already enabled for '{src['name']}'.")
            new = {"id": rid, "name": iname, "type": f"{NS}/vaults/replicationFabrics/replicationProtectionContainers/replicationProtectedItems",
                   "location": vault["location"],
                   "properties": {"friendlyName": src["name"], "protectedItemType": "A2A", "replicationHealth": "Normal", "protectionState": "Protected",
                                  "protectionStateDescription": "Protected", "activeLocation": "Primary", "testFailoverState": "None",
                                  "allowedOperations": ["TestFailover", "UnplannedFailover", "DisableProtection"], "recoveryFabricFriendlyName": tloc,
                                  "providerSpecificDetails": {"instanceType": "A2A", "fabricObjectId": src_vm_id, "primaryFabricLocation": src.get("location"),
                                                              "recoveryFabricLocation": tloc, "recoveryAzureResourceGroupId": trg, "monitoringJobType": "InitialReplication",
                                                              "lastRpoCalculatedTime": _now(), "rpoInSeconds": 0, "replicationStrategy": "Snapshot-based"}},
                   "_kind": "repl", "_snapshot": _snapshot_vm(state, src)}
            state[rid.lower()] = new
            _rjob(state, vault, "EnableDr", src["name"])
            return _ok(_view(new), 200)
        if method == "DELETE":
            if rec is None:
                return {"status": 204, "body": None}
            if rec["properties"].get("testFailoverState") == "InProgress":
                return _err(400, "TestFailoverInProgress", "Clean up the test failover before disabling replication.")
            state.pop(rid.lower())
            _rjob(state, vault, "DisableDr", rec["properties"]["friendlyName"])
            return _ok(None)
        return _err(405, "MethodNotAllowed", f"{method} not allowed.")
    if rec is None:
        return _err(404, "ResourceNotFound", f"Replicated item '{iname}' was not found.")
    act = rest[1].lower()
    if method != "POST" or act not in A2A_ACTIONS:
        return _err(404, "ResourceNotFound", f"Unknown replicated item action '{rest[1]}'.")
    ip = rec["properties"]
    det = ip["providerSpecificDetails"]
    snap = rec["_snapshot"]
    p = ((payload or {}).get("properties") or {})
    if act in ("testfailover", "unplannedfailover", "plannedfailover"):
        if act == "testfailover" and ip["testFailoverState"] == "InProgress":
            return _err(400, "TestFailoverInProgress", "A test failover is already in progress; clean it up first.")
        if act != "testfailover" and ip["testFailoverState"] == "InProgress":
            return _err(400, "TestFailoverInProgress", "Clean up the test failover before running a failover.")
        if act != "testfailover" and ip["activeLocation"] != "Primary":
            return _err(400, "FailoverNotAllowed", "The item is already failed over to the recovery region.")
        net = (p.get("providerSpecificDetails") or {}).get("recoveryAzureNetworkId") or (p.get("networkId") or "")
        trg_name = det["recoveryAzureResourceGroupId"].rstrip("/").rsplit("/", 1)[-1]
        t_name = f"{snap['name']}-{'test' if act == 'testfailover' else 'dr'}"
        if state.get(f"/subscriptions/{sub}/resourceGroups/{trg_name}/providers/Microsoft.Compute/virtualMachines/{t_name}".lower()):
            return _err(409, "TargetVmExists", f"The VM '{t_name}' already exists in the recovery resource group.")
        if not net:
            return _err(400, "InvalidRequestContent", "providerSpecificDetails.recoveryAzureNetworkId (test network) is required.")
        vn = state.get(net.lower())
        if vn is None or (vn.get("_type") or "").lower() != "microsoft.network/virtualnetworks":
            return _err(400, "RecoveryNetworkNotFound", f"The recovery virtual network '{net}' does not exist.")
        subnets = [s.get("name") for s in ((vn.get("properties") or {}).get("subnets") or [])]
        if not subnets:
            return _err(400, "RecoveryNetworkNotFound", "The recovery virtual network has no subnet.")
        subnet_id = f"{net}/subnets/{subnets[0]}"
        nic = f"{t_name}-nic"
        r = arm_put(f"/subscriptions/{sub}/resourceGroups/{trg_name}/providers/Microsoft.Network/networkInterfaces/{nic}", "2023-09-01",
                    {"location": det["recoveryFabricLocation"], "properties": {"ipConfigurations": [{"name": "ipconfig1", "properties": {"subnet": {"id": subnet_id}, "privateIPAllocationMethod": "Dynamic"}}]}})
        if r["status"] >= 300:
            return _err(r["status"], "FailoverFailed", (r["body"].get("error") or {}).get("message", "NIC creation failed."))
        nic_id = (r["body"] or {}).get("id") or ""
        props = json.loads(json.dumps(snap["properties"]))
        props["networkProfile"] = {"networkInterfaces": [{"id": nic_id, "properties": {"primary": True}}]}
        props.pop("vmId", None)
        props.pop("provisioningState", None)
        (props.get("osProfile") or {}).pop("adminPassword", None)
        spf = props.get("storageProfile") or {}
        for d in [(spf.get("osDisk") or {})] + list(spf.get("dataDisks") or []):
            d.pop("managedDisk", None)
            d.pop("name", None)
            d["createOption"] = "FromImage" if d is spf.get("osDisk") else "Empty"
        r = arm_put(f"/subscriptions/{sub}/resourceGroups/{trg_name}/providers/Microsoft.Compute/virtualMachines/{t_name}", "2023-09-01",
                    {"location": det["recoveryFabricLocation"], "tags": dict(snap.get("tags") or {}, **{"vyomi:drFrom": snap["name"], "vyomi:drMode": "test" if act == "testfailover" else "failover"}), "properties": props})
        if r["status"] >= 300:
            return _err(r["status"], "FailoverFailed", (r["body"].get("error") or {}).get("message", "Creating the replica VM failed."))
        rec["_replica"] = f"/subscriptions/{sub}/resourceGroups/{trg_name}/providers/Microsoft.Compute/virtualMachines/{t_name}"
        rec["_nic"] = nic_id
        if act == "testfailover":
            ip["testFailoverState"] = "InProgress"
            ip["allowedOperations"] = ["TestFailoverCleanup"]
        else:
            ip["activeLocation"], ip["protectionState"] = "Recovery", "PendingCommit"
            ip["allowedOperations"] = ["Commit", "ReProtect"]
            det["recoveryFabricLocation"], det["primaryFabricLocation"] = det["primaryFabricLocation"], det["recoveryFabricLocation"]
        det["failoverRecoveryPointId"] = str(uuid.uuid4())
        job = _rjob(state, vault, "TestFailover" if act == "testfailover" else "UnplannedFailover", snap["name"])
        return _ok(_view(job), 200, {"Location": job["id"]})
    if act == "testfailovercleanup":
        if ip["testFailoverState"] != "InProgress":
            return _err(400, "NoTestFailoverInProgress", "There is no test failover to clean up.")
        for key in ("_replica", "_nic"):
            state.pop(rec.pop(key, "").lower(), None)
        ip["testFailoverState"], ip["allowedOperations"] = "None", ["TestFailover", "UnplannedFailover", "DisableProtection"]
        return _ok(_view(_rjob(state, vault, "TestFailoverCleanup", snap["name"])))
    if act == "commit":
        if ip["protectionState"] != "PendingCommit":
            return _err(400, "CommitNotAllowed", "Commit is only valid after a failover.")
        ip["protectionState"], ip["allowedOperations"] = "UnprotectedAfterFailover", ["ReProtect", "DisableProtection"]
        return _ok(_view(_rjob(state, vault, "Commit", snap["name"])))
    if act == "reprotect":
        if ip["activeLocation"] != "Recovery":
            return _err(400, "ReprotectNotAllowed", "Re-protect is only valid after a failover.")
        ip.update({"protectionState": "Protected", "replicationHealth": "Normal", "allowedOperations": ["TestFailover", "UnplannedFailover", "DisableProtection"]})
        return _ok(_view(_rjob(state, vault, "Reprotect", snap["name"])))
    return _err(400, "InvalidRequest", "Unsupported action.")


# ── entry point ────────────────────────────────────────────────────────────────────────
def backup_status(state, sub, loc, payload):
    """POST /subscriptions/{s}/providers/Microsoft.RecoveryServices/locations/{loc}/backupStatus"""
    rid = (payload or {}).get("resourceId") or ""
    for i in state.values():
        if isinstance(i, dict) and i.get("_kind") == "item" and (i["properties"].get("sourceResourceId") or "").lower() == rid.lower() \
                and not i["properties"].get("isScheduledForDeferredDelete"):
            vid = i["id"].split("/backupFabrics/")[0]
            return _ok({"protectionStatus": "Protected", "vaultId": vid, "fabricName": "Azure", "containerName": i["properties"]["containerName"],
                        "protectedItemName": i["name"], "policyName": i["properties"].get("policyName")})
    return _ok({"protectionStatus": "NotProtected"})


def dispatch(state, method, sub, rg, chain, payload, query, blob_store=None, arm_put=None, base=""):
    """chain after 'providers/Microsoft.RecoveryServices'."""
    if not chain:
        return _err(404, "ResourceNotFound", "Unknown Microsoft.RecoveryServices resource type.")
    if chain[0].lower() == "locations" and len(chain) == 3 and chain[2].lower() == "backupstatus" and method == "POST":
        return backup_status(state, sub, chain[1], payload)
    if chain[0].lower() != "vaults":
        return _err(404, "ResourceNotFound", "Unknown Microsoft.RecoveryServices resource type.")
    if len(chain) == 1:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        return _ok({"value": [_view(r) for r in state.values() if isinstance(r, dict) and (r.get("_type") or "") == VAULT and r.get("_sub") == sub
                              and (rg is None or (r.get("_rg") or "").lower() == rg.lower())]})
    if rg is None:
        return _err(400, "InvalidRequest", "A vault path needs a resource group.")
    rid = f"/subscriptions/{sub}/resourceGroups/{rg}/providers/{NS}/vaults/{chain[1]}"
    vault = state.get(rid.lower())
    if len(chain) == 2:
        return _vault(state, method, sub, rg, chain[1], rid, vault, payload, blob_store)
    if vault is None:
        return _err(404, "ResourceNotFound", f"The Resource '{NS}/vaults/{chain[1]}' under resource group '{rg}' was not found.")
    rest = chain[2:]
    k = rest[0].lower()
    if k == "backuppolicies":
        return _policies(state, method, vault, rest[1:], payload)
    if k == "backupfabrics":
        return _items(state, method, sub, vault, rest, payload, query, blob_store, arm_put)
    if k == "backupprevalidateprotection" and method == "POST":
        rid_src = (((payload or {}).get("properties") or {}).get("resourceId")) or ""
        if not state.get(rid_src.lower()):
            return _err(404, "ResourceNotFound", f"The resource '{rid_src}' was not found.")
        return {"status": 200, "body": None}
    if k.startswith("replication"):
        return _repl(state, method, sub, vault, rest, payload, arm_put)
    return _vault_views(state, method, sub, vault, rest, payload, query)


# ── Storage account geo-replication + customer-initiated failover ──────────────────────
PAIRS = {"eastus": "westus", "westus": "eastus", "eastus2": "centralus", "centralus": "eastus2", "westus2": "westcentralus",
         "westcentralus": "westus2", "northcentralus": "southcentralus", "southcentralus": "northcentralus", "westeurope": "northeurope",
         "northeurope": "westeurope", "uksouth": "ukwest", "ukwest": "uksouth", "southeastasia": "eastasia", "eastasia": "southeastasia",
         "centralindia": "southindia", "southindia": "centralindia", "japaneast": "japanwest", "japanwest": "japaneast",
         "australiaeast": "australiasoutheast", "australiasoutheast": "australiaeast", "canadacentral": "canadaeast", "canadaeast": "canadacentral"}
GEO_SKUS = ("Standard_GRS", "Standard_RAGRS", "Standard_GZRS", "Standard_RAGZRS")


def storage_after_put(state, rec):
    """Derive the secondary region + geo-replication stats from the account SKU (the real RP does this server-side)."""
    sku = (rec.get("sku") or {}).get("name", "")
    p = rec.setdefault("properties", {})
    loc = str(rec.get("location", "")).lower().replace(" ", "")
    if sku in GEO_SKUS and loc in PAIRS:
        p["secondaryLocation"] = PAIRS[loc]
        p["statusOfPrimary"], p["statusOfSecondary"] = "available", "available"
        p["geoReplicationStats"] = {"status": "Live", "lastSyncTime": _now(), "canFailover": True, "canPlannedFailover": True}
        if sku.startswith("Standard_RA"):
            acct = rec["name"]
            p["secondaryEndpoints"] = {"blob": f"https://{acct}-secondary.blob.core.windows.net/", "queue": f"https://{acct}-secondary.queue.core.windows.net/",
                                       "table": f"https://{acct}-secondary.table.core.windows.net/", "file": f"https://{acct}-secondary.file.core.windows.net/"}
        else:
            p.pop("secondaryEndpoints", None)
    else:
        for k in ("secondaryLocation", "statusOfSecondary", "geoReplicationStats", "secondaryEndpoints"):
            p.pop(k, None)


def storage_failover(state, rec, query):
    sku = (rec.get("sku") or {}).get("name", "")
    p = rec.get("properties") or {}
    if sku not in GEO_SKUS or not p.get("secondaryLocation"):
        return _err(400, "AccountFailoverNotSupported", f"The storage account '{rec['name']}' ({sku or 'no sku'}) is not geo-redundant (GRS/RA-GRS/GZRS/RA-GZRS); customer-initiated failover is not available.")
    if (query or {}).get("failoverType", "Unplanned") not in ("Planned", "Unplanned"):
        return _err(400, "InvalidQueryParameterValue", "failoverType must be Planned or Unplanned.")
    old = rec["location"]
    rec["location"] = p["secondaryLocation"]
    p["primaryLocation"] = rec["location"]
    rec["sku"] = dict(rec["sku"], name="Standard_LRS")      # the real RP converts the account to LRS in the new primary
    storage_after_put(state, rec)
    p["lastGeoFailoverTime"] = _now()
    rec["_failover_from"] = old
    return _ok(None, 200)
