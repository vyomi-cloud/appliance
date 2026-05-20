from __future__ import annotations

from typing import Any


def build_pack(
    pack_id: str,
    pack_type: str,
    version: str,
    provider: str,
    api: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": pack_id,
        "type": pack_type,
        "version": version,
        "provider": provider,
        "coreProviderNeutral": True,
        "state": "available",
        "active": False,
        "api": api,
    }
