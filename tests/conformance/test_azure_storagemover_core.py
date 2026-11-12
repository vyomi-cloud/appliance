"""Storage Mover: endpoint/job validation + a REAL blob->blob and blob->Azure Files copy (Additive/Mirror)."""
import base64
try:
    from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as S
    from core.azure_blob_core import AzureBlobStore
    from core import azure_blob_core as blob
except ImportError:  # pragma: no cover
    from azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as S  # type: ignore
    from azure_blob_core import AzureBlobStore  # type: ignore
    import azure_blob_core as blob  # type: ignore


def _check(n, c):
    if not c:
        raise AssertionError(n)
    print("  ok ", n)


def run():
    a = AzureArm()
    a.blob_store = store = AzureBlobStore()
    av = {"api-version": "2024-07-01"}
    h = lambda m, p, b=None, q=None: a.handle(m, p, dict(av, **(q or {})), b)
    h("PUT", f"/subscriptions/{S}/resourceGroups/r", {"location": "eastus"})
    sa = f"/subscriptions/{S}/resourceGroups/r/providers/Microsoft.Storage/storageAccounts"
    h("PUT", f"{sa}/src", {"location": "eastus", "kind": "StorageV2", "sku": {"name": "Standard_LRS"}})
    h("PUT", f"{sa}/dst", {"location": "eastus", "kind": "StorageV2", "sku": {"name": "Standard_LRS"}})
    store.create_container("src/in")
    store.create_container("dst/out")
    for n, d in (("a.txt", b"one"), ("dir/b.txt", b"two"), ("dir/c.txt", b"three")):
        blob.dispatch(store, "PUT", f"/in/{n}", {}, {"x-ms-blob-type": "BlockBlob"}, d, account="src")
    sm = f"/subscriptions/{S}/resourceGroups/r/providers/Microsoft.StorageMover/storageMovers/m1"
    _check("bad name", h("PUT", sm.replace("m1", "bad name!"), {"location": "eastus"})["status"] == 400)
    _check("create mover", h("PUT", sm, {"location": "eastus", "properties": {"description": "d"}})["status"] == 201)
    _check("bad endpoint type", h("PUT", f"{sm}/endpoints/e", {"properties": {"endpointType": "Ftp"}})["status"] == 400)
    _check("missing account", h("PUT", f"{sm}/endpoints/e", {"properties": {"endpointType": "AzureStorageBlobContainer", "storageAccountResourceId": f"{sa}/ghost", "blobContainerName": "c"}})["status"] == 400)
    ep = lambda n, acct, cont: h("PUT", f"{sm}/endpoints/{n}", {"properties": {"endpointType": "AzureStorageBlobContainer", "storageAccountResourceId": f"{sa}/{acct}", "blobContainerName": cont}})
    _check("source ep", ep("s", "src", "in")["status"] == 201)
    _check("target ep", ep("t", "dst", "out")["status"] == 201)
    _check("onprem ep", h("PUT", f"{sm}/endpoints/nfs", {"properties": {"endpointType": "NfsMount", "host": "10.0.0.5", "export": "/data"}})["status"] == 201)
    h("PUT", f"{sm}/projects/p1", {"properties": {}})
    jd = f"{sm}/projects/p1/jobDefinitions/j1"
    _check("copyMode required", h("PUT", jd, {"properties": {"sourceName": "s", "targetName": "t"}})["status"] == 400)
    _check("target must be azure", h("PUT", jd, {"properties": {"copyMode": "Additive", "sourceName": "s", "targetName": "nfs"}})["status"] == 400)
    _check("onprem source needs agent", h("PUT", f"{sm}/projects/p1/jobDefinitions/jn", {"properties": {"copyMode": "Additive", "sourceName": "nfs", "targetName": "t"}})["status"] == 400)
    _check("job create", h("PUT", jd, {"properties": {"copyMode": "Additive", "sourceName": "s", "targetName": "t", "sourceSubpath": "dir", "targetSubpath": "copied"}})["status"] == 201)
    _check("endpoint in use", h("DELETE", f"{sm}/endpoints/s")["status"] == 409)
    r = h("POST", f"{jd}/startJob")
    _check("start job", r["status"] == 200)
    run1 = h("GET", f"{jd}/jobRuns")["body"]["value"][0]["properties"]
    _check("run succeeded w/ counters", run1["status"] == "Succeeded" and run1["transferredItemsCount"] == 2 and run1["transferredBytes"] == 8)
    keys = set(store.container_blobs("dst/out"))
    _check("bytes really copied under targetSubpath", {"copied/b.txt", "copied/c.txt"} <= keys and "copied/a.txt" not in keys)
    h("POST", f"{jd}/startJob")
    run2 = h("GET", f"{jd}/jobRuns")["body"]["value"][0]["properties"]
    _check("re-run skips unchanged", run2["transferredItemsCount"] == 0 and run2["itemsExcluded"] == 2)
    blob.dispatch(store, "PUT", "/out/copied/stale.txt", {}, {"x-ms-blob-type": "BlockBlob"}, b"x", account="dst")
    h("PATCH", jd, {"properties": {"copyMode": "Mirror"}})
    h("POST", f"{jd}/startJob")
    _check("mirror deletes extras", "copied/stale.txt" not in store.container_blobs("dst/out") and h("GET", f"{jd}/jobRuns")["body"]["value"][0]["properties"]["itemsDeleted"] == 1)
    # blob -> Azure Files
    fs = f"{sa}/dst/fileServices/default/shares/share1"
    h("PUT", fs, {"properties": {"shareQuota": 5}})
    h("PUT", f"{sm}/endpoints/f", {"properties": {"endpointType": "AzureStorageSmbFileShare", "storageAccountResourceId": f"{sa}/dst", "fileShareName": "share1"}})
    h("PUT", f"{sm}/projects/p1/jobDefinitions/j2", {"properties": {"copyMode": "Additive", "sourceName": "s", "targetName": "f"}})
    h("POST", f"{sm}/projects/p1/jobDefinitions/j2/startJob")
    tree = h("GET", f"{fs}/items/dir")["body"]["value"]
    _check("copied into the Files share", sorted(k["name"] for k in tree) == ["b.txt", "c.txt"])
    _check("share usage reflects copy", h("GET", fs)["body"]["properties"]["shareUsageBytes"] == 11)
    # failure modes
    store.delete_container("src/in")
    h("POST", f"{jd}/startJob")
    fr = h("GET", f"{jd}/jobRuns")["body"]["value"][0]["properties"]
    _check("missing container fails run", fr["status"] == "Failed" and fr["error"]["code"] == "ContainerNotFound")
    h("PUT", f"{sm}/agents/ag", {"properties": {}})
    _check("agents are registered by software", h("PUT", f"{sm}/agents/ag", {"properties": {}})["status"] == 404)
    _check("mover with projects not deletable", h("DELETE", sm)["status"] == 409)
    print("PASS test_azure_storagemover_core")


if __name__ == "__main__":
    run()
