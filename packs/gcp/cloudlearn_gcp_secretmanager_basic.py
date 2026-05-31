from __future__ import annotations

from .._shared import build_pack

PACK = build_pack(
    "cloudlearn.gcp.secretmanager.basic",
    "service",
    "1.0.0",
    "gcp",
    {
        "protocol": "gcp-like",
        "actions": [
            "projects.secrets.create",
            "projects.secrets.get",
            "projects.secrets.delete",
            "projects.secrets.list",
            "projects.secrets.addVersion",
            "projects.secrets.versions.access",
            "projects.secrets.versions.list",
            "projects.secrets.versions.disable",
        ],
        "requestSchemas": True,
        "responseSchemas": True,
        "errors": True,
        "pagination": True,
        "regionAware": True,
        "dataPlane": "HashiCorp Vault (cloudlearn-vault:8200) — KV v2 backed; routed via core/vault_routes._register_gcp",
    },
)
