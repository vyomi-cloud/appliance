"""Azure Files: file service props, shares (quota/protocol/tier validation), soft delete + restore, snapshots, lease, content + quota."""
import base64
try:
    from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as S
    from core import azure_files_core as F
except ImportError:  # pragma: no cover
    from azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as S  # type: ignore
    import azure_files_core as F  # type: ignore


def _check(n, c):
    if not c:
        raise AssertionError(n)
    print("  ok ", n)


def run():
    a = AzureArm()
    av = {"api-version": "2023-01-01"}
    a.handle("PUT", f"/subscriptions/{S}/resourceGroups/r", {"api-version": "2021-04-01"}, {"location": "eastus"})
    sa = f"/subscriptions/{S}/resourceGroups/r/providers/Microsoft.Storage/storageAccounts"
    a.handle("PUT", f"{sa}/stdacct", av, {"location": "eastus", "kind": "StorageV2", "sku": {"name": "Standard_LRS"}})
    a.handle("PUT", f"{sa}/premacct", av, {"location": "eastus", "kind": "FileStorage", "sku": {"name": "Premium_LRS"}})
    a.handle("PUT", f"{sa}/blobonly", av, {"location": "eastus", "kind": "BlockBlobStorage", "sku": {"name": "Premium_LRS"}})
    fs = f"{sa}/stdacct/fileServices/default"
    h = lambda m, p, b=None, q=None: a.handle(m, p, dict(av, **(q or {})), b)
    _check("file service listed", h("GET", f"{sa}/stdacct/fileServices")["body"]["value"][0]["name"] == "default")
    _check("blockblob refused", h("GET", f"{sa}/blobonly/fileServices/default")["status"] == 400)
    _check("bad cors rule 400", h("PUT", fs, {"properties": {"cors": {"corsRules": [{"allowedOrigins": ["*"], "allowedMethods": ["FETCH"], "maxAgeInSeconds": 1, "exposedHeaders": [], "allowedHeaders": []}]}}})["status"] == 400)
    _check("multichannel premium only", h("PUT", fs, {"properties": {"protocolSettings": {"smb": {"multichannel": {"enabled": True}}}}})["status"] == 400)
    _check("premium multichannel ok", h("PUT", f"{sa}/premacct/fileServices/default", {"properties": {"protocolSettings": {"smb": {"multichannel": {"enabled": True}}}}})["status"] == 200)
    _check("retention days validated", h("PUT", fs, {"properties": {"shareDeleteRetentionPolicy": {"enabled": True, "days": 999}}})["status"] == 400)
    _check("retention set", h("PUT", fs, {"properties": {"shareDeleteRetentionPolicy": {"enabled": True, "days": 5}}})["body"]["properties"]["shareDeleteRetentionPolicy"]["days"] == 5)
    _check("bad share name", h("PUT", f"{fs}/shares/Bad_Name", {"properties": {}})["status"] == 400)
    _check("hyphen-pair name", h("PUT", f"{fs}/shares/a--b", {"properties": {}})["status"] == 400)
    r = h("PUT", f"{fs}/shares/docs", {"properties": {"shareQuota": 10, "metadata": {"k": "v"}}})
    _check("create 201 + defaults", r["status"] == 201 and r["body"]["properties"]["enabledProtocols"] == "SMB" and r["body"]["properties"]["accessTier"] == "TransactionOptimized")
    _check("quota max 5120 w/o large", h("PUT", f"{fs}/shares/big", {"properties": {"shareQuota": 6000}})["status"] == 400)
    a.handle("PATCH", f"{sa}/stdacct", av, {"properties": {"largeFileSharesState": "Enabled"}})
    _check("quota 6000 with large file shares", h("PUT", f"{fs}/shares/big", {"properties": {"shareQuota": 6000}})["status"] == 201)
    _check("NFS needs premium", h("PUT", f"{fs}/shares/nfs", {"properties": {"enabledProtocols": "NFS"}})["status"] == 400)
    pf = f"{sa}/premacct/fileServices/default"
    r = h("PUT", f"{pf}/shares/nfs1", {"properties": {"enabledProtocols": "NFS", "rootSquash": "RootSquash", "shareQuota": 100}})
    _check("NFS on premium + rootSquash", r["status"] == 201 and r["body"]["properties"]["rootSquash"] == "RootSquash" and r["body"]["properties"]["accessTier"] == "Premium")
    _check("premium min quota 100", h("PUT", f"{pf}/shares/small", {"properties": {"shareQuota": 10}})["status"] == 400)
    _check("rootSquash only NFS", h("PUT", f"{fs}/shares/rs", {"properties": {"rootSquash": "RootSquash"}})["status"] == 400)
    _check("protocol immutable", h("PUT", f"{pf}/shares/nfs1", {"properties": {"enabledProtocols": "SMB"}})["status"] == 409)
    _check("Premium tier refused on standard", h("PUT", f"{fs}/shares/pt", {"properties": {"accessTier": "Premium"}})["status"] == 400)
    # content
    it = f"{fs}/shares/docs/items"
    _check("mkdir", h("PUT", f"{it}/a", {"type": "directory"})["status"] == 201)
    _check("parent required", h("PUT", f"{it}/zz/f.txt", {"type": "file", "contentBase64": ""})["status"] == 404)
    _check("upload", h("PUT", f"{it}/a/f.txt", {"type": "file", "contentBase64": base64.b64encode(b"hello").decode()})["status"] == 201)
    _check("bad base64", h("PUT", f"{it}/a/g.txt", {"type": "file", "contentBase64": "!!"})["status"] == 400)
    _check("list dir", [k["name"] for k in h("GET", f"{it}/a")["body"]["value"]] == ["f.txt"])
    _check("download", base64.b64decode(h("GET", f"{it}/a/f.txt")["body"]["contentBase64"]) == b"hello")
    _check("usage from content", h("GET", f"{fs}/shares/docs")["body"]["properties"]["shareUsageBytes"] == 5)
    _check("non-empty dir delete 409", h("DELETE", f"{it}/a")["status"] == 409)
    # quota enforcement: shrink below usage allowed? 1 GiB min -> write over quota
    sh = a.state[sa.lower() + "/stdacct"]["_files_shares"]["docs"]
    sh["properties"]["shareQuota"] = 1
    big = base64.b64encode(b"x" * 1024).decode()
    sh["_tree"]["a/huge"] = {"type": "file", "_b64": "", "size": 1024 ** 3 - 2, "modified": "x"}
    _check("write beyond quota 409", h("PUT", f"{it}/a/over.txt", {"type": "file", "contentBase64": big})["status"] == 409)
    sh["_tree"].pop("a/huge")
    # snapshots
    sn = h("POST", f"{fs}/shares/docs/snapshot")
    _check("snapshot 201", sn["status"] == 201)
    h("DELETE", f"{it}/a/f.txt")
    snap_time = sn["body"]["snapshotTime"]
    _check("snapshot keeps deleted file", h("GET", f"{it}/a/f.txt", None, {"snapshot": snap_time})["status"] == 200)
    _check("share with snapshots refuses delete", h("DELETE", f"{fs}/shares/docs")["status"] == 409)
    _check("snapshots listed", len(h("GET", f"{fs}/shares/docs/snapshots")["body"]["value"]) == 1)
    _check("delete snapshot", h("DELETE", f"{fs}/shares/docs/snapshot/{snap_time}")["status"] == 200)
    # lease
    ls = h("POST", f"{fs}/shares/docs/lease", {"action": "acquire"})
    _check("lease acquire", ls["status"] == 200)
    _check("second acquire 409", h("POST", f"{fs}/shares/docs/lease", {"action": "acquire"})["status"] == 409)
    _check("write w/o lease id 412", h("PUT", f"{it}/n.txt", {"type": "file", "contentBase64": ""})["status"] == 412)
    _check("write with lease id", h("PUT", f"{it}/n.txt", {"type": "file", "contentBase64": "", "leaseId": ls["body"]["leaseId"]})["status"] == 201)
    _check("release", h("POST", f"{fs}/shares/docs/lease", {"action": "release", "leaseId": ls["body"]["leaseId"]})["status"] == 200)
    # soft delete + restore
    _check("soft delete", h("DELETE", f"{fs}/shares/docs")["status"] == 200)
    _check("hidden from list", all(s["name"] != "docs" for s in h("GET", f"{fs}/shares")["body"]["value"]))
    _check("visible with deleted expand", any(s["name"] == "docs" and s["properties"].get("deleted") for s in h("GET", f"{fs}/shares", None, {"$expand": "deleted"})["body"]["value"]))
    _check("recreate while soft-deleted 409", h("PUT", f"{fs}/shares/docs", {"properties": {}})["status"] == 409)
    _check("restore", h("POST", f"{fs}/shares/docs/restore")["status"] == 200 and h("GET", f"{fs}/shares/docs")["status"] == 200)
    _check("permanent delete refused unless allowed", h("DELETE", f"{fs}/shares/docs", None, {"permanent": "true"})["status"] == 409)
    rule = {"allowedOrigins": ["*"], "allowedMethods": ["GET"], "maxAgeInSeconds": 60, "exposedHeaders": ["*"], "allowedHeaders": ["*"]}
    for svc in ("queueServices", "tableServices"):
        _check(f"{svc} cors stored", h("PUT", f"{sa}/stdacct/{svc}/default", {"properties": {"cors": {"corsRules": [rule]}}})["body"]["properties"]["cors"]["corsRules"][0]["maxAgeInSeconds"] == 60
               and h("GET", f"{sa}/stdacct/{svc}/default")["body"]["properties"]["cors"]["corsRules"][0]["allowedOrigins"] == ["*"])
        _check(f"{svc} cors validated", h("PUT", f"{sa}/stdacct/{svc}/default", {"properties": {"cors": {"corsRules": [dict(rule, allowedMethods=["NOPE"])]}}})["status"] == 400)
    # account-level properties
    _check("large file shares need standard LRS/ZRS/GRS/GZRS", h("PATCH", f"{sa}/premacct", {"properties": {"largeFileSharesState": "Enabled"}})["status"] == 400)
    _check("large file shares one-way", h("PATCH", f"{sa}/stdacct", {"properties": {"largeFileSharesState": "Disabled"}})["status"] == 400)
    _check("NFSv3 needs HNS", h("PUT", f"{sa}/nfsacct", {"location": "eastus", "kind": "StorageV2", "sku": {"name": "Standard_LRS"}, "properties": {"isNfsV3Enabled": True}})["status"] == 400)
    _check("NFSv3 needs secure transfer off", h("PUT", f"{sa}/nfsacct", {"location": "eastus", "kind": "StorageV2", "sku": {"name": "Standard_LRS"}, "properties": {"isNfsV3Enabled": True, "isHnsEnabled": True}})["status"] == 400)
    _check("NFSv3 account", h("PUT", f"{sa}/nfsacct", {"location": "eastus", "kind": "StorageV2", "sku": {"name": "Standard_LRS"}, "properties": {"isNfsV3Enabled": True, "isHnsEnabled": True, "supportsHttpsTrafficOnly": False}})["status"] in (200, 201))
    _check("NFSv3 immutable after create", h("PATCH", f"{sa}/nfsacct", {"properties": {"isNfsV3Enabled": False}})["status"] == 400)
    _check("SFTP needs HNS", h("PATCH", f"{sa}/stdacct", {"properties": {"isSftpEnabled": True}})["status"] == 400)
    print("PASS test_azure_files_core")


if __name__ == "__main__":
    run()
