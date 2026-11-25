# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""The AWS SDK a Lambda handler sees INSIDE the in-process sandbox (Nano / Pyodide), plus the same boto3 for hosted agents.

Real course handlers do ``import os, json, time, boto3`` and call DynamoDB / SNS / Bedrock through boto3. The sandbox (core/lambda_core.py)
refuses every module outside a short allow-list, so without this module a handler dies on ``import boto3``.

What a handler gets, and nothing more:
  * ``boto3`` -- ``client(name)`` / ``Session().client(name)`` only. Every call is serialised with botocore's own serialisers and handed to the
    ONE registered in-process transport (the Nano wire router). There is no socket, no urllib, no endpoint override: ``endpoint_url`` is ignored.
  * ``botocore.exceptions`` -- the exception classes (``ClientError``) so ``except ClientError`` works.
  * ``os`` -- a proxy with ``environ`` (the function's own environment variables + the AWS_* defaults), ``getenv``, ``getpid`` and a handful of pure
    ``os.path`` string helpers. No filesystem, process or network call exists on it.
  * ``urllib.parse`` -- pure string helpers.
Nothing is available unless the host registered a transport (``set_transport``); on the appliance (a real runtime) this module is inert and a
handler's ``import boto3`` fails exactly as before. Reuses core/tf_export/wire_clients.py (the same boto3-shaped clients the Terraform exporter uses)."""
from __future__ import annotations

import io
import posixpath
import sys
import types

_TRANSPORT = None
_MODELS_DIR = None
_PID = 4242                                   # a stable fake pid: handlers print it, nothing depends on it


def set_transport(transport, models_dir: str | None = None) -> None:
    """Register the in-process transport ``(method, path, query, headers, body) -> (status, headers, body)`` (Nano: the wire router)."""
    global _TRANSPORT, _MODELS_DIR
    _TRANSPORT, _MODELS_DIR = transport, models_dir


def available() -> bool:
    return _TRANSPORT is not None


def _models_dir() -> str:
    if _MODELS_DIR:
        return _MODELS_DIR
    import os
    import botocore
    return os.path.join(os.path.dirname(botocore.__file__), "data")


class _Body(io.BytesIO):
    """botocore's StreamingBody surface for the blobs boto3 streams back (Lambda Payload, S3 Body, ...)."""
    def iter_lines(self, chunk_size=1024, keepends=False):
        yield from self.read().splitlines(keepends)

    def iter_chunks(self, chunk_size=1024):
        while True:
            b = self.read(chunk_size)
            if not b:
                return
            yield b


_EXC_CLASSES = {}


def _exc_class(code):
    """The class `client.exceptions.<Code>` names: a ClientError subclass per error code, as botocore generates, so
    `except ddb.exceptions.ConditionalCheckFailedException` catches exactly what the wire raised for that code."""
    k = _EXC_CLASSES.get(code)
    if k is None:
        from botocore.exceptions import ClientError
        k = _EXC_CLASSES[code] = type(str(code), (ClientError,), {})
    return k


class _ClientExceptions:
    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        if name == "ClientError":
            from botocore.exceptions import ClientError
            return ClientError
        return _exc_class(name)


def _client_error(wire_exc):
    try:
        code = ((wire_exc.response or {}).get("Error") or {}).get("Code") or ""
        return _exc_class(code or "ClientError")(wire_exc.response, wire_exc.args[0].split("when calling the ")[-1].split(" operation")[0] if wire_exc.args else "")
    except Exception:  # noqa: BLE001
        return wire_exc


class _Meta:
    def __init__(self, region):
        self.region_name = region
        self.endpoint_url = "https://" + "amazonaws.com"


class SdkClient:
    """boto3-client lookalike over one WireClient: snake_case operations, streaming blobs, botocore's ClientError."""
    def __init__(self, service: str, region: str):
        from core.tf_export.wire_clients import WireClient
        self._svc = service
        self._wc = WireClient(service, _TRANSPORT, region, _models_dir())
        self.meta = _Meta(region)
        self.exceptions = _ClientExceptions()

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        wc = object.__getattribute__(self, "_wc")
        if name == "get_paginator":
            return wc.get_paginator
        if name not in wc._ops:
            raise AttributeError(f"'{self._svc}' client has no operation '{name}'")
        op = wc._ops[name]

        def call(**kw):
            from core.tf_export.wire_clients import ClientError as _WireErr
            kw = {k: (v.read() if hasattr(v, "read") else v) for k, v in kw.items()}
            try:
                out = getattr(wc, name)(**kw)
            except _WireErr as e:
                raise _client_error(e) from None
            shape = wc._model.operation_model(op).output_shape
            pm = (shape.serialization.get("payload") if shape is not None else None)   # a blob payload member (Lambda Payload, S3 Body) is a stream in boto3
            for m, s in ((shape.members if shape is not None else {}) or {}).items():
                v = out.get(m)
                if (m == pm or s.serialization.get("streaming")) and s.type_name == "blob" and isinstance(v, (bytes, bytearray, str)):
                    out[m] = _Body(v.encode() if isinstance(v, str) else bytes(v))
            return out
        call.__name__ = name
        return call


class _Creds:
    """The fixed dummy credentials every Nano call carries (Vyomi does not verify SigV4); enough for SigV4Auth to sign with."""
    access_key, secret_key, token, method = "test", "test", None, "static"

    def get_frozen_credentials(self):
        return self


class _Session:
    def __init__(self, *a, region_name=None, **k):
        self.region_name = region_name or "us-east-1"

    def get_credentials(self):
        return _Creds()

    def client(self, service_name, region_name=None, **_ignored):
        return SdkClient(service_name, region_name or self.region_name)

    def resource(self, *a, **k):
        raise NotImplementedError("boto3.resource is not available here; use boto3.client(...)")


def _urlopen(req, data=None, timeout=None, **kw):
    """urllib.request.urlopen for hosted agents on Nano: ONLY the simulator's own data planes (gateway MCP, runtimes) reachable through the
    in-process transport; any other URL is refused like a closed network."""
    import re
    import urllib.error
    import urllib.request
    url = req if isinstance(req, str) else req.full_url
    d = data if data is not None else (None if isinstance(req, str) else req.data)
    hdrs = {} if isinstance(req, str) else dict(req.header_items())
    from urllib.parse import urlsplit
    path = urlsplit(url).path
    m = re.search(r"(/gateways/[^/?]+/mcp/?|/runtimes/[^?]+/invocations)$", path)
    if _TRANSPORT is None or not m:
        raise urllib.error.URLError("network access is not available in the Nano sandbox (only the simulator's own gateway and runtime endpoints)")
    status, rh, body = _TRANSPORT((req.get_method() if not isinstance(req, str) else ("POST" if d else "GET")), m.group(1), {}, hdrs, d.encode() if isinstance(d, str) else (d or b""))
    if status >= 400:
        raise urllib.error.HTTPError(url, status, "HTTP %d" % status, rh, io.BytesIO(body))
    r = _Body(body)
    r.status = r.code = status
    r.headers = rh
    return r


def install_urlopen() -> None:
    import urllib.request
    if getattr(urllib.request.urlopen, "_nano", False):
        return
    _urlopen._nano = True
    urllib.request.urlopen = _urlopen


def make_boto3(default_region: str = "us-east-1") -> types.ModuleType:
    """A module-shaped boto3 bound to the registered transport. Raises ImportError when none is registered (appliance / plain Python)."""
    if _TRANSPORT is None:
        raise ImportError("boto3 is not available here (no in-process transport registered)")
    mod = types.ModuleType("boto3")
    mod.__version__ = "1.40.0"
    mod.client = lambda service_name, region_name=None, **_ignored: SdkClient(service_name, region_name or default_region)
    mod.Session = lambda *a, region_name=None, **k: _Session(region_name=region_name or default_region)
    mod.session = types.SimpleNamespace(Session=mod.Session)
    mod.resource = _Session().resource
    return mod


def install_boto3(default_region: str = "us-east-1") -> bool:
    """Put the in-process boto3 on sys.modules for hosted-agent code (AgentCore inproc runtime), unless a real boto3 is already importable."""
    if "boto3" in sys.modules or _TRANSPORT is None:
        return "boto3" in sys.modules
    sys.modules["boto3"] = make_boto3(default_region)
    install_urlopen()
    return True


# ── the sandbox side ────────────────────────────────────────────────────────────────────
def _sandbox_os(env: dict):
    environ = dict(env)
    o = types.SimpleNamespace(
        environ=environ, sep="/", linesep="\n", name="posix",
        getenv=lambda k, d=None: environ.get(k, d),
        getpid=lambda: _PID,
        path=types.SimpleNamespace(join=posixpath.join, basename=posixpath.basename, dirname=posixpath.dirname, splitext=posixpath.splitext,
                                   normpath=posixpath.normpath, sep="/"),
    )
    return o


def _sandbox_botocore():
    try:
        import botocore.exceptions as ex
    except Exception:  # noqa: BLE001
        from core.tf_export import wire_clients as ex
    return types.SimpleNamespace(exceptions=ex)


def _sandbox_urllib():
    import urllib.parse as p
    return types.SimpleNamespace(parse=p)


def sandbox_modules(fn: dict, region: str = "us-east-1") -> dict:
    """Name -> module for the extra imports one invocation may make. Empty when no transport is registered."""
    if _TRANSPORT is None:
        return {}
    name = fn.get("name", "")
    env = {"AWS_REGION": region, "AWS_DEFAULT_REGION": region, "AWS_LAMBDA_FUNCTION_NAME": name, "AWS_LAMBDA_FUNCTION_VERSION": "$LATEST",
           "AWS_LAMBDA_FUNCTION_MEMORY_SIZE": str(fn.get("memory_size", 128)), "AWS_EXECUTION_ENV": "AWS_Lambda_" + str(fn.get("runtime", "python3.12")),
           "_HANDLER": str(fn.get("handler", "index.handler")), "LAMBDA_TASK_ROOT": "/var/task", "TZ": ":UTC"}
    env.update({str(k): str(v) for k, v in (fn.get("env") or {}).items()})
    bc = _sandbox_botocore()
    return {"os": _sandbox_os(env), "boto3": make_boto3(env.get("AWS_REGION", region)), "botocore": bc,
            "botocore.exceptions": bc.exceptions, "urllib": _sandbox_urllib(), "urllib.parse": _sandbox_urllib().parse}
