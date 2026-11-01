"""Azure Blob Storage WAVE 5b gap-sweep conformance — redundancy's RA secondary endpoint,
soft delete (blobs + containers), versioning, change feed and request telemetry, all
ENFORCED by core/azure_blob_core.py (see its module docstring, "v4 WAVE 5b" section).

Run on host:    python3 tests/conformance/test_azure_storage_wave5b_core.py
Run in Pyodide: loaded by the wasm/ harness (same file).
"""
from datetime import datetime, timedelta, timezone

try:
    from core import azure_blob_core as az
    from core.azure_arm_core import AzureArm
except ImportError:  # pragma: no cover - Pyodide flat layout
    import azure_blob_core as az  # type: ignore
    from azure_arm_core import AzureArm  # type: ignore

ACCT = "uicstorage"
RID = f"/subscriptions/sub1/resourcegroups/uic-rg/providers/microsoft.storage/storageaccounts/{ACCT}"
sk = lambda a: {"authorization": f"SharedKey {a}:c2lnbmF0dXJl", "x-ms-version": az.X_MS_VERSION}


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def _text(r):
    return r.body.decode()


def _http_date(dt: datetime) -> str:
    return dt.strftime("%a, %d %b %Y %H:%M:%S GMT")


def run() -> int:
    st = az.AzureBlobStore()
    arm_state = {RID: {"sku": {"name": "Standard_LRS"}, "properties": {}}}

    # ── Redundancy: the secondary endpoint is a real, read-only alias ──────────────────
    az.dispatch(st, "PUT", f"/{ACCT}/data", {"restype": "container"}, sk(ACCT), b"", arm_state=arm_state)
    az.dispatch(st, "PUT", f"/{ACCT}/data/x.txt", {}, {**sk(ACCT), "x-ms-blob-type": "BlockBlob"}, b"hello", arm_state=arm_state)

    no_ra = az.dispatch(st, "GET", f"/{ACCT}-secondary/data/x.txt", {}, sk(f"{ACCT}-secondary"), b"", arm_state=arm_state)
    _check("secondary 404s when the sku is not RA-*", no_ra.status == 404)
    _check("secondary 404 error code", no_ra.headers.get("x-ms-error-code") == "ResourceNotFound")

    arm_state[RID]["sku"]["name"] = "Standard_RAGRS"
    ra_get = az.dispatch(st, "GET", f"/{ACCT}-secondary/data/x.txt", {}, sk(f"{ACCT}-secondary"), b"", arm_state=arm_state)
    _check("RA-GRS secondary read succeeds", ra_get.status == 200 and ra_get.body == b"hello")
    ra_put = az.dispatch(st, "PUT", f"/{ACCT}-secondary/data/y.txt", {}, {**sk(f"{ACCT}-secondary"), "x-ms-blob-type": "BlockBlob"}, b"no", arm_state=arm_state)
    _check("RA-GRS secondary is read-only", ra_put.status == 403)
    _check("RA-GRS secondary read-only error code", ra_put.headers.get("x-ms-error-code") == "OperationNotAllowedOnSecondary")

    # ── Soft delete: blobs ──────────────────────────────────────────────────────────────
    arm_state[RID + "/blobservices/default"] = {"properties": {
        "deleteRetentionPolicy": {"enabled": True, "days": 7},
        "containerDeleteRetentionPolicy": {"enabled": True, "days": 7},
        "isVersioningEnabled": True, "changeFeed": {"enabled": True},
    }}
    az.dispatch(st, "DELETE", f"/{ACCT}/data/x.txt", {}, sk(ACCT), b"", arm_state=arm_state)
    gone = az.dispatch(st, "GET", f"/{ACCT}/data/x.txt", {}, sk(ACCT), b"", arm_state=arm_state)
    _check("soft-deleted blob is invisible to a normal GET", gone.status == 404)
    listing = _text(az.dispatch(st, "GET", f"/{ACCT}/data", {"restype": "container", "comp": "list"}, sk(ACCT), b"", arm_state=arm_state))
    _check("soft-deleted blob absent from a normal listing", "x.txt" not in listing)
    listing_deleted = _text(az.dispatch(st, "GET", f"/{ACCT}/data", {"restype": "container", "comp": "list", "include": "deleted"}, sk(ACCT), b"", arm_state=arm_state))
    _check("include=deleted shows the soft-deleted blob", "<Name>x.txt</Name>" in listing_deleted and "<Deleted>true</Deleted>" in listing_deleted)

    undel = az.dispatch(st, "PUT", f"/{ACCT}/data/x.txt", {"comp": "undelete"}, sk(ACCT), b"", arm_state=arm_state)
    _check("undelete blob 200", undel.status == 200)
    back = az.dispatch(st, "GET", f"/{ACCT}/data/x.txt", {}, sk(ACCT), b"", arm_state=arm_state)
    _check("undeleted blob is readable again", back.status == 200 and back.body == b"hello")

    # retention expiry is purged lazily on list
    az.dispatch(st, "DELETE", f"/{ACCT}/data/x.txt", {}, sk(ACCT), b"", arm_state=arm_state)
    st.deleted_blobs[f"{ACCT}/data"]["x.txt"]["deleted_at"] = datetime.now(timezone.utc) - timedelta(days=30)
    az.dispatch(st, "GET", f"/{ACCT}/data", {"restype": "container", "comp": "list"}, sk(ACCT), b"", arm_state=arm_state)
    _check("an expired soft-deleted blob is purged for real", "x.txt" not in st.deleted_blobs.get(f"{ACCT}/data", {}))

    # ── Soft delete: containers ─────────────────────────────────────────────────────────
    az.dispatch(st, "PUT", f"/{ACCT}/keep", {"restype": "container"}, sk(ACCT), b"", arm_state=arm_state)
    az.dispatch(st, "DELETE", f"/{ACCT}/keep", {"restype": "container"}, sk(ACCT), b"", arm_state=arm_state)
    gone_c = az.dispatch(st, "GET", f"/{ACCT}/keep", {"restype": "container"}, sk(ACCT), b"", arm_state=arm_state)
    _check("soft-deleted container is gone from a normal GET", gone_c.status == 404)
    clist = _text(az.dispatch(st, "GET", f"/{ACCT}", {"comp": "list", "include": "deleted"}, sk(ACCT), b"", arm_state=arm_state))
    _check("include=deleted shows the soft-deleted container", "<Name>keep</Name>" in clist and "<Deleted>true</Deleted>" in clist)
    undel_c = az.dispatch(st, "PUT", f"/{ACCT}/keep", {"restype": "container", "comp": "undelete"}, sk(ACCT), b"", arm_state=arm_state)
    _check("undelete container 201", undel_c.status == 201)
    back_c = az.dispatch(st, "GET", f"/{ACCT}/keep", {"restype": "container"}, sk(ACCT), b"", arm_state=arm_state)
    _check("undeleted container is reachable again", back_c.status == 200)

    # ── Versioning ───────────────────────────────────────────────────────────────────────
    v1 = az.dispatch(st, "PUT", f"/{ACCT}/data/v.txt", {}, {**sk(ACCT), "x-ms-blob-type": "BlockBlob"}, b"v1", arm_state=arm_state)
    v1_id = v1.headers["etag"]
    az.dispatch(st, "PUT", f"/{ACCT}/data/v.txt", {}, {**sk(ACCT), "x-ms-blob-type": "BlockBlob"}, b"v2", arm_state=arm_state)
    cur = az.dispatch(st, "GET", f"/{ACCT}/data/v.txt", {}, sk(ACCT), b"", arm_state=arm_state)
    _check("current version is the latest write", cur.body == b"v2")
    old = az.dispatch(st, "GET", f"/{ACCT}/data/v.txt", {"versionid": v1_id}, sk(ACCT), b"", arm_state=arm_state)
    _check("a prior version is still fetchable by versionid", old.status == 200 and old.body == b"v1")
    vlist = _text(az.dispatch(st, "GET", f"/{ACCT}/data", {"restype": "container", "comp": "list", "include": "versions"}, sk(ACCT), b"", arm_state=arm_state))
    _check("include=versions lists both versions of v.txt", vlist.count("<Name>v.txt</Name>") == 2)

    # ── Change feed ──────────────────────────────────────────────────────────────────────
    feed = az.dispatch(st, "GET", f"/{ACCT}", {"comp": "changefeed"}, sk(ACCT), b"", arm_state=arm_state)
    _check("change feed is readable", feed.status == 200)
    import json
    feed_events = json.loads(feed.body)["value"]
    _check("change feed recorded real BlobCreated/BlobDeleted events", any(e["event"] == "BlobCreated" for e in feed_events)
           and any(e["event"] == "BlobDeleted" for e in feed_events))

    # ── Request telemetry: real counters + gated diagnostic log ────────────────────────
    stats = az.account_metrics(st, ACCT)
    _check("account_metrics reports a real transaction count", stats["transactions"] > 0)
    _check("account_metrics reports real capacity/blob/container counts", stats["blobCount"] >= 1 and stats["containerCount"] >= 1)

    log_no_diag = json.loads(az.dispatch(st, "GET", f"/{ACCT}", {"comp": "diagnosticlog"}, sk(ACCT), b"", arm_state=arm_state).body)
    _check("no diagnostic setting -> no forwarded log rows", log_no_diag["value"] == [] and log_no_diag["enabledCategories"] == [])

    arm_state[f"{RID}/providers/microsoft.insights/diagnosticsettings/toblob"] = {
        "_diag_scope": RID, "properties": {"storageAccountId": "x", "logs": [{"category": "StorageWrite", "enabled": True}]},
    }
    log_with_diag = json.loads(az.dispatch(st, "GET", f"/{ACCT}", {"comp": "diagnosticlog"}, sk(ACCT), b"", arm_state=arm_state).body)
    _check("an enabled StorageWrite diagnostic category forwards write rows",
           any(r["category"] == "StorageWrite" for r in log_with_diag["value"]))
    _check("a non-enabled category (StorageRead) stays filtered out",
           not any(r["category"] == "StorageRead" for r in log_with_diag["value"]))

    # ── Microsoft.Insights/metrics (real ARM extension, see azure_arm_core._metrics /
    #    azure_monitor_core.get_storage_metrics) end to end over the SAME blob store ──────
    arm = AzureArm()
    arm.blob_store = st
    rid_path = f"/subscriptions/sub1/resourceGroups/uic-rg/providers/Microsoft.Storage/storageAccounts/{ACCT}"
    created = arm.handle("PUT", rid_path, {"api-version": "2023-01-01"}, {"location": "eastus"})
    _check("ARM create of the same account for the metrics extension", created["status"] == 200)
    m = arm.handle("GET", rid_path + "/providers/Microsoft.Insights/metrics",
                   {"api-version": "2018-01-01", "metricnames": "UsedCapacity,Transactions"})
    _check("Microsoft.Insights/metrics 200s for a storage account", m["status"] == 200)
    metric_names = {v["name"]["value"]: v["timeseries"][0]["data"][0]["total"] for v in m["body"]["value"]}
    _check("UsedCapacity reflects real blob bytes", metric_names["UsedCapacity"] == stats["usedCapacity"])
    _check("Transactions reflects real request count", metric_names["Transactions"] == stats["transactions"])
    other = arm.handle("PUT", "/subscriptions/sub1/resourceGroups/uic-rg/providers/Microsoft.Network/virtualNetworks/vnet1",
                       {"api-version": "2023-11-01"}, {"location": "eastus"})
    _check("ARM create of an unrelated resource", other["status"] == 200)
    m2 = arm.handle("GET", "/subscriptions/sub1/resourceGroups/uic-rg/providers/Microsoft.Network/virtualNetworks/vnet1"
                     "/providers/Microsoft.Insights/metrics", {"api-version": "2018-01-01"})
    # A non-storage resource serves only the generic ActivityOperations metric (the default when
    # metricnames is omitted, as real Azure returns the resource's default metric) — never the
    # storage metrics, and never an error.
    _check("metrics for a non-storage resource is the generic ActivityOperations series only",
           m2["status"] == 200 and [v["name"]["value"] for v in m2["body"]["value"]] == ["ActivityOperations"])
    m3 = arm.handle("GET", "/subscriptions/sub1/resourceGroups/uic-rg/providers/Microsoft.Network/virtualNetworks/vnet1"
                     "/providers/Microsoft.Insights/metrics", {"api-version": "2018-01-01", "metricnames": "UsedCapacity"})
    _check("storage metric names are unknown on a non-storage resource → 400", m3["status"] == 400)
    defs = arm.handle("GET", rid_path + "/providers/Microsoft.Insights/metricDefinitions", {"api-version": "2018-01-01"})
    def_units = {d["name"]["value"]: d["unit"] for d in defs["body"]["value"]}
    _check("storage metricDefinitions = ActivityOperations + the six storage metrics with units",
           defs["status"] == 200 and def_units.get("ActivityOperations") == "Count" and def_units.get("UsedCapacity") == "Bytes"
           and def_units.get("Transactions") == "Count" and len(def_units) == 7)
    mixed = arm.handle("GET", rid_path + "/providers/Microsoft.Insights/metrics",
                       {"api-version": "2018-01-01", "metricnames": "ActivityOperations,BlobCount"})
    _check("metricnames may mix ActivityOperations with storage metrics",
           mixed["status"] == 200 and [v["name"]["value"] for v in mixed["body"]["value"]] == ["ActivityOperations", "BlobCount"]
           and mixed["body"]["value"][1]["timeseries"][0]["data"][0]["total"] == stats["blobCount"])
    bad = arm.handle("GET", rid_path + "/providers/Microsoft.Insights/metrics",
                     {"api-version": "2018-01-01", "metricnames": "UsedCapacity,NotReal"})
    _check("an unknown metric name on a storage account → native 400",
           bad["status"] == 400 and "Failed to find metric configuration" in bad["body"]["error"]["message"])

    # ── Encryption: customer-managed keys must name a key vault that really exists ──────
    cmk_missing = arm.handle("PUT", rid_path, {"api-version": "2023-01-01"},
                             {"location": "eastus", "properties": {"encryption": {"keySource": "Microsoft.Keyvault", "keyvaultproperties": {}}}})
    _check("CMK encryption needs keyvaulturi/keyname", cmk_missing["status"] == 400)
    cmk_unknown = arm.handle("PUT", rid_path, {"api-version": "2023-01-01"}, {"location": "eastus", "properties": {
        "encryption": {"keySource": "Microsoft.Keyvault", "keyvaultproperties": {"keyvaulturi": "https://nope.vault.azure.net/", "keyname": "k1"}}}})
    _check("CMK encryption rejects an unknown vault", cmk_unknown["status"] == 400)
    arm.handle("PUT", "/subscriptions/sub1/resourceGroups/uic-rg/providers/Microsoft.KeyVault/vaults/wave5bvault", {"api-version": "2023-07-01"}, {"location": "eastus"})
    cmk_ok = arm.handle("PUT", rid_path, {"api-version": "2023-01-01"}, {"location": "eastus", "properties": {
        "encryption": {"keySource": "Microsoft.Keyvault", "keyvaultproperties": {"keyvaulturi": "https://wave5bvault.vault.azure.net/", "keyname": "k1"}}}})
    _check("CMK encryption accepted for a real vault", cmk_ok["status"] == 200)

    # ── Data Lake Gen2 upgrade: one-way, eligible-kind-only ─────────────────────────────
    hns_on = arm.handle("PATCH", rid_path, {"api-version": "2023-01-01"}, {"properties": {"isHnsEnabled": True}})
    _check("HNS upgrade succeeds on a StorageV2 account", hns_on["status"] == 200)
    hns_off = arm.handle("PATCH", rid_path, {"api-version": "2023-01-01"}, {"properties": {"isHnsEnabled": False}})
    _check("HNS downgrade is rejected (one-way)", hns_off["status"] == 400)
    legacy_rid = f"/subscriptions/sub1/resourceGroups/uic-rg/providers/Microsoft.Storage/storageAccounts/{ACCT}legacy"
    arm.handle("PUT", legacy_rid, {"api-version": "2023-01-01"}, {"location": "eastus", "kind": "Storage"})
    hns_ineligible = arm.handle("PATCH", legacy_rid, {"api-version": "2023-01-01"}, {"properties": {"isHnsEnabled": True}})
    _check("HNS upgrade is rejected on an ineligible (legacy) kind", hns_ineligible["status"] == 400)

    # ── Diagnostic settings: a storageAccountId destination must name a real account ──
    try:
        from core import azure_monitor_core as mo
    except ImportError:  # pragma: no cover - Pyodide flat layout
        import azure_monitor_core as mo  # type: ignore
    bad_dest = mo.upsert_diagnostic_setting(arm.state, rid_path, "toUnknown", {"properties": {
        "storageAccountId": "/subscriptions/sub1/resourceGroups/uic-rg/providers/Microsoft.Storage/storageAccounts/doesnotexist",
        "logs": [{"category": "StorageWrite", "enabled": True}]}})
    _check("diagnostic setting rejects a storageAccountId that doesn't exist", bad_dest["status"] == 400)
    good_dest = mo.upsert_diagnostic_setting(arm.state, rid_path, "toReal", {"properties": {
        "storageAccountId": rid_path, "logs": [{"category": "StorageWrite", "enabled": True}]}})
    _check("diagnostic setting accepts a real storageAccountId", good_dest["status"] == 201)

    print("\nAzure Blob Storage WAVE 5b (redundancy / data protection / telemetry) conformance: ALL GREEN")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(run())
