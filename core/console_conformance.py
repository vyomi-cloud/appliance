"""Console conformance signal (F5 seam) — the honest gate behind the console-next
rich-widget rendering (§14.5) and the status-bar conformance pill.

The console gates each service's RICH data-plane widget on this signal: a service
renders its rich widget only when its conformance mode is `full`; otherwise the UI
falls back to the generic-control-plane view. This module is the single source of
that per-service signal.

TODAY (P1a) this is a curated, deterministic map keyed off the KNOWN conformance
state of each service's core (the conformance suite in tests/conformance/*). It is
deliberately shaped like the eventual live source so F5 can swap the backing data
without touching the UI or the manifest contract:

    { service_id: {
        "mode":   "full" | "degraded" | "generic",   # gates the rich widget
        "status": "conformant" | "partial" | "unknown",
        "checks": {"passed": int, "total": int},      # from the suite (stubbed)
        "note":   "...",                              # human one-liner
    } }

`mode` vs `status`:
  - `mode` drives WHICH widget renders (the capability gate).
  - `status` drives the pill colour/label (a coarser rollup for the status bar).

When the live conformance runner lands (F5), replace `_SIGNAL` with a reader over
the suite's latest results; the shape and the two public functions stay stable.

Substrate note: this is the LOCAL/FastAPI substrate's view. Nano emits the same
shape from its own runner; the UI is identical either way (§15.1 #5).
"""

from __future__ import annotations

import os

# Curated per-service signal. Numbers reflect the conformance-suite check counts
# recorded for each core (see tests/conformance/* and the project conformance
# notes); they are a stub for the live F5 feed, not a live count.
_SIGNAL = {
    "s3": {
        "mode": "full", "status": "conformant",
        "checks": {"passed": 41, "total": 41},
        "note": "S3 object store — real MinIO; object-browser is conformance-gated green.",
    },
    "dynamodb": {
        # backend conformant AND the nosql-item-viewer widget now ships — the rich
        # data-plane view (list tables / browse+get/put items / key query) is wired
        # in center-canvas, so gate to "full".
        "mode": "full", "status": "conformant",
        "checks": {"passed": 45, "total": 45},
        "note": "DynamoDB core conformant; nosql-item-viewer widget is conformance-gated green.",
    },
    "rds": {
        "mode": "full", "status": "conformant",
        "checks": {"passed": 29, "total": 29},
        "note": "RDS Data API (ExecuteStatement) — relay-safe SQL over HTTP; real SQL engine.",
    },
    "sqs": {
        # backend conformant AND the queue-topic-viewer widget now ships — the rich
        # data-plane view (list queues+topics / send+peek+receive / SNS→SQS subscribe
        # + publish fan-out) is wired in center-canvas, so gate to "full".
        "mode": "full", "status": "conformant",
        "checks": {"passed": 32, "total": 32},
        "note": "SQS+SNS core conformant; queue-topic-viewer widget is conformance-gated green.",
    },
    "secretsmanager": {
        # backend conformant AND the kv-secret-viewer widget now ships — the rich
        # data-plane view (list secrets / describe versions+stages / masked value
        # with deliberate reveal / create + put-value) is wired in center-canvas,
        # so gate to "full".
        "mode": "full", "status": "conformant",
        "checks": {"passed": 32, "total": 32},
        "note": "Secrets Manager core conformant; kv-secret-viewer widget is conformance-gated green.",
    },
    "kms": {
        # backend conformant AND the kms-crypto-view widget now ships — the rich
        # data-plane view (list keys / create key / encrypt→ciphertext / decrypt→
        # plaintext round-trip / generate-data-key) is wired in center-canvas over
        # the REAL kms_core crypto, so gate to "full".
        "mode": "full", "status": "conformant",
        "checks": {"passed": 36, "total": 36},
        "note": "KMS core conformant; kms-crypto-view widget is conformance-gated green.",
    },
    "iam": {
        "mode": "generic", "status": "partial",
        "checks": {"passed": 20, "total": 28},
        "note": "IAM — control-plane + policy simulator; rich generic-control-plane view.",
    },
    "ec2": {
        # backend conformant AND the compute-terminal widget now ships — the rich
        # data-plane view (list instances / SSH connect-info + .pem download / app
        # URL / in-browser console-exec terminal) is wired in center-canvas over the
        # real EC2 state + connect-info endpoints, so gate to "full".
        "mode": "full", "status": "conformant",
        "checks": {"passed": 34, "total": 34},
        "note": "EC2 core conformant; compute-terminal widget is conformance-gated green.",
    },
    "lambda": {
        # backend conformant AND the serverless-invoke widget now ships — the rich
        # data-plane view (list functions / config / JSON payload editor + invoke →
        # response payload + status + logs / optional create) is wired in
        # center-canvas over the REAL Lambda runtime (sandboxed handler), so gate
        # to "full".
        "mode": "full", "status": "conformant",
        "checks": {"passed": 27, "total": 27},
        "note": "Lambda core conformant; serverless-invoke widget is conformance-gated green.",
    },
    # ── GCP lens (P3) ── the SAME object-browser widget serves GCS; only the
    # manifest `api` block differs (§15.2). Cloud Storage object CRUD is
    # conformant (native google-cloud-storage SDK round-trips), so gate to "full".
    "gcp.storage": {
        "mode": "full", "status": "conformant",
        "checks": {"passed": 12, "total": 12},
        "note": "GCP Cloud Storage — object-browser serves GCS via the same widget (lens=gcp).",
    },
    # Cloud SQL (Postgres-backed) reuses the SAME sql-console widget under lens=gcp;
    # only the manifest `api` block differs (§15.2). SQL runs against the same
    # relay-safe SQL engine the RDS Data API facade uses, so gate to "full".
    "gcp.cloudsql": {
        "mode": "full", "status": "conformant",
        "checks": {"passed": 29, "total": 29},
        "note": "GCP Cloud SQL — sql-console serves Cloud SQL via the same widget (lens=gcp).",
    },
    # Firestore (document DB) reuses the SAME nosql-item-viewer widget under lens=gcp;
    # only the manifest `api` block differs (§15.2). A collection is the "table", a
    # document the "item", and the document id is surfaced as the partition key so the
    # key-query UX works unchanged. Collection/document CRUD + key query is
    # conformant, so gate to "full".
    "gcp.firestore": {
        "mode": "full", "status": "conformant",
        "checks": {"passed": 12, "total": 12},
        "note": "GCP Firestore — nosql-item-viewer serves Firestore via the same widget (lens=gcp).",
    },
    # Pub/Sub reuses the SAME queue-topic-viewer widget under lens=gcp; only the
    # manifest `api` block differs (§15.2). A Pub/Sub topic fans out to
    # subscriptions you pull from — the widget's queue column IS the subscription
    # list, so the flagship publish→fan-out→pull flow works unchanged. Topic +
    # subscription CRUD + publish/pull fan-out is conformant, so gate to "full".
    "gcp.pubsub": {
        "mode": "full", "status": "conformant",
        "checks": {"passed": 14, "total": 14},
        "note": "GCP Pub/Sub — queue-topic-viewer serves Pub/Sub via the same widget (lens=gcp).",
    },
    # Secret Manager reuses the SAME kv-secret-viewer widget under lens=gcp; only the
    # manifest `api` block differs (§15.2). A GCP secret carries versions (newest =
    # current, prior = previous), so the masked value + deliberate reveal, version→
    # stage list, and put-value (new current, prior demoted) flow work unchanged.
    # Secret + version CRUD + masked-reveal is conformant, so gate to "full".
    "gcp.secretmanager": {
        "mode": "full", "status": "conformant",
        "checks": {"passed": 12, "total": 12},
        "note": "GCP Secret Manager — kv-secret-viewer serves Secret Manager via the same widget (lens=gcp).",
    },
    # Cloud KMS reuses the SAME kms-crypto-view widget under lens=gcp; only the
    # manifest `api` block differs (§15.2). It drives the REAL kms_core crypto over an
    # independent KeyStore, so the list keys / create key / encrypt→ciphertext /
    # decrypt→plaintext round-trip / generate-data-key playground works unchanged.
    # Key CRUD + real crypto round-trip is conformant, so gate to "full".
    "gcp.kms": {
        "mode": "full", "status": "conformant",
        "checks": {"passed": 36, "total": 36},
        "note": "GCP Cloud KMS — kms-crypto-view serves Cloud KMS via the same widget (lens=gcp) over the real kms_core.",
    },
    # Compute Engine reuses the SAME compute-terminal widget under lens=gcp; only the
    # manifest `api`/`connect` blocks differ (§15.2). It lists GCE instances, surfaces
    # the native SSH connect-info + .pem (the existing /api/gcp/compute/... endpoints),
    # and drives the SAME container-exec path EC2 uses for the in-console terminal, so
    # the list / connect / .pem / exec flow works unchanged. Backend conformant AND the
    # widget ships, so gate to "full".
    "gcp.compute": {
        "mode": "full", "status": "conformant",
        "checks": {"passed": 34, "total": 34},
        "note": "GCP Compute Engine — compute-terminal serves GCE via the same widget (lens=gcp).",
    },
    # Cloud Functions reuses the SAME serverless-invoke widget under lens=gcp; only the
    # manifest `api`/`connect` blocks differ (§15.2). It lists functions, shows config,
    # and INVOKES the REAL sandboxed handler (core/console_gcf runs the user code in a
    # subprocess, exactly like the Lambda runtime), returning the SAME response shape,
    # so the list / config / JSON-payload invoke → payload + status + logs / create
    # flow works unchanged. Backend runs the real handler AND the widget ships, so gate
    # to "full".
    "gcp.functions": {
        "mode": "full", "status": "conformant",
        "checks": {"passed": 27, "total": 27},
        "note": "GCP Cloud Functions — serverless-invoke serves Cloud Functions via the same widget (lens=gcp) over the real handler runtime.",
    },
    # GCP IAM mirrors the AWS `iam` entry: control-plane + policy surface on the
    # generic-control-plane view (no dedicated rich widget), so mode stays "generic"
    # and status "partial" — honest, never a false green.
    "gcp.iam": {
        "mode": "generic", "status": "partial",
        "checks": {"passed": 20, "total": 28},
        "note": "GCP IAM — control-plane + policy surface; rich generic-control-plane view (lens=gcp).",
    },
    # ── Azure lens (P4) ── the SAME object-browser widget serves Azure Blob; only
    # the manifest `api` block differs (§15.2). A "container" is the bucket and a
    # "blob" the object. Container/blob CRUD round-trips through the console facade,
    # so gate to "full".
    "azure.blob": {
        "mode": "full", "status": "conformant",
        "checks": {"passed": 12, "total": 12},
        "note": "Azure Blob Storage — object-browser serves Azure Blob via the same widget (lens=azure).",
    },
    # Azure SQL Database reuses the SAME sql-console widget under lens=azure; only the
    # manifest `api` block differs (§15.2). SQL runs against the same relay-safe SQL
    # engine the RDS Data API / Cloud SQL facades use, so gate to "full".
    "azure.sql": {
        "mode": "full", "status": "conformant",
        "checks": {"passed": 29, "total": 29},
        "note": "Azure SQL Database — sql-console serves Azure SQL via the same widget (lens=azure).",
    },
    # Cosmos DB (document DB) reuses the SAME nosql-item-viewer widget under lens=azure;
    # only the manifest `api` block differs (§15.2). A container is the "table", a
    # document the "item", and the required document `id` is surfaced as the partition
    # key so the key-query UX works unchanged. Container/document CRUD + key query
    # round-trips through the console facade, so gate to "full".
    "azure.cosmos": {
        "mode": "full", "status": "conformant",
        "checks": {"passed": 12, "total": 12},
        "note": "Azure Cosmos DB — nosql-item-viewer serves Cosmos via the same widget (lens=azure).",
    },
    # Service Bus reuses the SAME queue-topic-viewer widget under lens=azure; only the
    # manifest `api` block differs (§15.2). A "queue" is a Service Bus queue, the topic
    # fans out to attached subscriptions (an existing queue attached as the sub) — the
    # publish→fan-out+receive/peek path round-trips through the console facade, so gate
    # to "full".
    "azure.servicebus": {
        "mode": "full", "status": "conformant",
        "checks": {"passed": 11, "total": 11},
        "note": "Azure Service Bus — queue-topic-viewer serves Service Bus via the same widget (lens=azure).",
    },
    # Key Vault (secrets) reuses the SAME kv-secret-viewer widget under lens=azure; only
    # the manifest `api` block differs (§15.2). Secrets carry versions (newest =
    # current, prior = previous) and the value stays masked until a deliberate reveal.
    # Secret + version CRUD + masked-reveal round-trips through the console facade, so
    # gate to "full".
    "azure.keyvault_secrets": {
        "mode": "full", "status": "conformant",
        "checks": {"passed": 32, "total": 32},
        "note": "Azure Key Vault secrets — kv-secret-viewer serves Key Vault via the same widget (lens=azure).",
    },
}

# The status precedence for the coarse status-bar rollup pill.
_STATUS_RANK = {"conformant": 0, "partial": 1, "unknown": 2}


def service_signal(service_id: str) -> dict:
    """Per-service conformance signal (see module docstring for the shape). Unknown
    services degrade honestly to a `generic`/`unknown` signal — never a false green."""
    sig = _SIGNAL.get(service_id)
    if sig:
        return dict(sig)
    return {
        "mode": "generic", "status": "unknown",
        "checks": {"passed": 0, "total": 0},
        "note": "No conformance signal for this service — generic control-plane only.",
    }


def all_signals() -> dict:
    """The full per-service signal map (service_id -> signal)."""
    return {sid: dict(sig) for sid, sig in _SIGNAL.items()}


def rollup() -> dict:
    """A coarse workspace-level rollup for the status-bar pill: the WORST status
    across all services + a passed/total sum. Deterministic and offline."""
    worst = "conformant"
    passed = total = 0
    for sig in _SIGNAL.values():
        st = sig.get("status", "unknown")
        if _STATUS_RANK.get(st, 2) > _STATUS_RANK.get(worst, 2):
            worst = st
        c = sig.get("checks", {})
        passed += int(c.get("passed", 0))
        total += int(c.get("total", 0))
    label = {"conformant": "conformant", "partial": "partial", "unknown": "unknown"}[worst]
    return {
        "status": worst,
        "label": label,
        "checks": {"passed": passed, "total": total},
        "services": len(_SIGNAL),
    }


def summary() -> dict:
    """A flat workspace-level summary for the status-bar pill (§4). Aggregates over
    `_SIGNAL`: how many services are fully conformant, the summed check counts, and
    the WORST status across all services (the coarse pill colour/label driver).

    Shape (stable — the pill reads these keys directly):
        { services_total, services_full, checks_passed, checks_total, status }

    `status` is the worst per-service status ("conformant" > "partial" > "unknown"),
    so the pill only shows green when EVERY service is conformant — never a false
    green. Deterministic and offline; live-runner-ready (F5 swaps the backing feed)."""
    worst = "conformant"
    services_full = passed = total = 0
    for sig in _SIGNAL.values():
        if sig.get("mode") == "full":
            services_full += 1
        st = sig.get("status", "unknown")
        if _STATUS_RANK.get(st, 2) > _STATUS_RANK.get(worst, 2):
            worst = st
        c = sig.get("checks", {})
        passed += int(c.get("passed", 0))
        total += int(c.get("total", 0))
    return {
        "services_total": len(_SIGNAL),
        "services_full": services_full,
        "checks_passed": passed,
        "checks_total": total,
        "status": worst,
    }


def widget_modes() -> dict:
    """Map service_id -> widget `mode` (`full`/`degraded`/`generic`). This is what
    the capability manifest merges into `widgets` so the center-canvas gates on it.

    A per-widget override via env lets a demo force-degrade a service without code
    edits (e.g. VYOMI_CONSOLE_DEGRADE="rds,sqs")."""
    degraded = {
        s.strip() for s in os.environ.get("VYOMI_CONSOLE_DEGRADE", "").split(",") if s.strip()
    }
    out = {}
    for sid, sig in _SIGNAL.items():
        out[sid] = "degraded" if sid in degraded else sig.get("mode", "generic")
    return out
