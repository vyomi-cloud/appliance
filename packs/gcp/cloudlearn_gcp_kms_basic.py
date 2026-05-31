from __future__ import annotations

from .._shared import build_pack

PACK = build_pack(
    "cloudlearn.gcp.kms.basic",
    "service",
    "1.0.0",
    "gcp",
    {
        "protocol": "gcp-like",
        "actions": [
            "projects.locations.keyRings.create",
            "projects.locations.keyRings.cryptoKeys.create",
            "projects.locations.keyRings.cryptoKeys.encrypt",
            "projects.locations.keyRings.cryptoKeys.decrypt",
            "projects.locations.keyRings.cryptoKeys.cryptoKeyVersions.list",
            "projects.locations.keyRings.list",
        ],
        "requestSchemas": True,
        "responseSchemas": True,
        "errors": True,
        "pagination": True,
        "regionAware": True,
        "dataPlane": "HashiCorp Vault (cloudlearn-vault:8200) — transit engine; routed via core/vault_routes._register_gcp",
    },
)
