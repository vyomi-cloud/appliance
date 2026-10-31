# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Lambda core — substrate-independent serverless data plane (PARITY P4 #14, extended for
the v4 console). The first real function-invoke path in the simulator: register a
function's code, then synchronously **Invoke** it — the code actually runs against the
event payload and its return value is the response.

Speaks the native **Lambda REST API** (`/2015-03-31/functions/...` plus the handful of
versioned sibling paths real Lambda uses for sub-resources — `layers`,
`event-source-mappings`, `.../url`, `.../aliases`, `.../versions`, `.../tags`,
`.../concurrency`, `.../recursion-config`, `.../event-invoke-config`) so an unmodified
boto3 `lambda` client works for the core lifecycle: CreateFunction / GetFunction /
ListFunctions / DeleteFunction / UpdateFunctionCode / UpdateFunctionConfiguration / Invoke,
plus Tags, Function URLs, Aliases, Versions, Layers, Event source mappings, reserved
concurrency and recursive-loop detection. NO fastapi / boto3 / socket imports → loads
under Pyodide.

Runtime: a **sandboxed Python runtime**. The function code (Code.ZipFile as base64, or the
simulator-friendly Code.Source string) must define `handler(event, context)`. Invoke execs
it in a restricted namespace — a curated safe builtins subset, `json` available, and NO
__import__ / open / exec / eval / compile / file or network access. This is a real,
deterministic simulation of a Python-runtime function; other runtimes (node/go) and
async/event-source invokes slot in behind the same seam.

Honest scope (declared in core/capabilities/aws/lambda.json, not hidden):
  * "Triggers" (Add trigger / event source mappings) are stored and listed for real for
    every source type the console offers (SQS, DynamoDB, Kinesis, S3, SNS, EventBridge,
    API Gateway, CloudWatch Logs), but Vyomi never polls/subscribes the other service — no
    trigger ever actually invokes the function on its own. Only direct Invoke (Test tab /
    native API) runs code.
  * Code signing configurations are not modeled (no cryptographic signing pipeline).
  * VPC / file-system config is shape-validated for real: SubnetIds/SecurityGroupIds must be
    given in pairs and look like real EC2 resource IDs, and an EFS access point's Arn and
    LocalMountPath must be well-formed — see `_validate_network_config`. Vyomi has no VPC engine
    on this seam, so a syntactically valid but nonexistent subnet/security group/file system is
    still accepted, stored and returned exactly as configured; Vyomi never attaches a real ENI
    or mounts EFS, so code never actually reaches either at Invoke time. Async-invoke
    Destinations and the legacy DeadLetterConfig DO deliver for real (SQS/SNS/Lambda targets) —
    see `_deliver_async_result`.
  * Reserved concurrency of 0 really throttles (TooManyRequestsException); a positive value
    is stored but not enforced (every Invoke is synchronous, so nothing runs concurrently).
  * "Recent invocations" / Metrics are Vyomi's own lightweight read of the last invocations
    the sandbox actually ran — not a real CloudWatch Logs Insights / X-Ray integration.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import time
import uuid
from dataclasses import dataclass, field

# A curated safe builtins subset — no open / exec / eval / compile. A restricted
# __import__ (below) is added so realistic handlers can `import json` etc.
_SAFE_BUILTINS = {
    name: __builtins__[name] if isinstance(__builtins__, dict) else getattr(__builtins__, name)
    for name in ("abs", "all", "any", "bool", "dict", "enumerate", "filter", "float",
                 "int", "len", "list", "map", "max", "min", "range", "reversed",
                 "round", "set", "sorted", "str", "sum", "tuple", "zip", "print",
                 "isinstance", "hasattr", "getattr", "repr", "type", "chr", "ord",
                 "Exception", "ValueError", "KeyError", "TypeError", "IndexError")
}

# Stdlib modules a function may import — pure/computational only. Deliberately
# EXCLUDES os / sys / subprocess / socket / importlib / ctypes / io / pathlib /
# shutil / builtins, so a handler cannot reach the filesystem, network or process.
_SAFE_MODULES = {"json", "math", "datetime", "base64", "re", "random", "uuid",
                 "hashlib", "hmac", "itertools", "functools", "collections",
                 "string", "decimal", "statistics", "textwrap", "time"}

ACCOUNT_ID = "123456789012"
REGION = "us-east-1"
ACCOUNT_CONCURRENCY_LIMIT = 1000
TRIGGER_SOURCES = ("SQS", "DynamoDB", "Kinesis", "S3", "SNS", "EventBridge (CloudWatch Events)",
                   "API Gateway", "CloudWatch Logs")
RECENT_INVOCATIONS_KEPT = 20


def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):
    root = name.split(".")[0]
    if root not in _SAFE_MODULES:
        raise ImportError(f"module '{name}' is not available in the Lambda sandbox")
    import importlib
    return importlib.import_module(name)


_SAFE_BUILTINS["__import__"] = _safe_import


@dataclass
class LambdaResponse:
    status: int = 200
    body: bytes = b""
    headers: dict = field(default_factory=dict)
    media_type: str | None = "application/json"


def _json(status: int, obj: dict, headers: dict | None = None) -> LambdaResponse:
    return LambdaResponse(status=status, body=json.dumps(obj).encode(), headers=headers or {})


def _err(status: int, err_type: str, message: str) -> LambdaResponse:
    # Body carries BOTH the real-Lambda shape (top-level "Message") and an
    # "error": {code, message} wrapper — the latter is what the console's generic
    # restJson() wire helper (consoles/src/common/wire.js) parses errors with.
    return LambdaResponse(status=status, body=json.dumps({"Message": message, "error": {"code": err_type, "message": message}}).encode(),
                          headers={"x-amzn-errortype": err_type})


# ── store accessors (public dict attrs are the persistence seam) ───────────────────────
def _functions(store) -> dict:
    m = getattr(store, "_lambda_functions", None)
    if m is None:
        m = {}
        store._lambda_functions = m
    return m


def _layers(store) -> dict:
    m = getattr(store, "_lambda_layers", None)
    if m is None:
        m = {}
        store._lambda_layers = m
    return m


def _esms(store) -> dict:
    m = getattr(store, "_lambda_esms", None)
    if m is None:
        m = {}
        store._lambda_esms = m
    return m


# Vyomi-exclusive console surfaces (EC2 capacity providers, code signing, MicroVMs +
# their network connectors, applications): the deep runtime behavior these names imply
# in the real console (EC2-backed execution, cryptographic signing, Firecracker VMs) is
# NOT simulated, but the resource itself — create, list, delete, the fields the console
# shows — is real, stored state round-tripping over the native wire, same as Layers.
def _capacity_providers(store) -> dict:
    m = getattr(store, "_lambda_capacity_providers", None)
    if m is None:
        m = {}
        store._lambda_capacity_providers = m
    return m


def _code_signing_configs(store) -> dict:
    m = getattr(store, "_lambda_code_signing_configs", None)
    if m is None:
        m = {}
        store._lambda_code_signing_configs = m
    return m


def _network_connectors(store) -> dict:
    m = getattr(store, "_lambda_network_connectors", None)
    if m is None:
        m = {}
        store._lambda_network_connectors = m
    return m


def _microvm_images(store) -> dict:
    m = getattr(store, "_lambda_microvm_images", None)
    if m is None:
        m = {}
        store._lambda_microvm_images = m
    return m


def _microvms(store) -> dict:
    m = getattr(store, "_lambda_microvms", None)
    if m is None:
        m = {}
        store._lambda_microvms = m
    return m


def _applications(store) -> dict:
    m = getattr(store, "_lambda_applications", None)
    if m is None:
        m = {}
        store._lambda_applications = m
    return m


def _persist(store):
    if hasattr(store, "persist"):
        try:
            store.persist()
        except Exception:
            pass


def _zip_module(raw: bytes, handler: str = "") -> str:
    """The handler module's source out of a real deployment package (a .zip archive, what
    boto3 / the CLI / SAM send): `{module path}.py` for Handler `pkg.mod.fn`, else the first
    .py file. "" when `raw` is not a zip."""
    if not raw[:2] == b"PK":
        return ""
    try:
        import io
        import zipfile
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            names = zf.namelist()
            module = (str(handler or "").rsplit(".", 1)[0].replace(".", "/") + ".py") if "." in str(handler or "") else ""
            pick = module if module in names else next((n for n in names if n.endswith(".py")), "")
            return zf.read(pick).decode("utf-8") if pick else ""
    except Exception:
        return ""


def _extract_source(code: dict, handler: str = "") -> str:
    """Function source from Code.ZipFile (base64 of a .zip deployment package, or of the bare
    source), or the simulator-friendly Code.Source (plain string)."""
    if not isinstance(code, dict):
        return ""
    if code.get("Source"):
        return str(code["Source"])
    zf = code.get("ZipFile")
    if zf:
        try:
            raw = base64.b64decode(zf)
        except Exception:
            raw = zf if isinstance(zf, (bytes, bytearray)) else str(zf).encode()
        if raw[:2] == b"PK":
            return _zip_module(bytes(raw), handler)
        try:
            return raw.decode("utf-8")
        except Exception:
            return ""
    return ""


_NAME_OK = __import__("re").compile(r"^[A-Za-z0-9_-]{1,64}$")


def _norm_name(name: str) -> str:
    """FunctionName as real Lambda accepts it in the path: a name, a full / partial ARN
    (`arn:aws:lambda:…:function:NAME[:QUALIFIER]`, `ACCOUNT:function:NAME`)."""
    from urllib.parse import unquote
    n = unquote(str(name or ""))
    if ":function:" in n:
        n = n.split(":function:", 1)[1].split(":", 1)[0]
    return n


def _now_iso() -> str:
    """Lambda's LastModified format: 2026-10-29T01:52:56.000+0000."""
    import datetime as _dt
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000+0000")


def _fn_arn(name: str, qualifier: str | None = None) -> str:
    base = f"arn:aws:lambda:{REGION}:{ACCOUNT_ID}:function:{name}"
    return f"{base}:{qualifier}" if qualifier else base


def _layer_arn(name: str, version: int | None = None) -> str:
    base = f"arn:aws:lambda:{REGION}:{ACCOUNT_ID}:layer:{name}"
    return f"{base}:{version}" if version else base


def _fn_view(fn: dict, qualifier: str | None = None) -> dict:
    out = {
        "FunctionName": fn["name"], "FunctionArn": _fn_arn(fn["name"], qualifier),
        "Runtime": fn.get("runtime", "python3.12"), "Handler": fn.get("handler", "index.handler"),
        "CodeSize": len(fn.get("source", "")), "CodeSha256": fn.get("code_sha256", ""),
        "Version": qualifier or "$LATEST",
        "MemorySize": fn.get("memory_size", 128), "Timeout": fn.get("timeout", 3),
        "Role": fn.get("role", ""), "Description": fn.get("description", ""),
        "PackageType": "Zip", "State": "Active", "LastUpdateStatus": "Successful",
        "Architectures": fn.get("architectures", ["x86_64"]),
        "EphemeralStorage": {"Size": fn.get("ephemeral_storage_mb", 512)},
        "SnapStart": {"ApplyOn": fn.get("snap_start", "None"), "OptimizationStatus": "Off"},
        "Environment": {"Variables": fn.get("env", {})},
        "LastModified": fn.get("last_modified", ""),
        "RevisionId": fn.get("revision_id", ""),
        "TracingConfig": {"Mode": fn.get("tracing_mode", "PassThrough")},
        "LoggingConfig": {"LogFormat": fn.get("log_format", "Text")},
    }
    if fn.get("layers"):
        out["Layers"] = [{"Arn": a, "CodeSize": 0} for a in fn["layers"]]
    if fn.get("vpc_config"):
        out["VpcConfig"] = fn["vpc_config"]
    if fn.get("dead_letter_config"):
        out["DeadLetterConfig"] = fn["dead_letter_config"]
    if fn.get("file_systems"):
        out["FileSystemConfigs"] = fn["file_systems"]
    if fn.get("recursive_loop"):
        out["RecursiveLoop"] = fn["recursive_loop"]
    return out


def _find_fn(store, name) -> dict | None:
    return _functions(store).get(name)


def _require_fn(store, name) -> dict:
    fn = _find_fn(store, name)
    if not fn:
        raise _NotFound(f"Function not found: {_fn_arn(name)}")
    return fn


class _NotFound(Exception):
    pass


class _BadInput(Exception):
    pass


_EFS_ARN_RE = re.compile(r"^arn:aws:elasticfilesystem:[a-z0-9-]+:\d{12}:access-point/fsap-[0-9a-f]+$")
_SUBNET_ID_RE = re.compile(r"^subnet-[0-9a-f]{8,17}$")
_SG_ID_RE = re.compile(r"^sg-[0-9a-f]{8,17}$")


def _validate_network_config(vpc_config, file_systems):
    """VPC/EFS references are shape-validated for real (lambda.vpc-filesystems): SubnetIds and
    SecurityGroupIds must both be given (or both omitted — detaching the VPC) and look like real
    EC2 resource IDs, and an EFS access point's Arn/LocalMountPath must be well-formed — the same
    validation real Lambda does before it ever reaches EC2 to check the referenced resources
    actually exist (which Vyomi, with no shared VPC engine on this seam, does not check). Returns
    an error message, or None."""
    if vpc_config:
        subnet_ids = list(vpc_config.get("SubnetIds") or [])
        sg_ids = list(vpc_config.get("SecurityGroupIds") or [])
        if subnet_ids or sg_ids:  # both empty == detach the VPC, same as real Lambda
            if not subnet_ids or not sg_ids:
                return "VpcConfig requires at least one subnet ID and one security group ID."
            for sid in subnet_ids:
                if not _SUBNET_ID_RE.match(sid):
                    return f"Invalid subnet ID: '{sid}'"
            for gid in sg_ids:
                if not _SG_ID_RE.match(gid):
                    return f"Invalid security group ID: '{gid}'"
    for fsc in (file_systems or []):
        arn = str(fsc.get("Arn", ""))
        if not _EFS_ARN_RE.match(arn):
            return f"Invalid file system ARN: {arn}"
        if not str(fsc.get("LocalMountPath", "")).startswith("/mnt/"):
            return "LocalMountPath must be an absolute path under /mnt/"
    return None


# ── control plane: functions ────────────────────────────────────────────────────────────
def _create_function(store, body):
    name = str(body.get("FunctionName", "")).strip()
    if not name:
        return _err(400, "InvalidParameterValueException", "FunctionName is required.")
    if not _NAME_OK.match(name):
        return _err(400, "InvalidParameterValueException",
                    f"1 validation error detected: Value '{name}' at 'functionName' failed to satisfy "
                    "constraint: Member must satisfy regular expression pattern: [a-zA-Z0-9-_]+ (1-64 chars)")
    if name in _functions(store):
        return _err(409, "ResourceConflictException", f"Function already exist: {name}")
    net_err = _validate_network_config(body.get("VpcConfig"), body.get("FileSystemConfigs"))
    if net_err:
        return _err(400, "InvalidParameterValueException", net_err)
    source = _extract_source(body.get("Code") or {}, str(body.get("Handler", "index.handler")))
    fn = {
        "name": name, "arn": _fn_arn(name), "runtime": str(body.get("Runtime", "python3.12")),
        "handler": str(body.get("Handler", "index.handler")), "source": source,
        "code_sha256": base64.b64encode(hashlib.sha256(source.encode()).digest()).decode(),
        "env": dict((body.get("Environment") or {}).get("Variables") or {}),
        "memory_size": int(body.get("MemorySize") or 128), "timeout": int(body.get("Timeout") or 3),
        "role": str(body.get("Role") or "arn:aws:iam::123456789012:role/service-role/lambda-basic-execution"),
        "description": str(body.get("Description") or ""),
        "architectures": list(body.get("Architectures") or ["x86_64"]),
        "ephemeral_storage_mb": int((body.get("EphemeralStorage") or {}).get("Size") or 512),
        "snap_start": (body.get("SnapStart") or {}).get("ApplyOn", "None"),
        "tags": dict(body.get("Tags") or {}),
        "layers": list(body.get("Layers") or []),
        "vpc_config": body.get("VpcConfig") or None,
        "dead_letter_config": body.get("DeadLetterConfig") or None,
        "file_systems": body.get("FileSystemConfigs") or [],
        "recursive_loop": "Terminate",
        "tracing_mode": (body.get("TracingConfig") or {}).get("Mode", "PassThrough"),
        "log_format": (body.get("LoggingConfig") or {}).get("LogFormat", "Text"),
        "reserved_concurrency": None,
        "function_url": None,
        "event_invoke_config": None,
        "policy_statements": {},
        "aliases": {},
        "versions": {}, "next_version": 1,
        "invocations": [],
        "throttles": 0, "async_delivery_failures": 0,
        "last_modified": _now_iso(), "revision_id": uuid.uuid4().hex,
    }
    _functions(store)[name] = fn
    _persist(store)
    return _json(201, _fn_view(fn))


def _update_function_code(store, name, body):
    try:
        fn = _require_fn(store, name)
    except _NotFound as e:
        return _err(404, "ResourceNotFoundException", str(e))
    source = _extract_source(body, fn.get("handler", ""))
    if source:
        fn["source"] = source
        fn["code_sha256"] = base64.b64encode(hashlib.sha256(source.encode()).digest()).decode()
    if body.get("Architectures"):
        fn["architectures"] = list(body["Architectures"])
    fn["last_modified"] = _now_iso()
    fn["revision_id"] = uuid.uuid4().hex
    _persist(store)
    return _json(200, _fn_view(fn))


_CONFIG_FIELDS = {
    "Description": "description", "MemorySize": "memory_size", "Timeout": "timeout",
    "Handler": "handler", "Runtime": "runtime", "Role": "role",
}


def _update_function_configuration(store, name, body):
    try:
        fn = _require_fn(store, name)
    except _NotFound as e:
        return _err(404, "ResourceNotFoundException", str(e))
    net_err = _validate_network_config(body.get("VpcConfig"), body.get("FileSystemConfigs"))
    if net_err:
        return _err(400, "InvalidParameterValueException", net_err)
    for api_key, local_key in _CONFIG_FIELDS.items():
        if api_key in body and body[api_key] is not None:
            fn[local_key] = body[api_key]
    if "Environment" in body:
        fn["env"] = dict((body.get("Environment") or {}).get("Variables") or {})
    if "Layers" in body:
        fn["layers"] = list(body["Layers"] or [])
    if "Architectures" in body:
        fn["architectures"] = list(body["Architectures"] or ["x86_64"])
    if "VpcConfig" in body:
        vc = body["VpcConfig"] or None
        if vc and not vc.get("SubnetIds") and not vc.get("SecurityGroupIds"):
            vc = None  # both empty == detach, same as real Lambda
        fn["vpc_config"] = vc
    if "DeadLetterConfig" in body:
        fn["dead_letter_config"] = body["DeadLetterConfig"] or None
    if "FileSystemConfigs" in body:
        fn["file_systems"] = body["FileSystemConfigs"] or []
    if "EphemeralStorage" in body:
        fn["ephemeral_storage_mb"] = int((body.get("EphemeralStorage") or {}).get("Size") or 512)
    if "SnapStart" in body:
        fn["snap_start"] = (body.get("SnapStart") or {}).get("ApplyOn", "None")
    if "TracingConfig" in body:
        fn["tracing_mode"] = (body.get("TracingConfig") or {}).get("Mode", "PassThrough")
    if "LoggingConfig" in body:
        fn["log_format"] = (body.get("LoggingConfig") or {}).get("LogFormat", "Text")
    fn["last_modified"] = _now_iso()
    fn["revision_id"] = uuid.uuid4().hex
    _persist(store)
    return _json(200, _fn_view(fn))


def _get_function(store, name, qualifier=None):
    fn = _find_fn(store, name)
    if not fn:
        return _err(404, "ResourceNotFoundException", f"Function not found: {_fn_arn(name)}")
    if qualifier and qualifier != "$LATEST":
        snap = fn["versions"].get(qualifier)
        if not snap:
            if qualifier not in fn["aliases"]:
                return _err(404, "ResourceNotFoundException", f"Version not found: {qualifier}")
        cfg = _version_view(fn, qualifier) if snap else _fn_view(fn, fn["aliases"][qualifier]["FunctionVersion"])
    else:
        cfg = _fn_view(fn)
    return _json(200, {"Configuration": cfg, "Tags": fn.get("tags", {}),
                       "Code": {"RepositoryType": "S3", "Location": f"https://vyomi-lambda.example/{name}", "Source": fn.get("source", "")}})


def _get_function_configuration(store, name):
    fn = _find_fn(store, name)
    if not fn:
        return _err(404, "ResourceNotFoundException", f"Function not found: {_fn_arn(name)}")
    return _json(200, _fn_view(fn))


def _list_functions(store):
    return _json(200, {"Functions": [_fn_view(f) for f in _functions(store).values()]})


def _delete_function(store, name):
    if _functions(store).pop(name, None) is None:
        return _err(404, "ResourceNotFoundException", f"Function not found: {_fn_arn(name)}")
    _esms(store)
    store._lambda_esms = {k: v for k, v in _esms(store).items() if v.get("FunctionName") != name}
    _persist(store)
    return LambdaResponse(status=204)


def _delete_version(store, name, version):
    fn = _find_fn(store, name)
    if not fn or fn["versions"].pop(version, None) is None:
        return _err(404, "ResourceNotFoundException", f"Version not found: {version}")
    _persist(store)
    return LambdaResponse(status=204)


# ── tags ─────────────────────────────────────────────────────────────────────────────────
def _tag_resource(store, name, body):
    try:
        fn = _require_fn(store, name)
    except _NotFound as e:
        return _err(404, "ResourceNotFoundException", str(e))
    fn["tags"].update({str(k): str(v) for k, v in (body.get("Tags") or {}).items()})
    _persist(store)
    return _json(200, {})


def _untag_resource(store, name, keys):
    try:
        fn = _require_fn(store, name)
    except _NotFound as e:
        return _err(404, "ResourceNotFoundException", str(e))
    for k in keys:
        fn["tags"].pop(k, None)
    _persist(store)
    return _json(200, {})


def _list_tags(store, name):
    try:
        fn = _require_fn(store, name)
    except _NotFound as e:
        return _err(404, "ResourceNotFoundException", str(e))
    return _json(200, {"Tags": fn.get("tags", {})})


# ── function URL ─────────────────────────────────────────────────────────────────────────
def _url_view(name, cfg):
    return {"FunctionUrl": f"https://{name.lower()}.lambda-url.{REGION}.on.vyomi/",
            "FunctionArn": _fn_arn(name), "AuthType": cfg.get("AuthType", "AWS_IAM"),
            "Cors": cfg.get("Cors") or {}, "InvokeMode": cfg.get("InvokeMode", "BUFFERED"),
            "CreationTime": cfg.get("CreationTime", _now_iso()), "LastModifiedTime": _now_iso()}


def _create_function_url_config(store, name, body):
    try:
        fn = _require_fn(store, name)
    except _NotFound as e:
        return _err(404, "ResourceNotFoundException", str(e))
    if fn.get("function_url"):
        return _err(409, "ResourceConflictException", "Function URL config already exists.")
    fn["function_url"] = {"AuthType": body.get("AuthType", "AWS_IAM"), "Cors": body.get("Cors") or {},
                          "InvokeMode": body.get("InvokeMode", "BUFFERED"), "CreationTime": _now_iso()}
    _persist(store)
    return _json(201, _url_view(name, fn["function_url"]))


def _get_function_url_config(store, name):
    fn = _find_fn(store, name)
    if not fn:
        return _err(404, "ResourceNotFoundException", f"Function not found: {_fn_arn(name)}")
    if not fn.get("function_url"):
        return _err(404, "ResourceNotFoundException", "The resource you requested doesn't exist.")
    return _json(200, _url_view(name, fn["function_url"]))


def _update_function_url_config(store, name, body):
    try:
        fn = _require_fn(store, name)
    except _NotFound as e:
        return _err(404, "ResourceNotFoundException", str(e))
    if not fn.get("function_url"):
        return _err(404, "ResourceNotFoundException", "The resource you requested doesn't exist.")
    fn["function_url"].update({k: v for k, v in body.items() if k in ("AuthType", "Cors", "InvokeMode")})
    _persist(store)
    return _json(200, _url_view(name, fn["function_url"]))


def _delete_function_url_config(store, name):
    fn = _find_fn(store, name)
    if not fn or not fn.get("function_url"):
        return _err(404, "ResourceNotFoundException", "The resource you requested doesn't exist.")
    fn["function_url"] = None
    _persist(store)
    return LambdaResponse(status=204)


# ── aliases ──────────────────────────────────────────────────────────────────────────────
def _alias_view(name, a):
    return {"AliasArn": _fn_arn(name, a["Name"]), "Name": a["Name"], "FunctionVersion": a["FunctionVersion"],
            "Description": a.get("Description", ""), "RoutingConfig": a.get("RoutingConfig"),
            "RevisionId": a.get("RevisionId", "")}


def _create_alias(store, name, body):
    try:
        fn = _require_fn(store, name)
    except _NotFound as e:
        return _err(404, "ResourceNotFoundException", str(e))
    alias_name = str(body.get("Name", "")).strip()
    if not alias_name:
        return _err(400, "InvalidParameterValueException", "Name is required.")
    if alias_name in fn["aliases"]:
        return _err(409, "ResourceConflictException", f"Alias already exists: {alias_name}")
    a = {"Name": alias_name, "FunctionVersion": str(body.get("FunctionVersion", "$LATEST")),
        "Description": body.get("Description", ""), "RoutingConfig": body.get("RoutingConfig"),
        "RevisionId": uuid.uuid4().hex}
    fn["aliases"][alias_name] = a
    _persist(store)
    return _json(201, _alias_view(name, a))


def _list_aliases(store, name):
    try:
        fn = _require_fn(store, name)
    except _NotFound as e:
        return _err(404, "ResourceNotFoundException", str(e))
    return _json(200, {"Aliases": [_alias_view(name, a) for a in fn["aliases"].values()]})


def _get_alias(store, name, alias_name):
    fn = _find_fn(store, name)
    a = fn and fn["aliases"].get(alias_name)
    if not a:
        return _err(404, "ResourceNotFoundException", f"Alias not found: {alias_name}")
    return _json(200, _alias_view(name, a))


def _update_alias(store, name, alias_name, body):
    fn = _find_fn(store, name)
    a = fn and fn["aliases"].get(alias_name)
    if not a:
        return _err(404, "ResourceNotFoundException", f"Alias not found: {alias_name}")
    for k in ("FunctionVersion", "Description", "RoutingConfig"):
        if k in body:
            a[k] = body[k]
    a["RevisionId"] = uuid.uuid4().hex
    _persist(store)
    return _json(200, _alias_view(name, a))


def _delete_alias(store, name, alias_name):
    fn = _find_fn(store, name)
    if not fn or fn["aliases"].pop(alias_name, None) is None:
        return _err(404, "ResourceNotFoundException", f"Alias not found: {alias_name}")
    _persist(store)
    return LambdaResponse(status=204)


# ── versions ─────────────────────────────────────────────────────────────────────────────
def _version_view(fn, version):
    snap = fn["versions"][version]
    v = _fn_view({**fn, **snap}, qualifier=version)
    return v


def _publish_version(store, name, body):
    try:
        fn = _require_fn(store, name)
    except _NotFound as e:
        return _err(404, "ResourceNotFoundException", str(e))
    version = str(fn["next_version"])
    fn["next_version"] += 1
    fn["versions"][version] = {
        "source": fn["source"], "code_sha256": fn["code_sha256"], "runtime": fn["runtime"],
        "handler": fn["handler"], "memory_size": fn["memory_size"], "timeout": fn["timeout"],
        "env": dict(fn["env"]), "description": body.get("Description", fn["description"]),
        "last_modified": _now_iso(),
    }
    _persist(store)
    return _json(201, _version_view(fn, version))


def _list_versions_by_function(store, name):
    try:
        fn = _require_fn(store, name)
    except _NotFound as e:
        return _err(404, "ResourceNotFoundException", str(e))
    versions = [_fn_view(fn, "$LATEST")] + [_version_view(fn, v) for v in sorted(fn["versions"], key=int)]
    return _json(200, {"Versions": versions})


# ── layers ───────────────────────────────────────────────────────────────────────────────
def _layer_version_view(layer_name, version, v):
    return {"LayerVersionArn": _layer_arn(layer_name, version), "LayerArn": _layer_arn(layer_name),
            "Version": version, "Description": v.get("Description", ""),
            "CreatedDate": v.get("CreatedDate", ""), "CompatibleRuntimes": v.get("CompatibleRuntimes", []),
            "CompatibleArchitectures": v.get("CompatibleArchitectures", []),
            "LicenseInfo": v.get("LicenseInfo", ""), "Content": {"CodeSize": v.get("CodeSize", 0)}}


def _publish_layer_version(store, layer_name, body):
    layers = _layers(store)
    entry = layers.setdefault(layer_name, {"versions": {}, "next_version": 1})
    version = entry["next_version"]
    entry["next_version"] += 1
    source = _extract_source(body.get("Content") or {}) or str((body.get("Content") or {}).get("S3Key") or "")
    entry["versions"][version] = {
        "Description": body.get("Description", ""), "CreatedDate": _now_iso(),
        "CompatibleRuntimes": body.get("CompatibleRuntimes") or [],
        "CompatibleArchitectures": body.get("CompatibleArchitectures") or [],
        "LicenseInfo": body.get("LicenseInfo", ""), "CodeSize": len(source),
        "Source": source,   # merged into the function's runtime by stores with a real runtime
    }
    _persist(store)
    return _json(201, _layer_version_view(layer_name, version, entry["versions"][version]))


def _list_layers(store, body=None):
    out = []
    for layer_name, entry in _layers(store).items():
        if not entry["versions"]:
            continue
        latest = max(entry["versions"])
        lv = _layer_version_view(layer_name, latest, entry["versions"][latest])
        out.append({"LayerName": layer_name, "LayerArn": _layer_arn(layer_name),
                    "LatestMatchingVersion": lv})
    return _json(200, {"Layers": out})


def _list_layer_versions(store, layer_name):
    entry = _layers(store).get(layer_name, {"versions": {}})
    rows = [_layer_version_view(layer_name, v, entry["versions"][v]) for v in sorted(entry["versions"], reverse=True)]
    return _json(200, {"LayerVersions": rows})


def _get_layer_version(store, layer_name, version):
    entry = _layers(store).get(layer_name)
    v = entry and entry["versions"].get(int(version))
    if not v:
        return _err(404, "ResourceNotFoundException", f"Layer version not found: {layer_name}:{version}")
    return _json(200, _layer_version_view(layer_name, int(version), v))


def _delete_layer_version(store, layer_name, version):
    entry = _layers(store).get(layer_name)
    if not entry or entry["versions"].pop(int(version), None) is None:
        return _err(404, "ResourceNotFoundException", f"Layer version not found: {layer_name}:{version}")
    _persist(store)
    return LambdaResponse(status=204)


# ── event source mappings ("Triggers") ──────────────────────────────────────────────────
# Modeled for every source the console offers (SQS/DynamoDB/Kinesis/S3/SNS/EventBridge/
# API Gateway/CloudWatch Logs) as one UUID-keyed, listable, deletable record — but Vyomi
# never polls or subscribes the other service, so LastProcessingResult always reads
# "No records processed" and the trigger never fires on its own (see module docstring).
def _esm_view(e):
    return {"UUID": e["UUID"], "EventSourceArn": e.get("EventSourceArn", ""),
            "FunctionArn": _fn_arn(e["FunctionName"]), "FunctionName": e["FunctionName"],
            "EventSourceType": e.get("EventSourceType", "Unknown"),
            "State": e.get("State", "Enabled"), "StateTransitionReason": "USER_INITIATED",
            "BatchSize": e.get("BatchSize", 10), "LastModified": e.get("LastModified", ""),
            "LastProcessingResult": "No records processed"}


def _create_event_source_mapping(store, body):
    fn_name = str(body.get("FunctionName", "")).strip()
    try:
        _require_fn(store, fn_name)
    except _NotFound as e:
        return _err(404, "ResourceNotFoundException", str(e))
    uid = str(uuid.uuid4())
    e = {"UUID": uid, "FunctionName": fn_name, "EventSourceArn": body.get("EventSourceArn", ""),
        "EventSourceType": body.get("EventSourceType") or _esm_source_type(body.get("EventSourceArn", "")),
        "State": "Enabled" if body.get("Enabled", True) else "Disabled",
        "BatchSize": int(body.get("BatchSize") or 10), "LastModified": _now_iso()}
    _esms(store)[uid] = e
    _persist(store)
    return _json(202, _esm_view(e))


def _esm_source_type(arn: str) -> str:
    for token, label in (("sqs", "SQS"), ("dynamodb", "DynamoDB"), ("kinesis", "Kinesis"),
                        ("s3", "S3"), ("sns", "SNS"), ("events", "EventBridge (CloudWatch Events)"),
                        ("logs", "CloudWatch Logs"), ("execute-api", "API Gateway")):
        if f":{token}:" in arn or arn.startswith(token):
            return label
    return "Unknown"


def _list_event_source_mappings(store, function_name=None):
    rows = [e for e in _esms(store).values() if not function_name or e["FunctionName"] == function_name]
    rows.sort(key=lambda e: e["LastModified"])
    return _json(200, {"EventSourceMappings": [_esm_view(e) for e in rows]})


def _get_event_source_mapping(store, uid):
    e = _esms(store).get(uid)
    if not e:
        return _err(404, "ResourceNotFoundException", f"Event source mapping not found: {uid}")
    return _json(200, _esm_view(e))


def _update_event_source_mapping(store, uid, body):
    e = _esms(store).get(uid)
    if not e:
        return _err(404, "ResourceNotFoundException", f"Event source mapping not found: {uid}")
    if "Enabled" in body:
        e["State"] = "Enabled" if body["Enabled"] else "Disabled"
    if "BatchSize" in body:
        e["BatchSize"] = int(body["BatchSize"])
    e["LastModified"] = _now_iso()
    _persist(store)
    return _json(200, _esm_view(e))


def _delete_event_source_mapping(store, uid):
    e = _esms(store).pop(uid, None)
    if not e:
        return _err(404, "ResourceNotFoundException", f"Event source mapping not found: {uid}")
    e["State"] = "Deleting"
    _persist(store)
    return _json(200, _esm_view(e))


# ── Capacity providers (Vyomi-exclusive; see module note above _capacity_providers) ────
def _capacity_provider_view(cp):
    return {"Name": cp["name"], "State": cp["state"], "Architectures": cp["architectures"],
            "MaximumVcpu": cp["max_vcpu"], "ScalingMode": cp["scaling_mode"],
            "VpcId": cp.get("vpc_id", ""), "LastModified": cp["last_modified"]}


def _create_capacity_provider(store, body):
    name = str(body.get("Name", "")).strip()
    if not name:
        return _err(400, "ValidationException", "Name is required")
    store_m = _capacity_providers(store)
    if name in store_m:
        return _err(409, "ResourceConflictException", f"Capacity provider already exists: {name}")
    cp = {"name": name, "state": "ACTIVE", "architectures": body.get("Architectures") or ["x86_64"],
          "max_vcpu": int(body.get("MaximumVcpu") or 4), "scaling_mode": body.get("ScalingMode") or "Managed scaling",
          "vpc_id": body.get("VpcId", ""), "last_modified": _now_iso()}
    store_m[name] = cp
    _persist(store)
    return _json(201, _capacity_provider_view(cp))


def _list_capacity_providers(store):
    rows = sorted(_capacity_providers(store).values(), key=lambda c: c["name"])
    return _json(200, {"CapacityProviders": [_capacity_provider_view(c) for c in rows]})


def _delete_capacity_provider(store, name):
    cp = _capacity_providers(store).pop(name, None)
    if not cp:
        return _err(404, "ResourceNotFoundException", f"Capacity provider not found: {name}")
    _persist(store)
    return _json(200, _capacity_provider_view(cp))


# ── Code signing configurations (Vyomi-exclusive) ───────────────────────────────────────
def _csc_view(c):
    return {"CodeSigningConfigId": c["id"], "CodeSigningConfigArn": f"arn:aws:lambda:{REGION}:{ACCOUNT_ID}:code-signing-config:{c['id']}",
            "Description": c.get("description", ""),
            "AllowedPublishers": {"SigningProfileVersionArns": c.get("signing_profiles", [])},
            "CodeSigningPolicies": {"UntrustedArtifactOnDeployment": c.get("policy", "Warn")},
            "LastModified": c["last_modified"]}


def _create_csc(store, body):
    cid = f"csc-{uuid.uuid4().hex[:17]}"
    c = {"id": cid, "description": body.get("Description", ""),
         "signing_profiles": (body.get("AllowedPublishers") or {}).get("SigningProfileVersionArns", []),
         "policy": (body.get("CodeSigningPolicies") or {}).get("UntrustedArtifactOnDeployment", "Warn"),
         "last_modified": _now_iso()}
    _code_signing_configs(store)[cid] = c
    _persist(store)
    return _json(201, _csc_view(c))


def _list_cscs(store):
    rows = sorted(_code_signing_configs(store).values(), key=lambda c: c["last_modified"])
    return _json(200, {"CodeSigningConfigs": [_csc_view(c) for c in rows]})


def _update_csc(store, cid, body):
    c = _code_signing_configs(store).get(cid)
    if not c:
        return _err(404, "ResourceNotFoundException", f"Code signing config not found: {cid}")
    if "Description" in body:
        c["description"] = body["Description"]
    if "AllowedPublishers" in body:
        c["signing_profiles"] = (body["AllowedPublishers"] or {}).get("SigningProfileVersionArns", [])
    if "CodeSigningPolicies" in body:
        c["policy"] = (body["CodeSigningPolicies"] or {}).get("UntrustedArtifactOnDeployment", c["policy"])
    c["last_modified"] = _now_iso()
    _persist(store)
    return _json(200, _csc_view(c))


def _delete_csc(store, cid):
    c = _code_signing_configs(store).pop(cid, None)
    if not c:
        return _err(404, "ResourceNotFoundException", f"Code signing config not found: {cid}")
    _persist(store)
    return _json(200, {})


# ── Network connectors (Vyomi-exclusive; bridge a MicroVM into a VPC) ──────────────────
def _nc_view(n):
    return {"Name": n["name"], "Id": n["id"],
            "Arn": f"arn:aws:lambda:{REGION}:{ACCOUNT_ID}:network-connector:{n['name']}",
            "Type": n.get("compute_type", "MicroVm"), "VpcId": n.get("vpc_id", ""),
            "NetworkProtocol": n.get("protocol", ""), "State": n["state"], "LastModified": n["last_modified"]}


def _create_network_connector(store, body):
    name = str(body.get("Name", "")).strip()
    if not name:
        return _err(400, "ValidationException", "Name is required")
    store_m = _network_connectors(store)
    if name in store_m:
        return _err(409, "ResourceConflictException", f"Network connector already exists: {name}")
    n = {"name": name, "id": f"ncr-{uuid.uuid4().hex[:12]}", "vpc_id": body.get("VpcId", ""),
         "compute_type": body.get("AssociatedComputeType") or "MicroVm", "protocol": body.get("NetworkProtocol", ""),
         "state": "AVAILABLE", "last_modified": _now_iso()}
    store_m[name] = n
    _persist(store)
    return _json(201, _nc_view(n))


def _list_network_connectors(store):
    rows = sorted(_network_connectors(store).values(), key=lambda n: n["name"])
    return _json(200, {"NetworkConnectors": [_nc_view(n) for n in rows]})


def _delete_network_connector(store, name):
    n = _network_connectors(store).pop(name, None)
    if not n:
        return _err(404, "ResourceNotFoundException", f"Network connector not found: {name}")
    _persist(store)
    return _json(200, _nc_view(n))


# ── MicroVM images (Vyomi-exclusive; Firecracker VM images layered on Lambda) ──────────
def _microvm_image_view(i):
    return {"Name": i["name"], "Description": i.get("description", ""), "State": i["state"],
            "ActiveVersion": i.get("active_version", 1), "FailedVersion": i.get("failed_version"),
            "Created": i["created"], "ImageArn": f"arn:aws:lambda:{REGION}:{ACCOUNT_ID}:microvm-image:{i['name']}"}


def _create_microvm_image(store, body):
    name = str(body.get("Name", "")).strip()
    if not name:
        return _err(400, "ValidationException", "Name is required")
    store_m = _microvm_images(store)
    if name in store_m:
        return _err(409, "ResourceConflictException", f"MicroVM image already exists: {name}")
    i = {"name": name, "description": body.get("Description", ""), "state": "ACTIVE",
         "active_version": 1, "failed_version": None, "created": _now_iso()}
    store_m[name] = i
    _persist(store)
    return _json(201, _microvm_image_view(i))


def _list_microvm_images(store):
    rows = sorted(_microvm_images(store).values(), key=lambda i: i["name"])
    return _json(200, {"MicrovmImages": [_microvm_image_view(i) for i in rows]})


def _delete_microvm_image(store, name):
    i = _microvm_images(store).pop(name, None)
    if not i:
        return _err(404, "ResourceNotFoundException", f"MicroVM image not found: {name}")
    _persist(store)
    return _json(200, _microvm_image_view(i))


# ── MicroVMs (Vyomi-exclusive; a running instance of a MicroVM image) ──────────────────
def _microvm_view(m):
    return {"Id": m["id"], "Status": m["status"], "MicrovmImage": m.get("microvm_image", ""),
            "Version": m.get("version", 1), "CreationTime": m["creation_time"]}


def _run_microvm(store, body):
    image = str(body.get("MicrovmImage", "")).strip()
    if not image:
        return _err(400, "ValidationException", "MicrovmImage is required")
    if image not in _microvm_images(store):
        return _err(404, "ResourceNotFoundException", f"MicroVM image not found: {image}")
    mid = f"mvm-{uuid.uuid4().hex[:12]}"
    m = {"id": mid, "status": "RUNNING", "microvm_image": image, "version": body.get("Version") or 1,
         "creation_time": _now_iso()}
    _microvms(store)[mid] = m
    _persist(store)
    return _json(201, _microvm_view(m))


def _list_microvms(store):
    rows = sorted(_microvms(store).values(), key=lambda m: m["creation_time"])
    return _json(200, {"Microvms": [_microvm_view(m) for m in rows]})


def _delete_microvm(store, mid):
    m = _microvms(store).pop(mid, None)
    if not m:
        return _err(404, "ResourceNotFoundException", f"MicroVM not found: {mid}")
    _persist(store)
    return _json(200, _microvm_view(m))


# ── Applications (Vyomi-exclusive; a tracked deployment record, not a real
#    CloudFormation/SAM stack — Vyomi has no CloudFormation core to provision one) ──────
def _application_view(a):
    return {"Name": a["name"], "Description": a.get("description", ""), "Status": a["status"],
            "LastModified": a["last_modified"], "Template": a.get("template", "From scratch")}


def _create_application(store, body):
    name = str(body.get("Name", "")).strip()
    if not name:
        return _err(400, "ValidationException", "Name is required")
    store_m = _applications(store)
    if name in store_m:
        return _err(409, "ResourceConflictException", f"Application already exists: {name}")
    a = {"name": name, "description": body.get("Description", ""), "status": "CREATE_COMPLETE",
         "template": body.get("Template", "From scratch"), "last_modified": _now_iso()}
    store_m[name] = a
    _persist(store)
    return _json(201, _application_view(a))


def _list_applications(store):
    rows = sorted(_applications(store).values(), key=lambda a: a["name"])
    return _json(200, {"Applications": [_application_view(a) for a in rows]})


def _delete_application(store, name):
    a = _applications(store).pop(name, None)
    if not a:
        return _err(404, "ResourceNotFoundException", f"Application not found: {name}")
    _persist(store)
    return _json(200, _application_view(a))


# ── Replicas (Vyomi-exclusive; Lambda@Edge copies of a function). Derived directly from
#    the function record it replicates — never a separate fabricated store — so a replica
#    always reflects that function's real Description/Runtime/LastModified. ────────────
def _replica_view(fn, region):
    return {"FunctionName": fn["name"], "Description": fn.get("description", ""),
            "Runtime": fn.get("runtime", "python3.12"), "Region": region,
            "LastModified": fn.get("last_modified", "")}


def _replicate_function(store, name, body):
    try:
        fn = _require_fn(store, name)
    except _NotFound as e:
        return _err(404, "ResourceNotFoundException", str(e))
    regions = [r for r in (body.get("Regions") or []) if r]
    fn["replicated_regions"] = sorted(set(fn.get("replicated_regions") or []) | set(regions))
    _persist(store)
    return _json(200, {"FunctionName": name, "Regions": fn["replicated_regions"]})


def _list_replicas(store):
    rows = []
    for fn in _functions(store).values():
        for region in fn.get("replicated_regions") or []:
            rows.append(_replica_view(fn, region))
    rows.sort(key=lambda r: r["FunctionName"])
    return _json(200, {"Replicas": rows})


# ── resource policy (AddPermission / GetPolicy / RemovePermission) ─────────────────────
def _add_permission(store, name, body):
    try:
        fn = _require_fn(store, name)
    except _NotFound as e:
        return _err(404, "ResourceNotFoundException", str(e))
    sid = str(body.get("StatementId", "")).strip()
    if not sid:
        return _err(400, "InvalidParameterValueException", "StatementId is required.")
    if sid in fn["policy_statements"]:
        return _err(409, "ResourceConflictException", f"Statement already exists: {sid}")
    principal = str(body.get("Principal", "*") or "*")
    principal_doc = "*" if principal == "*" else (
        {"AWS": principal} if principal.startswith("arn:") or principal.isdigit() else {"Service": principal})
    stmt = {"Sid": sid, "Effect": "Allow", "Action": body.get("Action", "lambda:InvokeFunction"),
            "Principal": principal_doc, "Resource": _fn_arn(name)}
    cond: dict = {}
    if body.get("PrincipalOrgID"):
        cond.setdefault("StringEquals", {})["aws:PrincipalOrgID"] = body["PrincipalOrgID"]
    if body.get("SourceArn"):
        cond.setdefault("ArnLike", {})["AWS:SourceArn"] = body["SourceArn"]
    if body.get("SourceAccount"):
        cond.setdefault("StringEquals", {})["AWS:SourceAccount"] = body["SourceAccount"]
    if cond:
        stmt["Condition"] = cond
    fn["policy_statements"][sid] = stmt
    _persist(store)
    return _json(201, {"Statement": json.dumps(stmt)})


def _get_policy(store, name):
    try:
        fn = _require_fn(store, name)
    except _NotFound as e:
        return _err(404, "ResourceNotFoundException", str(e))
    if not fn["policy_statements"]:
        return _err(404, "ResourceNotFoundException", "The resource you requested doesn't exist.")
    policy = {"Version": "2012-10-17", "Id": "default", "Statement": list(fn["policy_statements"].values())}
    return _json(200, {"Policy": json.dumps(policy), "RevisionId": uuid.uuid4().hex})


def _remove_permission(store, name, sid):
    fn = _find_fn(store, name)
    if not fn or fn["policy_statements"].pop(sid, None) is None:
        return _err(404, "ResourceNotFoundException", f"Statement not found: {sid}")
    _persist(store)
    return LambdaResponse(status=204)


# ── concurrency / recursion ──────────────────────────────────────────────────────────────
def _put_function_concurrency(store, name, body):
    try:
        fn = _require_fn(store, name)
    except _NotFound as e:
        return _err(404, "ResourceNotFoundException", str(e))
    fn["reserved_concurrency"] = int(body.get("ReservedConcurrentExecutions", 0))
    _persist(store)
    return _json(200, {"ReservedConcurrentExecutions": fn["reserved_concurrency"]})


def _get_function_concurrency(store, name):
    fn = _find_fn(store, name)
    if not fn:
        return _err(404, "ResourceNotFoundException", f"Function not found: {_fn_arn(name)}")
    return _json(200, {"ReservedConcurrentExecutions": fn.get("reserved_concurrency")})


def _delete_function_concurrency(store, name):
    fn = _find_fn(store, name)
    if not fn:
        return _err(404, "ResourceNotFoundException", f"Function not found: {_fn_arn(name)}")
    fn["reserved_concurrency"] = None
    _persist(store)
    return LambdaResponse(status=204)


def _put_function_recursion_config(store, name, body):
    try:
        fn = _require_fn(store, name)
    except _NotFound as e:
        return _err(404, "ResourceNotFoundException", str(e))
    value = body.get("RecursiveLoop", "Terminate")
    if value not in ("Allow", "Terminate"):
        return _err(400, "InvalidParameterValueException", "RecursiveLoop must be Allow or Terminate.")
    fn["recursive_loop"] = value
    _persist(store)
    return _json(200, {"RecursiveLoop": value})


def _get_function_recursion_config(store, name):
    fn = _find_fn(store, name)
    if not fn:
        return _err(404, "ResourceNotFoundException", f"Function not found: {_fn_arn(name)}")
    return _json(200, {"RecursiveLoop": fn.get("recursive_loop", "Terminate")})


# ── event invoke config ("Destinations") ────────────────────────────────────────────────
def _put_function_event_invoke_config(store, name, body):
    try:
        fn = _require_fn(store, name)
    except _NotFound as e:
        return _err(404, "ResourceNotFoundException", str(e))
    cfg = {"DestinationConfig": body.get("DestinationConfig") or {},
          "MaximumRetryAttempts": body.get("MaximumRetryAttempts", 2),
          "MaximumEventAgeInSeconds": body.get("MaximumEventAgeInSeconds", 21600),
          "LastModified": _now_iso()}
    fn["event_invoke_config"] = cfg
    _persist(store)
    return _json(200, {"FunctionArn": _fn_arn(name), **cfg})


def _get_function_event_invoke_config(store, name):
    fn = _find_fn(store, name)
    if not fn or not fn.get("event_invoke_config"):
        return _err(404, "ResourceNotFoundException", "The resource you requested doesn't exist.")
    return _json(200, {"FunctionArn": _fn_arn(name), **fn["event_invoke_config"]})


def _delete_function_event_invoke_config(store, name):
    fn = _find_fn(store, name)
    if not fn or not fn.get("event_invoke_config"):
        return _err(404, "ResourceNotFoundException", "The resource you requested doesn't exist.")
    fn["event_invoke_config"] = None
    _persist(store)
    return LambdaResponse(status=204)


# ── data plane: Invoke ──────────────────────────────────────────────────────────────────
def _record_invocation(fn, request_id, duration_ms, error, extra=None):
    row = {
        "Timestamp": _now_iso(), "RequestId": request_id,
        "LogStream": f"{time.strftime('%Y/%m/%d')}/[$LATEST]{uuid.uuid4().hex}",
        "DurationInMS": round(duration_ms, 2), "BilledDurationInMS": max(1, round(duration_ms)),
        "MemorySetInMB": fn.get("memory_size", 128),
        "MemoryUsedInMB": max(16, round(fn.get("memory_size", 128) * 0.35)),
        "Error": bool(error),
    }
    row.update(extra or {})
    fn["invocations"].insert(0, row)
    del fn["invocations"][RECENT_INVOCATIONS_KEPT:]


def _sandbox_run(fn, event, context) -> dict:
    """The in-process sandboxed Python runtime (Nano; any store without `run_function`)."""
    sandbox_globals = {"__builtins__": dict(_SAFE_BUILTINS), "json": json}
    try:
        exec(compile(fn.get("source", ""), f"<lambda:{fn['name']}>", "exec"), sandbox_globals)
        handler = sandbox_globals.get(fn.get("handler", "index.handler").split(".")[-1]) \
            or sandbox_globals.get("handler")
        if not callable(handler):
            raise RuntimeError("handler is not defined")
        return {"ok": True, "result": handler(event, context)}
    except Exception as e:
        return {"ok": False, "errorType": type(e).__name__, "error": str(e)}


def _statement_principal(stmt) -> str:
    p = stmt.get("Principal", "*")
    if isinstance(p, dict):
        p = p.get("Service") or p.get("AWS") or "*"
    return str(p or "*")


def can_invoke(fn: dict, principal: str = "", source_arn: str = "", source_account: str = "",
               action: str = "lambda:InvokeFunction") -> bool:
    """Resource-policy check for a SERVICE-originated invoke (S3 / SNS / EventBridge … name
    their principal + source). A direct caller (no principal / source) is always allowed —
    Vyomi does not evaluate identity policies here."""
    import fnmatch
    if not (principal or source_arn or source_account):
        return True
    for stmt in (fn.get("policy_statements") or {}).values():
        act = stmt.get("Action", "lambda:InvokeFunction")
        acts = act if isinstance(act, list) else [act]
        if not any(a in ("*", "lambda:*", action) for a in acts):
            continue
        sp = _statement_principal(stmt)
        if sp != "*" and (not principal or not fnmatch.fnmatchcase(principal, sp)):
            continue
        cond = stmt.get("Condition") or {}
        want_arn = (cond.get("ArnLike") or {}).get("AWS:SourceArn") or (cond.get("ArnEquals") or {}).get("AWS:SourceArn")
        if want_arn and (not source_arn or not fnmatch.fnmatchcase(source_arn, want_arn)):
            continue
        want_acct = (cond.get("StringEquals") or {}).get("AWS:SourceAccount")
        if want_acct and want_acct != source_account:
            continue
        return True
    return False


def _event_invoke_envelope(name: str, request_id: str, event, out: dict) -> dict:
    """The envelope a real async-invoke Destination (or, raw `event` instead, a legacy
    DLQ) receives — see `_deliver_async_result`."""
    ok = bool(out.get("ok"))
    envelope = {
        "version": "1.0", "timestamp": _now_iso(),
        "requestContext": {"requestId": request_id, "functionArn": _fn_arn(name, "$LATEST"),
                           "condition": "Success" if ok else "RetriesExhausted",
                           "approximateInvokeCount": 1},
        "requestPayload": event,
        "responseContext": {"statusCode": 200, "executedVersion": "$LATEST"},
    }
    if ok:
        envelope["responsePayload"] = out.get("result")
    else:
        envelope["responseContext"]["functionError"] = "Unhandled"
        envelope["responsePayload"] = {"errorType": out.get("errorType") or "Exception",
                                       "errorMessage": str(out.get("error") or "")}
    return envelope


def _deliver_to_arn(arn: str, payload: dict, msg_store, lam_store) -> bool:
    """Real delivery to an async-invoke target (SQS queue / SNS topic / another Lambda
    function) — reuses EventBridge's cross-core `deliver` (same 3 target types, same
    ARN-sniffing). Local import: eventbridge_core imports lambda_core, so this must stay
    a function-local import to avoid a circular top-level import."""
    from core import eventbridge_core as _eb
    try:
        return bool(_eb.deliver(msg_store, lam_store, arn, json.dumps(payload), payload))
    except Exception:
        return False


def _deliver_async_result(fn: dict, name: str, event, out: dict, request_id: str,
                          msg_store, lam_store) -> None:
    """Fire-and-forget delivery of an Event (async) Invoke's outcome to the function's
    configured Destinations (OnSuccess/OnFailure), falling back to the legacy
    DeadLetterConfig on failure when no OnFailure destination is set — same precedence
    real Lambda uses. No-op if the caller is a synchronous integration path that never
    supplies msg_store (API Gateway / Step Functions / EventBridge targets, which only
    ever reach here with itype == RequestResponse anyway)."""
    if msg_store is None:
        return
    ok = bool(out.get("ok"))
    cfg = (fn.get("event_invoke_config") or {}).get("DestinationConfig") or {}
    dest = ((cfg.get("OnSuccess") if ok else cfg.get("OnFailure")) or {}).get("Destination")
    delivered = True
    if dest:
        delivered = _deliver_to_arn(dest, _event_invoke_envelope(name, request_id, event, out), msg_store, lam_store)
    elif not ok and (fn.get("dead_letter_config") or {}).get("TargetArn"):
        delivered = _deliver_to_arn(fn["dead_letter_config"]["TargetArn"], event, msg_store, lam_store)
    if not delivered:
        fn["async_delivery_failures"] = fn.get("async_delivery_failures", 0) + 1


def _invoke(store, name, body, headers=None, query=None, msg_store=None, lam_store=None):
    fn = _functions(store).get(name)
    if not fn:
        return _err(404, "ResourceNotFoundException", f"Function not found: {_fn_arn(name)}")
    lh = {str(k).lower(): v for k, v in (headers or {}).items()}
    itype = str(lh.get("x-amz-invocation-type") or (query or {}).get("InvocationType") or "RequestResponse")
    if itype == "DryRun":
        return LambdaResponse(status=204, body=b"", media_type=None)
    if fn.get("reserved_concurrency") == 0:
        # Real Lambda: reserving ZERO concurrency blocks every Invoke outright. Vyomi
        # doesn't simulate concurrent execution (every Invoke is synchronous and instant),
        # so this is the one throttle condition it CAN enforce faithfully — see
        # core/capabilities/aws/lambda.json's lambda.concurrency entry.
        fn["throttles"] = fn.get("throttles", 0) + 1
        _persist(store)
        return _err(429, "TooManyRequestsException",
                    "Rate Exceeded. Reason: ReservedFunctionConcurrentInvocationLimitExceeded")
    try:
        event = json.loads(body.decode("utf-8")) if body else {}
    except Exception:
        event = {}
    request_id = uuid.uuid4().hex
    context = {"function_name": name, "aws_request_id": request_id,
               "invoked_function_arn": _fn_arn(name), "memory_limit_in_mb": fn.get("memory_size", 128)}
    # Runtime seam: a store with a REAL runtime (the offline appliance runs the code in a
    # separate Python process with its environment, timeout and layers) supplies
    # `run_function(fn, event, context) -> {ok, result | errorType, error, logs}`; otherwise
    # the in-process sandbox runs it.
    runner = getattr(store, "run_function", None)
    start = time.perf_counter()
    try:
        out = runner(fn, event, context) if callable(runner) else _sandbox_run(fn, event, context)
    except Exception as e:   # a runtime that itself failed
        out = {"ok": False, "errorType": type(e).__name__, "error": str(e)}
    duration_ms = (time.perf_counter() - start) * 1000
    logs = str(out.get("logs") or "")
    extra = {}
    if logs:
        extra["LogTail"] = logs[-4096:]
    if not out.get("ok"):
        extra["ErrorMessage"] = str(out.get("error") or "")[:1024]
    _record_invocation(fn, request_id, duration_ms, error=not out.get("ok"), extra=extra)
    if itype == "Event":
        _deliver_async_result(fn, name, event, out, request_id, msg_store, lam_store)
    _persist(store)
    hdrs = {"X-Amz-Executed-Version": "$LATEST", "x-amzn-RequestId": request_id}
    if str(lh.get("x-amz-log-type") or "").lower() == "tail":
        tail = (logs + f"END RequestId: {request_id}\nREPORT RequestId: {request_id}\t"
                f"Duration: {round(duration_ms, 2)} ms\n")[-4096:]
        hdrs["X-Amz-Log-Result"] = base64.b64encode(tail.encode()).decode()
    if itype == "Event":
        return LambdaResponse(status=202, body=b"", headers=hdrs, media_type=None)
    if out.get("ok"):
        try:
            payload = json.dumps(out.get("result")).encode()
        except Exception:
            payload = json.dumps(str(out.get("result"))).encode()
        return LambdaResponse(status=200, body=payload, headers=hdrs)
    # Function error: 200 with X-Amz-Function-Error, like real Lambda.
    err = {"errorType": out.get("errorType") or "Exception", "errorMessage": str(out.get("error") or "")}
    if out.get("stackTrace"):
        err["stackTrace"] = out["stackTrace"]
    return LambdaResponse(status=200, body=json.dumps(err).encode(),
                          headers={**hdrs, "X-Amz-Function-Error": "Unhandled"})


def invoke_by_arn(store, arn: str, event: dict) -> bool:
    """Public cross-core seam: asynchronously invoke a function by ARN with an
    event payload, for callers that only have an ARN (EventBridge targets).
    Returns False if the function does not exist; the result is discarded,
    same as a real Lambda event-source invocation (fire-and-forget)."""
    name = _norm_name(str(arn).rsplit(":", 1)[-1] if ":function:" not in str(arn) else arn)
    if name not in _functions(store):
        return False
    try:
        _invoke(store, name, json.dumps(event).encode())
    except Exception:
        pass
    return True


def _recent_invocations(store, name):
    fn = _functions(store).get(name)
    if not fn:
        return _err(404, "ResourceNotFoundException", f"Function not found: {_fn_arn(name)}")
    rows = fn.get("invocations", [])
    n = len(rows)
    errors = sum(1 for r in rows if r["Error"])
    avg_ms = round(sum(r["DurationInMS"] for r in rows) / n, 2) if n else 0
    metrics = {
        "Invocations": n, "AvgDurationMs": avg_ms,
        "ErrorCount": errors, "SuccessRatePct": round((n - errors) / n * 100, 1) if n else 100.0,
        "Throttles": fn.get("throttles", 0), "AsyncDeliveryFailures": fn.get("async_delivery_failures", 0),
        "ConcurrentExecutions": 0,
    }
    return _json(200, {"Invocations": rows, "Metrics": metrics})


# ── dispatch ────────────────────────────────────────────────────────────────────────────
def dispatch(store, method: str, path: str,
             query: dict | None = None, headers: dict | None = None,
             body: bytes = b"", msg_store=None, lam_store=None) -> LambdaResponse:
    """Native Lambda REST router. Paths are versioned like real Lambda:
        /2015-03-31/functions[...]                CRUD, code, configuration, invoke(s),
                                                    aliases, versions, policy, tags
        /2015-03-31/functions/{name}/url           Function URL config
        /2015-03-31/functions/{name}/concurrency   Reserved concurrency
        /2015-03-31/functions/{name}/recursion-config
        /2015-03-31/functions/{name}/event-invoke-config
        /2015-03-31/layers[...]                    PublishLayerVersion / List* / Get* / Delete*
        /2015-03-31/event-source-mappings[...]     Triggers (see module docstring)
        /2015-03-31/capacity-providers[...]        Vyomi extension — see module note above
        /2015-03-31/code-signing-configs[...]      _capacity_providers (named-resource CRUD;
        /2015-03-31/network-connectors[...]        the real console's underlying runtime —
        /2015-03-31/microvm-images[...]             EC2, AWS Signer, Firecracker — isn't
        /2015-03-31/microvms[...]                   simulated, only the resource & its fields).
        /2015-03-31/applications[...]
        /2015-03-31/replicas                       Derived from functions' replicated_regions
    """
    method = (method or "GET").upper()
    query = query or {}
    p = path.split("?", 1)[0]
    segs = [s for s in p.split("/") if s != ""]
    if not segs or not segs[0].startswith("20"):
        return _err(404, "ResourceNotFoundException", f"Unknown path: {path}")
    rest = segs[1:]
    if not rest:
        return _err(404, "ResourceNotFoundException", f"Unknown path: {path}")
    kind, tail = rest[0], rest[1:]

    if kind == "layers":
        return _dispatch_layers(store, method, tail, body)
    if kind == "tags" and tail:          # native TagResource / UntagResource / ListTags: /2017-03-31/tags/{ARN}
        from urllib.parse import unquote
        arn = unquote("/".join(tail))
        name = arn.split(":function:", 1)[-1].split(":", 1)[0] if ":function:" in arn else arn
        if method == "GET":
            return _list_tags(store, name)
        if method == "POST":
            return _tag_resource(store, name, _parse(body))
        if method == "DELETE":
            keys = query.get("tagKeys") or []
            keys = keys if isinstance(keys, list) else str(keys).split(",")
            return _untag_resource(store, name, [k for k in keys if k])
    if kind == "account-settings" and not tail and method == "GET":   # GetAccountSettings
        fns = _functions(store)
        total = sum(len(f.get("source", "")) for f in fns.values())
        return _json(200, {
            "AccountLimit": {"TotalCodeSize": 80530636800, "CodeSizeUnzipped": 262144000,
                             "CodeSizeZipped": 52428800, "ConcurrentExecutions": 1000,
                             "UnreservedConcurrentExecutions": 1000 - sum(
                                 int(f.get("reserved_concurrency") or 0) for f in fns.values())},
            "AccountUsage": {"TotalCodeSize": total, "FunctionCount": len(fns)}})
    if kind == "event-source-mappings":
        return _dispatch_esms(store, method, tail, query, body)
    if kind == "functions":
        return _dispatch_functions(store, method, tail, query, body, headers, msg_store, lam_store)
    if kind == "capacity-providers":
        return _dispatch_capacity_providers(store, method, tail, body)
    if kind == "code-signing-configs":
        return _dispatch_cscs(store, method, tail, body)
    if kind == "network-connectors":
        return _dispatch_network_connectors(store, method, tail, body)
    if kind == "microvm-images":
        return _dispatch_microvm_images(store, method, tail, body)
    if kind == "microvms":
        return _dispatch_microvms(store, method, tail, body)
    if kind == "applications":
        return _dispatch_applications(store, method, tail, body)
    if kind == "replicas" and not tail:
        if method == "GET":
            return _list_replicas(store)
        return _err(405, "MethodNotAllowed", "Unsupported method on replicas")
    return _err(404, "ResourceNotFoundException", f"Unknown path: {path}")


def _dispatch_capacity_providers(store, method, tail, body):
    if not tail:
        if method == "POST":
            return _create_capacity_provider(store, _parse(body))
        if method == "GET":
            return _list_capacity_providers(store)
        return _err(405, "MethodNotAllowed", "Unsupported method on capacity-providers")
    if method == "DELETE":
        return _delete_capacity_provider(store, tail[0])
    return _err(404, "ResourceNotFoundException", "Unknown capacity-providers path")


def _dispatch_cscs(store, method, tail, body):
    if not tail:
        if method == "POST":
            return _create_csc(store, _parse(body))
        if method == "GET":
            return _list_cscs(store)
        return _err(405, "MethodNotAllowed", "Unsupported method on code-signing-configs")
    cid = tail[0]
    if method == "PUT":
        return _update_csc(store, cid, _parse(body))
    if method == "DELETE":
        return _delete_csc(store, cid)
    return _err(404, "ResourceNotFoundException", "Unknown code-signing-configs path")


def _dispatch_network_connectors(store, method, tail, body):
    if not tail:
        if method == "POST":
            return _create_network_connector(store, _parse(body))
        if method == "GET":
            return _list_network_connectors(store)
        return _err(405, "MethodNotAllowed", "Unsupported method on network-connectors")
    if method == "DELETE":
        return _delete_network_connector(store, tail[0])
    return _err(404, "ResourceNotFoundException", "Unknown network-connectors path")


def _dispatch_microvm_images(store, method, tail, body):
    if not tail:
        if method == "POST":
            return _create_microvm_image(store, _parse(body))
        if method == "GET":
            return _list_microvm_images(store)
        return _err(405, "MethodNotAllowed", "Unsupported method on microvm-images")
    if method == "DELETE":
        return _delete_microvm_image(store, tail[0])
    return _err(404, "ResourceNotFoundException", "Unknown microvm-images path")


def _dispatch_microvms(store, method, tail, body):
    if not tail:
        if method == "POST":
            return _run_microvm(store, _parse(body))
        if method == "GET":
            return _list_microvms(store)
        return _err(405, "MethodNotAllowed", "Unsupported method on microvms")
    if method == "DELETE":
        return _delete_microvm(store, tail[0])
    return _err(404, "ResourceNotFoundException", "Unknown microvms path")


def _dispatch_applications(store, method, tail, body):
    if not tail:
        if method == "POST":
            return _create_application(store, _parse(body))
        if method == "GET":
            return _list_applications(store)
        return _err(405, "MethodNotAllowed", "Unsupported method on applications")
    if method == "DELETE":
        return _delete_application(store, tail[0])
    return _err(404, "ResourceNotFoundException", "Unknown applications path")


def _dispatch_layers(store, method, tail, body):
    if not tail:
        if method == "GET":
            return _list_layers(store)
        return _err(405, "MethodNotAllowed", "Unsupported method on layers")
    layer_name = tail[0]
    if len(tail) >= 2 and tail[1] == "versions":
        if len(tail) == 2:
            if method == "POST":
                return _publish_layer_version(store, layer_name, _parse(body))
            if method == "GET":
                return _list_layer_versions(store, layer_name)
        if len(tail) == 3:
            version = tail[2]
            if method == "GET":
                return _get_layer_version(store, layer_name, version)
            if method == "DELETE":
                return _delete_layer_version(store, layer_name, version)
    return _err(404, "ResourceNotFoundException", "Unknown layers path")


def _dispatch_esms(store, method, tail, query, body):
    if not tail:
        if method == "POST":
            return _create_event_source_mapping(store, _parse(body))
        if method == "GET":
            return _list_event_source_mappings(store, query.get("FunctionName"))
        return _err(405, "MethodNotAllowed", "Unsupported method on event-source-mappings")
    uid = tail[0]
    if method == "GET":
        return _get_event_source_mapping(store, uid)
    if method == "PUT":
        return _update_event_source_mapping(store, uid, _parse(body))
    if method == "DELETE":
        return _delete_event_source_mapping(store, uid)
    return _err(405, "MethodNotAllowed", "Unsupported method on event-source-mapping")


def _dispatch_functions(store, method, tail, query, body, headers=None, msg_store=None, lam_store=None):
    if not tail:
        if method == "POST":
            return _create_function(store, _parse(body))
        if method == "GET":
            return _list_functions(store)
        return _err(405, "MethodNotAllowed", f"Unsupported {method} on functions")

    name = _norm_name(tail[0])
    if len(tail) == 1:
        if method == "GET":
            return _get_function(store, name, query.get("Qualifier"))
        if method == "DELETE":
            qualifier = query.get("Qualifier")
            if qualifier and qualifier != "$LATEST":
                return _delete_version(store, name, qualifier)
            return _delete_function(store, name)
        return _err(405, "MethodNotAllowed", f"Unsupported {method} on function")

    sub, rest = tail[1], tail[2:]

    if sub == "invocations" and not rest:
        if method == "POST":
            return _invoke(store, name, body, headers, query, msg_store, lam_store)
        if method == "GET":
            return _recent_invocations(store, name)

    if sub == "code" and not rest and method in ("PUT", "POST"):
        return _update_function_code(store, name, _parse(body))

    if sub == "configuration" and not rest:
        if method == "PUT":
            return _update_function_configuration(store, name, _parse(body))
        if method == "GET":
            return _get_function_configuration(store, name)

    if sub == "url" and not rest:
        if method == "POST":
            return _create_function_url_config(store, name, _parse(body))
        if method == "GET":
            return _get_function_url_config(store, name)
        if method == "PUT":
            return _update_function_url_config(store, name, _parse(body))
        if method == "DELETE":
            return _delete_function_url_config(store, name)

    if sub == "tags" and not rest:
        if method == "GET":
            return _list_tags(store, name)
        if method == "POST":
            return _tag_resource(store, name, _parse(body))
        if method == "DELETE":
            keys = query.get("tagKeys") or ""
            return _untag_resource(store, name, [k for k in keys.split(",") if k])

    if sub == "concurrency" and not rest:
        if method == "PUT":
            return _put_function_concurrency(store, name, _parse(body))
        if method == "GET":
            return _get_function_concurrency(store, name)
        if method == "DELETE":
            return _delete_function_concurrency(store, name)

    if sub == "recursion-config" and not rest:
        if method == "PUT":
            return _put_function_recursion_config(store, name, _parse(body))
        if method == "GET":
            return _get_function_recursion_config(store, name)

    if sub == "event-invoke-config" and not rest:
        if method in ("PUT", "POST"):
            return _put_function_event_invoke_config(store, name, _parse(body))
        if method == "GET":
            return _get_function_event_invoke_config(store, name)
        if method == "DELETE":
            return _delete_function_event_invoke_config(store, name)

    if sub == "aliases":
        if not rest:
            if method == "POST":
                return _create_alias(store, name, _parse(body))
            if method == "GET":
                return _list_aliases(store, name)
        elif len(rest) == 1:
            alias_name = rest[0]
            if method == "GET":
                return _get_alias(store, name, alias_name)
            if method == "PUT":
                return _update_alias(store, name, alias_name, _parse(body))
            if method == "DELETE":
                return _delete_alias(store, name, alias_name)

    if sub == "versions" and not rest:
        if method == "POST":
            return _publish_version(store, name, _parse(body))
        if method == "GET":
            return _list_versions_by_function(store, name)

    if sub == "replication" and not rest and method == "PUT":
        return _replicate_function(store, name, _parse(body))

    if sub == "policy":
        if not rest:
            if method == "POST":
                return _add_permission(store, name, _parse(body))
            if method == "GET":
                return _get_policy(store, name)
        elif len(rest) == 1 and method == "DELETE":
            return _remove_permission(store, name, rest[0])

    return _err(404, "ResourceNotFoundException", f"Unknown functions path: /{name}/{sub}")


def _parse(body: bytes) -> dict:
    try:
        return json.loads(body.decode("utf-8")) if body else {}
    except Exception:
        return {}
