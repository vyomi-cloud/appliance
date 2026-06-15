from __future__ import annotations

from .._shared import build_pack

PACK = build_pack(
    "cloudlearn.azure.sql.basic",
    "service",
    "1.0.0",
    "azure",
    {
        "protocol": "azure-arm",
        "resourceType": "Microsoft.Sql/servers",
        "actions": [
            "Servers_CreateOrUpdate",
            "Servers_Get",
            "Servers_Delete",
            "Servers_List",
            "Databases_CreateOrUpdate",
            "Databases_Get",
            "Databases_Delete",
            "Databases_List",
            "FirewallRules_CreateOrUpdate",
        ],
        "requestSchemas": True,
        "responseSchemas": True,
        "errors": True,
        "pagination": True,
        "regionAware": True,
        "apiVersion": "2023-08-01",
        "dataPlane": "postgres:16-alpine (each Microsoft.Sql/servers/databases backed by a real Postgres DB via gcp_sql_engine)",
    },
)
