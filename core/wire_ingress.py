"""Unified native-wire ingress for Pro/Max (v2.4.0 Phase 6).

One front door for every cloud's native SDK, on real backends. The SAME
`AwsWireRouter` that serves the Nano relay serves the appliance here — only the
STORES differ: injected backed stores (MinIO / Postgres / Vault / NATS) instead
of the in-WASM defaults. This is how the drift dies: external boto3 / google-cloud-*
/ azure-* SDKs hit identical routing and the identical proven cores on every tier.

`build_backed_router()` constructs the router wired to the real backends (endpoints
from env, host-friendly defaults). `mount(app)` exposes it as a FastAPI catch-all
— defined but NOT auto-activated; the switchover from the legacy per-service
handlers is a deliberate step once this ingress is validated in parallel.

Pro/Max only (imports the boto3/psycopg2/nats/urllib backed stores) — never WASM.

v4 C0 — per-service unified ingress, ON by default. `unified_services()` names the
services whose native wire the offline appliance serves through this router
(VYOMI_UNIFIED_INGRESS_SERVICES, default "s3,dynamodb,gcs"; "none" — or
VYOMI_LEGACY_WIRE=1 — restores the pre-v4 legacy handlers). `appliance_router()` is
the router those services use: the shared cores over core/appliance_stores.py (the
appliance's own space-scoped state, so the classic console REST sees the same
buckets / tables). Every other service stays on its current handler.

v4 C0b adds "azure_blob" (the Blob REST under /azure-data/blob/{account}, reached via the
x-ms-version path rewrite — core/azure_blob_core.py), "gcp_secrets" (/v1/projects/{p}/secrets…
— core/gcp_secretmanager_core.py) and "gcp_kms" (/v1/projects/{p}/locations/{l}/keyRings… —
core/gcp_kms_core.py), each over core/appliance_stores.py; the classic console REST of each
(/api/azure/storage/*, /api/gcp/secrets*, /api/gcp/kms/keys*) reads/writes the same stores.

v4 C0c adds "kms" (AWS KMS, X-Amz-Target TrentService.* — core/kms_core.py) and
"secretsmanager" (AWS Secrets Manager, secretsmanager.* — core/secrets_core.py), served on
POST / (and /_wire/) by routes/aws_s3.aws_query_root over core/appliance_stores.py; the
classic console REST (/api/aws/kms/keys*, /api/aws/secrets*) is re-implemented on the same
stores (routes/aws_secrets_kms_unified.py). Pre-v4 they were Vault-only handlers.

v4 C0d adds "gcp_firestore" (Firestore data + admin plane, /v1/projects/{p}/databases… —
core/gcp_firestore_core.py) and "gcp_compute" (/compute/v1|beta/… routed by path exactly like
AwsWireRouter: VPC networks / subnetworks / firewalls / routes / addresses →
core/gcp_compute_core.py, everything else → core/gcp_compute_instances_core.py), each over
core/appliance_stores.py. The classic console paths (/firestore/v1/…, /api/gcp/firestore/v1/…,
/api/gcp/compute/v1/…, /api/gcp/vpc/*, /api/gcp/dynamodb/*) are aliases onto the same stores
(routes/gcp_firestore_compute_unified.py, which also drives a Compute instance's real
Docker / LXD / Multipass runtime exactly as the pre-v4 handler did).

v4 C0e adds "sqs" (JSON 1.0 `AmazonSQS.*` AND the legacy Query protocol — core/sqs_core.py),
"sns" (Query — core/sns_core.py), "events" (EventBridge `AWSEvents.*` — core/eventbridge_core.py)
and "scheduler" (EventBridge Scheduler REST /schedules, /schedule-groups — core/scheduler_core.py),
all over ONE messaging store (core/appliance_stores.AppStateMessagingStore), exactly as Nano's
AwsWireRouter shares `self.msg`: an EventBridge rule's SQS / SNS / Lambda targets and an SNS
topic's SQS subscriptions really deliver. Native wire on POST / and /_wire/ (routes/aws_s3.
aws_query_root) and on the queue URL itself (`POST /<account>/<queue>`, routes/
aws_messaging_unified.py); the classic console REST (/api/sqs/*, /api/aws/sns/*,
/api/eventbridge/rules*, /api/aws/extras/eventbridge/*) reads/writes the same store.

v4 C0f adds "lambda" (the Lambda REST API /2015-03-31/… — core/lambda_core.py — whose Invoke
runs the code in the appliance's REAL runtime through the store's `run_function` hook),
"azure_keyvault" (Key Vault secrets / keys / certificates data planes, root `/secrets…`,
`/keys…`, `/certificates…` with ?api-version AND `/azure-data/keyvault/{vault}/…` — core/
azure_keyvault_*_core.py), "azure_acr" (the registry data plane /v2/… + /acr/v1/… —
core/azure_acr_core.py) and "azure_servicebus" (the Service Bus REST data plane: entities +
messages at the namespace root — core/azure_servicebus_core.py), each over
core/appliance_stores.py. EventBridge / Scheduler / Step
Functions / API Gateway / SNS / S3-notification Lambda targets reach the SAME functions
(routes/aws_lambda_unified.py). ARM types the shared core ARM engine knows but the offline
catalog does not (Microsoft.ContainerRegistry, Microsoft.ContainerService, …) are served by
core/azure_arm_core.AzureArm over the offline ARM state (providers/azure_services.py).

v4 C0g adds "gcp_pubsub" (the Pub/Sub REST API v1, /v1/projects/{p}/topics|subscriptions|
snapshots|schemas… — core/gcp_pubsub_core.py) over core/appliance_stores.AppStatePubsubStore,
whose records live IN the pre-v4 `gcp_pubsub_state` slot (so inventory, cost savings, console
counts and quantity caps read the core's own records). The classic console REST
(/api/gcp/pubsub/*, /api/gcp/sqs/queues*) and the Cloud Scheduler pubsubTarget publish reach
the same store (routes/gcp_pubsub_unified.py). Pre-v4 the hand-written handlers (or the
Pub/Sub emulator, when PUBSUB_EMULATOR_HOST was set) served it, and snapshots / seek /
schemas:validate / modifyPushConfig fell through to the S3 catch-all.

v4 C0h adds "azure_graph" (Microsoft Graph /v1.0 + /beta — the Entra ID directory,
core/azure_graph_core.py) over core/appliance_stores.AppStateGraphStore (the space's
`azure_graph` slot), mounted by routes/azure_graph_unified.py. Pre-v4 the appliance had no
Graph wire at all: the v4 Entra console's user/group create fell through to the S3 catch-all
(405 MethodNotAllowed). Same for "azure_cosmos": the root Cosmos DB data plane (/dbs/… —
core/azure_cosmos_core.py, the wire Nano and the v4 Cosmos console speak) over
AppStateCosmosStore. The pre-v4 per-account /azure-data/cosmos/{account}/… handler
(core/azure_dataplane.py, in-memory) is unchanged.
"""
from __future__ import annotations

import os

from core.aws_wire_router import AwsWireRouter


def _cfg(key: str, default: str) -> str:
    return os.environ.get(key, default)


_DEFAULT_SERVICES = ("s3,dynamodb,gcs,azure_blob,gcp_secrets,gcp_kms,kms,secretsmanager,"
                     "gcp_firestore,gcp_compute,sqs,sns,events,scheduler,"
                     "lambda,azure_keyvault,azure_acr,azure_servicebus,gcp_pubsub,azure_graph,azure_cosmos,iam,"
                     "azure_table")
_KNOWN_SERVICES = ("s3", "dynamodb", "gcs", "azure_blob", "gcp_secrets", "gcp_kms",
                   "kms", "secretsmanager", "gcp_firestore", "gcp_compute",
                   "sqs", "sns", "events", "scheduler",
                   "lambda", "azure_keyvault", "azure_acr", "azure_servicebus", "gcp_pubsub",
                   "azure_graph", "azure_cosmos", "iam", "azure_table")


def unified_services() -> frozenset:
    """Services whose native wire the appliance serves via the shared cores (C0)."""
    if os.environ.get("VYOMI_LEGACY_WIRE", "").strip().lower() in ("1", "true", "yes"):
        return frozenset()
    raw = os.environ.get("VYOMI_UNIFIED_INGRESS_SERVICES", _DEFAULT_SERVICES).strip().lower()
    if raw in ("", "none", "off", "0", "false", "legacy"):
        return frozenset()
    if raw in ("all", "*"):
        return frozenset(_KNOWN_SERVICES)
    return frozenset(x.strip() for x in raw.split(",") if x.strip() in _KNOWN_SERVICES)


def is_unified(service: str) -> bool:
    return service in unified_services()


_APPLIANCE_ROUTER: AwsWireRouter | None = None


def appliance_stores() -> dict:
    """The C0/C0b/C0c/C0d stores (S3 / GCS / DynamoDB / Azure Blob / GCP Secret Manager /
    Cloud KMS / AWS KMS / AWS Secrets Manager / Firestore / Compute Engine over the
    appliance's own state)."""
    from core import appliance_stores as aps
    return {"s3": aps.s3_store(), "gcs": aps.gcs_store(), "ddb": aps.ddb_store(),
            "az_blob": aps.az_blob_store(), "gcp_sec": aps.gcp_secrets_store(),
            "gcp_kms": aps.gcp_kms_store(), "kms": aps.aws_kms_store(),
            "sec": aps.aws_secrets_store(), "gcp_fs": aps.gcp_firestore_store(),
            "gcp_compute": aps.gcp_compute_vpc_store(), "gcp_compute_vm": aps.gcp_compute_vm_store(),
            "msg": aps.messaging_store(), "sched": aps.scheduler_store(),
            "lam": aps.lambda_store(), "az_kvsec": aps.az_kv_secrets_store(),
            "az_kvkeys": aps.az_kv_keys_store(), "az_kvcerts": aps.az_kv_certs_store(),
            "az_acr": aps.acr_store(), "az_sb": aps.az_servicebus_store(),
            "gcp_msg": aps.gcp_pubsub_store(), "az_graph": aps.graph_store(),
            "az_cosmos": aps.cosmos_store(), "iam": aps.iam_store(), "az_table": aps.table_store(),
            **_gcp_logging_store()}


def _gcp_logging_store() -> dict:
    """The offline Cloud Logging store (routes/gcp_logging.py — the active space's persisted
    slot that entries:list reads), so engine-written entries (Secret Manager audit events, …)
    land where the console's Logs views read them."""
    try:
        from routes.gcp_logging import _STORE
        return {"gcp_logging": _STORE}
    except Exception:
        return {}


# router store key -> unified service name (which stores a full-ingress router overrides)
STORE_SERVICE = {"s3": "s3", "gcs": "gcs", "ddb": "dynamodb", "az_blob": "azure_blob",
                 "gcp_sec": "gcp_secrets", "gcp_kms": "gcp_kms", "kms": "kms",
                 "sec": "secretsmanager", "gcp_fs": "gcp_firestore",
                 "gcp_compute": "gcp_compute", "gcp_compute_vm": "gcp_compute",
                 "msg": "sqs", "sched": "scheduler", "lam": "lambda",
                 "az_kvsec": "azure_keyvault", "az_kvkeys": "azure_keyvault",
                 "az_kvcerts": "azure_keyvault", "az_acr": "azure_acr", "az_sb": "azure_servicebus",
                 "gcp_msg": "gcp_pubsub", "az_graph": "azure_graph", "az_cosmos": "azure_cosmos",
                 "iam": "iam", "az_table": "azure_table",
                 "gcp_logging": "gcp_secrets"}   # Secret Manager writes its audit entries here


def appliance_router() -> AwsWireRouter:
    """The router the default appliance uses for the unified services."""
    global _APPLIANCE_ROUTER
    if _APPLIANCE_ROUTER is None:
        _APPLIANCE_ROUTER = AwsWireRouter(stores=appliance_stores())
    return _APPLIANCE_ROUTER


def to_response(out: dict):
    """Router output {status, headers, body} → a Starlette Response."""
    from fastapi import Response
    hdrs = {k: v for k, v in (out.get("headers") or {}).items()}
    return Response(content=out.get("body") or b"", status_code=out["status"], headers=hdrs)


async def serve(router: AwsWireRouter, request, path: str | None = None, body: bytes | None = None):
    """Dispatch one FastAPI request through the router (path override for aliases)."""
    if body is None:
        body = await request.body()
    out = await router.ahandle(request.method, path or request.url.path,
                               dict(request.query_params), dict(request.headers), body)
    return to_response(out)


def _project_of(path: str) -> str:
    segs = [x for x in path.split("?", 1)[0].split("/") if x]
    if segs and segs[0] in ("v1", "v1beta1"):
        segs = segs[1:]
    return segs[1] if len(segs) > 1 and segs[0] == "projects" else ""


def dispatch_service(service: str, method: str, path: str, query: dict, headers: dict,
                     body: bytes, router: AwsWireRouter | None = None, account: str | None = None) -> dict:
    """Serve one request of a KNOWN service (the route already identified it) with
    that service's core over the router's store. Skips the router's header/path
    sniffing on purpose: an S3 key like `a/restapis/b` or an upload carrying
    `atom+xml` must never be re-classified as another service."""
    import json as _json
    from core import s3_object_core, gcp_storage_core, dynamodb_core
    r = router or appliance_router()
    if service == "s3":
        resp = s3_object_core.dispatch(r.s3, method, path, query, headers, body)
        return {"status": resp.status, "headers": dict(resp.headers or {}), "body": resp.body or b""}
    if service == "gcs":
        resp = gcp_storage_core.dispatch(r.gcs, method, path, query, headers, body)
        hdrs = dict(resp.headers or {})
        if resp.media_type and not any(k.lower() == "content-type" for k in hdrs):
            hdrs["content-type"] = resp.media_type
        return {"status": resp.status, "headers": hdrs, "body": resp.body or b""}
    if service == "dynamodb":
        target = next((v for k, v in headers.items() if k.lower() == "x-amz-target"), "") or ""
        try:
            payload = _json.loads(body or b"{}")
        except Exception:
            return {"status": 400, "headers": {"content-type": "application/x-amz-json-1.0"},
                    "body": _json.dumps({"__type": "com.amazon.coral.service#SerializationException",
                                         "message": "Request body is not valid JSON."}).encode()}
        resp = dynamodb_core.dispatch(r.ddb, target, payload if isinstance(payload, dict) else {})
        import uuid as _uuid
        hdrs = {"x-amzn-requestid": _uuid.uuid4().hex.upper(), **dict(resp.headers or {})}
        hdrs.setdefault("content-type", "application/x-amz-json-1.0")
        return {"status": resp.status, "headers": hdrs, "body": resp.json_bytes()}
    if service == "azure_blob":
        from core import azure_blob_core
        st = r.az_blob
        if account is not None and hasattr(st, "adopt"):
            st.adopt(account)            # pre-v4 Azurite blobs → this state (once)
        resp = azure_blob_core.dispatch(st, method, path, query, headers, body, account=account)
        hdrs = dict(resp.headers or {})
        if resp.media_type and not any(k.lower() == "content-type" for k in hdrs):
            hdrs["content-type"] = resp.media_type
        return {"status": resp.status, "headers": hdrs, "body": resp.body or b""}
    if service in ("gcp_secrets", "gcp_kms"):
        from core import gcp_kms_core, gcp_secretmanager_core
        mod, st = ((gcp_secretmanager_core, r.gcp_sec) if service == "gcp_secrets"
                   else (gcp_kms_core, r.gcp_kms))
        project = _project_of(path)
        if project and hasattr(st, "adopt"):
            st.adopt(project)            # pre-v4 Vault secrets / key index → this state (once)
        if service == "gcp_secrets":   # version lifecycle -> real Pub/Sub publish + Cloud Logging entry
            resp = mod.dispatch(st, method, path, query, headers, body,
                                notifier=r._secrets_notify, logger=r._secrets_log)
        else:
            resp = mod.dispatch(st, method, path, query, headers, body)
        hdrs = dict(resp.headers or {})
        hdrs.setdefault("content-type", resp.media_type or "application/json")
        return {"status": resp.status, "headers": hdrs, "body": resp.body or b""}
    if service in ("kms", "secretsmanager"):
        import uuid as _uuid
        from core import kms_core, secrets_core
        mod, st = (kms_core, r.kms) if service == "kms" else (secrets_core, r.sec)
        target = next((v for k, v in headers.items() if k.lower() == "x-amz-target"), "") or ""
        try:
            payload = _json.loads(body or b"{}")
        except Exception:
            return {"status": 400, "headers": {"content-type": "application/x-amz-json-1.1"},
                    "body": _json.dumps({"__type": "SerializationException",
                                         "message": "Request body is not valid JSON."}).encode()}
        if hasattr(st, "adopt"):
            st.adopt()                   # pre-v4 Vault keys / secrets → this state (once per space)
        if service == "secretsmanager":   # a customer KmsKeyId is really encrypted/decrypted through the KMS core
            resp = mod.dispatch(st, target, payload if isinstance(payload, dict) else {}, kms_store=r.kms)
        else:
            resp = mod.dispatch(st, target, payload if isinstance(payload, dict) else {})
        hdrs = {"x-amzn-requestid": str(_uuid.uuid4()), **dict(resp.headers or {})}
        hdrs.setdefault("content-type", "application/x-amz-json-1.1")
        return {"status": resp.status, "headers": hdrs, "body": _json.dumps(resp.body).encode()}
    if service == "gcp_firestore":
        from core import gcp_firestore_core
        st = r.gcp_fs
        project = _project_of(path)
        if project and hasattr(st, "adopt"):
            st.adopt(project)            # pre-v4 databases / indexes / documents → this state (once)
        resp = gcp_firestore_core.dispatch(st, method, path, query, headers, body, gcs_store=r.gcs)
        hdrs = dict(resp.headers or {})
        hdrs.setdefault("content-type", resp.media_type or "application/json")
        return {"status": resp.status, "headers": hdrs, "body": resp.body or b""}
    if service == "gcp_compute":
        from core import gcp_compute_core, gcp_compute_instances_core
        from core.aws_wire_router import _gcp_service
        project = compute_project_of(path)
        for st in (r.gcp_compute, r.gcp_compute_vm):
            if project and hasattr(st, "adopt"):
                st.adopt(project)        # pre-v4 VPC / Compute Engine records → this state (once)
        if _gcp_service(path) == "gcp-compute":
            resp = gcp_compute_core.dispatch(r.gcp_compute, method, path, query, headers, body, vm_store=r.gcp_compute_vm)
        else:
            resp = gcp_compute_instances_core.dispatch(r.gcp_compute_vm, method, path, query, headers, body)
        hdrs = dict(resp.headers or {})
        hdrs.setdefault("content-type", resp.media_type or "application/json")
        return {"status": resp.status, "headers": hdrs, "body": resp.body or b""}
    if service in ("sqs", "sns", "events", "scheduler"):
        return _dispatch_messaging(service, r, method, path, query, headers, body)
    if service == "lambda":
        from core import lambda_core
        st = r.lam
        if hasattr(st, "adopt"):
            st.adopt()                   # pre-v4 functions / layers → the core shape (once per space)
        resp = lambda_core.dispatch(st, method, path, query or {}, headers or {}, body or b"",
                                    msg_store=r.msg, lam_store=r.lam)
        hdrs = dict(resp.headers or {})
        if resp.media_type and resp.body and not any(k.lower() == "content-type" for k in hdrs):
            hdrs["content-type"] = resp.media_type
        hdrs.setdefault("x-amzn-requestid", str(__import__("uuid").uuid4()))
        return {"status": resp.status, "headers": hdrs, "body": resp.body or b""}
    if service in ("azure_keyvault", "azure_acr", "azure_servicebus"):
        return _dispatch_azure(service, r, method, path, query, headers, body)
    if service == "gcp_pubsub":
        from core import gcp_pubsub_core
        st = r.gcp_msg
        if hasattr(st, "adopt"):
            st.adopt()                   # pre-v4 records / emulator resources → the core shape
        resp = gcp_pubsub_core.dispatch(st, method, path, query or {}, headers or {}, body or b"")
        hdrs = dict(resp.headers or {})
        hdrs.setdefault("content-type", resp.media_type or "application/json")
        return {"status": resp.status, "headers": hdrs, "body": resp.body or b""}
    if service in ("azure_graph", "azure_cosmos", "azure_table"):
        from core import azure_graph_core, azure_cosmos_core, azure_table_core
        from core import app_context as _ctx
        core, st = {"azure_graph": (azure_graph_core, r.az_graph),
                    "azure_cosmos": (azure_cosmos_core, r.az_cosmos),
                    "azure_table": (azure_table_core, r.az_table)}[service]
        tok = _ctx.REQUEST_PROVIDER.set("azure")   # the state lives in the Azure space
        try:
            resp = core.dispatch(st, method, path, query or {}, headers or {}, body or b"")
        finally:
            _ctx.REQUEST_PROVIDER.reset(tok)
        hdrs = dict(resp.headers or {})
        hdrs.setdefault("content-type", resp.media_type or "application/json")
        return {"status": resp.status, "headers": hdrs, "body": resp.body or b""}
    if service == "iam":
        from core import iam_core
        if hasattr(r.iam, "adopt"):
            r.iam.adopt()                 # pre-v4 users/groups/roles/policies (once per space)
        params = r._query_params(query, body)
        resp = iam_core.dispatch(r.iam, params)
        hdrs = dict(resp.headers or {})
        hdrs.setdefault("content-type", "text/xml")
        return {"status": resp.status, "headers": hdrs, "body": resp.body.encode()}
    raise ValueError(f"not a unified service: {service}")


_KV_HOST = "https://vault.vault.azure.net"


def kv_core_path(path: str) -> str:
    """`/azure-data/keyvault/{vault}/secrets/x` → `/secrets/x` (the core's path); root paths as-is."""
    segs = [x for x in (path or "").split("?", 1)[0].split("/") if x]
    if len(segs) >= 3 and segs[0] == "azure-data" and segs[1] == "keyvault":
        return "/" + "/".join(segs[3:])
    return path.split("?", 1)[0]


def _dispatch_azure(service: str, r: AwsWireRouter, method: str, path: str, query: dict,
                    headers: dict, body: bytes) -> dict:
    """Key Vault / ACR data planes. The state is Azure's: the request is bound to the Azure
    space for the duration (the provider middleware classifies these root paths as AWS)."""
    from core import app_context as _ctx
    tok = _ctx.REQUEST_PROVIDER.set("azure")
    try:
        if service in ("azure_acr", "azure_servicebus"):
            from core import azure_acr_core, azure_servicebus_core
            mod, st = (azure_acr_core, r.az_acr) if service == "azure_acr" else (azure_servicebus_core, r.az_sb)
            resp = mod.dispatch(st, method, path, query or {}, headers or {}, body or b"")
            hdrs = dict(resp.headers or {})
            if resp.media_type and not any(k.lower() == "content-type" for k in hdrs):
                hdrs["content-type"] = resp.media_type
            return {"status": resp.status, "headers": hdrs, "body": resp.body or b""}
        from core import (azure_keyvault_certificates_core as kvc, azure_keyvault_keys_core as kvk,
                          azure_keyvault_secrets_core as kvs)
        if hasattr(r.az_kvkeys, "adopt"):
            r.az_kvkeys.adopt()          # pre-v4 Vault-backed secrets / RSA keys (once per space)
        p = kv_core_path(path)
        kind = p.lstrip("/").split("/", 1)[0]
        mod, st = {"secrets": (kvs, r.az_kvsec), "keys": (kvk, r.az_kvkeys),
                   "certificates": (kvc, r.az_kvcerts)}.get(kind, (None, None))
        if mod is None:
            return {"status": 404, "headers": {"content-type": "application/json"},
                    "body": b'{"error":{"code":"NotFound","message":"Unknown Key Vault path."}}'}
        resp = mod.dispatch(st, method, p, query or {}, headers or {}, body or b"")
        hdrs = dict(resp.headers or {})
        if resp.media_type and not any(k.lower() == "content-type" for k in hdrs):
            hdrs["content-type"] = resp.media_type
        out = resp.body or b""
        # Identifiers (secret id / kid / cert id) name the vault the CLIENT talks to, as real
        # Key Vault does — the native SDKs (CryptographyClient, …) send follow-ups to that host.
        lh = {str(k).lower(): v for k, v in (headers or {}).items()}
        host = lh.get("x-forwarded-host") or lh.get("host") or ""
        if host and out and _KV_HOST.encode() in out:
            out = out.replace(_KV_HOST.encode(), f"https://{host}".encode())
        return {"status": resp.status, "headers": hdrs, "body": out}
    finally:
        _ctx.REQUEST_PROVIDER.reset(tok)


def _lam_store(r: AwsWireRouter):
    """The Lambda function store EventBridge / Scheduler targets reach: the net-new
    lambda_core router's (offline `/2015-03-31/functions/*` sub-resources); the appliance's
    own function registry is reached through the messaging store's `deliver_lambda` hook."""
    nr = new_services_router()
    return nr.lam if nr is not None else r.lam


def _dispatch_messaging(service: str, r: AwsWireRouter, method: str, path: str, query: dict,
                        headers: dict, body: bytes) -> dict:
    import json as _json
    import uuid as _uuid
    from urllib.parse import parse_qsl
    from core import appliance_stores as aps
    st = r.msg
    aps.set_request_base(headers)
    if hasattr(st, "adopt"):
        st.adopt()                       # pre-v4 queues / rules / targets → this state (once per space)
    lh = {str(k).lower(): v for k, v in (headers or {}).items()}
    target = lh.get("x-amz-target", "") or ""
    rid = str(_uuid.uuid4())
    if service == "scheduler":
        from core import scheduler_core
        fired = {k: s.get("last_run") for k, s in r.sched.schedules.items()}
        resp = scheduler_core.dispatch(r.sched, method, path, query or {}, headers or {}, body or b"",
                                       msg_store=st, lam_store=_lam_store(r))
        if method.upper() == "GET" and fired != {k: s.get("last_run") for k, s in r.sched.schedules.items()}:
            try:   # a due schedule fired during a read: the middleware only flushes writes
                from core import app_context as _ctx
                _ctx.persist_state()
            except Exception:
                pass
        hdrs = {"x-amzn-requestid": rid, **dict(resp.headers or {})}
        if resp.media_type and not any(k.lower() == "content-type" for k in hdrs):
            hdrs["content-type"] = resp.media_type
        return {"status": resp.status, "headers": hdrs, "body": resp.body or b""}
    if target:                           # JSON protocol (SQS JSON 1.0, EventBridge JSON 1.1)
        try:
            payload = _json.loads(body or b"{}")
        except Exception:
            payload = None
        ct = "application/x-amz-json-1.0" if service == "sqs" else "application/x-amz-json-1.1"
        if not isinstance(payload, dict):
            return {"status": 400, "headers": {"content-type": ct, "x-amzn-requestid": rid},
                    "body": _json.dumps({"__type": "SerializationException",
                                         "message": "Request body is not valid JSON."}).encode()}
        if service == "sqs":
            from core import sqs_core
            resp = sqs_core.dispatch(st, target, payload)
        elif service == "events":
            from core import eventbridge_core
            resp = eventbridge_core.dispatch(st, target, payload, lam_store=_lam_store(r))
        else:
            return {"status": 400, "headers": {"content-type": ct, "x-amzn-requestid": rid},
                    "body": _json.dumps({"__type": "UnknownOperationException",
                                         "message": f"{target} is not an operation of {service}."}).encode()}
        hdrs = {"x-amzn-requestid": rid, **dict(resp.headers or {})}
        if resp.status >= 400 and "x-amzn-query-error" not in {k.lower() for k in hdrs} and service == "sqs":
            code = str(resp.body.get("__type", "")).split("#")[-1]
            from core.sqs_core import _QUERY_ERROR_CODE
            hdrs["x-amzn-query-error"] = f"{_QUERY_ERROR_CODE.get(code, code)};Sender"
        hdrs.setdefault("content-type", ct)
        return {"status": resp.status, "headers": hdrs, "body": _json.dumps(resp.body).encode()}
    # Query protocol (form body and/or query string): SQS legacy, SNS
    params = dict(query or {})
    if body:
        try:
            params.update(dict(parse_qsl(body.decode("utf-8") if isinstance(body, (bytes, bytearray)) else str(body),
                                         keep_blank_values=True)))
        except Exception:
            pass
    if service == "sqs":
        from core import sqs_core
        if "QueueUrl" not in params:     # POSTed to the queue URL itself (Java v1 / .NET style)
            segs = [x for x in (path or "").split("?", 1)[0].split("/") if x]
            if len(segs) == 2:
                params["QueueUrl"] = segs[1]
        status, xml = sqs_core.dispatch_query(st, params)
        return {"status": status, "headers": {"content-type": "text/xml", "x-amzn-requestid": rid},
                "body": xml.encode()}
    if service == "sns":
        from core import sns_core
        resp = sns_core.dispatch(st, params)
        hdrs = {"x-amzn-requestid": rid, **dict(resp.headers or {})}
        hdrs.setdefault("content-type", getattr(resp, "media_type", None) or "text/xml")
        b = resp.body if isinstance(resp.body, (bytes, bytearray)) else str(resp.body).encode()
        return {"status": resp.status, "headers": hdrs, "body": b}
    return {"status": 400, "headers": {"content-type": "application/x-amz-json-1.1"},
            "body": _json.dumps({"__type": "MissingAction", "message": "X-Amz-Target is required."}).encode()}


_NEW_SERVICES_ROUTER: AwsWireRouter | None = None


def new_services_router() -> AwsWireRouter | None:
    """The router mount_new_services() serves the net-new paths with (None until mounted)."""
    return _NEW_SERVICES_ROUTER


def compute_project_of(path: str) -> str:
    """`/compute/v1/projects/{p}/…` → p."""
    segs = [x for x in path.split("?", 1)[0].split("/") if x]
    i = segs.index("projects") if "projects" in segs else -1
    return segs[i + 1] if 0 <= i < len(segs) - 1 else ""


async def serve_service(service: str, request, path: str | None = None, body: bytes | None = None,
                        query: dict | None = None, account: str | None = None):
    if body is None:
        body = await request.body()
    out = dispatch_service(service, request.method, path or request.url.path,
                           dict(request.query_params) if query is None else query,
                           dict(request.headers), body, account=account)
    return to_response(out)


def mount_gcp_secrets_kms(app) -> None:
    """Register the native Secret Manager / Cloud KMS REST paths on the shared cores
    (C0b). Call BEFORE any other /v1/projects/* route (core/vault_routes.register
    does, at the very start of route registration)."""
    methods = ["GET", "POST", "PATCH", "DELETE"]

    def _raw(request) -> str:
        raw = request.scope.get("raw_path")
        p = raw.decode("utf-8", "replace") if isinstance(raw, (bytes, bytearray)) and raw else \
            (request.scope.get("path") or request.url.path)
        from urllib.parse import unquote
        return unquote(p.split("?", 1)[0])    # ":access" may arrive as %3Aaccess

    async def _secrets(request):
        return await serve_service("gcp_secrets", request, path=_raw(request))

    async def _kms(request):
        return await serve_service("gcp_kms", request, path=_raw(request))

    if is_unified("gcp_secrets"):
        for v in ("/v1", "/v1beta1"):
            app.add_route(v + "/projects/{project}/secrets", _secrets, methods=methods)
            app.add_route(v + "/projects/{project}/secrets/{rest:path}", _secrets, methods=methods)
    if is_unified("gcp_kms"):
        app.add_route("/v1/projects/{project}/locations/{loc}/keyRings", _kms, methods=methods)
        app.add_route("/v1/projects/{project}/locations/{loc}/keyRings/{rest:path}", _kms, methods=methods)


_GCS_PREFIXES = ("/storage/v1/b", "/upload/storage/v1/b", "/download/storage/v1/b", "/api/gcp/storage/v1/b")


def gcs_core_path(path: str) -> bool:
    """A GCS route the core serves (vs. the legacy-only folders / console upload helper)."""
    return path.startswith(_GCS_PREFIXES) and "/folders" not in path and not path.endswith("/upload")


def mount_gcs(app) -> None:
    """Register the GCS JSON API on the shared core (C0). Call AFTER the provider
    routes (so legacy folders/transfer routes registered earlier still win) and
    BEFORE the S3 catch-all."""
    import json as _json

    async def _gcs(request):
        # The GCS core splits on "/" and unquotes each segment itself, so it needs the
        # RAW (still-encoded) path: an object named "reports/" arrives as
        # `/o/reports%2F` and must not collapse into "reports".
        raw = request.scope.get("raw_path")
        path = raw.decode("utf-8", "replace") if isinstance(raw, (bytes, bytearray)) and raw else \
            (request.scope.get("path") or request.url.path)
        body = await request.body()
        if path.startswith("/api/gcp/"):
            # classic console alias → the native path; accept its legacy body keys
            path = path[len("/api/gcp"):]
            if request.method == "POST" and path.rstrip("/") == "/storage/v1/b" and body:
                try:
                    d = _json.loads(body)
                    if isinstance(d, dict) and not d.get("name") and d.get("bucket"):
                        d["name"] = d["bucket"]
                        body = _json.dumps(d).encode()
                except Exception:
                    pass
        return await serve_service("gcs", request, path=path, body=body)

    methods = ["GET", "POST", "PUT", "PATCH", "DELETE"]
    for prefix in _GCS_PREFIXES:
        app.add_route(prefix, _gcs, methods=methods)
        app.add_route(prefix + "/{rest:path}", _gcs, methods=methods)


def build_backed_router(overrides: dict | None = None) -> AwsWireRouter:
    """An AwsWireRouter wired to the appliance's real backends behind the seams.
    `overrides` replaces individual stores (server.py passes the C0 appliance
    stores for s3/gcs/ddb so the full ingress shares the console's state)."""
    from core.minio_backed_store import build_object_store
    from core.postgres_backed_store import PostgresBackedSqlStore
    from core.vault_backed_store import VaultBackedKeyStore, VaultBackedKvStore
    from core.persistent_store import (SqliteStateBackend, PersistentAzureBlobStore,
                                        PersistentNoSqlStore, PersistentFirestoreStore,
                                        PersistentCosmosStore, PersistentAzureQueueStore,
                                        PersistentMessagingStore, PersistentCloudWatchStore)
    from core.nats_backed_store import NatsBackedMessagingStore

    minio = dict(
        endpoint=_cfg("VYOMI_MINIO_ENDPOINT", _cfg("CLOUDLEARN_MINIO_URL", "http://localhost:9100")),
        access_key=_cfg("VYOMI_MINIO_ACCESS_KEY", "cloudlearn"),
        secret_key=_cfg("VYOMI_MINIO_SECRET_KEY", "cloudlearn-dev-secret-key"))
    pg_dsn = _cfg("VYOMI_PG_DSN",
                  "host=localhost port=35432 user=postgres password=cloudlearn dbname=postgres")
    vault = dict(addr=_cfg("VYOMI_VAULT_ADDR", "http://localhost:8200"),
                 token=_cfg("VYOMI_VAULT_TOKEN", "vyomi-dev-token"))
    nats_servers = _cfg("VYOMI_NATS", "nats://localhost:4222")

    overrides = overrides or {}
    stores = {
        # object storage — AWS S3 + GCP GCS on MinIO (namespaced prefixes); bucket
        # metadata in a SQLite sidecar next to the appliance state (C0). Without
        # MinIO: SQLite-only persistent stores (logged once).
        "s3": overrides.get("s3") or build_object_store("aws-s3-", **minio),
        "gcs": overrides.get("gcs") or build_object_store("gcp-gcs-", **minio),
        # relational — RDS + Cloud SQL on real Postgres (schema-namespaced)
        "rds": PostgresBackedSqlStore(pg_dsn, schema_prefix="rds_"),
        "gcp_sql": PostgresBackedSqlStore(pg_dsn, schema_prefix="gcpsql_"),
        # security / crypto — KMS + Cloud KMS + Azure KV keys on Vault Transit
        "kms": VaultBackedKeyStore(**vault),
        "gcp_kms": overrides.get("gcp_kms") or VaultBackedKeyStore(**vault),
        "az_kvkeys": VaultBackedKeyStore(**vault),
        # secrets (v2.5.0) — Vault KV v2, namespaced per cloud
        "sec": VaultBackedKvStore(prefix="aws-sec/", **vault),
        "gcp_sec": overrides.get("gcp_sec") or VaultBackedKvStore(prefix="gcp-sec/", **vault),
        "az_kvsec": VaultBackedKvStore(prefix="az-sec/", **vault),
        # Azure Blob (v2.5.0) — durable via the file-backed substrate (was in-memory)
        "az_blob": overrides.get("az_blob") or PersistentAzureBlobStore(
            SqliteStateBackend(_cfg("VYOMI_AZBLOB_DB", "/tmp/vyomi-azblob.sqlite"))),
        # DynamoDB (v2.5.0) — durable NoSQL via the file-backed substrate (was in-memory)
        "ddb": overrides.get("ddb") or PersistentNoSqlStore(
            SqliteStateBackend(_cfg("VYOMI_DDB_DB", "/tmp/vyomi-ddb.sqlite"))),
        # Firestore (v2.5.0) — durable documents via the file-backed substrate
        "gcp_fs": overrides.get("gcp_fs") or PersistentFirestoreStore(
            SqliteStateBackend(_cfg("VYOMI_FS_DB", "/tmp/vyomi-fs.sqlite"))),
        # Cosmos (v2.5.0) — durable via the file-backed substrate
        "az_cosmos": PersistentCosmosStore(
            SqliteStateBackend(_cfg("VYOMI_COSMOS_DB", "/tmp/vyomi-cosmos.sqlite"))),
        # Azure Queue (v2.5.0) — durable via the file-backed substrate (Message-aware)
        "az_queue": PersistentAzureQueueStore(
            SqliteStateBackend(_cfg("VYOMI_AZQUEUE_DB", "/tmp/vyomi-azqueue.sqlite"))),
        # Azure Service Bus topics (v2.5.0) — durable via the file-backed substrate
        # (topics+subscriptions, bytes-aware codec handles message bodies)
        "az_sb": PersistentMessagingStore(
            SqliteStateBackend(_cfg("VYOMI_AZSB_DB", "/tmp/vyomi-azsb.sqlite")), store_id="azsb"),
        # CloudWatch — durable metrics / alarms / dashboards via the file-backed substrate
        "cw": PersistentCloudWatchStore(
            SqliteStateBackend(_cfg("VYOMI_CW_DB", "/tmp/vyomi-cw.sqlite"))),
        # messaging — SQS/SNS + Pub/Sub on NATS JetStream (separate KV buckets)
        "msg": overrides.get("msg") or NatsBackedMessagingStore(servers=nats_servers, bucket="aws_msg"),
        "gcp_msg": overrides.get("gcp_msg") or NatsBackedMessagingStore(servers=nats_servers, bucket="gcp_msg"),
    }
    if overrides.get("sched") is not None:   # C0e: EventBridge Scheduler on the appliance state
        stores["sched"] = overrides["sched"]
    for _k in ("gcp_compute", "gcp_compute_vm",   # C0d: Compute Engine on the appliance state
               "lam", "az_acr"):                  # C0f: Lambda + ACR on the appliance state
        if overrides.get(_k) is not None:
            stores[_k] = overrides[_k]
    for _k in ("az_kvsec", "az_kvkeys", "az_kvcerts", "az_sb"):   # C0f: Key Vault / Service Bus on the appliance state
        if overrides.get(_k) is not None:
            stores[_k] = overrides[_k]
    from core import appliance_stores as _aps
    _aps.install_core_slot_stores()   # the cores' shared_store()s → durable space slots
    for _k in ("gcp_iam", "gcp_rm"):   # GCP custom roles / Workload Identity / Org Policy v2
        stores[_k] = _aps.net_new_core_stores()[_k]
    from core.apigatewayv2_core import shared_store
    stores["apigwv2"] = shared_store()   # shared with the console REST (/api/apigatewayv2)
    from core.stepfunctions_core import shared_store as _sfn_store
    stores["sfn"] = _sfn_store()   # shared with the console REST (/api/stepfunctions)
    from core.gcp_cloudscheduler_core import shared_store as _gcp_sched_store
    stores["gcp_sched"] = _gcp_sched_store()   # shared with the console REST (/api/gcp/cloudscheduler)
    from core.gcp_container_core import shared_store as _gcp_gke_store
    stores["gcp_gke"] = _gcp_gke_store()   # shared with the console REST (/api/gcp/container)
    from core.gcp_iamcredentials_core import shared_store as _gcp_iamc_store
    stores["gcp_iamc"] = _gcp_iamc_store()   # shared with the console REST (/api/gcp/iamcredentials)
    from core.gcp_redis_core import shared_store as _gcp_redis_store
    stores["gcp_redis"] = _gcp_redis_store()   # shared with the console REST (/api/gcp/redis)
    from core.gcp_monitoring_core import shared_store as _gcp_mon_store
    stores["gcp_mon"] = _gcp_mon_store()   # shared with the console REST (/api/gcp/monitoring)
    return AwsWireRouter(stores=stores)


def mount(app, router: AwsWireRouter | None = None) -> None:
    """Mount the unified ingress as a FastAPI catch-all delegating to the router.
    NOT auto-called — server.py opts in when retiring the legacy handlers."""
    from fastapi import Request, Response

    r = router or build_backed_router()

    async def _ingress(request: Request):
        body = await request.body()
        out = await r.ahandle(request.method, request.url.path,
                              dict(request.query_params), dict(request.headers), body)
        return Response(content=out["body"], status_code=out["status"],
                        headers={k: v for k, v in (out["headers"] or {}).items()})

    # Starlette raw route (NOT add_api_route — that wraps the handler in FastAPI's
    # request-validation machinery and 422s a raw native-wire request). Registered
    # LAST so it only catches paths no explicit route already claimed.
    app.add_route("/{full_path:path}", _ingress,
                  methods=["GET", "POST", "PUT", "DELETE", "HEAD", "PATCH"])


def mount_new_services(app, router: AwsWireRouter | None = None) -> None:
    """Expose the v2.6.0–2.8.0 NET-NEW services on the DEFAULT appliance path —
    additively and SAFELY. Unlike `mount()` (a greedy catch-all, opt-in behind the
    unified-ingress flag), this registers ONLY the specific path prefixes of the
    net-new services, which have NO legacy handler to conflict with:

        /2015-03-31/functions...        Lambda (serverless invoke)
        /restapis...                    API Gateway
        /v2/apis, /v2/domainnames, /v2/vpclinks, /v2/tags   API Gateway V2
        /azure-sql/...                  Azure SQL data plane
        /providers/Microsoft.Authorization/...   Azure RBAC checkAccess

    So the appliance serves these regardless of VYOMI_UNIFIED_INGRESS, without
    touching the existing S3/DynamoDB/… handlers. No backend deps (no MinIO/Vault/NATS
    required at mount time): every store is a durable space slot of the appliance state
    (core/appliance_stores._CoreSlotStore), never the router's in-memory default. Header/Action-routed net-new services (EventBridge,
    VPC, Service Bus — dispatched on `/` by X-Amz-Target/Action) can't be isolated
    from the existing `/` handlers additively, so they remain served via the full
    unified ingress (mount())."""
    from fastapi import Request, Response

    from core import appliance_stores as _aps
    _aps.install_core_slot_stores()   # the cores' shared_store()s → durable space slots
    from core.apigatewayv2_core import shared_store as _apigwv2_store
    from core.stepfunctions_core import shared_store as _sfn_store, set_lambda_store as _sfn_lambda
    from core.gcp_cloudscheduler_core import shared_store as _gcp_sched_store
    from core.gcp_container_core import shared_store as _gcp_gke_store
    from core.gcp_iamcredentials_core import shared_store as _gcp_iamc_store
    from core.gcp_redis_core import shared_store as _gcp_redis_store
    from core.gcp_monitoring_core import shared_store as _gcp_mon_store
    _ns = {"apigwv2": _apigwv2_store(), "sfn": _sfn_store(), "gcp_sched": _gcp_sched_store(), "gcp_gke": _gcp_gke_store(), "gcp_iamc": _gcp_iamc_store(), "gcp_redis": _gcp_redis_store(), "gcp_mon": _gcp_mon_store(),
           # GCP custom roles / Workload Identity (gcp_iam), Org Policy v2 (gcp_rm), Azure RBAC
           # (iam) and Azure SQL (rds): durable space slots, not the router's in-memory defaults
           **_aps.net_new_core_stores()}
    if is_unified("lambda"):   # C0f: API Gateway / Step Functions / Scheduler reach the appliance's functions
        _ns["lam"] = _aps.lambda_store()
    try:   # the Azure SQL data plane enforces the server's ARM settings (publicNetworkAccess, …):
        from providers.azure_services import core_arm as _core_arm   # read the appliance's OWN ARM state
        _ns["az_arm"] = _core_arm()
    except Exception:
        pass
    r = router or AwsWireRouter(stores=_ns)
    _sfn_lambda(r.lam)   # Step Functions Task states invoke the Lambdas this router serves
    global _NEW_SERVICES_ROUTER
    _NEW_SERVICES_ROUTER = r   # C0e: EventBridge / Scheduler Lambda targets reach these functions too

    async def _proxy(request: Request):
        body = await request.body()
        from core import app_context as _ctx
        # /azure-sql reads the Azure space's ARM records (space-scoped by provider)
        tok = _ctx.REQUEST_PROVIDER.set("azure") if request.url.path.startswith("/azure-sql") else None
        try:
            out = await r.ahandle(request.method, request.url.path,
                                  dict(request.query_params), dict(request.headers), body)
        finally:
            if tok is not None:
                _ctx.REQUEST_PROVIDER.reset(tok)
        return Response(content=out["body"], status_code=out["status"],
                        headers={k: v for k, v in (out["headers"] or {}).items()})

    methods = ["GET", "POST", "PUT", "DELETE", "HEAD", "PATCH"]
    for prefix in ("/2015-03-31/functions", "/restapis", "/v2/apis", "/v2/domainnames", "/v2/vpclinks", "/v2/tags", "/azure-sql",
                   "/providers/Microsoft.Authorization",
                   # GCP IAM custom roles, Workload Identity Federation, Org Policy v2 — the
                   # cores Nano serves (the offline legacy GCP IAM never had these: 404)
                   "/v1/projects/{project}/roles", "/v1/projects/{project}/locations/global/workloadIdentityPools",
                   "/v2/projects/{project}/policies"):
        app.add_route(prefix, _proxy, methods=methods)
        app.add_route(prefix + "/{rest:path}", _proxy, methods=methods)
