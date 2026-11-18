"""A small gRPC front door for the Google clients that have no REST transport (offline / Mesh only).

`google-cloud-monitoring` (MetricServiceClient, AlertPolicyServiceClient) and the gapic Cloud Logging client
(LoggingServiceV2Client, what `logging.Client()` uses by default) speak gRPC only, and the simulator's front door is
HTTP/1.1, so they cannot connect. This module is a protocol adapter, not a backend: each RPC is turned into the
equivalent REST call (verb + path + JSON) against the simulator's OWN REST front door and the JSON answer is parsed
back into the response message, so the REST cores stay the single implementation and console/REST/gRPC all see the
same state. No new data store, no new engine.

Start: automatic when VYOMI_GCP_REAL_BACKENDS=1 or VYOMI_GCP_GRPC=1 (or VYOMI_GCP_GRPC_PORT=<port>, default 50051, TLS with a generated cert); server.py calls maybe_start(); the upstream REST base defaults to
http://127.0.0.1:${PORT:-9000} (override with VYOMI_GCP_GRPC_UPSTREAM). Optional TLS: VYOMI_GCP_GRPC_TLS_CERT / _KEY. Needs grpcio (already a dependency of the
Google client libraries); Nano never starts it.

Client side (no emulator env var exists for these two libraries, so the channel is passed explicitly; plaintext h2c):
    ch = grpc.insecure_channel("127.0.0.1:50051")
    MetricServiceClient(transport=MetricServiceGrpcTransport(channel=ch))
    LoggingServiceV2Client(transport=LoggingServiceV2GrpcTransport(channel=ch))
    logging.Client(...)._logging_api  # or hand the gapic client to logging's _gapic wrappers (see the test)

Adding an RPC is one row in _TABLE: (service, method, request type path, response type path, verb, rest path
template, body mode). Path templates use `{name}` for the request's resource-name field.
"""
from __future__ import annotations

import importlib
import json
import logging
import os
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from concurrent import futures

_log = logging.getLogger("vyomi.grpcfront")

M = "google.cloud.monitoring_v3.types.metric_service"
A = "google.cloud.monitoring_v3.types.alert_service"
L = "google.cloud.logging_v2.types.logging"
MON, ALR, LOG = "google.monitoring.v3.MetricService", "google.monitoring.v3.AlertPolicyService", "google.logging.v2.LoggingServiceV2"

# (service, rpc, request module, request type, response module, response type, verb, rest path template, field holding the
#  resource name used in the path, body mode)   body: "*" = whole request, "<field>" = that field only, "" = none (query)
_TABLE = [
    (MON, "ListMonitoredResourceDescriptors", M, "ListMonitoredResourceDescriptorsRequest", M, "ListMonitoredResourceDescriptorsResponse", "GET", "/v3/{name}/monitoredResourceDescriptors", "name", ""),
    (MON, "GetMonitoredResourceDescriptor", M, "GetMonitoredResourceDescriptorRequest", "google.api.monitored_resource_pb2", "MonitoredResourceDescriptor", "GET", "/v3/{name}", "name", ""),
    (MON, "ListMetricDescriptors", M, "ListMetricDescriptorsRequest", M, "ListMetricDescriptorsResponse", "GET", "/v3/{name}/metricDescriptors", "name", ""),
    (MON, "GetMetricDescriptor", M, "GetMetricDescriptorRequest", "google.api.metric_pb2", "MetricDescriptor", "GET", "/v3/{name}", "name", ""),
    (MON, "CreateMetricDescriptor", M, "CreateMetricDescriptorRequest", "google.api.metric_pb2", "MetricDescriptor", "POST", "/v3/{name}/metricDescriptors", "name", "metric_descriptor"),
    (MON, "DeleteMetricDescriptor", M, "DeleteMetricDescriptorRequest", "google.protobuf.empty_pb2", "Empty", "DELETE", "/v3/{name}", "name", ""),
    (MON, "ListTimeSeries", M, "ListTimeSeriesRequest", M, "ListTimeSeriesResponse", "GET", "/v3/{name}/timeSeries", "name", ""),
    (MON, "CreateTimeSeries", M, "CreateTimeSeriesRequest", "google.protobuf.empty_pb2", "Empty", "POST", "/v3/{name}/timeSeries", "name", "*"),
    (ALR, "ListAlertPolicies", A, "ListAlertPoliciesRequest", A, "ListAlertPoliciesResponse", "GET", "/v3/{name}/alertPolicies", "name", ""),
    (ALR, "GetAlertPolicy", A, "GetAlertPolicyRequest", "google.cloud.monitoring_v3.types.alert", "AlertPolicy", "GET", "/v3/{name}", "name", ""),
    (ALR, "CreateAlertPolicy", A, "CreateAlertPolicyRequest", "google.cloud.monitoring_v3.types.alert", "AlertPolicy", "POST", "/v3/{name}/alertPolicies", "name", "alert_policy"),
    (ALR, "DeleteAlertPolicy", A, "DeleteAlertPolicyRequest", "google.protobuf.empty_pb2", "Empty", "DELETE", "/v3/{name}", "name", ""),
    (LOG, "WriteLogEntries", L, "WriteLogEntriesRequest", L, "WriteLogEntriesResponse", "POST", "/v2/entries:write", "", "*"),
    (LOG, "ListLogEntries", L, "ListLogEntriesRequest", L, "ListLogEntriesResponse", "POST", "/v2/entries:list", "", "*"),
    (LOG, "ListLogs", L, "ListLogsRequest", L, "ListLogsResponse", "GET", "/v2/{name}/logs", "parent", ""),
    (LOG, "DeleteLog", L, "DeleteLogRequest", "google.protobuf.empty_pb2", "Empty", "DELETE", "/v2/{name}", "log_name", ""),
    (LOG, "ListMonitoredResourceDescriptors", L, "ListMonitoredResourceDescriptorsRequest", L, "ListMonitoredResourceDescriptorsResponse", "GET", "/v2/monitoredResourceDescriptors", "", ""),
]

_HTTP2GRPC = {400: "INVALID_ARGUMENT", 401: "UNAUTHENTICATED", 403: "PERMISSION_DENIED", 404: "NOT_FOUND", 409: "ALREADY_EXISTS",
              412: "FAILED_PRECONDITION", 429: "RESOURCE_EXHAUSTED", 501: "UNIMPLEMENTED", 503: "UNAVAILABLE", 504: "DEADLINE_EXCEEDED"}


def _type(modname: str, tname: str):
    return getattr(importlib.import_module(modname), tname)


def _is_plus(t) -> bool:
    return hasattr(t, "pb") and hasattr(t, "serialize")


def _to_dict(t, msg) -> dict:
    from google.protobuf import json_format
    pb = t.pb(msg) if _is_plus(t) else msg
    return json_format.MessageToDict(pb, preserving_proto_field_name=False)


def _flatten(d: dict, prefix: str = "") -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for k, v in d.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out += _flatten(v, key + ".")
        elif isinstance(v, list):
            out += [(key, str(x)) for x in v]
        elif isinstance(v, bool):
            out.append((key, "true" if v else "false"))
        else:
            out.append((key, str(v)))
    return out


def _camel(s: str) -> str:
    h, *t = s.split("_")
    return h + "".join(x.title() for x in t)


def _make_handler(upstream: str, row):
    import grpc
    from google.protobuf import json_format
    svc, rpc, rq_mod, rq_name, rs_mod, rs_name, verb, tmpl, name_field, body_mode = row
    rq_t, rs_t = _type(rq_mod, rq_name), _type(rs_mod, rs_name)

    def call(request, context):
        d = _to_dict(rq_t, request)
        name = ""
        if name_field:
            name = str(d.pop(_camel(name_field), "") or "")
        path = tmpl.replace("{name}", name)
        body = b""
        query: list[tuple[str, str]] = []
        if body_mode == "*":
            body = json.dumps(d).encode()
        elif body_mode:
            body = json.dumps(d.get(_camel(body_mode), {})).encode()
        elif verb == "GET":
            query = _flatten(d)
        url = upstream.rstrip("/") + urllib.parse.quote(path, safe="/:") + ("?" + urllib.parse.urlencode(query) if query else "")
        headers = {"Content-Type": "application/json", "Authorization": "Bearer vyomi-local"}
        for k, v in context.invocation_metadata() or ():
            if k.lower() == "authorization":
                headers["Authorization"] = v
        req = urllib.request.Request(url, data=body if verb in ("POST", "PUT", "PATCH") else None, method=verb, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                raw, code = r.read(), r.status
        except urllib.error.HTTPError as e:
            raw, code = e.read(), e.code
        except Exception as exc:  # noqa: BLE001
            context.abort(grpc.StatusCode.UNAVAILABLE, f"simulator REST front door unreachable: {exc}")
        if code >= 300:
            try:
                msg = json.loads(raw).get("error", {}).get("message") or raw.decode()[:300]
            except Exception:  # noqa: BLE001
                msg = raw.decode(errors="replace")[:300]
            context.abort(getattr(grpc.StatusCode, _HTTP2GRPC.get(code, "INTERNAL")), msg)
        resp = rs_t()
        pb = rs_t.pb(resp) if _is_plus(rs_t) else resp
        if raw.strip():
            json_format.Parse(raw, pb, ignore_unknown_fields=True)
        return resp

    return grpc.unary_unary_rpc_method_handler(
        call,
        request_deserializer=(rq_t.deserialize if _is_plus(rq_t) else rq_t.FromString),
        response_serializer=(rs_t.serialize if _is_plus(rs_t) else lambda m: m.SerializeToString()))


def build_server(upstream: str, port: int = 0, host: str = "127.0.0.1", workers: int = 8, tls: tuple[str, str] | None = None):
    """Returns (grpc server, bound port). The caller starts/stops it. `tls` = (cert pem path, key pem path) serves TLS so the
    DEFAULT client constructors work with only `client_options={"api_endpoint": host:port}` and GRPC_DEFAULT_SSL_ROOTS_FILE_PATH=<cert>."""
    import grpc
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=workers))
    by_service: dict[str, dict] = {}
    for row in _TABLE:
        by_service.setdefault(row[0], {})[row[1]] = _make_handler(upstream, row)
    for svc, handlers in by_service.items():
        server.add_generic_rpc_handlers((grpc.method_handlers_generic_handler(svc, handlers),))
    if tls:
        creds = grpc.ssl_server_credentials([(open(tls[1], "rb").read(), open(tls[0], "rb").read())])
        bound = server.add_secure_port(f"{host}:{port}", creds)
    else:
        bound = server.add_insecure_port(f"{host}:{port}")
    return server, bound


_server = None
_info: dict = {}


def _truthy(v) -> bool:
    return str(v or "").strip().lower() in ("1", "true", "yes", "on")


def wanted() -> bool:
    """The front starts by itself when asked (VYOMI_GCP_GRPC=1 or VYOMI_GCP_GRPC_PORT) or when the real-backend mode is on
    (VYOMI_GCP_REAL_BACKENDS=1: the app's Pub/Sub/Firestore are gRPC then, and so are Monitoring/Logging)."""
    return bool(os.environ.get("VYOMI_GCP_GRPC_PORT", "").strip()) or _truthy(os.environ.get("VYOMI_GCP_GRPC")) \
        or _truthy(os.environ.get("VYOMI_GCP_REAL_BACKENDS")) and _truthy(os.environ.get("VYOMI_GCP_GRPC", "1"))


def _self_signed(dirpath: str) -> tuple[str, str] | None:
    """A throwaway self-signed cert for localhost/127.0.0.1 (cryptography is already a dependency of the appliance); None if unavailable."""
    try:
        import datetime
        import ipaddress
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
        now = datetime.datetime.now(datetime.timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(now - datetime.timedelta(minutes=5)).not_valid_after(now + datetime.timedelta(days=365))
                .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
                .sign(key, hashes.SHA256()))
        c, k = os.path.join(dirpath, "grpc-front.crt"), os.path.join(dirpath, "grpc-front.key")
        open(c, "wb").write(cert.public_bytes(serialization.Encoding.PEM))
        open(k, "wb").write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()))
        return c, k
    except Exception:  # noqa: BLE001
        return None


def maybe_start(upstream: str | None = None, port: int | None = None) -> int:
    """Start the front when wanted() (see above); returns the bound port or 0. Contract for clients (also served by discovery()):
      VYOMI_GCP_GRPC_ENDPOINT = host:port to put in client_options={"api_endpoint": ...}
      VYOMI_GCP_GRPC_CA       = PEM file of the serving certificate (empty when plaintext); the client sets
                                GRPC_DEFAULT_SSL_ROOTS_FILE_PATH to it, then the DEFAULT constructors work (MetricServiceClient, logging.Client).
    `upstream` = base URL of the simulator's REST front door (default: http://127.0.0.1:$PORT or :9000); `port` overrides the env
    (0 = any free port, what the in-process harness uses). TLS: VYOMI_GCP_GRPC_TLS_CERT/_KEY, else a generated self-signed cert
    (VYOMI_GCP_GRPC_TLS=0 forces plaintext)."""
    global _server
    if sys.platform == "emscripten" or _server is not None:
        return _info.get("port", 0) if _server is not None else 0
    if not wanted():
        return 0
    try:
        upstream = upstream or os.environ.get("VYOMI_GCP_GRPC_UPSTREAM") or f"http://127.0.0.1:{os.environ.get('PORT', '9000')}"
        want = os.environ.get("VYOMI_GCP_GRPC_PORT", "").strip()
        port = port if port is not None else (int(want) if want else 50051)
        cert, key = os.environ.get("VYOMI_GCP_GRPC_TLS_CERT", ""), os.environ.get("VYOMI_GCP_GRPC_TLS_KEY", "")
        if not (cert and key) and os.environ.get("VYOMI_GCP_GRPC_TLS", "1") != "0":
            import tempfile
            pair = _self_signed(tempfile.mkdtemp(prefix="vyomi-grpc-"))
            cert, key = pair if pair else ("", "")
        host = os.environ.get("VYOMI_GCP_GRPC_HOST", "0.0.0.0")
        try:
            _server, bound = build_server(upstream, port, host=host, tls=(cert, key) if cert and key else None)
        except RuntimeError:   # the default port is taken: any free port, advertised through the endpoint variable
            _server, bound = build_server(upstream, 0, host=host, tls=(cert, key) if cert and key else None)
        _server.start()
        _info.update(port=bound, endpoint=f"localhost:{bound}", ca=cert if cert and key else "", tls=bool(cert and key))
        os.environ["VYOMI_GCP_GRPC_ENDPOINT"], os.environ["VYOMI_GCP_GRPC_CA"] = _info["endpoint"], _info["ca"]
        _log.info("GCP gRPC front door on :%s -> %s (tls=%s)", bound, upstream, _info["tls"])
        return bound
    except Exception as exc:  # noqa: BLE001 - never break appliance boot
        _server = None
        _log.warning("GCP gRPC front door not started: %s", exc)
        return 0


def discovery() -> dict:
    """What `GET /_vyomi/gcp-grpc` returns so a remote app (Mesh) learns the endpoint and CA without reading files."""
    if not _info:
        return {"enabled": False}
    pem = ""
    if _info.get("ca"):
        try:
            pem = open(_info["ca"]).read()
        except OSError:
            pem = ""
    return {"enabled": True, "endpoint": _info["endpoint"], "tls": _info["tls"], "ca_pem": pem, "port": _info["port"]}
