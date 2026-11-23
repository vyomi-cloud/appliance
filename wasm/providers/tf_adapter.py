"""Nano (Pyodide) side of the Infrastructure Studio's Terraform API: GET /api/terraform/export/{graph,bundle}, POST /api/terraform/classify.

The SAME exporter as the appliance (core/tf_export) runs here, reading Nano's AWS state through boto3-shaped clients
(core.tf_export.wire_clients) whose transport is the in-process native-wire router, so the Terraform matches what an SDK/CLI sees."""
from __future__ import annotations

import base64
import os

from . import wire_adapter


def _transport(method, path, query, headers, body):
    r = wire_adapter.router().handle(method, path, query or {}, headers or {}, body or b"")
    out = r.get("body") or b""
    out = out.encode("utf-8") if isinstance(out, str) else bytes(out)
    return int(r.get("status") or 200), {str(k): str(v) for k, v in (r.get("headers") or {}).items()}, out


def _models_dir() -> str:
    import botocore
    return os.path.join(os.path.dirname(botocore.__file__), "data")


def _build(region: str, real: bool):
    from core.tf_export import build_aws_with
    from core.tf_export.wire_clients import make_clients
    clients = make_clients(_transport, region, _models_dir())

    def fetch(path):  # Lambda deployment package, straight from the store
        from core import lambda_core as lc
        from core.appliance_stores import lambda_store
        fn = lc._find_fn(lambda_store(), lc._norm_name(path.rstrip("/").split("/")[-1]))
        return base64.b64decode(fn["code_zip"]) if fn and fn.get("code_zip") else None
    return build_aws_with(clients, region, real, fetch=fetch)


def handle(op: str, params: dict) -> dict:
    region = (params or {}).get("region") or "us-east-1"
    if op == "Graph":
        r = _build(region, False)
        return {**r["graph"], "region": region, "portability": r["portability"], "summary": r["summary"]}
    if op == "Bundle":
        r = _build(region, (params or {}).get("mode") == "real")
        return {"files": r["files"], "summary": r["summary"], "portability": r["portability"], "graph": r["graph"],
                "binaries": {k: base64.b64encode(v).decode() for k, v in r["binaries"].items()}}
    if op in ("Plan", "Apply", "Destroy"):  # Terraform import: the SAME engine as the appliance, creating through the native wire
        from core.tf_export.apply import handle
        from core.tf_export.wire_clients import make_clients
        return handle(op, params or {}, make_clients(_transport, region, _models_dir()), region)
    if op == "Classify":
        from core.tf_export.graph import classify
        return {"availability": classify([t for t in ((params or {}).get("types") or []) if isinstance(t, str)][:500])}
    return {"ok": False, "code": "UnsupportedOperation", "operation": op}
