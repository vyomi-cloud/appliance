"""boto3-shaped clients over a pluggable in-process transport, for places boto3 cannot run (Nano / Pyodide).

Uses only botocore's service models + serializers + parsers (pure Python), so request and response shapes are exactly boto3's. The
transport is any callable ``(method, path, query: dict, headers: dict, body: bytes) -> (status, headers, body_bytes)``; in Nano it is
``core.aws_wire_router.AwsWireRouter.handle``, on a laptop it can be an HTTP call. No sockets, no signing (Vyomi does not verify SigV4)."""
from __future__ import annotations

import json
import os
from typing import Any, Callable
from urllib.parse import parse_qsl, urlsplit

AWS_SERVICES = ("ec2", "s3", "logs", "iam", "lambda", "apigateway", "rds", "secretsmanager", "dynamodb", "sqs", "sns", "events", "kms", "stepfunctions", "ecr", "cloudwatch", "backup")  # every service the exporter reads; also the botocore models Nano ships (wasm/build_botocore_lite.py KEEP)

Transport = Callable[[str, str, dict, dict, bytes], "tuple[int, dict, bytes]"]


class _Meta:
    def __init__(self, endpoint_url: str):
        self.endpoint_url = endpoint_url


class ClientError(Exception):
    def __init__(self, response: dict, op: str):
        self.response = response
        super().__init__(f"An error occurred ({response.get('Error', {}).get('Code')}) when calling the {op} operation: {response.get('Error', {}).get('Message')}")


class _Paginator:
    def __init__(self, client: "WireClient", op: str, cfg: dict):
        self._c, self._op, self._cfg = client, op, cfg

    def paginate(self, **kw):
        in_tok, out_tok = self._cfg.get("input_token"), self._cfg.get("output_token")
        in_tok = in_tok if isinstance(in_tok, str) else (in_tok or [None])[0]
        out_tok = out_tok if isinstance(out_tok, str) else (out_tok or [None])[0]
        call = dict(kw)
        while True:
            page = getattr(self._c, self._op)(**call)
            yield page
            nxt = page.get(out_tok) if out_tok else None
            if not nxt or not in_tok:
                return
            call[in_tok] = nxt


class WireClient:
    def __init__(self, service: str, transport: Transport, region: str, models_dir: str, endpoint: str = "http://nano.local"):
        from botocore import serialize, parsers
        from botocore.loaders import Loader
        from botocore.model import ServiceModel
        loader = Loader(extra_search_paths=[models_dir], include_default_search_paths=False)
        self._model = ServiceModel(loader.load_service_model(service, "service-2"), service)
        try:
            self._pag = loader.load_service_model(service, "paginators-1").get("pagination", {})
        except Exception:  # noqa: BLE001
            self._pag = {}
        proto = self._model.metadata["protocol"]
        self._ser, self._par = serialize.create_serializer(proto), parsers.create_parser(proto)
        self._t, self._region = transport, region
        self._sign = self._model.metadata.get("signingName") or self._model.metadata.get("endpointPrefix") or service
        self.meta = _Meta(endpoint)
        from botocore import xform_name
        self._ops = {xform_name(n): n for n in self._model.operation_names}

    def __getattr__(self, name: str):
        if name.startswith("_") or name not in self._ops:
            raise AttributeError(name)
        return lambda **kw: self._call(self._ops[name], kw)

    def get_paginator(self, name: str) -> _Paginator:
        return _Paginator(self, name, self._pag.get(self._ops[name], {}))

    def _call(self, op: str, params: dict) -> dict[str, Any]:
        opm = self._model.operation_model(op)
        if op == "RunInstances" and isinstance(params.get("UserData"), str):  # boto3 base64-encodes this in a handler the serializer does not have
            import base64
            params = {**params, "UserData": base64.b64encode(params["UserData"].encode()).decode()}
        req = self._ser.serialize_to_request(params, opm)
        headers = {str(k): (v.decode() if isinstance(v, bytes) else str(v)) for k, v in req["headers"].items()}
        headers["Authorization"] = f"AWS4-HMAC-SHA256 Credential=test/20240101/{self._region}/{self._sign}/aws4_request, SignedHeaders=host, Signature=0"
        headers.setdefault("Host", f"{self._model.metadata.get('endpointPrefix', self._sign)}.{self._region}.amazonaws.com")
        body = req["body"]
        if isinstance(body, dict):  # Query protocol: form-encoded parameters
            from urllib.parse import urlencode
            body = urlencode(body, doseq=True)
        body = body.encode() if isinstance(body, str) else (body or b"")
        query = req["query_string"] if isinstance(req["query_string"], dict) else dict(parse_qsl(req["query_string"] or ""))
        status, rh, rb = self._t(req["method"], req["url_path"], query, headers, body)
        parsed = self._par.parse({"status_code": status, "headers": {k: v for k, v in rh.items()}, "body": rb}, opm.output_shape)
        if status >= 300:
            raise ClientError(parsed, op)
        parsed.pop("ResponseMetadata", None)
        return parsed


def make_clients(transport: Transport, region: str, models_dir: str | None = None, names=AWS_SERVICES, endpoint: str = "http://nano.local") -> dict[str, WireClient]:
    models_dir = models_dir or os.environ.get("VYOMI_BOTOCORE_DATA", "")
    return {n: WireClient(n, transport, region, models_dir, endpoint) for n in names}


def http_transport(endpoint: str) -> Transport:
    """Plain-urllib transport for a laptop or test (an appliance / Mesh endpoint); never used in Nano."""
    import urllib.request
    from urllib.error import HTTPError

    def send(method, path, query, headers, body):
        from urllib.parse import urlencode
        url = endpoint.rstrip("/") + path + (("?" + urlencode(query)) if query else "")
        rq = urllib.request.Request(url, data=body or None, method=method, headers=headers)
        try:
            with urllib.request.urlopen(rq, timeout=30) as r:
                return r.status, dict(r.headers), r.read()
        except HTTPError as e:
            return e.code, dict(e.headers), e.read()
    return send
