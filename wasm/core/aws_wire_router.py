# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
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

# SigV4 credential scope: "Credential=AKID/20230626/us-east-1/<service>/aws4_request"
_CRED_RE = re.compile(r"Credential=[^/]+/[^/]+/[^/]+/([^/,]+)/aws4_request")

# AWS signing-name → our core key. (S3 falls through as the default.)
_SIGNING = {
    "dynamodb": "dynamodb", "kms": "kms", "secretsmanager": "secretsmanager",
    "sqs": "sqs", "sns": "sns", "iam": "iam", "rds": "rds", "s3": "s3",
    "rds-data": "rds-data",   # the Aurora HTTP SQL surface (async path)
}

# X-Amz-Target prefix → our core key (the JSON-wire services).
_TARGET_PREFIX = {
    "DynamoDB_": "dynamodb", "TrentService": "kms",
    "secretsmanager": "secretsmanager", "AmazonSQS": "sqs",
}

# Native JSON content-types the real SDK expects back per service.
_JSON_CT = {
    "dynamodb": "application/x-amz-json-1.0", "kms": "application/x-amz-json-1.1",
    "secretsmanager": "application/x-amz-json-1.1", "sqs": "application/x-amz-json-1.0",
}

# Query-protocol Action → service, for UNSIGNED query requests (signed ones route
# by credential scope). Small but covers the common verbs of each service.
_QUERY_ACTION = {
    # SNS
    "CreateTopic": "sns", "DeleteTopic": "sns", "ListTopics": "sns",
    "Subscribe": "sns", "Unsubscribe": "sns", "ListSubscriptions": "sns",
    "ListSubscriptionsByTopic": "sns", "Publish": "sns", "GetTopicAttributes": "sns",
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
}


def _lower_headers(headers):
    return {str(k).lower(): v for k, v in (headers or {}).items()}


class AwsWireRouter:
    """Holds one in-tab store per service (the single source of truth for the
    relay endpoint) and routes native AWS-wire requests to the proven cores."""

    def __init__(self, sql_store=None):
        self.s3 = InMemoryObjectStore()
        self.ddb = InMemoryNoSqlStore()
        self.kms = InMemoryKeyStore()
        self.sec = InMemoryKvStore()
        # RDS data-plane engine is injectable: sqlite3 by default (host + Pyodide),
        # PGliteSqlStore (real Postgres) when the browser bundle supplies it.
        self.rds = sql_store if sql_store is not None else InMemorySqlStore()
        self.iam = InMemoryIamStore()
        self.msg = InMemoryMessagingStore()   # SHARED by sqs + sns (fan-out)

    # ── service detection ──────────────────────────────────────────────
    def service_of(self, method, path, lheaders, body):
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
        if self.service_of(method, path, lheaders, b) == "rds-data":
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
        svc = self.service_of(method, path, lheaders, body)

        if svc == "rds-data":  # async-only — guard the sync path
            return {"status": 400, "headers": {"x-amzn-errortype": "BadRequestException"},
                    "body": b'{"message":"RDS Data API requires the async dispatch path"}'}

        if svc == "s3":
            r = s3.dispatch(self.s3, method, path, query or {}, headers or {}, bytes(body))
            return {"status": r.status, "headers": dict(r.headers or {}),
                    "body": r.body or b""}

        if svc in _JSON_CT:
            target = lheaders.get("x-amz-target", "") or ""
            payload = self._json_body(body)
            if svc == "dynamodb":
                r = ddb.dispatch(self.ddb, target, payload)
            elif svc == "kms":
                r = kms.dispatch(self.kms, target, payload)
            elif svc == "secretsmanager":
                r = secrets.dispatch(self.sec, target, payload)
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
        else:  # sns
            r = sns.dispatch(self.msg, params)
        hdrs = dict(r.headers or {})
        hdrs.setdefault("content-type", "text/xml")
        body_txt = r.body if isinstance(r.body, str) else json.dumps(r.body)
        return {"status": r.status, "headers": hdrs, "body": body_txt.encode()}
