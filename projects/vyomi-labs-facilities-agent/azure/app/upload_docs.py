import os
from azure.mgmt.storage import StorageManagementClient
from azure.storage.blob import BlobServiceClient
from azlab import arm, ensure_rg, RG, LOC
from azdata import storage_cs

ensure_rg()
arm(StorageManagementClient).storage_accounts.begin_create(RG, "facilitiesdocs", {"location": LOC, "sku": {"name": "Standard_LRS"}, "kind": "StorageV2"}).result()
blobs = BlobServiceClient.from_connection_string(storage_cs("Blob"))
try:
    blobs.create_container("docs")
except Exception as e:
    if "ContainerAlreadyExists" not in str(e):
        raise
for name in ("boiler-sop.md", "elevator-sop.md", "fire-safety-sop.md", "hvac-maintenance-manual.md"):
    blobs.get_blob_client("docs", name).upload_blob(open(name, "rb").read(), overwrite=True)
names = sorted(b.name for b in blobs.get_container_client("docs").list_blobs())
print("container docs:", names)
print("read back:", blobs.get_blob_client("docs", "boiler-sop.md").download_blob().readall().decode().splitlines()[0])
