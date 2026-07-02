# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""MessagingStore — the data-plane seam for eventing / pub-sub (ADR-001).

The messaging protocol logic (SQS queues + visibility, SNS topics + fan-out) is
substrate-independent and lives in core/sqs_core.py + core/sns_core.py. THIS is
the seam they persist through — the in-memory pub/sub primitive, the WASM analogue
of Lite's NATS/ElasticMQ:

    Pro/Max : ElasticMQ (SQS) + a NATS-backed bus  (mirror)
    Nano    : InMemoryMessagingStore — pure in-WASM (Pyodide)
    tests   : InMemoryMessagingStore

The store owns the two state dicts the handlers read/write (queues + topics) and
a CLOCK — SQS visibility timeouts are timestamp-based, so a controllable clock
lets the same logic be deterministic in tests (advance time instead of sleeping)
and real in production. Nothing here imports fastapi / boto3 / socket / a NATS
client, so it loads under Pyodide.

State shapes (record shapes owned by the cores):
    queues : { queue_name -> queue }   (queue.messages is the message list)
    topics : { topic_arn  -> topic }   (topic.subscriptions is the sub list)
"""
from __future__ import annotations

from typing import Any

DEFAULT_ACCOUNT_ID = "123456789012"  # matches core.app_context.AWS_ACCOUNT_ID
REGION = "us-east-1"


class MessagingStore:
    """Base seam. In-memory by default; subclass to add a mirror / persistence."""

    def __init__(self, account_id: str = DEFAULT_ACCOUNT_ID) -> None:
        self.queues: dict[str, dict[str, Any]] = {}
        self.topics: dict[str, dict[str, Any]] = {}
        self.account_id = account_id
        self._clock: float | None = None  # None -> real wall clock

    # ── clock (so visibility timeouts are deterministic in tests) ──────
    def now(self) -> float:
        if self._clock is not None:
            return self._clock
        import time
        return time.time()

    def set_time(self, t: float) -> None:
        self._clock = t

    def advance(self, seconds: float) -> None:
        self._clock = self.now() + seconds

    # ── queue accessors ───────────────────────────────────────────────
    def queue_exists(self, name: str) -> bool:
        return name in self.queues

    def get_queue(self, name: str) -> dict | None:
        q = self.queues.get(name)
        return q if isinstance(q, dict) else None

    def get_queue_by_arn(self, arn: str) -> dict | None:
        for q in self.queues.values():
            if q.get("queue_arn") == arn:
                return q
        return None

    def put_queue(self, name: str, queue: dict) -> None:
        self.queues[name] = queue

    def drop_queue(self, name: str) -> None:
        self.queues.pop(name, None)

    def queue_names(self) -> list[str]:
        return sorted(self.queues)

    # ── topic accessors ───────────────────────────────────────────────
    def get_topic(self, arn: str) -> dict | None:
        t = self.topics.get(arn)
        return t if isinstance(t, dict) else None

    def put_topic(self, arn: str, topic: dict) -> None:
        self.topics[arn] = topic

    def drop_topic(self, arn: str) -> None:
        self.topics.pop(arn, None)

    def topic_arns(self) -> list[str]:
        return sorted(self.topics)

    # ── optional hooks (no-ops in the base) ───────────────────────────
    def persist(self) -> None:
        """Flush state to durable storage (appliance ctx in Pro/Max, IDB in Nano)."""

    def mirror(self, kind: str, key: str, record: dict | None) -> None:
        """Best-effort write-through/delete in an external backend (ElasticMQ/NATS)."""


class InMemoryMessagingStore(MessagingStore):
    """The Nano / test substrate: pure in-memory, zero external deps."""
