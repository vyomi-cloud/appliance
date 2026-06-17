"""Backend-state rehydration on simulator startup.

State-survival audit per backend (as of v2.0.3):

  ✓ Persists natively via volume mount:
        cloudlearn-vault       — prod-mode file backend (KMS + secrets)
        cloudlearn-firestore   — REST-export on SIGTERM + import on boot
        vyomi-sql-pg           — real Postgres data dir
        vyomi-sql-mysql        — real MySQL data dir
        vyomi-gcs              — fake-gcs filesystem backend
        vyomi-minio            — S3 object bytes
        vyomi-dynamodb         — local sharedDb file
        vyomi-data             — simulator's own sqlite state DB
        cloudsim-data          — CloudSim Plus backbone state

  ✗ Emulator-level persistence is unreliable / unimplemented:
        cloudlearn-pubsub      — gcloud emulator's --data-dir writes only
                                 env.yaml (no topic WAL). Rehydration here
                                 would let the simulator re-declare topics
                                 + subscriptions on every boot from its own
                                 STATE — BUT this requires the simulator's
                                 GCP Pub/Sub endpoints to actually write
                                 topic/sub metadata to STATE (today they
                                 proxy-through). That STATE-write is queued
                                 for v2.1.0 alongside the schema-migration
                                 framework. The rehydrate_pubsub_topics()
                                 helper is shipped early so when STATE
                                 starts being populated, the recovery path
                                 already exists.
        cloudlearn-elasticmq   — same story: in-memory only, queues vanish
                                 on restart. Rehydration helper present;
                                 needs SQS proxy STATE-write in v2.1.0 to
                                 actually fire.

This runs as a FastAPI `@app.on_event("startup")` hook. Failures are
logged + swallowed — a single backend's failure to rehydrate must never
prevent the simulator from booting.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any
from urllib.parse import urlencode

import requests

log = logging.getLogger(__name__)

_EMQ_URL    = os.environ.get("CLOUDLEARN_ELASTICMQ_URL", "http://cloudlearn-elasticmq:9324")
_PUBSUB_URL = "http://" + os.environ.get(
    "CLOUDLEARN_PUBSUB_EMULATOR_HOST",
    os.environ.get("PUBSUB_EMULATOR_HOST", "cloudlearn-pubsub:8085"),
)


def _wait_for_elasticmq(timeout_s: float = 30.0) -> bool:
    """Poll ElasticMQ until it responds to ListQueues, or give up."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            r = requests.get(
                _EMQ_URL,
                params={"Action": "ListQueues", "Version": "2012-11-05"},
                timeout=2,
            )
            if r.status_code == 200:
                return True
        except requests.RequestException:
            pass
        time.sleep(1)
    return False


def _redeclare_sqs_queue(queue_name: str, attrs: dict[str, Any]) -> bool:
    """Idempotently declare a queue in ElasticMQ. Returns True on success."""
    params: dict[str, Any] = {
        "Action": "CreateQueue",
        "Version": "2012-11-05",
        "QueueName": queue_name,
    }
    # Translate the handful of attributes the simulator actually persists.
    i = 1
    for k_name, k_attr in (
        ("VisibilityTimeout",          "VisibilityTimeout"),
        ("MessageRetentionPeriod",     "MessageRetentionPeriod"),
        ("DelaySeconds",               "DelaySeconds"),
        ("MaximumMessageSize",         "MaximumMessageSize"),
        ("ReceiveMessageWaitTimeSeconds", "ReceiveMessageWaitTimeSeconds"),
    ):
        v = attrs.get(k_name) or attrs.get(k_attr) or attrs.get(k_name.lower())
        if v is None:
            continue
        params[f"Attribute.{i}.Name"] = k_attr
        params[f"Attribute.{i}.Value"] = str(v)
        i += 1
    try:
        r = requests.post(_EMQ_URL, data=params, timeout=5)
        # ElasticMQ returns 200 on success (and idempotently on already-exists
        # if attributes match). 400 means a real error.
        if r.status_code == 200:
            return True
        log.warning("elasticmq CreateQueue %s → HTTP %d: %s",
                    queue_name, r.status_code, r.text[:200])
        return False
    except requests.RequestException as e:
        log.warning("elasticmq CreateQueue %s failed: %s", queue_name, e)
        return False


def rehydrate_sqs_queues(state: dict) -> dict[str, int]:
    """Walk the simulator's persisted SQS state and re-declare every queue
    against ElasticMQ. Returns {"declared": n, "failed": m, "skipped": k}.

    `state` is the SimulationKernel state dict (the same dict the rest of
    the simulator mutates). The SQS section lives at:

        state.tenants.<tid>.spaces.<sid>.providers.aws.service_states.sqs.queues
    """
    declared = failed = skipped = 0

    # Gather all queues across all tenants × spaces. Each queue carries
    # its name + the attributes we care about.
    queues_to_declare: list[tuple[str, dict[str, Any]]] = []

    tenants = (state.get("tenants") or {}) if isinstance(state, dict) else {}
    for _tid, tenant in tenants.items():
        spaces = (tenant or {}).get("spaces", {}) or {}
        for _sid, space in spaces.items():
            providers = (space or {}).get("providers", {}) or {}
            aws = providers.get("aws") or {}
            sqs = ((aws.get("service_states") or {}).get("sqs") or {})
            for q in (sqs.get("queues") or {}).values():
                name = q.get("QueueName") or q.get("queue_name") or q.get("name")
                if not name:
                    skipped += 1
                    continue
                queues_to_declare.append((name, q))

    if not queues_to_declare:
        return {"declared": 0, "failed": 0, "skipped": 0}

    if not _wait_for_elasticmq(timeout_s=30):
        log.warning("ElasticMQ not reachable — skipping SQS rehydration "
                    "(%d queues will be re-declared on next user CreateQueue)",
                    len(queues_to_declare))
        return {"declared": 0, "failed": 0, "skipped": len(queues_to_declare)}

    for name, q in queues_to_declare:
        if _redeclare_sqs_queue(name, q):
            declared += 1
        else:
            failed += 1
    return {"declared": declared, "failed": failed, "skipped": skipped}


# ── Pub/Sub topics + subscriptions ────────────────────────────────────────

def _wait_for_pubsub(timeout_s: float = 30.0) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            r = requests.get(f"{_PUBSUB_URL}/v1/projects/cloudlearn/topics", timeout=2)
            if r.status_code == 200:
                return True
        except requests.RequestException:
            pass
        time.sleep(1)
    return False


def _redeclare_pubsub_topic(project: str, topic_name: str) -> bool:
    """Idempotently create topic. Pub/Sub emulator returns 200 on first
    create + 409 on already-exists; we treat both as success."""
    url = f"{_PUBSUB_URL}/v1/projects/{project}/topics/{topic_name}"
    try:
        r = requests.put(url, json={}, timeout=5,
                         headers={"Content-Type": "application/json"})
        if r.status_code in (200, 409):
            return True
        log.warning("pubsub PUT %s → HTTP %d: %s", url, r.status_code, r.text[:200])
        return False
    except requests.RequestException as e:
        log.warning("pubsub PUT %s failed: %s", url, e)
        return False


def _redeclare_pubsub_subscription(project: str, sub_name: str,
                                    topic_name: str, attrs: dict[str, Any]) -> bool:
    body: dict[str, Any] = {
        "topic": f"projects/{project}/topics/{topic_name}",
    }
    if "ackDeadlineSeconds" in attrs:
        body["ackDeadlineSeconds"] = int(attrs["ackDeadlineSeconds"])
    elif "ack_deadline_seconds" in attrs:
        body["ackDeadlineSeconds"] = int(attrs["ack_deadline_seconds"])
    url = f"{_PUBSUB_URL}/v1/projects/{project}/subscriptions/{sub_name}"
    try:
        r = requests.put(url, json=body, timeout=5,
                         headers={"Content-Type": "application/json"})
        if r.status_code in (200, 409):
            return True
        log.warning("pubsub PUT sub %s → HTTP %d: %s", url, r.status_code, r.text[:200])
        return False
    except requests.RequestException as e:
        log.warning("pubsub PUT sub %s failed: %s", url, e)
        return False


def rehydrate_pubsub_topics(state: dict) -> dict[str, int]:
    """Walk persisted GCP Pub/Sub state and re-declare topics + subscriptions.

    Pub/Sub state lives under:
        state.tenants.<tid>.spaces.<sid>.providers.gcp.service_states.pubsub
            .topics        — dict of topic_id → {name, project, ...}
            .subscriptions — dict of sub_id → {name, project, topic, ...}
    """
    declared_topics = declared_subs = failed = skipped = 0
    topics_to_declare: list[tuple[str, str]] = []
    subs_to_declare:   list[tuple[str, str, str, dict[str, Any]]] = []

    tenants = (state.get("tenants") or {}) if isinstance(state, dict) else {}
    for _tid, tenant in tenants.items():
        spaces = (tenant or {}).get("spaces", {}) or {}
        for _sid, space in spaces.items():
            providers = (space or {}).get("providers", {}) or {}
            gcp = providers.get("gcp") or {}
            ps = ((gcp.get("service_states") or {}).get("pubsub") or {})
            for t in (ps.get("topics") or {}).values():
                # Topic identity can live under several keys depending on
                # when it was created — be liberal in what we accept.
                name = (t.get("name") or t.get("topic_id") or "").split("/")[-1]
                project = t.get("project") or t.get("projectId") or "cloudlearn"
                if not name:
                    skipped += 1
                    continue
                topics_to_declare.append((project, name))
            for s in (ps.get("subscriptions") or {}).values():
                sname = (s.get("name") or s.get("subscription_id") or "").split("/")[-1]
                project = s.get("project") or s.get("projectId") or "cloudlearn"
                tref = (s.get("topic") or "").split("/")[-1]
                if not sname or not tref:
                    skipped += 1
                    continue
                subs_to_declare.append((project, sname, tref, s))

    if not topics_to_declare and not subs_to_declare:
        return {"topics_declared": 0, "subs_declared": 0, "failed": 0, "skipped": 0}

    if not _wait_for_pubsub(timeout_s=30):
        log.warning("Pub/Sub emulator not reachable — skipping rehydration "
                    "(%d topics / %d subs)",
                    len(topics_to_declare), len(subs_to_declare))
        return {"topics_declared": 0, "subs_declared": 0,
                "failed": 0,
                "skipped": len(topics_to_declare) + len(subs_to_declare)}

    for project, name in topics_to_declare:
        if _redeclare_pubsub_topic(project, name):
            declared_topics += 1
        else:
            failed += 1
    for project, sname, tref, s in subs_to_declare:
        if _redeclare_pubsub_subscription(project, sname, tref, s):
            declared_subs += 1
        else:
            failed += 1

    return {
        "topics_declared": declared_topics,
        "subs_declared":   declared_subs,
        "failed":          failed,
        "skipped":         skipped,
    }
