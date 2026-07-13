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
"""
from __future__ import annotations

import os

from core.aws_wire_router import AwsWireRouter


def _cfg(key: str, default: str) -> str:
    return os.environ.get(key, default)


def build_backed_router() -> AwsWireRouter:
    """An AwsWireRouter wired to the appliance's real backends behind the seams."""
    from core.minio_backed_store import MinioBackedObjectStore
    from core.postgres_backed_store import PostgresBackedSqlStore
    from core.vault_backed_store import VaultBackedKeyStore, VaultBackedKvStore
    from core.persistent_store import (SqliteStateBackend, PersistentAzureBlobStore,
                                        PersistentNoSqlStore, PersistentFirestoreStore,
                                        PersistentCosmosStore, PersistentAzureQueueStore,
                                        PersistentMessagingStore)
    from core.nats_backed_store import NatsBackedMessagingStore

    minio = dict(
        endpoint=_cfg("VYOMI_MINIO_ENDPOINT", "http://localhost:9100"),
        access_key=_cfg("VYOMI_MINIO_ACCESS_KEY", "cloudlearn"),
        secret_key=_cfg("VYOMI_MINIO_SECRET_KEY", "cloudlearn-dev-secret-key"))
    pg_dsn = _cfg("VYOMI_PG_DSN",
                  "host=localhost port=35432 user=postgres password=cloudlearn dbname=postgres")
    vault = dict(addr=_cfg("VYOMI_VAULT_ADDR", "http://localhost:8200"),
                 token=_cfg("VYOMI_VAULT_TOKEN", "vyomi-dev-token"))
    nats_servers = _cfg("VYOMI_NATS", "nats://localhost:4222")

    stores = {
        # object storage — AWS S3 + GCP GCS on MinIO (namespaced prefixes)
        "s3": MinioBackedObjectStore(prefix="aws-s3-", **minio),
        "gcs": MinioBackedObjectStore(prefix="gcp-gcs-", **minio),
        # relational — RDS + Cloud SQL on real Postgres (schema-namespaced)
        "rds": PostgresBackedSqlStore(pg_dsn, schema_prefix="rds_"),
        "gcp_sql": PostgresBackedSqlStore(pg_dsn, schema_prefix="gcpsql_"),
        # security / crypto — KMS + Cloud KMS + Azure KV keys on Vault Transit
        "kms": VaultBackedKeyStore(**vault),
        "gcp_kms": VaultBackedKeyStore(**vault),
        "az_kvkeys": VaultBackedKeyStore(**vault),
        # secrets (v2.5.0) — Vault KV v2, namespaced per cloud
        "sec": VaultBackedKvStore(prefix="aws-sec/", **vault),
        "gcp_sec": VaultBackedKvStore(prefix="gcp-sec/", **vault),
        "az_kvsec": VaultBackedKvStore(prefix="az-sec/", **vault),
        # Azure Blob (v2.5.0) — durable via the file-backed substrate (was in-memory)
        "az_blob": PersistentAzureBlobStore(
            SqliteStateBackend(_cfg("VYOMI_AZBLOB_DB", "/tmp/vyomi-azblob.sqlite"))),
        # DynamoDB (v2.5.0) — durable NoSQL via the file-backed substrate (was in-memory)
        "ddb": PersistentNoSqlStore(
            SqliteStateBackend(_cfg("VYOMI_DDB_DB", "/tmp/vyomi-ddb.sqlite"))),
        # Firestore (v2.5.0) — durable documents via the file-backed substrate
        "gcp_fs": PersistentFirestoreStore(
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
        # messaging — SQS/SNS + Pub/Sub on NATS JetStream (separate KV buckets)
        "msg": NatsBackedMessagingStore(servers=nats_servers, bucket="aws_msg"),
        "gcp_msg": NatsBackedMessagingStore(servers=nats_servers, bucket="gcp_msg"),
    }
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
