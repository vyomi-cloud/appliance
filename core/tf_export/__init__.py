"""Faithful Terraform export: the simulator's live state -> a Terraform bundle that rebuilds the same stack."""
from __future__ import annotations

import io
import zipfile
from typing import Any

from core.tf_export import (aws_apigw, aws_compute, aws_data, aws_dynamodb, aws_iam, aws_kms, aws_lambda, aws_messaging, aws_network,  # noqa: F401  (register exporters)
                            aws_ops, aws_storage)
from core.tf_export.core import Ctx, registered, render_files
from core.tf_export.graph import build_graph, portability


AWS_SERVICES = ("ec2", "s3", "logs", "iam", "lambda", "apigateway", "rds", "secretsmanager", "dynamodb", "sqs", "sns", "events", "kms", "stepfunctions", "ecr", "cloudwatch", "backup")


def _clients(endpoint: str, region: str) -> dict[str, Any]:
    import boto3
    from botocore.config import Config
    cfg = Config(retries={"max_attempts": 8, "mode": "standard"}, s3={"addressing_style": "path"})
    kw = dict(endpoint_url=endpoint, region_name=region, aws_access_key_id="test", aws_secret_access_key="test", config=cfg)
    return {n: boto3.client(n, **kw) for n in AWS_SERVICES}


def build_aws(endpoint: str, region: str = "us-east-1", real_cloud: bool = False) -> dict[str, Any]:
    return build_aws_with(_clients(endpoint, region), region, real_cloud)


def build_aws_with(clients: dict[str, Any], region: str = "us-east-1", real_cloud: bool = False, fetch=None) -> dict[str, Any]:
    """Same export over any boto3-shaped clients (Nano passes core.tf_export.wire_clients over the in-process router); ``fetch(path)->bytes|None`` downloads Lambda code."""
    ctx = Ctx(clients, region)
    ctx.fetch = fetch
    errors: list[dict[str, str]] = []
    for _order, name, fn in registered():
        try:
            fn(ctx)
        except Exception as exc:  # noqa: BLE001 - one service failing must not hide the rest
            errors.append({"exporter": name, "error": f"{type(exc).__name__}: {exc}"[:300]})
    files = render_files(ctx, real_cloud=real_cloud)
    return {"files": files, "binaries": ctx.files_bin, "graph": build_graph(ctx), "portability": portability(ctx, files, real_cloud),
            "summary": {"resources": len(ctx.resources), "by_type": _count(ctx), "skipped": ctx.skipped, "errors": errors}}


def _count(ctx: Ctx) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in ctx.resources:
        out[r.type] = out.get(r.type, 0) + 1
    return out


def bundle_zip(result: dict[str, Any]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, text in result["files"].items():
            z.writestr(name, text)
        for name, data in result["binaries"].items():
            z.writestr(name, data)
    return buf.getvalue()
