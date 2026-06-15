from __future__ import annotations

from .._shared import build_pack

PACK = build_pack(
    "cloudlearn.azure.cosmos.basic",
    "service",
    "1.0.0",
    "azure",
    {
        "protocol": "azure-arm+rest",
        "resourceType": "Microsoft.DocumentDB/databaseAccounts",
        "actions": [
            "DatabaseAccounts_CreateOrUpdate",
            "DatabaseAccounts_Get",
            "DatabaseAccounts_Delete",
            "DatabaseAccounts_List",
            "DatabaseAccounts_ListKeys",
            "SqlResources_CreateUpdateSqlDatabase",
            "SqlResources_CreateUpdateSqlContainer",
            "Docs_Create",
            "Docs_Query",
        ],
        "requestSchemas": True,
        "responseSchemas": True,
        "errors": True,
        "pagination": True,
        "regionAware": True,
        "apiVersion": "2023-11-15",
        "dataPlane": "in-process SQL API subset under /azure-data/cosmos/{account}/dbs/{db}/colls/{coll}/docs",
    },
)
