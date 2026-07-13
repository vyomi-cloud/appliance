"""AwsWireRouter — the native-AWS-wire front door for the Nano relay / bridge.

An EXTERNAL app (unmodified boto3 / aws-cli / your service) points its
`--endpoint-url` at the relay; the relay forwards the raw HTTP request to the
in-browser Nano tab, which hands it to this router. The router inspects the
request the way a real cloud front-end does — SigV4 credential scope, then the
`X-Amz-Target` header, then the Query-protocol `Action` — picks the owning
service, and dispatches to that service's PROVEN conformance core in its NATIVE
wire (S3: method+path; DynamoDB/KMS/Secrets/SQS: X-Amz-Target JSON; IAM/RDS/SNS:
Query+XML). So an external SDK call is served by the SAME logic the conformance
suite asserts on host CPython AND Pyodide — not a stub, and not a re-implementation.

This is the relay analogue of the console's `aws_core_adapter` (which translates
the friendly console REST). Here there is NO translation: the wire IS the native
cloud wire, because the caller is a real SDK.

Design notes:
  * Substrate-free — stdlib (json/base64/urllib/re) + the cores only. No
    fastapi / socket / boto3 at module top, so it loads under Pyodide and is
    provable on both substrates like every core.
  * Routing reads SigV4 but NEVER verifies it (handlers don't enforce SigV4 so
    an unmodified SDK works); the credential scope is just the cleanest service
    signal a real SDK always sends, even through `--endpoint-url`.
  * SNS and SQS SHARE one MessagingStore so `Publish` fans out into a subscribed
    SQS queue — the canonical SNS→SQS pattern, exactly as the messaging
    conformance suite proves.

Output is uniform: {"status": int, "headers": {str:str}, "body": bytes}.
"""
from __future__ import annotations

import json
import re
from urllib.parse import parse_qsl

from core.object_store import InMemoryObjectStore
from core import s3_object_core as s3
from core.nosql_store import InMemoryNoSqlStore
from core import dynamodb_core as ddb
from core.kms_keystore import InMemoryKeyStore
from core import kms_core as kms
from core.kv_store import InMemoryKvStore
from core import secrets_core as secrets
from core.sql_store import InMemorySqlStore
from core import rds_core as rds
from core.iam_store import InMemoryIamStore
from core import iam_core as iam
from core.messaging_store import InMemoryMessagingStore
from core import sqs_core as sqs
from core import sns_core as sns
from core import rds_data_core as rds_data
from core import gcp_storage_core as gcs   # GCP: GCS JSON API, path-routed (not SigV4)
from core import gcp_firestore_core as gcp_fs
from core.gcp_firestore_core import FirestoreStore
from core import gcp_kms_core as gcp_kms
from core import gcp_secretmanager_core as gcp_sec
from core import gcp_pubsub_core as gcp_ps
from core import gcp_iam_core as gcp_iam
from core import gcp_cloudsql_core as gcp_sql


def _gcp_service(path):
    """Route a GCP request by URL path (GCP carries no SigV4; each google-cloud-*
    client is pointed at the relay and the path is the service discriminator)."""
    if path.startswith(("/storage/v1", "/upload/storage/v1", "/download/storage/v1")):
        return "gcp-gcs"
    if path.startswith(("/sql/v1beta4", "/sql/v1")):
        return "gcp-cloudsql"
    # The /v1/projects/* family — gate on /projects/ so Azure's root /secrets,
    # /keys, /topics never collide (GCP always scopes these under a project).
    if "/projects/" in path:
        if "/databases/" in path and "/documents" in path:
            return "gcp-firestore"
        if "/keyRings" in path:
            return "gcp-kms"
        if "/secrets" in path:
            return "gcp-secretmanager"
        if "/topics" in path or "/subscriptions" in path:
            return "gcp-pubsub"
        if "/serviceAccounts" in path or path.endswith(
                (":getIamPolicy", ":setIamPolicy", ":testIamPermissions")):
            return "gcp-iam"
    return None


from core import azure_blob_core as az_blob
from core.azure_blob_core import AzureBlobStore
from core import azure_cosmos_core as az_cosmos
from core.azure_cosmos_core import CosmosStore
from core import azure_keyvault_secrets_core as az_kvsec
from core import azure_keyvault_keys_core as az_kvkeys
from core import azure_queue_core as az_queue
from core.azure_queue_core import AzureQueueStore
from core import azure_servicebus_core as az_sb
from core import eventbridge_core as events
from core import lambda_core as lam
from core import apigateway_core as apigw
from core import vpc_core as vpc
import types as _types


def _azure_service(path, lheaders, query):
    """Route an Azure data-plane request. Azure carries no SigV4; we read the
    x-ms-* headers, the ?api-version / ?restype / ?comp query, and the path
    shape. Known limits: over a single relay we can't see the .blob/.queue host,
    so root `?comp=list` (list-containers vs list-queues) defaults to blob."""
    query = query or {}
    p = path
    if p.startswith("/devstoreaccount1/"):     # Azurite account prefix
        p = p[len("/devstoreaccount1"):]
    elif p == "/devstoreaccount1":
        p = "/"
    apiv = ("api-version" in query) or ("api-version=" in path)
    # Key Vault (data plane): root /keys or /secrets WITH api-version (GCP secrets
    # live under /v1/projects/…; a plain S3 bucket named "keys" has no api-version).
    if apiv and "/projects/" not in p:
        s0 = p.lstrip("/").split("/", 1)[0]
        if s0 == "keys":
            return "az-kv-keys"
        if s0 == "secrets":
            return "az-kv-secrets"
    # Cosmos DB: /dbs path or the documentdb headers.
    if p.startswith("/dbs") or any(k.startswith("x-ms-documentdb") for k in lheaders):
        return "az-cosmos"
    # Blob / Queue: identified by the x-ms-* storage headers.
    if "x-ms-version" in lheaders or "x-ms-blob-type" in lheaders:
        if "/messages" in p:
            return "az-queue"
        if "x-ms-blob-type" in lheaders or query.get("restype") == "container":
            return "az-blob"
        segs = [s for s in p.split("/") if s]
        if len(segs) >= 2:          # /{container}/{blob}
            return "az-blob"
        if len(segs) == 1:          # /{queue} create/delete/metadata (blob container ops carry restype)
            return "az-queue"
        return "az-blob"            # root ?comp=list → default to containers
    return None

# SigV4 credential scope: "Credential=AKID/20230626/us-east-1/<service>/aws4_request"
_CRED_RE = re.compile(r"Credential=[^/]+/[^/]+/[^/]+/([^/,]+)/aws4_request")

# AWS signing-name → our core key. (S3 falls through as the default.)
_SIGNING = {
    "dynamodb": "dynamodb", "kms": "kms", "secretsmanager": "secretsmanager",
    "sqs": "sqs", "sns": "sns", "iam": "iam", "rds": "rds", "s3": "s3",
    "rds-data": "rds-data",   # the Aurora HTTP SQL surface (async path)
    "events": "events", "lambda": "lambda", "ec2": "vpc",
}

# X-Amz-Target prefix → our core key (the JSON-wire services).
_TARGET_PREFIX = {
    "DynamoDB_": "dynamodb", "TrentService": "kms",
    "secretsmanager": "secretsmanager", "AmazonSQS": "sqs", "AWSEvents": "events",
}

# Native JSON content-types the real SDK expects back per service.
_JSON_CT = {
    "dynamodb": "application/x-amz-json-1.0", "kms": "application/x-amz-json-1.1",
    "secretsmanager": "application/x-amz-json-1.1", "sqs": "application/x-amz-json-1.0",
    "events": "application/x-amz-json-1.1",
}

# Query-protocol Action → service, for UNSIGNED query requests (signed ones route
# by credential scope). Small but covers the common verbs of each service.
_QUERY_ACTION = {
    # SNS
    "CreateTopic": "sns", "DeleteTopic": "sns", "ListTopics": "sns",
    "Subscribe": "sns", "Unsubscribe": "sns", "ListSubscriptions": "sns",
    "ListSubscriptionsByTopic": "sns", "Publish": "sns", "GetTopicAttributes": "sns",
    "SetSubscriptionAttributes": "sns", "GetSubscriptionAttributes": "sns",
    # RDS
    "CreateDBInstance": "rds", "DescribeDBInstances": "rds", "DeleteDBInstance": "rds",
    "ModifyDBInstance": "rds", "StartDBInstance": "rds", "StopDBInstance": "rds",
    "RebootDBInstance": "rds", "CreateDBSnapshot": "rds", "DescribeDBSnapshots": "rds",
    # IAM
    "CreateUser": "iam", "DeleteUser": "iam", "ListUsers": "iam", "GetUser": "iam",
    "CreateRole": "iam", "DeleteRole": "iam", "ListRoles": "iam",
    "CreatePolicy": "iam", "DeletePolicy": "iam", "ListPolicies": "iam",
    "AttachUserPolicy": "iam", "DetachUserPolicy": "iam",
    "SimulatePrincipalPolicy": "iam", "CreateGroup": "iam", "ListGroups": "iam",
    # EC2 / VPC
    "CreateVpc": "vpc", "CreateSubnet": "vpc", "CreateSecurityGroup": "vpc",
    "AuthorizeSecurityGroupIngress": "vpc", "AuthorizeSecurityGroupEgress": "vpc",
    "CreateInternetGateway": "vpc", "AttachInternetGateway": "vpc", "CreateRoute": "vpc",
    "DescribeVpcs": "vpc", "CreateNetworkAcl": "vpc", "CreateNetworkAclEntry": "vpc",
    "AssociateNetworkAcl": "vpc", "AnalyzeReachability": "vpc",
}


def _lower_headers(headers):
    return {str(k).lower(): v for k, v in (headers or {}).items()}


class AwsWireRouter:
    """Holds one in-tab store per service (the single source of truth for the
    relay endpoint) and routes native AWS-wire requests to the proven cores."""

    def __init__(self, sql_store=None, stores=None):
        # Stores are INJECTABLE (v2.4.0): Nano/relay pass nothing → in-WASM
        # defaults; Pro/Max passes a `stores` map of real backed stores (MinIO,
        # Postgres, Vault, NATS) behind the identical seam. `sql_store` kept for
        # back-compat (the browser PGlite path).
        s = stores or {}
        self.s3 = s.get("s3") or InMemoryObjectStore()
        self.ddb = s.get("ddb") or InMemoryNoSqlStore()
        self.kms = s.get("kms") or InMemoryKeyStore()
        self.sec = s.get("sec") or InMemoryKvStore()
        self.rds = s.get("rds") or sql_store or InMemorySqlStore()
        self.iam = s.get("iam") or InMemoryIamStore()
        self.msg = s.get("msg") or InMemoryMessagingStore()   # SHARED by sqs + sns (fan-out)
        # GCP services — each its own store instance (namespaced from AWS).
        self.gcs = s.get("gcs") or InMemoryObjectStore()
        self.gcp_fs = s.get("gcp_fs") or FirestoreStore()
        self.gcp_kms = s.get("gcp_kms") or InMemoryKeyStore()
        self.gcp_sec = s.get("gcp_sec") or InMemoryKvStore()
        self.gcp_msg = s.get("gcp_msg") or InMemoryMessagingStore()
        self.gcp_iam = s.get("gcp_iam") or InMemoryIamStore()
        self.gcp_sql = s.get("gcp_sql") or InMemorySqlStore()
        # Azure data-plane services.
        self.az_blob = s.get("az_blob") or AzureBlobStore()
        self.az_cosmos = s.get("az_cosmos") or CosmosStore()
        self.az_kvsec = s.get("az_kvsec") or InMemoryKvStore()
        self.az_kvkeys = s.get("az_kvkeys") or InMemoryKeyStore()
        self.az_queue = s.get("az_queue") or AzureQueueStore()
        self.az_sb = s.get("az_sb") or InMemoryMessagingStore()   # Service Bus topics (fan-out)
        # EventBridge shares the messaging store (rules + SQS delivery); Lambda gets
        # its own lightweight function registry (a namespace the core attaches to).
        self.events = s.get("events") or self.msg
        self.lam = s.get("lam") or _types.SimpleNamespace()
        # API Gateway shares the Lambda store so an AWS_PROXY integration can reach
        # the registered functions (the API-GW → Lambda synergy).
        self.apigw = s.get("apigw") or self.lam
        self.vpc = s.get("vpc") or _types.SimpleNamespace()   # EC2/VPC network model

    def _servicebus_service(self, method, path, lheaders):
        """Azure Service Bus (topics) — the pub/sub-fan-out peer of SNS/Pub-Sub.
        Distinct from Azure Storage (carries NO x-ms-* storage headers) and from
        the ARM control plane (`subscriptions` is segment[1], not segment[0]).
        Identified by: a subscription-scoped path, a Service Bus runtime marker
        (BrokerProperties / atom+xml management), or a first segment that already
        names a known topic (so send/receive on an existing topic routes cleanly)."""
        if "x-ms-version" in lheaders or "x-ms-blob-type" in lheaders:
            return False   # Azure Storage (Blob/Queue), not Service Bus
        segs = [s for s in path.split("?", 1)[0].split("/") if s]
        if len(segs) >= 3 and segs[1] == "subscriptions":
            return True    # /{topic}/subscriptions/{sub}[...] — unambiguous
        if "brokerproperties" in lheaders:
            return True    # a Service Bus send/receive runtime request
        ct = (lheaders.get("content-type") or "")
        if "atom+xml" in ct:
            return True    # Service Bus entity-management (create topic/subscription)
        if segs and segs[0] in getattr(self.az_sb, "topics", {}):
            return True    # send/get/delete on an already-created topic
        return False

    # ── service detection ──────────────────────────────────────────────
    def service_of(self, method, path, lheaders, body, query=None):
        # GCP services are unambiguous by path (REST) and carry no SigV4 — route
        # them first so they never fall through to the S3 default.
        gcp = _gcp_service(path)
        if gcp:
            return gcp
        az = _azure_service(path, lheaders, query)   # Azure data plane (x-ms-* / api-version)
        if az:
            return az
        if self._servicebus_service(method, path, lheaders):
            return "az-servicebus"
        if "/2015-03-31/functions" in path:   # Lambda REST (native boto3 lambda wire)
            return "lambda"
        if "/restapis" in path:               # API Gateway v1 control plane
            return "apigateway"
        target = lheaders.get("x-amz-target", "") or ""
        if target:
            for prefix, svc in _TARGET_PREFIX.items():
                if target.startswith(prefix):
                    return svc
        auth = lheaders.get("authorization", "") or ""
        m = _CRED_RE.search(auth)
        if m:
            svc = _SIGNING.get(m.group(1))
            if svc:
                return svc
        # Unsigned Query-protocol request: route by Action.
        ct = (lheaders.get("content-type", "") or "").lower()
        if "x-www-form-urlencoded" in ct or "Action=" in (self._text(body) or ""):
            action = self._query_params(None, body).get("Action", "")
            svc = _QUERY_ACTION.get(action)
            if svc:
                return svc
        if rds_data.is_data_api_path(path):  # unsigned Data API (rest-json path)
            return "rds-data"
        return "s3"  # default: bucket/key path-style

    # ── body helpers ───────────────────────────────────────────────────
    @staticmethod
    def _text(body):
        if body is None:
            return ""
        if isinstance(body, (bytes, bytearray)):
            try:
                return body.decode("utf-8")
            except Exception:
                return ""
        return str(body)

    def _json_body(self, body):
        txt = self._text(body).strip()
        if not txt:
            return {}
        try:
            d = json.loads(txt)
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}

    def _query_params(self, query, body):
        params = dict(query or {})
        txt = self._text(body)
        if txt:
            params.update(dict(parse_qsl(txt, keep_blank_values=True)))
        return params

    # ── dispatch ───────────────────────────────────────────────────────
    async def ahandle(self, method, path, query, headers, body):
        """Async front door: serves the RDS Data API (which must await the SQL
        engine) and delegates every other — synchronous — service to handle(). The
        relay tab calls THIS so an external `boto3 rds-data` request reaches PGlite."""
        lheaders = _lower_headers(headers)
        b = body if isinstance(body, (bytes, bytearray)) else (body or b"")
        if isinstance(b, str):
            b = b.encode("utf-8")
        if self.service_of(method, path, lheaders, b, query) == "rds-data":
            r = await rds_data.dispatch(self.rds, path, self._json_body(b))
            hdrs = dict(r.headers or {})
            hdrs.setdefault("content-type", "application/json")
            return {"status": r.status, "headers": hdrs, "body": json.dumps(r.body).encode()}
        return self.handle(method, path, query, headers, body)

    def handle(self, method, path, query, headers, body):
        """Route ONE native-wire request. Returns {status, headers, body(bytes)}.
        SYNC services only — the RDS Data API goes through ahandle()."""
        lheaders = _lower_headers(headers)
        body = body if isinstance(body, (bytes, bytearray)) else (body or b"")
        if isinstance(body, str):
            body = body.encode("utf-8")
        svc = self.service_of(method, path, lheaders, body, query)

        if svc == "rds-data":  # async-only — guard the sync path
            return {"status": 400, "headers": {"x-amzn-errortype": "BadRequestException"},
                    "body": b'{"message":"RDS Data API requires the async dispatch path"}'}

        if svc == "s3":
            r = s3.dispatch(self.s3, method, path, query or {}, headers or {}, bytes(body))
            return {"status": r.status, "headers": dict(r.headers or {}),
                    "body": r.body or b""}

        if svc == "lambda":   # native Lambda REST (function mgmt + sandboxed invoke)
            r = lam.dispatch(self.lam, method, path, query or {}, headers or {}, bytes(body))
            hdrs = dict(r.headers or {})
            if r.media_type and not any(k.lower() == "content-type" for k in hdrs):
                hdrs["content-type"] = r.media_type
            return {"status": r.status, "headers": hdrs, "body": r.body or b""}

        if svc == "apigateway":   # native API Gateway v1 control plane (/restapis)
            r = apigw.dispatch(self.apigw, method, path, query or {}, headers or {}, bytes(body))
            hdrs = dict(r.headers or {})
            if r.media_type and not any(k.lower() == "content-type" for k in hdrs):
                hdrs["content-type"] = r.media_type
            return {"status": r.status, "headers": hdrs, "body": r.body or b""}

        if svc and svc.startswith("gcp-"):   # GCP services — native google-cloud-* REST wire
            _gcp_core = {
                "gcp-gcs": (gcs, self.gcs), "gcp-firestore": (gcp_fs, self.gcp_fs),
                "gcp-kms": (gcp_kms, self.gcp_kms), "gcp-secretmanager": (gcp_sec, self.gcp_sec),
                "gcp-pubsub": (gcp_ps, self.gcp_msg), "gcp-iam": (gcp_iam, self.gcp_iam),
                "gcp-cloudsql": (gcp_sql, self.gcp_sql),
            }[svc]
            mod, store = _gcp_core
            r = mod.dispatch(store, method, path, query or {}, headers or {}, bytes(body))
            hdrs = dict(r.headers or {})
            if r.media_type and not any(k.lower() == "content-type" for k in hdrs):
                hdrs["content-type"] = r.media_type
            return {"status": r.status, "headers": hdrs, "body": r.body or b""}

        if svc and svc.startswith("az-"):   # Azure data plane — native azure-* SDK wire
            _az_core = {
                "az-blob": (az_blob, self.az_blob), "az-cosmos": (az_cosmos, self.az_cosmos),
                "az-kv-secrets": (az_kvsec, self.az_kvsec), "az-kv-keys": (az_kvkeys, self.az_kvkeys),
                "az-queue": (az_queue, self.az_queue), "az-servicebus": (az_sb, self.az_sb),
            }[svc]
            mod, store = _az_core
            r = mod.dispatch(store, method, path, query or {}, headers or {}, bytes(body))
            hdrs = dict(r.headers or {})
            if r.media_type and not any(k.lower() == "content-type" for k in hdrs):
                hdrs["content-type"] = r.media_type
            return {"status": r.status, "headers": hdrs, "body": r.body or b""}

        if svc in _JSON_CT:
            target = lheaders.get("x-amz-target", "") or ""
            payload = self._json_body(body)
            if svc == "dynamodb":
                r = ddb.dispatch(self.ddb, target, payload)
            elif svc == "kms":
                r = kms.dispatch(self.kms, target, payload)
            elif svc == "secretsmanager":
                r = secrets.dispatch(self.sec, target, payload)
            elif svc == "events":
                r = events.dispatch(self.events, target, payload)
            else:  # sqs
                r = sqs.dispatch(self.msg, target, payload)
            hdrs = dict(r.headers or {})
            hdrs.setdefault("content-type", _JSON_CT[svc])
            return {"status": r.status, "headers": hdrs,
                    "body": json.dumps(r.body).encode()}

        # Query-protocol / XML services
        params = self._query_params(query, body)
        if svc == "iam":
            r = iam.dispatch(self.iam, params)
        elif svc == "rds":
            r = rds.dispatch(self.rds, params)
        elif svc == "vpc":
            r = vpc.dispatch(self.vpc, params)
        else:  # sns
            r = sns.dispatch(self.msg, params)
        hdrs = dict(r.headers or {})
        hdrs.setdefault("content-type", "text/xml")
        body_txt = r.body if isinstance(r.body, str) else json.dumps(r.body)
        return {"status": r.status, "headers": hdrs, "body": body_txt.encode()}
