from __future__ import annotations

import copy
import importlib
from pathlib import Path
from typing import Any

CORE_PACK_IDS = [
    "cloudlearn.s3.basic",
    "cloudlearn.iam.basic",
    "cloudlearn.ec2.basic",
    "cloudlearn.gcp.compute.basic",
    "cloudlearn.gcp.iam.basic",
    "cloudlearn.gcp.vpc.basic",
    "cloudlearn.gcp.cloudsql.basic",
    "cloudlearn.gcp.pubsub.basic",
    "cloudlearn.gcp.firestore.basic",
    "cloudlearn.gcp.functions.basic",
    "cloudlearn.gcp.apigateway.basic",
    "cloudlearn.gcp.storage.basic",
    "cloudlearn.vpc.basic",
    "cloudlearn.apigateway.basic",
    "cloudlearn.runtime.python",
    "cloudlearn.lambda.basic",
    "cloudlearn.sqs.basic",
    "cloudlearn.dynamodb.basic",
    "cloudlearn.cloudsim.basic",
]

_PACK_MODULE_PREFIX = "packs"
_PACK_FILES = {
    pack_id: pack_id.replace(".", "_")
    for pack_id in CORE_PACK_IDS
}


def pack_module_name(pack_id: str) -> str:
    return _PACK_FILES[pack_id]


def pack_fragment_path(pack_id: str) -> Path:
    return Path(__file__).with_name("packs") / "html" / f"{pack_module_name(pack_id)}.html"


def _import_pack_module(pack_id: str):
    if pack_id not in _PACK_FILES:
        raise KeyError(pack_id)
    return importlib.import_module(f"{_PACK_MODULE_PREFIX}.{pack_module_name(pack_id)}")


def load_pack(pack_id: str) -> dict[str, Any]:
    module = _import_pack_module(pack_id)
    pack = copy.deepcopy(getattr(module, "PACK", {}))
    if not isinstance(pack, dict):
        raise ValueError(f"Invalid pack payload for {pack_id}")
    pack.setdefault("id", pack_id)
    pack.setdefault("fragment_url", f"/api/packs/{pack_id}/fragment")
    pack.setdefault("html_fragment", str(pack_fragment_path(pack_id).relative_to(Path(__file__).parent)))
    return pack


def default_packs() -> dict[str, dict[str, Any]]:
    return {pack_id: load_pack(pack_id) for pack_id in CORE_PACK_IDS}


def catalog() -> list[dict[str, Any]]:
    return [copy.deepcopy(pack) for pack in default_packs().values()]


def fragment_for_pack(pack_id: str) -> str:
    path = pack_fragment_path(pack_id)
    if not path.exists():
        raise KeyError(pack_id)
    return path.read_text(encoding="utf-8")
