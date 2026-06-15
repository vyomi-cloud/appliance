from __future__ import annotations

from .._shared import build_pack

PACK = build_pack(
    "cloudlearn.azure.storage.basic",
    "service",
    "1.0.0",
    "azure",
    {
        "protocol": "azure-arm+blob",
        "resourceType": "Microsoft.Storage/storageAccounts",
        "actions": [
            "StorageAccounts_Create",
            "StorageAccounts_Get",
            "StorageAccounts_Delete",
            "StorageAccounts_List",
            "StorageAccounts_ListKeys",
            "BlobContainers_Create",
            "BlobContainers_Get",
            "BlobContainers_Delete",
            "Blob_Put",
            "Blob_Get",
            "Blob_Delete",
        ],
        "requestSchemas": True,
        "responseSchemas": True,
        "errors": True,
        "pagination": True,
        "regionAware": True,
        "apiVersion": "2023-05-01",
        "dataPlane": "fake-gcs-server (Blob bytes shared with GCP storage layer)",
        "dataPlaneRoutes": ["/azure-data/blob/{account}/{container}/{blob}"],
    },
)
