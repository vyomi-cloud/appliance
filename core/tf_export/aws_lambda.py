"""Lambda functions (code bundled into the export), resource policies (permissions) and event source mappings."""
from __future__ import annotations

import json
import re
import urllib.request

from core.tf_export import hcl
from core.tf_export.core import Ctx, exporter


def _download(ctx: Ctx, location: str) -> bytes | None:
    """Fetch the deployment package through the simulator's own endpoint (Location is built from its public URL)."""
    path = re.sub(r"^https?://[^/]+", "", location)
    fetch = getattr(ctx, "fetch", None)
    if fetch is not None:
        try:
            return fetch(path)
        except Exception:  # noqa: BLE001
            return None
    base = ctx.c["lambda"].meta.endpoint_url.rstrip("/")
    try:
        with urllib.request.urlopen(base + path, timeout=30) as r:  # noqa: S310 - the simulator's own loopback endpoint
            return r.read()
    except Exception:  # noqa: BLE001
        return None


@exporter(40, "lambda")
def export_lambda(ctx: Ctx) -> None:
    lam = ctx.c["lambda"]
    fns = []
    for page in lam.get_paginator("list_functions").paginate():
        fns += page.get("Functions", [])
    for f in fns:
        ctx.reserve("aws_lambda_function", f["FunctionArn"], f["FunctionName"])
    for f in fns:
        name = f["FunctionName"]
        got = lam.get_function(FunctionName=name)
        code = got.get("Code", {})
        zbytes = _download(ctx, code.get("Location", "")) if code.get("Location") else None
        if zbytes is None and code.get("Source"):
            import io, zipfile
            mod = (f.get("Handler", "index.handler").rsplit(".", 1)[0].replace(".", "/") or "index") + ".py"
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                z.writestr(mod, code["Source"])
            zbytes = buf.getvalue()
        attrs = {"function_name": name, "role": ctx.ref("aws_iam_role", f["Role"], "arn"), "runtime": f.get("Runtime"),
                 "handler": f.get("Handler"), "description": f.get("Description") or None,
                 "memory_size": f["MemorySize"] if f.get("MemorySize") not in (None, 128) else None,
                 "timeout": f["Timeout"] if f.get("Timeout") not in (None, 3) else None,
                 "architectures": f.get("Architectures") if f.get("Architectures") not in (None, ["x86_64"]) else None,
                 "layers": f.get("Layers") and [l["Arn"] for l in f["Layers"]] or None,
                 "tags": got.get("Tags") or None}
        blocks = []
        env = (f.get("Environment") or {}).get("Variables")
        if env:
            blocks.append(("environment", {"variables": env}))
        if zbytes is not None:
            path = f"lambda/{name}.zip"
            ctx.files_bin[path] = zbytes
            attrs["filename"] = path
            attrs["source_code_hash"] = hcl.Ref(f'filebase64sha256("{path}")')
        addr = ctx.add("aws_lambda_function", f["FunctionArn"], name, attrs, blocks, file="lambda.tf")
        try:
            pol = json.loads(lam.get_policy(FunctionName=name)["Policy"])
        except Exception:  # noqa: BLE001 - no resource policy
            pol = {}
        for st in pol.get("Statement", []):
            princ = st.get("Principal", {})
            principal = princ.get("Service") or princ.get("AWS") or "*"
            cond = st.get("Condition", {})
            src = (cond.get("ArnLike") or cond.get("ArnEquals") or {}).get("AWS:SourceArn")
            ctx.add("aws_lambda_permission", f"{name}/{st.get('Sid')}", f"{name}_{st.get('Sid', 'perm')}",
                    {"statement_id": st.get("Sid"), "action": st.get("Action"), "function_name": hcl.Ref(f"{addr}.function_name"),
                     "principal": principal, "source_arn": src}, file="lambda.tf")
