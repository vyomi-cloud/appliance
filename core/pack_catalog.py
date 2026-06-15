from __future__ import annotations

import copy
import importlib
from pathlib import Path
from typing import Any

CORE_PACK_IDS = [
    "cloudlearn.s3.basic",
    "cloudlearn.iam.basic",
    "cloudlearn.ec2.basic",
    "cloudlearn.awscli.basic",
    "cloudlearn.aws.sdk.java.basic",
    "cloudlearn.aws.sdk.go.basic",
    "cloudlearn.gcp.compute.basic",
    "cloudlearn.gcp.gcloud.basic",
    "cloudlearn.gcp.sdk.java.basic",
    "cloudlearn.gcp.sdk.go.basic",
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
    # P2-A: 7 packs added 2026-06-01 to close per-provider gaps where new
    # services were added to the catalog but lacked pack metadata.
    "cloudlearn.rds.basic",
    "cloudlearn.eventbridge.basic",
    "cloudlearn.secretsmanager.basic",
    "cloudlearn.kms.basic",
    "cloudlearn.gcp.eventarc.basic",
    "cloudlearn.gcp.secretmanager.basic",
    "cloudlearn.gcp.kms.basic",
    # Azure parity — backfilled 2026-06-01 to close the pack-architecture gap.
    "cloudlearn.azure.vm.basic",
    "cloudlearn.azure.storage.basic",
    "cloudlearn.azure.sql.basic",
    "cloudlearn.azure.servicebus.basic",
    "cloudlearn.azure.cosmos.basic",
    "cloudlearn.azure.functionapp.basic",
    "cloudlearn.azure.apim.basic",
    "cloudlearn.azure.vnet.basic",
    "cloudlearn.azure.eventgrid.basic",
    "cloudlearn.azure.keyvault.basic",
    "cloudlearn.azure.rbac.basic",
    "cloudlearn.azure.azcli.basic",
    "cloudlearn.azure.sdk.java.basic",
    "cloudlearn.azure.sdk.go.basic",
]

_PACK_MODULE_PREFIX = "packs"
_PACK_FILES = {
    "cloudlearn.s3.basic": "aws.cloudlearn_s3_basic",
    "cloudlearn.iam.basic": "aws.cloudlearn_iam_basic",
    "cloudlearn.ec2.basic": "aws.cloudlearn_ec2_basic",
    "cloudlearn.awscli.basic": "aws.cloudlearn_awscli_basic",
    "cloudlearn.aws.sdk.java.basic": "aws.cloudlearn_aws_sdk_java_basic",
    "cloudlearn.aws.sdk.go.basic": "aws.cloudlearn_aws_sdk_go_basic",
    "cloudlearn.vpc.basic": "aws.cloudlearn_vpc_basic",
    "cloudlearn.apigateway.basic": "aws.cloudlearn_apigateway_basic",
    "cloudlearn.runtime.python": "cloudlearn_runtime_python",
    "cloudlearn.lambda.basic": "aws.cloudlearn_lambda_basic",
    "cloudlearn.sqs.basic": "aws.cloudlearn_sqs_basic",
    "cloudlearn.dynamodb.basic": "aws.cloudlearn_dynamodb_basic",
    "cloudlearn.cloudsim.basic": "cloudlearn_cloudsim_basic",
    "cloudlearn.gcp.compute.basic": "gcp.cloudlearn_gcp_compute_basic",
    "cloudlearn.gcp.gcloud.basic": "gcp.cloudlearn_gcp_gcloud_basic",
    "cloudlearn.gcp.sdk.java.basic": "gcp.cloudlearn_gcp_sdk_java_basic",
    "cloudlearn.gcp.sdk.go.basic": "gcp.cloudlearn_gcp_sdk_go_basic",
    "cloudlearn.gcp.iam.basic": "gcp.cloudlearn_gcp_iam_basic",
    "cloudlearn.gcp.vpc.basic": "gcp.cloudlearn_gcp_vpc_basic",
    "cloudlearn.gcp.cloudsql.basic": "gcp.cloudlearn_gcp_cloudsql_basic",
    "cloudlearn.gcp.pubsub.basic": "gcp.cloudlearn_gcp_pubsub_basic",
    "cloudlearn.gcp.firestore.basic": "gcp.cloudlearn_gcp_firestore_basic",
    "cloudlearn.gcp.functions.basic": "gcp.cloudlearn_gcp_functions_basic",
    "cloudlearn.gcp.apigateway.basic": "gcp.cloudlearn_gcp_apigateway_basic",
    "cloudlearn.gcp.storage.basic": "gcp.cloudlearn_gcp_storage_basic",
    # P2-A: 7 additional service packs added 2026-06-01 (AWS rds/eventbridge/
    # secretsmanager/kms + GCP eventarc/secretmanager/kms).
    "cloudlearn.rds.basic": "aws.cloudlearn_rds_basic",
    "cloudlearn.eventbridge.basic": "aws.cloudlearn_eventbridge_basic",
    "cloudlearn.secretsmanager.basic": "aws.cloudlearn_secretsmanager_basic",
    "cloudlearn.kms.basic": "aws.cloudlearn_kms_basic",
    "cloudlearn.gcp.eventarc.basic": "gcp.cloudlearn_gcp_eventarc_basic",
    "cloudlearn.gcp.secretmanager.basic": "gcp.cloudlearn_gcp_secretmanager_basic",
    "cloudlearn.gcp.kms.basic": "gcp.cloudlearn_gcp_kms_basic",
    # Azure pack module files (under packs/azure/).
    "cloudlearn.azure.vm.basic": "azure.vyomi_azure_vm_basic",
    "cloudlearn.azure.storage.basic": "azure.vyomi_azure_storage_basic",
    "cloudlearn.azure.sql.basic": "azure.vyomi_azure_sql_basic",
    "cloudlearn.azure.servicebus.basic": "azure.vyomi_azure_servicebus_basic",
    "cloudlearn.azure.cosmos.basic": "azure.vyomi_azure_cosmos_basic",
    "cloudlearn.azure.functionapp.basic": "azure.vyomi_azure_functionapp_basic",
    "cloudlearn.azure.apim.basic": "azure.vyomi_azure_apim_basic",
    "cloudlearn.azure.vnet.basic": "azure.vyomi_azure_vnet_basic",
    "cloudlearn.azure.eventgrid.basic": "azure.vyomi_azure_eventgrid_basic",
    "cloudlearn.azure.keyvault.basic": "azure.vyomi_azure_keyvault_basic",
    "cloudlearn.azure.rbac.basic": "azure.vyomi_azure_rbac_basic",
    "cloudlearn.azure.azcli.basic": "azure.vyomi_azure_azcli_basic",
    "cloudlearn.azure.sdk.java.basic": "azure.vyomi_azure_sdk_java_basic",
    "cloudlearn.azure.sdk.go.basic": "azure.vyomi_azure_sdk_go_basic",
}

PROVIDER_PACK_GROUPS = {
    "aws": [
        "cloudlearn.s3.basic",
        "cloudlearn.iam.basic",
        "cloudlearn.ec2.basic",
        "cloudlearn.awscli.basic",
        "cloudlearn.aws.sdk.java.basic",
        "cloudlearn.aws.sdk.go.basic",
        "cloudlearn.vpc.basic",
        "cloudlearn.apigateway.basic",
        "cloudlearn.runtime.python",
        "cloudlearn.lambda.basic",
        "cloudlearn.sqs.basic",
        "cloudlearn.dynamodb.basic",
        # P2-A additions (2026-06-01) — close pack-vs-catalog gap.
        "cloudlearn.rds.basic",
        "cloudlearn.eventbridge.basic",
        "cloudlearn.secretsmanager.basic",
        "cloudlearn.kms.basic",
    ],
    "gcp": [
        "cloudlearn.gcp.compute.basic",
        "cloudlearn.gcp.gcloud.basic",
        "cloudlearn.gcp.sdk.java.basic",
        "cloudlearn.gcp.sdk.go.basic",
        "cloudlearn.gcp.iam.basic",
        "cloudlearn.gcp.vpc.basic",
        "cloudlearn.gcp.cloudsql.basic",
        "cloudlearn.gcp.pubsub.basic",
        "cloudlearn.gcp.firestore.basic",
        "cloudlearn.gcp.functions.basic",
        "cloudlearn.gcp.apigateway.basic",
        "cloudlearn.gcp.storage.basic",
        # P2-A additions (2026-06-01).
        "cloudlearn.gcp.eventarc.basic",
        "cloudlearn.gcp.secretmanager.basic",
        "cloudlearn.gcp.kms.basic",
    ],
    "azure": [
        "cloudlearn.azure.vm.basic",
        "cloudlearn.azure.storage.basic",
        "cloudlearn.azure.sql.basic",
        "cloudlearn.azure.servicebus.basic",
        "cloudlearn.azure.cosmos.basic",
        "cloudlearn.azure.functionapp.basic",
        "cloudlearn.azure.apim.basic",
        "cloudlearn.azure.vnet.basic",
        "cloudlearn.azure.eventgrid.basic",
        "cloudlearn.azure.keyvault.basic",
        "cloudlearn.azure.rbac.basic",
        "cloudlearn.azure.azcli.basic",
        "cloudlearn.azure.sdk.java.basic",
        "cloudlearn.azure.sdk.go.basic",
    ],
    "other": [
        "cloudlearn.cloudsim.basic",
    ],
}


def pack_module_name(pack_id: str) -> str:
    return _PACK_FILES[pack_id]


def pack_fragment_path(pack_id: str) -> Path:
    html_dir = Path(__file__).with_name("packs") / "html"
    provider_scoped = html_dir / f"{pack_module_name(pack_id)}.html"
    if provider_scoped.exists():
        return provider_scoped
    legacy = html_dir / f"{pack_id.replace('.', '_')}.html"
    return legacy if legacy.exists() else provider_scoped


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


def packs_for_provider(provider: str | None) -> list[dict[str, Any]]:
    key = str(provider or "other").lower().strip()
    pack_ids = PROVIDER_PACK_GROUPS.get(key, PROVIDER_PACK_GROUPS["other"])
    return [load_pack(pack_id) for pack_id in pack_ids]


def pack_ids_for_provider(provider: str | None) -> list[str]:
    key = str(provider or "other").lower().strip()
    return list(PROVIDER_PACK_GROUPS.get(key, PROVIDER_PACK_GROUPS["other"]))


def catalog() -> list[dict[str, Any]]:
    return [copy.deepcopy(pack) for pack in default_packs().values()]


def fragment_for_pack(pack_id: str) -> str:
    path = pack_fragment_path(pack_id)
    if not path.exists():
        raise KeyError(pack_id)
    return path.read_text(encoding="utf-8")
